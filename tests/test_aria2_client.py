"""Test aria2_client.py CLI script functionality with real torrent downloads."""

import json
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, List, Tuple

import pytest
import torf

# Constants
DEFAULT_CLI_TIMEOUT_SECONDS: int = 60
CLI_PROCESS_TIMEOUT_SECONDS: int = 45
SEEDER_READY_TIMEOUT_SECONDS: int = 10
TEST_PORT: int = 6802
EXPECTED_FILE_SIZE: int = 40 * 1024 * 1024  # 40MB
CLI_BASE_CMD: List[str] = [str(Path(__file__).parent.parent / "downpore_core" / "aria2_client.py"), "--port", str(TEST_PORT)]


@dataclass(frozen=True)
class CLIResult:
    """CLI command execution result."""

    returncode: int
    stdout: str
    stderr: str


class TestAria2ClientCLI:
    """Test aria2_client.py CLI script functionality."""

    @pytest.fixture
    def aria2_daemon(self) -> Generator[subprocess.Popen, None, None]:
        """Start aria2c daemon for testing."""
        with _aria2_daemon_context() as daemon:
            yield daemon

    def test_cli_port_parameter(self, aria2_daemon: subprocess.Popen) -> None:
        """Test that aria2_client.py accepts --port parameter."""
        result = _run_cli_command(["add", "--magnet-link", "magnet:?xt=urn:btih:test"])
        _assert_cli_failure(result, "Invalid magnet link format")

    def test_cli_torrent_file_with_local_tracker(
        self, aria2_daemon: subprocess.Popen
    ) -> None:
        """Test CLI download via .torrent file with local tracker."""
        print("\n=== STARTING CLI TORRENT FILE TEST ===")

        with _seeder_context() as (
            seeder_process,
            torrent_file,
            test_file,
            magnet_link,
        ):
            print(f"Test file: {test_file}")
            print(f"File size: {test_file.stat().st_size / 1024 / 1024:.1f} MB")

            _test_download_with_seeder(
                test_file,
                seeder_process,
                ["download", "--torrent-file", str(torrent_file)],
                f"CLI torrent file: {torrent_file}",
            )

    def test_cli_magnet_link_with_local_tracker(self) -> None:
        """Test CLI download via magnet link with local tracker."""
        print("\n=== STARTING CLI MAGNET LINK TEST ===")

        with _seeder_context() as (
            seeder_process,
            torrent_file,
            test_file,
            magnet_link,
        ):
            print(f"Test file: {test_file}")
            print(f"File size: {test_file.stat().st_size / 1024 / 1024:.1f} MB")


            print("Starting aria2c daemon...")
            with _aria2_daemon_context() as aria2_process:
                print("aria2c daemon started successfully")
                _test_download_with_seeder(
                    test_file,
                    seeder_process,
                    ["download", "--magnet-link", magnet_link],
                    f"CLI magnet link: {magnet_link[:60]}...",
                )

    def test_cli_invalid_magnet(self, aria2_daemon: subprocess.Popen) -> None:
        """Test CLI handles invalid magnet links properly."""
        result = _run_cli_command(["download", "--magnet-link", "invalid_magnet_link"])
        _assert_cli_failure(result, "Invalid magnet link format")

    def test_cli_connection_error(self) -> None:
        """Test CLI handles connection errors properly."""
        cmd = [
            str(Path(__file__).parent.parent / "downpore_core" / "aria2_client.py"),
            "--port",
            "9999",  # Port with no daemon
            "download",
            "--magnet-link",
            "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        assert result.returncode != 0


def _build_aria2_command(port: int, download_dir: str) -> List[str]:
    """Build aria2c command with configuration.

    Args:
        port: RPC listen port
        download_dir: Download directory

    Returns:
        List of command arguments for subprocess
    """
    return [
        "aria2c",
        "--enable-rpc",
        f"--rpc-listen-port={port}",
        "--dir",
        download_dir,
        "--seed-time=0",  # Don't seed after download
        "--check-integrity=false",  # Speed up testing
        "--allow-overwrite=true",
        "--split=16",
        "--enable-dht=true",  # Enable DHT for peer discovery
        "--bt-tracker-timeout=5",  # Longer tracker timeout
        "--follow-torrent=true",  # Auto start file download after metadata
        "--bt-tracker-connect-timeout=30",  # Longer tracker connect timeout
    ]


# Helper functions


def _run_cli_command(args: List[str], timeout: int = CLI_PROCESS_TIMEOUT_SECONDS) -> CLIResult:
    """Run CLI command with common setup."""
    cmd = CLI_BASE_CMD + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return CLIResult(result.returncode, result.stdout, result.stderr)


def _assert_cli_success(result: CLIResult) -> None:
    """Assert CLI command succeeded with valid JSON output."""
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    output_data = json.loads(result.stdout)
    assert output_data["success"] is True
    assert "torrent_hash" in output_data
    assert "files" in output_data
    assert len(output_data["files"]) > 0
    assert output_data["download_size"] == EXPECTED_FILE_SIZE
    assert output_data["download_complete"] is True


def _assert_cli_failure(result: CLIResult, expected_error: str) -> None:
    """Assert CLI command failed with expected error."""
    assert result.returncode != 0
    assert expected_error in result.stderr or expected_error in result.stdout


def _terminate_process(process: subprocess.Popen, timeout: int = 5) -> None:
    """Terminate process gracefully with fallback to kill."""
    if process and process.returncode is None:
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _wait_for_process(name: str, process: subprocess.Popen, duration: int) -> None:
    """Wait for process to start and log status."""
    print(f"Waiting {duration} seconds for {name} to start...")
    time.sleep(duration)

    if process.poll() is not None:
        stdout, _ = process.communicate()
        print(f"[{name}] Process exited. Output:")
        print(stdout)
    else:
        print(f"[{name}] Process is still running")


@contextmanager
def _aria2_daemon_context() -> Generator[subprocess.Popen, None, None]:
    """Context manager for aria2c daemon."""
    download_dir = tempfile.mkdtemp(prefix="aria2_cli_test_")
    cmd = _build_aria2_command(TEST_PORT, download_dir)

    print(f"Starting aria2c with command: {' '.join(cmd)}")
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    time.sleep(2)

    if process.poll() is not None:
        stdout, _ = process.communicate()
        raise RuntimeError(f"aria2c failed to start. Output: {stdout}")

    try:
        yield process
    finally:
        _terminate_process(process)
        shutil.rmtree(download_dir, ignore_errors=True)


@contextmanager
def _seeder_context() -> (
    Generator[Tuple[subprocess.Popen, Path, Path, str], None, None]
):
    """Simplified seeder context manager."""
    seeder_script = Path(__file__).parent.parent / "downpore_core" / "test_seeder.py"

    process = subprocess.Popen(
        [
            "python",
            str(seeder_script),
            "--size",
            "40",
            "--duration",
            "300",
            "--keep-files",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Wait for files to be created
    test_file, torrent_file = None, None
    for _ in range(SEEDER_READY_TIMEOUT_SECONDS):
        time.sleep(1)

        if process.poll() is not None:
            stdout, _ = process.communicate()
            raise RuntimeError(f"test_seeder failed. Output: {stdout}")

        temp_dirs = list(Path(tempfile.gettempdir()).glob("torrentp_test_*"))
        if temp_dirs:
            test_dir = sorted(temp_dirs, key=lambda p: p.stat().st_mtime)[-1]
            test_file = test_dir / "test_file_40mb.bin"
            torrent_file = test_dir / "test_file_40mb.torrent"

            if test_file.exists() and torrent_file.exists():
                torrent = torf.Torrent.read(torrent_file)
                magnet_link = str(torrent.magnet())
                print(
                    f"Seeder ready: {test_file} ({test_file.stat().st_size / 1024 / 1024:.1f} MB)"
                )
                break
    else:
        _terminate_process(process)
        raise RuntimeError(f"Seeder files not created within {SEEDER_READY_TIMEOUT_SECONDS} seconds")

    try:
        yield process, torrent_file, test_file, magnet_link
    finally:
        _terminate_process(process)
        if test_file and test_file.exists():
            temp_dir = test_file.parent
            if temp_dir.exists() and "torrentp_test_" in temp_dir.name:
                shutil.rmtree(temp_dir, ignore_errors=True)


def _test_download_with_seeder(
    test_file: Path,
    seeder_process: subprocess.Popen,
    cli_args: List[str],
    description: str,
) -> None:
    """Test CLI download with running seeder."""
    if seeder_process.poll() is not None:
        stdout, _ = seeder_process.communicate()
        pytest.fail(
            f"Seeder died early. Code: {seeder_process.returncode}. Output: {stdout}"
        )

    print(f"Starting CLI download via {description}")

    cmd_args = cli_args + ["--timeout", str(DEFAULT_CLI_TIMEOUT_SECONDS)]
    result = _run_cli_command(cmd_args)

    print(f"CLI return code: {result.returncode}")
    print(f"CLI stdout: {result.stdout}")
    print(f"CLI stderr: {result.stderr}")

    _assert_cli_success(result)
    print("CLI download completed successfully!")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
