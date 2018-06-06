from contextlib import contextmanager
import hashlib
import os
import os.path
from typing import Any, Callable, Dict, List, Optional, Tuple

from plumbum import local
from plumbum.cmd import (cp,  # pylint: disable=import-error
                         diff,
                         echo,
                         install,
                         rm,
                         sudo,
                         tee)
from plumbum.machines import LocalCommand
import portalocker


class ExceptionEater:
    def __init__(self) -> None:
        self.exceptions: List[Exception] = []

    def eat(self,
            function: Callable,
            *args,
            **kwargs) -> Tuple[Any, Optional[Exception]]:
        try:
            return (function(*args, **kwargs), None)
        except Exception as exception:  # pylint: disable=broad-except
            self.exceptions.append(exception)
            return (None, exception)

    def raise_first_if_any(self) -> None:
        if self.exceptions:
            raise self.exceptions[0]


class FileInstaller:
    def __init__(self, source_base_dir: str, target_base_dir: str) -> None:
        self.source_base_dir = source_base_dir
        self.target_base_dir = target_base_dir
        self.files: List[str] = []

    def _make_source_path(self, rel_path: str) -> str:
        return os.path.join(self.source_base_dir, rel_path.lstrip("/"))

    def _make_target_path(self, rel_path: str) -> str:
        return os.path.join(self.target_base_dir, rel_path.lstrip("/"))

    def _remove(self, rel_path: str) -> None:
        sudo[rm[self._make_target_path(rel_path)]]()

    def ensure_is_copied(self, rel_path: str) -> None:
        source_path = self._make_source_path(rel_path)
        target_path = self._make_target_path(rel_path)
        diff[source_path, target_path]()

    def copy(self, rel_path: str) -> str:
        source_path = self._make_source_path(rel_path)
        target_path = self._make_target_path(rel_path)
        sudo[cp["--dereference", source_path, target_path]]()
        self.files.append(rel_path)
        return target_path

    def install(self, rel_path: str, mode: Optional[str] = None) -> str:
        source_path = self._make_source_path(rel_path)
        target_path = self._make_target_path(rel_path)
        if mode is None:
            mode = format(os.stat(source_path).st_mode & 0o7777, "04o")
        sudo[install[f"--mode={mode}",
                     "--owner=root",
                     "--group=root",
                     "-D",
                     source_path,
                     target_path]]()
        self.files.append(rel_path)
        return target_path

    def uninstall(self, rel_path: str) -> None:
        self._remove(rel_path)
        self.files.remove(rel_path)

    def uninstall_all(self) -> None:
        while self.files:
            rel_path = self.files.pop()
            self._remove(rel_path)


class FileSemaphore:
    def __init__(self, path: str) -> None:
        self.sem_file_path = path
        self.lock_file_path = path + ".lock"

    def _read(self) -> int:
        try:
            with portalocker.Lock(self.lock_file_path) as lock_file:
                if os.path.exists(self.sem_file_path):
                    with portalocker.Lock(self.sem_file_path,
                                          mode="r") as lock_file:
                        return int(lock_file.read().strip() or 0)
                else:
                    return 0
        finally:
            os.remove(self.lock_file_path)

    def _update(self, func: Callable[[int], int]) -> int:
        counter = -1

        try:
            with portalocker.Lock(self.lock_file_path) as lock_file:
                if os.path.exists(self.sem_file_path):
                    with portalocker.Lock(self.sem_file_path,
                                          mode="r") as lock_file:
                        counter = int(lock_file.read().strip() or 0)
                else:
                    counter = 0

                counter = func(counter)

                with portalocker.Lock(self.sem_file_path,
                                      mode="w") as lock_file:
                    lock_file.write(str(counter))

            return counter
        finally:
            os.remove(self.lock_file_path)
            if counter == 0:
                os.remove(self.sem_file_path)

    def down(self) -> int:
        return self._update(lambda counter: counter - 1)

    def get(self) -> int:
        return self._read()

    def up(self) -> int:  # pylint: disable=invalid-name
        return self._update(lambda counter: counter + 1)


class FileTempInst:
    def __init__(self, chroot_dir: str, file_path: str) -> None:
        self.inst = FileInstaller("/", chroot_dir)
        self.file_path = file_path

    def copy(self) -> None:
        self.inst.copy(self.file_path)

    def ensure_is_copied(self) -> None:
        self.inst.ensure_is_copied(self.file_path)

    def remove(self) -> None:
        self.inst.uninstall_all()


def drop_prefix(prefix: str, string: str) -> str:
    return string[len(prefix):] if string.startswith(prefix) else string


def hash_path(path: str) -> str:
    hasher = hashlib.sha1()
    hasher.update(path.encode("utf-8"))
    return hasher.hexdigest()


def join_url(base_url: str, path: str) -> str:
    return "/".join((base_url.rstrip("/"), path.lstrip("/")))


def make_proxies_dict() -> Dict[str, str]:
    proxies = {}

    for var in ["http_proxy", "https_proxy"]:
        if var in local.env:
            proxies[var] = local.env[var]

    return proxies


@contextmanager
def no_escaping():
    orig_quote_level = LocalCommand.QUOTE_LEVEL
    LocalCommand.QUOTE_LEVEL = 0xffffffff
    try:
        yield
    finally:
        LocalCommand.QUOTE_LEVEL = orig_quote_level


def sibling_path(path: str, rename_leaf: Callable[[str], str]) -> str:
    normalised_path = os.path.normpath(path)
    tail, head = os.path.split(normalised_path)
    return os.path.join(tail, rename_leaf(head))


def sudo_append(path: str, content: str) -> None:
    (echo["-n", content] | sudo[tee, "--append", path] > '/dev/null')()


def sudo_write(path: str, content: str) -> None:
    (echo["-n", content] | sudo[tee, path] > '/dev/null')()
