#!/usr/bin/env python3
import datetime
import multiprocessing
import os
import pathlib
import subprocess
import sys

import yaml
from debian import deb822


def get_arch() -> str:
    p = subprocess.run(["dpkg", "--print-architecture"], stdout=subprocess.PIPE)
    return p.stdout.decode().strip()


MY_ARCHITECTURE = get_arch()


def main():
    pkg_list_file = sys.argv[1]
    changes_file = pathlib.Path(sys.argv[2]).absolute()
    job_name = sys.argv[3]
    job_dir = pathlib.Path(f"./{job_name}").absolute()
    job_dir.mkdir(exist_ok=True)

    build_dir = (job_dir / "target").absolute()
    build_dir.mkdir(exist_ok=True)
    print("Writing build files to", build_dir)

    buildlog_dir = (job_dir / "buildlogs").absolute()
    buildlog_dir.mkdir(exist_ok=True)
    print("Writing buildlogs to", buildlog_dir)

    with open(pkg_list_file, "r") as fp:
        srcpkgs = [line.strip() for line in fp.readlines()]

    with (pathlib.Path(__file__).parent / "known_broken").open("r") as fp:
        known_broken = [line.split("#", 1) for line in fp.readlines()]
        known_broken = {k.strip(): v.strip() for (k, v) in known_broken}

    extra_pkgs = []
    with open(changes_file, "r") as fp:
        changes = deb822.Changes(fp)
        for file_meta in changes["Files"]:
            extra_pkg = f"{changes_file.parent}/{file_meta['name']}"
            if not pathlib.Path(extra_pkg).exists():
                print("E: extra package from changes does not exist:", extra_pkg)
                sys.exit(1)
            extra_pkgs.append(extra_pkg)
    print("Adding extra packages:", " ".join(extra_pkgs))

    max_parallel = int(multiprocessing.cpu_count() * 1.6)
    with multiprocessing.Pool(max_parallel) as pool:
        results = pool.map(
            do_build_one,
            [(srcpkg, str(build_dir), str(buildlog_dir), extra_pkgs, known_broken) for srcpkg in srcpkgs],
            1,
        )

    with (job_dir / f"results{datetime.datetime.now().isoformat().replace(':', '_')}.yaml").open("w") as fp:
        yaml.safe_dump_all(results, fp)


def do_build_one(workitem) -> dict:
    srcpkg, build_dir, buildlog_dir, extra_pkgs, known_broken = workitem
    result = build_one(srcpkg, pathlib.Path(build_dir), pathlib.Path(buildlog_dir), extra_pkgs, known_broken)
    return {srcpkg: {"package": srcpkg} | result}


def build_one(srcpkg, build_dir, buildlog_dir, extra_pkgs, known_broken: dict) -> dict:
    build_dir.cwd()

    if (build_dir / f"{srcpkg}_{MY_ARCHITECTURE}.buildinfo").exists():
        print("Skipping", srcpkg, "(buildinfo already exists)")
        return {"status": "already_built"}

    if broken_detail := known_broken.get(srcpkg.split("_")[0]):
        print("Skipping", srcpkg, "(known broken)")
        return {"status": "known_broken", "detail": broken_detail}

    print(datetime.datetime.now().isoformat(), "Building", srcpkg, "...", f"(worker={os.getpid()})")
    args = [
        "sbuild",
        "--dist=unstable",
        "--nolog",
        "--no-run-piuparts",
        "--no-run-lintian",
        f"--build-dir={build_dir}",
        srcpkg,
    ]
    for extra_pkg in extra_pkgs:
        args.append(f"--extra-package={extra_pkg}")
    #    print("   ", args)
    buildlog_file = buildlog_dir / srcpkg
    with buildlog_file.open("w") as out_fp:
        proc = subprocess.run(args, stdout=out_fp, stderr=subprocess.PIPE)

    result = {"status": "unknown"}
    if proc.returncode != 0:
        result["status"] = "sbuild_failed"
        result["detail"] = {"returncode": proc.returncode}
        result["stderr"] = proc.stderr.decode().strip()
        print("FAIL", srcpkg, f"(sbuild exited with {proc.returncode})", proc.stderr.decode().strip())

    return result


if __name__ == "__main__":
    main()
