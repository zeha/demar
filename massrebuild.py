#!/usr/bin/env python3
import pathlib
import subprocess
import datetime
import sys
from debian import deb822
import multiprocessing
import yaml


def main():
    pkg_list_file = sys.argv[1]
    changes_file = pathlib.Path(sys.argv[2]).absolute()
    build_dir = pathlib.Path(f"./build-{datetime.datetime.now().isoformat().replace(':', '-')}").absolute()
    buildlog_dir = (build_dir / "buildlogs").absolute()
    print("Writing build files to", buildlog_dir)
    build_dir.mkdir()
    print("Writing buildlogs to", buildlog_dir)
    buildlog_dir.mkdir()

    with open(pkg_list_file, "r") as fp:
        srcpkgs = fp.readlines()
        srcpkgs = [l.strip() for l in srcpkgs]

    # Files:
    # f0f6b108ae3ce47dda7cd839075337c3 345020 debug optional libnss-myhostname-dbgsym_255~rc3-2.1_amd64.deb
    # 23688c455a80d9c1ffe1dc2c0eefaf33 95496 admin optional libnss-myhostname_255~rc3-2.1_amd64.deb

    extra_pkgs = []
    with open(changes_file, "r") as fp:
        changes = deb822.Changes(fp)
        for file_meta in changes["Files"]:
            extra_pkgs.append(f"{changes_file.parent}/{file_meta['name']}")
    print("Adding extra packages:", " ".join(extra_pkgs))

    max_parallel = int(multiprocessing.cpu_count() * 1.6)
    with multiprocessing.Pool(max_parallel) as pool:
        results = pool.map(
            do_build_one, [(srcpkg, str(build_dir), str(buildlog_dir), extra_pkgs) for srcpkg in srcpkgs]
        )

    with (build_dir / "results.yaml").open("w") as fp:
        yaml.safe_dump_all(results, fp)
        # for src_index, srcpkg in enumerate(srcpkgs):
        #    progress_info = f"{src_index}/{len(srcpkgs)}"


def do_build_one(workitem):
    srcpkg, build_dir, buildlog_dir, extra_pkgs = workitem
    return build_one(srcpkg, pathlib.Path(build_dir), pathlib.Path(buildlog_dir), extra_pkgs)


def build_one(srcpkg, build_dir, buildlog_dir, extra_pkgs):
    build_dir.cwd()

    print(datetime.datetime.now().isoformat(), "Building", srcpkg, "...")
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
        result = subprocess.run(args, stdout=out_fp)
    if result.returncode != 0:
        print("FAIL", srcpkg)

    return {srcpkg: {"package": srcpkg, "result": result.returncode}}


if __name__ == "__main__":
    main()
