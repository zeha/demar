#!/usr/bin/env python3
import argparse
import datetime
import json
import re
import time
from pathlib import Path

import httpx
import psycopg
import psycopg.rows
import yaml

CACHE_DIR = Path("~/.cache/demar").expanduser()

PG_UDD_URL = "postgresql://udd-mirror:udd-mirror@udd-mirror.debian.net/udd?client_encoding=utf-8"

BUGLIST_URL = r"https://udd.debian.org/bugs/?release=na&merged=ign&fnewerval=7&flastmodval=7&fusertag=only&fusertagtag=dep17m2&fusertaguser=helmutg%40debian.org&allbugs=1&cseverity=1&ctags=1&caffected=1&clastupload=1&format=json"

META = {
    "WARNING": "The tool producing this list is not very smart. Human discretion is required.",
}

NMU_PATCH_AGE = datetime.timedelta(days=10)

ESSENTIAL = {
    "base-files",
    "bash",
    "coreutils",
    "dash",
    "debianutils",
    "dpkg",
    "grep",
    "gzip",
    "hostname",
    "sed",
    "shadow",
    "sysvinit",
    "tar",
}

ONE_UPLOAD = {
    "bash", "base-files", "coreutils", "dash", "glibc", "util-linux",
}

def read_skip_file(filename: str):
    file = Path(__file__).parent / filename
    print("Reading skip file", file)
    with file.open("r") as fp:
        skip_reasons = [line.split("#", 1) for line in fp.read().strip().splitlines()]
        return {k.strip(): v.strip() for (k, v) in skip_reasons}


def query_bugs_http():
    print("Downloading bugs list")
    return httpx.get(BUGLIST_URL, headers={"User-Agent": "demar/tally_results (zeha@debian.org)"}).read().json()


def query_bugs_udd():
    sql = """
    with sources_uploads as (
        select max(date) AS lastupload, s1.source
        from sources s1, upload_history uh
        where s1.source = uh.source
        and s1.version = uh.version
        and s1.release='sid'
        group by s1.source
    ),
    bugs_usertagged as (
        select id
        from bugs_usertags
        where email='helmutg@debian.org' and tag like 'dep17%'
    )
    select bugs.id, bugs.source, bugs.severity, bugs.title,
        bugs.last_modified::text,
        bugs.status,
        bugs.affects_testing, bugs.affects_unstable, bugs.affects_experimental,
        sources_uploads.lastupload::text,
        coalesce((select array_agg(bugs_tags.tag order by tag) from bugs_tags where bugs_tags.id = bugs.id), array[]::text[]) as tags,
        (select max(version) from bugs_found_in where bugs_found_in.id = bugs.id) as max_found_in
    from bugs_usertagged
    join bugs on bugs.id = bugs_usertagged.id
    join sources_uploads on bugs.source = sources_uploads.source
    where
        bugs.id not in (select id from bugs_merged_with where id > merged_with)
    """
    with psycopg.connect(PG_UDD_URL, row_factory=psycopg.rows.dict_row) as conn:
        # Open a cursor to perform database operations
        with conn.cursor() as cursor:
            return cursor.execute(sql).fetchall()


def get_bugs():
    cache_file = CACHE_DIR / "bugs"
    if not cache_file.exists() or (time.time() - cache_file.stat().st_mtime) > 3600:
        print("Downloading bugs list")
        result = json.dumps(query_bugs_udd())
        with cache_file.open("w") as fp:
            fp.write(result)

    print("Using bugs cache", cache_file.absolute(), cache_file.stat().st_mtime)
    with cache_file.open("rb") as fp:
        return json.load(fp)


def get_transformed_bugs() -> tuple[dict[str, dict], dict[str, list[dict]]]:
    bugs = {}
    pkg_meta = {}
    for bug in get_bugs():
        src = bug["source"]
        detail = {
            "id": bug["id"],
            "title": bug["title"],
            "source": src,
            "status": bug["status"],
            "last_modified": bug["last_modified"],
            "tags": bug.get("tags", []),
        }

        for k in ("affects_experimental", "affects_testing", "affects_unstable"):
            if v := bug.get(k):
                detail[k] = v

        if bug["status"] == "done" and not bug.get("affects_testing", False) and not bug.get("affects_unstable", False):
            continue

        # if src.startswith("src:"):
        #     src = src[4:]
        bugs.setdefault(src, [])
        bugs[src].append(detail)

        pkg_meta.setdefault(src, {})
        if v := bug.get("lastupload"):
            pkg_meta[src]["last_upload"] = v

    return pkg_meta, bugs


