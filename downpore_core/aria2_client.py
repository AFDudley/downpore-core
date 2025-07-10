#!/usr/bin/env python3
"""Simple aria2 client that assumes SSH tunnel is already established by Ansible.

This script connects to aria2 daemon via localhost:6800 and provides
a clean CLI interface for torrent operations. SSH tunneling is handled
by Ansible, not this script.
"""

import json
import re
import sys
import time
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

import aria2p


@dataclass(frozen=True)
class Aria2Config:
    """Immutable aria2 daemon configuration."""

    rpc_port: int = 6800
    download_dir: str = "~/downloads"


@dataclass(frozen=True)
class TorrentStatus:
    """Immutable torrent status information - matches rtorrent_client interface."""

    hash: str
    name: str
    size_bytes: int
    completed_bytes: int
    download_rate: int
    is_complete: bool
    is_active: bool
    error_message: Optional[str]

    @property
    def progress_percent(self) -> float:
        """Calculate download progress as percentage."""
        if self.size_bytes == 0:
            return 0.0
        return (self.completed_bytes / self.size_bytes) * 100.0


class Aria2Client:
    """Simple aria2 client that connects to localhost (SSH tunnel managed by Ansible)."""

    def __init__(self, port: int = 6800) -> None:
        self._port = port
        self._api: Optional[aria2p.API] = None

    def __enter__(self) -> "Aria2Client":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()

    def connect(self) -> None:
        """Connect to aria2 daemon via localhost (SSH tunnel assumed established)."""
        # Create aria2p API client - Ansible handles SSH tunnel
        client = aria2p.Client(
            host="http://127.0.0.1", port=self._port, secret="changeme123"
        )
        self._api = aria2p.API(client)

        # Test connection
        self._api.get_global_options()

    def disconnect(self) -> None:
        """Clean up API connection."""
        self._api = None

    def add_torrent(self, magnet_link: str, download_dir: Optional[str] = None) -> str:
        """Add torrent from magnet link and return GID."""
        if not self._validate_magnet_link(magnet_link):
            raise ValueError("Invalid magnet link format")

        if not self._api:
            raise RuntimeError("Not connected to aria2")

        # Add magnet link - aria2p handles the complexity
        download = self._api.add_magnet(magnet_link)
        return download.gid

    def add_torrent_file(
        self, torrent_file: str, download_dir: Optional[str] = None
    ) -> str:
        """Add torrent from .torrent file and return GID."""
        if not self._api:
            raise RuntimeError("Not connected to aria2")

        # Add torrent file - aria2p handles the complexity
        download = self._api.add_torrent(torrent_file)
        return download.gid

    def get_status(self, torrent_gid: str) -> TorrentStatus:
        """Get current status of torrent."""
        if not self._api:
            raise RuntimeError("Not connected to aria2")

        all_downloads = self._api.get_downloads()

        # First try to find a completed non-metadata download (for magnet links)
        for d in all_downloads:
            if d.is_complete and not d.is_metadata:
                d.update()
                return TorrentStatus(
                    hash=d.gid,  # Use GID as hash equivalent
                    name=d.name or "",
                    size_bytes=d.total_length,
                    completed_bytes=d.completed_length,
                    download_rate=d.download_speed,
                    is_complete=d.is_complete,
                    is_active=d.is_active,
                    error_message=d.error_message if d.has_failed else None,
                )

        # Fallback: find download by original GID
        for d in all_downloads:
            if d.gid == torrent_gid:
                d.update()
                return TorrentStatus(
                    hash=d.gid,  # Use GID as hash equivalent
                    name=d.name or "",
                    size_bytes=d.total_length,
                    completed_bytes=d.completed_length,
                    download_rate=d.download_speed,
                    is_complete=d.is_complete,
                    is_active=d.is_active,
                    error_message=d.error_message if d.has_failed else None,
                )

        raise RuntimeError(f"Torrent with GID {torrent_gid} not found")

    def wait_for_completion(self, torrent_gid: str, timeout: int = 3600) -> bool:
        """Wait for torrent to complete download."""
        if not self._api:
            raise RuntimeError("Not connected to aria2")

        start_time = time.time()

        while time.time() - start_time < timeout:
            # Get all downloads to find the actual file download (not metadata)
            all_downloads = self._api.get_downloads()

            # For magnet links, aria2 creates multiple downloads
            # Find the one that's complete and not metadata
            for download in all_downloads:
                if download.has_failed:
                    raise RuntimeError(f"Download failed: {download.error_message}")

                # Check if this is the actual file download (not metadata)
                if download.is_complete and not download.is_metadata:
                    return True

            time.sleep(5)  # Check every 5 seconds

        raise TimeoutError(f"Torrent not completed within {timeout} seconds")

    def get_files(self, torrent_gid: str) -> List[str]:
        """Get list of files in completed torrent."""
        if not self._api:
            raise RuntimeError("Not connected to aria2")

        # For magnet links, find the completed non-metadata download
        all_downloads = self._api.get_downloads()
        for download in all_downloads:
            if download.is_complete and not download.is_metadata and download.files:
                return [str(f.path) for f in download.files]

        # Fallback: try to find by GID
        for download in all_downloads:
            if download.gid == torrent_gid and download.files:
                return [str(f.path) for f in download.files]

        return []

    def remove_torrent(self, torrent_gid: str, delete_files: bool = False) -> None:
        """Remove torrent from aria2."""
        if not self._api:
            raise RuntimeError("Not connected to aria2")

        # Find download by GID
        download = None
        for d in self._api.get_downloads():
            if d.gid == torrent_gid:
                download = d
                break

        if download:
            download.remove(force=delete_files)

    def _validate_magnet_link(self, magnet_link: str) -> bool:
        """Validate magnet link format."""
        return bool(re.match(r"^magnet:\?xt=urn:btih:[a-fA-F0-9]{40}", magnet_link))


