"""
Runs a mosaicod server for the integration tests, with `--start-mosaicod`.

The server uses the PostgreSQL instances of `docker/testing/compose.yml`, recreated empty
for each session, and keeps its data in a temporary folder of the pytest session.
"""

import functools
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

REPO_DIR = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_DIR / "docker" / "testing" / "compose.yml"

# Databases of `docker/testing/compose.yml`
DB_URL = "postgresql://localhost:6543/mosaico"
DB_TLS_URL = "postgresql://localhost:6544/mosaico?sslmode=require"
DB_USER = "postgres"
DB_PASSWORD = "password"

STORE_BUCKET = "mosaico-auto-testing"

# Certificates shared with the mosaicod tests
TLS_DATA_DIR = REPO_DIR / "mosaicod" / "tests" / "data"

# Permissions of the API keys created with `--api-key`
API_KEY_PERMISSIONS = {
    "read": "read",
    "write": "write",
    "delete": "delete",
    "manage": "read|write|delete",
}

# mosaicod runs the database migrations before listening, which can take a while on CI.
STARTUP_TIMEOUT = 60
SHUTDOWN_TIMEOUT = 10


class MosaicodError(Exception):
    """mosaicod or its databases failed to start, or one of its commands failed."""


@functools.cache
def docker_compose_command() -> List[str]:
    """The `docker compose` plugin, or the legacy `docker-compose` when it is missing."""
    try:
        plugin = subprocess.run(["docker", "compose", "version"], capture_output=True)
    except FileNotFoundError:
        raise MosaicodError("Docker is not installed.") from None
    if plugin.returncode == 0:
        return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    raise MosaicodError("Docker Compose is not installed.")


def docker_compose(*args: str) -> None:
    """Runs `docker compose` on the testing databases."""
    result = subprocess.run(
        [*docker_compose_command(), "-f", str(COMPOSE_FILE), *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise MosaicodError(
            f"`docker compose {' '.join(args)}` failed:\n{result.stderr.strip()}"
        )


def start_databases() -> None:
    """Starts the testing databases, empty, and waits until they are healthy."""
    stop_databases()
    docker_compose("up", "-d", "--wait")


def stop_databases() -> None:
    """Stops the testing databases and removes their data."""
    docker_compose("down", "-v")


@dataclass
class Mosaicod:
    """A mosaicod server started for the test session."""

    binary: str
    env: Dict[str, str]
    log_file: Path
    api_keys: Dict[str, str] = field(default_factory=dict)
    process: Optional[subprocess.Popen] = None

    @classmethod
    def configure(
        cls,
        binary: str,
        data_dir: Path,
        tls: bool,
        gzip: bool,
        api_key: bool,
    ) -> "Mosaicod":
        """Sets up the environment of the server, without starting it."""
        env = dict(os.environ)
        env.setdefault("RUST_LOG", "mosaico=trace")
        env.update(
            {
                "MOSAICOD_DB_URL": DB_TLS_URL if tls else DB_URL,
                "MOSAICOD_DB_USER": DB_USER,
                "MOSAICOD_DB_PASSWORD": DB_PASSWORD,
                "MOSAICOD_STORE_ENDPOINT": (data_dir / "store").as_uri(),
                "MOSAICOD_STORE_BUCKET": STORE_BUCKET,
                "MOSAICOD_TLS_ENABLED": str(tls).lower(),
                "MOSAICOD_GZIP_ENABLED": str(gzip).lower(),
                "MOSAICOD_API_KEY_ENABLED": str(api_key).lower(),
            }
        )
        if tls:
            env["MOSAICOD_TLS_CERT_FILE"] = str(TLS_DATA_DIR / "cert.pem")
            env["MOSAICOD_TLS_PRIVATE_KEY_FILE"] = str(TLS_DATA_DIR / "key.pem")

        (data_dir / "store").mkdir(parents=True, exist_ok=True)
        server = cls(binary=binary, env=env, log_file=data_dir / "mosaicod.log")

        if api_key:
            server.api_keys = {
                name: server.run("api-key", "create", "-p", permission)
                for name, permission in API_KEY_PERMISSIONS.items()
            }

        return server

    def run(self, *args: str) -> str:
        """Runs a mosaicod command with the server environment and returns its output."""
        # Without `RUST_LOG`, so the output is only the command's.
        result = subprocess.run(
            [self.binary, *args],
            env=self.env | {"RUST_LOG": ""},
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise MosaicodError(
                f"`mosaicod {' '.join(args)}` failed:\n{result.stderr.strip()}"
            )
        return result.stdout.strip()

    def start(self, host: str, port: int, log_to_terminal: bool = False) -> None:
        """Starts the server and waits until it accepts connections.

        The server logs to `log_file`, or to the terminal with `log_to_terminal`.
        """
        command = [self.binary, "server", "--port", str(port)]
        if log_to_terminal:
            self.process = subprocess.Popen(command, env=self.env)
        else:
            with open(self.log_file, "wb") as log:
                self.process = subprocess.Popen(
                    command, env=self.env, stdout=log, stderr=subprocess.STDOUT
                )

        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise MosaicodError(
                    f"mosaicod exited during startup with code {self.process.returncode}.\n"
                    f"{self.log_tail()}"
                )
            try:
                with socket.create_connection((host, port), timeout=1):
                    return
            except OSError:
                time.sleep(0.2)

        self.stop()
        raise MosaicodError(
            f"mosaicod did not accept connections on {host}:{port} "
            f"within {STARTUP_TIMEOUT} seconds.\n{self.log_tail()}"
        )

    def stop(self) -> None:
        """Stops the server, killing it if it does not exit in time."""
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

    def log_tail(self, lines: int = 20) -> str:
        """The last lines of the server log, to explain a failure."""
        if not self.log_file.exists():
            return "See the mosaicod output above."
        try:
            text = self.log_file.read_text(errors="replace")
        except OSError:
            return f"Cannot read the mosaicod log at {self.log_file}."
        tail = "\n".join(text.splitlines()[-lines:])
        return f"Last lines of {self.log_file}:\n{tail}"
