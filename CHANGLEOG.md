# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog][kchng], and this project
adheres to [PEP 440 -- Version Identification and Dependency
Specification][pep440].

[kchng]: https://keepachangelog.com/en/1.0.0/
[pep440]: https://www.python.org/dev/peps/pep-0440/


## [Unreleased]

### Fixed

- Update expired GPG keys. Gentoo Releng key (that is kept in Geni
  package) to verify tarballs digests was expired.


## [0.1.0.dev2] - 2019-08-22

### Fixed

- Fix error saying that none of hashes are supported: SHA512, WHIRLPOOL.
  The error occurs with Python 3.7 only.


## [0.1.0.dev1] - 2019-08-15

### Added

- Bootstrap Gentoo chroot from latest stage3 tarball.
- Install tree of config files into /etc.
- Configure: locale, network simple names (e.g. "eth0"), portage profile.
- Sync portage tree with webrsync.
- Upgrade system.
- Install specified packages.
- Execute arbitrary command.
- Enter interactive shell.
