#!/usr/bin/env python3
"""Proper torrent seeder using libtorrent-rasterbar.

This creates a real BitTorrent seeder that can share files with other peers.
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import libtorrent as lt
except ImportError:
    print("ERROR: libtorrent-rasterbar is required for seeding")
    print("Install with: pip install libtorrent")
    sys.exit(1)

try:
    from pybtracker import TrackerServer
except ImportError:
    print("ERROR: pybtracker is required for local tracking")
    print("Install with: pip install pybtracker")
    sys.exit(1)

import torf

from test_data import create_test_torrent, cleanup_test_data


class TorrentSeeder:
    """BitTorrent seeder using libtorrent with local tracker."""

    def __init__(
        self,
        torrent_file: Path,
        data_dir: Path,
        listen_port: int = 6881,
        tracker_port: int = 6889,
    ):
        """Initialize seeder.

        Args:
            torrent_file: Path to .torrent file
            data_dir: Directory containing the file to seed
            listen_port: Port to listen on for BitTorrent connections
            tracker_port: Port for local UDP tracker
        """
        self.torrent_file = torrent_file
        self.data_dir = data_dir
        self.listen_port = listen_port
        self.tracker_port = tracker_port
        self.session: Optional[lt.session] = None
        self.handle: Optional[lt.torrent_handle] = None
        self.tracker: Optional[TrackerServer] = None

    async def start(self) -> None:
        """Start the seeder and local tracker."""
        print(f"Starting seeder on port {self.listen_port}")
        print(f"Starting local tracker on port {self.tracker_port}")

        # Start local UDP tracker
        loop = asyncio.get_event_loop()
        self.tracker = TrackerServer(
            local_addr=("127.0.0.1", self.tracker_port), loop=loop
        )
        asyncio.ensure_future(self.tracker.start())

        # Give tracker time to start
        await asyncio.sleep(1)

        # Create session with default settings
        self.session = lt.session()

        # Set listen port range
        self.session.listen_on(self.listen_port, self.listen_port + 10)

        # Enable DHT (but we'll primarily use local tracker)
        self.session.start_dht()

        # Load torrent
        with open(self.torrent_file, "rb") as f:
            torrent_data = f.read()

        torrent_info = lt.torrent_info(torrent_data)

        # Add torrent for seeding
        add_params = {
            "ti": torrent_info,
            "save_path": str(self.data_dir),
            "flags": lt.add_torrent_params_flags_t.flag_seed_mode,  # Seed mode
        }

        self.handle = self.session.add_torrent(add_params)
        print(f"Added torrent: {torrent_info.name()}")
        print(f"Info hash: {torrent_info.info_hash()}")

        # Force recheck to verify we have the file
        self.handle.force_recheck()

    async def stop(self) -> None:
        """Stop the seeder and tracker."""
        if self.handle:
            self.session.remove_torrent(self.handle)
        if self.session:
            del self.session
        if self.tracker:
            await self.tracker.stop()

    def get_status(self) -> dict:
        """Get seeder status."""
        if not self.handle:
            return {"status": "not_started"}

        status = self.handle.status()
        return {
            "status": str(status.state),
            "progress": status.progress,
            "upload_rate": status.upload_rate,
            "download_rate": status.download_rate,
            "num_peers": status.num_peers,
            "num_seeds": status.num_seeds,
            "total_uploaded": status.total_upload,
            "total_downloaded": status.total_download,
        }

    async def seed_for_duration(self, duration_seconds: Optional[int] = None) -> None:
        """Seed for specified duration.

        Args:
            duration_seconds: How long to seed (None = forever)
        """
        print("Seeding started...")
        start_time = time.time()

        try:
            while True:
                status = self.get_status()
                elapsed = time.time() - start_time

                print(
                    f"[{elapsed:.0f}s] Status: {status['status']} | "
                    f"Peers: {status['num_peers']} | "
                    f"Upload: {status['upload_rate'] / 1024:.1f} KB/s | "
                    f"Uploaded: {status['total_uploaded'] / 1024 / 1024:.1f} MB"
                )

                if duration_seconds and elapsed >= duration_seconds:
                    print(f"Seeding completed after {duration_seconds} seconds")
                    break

                await asyncio.sleep(5)

        except KeyboardInterrupt:
            print("\\nSeeding stopped by user")


def create_torrent_file(test_file: Path, tracker_port: int = 6889) -> Path:
    """Create .torrent file for the test file with local tracker.

    Args:
        test_file: Path to file to create torrent from
        tracker_port: Port of local tracker

    Returns:
        Path to created .torrent file
    """
    torrent_file = test_file.with_suffix(".torrent")

    if torrent_file.exists():
        torrent_file.unlink()

    torrent = torf.Torrent(
        path=test_file,
        trackers=[f"udp://127.0.0.1:{tracker_port}/announce"],  # Local UDP tracker
        piece_size=32768,  # 32KB pieces
        private=False,  # Allow DHT as backup
        comment="Test torrent for aria2 testing with local tracker",
    )

    torrent.generate()
    torrent.write(torrent_file)

    return torrent_file


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Seed a torrent using libtorrent")
    parser.add_argument(
        "--size", type=int, default=40, help="Size of test file in MB (default: 40)"
    )
    parser.add_argument(
        "--duration", type=int, help="Seed duration in seconds (default: unlimited)"
    )
    parser.add_argument(
        "--port", type=int, default=6881, help="BitTorrent listen port (default: 6881)"
    )
    parser.add_argument(
        "--keep-files", action="store_true", help="Keep test files after seeding"
    )
    parser.add_argument(
        "--existing-file",
        type=Path,
        help="Use existing file instead of creating new one",
    )
    parser.add_argument(
        "--magnet-file",
        type=Path,
        help="Write magnet link to this file",
    )

    args = parser.parse_args()

    if args.existing_file:
        # Use existing file
        test_file = args.existing_file
        if not test_file.exists():
            print(f"ERROR: File not found: {test_file}")
            sys.exit(1)
        # Don't cleanup if using existing file
        cleanup = False
    else:
        # Create new test file
        print(f"Creating {args.size}MB test file...")
        test_file, magnet_link = create_test_torrent(size_mb=args.size)
        print(f"Magnet link: {magnet_link}")
        cleanup = not args.keep_files

    try:
        # Create torrent file with local tracker
        tracker_port = args.port + 8  # Use port + 8 for tracker (e.g., 6881 + 8 = 6889)
        torrent_file = create_torrent_file(test_file, tracker_port)

        # Generate magnet link from torrent file
        import torf

        torrent = torf.Torrent.read(torrent_file)
        magnet_link = str(torrent.magnet())

        # Write magnet link to file if requested
        if args.magnet_file:
            with open(args.magnet_file, "w") as f:
                f.write(magnet_link)
            print(f"Magnet link written to: {args.magnet_file}")

        print(f"\\nFile: {test_file}")
        print(f"Size: {test_file.stat().st_size / 1024 / 1024:.1f} MB")
        print(f"Torrent: {torrent_file}")
        print(f"Magnet: {magnet_link}")
        print(f"Local tracker: udp://127.0.0.1:{tracker_port}/announce")
        print("=" * 60)

        # Start seeder with local tracker
        seeder = TorrentSeeder(torrent_file, test_file.parent, args.port, tracker_port)
        await seeder.start()

        # Seed for specified duration
        await seeder.seed_for_duration(args.duration)

    finally:
        if "seeder" in locals():
            await seeder.stop()
        if cleanup:
            print("\\nCleaning up test files...")
            cleanup_test_data(test_file)
        else:
            print(f"\\nTest files kept at: {test_file.parent}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\\nSeeder stopped by user")
        sys.exit(0)
