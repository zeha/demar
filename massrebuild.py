# sbuild --arch-all --dist=unstable --nolog munge_0.5.15-3 --extra-package=libnss-myhostname-dbgsym_255~rc3-2.1_amd64.deb --extra-package=libnss-myhostname_255~rc3-2.1_amd64.deb --extra-package=libnss-mymachines-dbgsym_255~rc3-2.1_amd64.deb --extra-package=libnss-mymachines_255~rc3-2.1_amd64.deb --extra-package=libnss-resolve-dbgsym_255~rc3-2.1_amd64.deb --extra-package=libnss-resolve_255~rc3-2.1_amd64.deb --extra-package=libnss-systemd-dbgsym_255~rc3-2.1_amd64.deb --extra-package=libnss-systemd_255~rc3-2.1_amd64.deb --extra-package=libpam-systemd-dbgsym_255~rc3-2.1_amd64.deb --extra-package=libpam-systemd_255~rc3-2.1_amd64.deb --extra-package=libsystemd-dev_255~rc3-2.1_amd64.deb --extra-package=libsystemd-shared-dbgsym_255~rc3-2.1_amd64.deb --extra-package=libsystemd-shared_255~rc3-2.1_amd64.deb --extra-package=libsystemd0-dbgsym_255~rc3-2.1_amd64.deb --extra-package=libsystemd0_255~rc3-2.1_amd64.deb --extra-package=libudev-dev_255~rc3-2.1_amd64.deb --extra-package=libudev1-dbgsym_255~rc3-2.1_amd64.deb --extra-package=libudev1_255~rc3-2.1_amd64.deb --extra-package=systemd-boot-dbgsym_255~rc3-2.1_amd64.deb --extra-package=systemd-boot-efi_255~rc3-2.1_amd64.deb --extra-package=systemd-boot_255~rc3-2.1_amd64.deb --extra-package=systemd-container-dbgsym_255~rc3-2.1_amd64.deb --extra-package=systemd-container_255~rc3-2.1_amd64.deb --extra-package=systemd-coredump-dbgsym_255~rc3-2.1_amd64.deb --extra-package=systemd-coredump_255~rc3-2.1_amd64.deb --extra-package=systemd-dbgsym_255~rc3-2.1_amd64.deb --extra-package=systemd-dev_255~rc3-2.1_all.deb --extra-package=systemd-homed-dbgsym_255~rc3-2.1_amd64.deb --extra-package=systemd-homed_255~rc3-2.1_amd64.deb --extra-package=systemd-journal-remote-dbgsym_255~rc3-2.1_amd64.deb --extra-package=systemd-journal-remote_255~rc3-2.1_amd64.deb --extra-package=systemd-oomd-dbgsym_255~rc3-2.1_amd64.deb --extra-package=systemd-oomd_255~rc3-2.1_amd64.deb --extra-package=systemd-resolved-dbgsym_255~rc3-2.1_amd64.deb --extra-package=systemd-resolved_255~rc3-2.1_amd64.deb --extra-package=systemd-standalone-sysusers-dbgsym_255~rc3-2.1_amd64.deb --extra-package=systemd-standalone-sysusers_255~rc3-2.1_amd64.deb --extra-package=systemd-standalone-tmpfiles-dbgsym_255~rc3-2.1_amd64.deb --extra-package=systemd-standalone-tmpfiles_255~rc3-2.1_amd64.deb --extra-package=systemd-sysv_255~rc3-2.1_amd64.deb --extra-package=systemd-tests-dbgsym_255~rc3-2.1_amd64.deb --extra-package=systemd-tests_255~rc3-2.1_amd64.deb --extra-package=systemd-timesyncd-dbgsym_255~rc3-2.1_amd64.deb --extra-package=systemd-timesyncd_255~rc3-2.1_amd64.deb --extra-package=systemd-userdbd-dbgsym_255~rc3-2.1_amd64.deb --extra-package=systemd-userdbd_255~rc3-2.1_amd64.deb --extra-package=systemd_255~rc3-2.1_amd64.deb --extra-package=udev-dbgsym_255~rc3-2.1_amd64.deb --extra-package=udev_255~rc3-2.1_amd64.deb

import pathlib
import subprocess
import datetime
import sys

pkg_list_file = sys.argv[1]
changes_file = pathlib.Path(sys.argv[2]).absolute()
buildlog_dir = pathlib.Path(f"./buildlogs-{datetime.datetime.now().isoformat().replace(':', '-')}").absolute()
print("Writing buildlogs to", buildlog_dir)
buildlog_dir.mkdir()

with open(pkg_list_file, 'r') as fp:
    srcpkgs = fp.readlines()
    srcpkgs = [l.strip() for l in srcpkgs]

# Files:
# f0f6b108ae3ce47dda7cd839075337c3 345020 debug optional libnss-myhostname-dbgsym_255~rc3-2.1_amd64.deb
# 23688c455a80d9c1ffe1dc2c0eefaf33 95496 admin optional libnss-myhostname_255~rc3-2.1_amd64.deb

extra_pkgs = []
with open(changes_file, 'r') as fp:
    found = False
    for line in fp.readlines():
        if not found:
            if line.startswith('Files:'):
                found = True
        else:
            if line.startswith(' '):
                d = line.split()
                extra_pkgs.append(f"{changes_file.parent}/{d[4]}")
            else:
                found = False

for src_index, srcpkg in enumerate(srcpkgs):
    print("Building", srcpkg, f"{src_index}/{len(srcpkgs)}", "...")
    args = [
        "sbuild",
        "--dist=unstable",
        "-j4",
        "--nolog",
        srcpkg,
    ]
    for extra_pkg in extra_pkgs:
        args.append(f"--extra-package={extra_pkg}")
    print("   ", args)
    buildlog_file = buildlog_dir / srcpkg
    with buildlog_file.open("w") as out_fp:
        result = subprocess.run(args, stdout=out_fp)
    if result.returncode != 0:
        print("FAIL", srcpkg)

