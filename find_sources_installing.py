#!/usr/bin/env python3
import argparse
import gzip
import pathlib

from debian import deb822

ARCHS = ["all", "arm64", "amd64"]
COMPONENTS = ["main", "contrib", "non-free", "non-free-firmware"]

FINDERS = {
    "udev": lambda path: path.startswith("lib/udev/"),
    "systemd": lambda path: path.startswith("lib/systemd/"),
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
    source_pkgs = set()

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
                    if bin_name not in bin_pkgs:
                        continue
                    source_pkgs.add(f"{pkg.source}_{pkg.source_version}")
                    bin_pkgs.remove(bin_name)

    print("\n".join(sorted(source_pkgs)))

    if bin_pkgs:
        print("Unknown bins:", " ".join(sorted(bin_pkgs)))


if __name__ == "__main__":
    main()
