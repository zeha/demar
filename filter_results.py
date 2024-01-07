#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="filter tallied results")
    parser.add_argument("--plain", default=False, action="store_true")
    parser.add_argument("--aux-list", type=argparse.FileType(mode="r"))
    parser.add_argument("filename")
    parser.add_argument("how")
    return parser.parse_args()


def match_udev(detail):
    return detail["groups"] == ["udev"] and detail["guessed_status"] not in (
        "patch-in-bts",
        "patch-marked-pending",
        "bug-filed",
        "lingering-patch-in-bts-maybe-ping-nmu",
    )


def match_special(detail):
    return (
        "udev" not in detail["groups"]
        and "systemd" not in detail["groups"]
        and detail["guessed_status"]
        not in (
            "patch-in-bts",
            "patch-marked-pending",
            "bug-filed",
            "lingering-patch-in-bts-maybe-ping-nmu",
        )
    )


def tpl_match_status(status, detail):
    return detail["guessed_status"] == status


def parse_aux_file(fp):
    return [p.split("_")[0] for p in fp.read().splitlines()]


def main():
    args = parse_args()
    how = args.how

    if args.aux_list:
        aux_list = parse_aux_file(args.aux_list)
    else:
        aux_list = None

    with Path(args.filename).open("r") as fp:
        data = list(yaml.safe_load_all(fp))

    results = data[-1]

    filtered = {}

    if how == "udev":
        matcher = match_udev
    elif how == "special":
        matcher = match_special
    elif how.startswith("status:"):
        s = how.split(":")[1]
        matcher = lambda detail: tpl_match_status(s, detail)
    else:
        raise ValueError(f"unknown how: {how}")

    for src_name, detail in results.items():
        if aux_list is not None and src_name not in aux_list:
            continue

        if matcher(detail):
            filtered[src_name] = detail

    if args.plain:
        print("\n".join(filtered.keys()))
    else:
        yaml.safe_dump_all([filtered], sys.stdout)


if __name__ == "__main__":
    main()
