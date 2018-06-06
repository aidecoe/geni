import os.path
import shlex
import sys
import time
from typing import Optional, Type

from plumbum import BG, FG
from plumbum.cmd import (chroot,  # pylint: disable=import-error
                         mountpoint,
                         sudo)

from .exceptions import GeniException
from .mount import MountsManager
from .util import (ExceptionEater,
                   FileSemaphore,
                   FileTempInst,
                   hash_path,
                   no_escaping)


class ChrootExec:
    def __init__(self, chroot_dir: str) -> None:
        self.chroot_dir = chroot_dir

    def prep_bare(self, *args):
        return sudo[chroot[self.chroot_dir, args]]

    def prep(self, *args, env_vars={}):
        source_etc_profile = "source /etc/profile"
        env_vars_str = " ".join(
            "{key}={value}".format(key=key, value=shlex.quote(value))
            for key, value in env_vars.items()
        )
        command = " ".join(map(shlex.quote, args))
        return self.prep_bare(
            "/bin/bash",
            "-c",
            f"{source_etc_profile} && {env_vars_str} {command}"
        )

    def __call__(self, *args, env_vars={}):
        with no_escaping():
            return self.prep(*args, env_vars=env_vars)()

    def bg(self, *args, env_vars={}):  # pylint: disable=invalid-name
        with no_escaping():
            return self.prep(*args, env_vars=env_vars) & BG

    def fg(self, *args, env_vars={}):  # pylint: disable=invalid-name
        with no_escaping():
            return self.prep(*args, env_vars=env_vars) & FG

    def from_stdin(self):
        return (self.prep_bare("/bin/bash") < sys.stdin) & FG

    def shell(self):
        self.prep_bare("/bin/bash", "-l") & FG  # noqa: E501 pylint: disable=expression-not-assigned


class Chroot:
    def __init__(self, chroot_dir: str, work_dir: str) -> None:
        self.chroot_dir = chroot_dir
        self.mounts_mgr = MountsManager(self.chroot_dir)
        chroot_name = os.path.basename(chroot_dir)
        chroot_path_hash = hash_path(chroot_dir)
        self.semaphore = FileSemaphore(
            os.path.join(work_dir,
                         f"._geni_chroot_{chroot_name}_{chroot_path_hash}_cnt")
        )
        self.resolv_conf = FileTempInst(
            self.chroot_dir,
            "/etc/resolv.conf"
        )
        self.master = False

    def clean_up(self) -> None:
        self.semaphore.down()

        if self.master:
            while self.semaphore.get() > 0:
                # log warning?
                time.sleep(3)

            exc_eater = ExceptionEater()
            exc_eater.eat(self.umount_all)
            exc_eater.eat(self.resolv_conf.remove)
            self.master = False
            exc_eater.raise_first_if_any()

    @staticmethod
    def ensure_all_mounted() -> None:
        for mp_path in ["/tmp", "/proc", "/sys", "/dev"]:
            mountpoint["-q", mp_path]()

    def mount_all(self) -> None:
        self.mounts_mgr.mount("geni_tmpfs", "/tmp", "--types", "tmpfs")

        if os.path.islink("/dev/shm"):
            raise GeniException("/dev/shm is not a directory")

        self.mounts_mgr.mount("/proc", "/proc", "--types", "proc",
                              make_rslave=True)
        self.mounts_mgr.mount("/sys", "/sys", "--rbind",
                              make_rslave=True)
        self.mounts_mgr.mount("/dev", "/dev", "--rbind",
                              make_rslave=True)

    def umount_all(self) -> None:
        self.mounts_mgr.umount_all()

    def prepare(self) -> None:
        if self.semaphore.up() == 1:
            self.master = True
            self.resolv_conf.copy()
            self.mount_all()
        else:
            assert self.semaphore.get() > 1

        self.resolv_conf.ensure_is_copied()
        self.ensure_all_mounted()

    def __enter__(self) -> ChrootExec:
        try:
            self.prepare()
        except:  # noqa: E722
            self.clean_up()
            raise
        return ChrootExec(self.chroot_dir)

    def __exit__(self,
                 exception_type: Type[Exception],
                 exception_value: Exception,
                 traceback) -> Optional[bool]:
        self.clean_up()
        return False
