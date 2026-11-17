"""
A disposable development environment: mosaicod on empty databases, removed when it stops.

Run it with `just dev`, optionally with `--tls` and `--api-key`. With either option, it also
configures the `dev` profile of the `mosaico` CLI and makes it the default.
"""

import argparse
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .mosaicod import (
    TLS_DATA_DIR,
    Mosaicod,
    MosaicodError,
    start_databases,
    stop_databases,
)

HOST = "localhost"
PORT = 6276
CLI_PROFILE = "dev"


def configure_cli_profile(api_key: Optional[str], tls: bool) -> None:
    """Makes the `dev` profile of the `mosaico` CLI, set as default, point to the server."""
    subprocess.run(
        ["mosaico", "profile", "remove", CLI_PROFILE, "--force"], capture_output=True
    )
    command = [
        "mosaico", "profile", "add", CLI_PROFILE,
        "--no-interactive", "--force", "--default",
        "--host", HOST, "--port", str(PORT),
    ]  # fmt: skip
    if api_key:
        command += ["--api-key", api_key]
    if tls:
        command += ["--tls", "--cert-path", str(TLS_DATA_DIR / "ca.pem")]
    subprocess.run(command, check=True)


def run(mosaicod_bin: str, tls: bool, api_key: bool) -> None:
    """Runs mosaicod until it exits or Ctrl-C stops it."""
    with tempfile.TemporaryDirectory(prefix="mosaico-dev-") as data_dir:
        server = Mosaicod.configure(
            binary=mosaicod_bin,
            data_dir=Path(data_dir),
            tls=tls,
            gzip=False,
            api_key=api_key,
        )

        if api_key:
            print(f"API key (read, write and delete): {server.api_keys['manage']}")
        if tls:
            print(f"Client certificate: {TLS_DATA_DIR / 'ca.pem'}")
        if api_key or tls:
            configure_cli_profile(server.api_keys.get("manage"), tls)
            print(f"The '{CLI_PROFILE}' profile of the mosaico CLI uses this server.")

        try:
            server.start(HOST, PORT, log_to_terminal=True)
            print(f"mosaicod is listening on {HOST}:{PORT}, press Ctrl-C to stop it.")
            server.process.wait()
        except KeyboardInterrupt:
            pass
        finally:
            # A second Ctrl-C must not stop the cleanup, or the databases keep their data.
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            server.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--mosaicod-bin", required=True, help="Path to mosaicod")
    parser.add_argument("--tls", action="store_true", help="Enable TLS")
    parser.add_argument(
        "--api-key", action="store_true", help="Enable API keys and create one"
    )
    args = parser.parse_args()

    # Keeps our messages in order with the mosaicod output, also when piped.
    sys.stdout.reconfigure(line_buffering=True)

    try:
        start_databases()
        run(args.mosaicod_bin, args.tls, args.api_key)
    except KeyboardInterrupt:
        pass
    except MosaicodError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        stop_databases()
        print("Removed the databases.")


if __name__ == "__main__":
    main()
