from collections import defaultdict
import hashlib
import logging
import os.path
import re
from typing import Dict, TextIO

import requests

from .util import join_url


class Downloader:
    CHUNK_SIZE = 10240

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.session = requests.Session()

    def join_url(self, path: str) -> str:
        return join_url(self.base_url, path)

    def download_into(self, remote_path: str, local_path: str) -> None:
        if os.path.exists(local_path):
            raise FileExistsError(local_path)

        response = self.session.get(self.join_url(remote_path), stream=True)

        with open(local_path, 'wb') as local_file:
            for chunk in response.iter_content(chunk_size=self.CHUNK_SIZE):
                if chunk:  # Filter out keep-alive new chunks.
                    local_file.write(chunk)

    def download_text(self, path: str) -> str:
        response = self.session.get(self.join_url(path))
        return response.text


class StageDownloader:
    def __init__(self, mirror_url: str, downloads_dir: str) -> None:
        autobuilds_path = "releases/amd64/autobuilds"
        self._downloader = Downloader(join_url(mirror_url, autobuilds_path))
        self.downloads_dir = downloads_dir
        os.makedirs(self.downloads_dir, exist_ok=True)

    def _download(self, stage_remote_path: str, suffix: str) -> str:
        stage_file_name = os.path.basename(stage_remote_path)
        target_file_path = os.path.join(self.downloads_dir,
                                        f"{stage_file_name}{suffix}")
        try:
            self._downloader.download_into(f"{stage_remote_path}{suffix}",
                                           target_file_path)
        except FileExistsError:
            logging.info("File already exists, skipping download: %s",
                         target_file_path)

        return target_file_path

    def find_latest(self) -> str:
        latest_stage_pointer = "latest-stage3-amd64.txt"
        content = self._downloader.download_text(latest_stage_pointer)
        lines = [line
                 for line in content.split("\n")
                 if line and not line.startswith('#')]

        if not lines:
            raise ValueError(f"Link file '{latest_stage_pointer}' is empty")
        if len(lines) > 1:
            raise ValueError(f"Link file '{latest_stage_pointer}' has "
                             f"more line than expected")

        try:
            return lines[0].split()[0]
        except IndexError:
            raise ValueError(f"Link file '{latest_stage_pointer}' has "
                             f"format different from expected")

    def download_digests(self, stage_remote_path: str) -> str:
        return self._download(stage_remote_path, ".DIGESTS.asc")

    def download_contents(self, stage_remote_path: str) -> str:
        return self._download(stage_remote_path, ".CONTENTS")

    def download_stage(self, stage_remote_path: str) -> str:
        return self._download(stage_remote_path, "")


class Digests:
    CHUNK_SIZE = 10240

    hash_header = re.compile(r"^\s*#+\s*(?P<hash_name>\S+)\s+HASH\s*$")
    hash_line = re.compile(r"^(?P<hash>[a-fA-F0-9]+)\s+(?P<file_name>\S+)$")

    @staticmethod
    def _absolute_path(base_path: str, file_rel_path: str) -> str:
        return os.path.abspath(os.path.join(base_path, file_rel_path))

    @classmethod
    def parse_digests(cls,
                      digests_file: TextIO) -> Dict[str, Dict[str, str]]:
        digests_dir = os.path.dirname(digests_file.name)
        hashes: dict = defaultdict(dict)

        line = digests_file.readline()
        while line:
            hash_header_match = cls.hash_header.match(line.strip())

            if hash_header_match:
                hash_name = hash_header_match.group("hash_name")

                while True:
                    line = digests_file.readline()
                    if not line:
                        break
                    hash_line_match = cls.hash_line.match(line.strip())
                    if not hash_line_match:
                        break

                    hash_ = hash_line_match.group("hash")
                    file_name = hash_line_match.group("file_name")
                    file_abs_path = cls._absolute_path(digests_dir, file_name)
                    hashes[hash_name][file_abs_path] = hash_.lower()
            else:
                line = digests_file.readline()

        return dict(hashes)

    def __init__(self, digests_path: str) -> None:
        with open(digests_path, "r") as digests_file:
            all_hashes = self.parse_digests(digests_file)

        self.algorithms_available = (hashlib.algorithms_available &
                                     all_hashes.keys())
        if not self.algorithms_available:
            raise ValueError("None of the following hashes are supported: {}"
                             .format(", ".join(all_hashes.keys())))
        self.hash_name = next(iter(self.algorithms_available))
        self.hashes = all_hashes[self.hash_name]

    def verify(self, file_name: str) -> bool:
        expected_hash = self.hashes[os.path.abspath(file_name)]
        hasher = hashlib.new(self.hash_name)
        with open(file_name, "rb") as file:
            while True:
                chunk = file.read(self.CHUNK_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)

        return hasher.hexdigest().lower() == expected_hash
