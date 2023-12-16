#!/usr/bin/env python3
import argparse
import gzip
import pathlib
import sys

from debian import deb822
from debian.debian_support import version_compare

ARCHS = ["all", "arm64", "amd64"]
COMPONENTS = ["main", "contrib", "non-free", "non-free-firmware"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("filename", type=argparse.FileType(mode="r"))
    return parser.parse_args()


def main():
    mirror = "/srv/debian-mirror/mirror"
    source_pkg_versions = {}

    args = parse_args()
    unversioned_srcs = set([line.strip() for line in args.filename.read().strip().splitlines() if line])

    for component in COMPONENTS:
        for arch in ARCHS:
            pkglist_file = pathlib.Path(f"{mirror}/dists/sid/{component}/binary-{arch}/Packages.gz")
            with gzip.open(pkglist_file, "rt") as pkglist:
                for pkg in deb822.Packages.iter_paragraphs(pkglist):
                    source_name = pkg.source
                    if source_name not in unversioned_srcs:
                        continue
                    source_version = pkg.source_version
                    other_ver = source_pkg_versions.get(source_name)
                    if other_ver and version_compare(other_ver, source_version) >= 0:
                        continue
                    source_pkg_versions[source_name] = source_version

    source_pkgs = set()
    for source_name, source_version in source_pkg_versions.items():
        source_pkgs.add(f"{source_name}_{source_version}")

    print("\n".join(sorted(source_pkgs)))

    unversioned_srcs -= set(source_pkg_versions.keys())
    if unversioned_srcs:
        print("Unknown src:", " ".join(sorted(unversioned_srcs)), file=sys.stderr)


if __name__ == "__main__":
    main()
