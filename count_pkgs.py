#!/usr/bin/env python3

import re
import sys

def count_pkgs(s):
    seen = set()
    for line in s.splitlines():
        m = re.match('/([^_]+).*.deb$', line.strip())
        if m:
            pkg_name = m.group(1)
            seen.add(pkg_name)
    return len(seen)
               

for filename in sys.argv[1:]:
    with open(filename, 'rt') as fp:
        print(filename, count_pkgs(fp.read()))

