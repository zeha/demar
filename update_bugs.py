#!/usr/bin/env python3
import json
from pathlib import Path

import httpx
import psycopg
import psycopg.rows

CACHE_DIR = Path("~/.cache/demar").expanduser()

PG_UDD_URL = "postgresql://udd-mirror:udd-mirror@udd-mirror.debian.net/udd?client_encoding=utf-8"

SQL_DEP17 = """
with sources_uploads as (
    select max(date) AS lastupload, s1.source
    from sources s1, upload_history uh
    where s1.source = uh.source
    and s1.version = uh.version
    and s1.release='sid'
    group by s1.source
),
bugs_usertagged as (
    select id
    from bugs_usertags
    where email='helmutg@debian.org' and tag like 'dep17%'
)
select bugs.id, bugs.source, bugs.severity, bugs.title,
    bugs.last_modified::text,
    bugs.status,
    bugs.affects_testing, bugs.affects_unstable, bugs.affects_experimental,
    sources_uploads.lastupload::text,
    coalesce((select array_agg(bugs_tags.tag order by tag) from bugs_tags where bugs_tags.id = bugs.id), array[]::text[]) as tags,
    (select max(version) from bugs_found_in where bugs_found_in.id = bugs.id) as max_found_in
from bugs_usertagged
join bugs on bugs.id = bugs_usertagged.id
join sources_uploads on bugs.source = sources_uploads.source
where
    bugs.id not in (select id from bugs_merged_with where id > merged_with)
order by 2,1
"""

SQL_FTBFS = """
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
order by 2,1
"""

URL_BINARYCONTROL_STATOVERRIDE = (
    "https://binarycontrol.debian.net/?q=dpkg-statoverride&path=%2Funstable%2F&format=pkglist"
)


def query_udd(sql):
    with psycopg.connect(PG_UDD_URL, row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cursor:
            return cursor.execute(sql).fetchall()


def query_http(url: str):
    return (
        httpx.get(url, headers={"User-Agent": "demar/tally_results (zeha@debian.org)"})
        .read()
        .strip()
        .decode()
        .splitlines()
    )


def update_cache(filename, callable):
    cache_file = CACHE_DIR / filename
    result = json.dumps(callable())
    with cache_file.open("w") as fp:
        fp.write(result)


def main():
    update_cache("bugs-ftbfs", lambda: query_udd(SQL_FTBFS))
    update_cache("bugs-dep17", lambda: query_udd(SQL_DEP17))
    update_cache("binaries-using-statoverride", lambda: query_http(URL_BINARYCONTROL_STATOVERRIDE))


if __name__ == "__main__":
    main()
