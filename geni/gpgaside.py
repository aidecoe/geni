import logging
import os

from plumbum import local
from plumbum.cmd import gpg  # pylint: disable=import-error

from .util import drop_prefix


class GpgAside:
    def __init__(self, gpg_home: str) -> None:
        self.gpg_home = gpg_home
        os.makedirs(gpg_home, exist_ok=True)
        os.chmod(gpg_home, mode=0o700)

    def _call(self, *args) -> bool:
        with local.env(GNUPGHOME=self.gpg_home):
            output = gpg[args].run(retcode=None)
            level = logging.INFO if output[0] == 0 else logging.FATAL
            for line in output[2].split("\n"):
                logging.log(level,
                            "gpg[%s] %s",
                            self.gpg_home,
                            drop_prefix("gpg: ", line))
            return output[0] == 0

    def recv_keys(self, *pub_key_ids: str) -> bool:
        return all([self._call("--recv-key", pub_key_id)
                    for pub_key_id in pub_key_ids])

    def import_pub_keys(self, *pub_key_paths: str) -> bool:
        return all([self._call("--import", path)
                    for path in pub_key_paths])

    def verify(self, path: str) -> bool:
        return self._call("--verify", path)
