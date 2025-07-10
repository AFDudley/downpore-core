"""Test data generation for aria2_client testing."""

import os
import tempfile
from pathlib import Path
from typing import Tuple

import torf


def create_test_torrent(size_mb: int = 40) -> Tuple[Path, str]:
    """Create test file and torrent, return file path and magnet link.

    Args:
        size_mb: Size of test file in megabytes

    Returns:
        Tuple of (test_file_path, magnet_link)
    """
    # Create temporary directory for test files
    temp_dir = Path(tempfile.mkdtemp(prefix="torrentp_test_"))

    # Generate random test file
    test_file = temp_dir / f"test_file_{size_mb}mb.bin"
    with open(test_file, "wb") as f:
        f.write(os.urandom(size_mb * 1024 * 1024))

    # Create torrent with DHT (no trackers)
    torrent = torf.Torrent(
        path=test_file,
        trackers=[],  # DHT-only
        piece_size=32768,  # 32KB pieces
        comment=f"Test torrent for aria2_client - {size_mb}MB",
        private=False,  # Allow DHT
    )

    # Generate torrent file
    torrent.generate()

    # Save .torrent file
    torrent_file = temp_dir / f"test_file_{size_mb}mb.torrent"
    torrent.write(torrent_file)

    # Get magnet link
    magnet_link = torrent.magnet()

    return test_file, str(magnet_link)


def cleanup_test_data(test_file_path: Path) -> None:
    """Clean up test files and directory.

    Args:
        test_file_path: Path to the test file (directory will be removed)
    """
    import shutil

    # Remove entire temporary directory
    temp_dir = test_file_path.parent
    if temp_dir.exists() and "torrentp_test_" in temp_dir.name:
        shutil.rmtree(temp_dir, ignore_errors=True)
