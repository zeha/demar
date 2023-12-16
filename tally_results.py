#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import re
import httpx
import yaml
import datetime
import time

CACHE_DIR = Path("~/.cache/demar").expanduser()

BUGLIST_URL = r"https://udd.debian.org/bugs/?release=na&merged=ign&done=ign&fnewerval=7&flastmodval=7&fusertag=only&fusertagtag=dep17m2&fusertaguser=helmutg%40debian.org&allbugs=1&cseverity=1&ctags=1&caffected=1&clastupload=1&format=json"

META = {
    "WARNING": "The tool producing this list is not very smart. Human discretion is required.",
    "INFO-ftbfs": "ftbfs here can also mean the package was too large to rebuild or explicitly skipped.",
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


def get_bugs():
    cache_file = CACHE_DIR / "bugs"
    if not cache_file.exists() or (time.time() - cache_file.stat().st_mtime) > 3600:
        print("Downloading bugs list")
        with cache_file.open("wb") as fp:
            fp.write(httpx.get(BUGLIST_URL, headers={"User-Agent": "demar/tally_results (zeha@debian.org)"}).read())

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

        # if src.startswith("src:"):
        #     src = src[4:]
        bugs.setdefault(src, [])
        bugs[src].append(detail)

        pkg_meta.setdefault(src, {})
        if v := bug.get("lastupload"):
            pkg_meta[src]["last_upload"] = v

    return pkg_meta, bugs


def get_build_results(rebuild_list: str, buildlogs_dir: str) -> list[dict]:
    results = []
    seen_pkgs = set()
    for path in Path(buildlogs_dir).glob("*"):
        seen_pkgs.add(path.name)
        (src_name, src_version) = path.name.split("_", maxsplit=1)
        if src_name == "base-files":
            continue

        print(path)
        found_files = set()
        count = 0
        in_summary = False
        build_failed = False
        with path.open("rb") as fp:
            for line in fp:
                if in_summary:
                    if line.startswith(b"Fail-Stage"):
                        build_failed = True
                        break

                else:
                    if line.startswith(b"| Summary"):
                        in_summary = True

                    if count > 1000:
                        continue
                    if m := re.search(rb"[0-9]:[0-9][0-9] \./(.*)$", line):
                        found_file = m.group(1)
                        if found_file[0:3] not in (b"", b"usr", b"etc", b"var", b"boot"):
                            found_files.add(found_file.decode())
                            count += 1
                    if count > 1000:
                        found_files.add("MORE_THAN_1000")

        if found_files or build_failed:
            r = {
                "version": src_version,
                "source": src_name,
                "files": list(sorted(list(found_files))),
                "ftbfs": build_failed,
            }
            results.append(r)

    with Path(rebuild_list).open("r") as fp:
        for line in fp:
            line = line.strip()
            if line in seen_pkgs:
                continue

            (src_name, src_version) = line.split("_", maxsplit=1)
            r = {
                "version": src_version,
                "source": src_name,
                "files": [],
                "ftbfs": True,
                "ftbfs_reason": "unknown",
            }
            results.append(r)

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="tally build results against open bugs")
    parser.add_argument("-o", dest="output", required=True)
    parser.add_argument("--buildlogs-dir", dest="buildlogs_dir", required=True)
    parser.add_argument("--rebuild-list", dest="rebuild_list", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    CACHE_DIR.mkdir(exist_ok=True)

    work_todo = {}
    today = datetime.date.today()

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

        guessed_status = "needs-inspection"

        for bug in pkg_todo["bugs"]:
            if "patch" in bug["tags"]:
                guessed_status = "patch-in-bts"
                if "moreinfo" in bug["tags"]:
                    guessed_status = "blocked-patch-in-bts"
                elif "pending" in bug["tags"]:
                    guessed_status = "patch-marked-pending"
                elif today - datetime.date.fromisoformat(bug["last_modified"]) > NMU_PATCH_AGE:
                    guessed_status = "lingering-patch-in-bts-maybe-ping-nmu"

                break

            guessed_status = "bug-filed"

        pkg_todo["guessed_status"] = guessed_status

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

        if build_result["ftbfs"]:
            groups.add("ftbfs")

        if pkg_todo["essential"]:
            groups.add("essential")

        pkg_todo["groups"] = list(groups)

        stats["guessed_status"].setdefault(guessed_status, 0)
        stats["guessed_status"][guessed_status] += 1

        for g in groups:
            stats["groups"].setdefault(g, 0)
            stats["groups"][g] += 1

        stats["total_packages"] += 1

        if not build_result["files"]:
            del build_result["files"]

        if not build_result["ftbfs"]:
            del build_result["ftbfs"]

        pkg_todo["build_result"] = build_result
        work_todo[src] = pkg_todo

    meta = {
        "rebuild_timestamp": datetime.datetime.fromtimestamp(Path(args.rebuild_list).stat().st_mtime).isoformat(),
        "last_update": datetime.datetime.now().isoformat(),
    } | META

    with Path(args.output).open("w") as fp:
        yaml.safe_dump_all([{"___meta": meta}, {"___stats": stats}, work_todo], fp)


if __name__ == "__main__":
    main()
