#!/usr/bin/env python3

import re
import sys


def print_pkgs(s):
    seen = set()
    for line in s.splitlines():
        m = re.match("/([^_]+).*.deb$", line.strip())
        if m:
            pkg_name = m.group(1)
            x = pkg_name.rsplit("/", 2)
            pkg_name = x[-2]
            seen.add(pkg_name)
    return "\n".join(sorted(list(seen)))


for filename in sys.argv[1:]:
    with open(filename, "rt") as fp:
        print(print_pkgs(fp.read()))
