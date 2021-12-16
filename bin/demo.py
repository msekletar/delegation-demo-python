#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import logging
import os
import subprocess
import sys
import time

from typing import Optional, List, Set

from dbus import SystemBus, Interface
from dbus.exceptions import DBusException
from dbus.types import UInt32
from psutil import disk_partitions


class CgMode():
    LEGACY = 1
    HYBRID = 2
    UNIFIED = 3

    def __init__(self) -> None:
        cgroup_mounts = { p.mountpoint: p for p in disk_partitions(all=True) if p.mountpoint.startswith('/sys/fs/cgroup')}

        mnt_root = cgroup_mounts.get('/sys/fs/cgroup')
        mnt_unified = cgroup_mounts.get('/sys/fs/cgroup/unified')
        mnt_systemd = cgroup_mounts.get('/sys/fs/cgroup/systemd')

        named_hierarchy_is = lambda mount, fstype: mount and mount.fstype == fstype and mount.opts.find('name=systemd') != -1

        if mnt_root is None:
            return

        self._mode = None
        if mnt_root.fstype == 'cgroup2':
            self._mode = CgMode.UNIFIED
        elif mnt_root.fstype == 'tmpfs' and named_hierarchy_is(mnt_systemd, 'cgroup'):
            self._mode = CgMode.LEGACY
        elif mnt_root.fstype == 'tmpfs' and named_hierarchy_is(mnt_systemd, 'cgroup2'):
            self._mode = CgMode.HYBRID

        if self._mode is None:
            raise ValueError('Failed to detect cgroup mode.')

    def __eq__(self, other) -> bool:
        if isinstance(other, int):
            return self._mode == other

        if isinstance(other, CgMode):
            return self._mode == other._mode

        return False

    def __str__(self) -> str:
        if self._mode == CgMode.HYBRID:
            return 'hybrid'
        if self._mode == CgMode.LEGACY:
            return 'legacy'
        if self._mode == CgMode.UNIFIED:
            return 'unified'

        return ''


class DelegatedScope():
    def __init__(self, name: str, slice: str) -> None:
        if not slice.endswith('.slice'):
            raise ValueError('Invalid slice name.')

        if not name.endswith('.scope'):
            raise ValueError('Invalid scope name.')

        self._cgmode = CgMode()
        if self._cgmode == CgMode.HYBRID:
            raise ValueError('Hybrid cgroup mode is not support. Either boot to legacy (systemd.legacy_systemd_cgroup_controller) or full unified mode (systemd.unified_cgroup_hierarchy)')

        self._slice = slice
        self._scope = name
        self._cgpath = f'/sys/fs/cgroup/' + ('systemd/' if self._cgmode == CgMode.LEGACY else '') + f'{self._slice}/{self._scope}'
        self._subcgroups: Set[str] = set()

        self._start_unit()

    def __del__(self):
        self._stop_unit()

    def _connect_systemd(self) -> Interface:
        try:
            proxy = SystemBus().get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1")
            return Interface(proxy, "org.freedesktop.systemd1.Manager")
        except Exception as e:
            raise ConnectionError("Failed to connect to systemd over D-Bus") from e

    def _start_unit(self) -> None:
        try:
            systemd = self._connect_systemd()
            systemd.StartTransientUnit(self._scope,
                    "replace",
                    [("PIDs", [UInt32(os.getpid())]), \
                        ("Slice", self._slice),       \
                        ("Delegate", True),           \
                        ("CPUAccounting", True),      \
                        ("MemoryAccounting", True),   \
                        ("BlockIOAccounting", True),  \
                        ("TasksAccounting", True)],
                    [])
        except DBusException as e:
            if e.get_dbus_name() == 'org.freedesktop.systemd1.UnitExists':
                logging.info('Scope unit already exists, rusing.')
            else:
                raise e
        except Exception as e:
            raise RuntimeError(f'Failed to start scope unit') from e

        # TODO(msekleta): wait for the result of scope start job instead of sleeping
        time.sleep(0.1)

    def _stop_unit(self) -> None:
        try:
            systemd = self._connect_systemd()
            systemd.StopUnit(self._scope, "replace")
        except Exception as e:
            logging.error('Failed to stop scope unit: {e}')

    def create_subcgroup(self, name: str) -> Optional[List[str]]:
        result = []
        if not str:
            logging.error('Provide cgroup name, e.g. "manager".')
            return None

        cgdir = self._cgpath + f'/{name}'

        # Create group in the main hierarchy.
        try:
            os.rmdir(cgdir)
        except FileNotFoundError as e:
            pass

        os.mkdir(cgdir)
        result.append(cgdir)

        # When running in legacy mode create also cgroups in the hierarchy of each controller.
        if self._cgmode == CgMode.LEGACY:
            for c in ("cpu", "memory", "blkio", "pids"):
                cgdir = f'/sys/fs/cgroup/{c}/{self._slice}/{self._scope}/{name}'

                try:
                    os.rmdir(cgdir)
                except FileNotFoundError as e:
                    pass

                os.mkdir(cgdir)
                result.append(cgdir)

        self._subcgroups.add(name)
        return result

    def migrate_pid(self, subcgroup: str, pid: int) -> None:
        if not subcgroup in self._subcgroups:
            self.create_subcgroup(subcgroup)

        procs = self._cgpath + f'/{subcgroup}/cgroup.procs'
        with open(procs, 'w') as p:
            p.write(str(pid))

        if self._cgmode == CgMode.LEGACY:
            for c in ("cpu", "memory", "blkio", "pids"):
                procs = f'/sys/fs/cgroup/{c}/{self._slice}/{self._scope}/{subcgroup}/cgroup.procs'
                with open(procs, 'w') as p:
                    p.write(str(pid))

    def __str__(self) -> str:
        try:
            s = subprocess.Popen(['systemd-cgls', '--no-pager', self._cgpath], stderr=None)
            s.wait()
        except Exception as e:
            logging.info(f'Failed to run systemd-cgls: {e}')
            return ''

        return str(s.stdout)

    def delegate_resource_control(self) -> None:
        if self._cgmode != CgMode.UNIFIED:
            return

        with open(f'{self._cgpath}/cgroup.subtree_control', 'w') as f:
            f.write('+cpu +memory +pids +io')


def main():
    s=DelegatedScope("workload.scope", "workload.slice")

    s.create_subcgroup('manager')
    s.create_subcgroup('workers')

    # Migrate ourselves to manager cgroup
    s.migrate_pid('manager', os.getpid())

    # Create dummy manager process
    manager = subprocess.Popen(["sleep", "100"])
    s.migrate_pid('manager', manager.pid)

    # Create dummy worker process
    worker = subprocess.Popen(["sleep", "100"])
    s.migrate_pid('workers', worker.pid)

    # Cgroup tree setup so let's enable for the subtree controllers (on cgroupv2)
    s.delegate_resource_control()

    print(s)
    print('Sleeping for 30s')
    time.sleep(30)


if __name__ == '__main__':
    main()
