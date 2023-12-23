#!/usr/bin/env python3
import json
from pathlib import Path

import psycopg
import psycopg.rows

CACHE_DIR = Path("~/.cache/demar").expanduser()

PG_UDD_URL = "postgresql://udd-mirror:udd-mirror@udd-mirror.debian.net/udd?client_encoding=utf-8"


def query_bugs_udd():
    sql = """
select bugs.id, bugs.source, bugs.severity, bugs.title,
    bugs.last_modified::text,
    bugs.status,
    bugs.affects_testing, bugs.affects_unstable,
    (select array_agg(version) from bugs_found_in where bugs_found_in.id = bugs.id) as found_in
from bugs
join bugs_tags on bugs.id = bugs_tags.id
where bugs_tags.tag = 'ftbfs'
and severity in ('serious', 'grave')
and status <> 'done'
and (affects_testing or affects_unstable)
and bugs.id not in (select id from bugs_merged_with where id > merged_with)
    """
    with psycopg.connect(PG_UDD_URL, row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cursor:
            return cursor.execute(sql).fetchall()


def main():
    cache_file = CACHE_DIR / "bugs-ftbfs"
    result = json.dumps(query_bugs_udd())
    with cache_file.open("w") as fp:
        fp.write(result)

if __name__ == "__main__":
    main()
