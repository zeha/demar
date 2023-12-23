#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="filter tallied results")
    parser.add_argument("filename")
    return parser.parse_args()


def main():
    args = parse_args()

    with Path(args.filename).open("r") as fp:
        data = list(yaml.safe_load_all(fp))

    results = data[2]

    filtered = {}

    for src_name, detail in results.items():
        if detail["groups"] == ["udev"] and detail["guessed_status"] not in (
            "patch-in-bts",
            "patch-marked-pending",
            "bug-filed",
            "lingering-patch-in-bts-maybe-ping-nmu",
        ):
            filtered[src_name] = detail

    yaml.safe_dump_all([filtered], sys.stdout)


if __name__ == "__main__":
    main()
