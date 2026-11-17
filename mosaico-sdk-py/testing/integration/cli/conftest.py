import pytest
from typer.testing import CliRunner


@pytest.fixture(scope="session")
def cli_runner():
    return CliRunner()


@pytest.fixture(scope="session")
def cli_env(tmp_path_factory, host, port, api_key_manage, with_tls, tls_cert_path):
    env = {
        "MOSAICO_DAEMON_URL": f"{host}:{port}",
        # A missing config file, so the profiles of the user (e.g. the default one that
        # `just dev` configures) do not change the connection of the tests.
        "MOSAICO_CONFIG_PATH": str(tmp_path_factory.mktemp("cli") / "config.toml"),
    }
    if api_key_manage:
        env["MOSAICO_API_KEY"] = api_key_manage
    if with_tls:
        env["MOSAICO_TLS"] = "true"
    if tls_cert_path:
        env["MOSAICO_CERT_PATH"] = tls_cert_path
    return env