def main():
    """CLI entry point for Ansible script execution."""
    import argparse

    parser = argparse.ArgumentParser(description="aria2 JSON-RPC client operations")
    parser.add_argument(
        "action", choices=["add", "status", "wait", "files", "remove", "download"]
    )
    parser.add_argument(
        "--port", type=int, default=6800, help="Local port for aria2 connection"
    )
    parser.add_argument("--magnet-link", help="Magnet link for add/download actions")
    parser.add_argument(
        "--torrent-file", help="Torrent file path for add/download actions"
    )
    parser.add_argument(
        "--torrent-hash", help="Torrent GID for status/wait/files/remove"
    )
    parser.add_argument(
        "--download-dir", default="~/downloads", help="Download directory"
    )
    parser.add_argument(
        "--timeout", type=int, default=3600, help="Timeout for wait action"
    )
    parser.add_argument(
        "--delete-files", action="store_true", help="Delete files when removing"
    )

    args = parser.parse_args()
    result: Dict[str, Any] = {}

    with Aria2Client(port=args.port) as client:
        client.connect()

        if args.action == "add":
            if args.magnet_link:
                gid = client.add_torrent(args.magnet_link, args.download_dir)
            elif args.torrent_file:
                gid = client.add_torrent_file(args.torrent_file, args.download_dir)
            else:
                raise ValueError(
                    "Either --magnet-link or --torrent-file required for add action"
                )
            status = client.get_status(gid)
            result = {
                "success": True,
                "torrent_hash": gid,  # Use GID as hash
                "status": _status_to_dict(status),
            }

        elif args.action == "status":
            if not args.torrent_hash:
                raise ValueError("--torrent-hash required for status action")
            status = client.get_status(args.torrent_hash)
            result = {"success": True, "status": _status_to_dict(status)}

        elif args.action == "wait":
            if not args.torrent_hash:
                raise ValueError("--torrent-hash required for wait action")
            completed = client.wait_for_completion(args.torrent_hash, args.timeout)
            final_status = client.get_status(args.torrent_hash)
            result = {
                "success": True,
                "completed": completed,
                "final_status": _status_to_dict(final_status),
            }

        elif args.action == "files":
            if not args.torrent_hash:
                raise ValueError("--torrent-hash required for files action")
            files = client.get_files(args.torrent_hash)
            result = {"success": True, "files": files}

        elif args.action == "remove":
            if not args.torrent_hash:
                raise ValueError("--torrent-hash required for remove action")
            client.remove_torrent(args.torrent_hash, args.delete_files)
            result = {
                "success": True,
                "removed": True,
                "deleted_files": args.delete_files,
            }

        elif args.action == "download":
            # Complete download workflow for Ansible - matches rtorrent interface
            if args.magnet_link:
                gid = client.add_torrent(args.magnet_link, args.download_dir)
            elif args.torrent_file:
                gid = client.add_torrent_file(args.torrent_file, args.download_dir)
            else:
                raise ValueError(
                    "Either --magnet-link or --torrent-file required for download action"
                )
            client.wait_for_completion(gid, args.timeout)
            final_status = client.get_status(gid)
            files = client.get_files(gid)

            result = {
                "success": True,
                "torrent_hash": gid,
                "torrent_name": final_status.name,
                "files": files,
                "remote_file_path": files[0] if files else None,
                "download_size": final_status.size_bytes,
                "download_complete": final_status.is_complete,
            }

    print(json.dumps(result, indent=2))


def _status_to_dict(status: TorrentStatus) -> Dict[str, Any]:
    """Convert TorrentStatus to dictionary for JSON output."""
    return {
        "hash": status.hash,
        "name": status.name,
        "size_bytes": status.size_bytes,
        "completed_bytes": status.completed_bytes,
        "download_rate": status.download_rate,
        "is_complete": status.is_complete,
        "is_active": status.is_active,
        "error_message": status.error_message,
        "progress_percent": status.progress_percent,
    }


if __name__ == "__main__":
    main()
