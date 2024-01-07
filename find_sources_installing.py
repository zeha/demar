#!/usr/bin/env python3
import argparse
import gzip
import pathlib
import sys

from debian import deb822
from debian.debian_support import version_compare

ARCHS = ["all", "arm64", "amd64"]
COMPONENTS = ["main", "contrib", "non-free", "non-free-firmware"]

FINDERS = {
    "udev": lambda path: path.startswith("lib/udev/"),
    "systemd": lambda path: path.startswith("lib/systemd/"),
    "udevsystemd": lambda path: path.startswith("lib/udev/") or path.startswith("lib/systemd/"),
    "usrmerge": lambda path: path.startswith("lib/") or path.startswith("bin/") or path.startswith("sbin/"),
    "pam": lambda path: path.startswith("lib/x86_64-linux-gnu/security/")
    or path.startswith("usr/lib/x86_64-linux-gnu/security/"),
}


def find_bin_pkgs_with_paths(contents: pathlib.Path, finder) -> set[str]:
    bin_pkgs = set()
    with gzip.open(contents, "rt") as fp:
        for line in fp:
            path, packages = line.strip().split(maxsplit=1)
            if finder(path):
                for package in packages.split(","):
                    bin_pkgs.add(package.rsplit("/", 1)[1])

    return bin_pkgs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find sources installing paths into binaries")
    parser.add_argument("finder", choices=FINDERS.keys())
    return parser.parse_args()


def main():
    mirror = "/srv/debian-mirror/mirror"
    bin_pkgs = set()
    found_bin_pkgs = set()
    source_pkg_versions = {}

    args = parse_args()
    finder = FINDERS[args.finder]

    for component in COMPONENTS:
        for arch in ARCHS:
            bin_pkgs.update(
                find_bin_pkgs_with_paths(pathlib.Path(f"{mirror}/dists/sid/{component}/Contents-{arch}.gz"), finder)
            )

    for component in COMPONENTS:
        for arch in ARCHS:
            pkglist_file = pathlib.Path(f"{mirror}/dists/sid/{component}/binary-{arch}/Packages.gz")
            with gzip.open(pkglist_file, "rt") as pkglist:
                for pkg in deb822.Packages.iter_paragraphs(pkglist):
                    bin_name = pkg["Package"]
                    if pkg["Package"] not in bin_pkgs:
                        continue

                    found_bin_pkgs.add(bin_name)

                    source_name = pkg.source
                    source_version = pkg.source_version
                    other_ver = source_pkg_versions.get(source_name)
                    if other_ver and version_compare(other_ver, source_version) >= 0:
                        continue
                    source_pkg_versions[source_name] = source_version

    source_pkgs = set()
    for source_name, source_version in source_pkg_versions.items():
        source_pkgs.add(f"{source_name}_{source_version}")

    print("\n".join(sorted(source_pkgs)))

    unknown_bin_pkgs = bin_pkgs - found_bin_pkgs
    if unknown_bin_pkgs:
        print("Unknown bins:", " ".join(sorted(unknown_bin_pkgs)), file=sys.stderr)


if __name__ == "__main__":
    main()
