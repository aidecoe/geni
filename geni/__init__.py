from contextlib import contextmanager
import datetime
import logging
import os
import os.path
from typing import List, Optional

import arrow
import pkg_resources
from plumbum import (ProcessExecutionError,
                     cli,
                     local)
from plumbum.cmd import (egrep,  # pylint: disable=import-error
                         ln,
                         rm,
                         sudo,
                         tar)

from .chroot import Chroot
from .download import (Digests,
                       StageDownloader)
from .exceptions import GeniException
from .gpgaside import GpgAside
from .mount import (BindMount,
                    MountsManager,
                    OverlayMount)
from .util import (FileInstaller,
                   make_proxies_dict,
                   no_escaping,
                   sudo_write)


GENTOO_MIRROR = "http://mirror.bytemark.co.uk/gentoo"


class FileCorruptedError(GeniException):
    pass


def configure_net_simple_names(chroot_dir: str) -> None:
    net_name_slot_rules_path = "/etc/udev/rules.d/80-net-name-slot.rules"
    sudo[ln["-s",
            "/dev/null",
            os.path.join(chroot_dir,
                         net_name_slot_rules_path.lstrip("/"))]]()


def configure_time_zone(chroot: Chroot, timezone: str) -> None:
    timezone_file_path = os.path.join(chroot.chroot_dir, "etc", "timezone")
    sudo_write(timezone_file_path, timezone + "\n")

    with chroot as chroot_exec:
        chroot_exec("emerge", "--config", "sys-libs/timezone-data")


def extract_stage_tarball_into(archive_path: str, output_dir: str) -> None:
    # TODO: check whether it's newer?
    # TODO: release in .extracted file?
    output_dir_listing = os.listdir(output_dir)
    if output_dir_listing:
        logging.info("Output directory already exists, removing its content: "
                     "%s", output_dir)
        for file in output_dir_listing:
            sudo[rm["-rf", os.path.join(output_dir, file)]]()
    os.makedirs(output_dir, exist_ok=True)
    with no_escaping():
        sudo[tar["xapf",
                 archive_path,
                 "-C", output_dir,
                 "--xattrs-include='*.*'",
                 "--numeric-owner"]]()


def find_locale_line(chroot_dir: str, locale_name: str) -> str:
    supported_locale_file_path = os.path.join(chroot_dir,
                                              "usr/share/i18n/SUPPORTED")
    return egrep["-i", f"^{locale_name}\\s+"](supported_locale_file_path)


def generate_locales(chroot: Chroot, locales: List[str]) -> None:
    locale_file_path = os.path.join(chroot.chroot_dir, "etc", "locale.gen")

    with open(locale_file_path, "r") as file:
        locale_file_lines = file.readlines()

    modified_lines = []
    locales_lower = [locale.lower() for locale in locales]
    remaining_locales = locales_lower[:]

    for line in locale_file_lines:
        if not remaining_locales:
            break
        try:
            locale_name, charset = line.strip().lstrip("#").split()
        except ValueError:
            modified_lines.append(line)
        else:
            if locale_name.lower() in locales_lower:
                modified_lines.append(f"{locale_name} {charset}\n")
                remaining_locales.remove(locale_name.lower())
            else:
                modified_lines.append(line)

    while remaining_locales:
        locale_name = remaining_locales[0]
        modified_lines.append(find_locale_line(chroot.chroot_dir, locale_name))
        remaining_locales.remove(locale_name.lower())

    sudo_write(locale_file_path, "".join(modified_lines))

    with chroot as chroot_exec:
        chroot_exec.fg("locale-gen")


def make_chroot_dir(work_dir: str) -> str:
    default_chroot_dir = os.path.join(work_dir, "gentoo")
    chroot_dir = local.env.get("GENI_CHROOT_DIR", default_chroot_dir)
    os.makedirs(chroot_dir, exist_ok=True)
    return chroot_dir


def make_work_dir() -> str:
    work_dir = local.env.get("GENI_WORK_DIR", "geni_work")
    os.makedirs(work_dir, exist_ok=True)
    os.chmod(work_dir, mode=0o700)
    return work_dir


def set_locale(chroot: Chroot, locale_name: str) -> None:
    with chroot as chroot_exec:
        chroot_exec("eselect", "locale", "set", locale_name)


