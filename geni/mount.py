import os.path
from typing import List, Optional, Type

from plumbum.cmd import (mount,  # pylint: disable=import-error
                         sudo,
                         umount)

from .util import sibling_path


class Mount:
    def __init__(self,
                 device: str,
                 mount_point: str,
                 *opts: str,
                 make_rslave: bool = False) -> None:
        self.device = device
        self.mount_point = mount_point
        self.opts = opts
        self.make_rslave = make_rslave

    def __enter__(self) -> str:
        self.mount()
        return self.mount_point

    def __exit__(self,
                 exception_type: Type[Exception],
                 exception_value: Exception,
                 traceback) -> Optional[bool]:
        self.umount()
        return False

    def mount(self) -> None:
        sudo[mount[self.opts, self.device, self.mount_point]]()

        if self.make_rslave:
            sudo[mount["--make-rslave", self.mount_point]]()

    def umount(self) -> None:
        opts = []
        if self.make_rslave:
            opts.append("-R")
        sudo[umount[opts, self.mount_point]]()


class BindMount(Mount):
    def __init__(self,
                 source_dir: str,
                 mount_point: str,
                 *opts: str) -> None:
        super().__init__(
            source_dir,
            mount_point,
            "--bind",
            *opts,
            make_rslave=False)


class OverlayMount(Mount):
    def __init__(self,
                 mount_point: str,
                 upper_dir: str,
                 *opts: str,
                 lower_dir: Optional[str] = None,
                 work_dir: Optional[str] = None) -> None:
        self.lower_dir = lower_dir or mount_point
        self.upper_dir = upper_dir
        self.work_dir = work_dir or sibling_path(self.upper_dir,
                                                 '._overlay_{}'.format)
        os.makedirs(self.work_dir, exist_ok=True)

        super().__init__(
            "overlay",
            mount_point,
            "--types", "overlay",
            "-o", (f"lowerdir={self.lower_dir},"
                   f"upperdir={self.upper_dir},"
                   f"workdir={self.work_dir}"),
            *opts,
            make_rslave=False)


class MountsManager:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir
        self.mounts: List[Mount] = []

    def __enter__(self) -> 'MountsManager':
        return self

    def __exit__(self,
                 exception_type: Type[Exception],
                 exception_value: Exception,
                 traceback) -> Optional[bool]:
        self.umount_all()
        return False

    def add(self, mount_: Mount) -> None:
        self.mounts.append(mount_)
        mount_.mount()

    def mount(self,
              device: str,
              directory: str,
              *opts: str,
              make_rslave: bool = False) -> None:
        mount_point = os.path.join(self.base_dir, directory.lstrip("/"))
        mount_ = Mount(device, mount_point, *opts, make_rslave=make_rslave)
        self.add(mount_)

    def umount_all(self):
        while self.mounts:
            self.mounts.pop().umount()