def get_build_results(rebuild_list: str, buildlogs_dir: str) -> list[dict]:
    known_broken = read_skip_file("known_broken")
    skip_reasons = read_skip_file("skip_reasons")

    with Path(rebuild_list).open("r") as fp:
        wanted_pkgs = set(fp.read().strip().splitlines())

    results = []
    seen_pkgs = set()
    for path in Path(buildlogs_dir).glob("*"):
        if path.name.endswith(".old"):
            continue
        if path.name not in wanted_pkgs:
            print("Ignoring buildlog", path)
            continue

        (src_name, src_version) = path.name.split("_", maxsplit=1)
        if src_name == "base-files":
            continue

        print("Reading buildlog", path)
        found_files = set()
        count = 0
        in_summary = False
        built = False  # did sbuild complete (success or failure)
        build_fail_stage = None
        source_arch = None
        with path.open("rb") as fp:
            for line in fp:
                if in_summary:
                    if line.startswith(b"Fail-Stage:"):
                        build_fail_stage = line.split(b" ", maxsplit=1)[1].decode().strip()
                        continue

                else:
                    if line.startswith(b"| Summary"):
                        in_summary = True
                        built = True
                    if source_arch is None and line.startswith(b"Architecture:"):
                        source_arch = line.split(b": ", maxsplit=1)[1].decode().strip().split()

                    if count > 1000:
                        continue
                    if m := re.search(rb"[0-9]:[0-9][0-9] \./(.*)$", line):
                        found_file = m.group(1)
                        if found_file[0:3] not in (b"", b"usr", b"etc", b"var", b"boot"):
                            found_files.add(found_file.decode())
                            count += 1
                    if count > 1000:
                        found_files.add("MORE_THAN_1000")

        if built:
            seen_pkgs.add(path.name)

            r = {
                "version": src_version,
                "source": src_name,
                "built": built,
                "architecture": source_arch,
                "files": list(sorted(list(found_files))),
            }

            if build_fail_stage is not None:
                ftbfs_reason = known_broken.get(src_name)
                if ftbfs_reason:
                    ftbfs_reason = f"maybe-known-ftbfs {ftbfs_reason}"
                elif build_fail_stage:
                    ftbfs_reason = f"sbuild-failed-in-stage {build_fail_stage}"
                else:
                    ftbfs_reason = "unknown"
                r["ftbfs"] = True
                r["ftbfs_reason"] = ftbfs_reason

            results.append(r)

    for pkg in wanted_pkgs - seen_pkgs:
        (src_name, src_version) = pkg.split("_", maxsplit=1)
        r = {
            "version": src_version,
            "source": src_name,
            "files": [],
            "built": False,
        }

        skip_reason = skip_reasons.get(src_name)
        if skip_reason:
            r["build_skip_reason"] = skip_reason
        else:
            ftbfs_reason = known_broken.get(src_name)
            if ftbfs_reason:
                build_problem = f"known-ftbfs {ftbfs_reason}"
            else:
                build_problem = "unknown, no build result found"
            r["build_problem"] = build_problem

        results.append(r)

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="tally build results against open bugs")
    parser.add_argument("-o", dest="output", required=True)
    parser.add_argument("--buildlogs-dir", dest="buildlogs_dir", required=True)
    parser.add_argument("--rebuild-list", dest="rebuild_list", required=True)
    parser.add_argument("--output-need-rebuild", dest="output_need_rebuild")
    return parser.parse_args()