def install_stage_tarball(gpg_aside: GpgAside,
                          mirror_url: str,
                          downloads_dir: str,
                          chroot_dir: str) -> None:
    stage_downloader = StageDownloader(mirror_url, downloads_dir)
    latest_release = stage_downloader.find_latest()

    logging.info("Downloading digests")
    digests_path = stage_downloader.download_digests(latest_release)
    if not gpg_aside.verify(digests_path):
        raise FileCorruptedError(digests_path)
    digests = Digests(digests_path)

    logging.info("Downloading %s stage3 tarball", latest_release)
    stage_path = stage_downloader.download_stage(latest_release)
    if not digests.verify(stage_path):
        logging.fatal("Wrong check sum: %s", stage_path)
        raise FileCorruptedError(stage_path)

    logging.info("Extracting %s stage3 tarball", latest_release)
    extract_stage_tarball_into(stage_path, chroot_dir)


def configure_portage_basic(chroot: Chroot) -> None:
    config_path = pkg_resources.resource_filename(
        __name__, "data/portage-basic")
    finst = FileInstaller(config_path, chroot.chroot_dir)
    finst.install(os.path.join("etc", "portage", "make.conf"),
                  mode="0644")
    finst.install(os.path.join("etc", "portage", "repos.conf", "gentoo.conf"),
                  mode="0644")
    finst.install(os.path.join("usr", "local", "portage", "metadata",
                               "layout.conf"),
                  mode="0644")
    finst.install(os.path.join("usr", "local", "portage", "profiles",
                               "repo_name"),
                  mode="0644")
    finst.install(os.path.join("var", "lib", "portage", "world"),
                  mode="0644")

    with chroot as chroot_exec:
        portage_dir = chroot_exec(
            "portageq", "get_repo_path", "/", "gentoo").strip()
        chroot_exec("mkdir", "-p", portage_dir)


def configure_portage_extras(chroot_dir: str) -> None:
    config_path = pkg_resources.resource_filename(
        __name__, "data/portage-extras")
    finst = FileInstaller(config_path, chroot_dir)
    finst.install(os.path.join("etc", "portage", "repo.postsync.d",
                               "sync_gentoo_cache"),
                  mode="0755")
    finst.install(os.path.join("etc", "portage", "repo.postsync.d",
                               "sync_gentoo_dtd"),
                  mode="0755")
    finst.install(os.path.join("etc", "portage", "repo.postsync.d",
                               "sync_gentoo_glsa"),
                  mode="0755")
    finst.install(os.path.join("etc", "portage", "repo.postsync.d",
                               "sync_gentoo_news"),
                  mode="0755")


def get_portage_timestamp_file_path(chroot_dir: str) -> str:
    return os.path.join(
        chroot_dir, "usr", "portage", "metadata", "timestamp.chk")


def check_portage_tree_exists(chroot_dir: str) -> bool:
    return os.path.exists(get_portage_timestamp_file_path(chroot_dir))


def check_portage_needs_sync(chroot_dir: str) -> bool:
    last_sync_file_path = get_portage_timestamp_file_path(chroot_dir)
    if not os.path.exists(last_sync_file_path):
        return True

    with open(last_sync_file_path, "r") as file:
        last_sync = arrow.get(file.readline().strip(),
                              "ddd, DD MMM YYYY HH:mm:ss Z")
        return arrow.utcnow() - last_sync >= datetime.timedelta(days=1)


def sync_repo(chroot: Chroot) -> None:
    if not check_portage_tree_exists(chroot.chroot_dir):
        with chroot as chroot_exec:
            logging.info("Downloading and unpacking portage tree snapshot...")
            chroot_exec("emerge-webrsync", env_vars=make_proxies_dict())

    if check_portage_needs_sync(chroot.chroot_dir):
        with chroot as chroot_exec:
            logging.info("Syncing portage tree...")
            chroot_exec("emerge", "--sync", env_vars=make_proxies_dict())
            assert not check_portage_needs_sync(chroot.chroot_dir)
    else:
        logging.info("Portage tree is in sync.")


