# Geni

## Introduction

Geni is a command line [Gentoo][gen] installer. It follows [Gentoo AMD64
Handbook][genhb].

Geni bootstraps chroot by downloading and unpacking latest stage3. The
tarball is verified as [described in the Handbook][genhb1]. Geni can
perform initial configuration, but that mostly relies on configuration
files provided by the user to copy to `/etc` in the chroot.

The major feature of Geni is to allow user enter chroot (in multiple
sessions) with mounting all the necessary file systems and unmounting
after chroot is left. User can either enter interactive shell or just
execute commands as passed in arguments to `geni`.

[gen]: https://gentoo.org
[genhb]: https://wiki.gentoo.org/wiki/Handbook:AMD64 "Gentoo AMD64 Handbook"
[genhb1]: https://wiki.gentoo.org/wiki/Handbook:AMD64/Installation/Stage#Verifying_and_validating

## Purpose

The intended purpose of this tool is to be used by Qubes OS Gentoo
template builder. Any features included are driven by development of
Qubes OS Gentoo template builder.
