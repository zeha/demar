#!/usr/bin/env python3
import argparse
import datetime
import multiprocessing
import os
import pathlib
import subprocess
import sys
import random
import time

import yaml
from debian import deb822


MAX_REPICK_COUNT = 20  # number of packages to re-pick every run
MIN_REPICK_DELAY = 3 * 86400  # 3 days ago


def get_arch() -> str:
    p = subprocess.run(["dpkg", "--print-architecture"], stdout=subprocess.PIPE)
    return p.stdout.decode().strip()


MY_ARCHITECTURE = get_arch()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild a list of Debian source packages")
    parser.add_argument("pkg_list", type=argparse.FileType(mode="r"))
    parser.add_argument("job_name")
    parser.add_argument(
        "--extra-changes", dest="extra_changes", type=argparse.FileType(mode="r"), action="append", default=[]
    )
    return parser.parse_args()


def get_extra_pkgs(fp) -> list[str]:
    extra_pkgs = []
    print("Reading extra files from changes:", fp.name)
    changes = deb822.Changes(fp)
    for file_meta in changes["Files"]:
        if not file_meta["name"].endswith(".deb"):
            continue
        extra_pkg = f"{pathlib.Path(fp.name).parent}/{file_meta['name']}"
        if not pathlib.Path(extra_pkg).exists():
            print("E: extra package from changes does not exist:", extra_pkg)
            sys.exit(1)
        extra_pkgs.append(extra_pkg)
    return extra_pkgs


def read_skip_file(filename: str):
    file = pathlib.Path(__file__).parent / filename
    with file.open("r") as fp:
        skip_reasons = [line.split("#", 1) for line in fp.read().strip().splitlines()]
        return {k.strip(): v.strip() for (k, v) in skip_reasons}


def read_fail_file(job_dir: pathlib.Path) -> dict[str, str]:
    file = job_dir / "fail"
    if not file.exists():
        return {}
    with file.open("r") as fp:
        fails = [line.split(" ", maxsplit=2) for line in fp.read().strip().splitlines()]
        return {fail[1]: fail[2] for fail in fails}


def eval_status(build_dir: pathlib.Path, buildlog_dir: pathlib.Path, skip_reasons, srcpkg: str) -> dict | None:
    if "_" in srcpkg:
        srcpkg_name = srcpkg.split("_")[0]
        srcpkg_version = srcpkg.split("_", 1)[1]
    else:
        srcpkg_name = srcpkg
        srcpkg_version = ""

    binpkg_version = srcpkg_version
    if ":" in binpkg_version:
        binpkg_version = binpkg_version.split(":", 1)[1]

    buildinfo_file = build_dir / f"{srcpkg_name}_{binpkg_version}_{MY_ARCHITECTURE}.buildinfo"

    if buildinfo_file.exists():
        print("Skipping", srcpkg, "buildinfo exists")
        return {"status": "already_built", "last_attempt": buildinfo_file.stat().st_mtime}

    if broken_detail := skip_reasons.get(srcpkg_name):
        print("Skipping", srcpkg, f"known broken: {broken_detail}")
        return {"status": "known_broken", "detail": broken_detail}

    buildlog_file = buildlog_dir / srcpkg
    if buildlog_file.exists():
        print("Skipping", srcpkg, "buildlog exists, assuming old ftbfs")
        return {"status": "old_ftbfs", "last_attempt": buildlog_file.stat().st_mtime}

    return {"status": "needs_build"}


def wrap_result(srcpkg: str, result: dict) -> dict:
    return {srcpkg: {"package": srcpkg} | result}