def upgrade_system(chroot: Chroot) -> None:
    with chroot as chroot_exec:
        logging.info("Updating @world...")
        chroot_exec.fg("emerge",
                       "--autounmask-write",
                       "--quiet-build=y",
                       "-NuD",
                       "@world")


def emerge(chroot: Chroot, packages: List[str]) -> None:
    assert not any([p.startswith("-") for p in packages])

    with chroot as chroot_exec:
        chroot_exec.fg("emerge",
                       "--autounmask-write",
                       "--quiet-build=y",
                       *packages)


def clean_distdir(chroot: Chroot) -> None:
    with chroot as chroot_exec:
        dist_dir = chroot_exec("portageq", "distdir", "/", "gentoo").strip()
        chroot_exec("find", dist_dir, "-mindepth", "1", "-delete")


class Geni(cli.Application):
    debug = cli.Flag(["d", "debug"])

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.chroot_dir = ''
        self.work_dir = ''
        self.chroot: Optional[Chroot] = None

    def main(self) -> int:  # pylint: disable=arguments-differ
        logging.basicConfig(level=(logging.DEBUG
                                   if self.debug
                                   else logging.INFO))

        self.work_dir = make_work_dir()
        self.chroot_dir = make_chroot_dir(self.work_dir)
        self.chroot = Chroot(self.chroot_dir, self.work_dir)

        return 0


@Geni.subcommand("manage")
class GeniManage(cli.Application):
    """Prepares and manages chroot environment
    """
    @property
    def chroot(self) -> Chroot:
        return self.parent.chroot

    @property
    def chroot_dir(self) -> str:
        return self.parent.chroot_dir

    @property
    def work_dir(self) -> str:
        return self.parent.work_dir


@GeniManage.subcommand("bootstrap")
class GeniManageBootstrap(cli.Application):
    """Downloads and unpacks Gentoo stage3 tarball, configures portage
    """
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.gpg_aside: Optional[GpgAside] = None

    def main(self) -> int:  # pylint: disable=arguments-differ
        gpg_home_dir = os.path.join(self.parent.work_dir, "gpghome")
        self.gpg_aside = GpgAside(gpg_home_dir)
        key_path = pkg_resources.resource_filename(
            __name__, "data/gentoo-master-keys.asc")
        if not self.gpg_aside.import_pub_keys(key_path):
            return 1

        downloads_dir = os.path.join(self.parent.work_dir,
                                     "downloads")

        install_stage_tarball(self.gpg_aside,
                              GENTOO_MIRROR,
                              downloads_dir,
                              self.parent.chroot_dir)

        configure_portage_basic(self.parent.chroot)

        return 0


def install_tree(chroot_dir: str, source_path: str) -> None:
    if not os.path.exists(source_path):
        raise FileNotFoundError(source_path)
    if not os.path.isdir(source_path):
        raise NotADirectoryError(source_path)

    finst = FileInstaller(source_path, chroot_dir)
    for root, _dirs, files in os.walk(source_path):
        rel_root = root[len(source_path):]
        for file_name in files:
            file_path = os.path.join(rel_root, file_name)
            logging.debug("Installing %s", file_path)
            finst.install(file_path)


def select_portage_profile(chroot: Chroot, portage_profile: str) -> None:
    with chroot as chroot_exec:
        chroot_exec("eselect", "profile", "set", portage_profile)


@GeniManage.subcommand("install-tree")
class GeniManageInstallTree(cli.Application):
    """Installs tree into chroot
    """
    def main(self, source_path: str) -> int:  # noqa: E501 pylint: disable=arguments-differ
        install_tree(self.parent.chroot_dir, source_path)
        return 0


@GeniManage.subcommand("clean-dist")
class GeniManageCleanDist(cli.Application):
    """Cleans portage distdir content
    """
    def main(self) -> int:  # pylint: disable=arguments-differ
        clean_distdir(self.parent.chroot)
        return 0