def main():
    args = parse_args()
    CACHE_DIR.mkdir(exist_ok=True)

    work_todo = {}
    need_rebuild = {}
    today = datetime.datetime.today()

    print("Reading bugs")
    pkg_meta, bugs = get_transformed_bugs()
    print("Reading build logs")

    stats = {"total_packages": 0, "groups": {}, "guessed_status": {}}

    for build_result in get_build_results(args.rebuild_list, args.buildlogs_dir):
        src = build_result["source"]
        pkg_todo = pkg_meta.get(src, {})
        pkg_todo["bugs"] = bugs.get(src, [])
        del build_result["source"]
        pkg_todo["essential"] = src in ESSENTIAL
        just_need_rebuild = False

        groups = set()

        if build_result["files"]:
            for file in build_result["files"]:
                if " -> " in file:
                    groups.add("symlink")

                if file.startswith("lib/debian-installer"):
                    groups.add("d-i")

                if file.startswith("lib/security") or file.startswith("lib/x86_64-linux-gnu/security"):
                    groups.add("pam")
                    continue

                if file.startswith("lib/firmware"):
                    groups.add("firmware")
                    continue

                if file.startswith("lib/udev"):
                    groups.add("udev")
                    continue

                if file.startswith("lib/systemd"):
                    groups.add("systemd")
                    continue

                if file.startswith("bin/") and file[-1] != "/":
                    groups.add("bin")
                    continue

                if file.startswith("sbin/") and file[-1] != "/":
                    groups.add("sbin")
                    continue

                if file.startswith("lib/") and file[-1] != "/":
                    groups.add("lib-other")
                    continue

            # done with exclusives

            if all(file.endswith("/") for file in build_result["files"]):
                groups.add("empty-dirs")

            if len(groups) > 1:
                groups.add("multiple")

            if all(file.startswith("bin/") for file in build_result["files"]):
                groups.add("just-bin")
            if all(file.startswith("sbin/") for file in build_result["files"]):
                groups.add("just-sbin")

            if len(groups) == 0:
                groups.add("UNCATEGORIZED")

        if build_result.get("ftbfs", False):
            groups.add("ftbfs")
        if "ftbfs" in build_result.get("build_problem", ""):
            groups.add("ftbfs")

        if pkg_todo["essential"]:
            groups.add("essential")

        pkg_todo["groups"] = list(sorted(list(groups)))

        guessed_status = None
        for bug in pkg_todo["bugs"]:
            if "patch" in bug["tags"]:
                guessed_status = "patch-in-bts"
                if "moreinfo" in bug["tags"]:
                    guessed_status = "blocked-patch-in-bts"
                elif "pending" in bug["tags"]:
                    guessed_status = "patch-marked-pending"
                elif today - datetime.datetime.fromisoformat(bug["last_modified"]) > NMU_PATCH_AGE:
                    guessed_status = "lingering-patch-in-bts-maybe-ping-nmu"

                break

            guessed_status = "bug-filed"

        if (
            guessed_status is None
            and build_result["built"]
            and not build_result.get("ftbfs", False)
            and not build_result.get("files", [])
        ):
            just_need_rebuild = True
            if "all" in build_result["architecture"]:
                guessed_status = "needs-no-change-upload"
            else:
                guessed_status = "needs-binnmu"

        if guessed_status is None:
            guessed_status = "needs-inspection"

        if "essential" in groups:
            guessed_status = "essential-move-at-end"

        if src in ONE_UPLOAD:
            guessed_status = "essential-move-in-one-upload-by-helmut"

        pkg_todo["guessed_status"] = guessed_status

        stats["guessed_status"].setdefault(guessed_status, 0)
        stats["guessed_status"][guessed_status] += 1

        for g in groups:
            stats["groups"].setdefault(g, 0)
            stats["groups"][g] += 1

        stats["total_packages"] += 1

        if not build_result["files"]:
            del build_result["files"]

        pkg_todo["build_result"] = build_result

        if just_need_rebuild:
            need_rebuild[src] = pkg_todo
        else:
            work_todo[src] = pkg_todo

    meta = {
        "rebuild_timestamp": datetime.datetime.fromtimestamp(Path(args.rebuild_list).stat().st_mtime).isoformat(),
        "last_update": datetime.datetime.now().isoformat(),
    } | META

    with Path(args.output).open("w") as fp:
        yaml.safe_dump_all([{"___meta": meta}, {"___stats": stats}, work_todo], fp)

    if args.output_need_rebuild:
        with Path(args.output_need_rebuild).open("w") as fp:
            yaml.safe_dump_all([need_rebuild], fp)


if __name__ == "__main__":
    main()