def main():
    args = parse_args()
    job_name = args.job_name
    job_dir = pathlib.Path(f"./{job_name}").absolute()
    job_dir.mkdir(exist_ok=True)

    build_dir = (job_dir / "target").absolute()
    build_dir.mkdir(exist_ok=True)
    print("Writing build files to", build_dir)

    buildlog_dir = (job_dir / "buildlogs").absolute()
    buildlog_dir.mkdir(exist_ok=True)
    print("Writing buildlogs to", buildlog_dir)

    skip_reasons = read_skip_file("skip_reasons")

    srcpkgs = [line.strip() for line in args.pkg_list.readlines()]
    srcpkg_status = {}
    for srcpkg in srcpkgs:
        srcpkg_status[srcpkg] = eval_status(build_dir, buildlog_dir, skip_reasons, srcpkg)

    now = time.time()
    max_last_attempt = now - MIN_REPICK_DELAY
    picked = []
    eligible_repick = []
    for srcpkg, status in srcpkg_status.items():
        if status["status"] == "needs_build":
            picked.append(srcpkg)
        elif status.get("last_attempt", now) < max_last_attempt:
            eligible_repick.append(srcpkg)

    count_repick_possible = MAX_REPICK_COUNT - len(picked)
    if count_repick_possible > 0:
        random.shuffle(eligible_repick)
        eligible_repick = eligible_repick[0:count_repick_possible]
        print("Repicking", " ".join(eligible_repick))
        picked += eligible_repick

    extra_pkgs = []
    for extra_fp in args.extra_changes:
        extra_pkgs.extend(get_extra_pkgs(extra_fp))
    print("Adding extra packages:", " ".join(extra_pkgs))

    max_parallel = int(multiprocessing.cpu_count() * 1.6)
    with multiprocessing.Pool(max_parallel) as pool:
        results = pool.map(
            do_build_one,
            [(srcpkg, str(build_dir), str(buildlog_dir), extra_pkgs) for srcpkg in picked],
            1,
        )

    with (job_dir / f"results{datetime.datetime.now().isoformat().replace(':', '_')}.yaml").open("w") as fp:
        yaml.safe_dump_all(results, fp)


def do_build_one(workitem) -> dict:
    srcpkg, build_dir, buildlog_dir, extra_pkgs = workitem
    result = build_one(srcpkg, pathlib.Path(build_dir), pathlib.Path(buildlog_dir), extra_pkgs)
    return wrap_result(srcpkg, result)


def _create_subprocess_env_block() -> dict:
    env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LC_ALL": "C.UTF-8",
        "SHELL": "/bin/sh",
        "USER": os.getenv("USER"),
        "LOGNAME": os.getenv("LOGNAME"),
        "HOME": os.getenv("HOME"),
        "DEB_BUILD_OPTIONS": "nocheck",
    }
    env = {k: v for (k, v) in env.items() if k and v}
    return env


def build_one(srcpkg: str, build_dir: pathlib.Path, buildlog_dir: pathlib.Path, extra_pkgs) -> dict:
    build_dir.cwd()

    print(datetime.datetime.now().isoformat(), "Building", srcpkg, "...", f"(worker={os.getpid()})", flush=True)
    args = [
        "sbuild",
        "--dist=unstable",
        "--no-apt-upgrade",
        "--no-apt-distupgrade",
        "--nolog",
        "--no-run-piuparts",
        "--no-run-lintian",
        f"--build-dir={build_dir}",
        srcpkg,
    ]
    for extra_pkg in extra_pkgs:
        args.append(f"--extra-package={extra_pkg}")

    buildlog_file = buildlog_dir / srcpkg
    new_buildlog_file = buildlog_file.with_name(f"{buildlog_file.name}.new")
    with new_buildlog_file.open("w") as out_fp:
        proc = subprocess.run(
            args,
            stdout=out_fp,
            stderr=subprocess.PIPE,
            env=_create_subprocess_env_block(),
        )

    result = {"status": "unknown"}
    if proc.returncode != 0:
        result["status"] = "sbuild_failed"
        result["detail"] = {"returncode": proc.returncode}
        result["stderr"] = proc.stderr.decode().strip()
        print("FAIL", srcpkg, f"(sbuild exited with {proc.returncode})", proc.stderr.decode().strip())
    else:
        result["status"] = "built"

    if buildlog_file.exists():
        buildlog_file.replace(buildlog_file.with_name(f"{buildlog_file.name}.old"))
    new_buildlog_file.replace(buildlog_file)

    return result


if __name__ == "__main__":
    main()