@GeniManage.subcommand("configure")
class GeniManageConfigure(cli.Application):
    """Configures portage and system
    """
    locale_gen = cli.SwitchAttr(["locale-gen"], str, list=True)
    locale = cli.SwitchAttr(["locale"], str)
    net_simple_names = cli.Flag(["net-simple-names"])
    timezone = cli.SwitchAttr(["timezone"], str)
    portage_profile = cli.SwitchAttr(["portage-profile"], str)
    portage_extras = cli.SwitchAttr(["portage-extras"])

    def main(self) -> int:  # pylint: disable=arguments-differ
        if self.timezone:
            configure_time_zone(self.parent.chroot, self.timezone)

        if self.locale_gen:
            generate_locales(self.parent.chroot, self.locale_gen)

        if self.locale:
            set_locale(self.parent.chroot, self.locale)

        if self.net_simple_names:
            configure_net_simple_names(self.parent.chroot_dir)

        if self.portage_profile:
            select_portage_profile(self.parent.chroot, self.portage_profile)

        if self.portage_extras:
            configure_portage_extras(self.parent.chroot_dir)

        return 0


@GeniManage.subcommand("sync-repo")
class GeniManageSyncRepo(cli.Application):
    def main(self) -> int:  # pylint: disable=arguments-differ
        sync_repo(self.parent.chroot)

        return 0


@GeniManage.subcommand("upgrade")
class GeniManageUpgrade(cli.Application):
    def main(self) -> int:  # pylint: disable=arguments-differ
        sync_repo(self.parent.chroot)
        upgrade_system(self.parent.chroot)

        return 0


@GeniManage.subcommand("emerge")
class GeniManageEmerge(cli.Application):
    def main(self, *packages: str) -> int:  # pylint: disable=arguments-differ
        emerge(self.parent.chroot, list(packages))

        return 0


@Geni.subcommand("chroot")
class GeniChroot(cli.Application):
    chroot_overlay = cli.SwitchAttr(["o", "chroot-overlay"],
                                    cli.ExistingDirectory)
    bind_repo = cli.SwitchAttr(["r", "bind-repo"],
                               cli.ExistingDirectory)

    xorg = cli.Flag(["X", "xorg"])

    refresh_gentoo_cache = cli.Flag("--refresh-gentoo-cache")

    @contextmanager
    def enter_chroot(self):
        with MountsManager(self.parent.chroot_dir) as mounts:
            if self.chroot_overlay:
                os.makedirs(self.chroot_overlay, exist_ok=True)
                chroot_overlay = OverlayMount(self.parent.chroot_dir,
                                              self.chroot_overlay)
                mounts.add(chroot_overlay)

            if self.bind_repo:
                # portageq get_repo_path / gentoo 2>/dev/null
                chroot_repo_dir = os.path.join(self.parent.chroot_dir,
                                               "usr",
                                               "portage")
                repo = BindMount(self.bind_repo, chroot_repo_dir)
                mounts.add(repo)

            if self.xorg:
                x11_unix_dir = "/tmp/.X11-unix"
                chroot_x11_unix_dir = os.path.join(self.parent.chroot_dir,
                                                   x11_unix_dir.lstrip("/"))
                os.makedirs(chroot_x11_unix_dir, exist_ok=True)
                mounts.add(BindMount(x11_unix_dir, chroot_x11_unix_dir))

            with self.parent.chroot as chroot_exec:
                if self.bind_repo and self.refresh_gentoo_cache:
                    chroot_exec(
                        '/etc/portage/repo.postsync.d/sync_gentoo_cache',
                        'gentoo',
                        '',
                        '/usr/portage')
                yield chroot_exec


@GeniChroot.subcommand("exec")
class GeniChrootExec(cli.Application):
    def main(self, *args) -> int:  # pylint: disable=arguments-differ
        with self.parent.enter_chroot() as chroot_exec:
            try:
                chroot_exec.fg(*args)
            except ProcessExecutionError as error:
                return error.retcode
        return 0


@GeniChroot.subcommand("run")
class GeniChrootRun(cli.Application):
    def main(self) -> int:  # pylint: disable=arguments-differ
        with self.parent.enter_chroot() as chroot_exec:
            try:
                chroot_exec.from_stdin()
            except ProcessExecutionError as error:
                return error.retcode
        return 0


@GeniChroot.subcommand("shell")
class GeniChrootShell(cli.Application):
    def main(self) -> int:  # pylint: disable=arguments-differ
        with self.parent.enter_chroot() as chroot_exec:
            try:
                chroot_exec.shell()
            except ProcessExecutionError as error:
                return error.retcode
        return 0
