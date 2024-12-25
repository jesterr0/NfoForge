import bencode
import errno
import ssl
import xmlrpc
import xmlrpc.client
from pathlib import Path
from torf import Torrent

from src.config.config import Config
from src.exceptions import TrackerClientError


class Bunch(dict):
    """Generic attribute container that also acts as a dict."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'Bunch' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        self[name] = value

    def __repr__(self):
        return f"Bunch({', '.join(f'{k}={v!r}' for k, v in sorted(self.items()))})"


class RTorrent:
    def __init__(self, config: Config) -> None:
        """
        Example URI: "https://<user>:<password>@www.url.com/rutorrent/plugins/httprpc/action.php"
        """
        self.config = config
        self.rtorrent_config = config.cfg_payload.rtorrent

        if not self.rtorrent_config.host:
            raise TrackerClientError("Invalid host name")

        self.client = xmlrpc.client.Server(
            str(self.rtorrent_config.host), context=ssl._create_stdlib_context()
        )

    def inject_torrent(
        self, torrent_file: Path, file_path: Path, del_r_torrent: bool = False
    ) -> tuple[bool, str]:
        torrent_instance = self._get_torrent_obj(torrent_file)

        # Fast resume
        torrent_file = self._fast_resume(torrent_file, file_path)

        # Inject torrent
        self.client.load.raw_start_verbose("", *self._build_command(torrent_file))

        # Confirm injection
        if self.confirm_injection(torrent_instance.infohash):
            if del_r_torrent:
                torrent_file.unlink()
            return True, "Injected torrent to client"
        return False, "Failed to detect injection in the client"

    def confirm_injection(self, info_hash: str) -> bool:
        return bool(self.client.d.name(info_hash))

    def _build_command(self, torrent_file: Path) -> list:
        command = [xmlrpc.client.Binary(self._to_bytes(torrent_file))]
        if label := self.rtorrent_config.specific_params.get("label"):
            command.append(f"d.custom1.set={label}")
        if path := self.rtorrent_config.specific_params.get("path"):
            command.append(f"d.directory.set={path}")
        return command

    def _fast_resume(self, torrent_file: Path, file_path: Path) -> Path:
        try:
            metainfo = bencode.bread(torrent_file)
            fast_resume = self._add_fast_resume(metainfo, file_path)
            new_meta = bencode.bencode(fast_resume)

            if new_meta != metainfo:
                torrent_file = torrent_file.with_name(torrent_file.stem + "_r.torrent")
                bencode.bwrite(fast_resume, torrent_file)
            return torrent_file
        except EnvironmentError as e:
            raise TrackerClientError(f"Error making fast-resume data: {e}") from e
        except Exception as exc_e:
            raise TrackerClientError(
                f"Unknown error making fast-resume data: {exc_e}"
            ) from exc_e

    def _add_fast_resume(self, metainfo: bencode, data_path: Path) -> bencode:
        """
        Add fast resume data to a metafile dict using pathlib.
        Thanks L4G for the original code: https://github.com/L4GSP1KE/Upload-Assistant
        """
        data_path = Path(data_path)
        files = metainfo["info"].get("files", None)
        single = files is None

        if single:
            if data_path.is_dir():
                data_path = data_path / metainfo["info"]["name"]
            files = [
                Bunch(
                    path=[str(data_path.resolve())], length=metainfo["info"]["length"]
                )
            ]

        resume = metainfo.setdefault("libtorrent_resume", {})
        resume["bitfield"] = len(metainfo["info"]["pieces"]) // 20
        resume["files"] = []

        piece_length = metainfo["info"]["piece length"]
        offset = 0

        for file_info in files:
            filepath = Path(*file_info["path"])
            if not single:
                filepath = data_path / filepath.relative_to(filepath.anchor)

            # Validate file size
            try:
                file_stat = filepath.stat()
                if file_stat.st_size != file_info["length"]:
                    raise OSError(
                        errno.EINVAL,
                        f"File size mismatch for {filepath}: is {file_stat.st_size}, expected {file_info['length']}",
                    )
            except FileNotFoundError:
                raise FileNotFoundError(f"File not found: {filepath}")

            resume["files"].append(
                {
                    "priority": 1,
                    "mtime": int(file_stat.st_mtime),
                    "completed": (offset + file_info["length"] + piece_length - 1)
                    // piece_length
                    - offset // piece_length,
                }
            )
            offset += file_info["length"]

        return metainfo

    @staticmethod
    def _to_bytes(torrent_file: Path) -> bytes:
        with open(torrent_file, "rb") as t_file:
            return t_file.read()

    @staticmethod
    def _get_torrent_obj(torrent_file: Path) -> Torrent:
        return Torrent.read(torrent_file)
