--- 
title: Testing & Development
position: 2
description: "Development environment setup and contribution procedures for the Mosaico project. Covers local orchestration, database schema migration, and the test suite required before submitting changes."
---

This section outlines the standard procedures for contributing to the project. It covers local environment orchestration, database schema management, and the verification suite required to maintain code quality.

## Branches

### `main`

The only long-lived branch. All finished work lands here via pull request, for `mosaicod`, the SDK and the documentation. `main` must be in a releasable state at all times: every merged PR leaves it buildable, tested and ready to be tagged as a release.

### `issue/<num>`

Short-lived branches for a single feature or bug fix. Always branched from `main`, merged back via PR, then deleted.

Documentation ships with the code it describes. Every issue that changes a behavior, an API or a configuration includes the matching documentation changes in the same branch, so code and documentation are merged and released together.

## Developing the Daemon

The development lifecycle relies on a containerized infrastructure that includes a preconfigured **PostgreSQL** instance and a **VersityGW** S3 object store.

### Environment Setup

Initialize the required services using the provided docker compose file:

```bash
cd docker/devel
docker compose up -d
```

To configure the application for the development environment, initialize your local `.env` file:

```bash
cd mosaicod
cp env.devel .env
```

This configuration exports the `MOSAICOD_DB_URL`, database credentials, storage backend variables, and the `DATABASE_URL` required for compile-time query verification by [sqlx](https://github.com/launchbadge/sqlx).

### Update sqlx Queries Cache
If you modify SQL queries, you must refresh the offline metadata cache to allow the project to compile. This requires the sqlx command line tool, which can be installed with:

```bash
cargo install sqlx-cli
```

Run the following command to update the cache:

```bash
cd mosaicod/crates/mosaicod-db
cargo sqlx prepare -- --features postgres
```

### Apply Migrations

As detailed in the [Setup](../daemon/install.md) guide, the build process validates queries against the schema. Ensure your local database is synchronized with the latest migrations:

```bash 
cd mosaicod/crates/mosaicod-db
cargo sqlx migrate run
```

### Execution

You can execute the daemon directly from the source tree:

```bash
cd mosaicod
cargo run -- run [OPTIONS]
```

or compiled with:

```bash
cd mosaicod
cargo build --bin mosaicod --profile [PROFILE]
```

The current available prfiles are:

- `debug`: Default profile, optimized for development with debug symbols and no optimizations.
- `release`: Optimized for production, good amount of optimizations, smaller binary size, and few link-time optimizations but with no debug symbols.
- `docker`: As release but without link-time optimizations to reduce the binary size and speed up compilation. 
- `optimized`: Profile with high optimizations, slow to compile but with the best runtime performance. 

### Tests

Daemon specific test can be executed with:

```bash
cd mosaicod
cargo test
```

### Linting

Ensure compliance with the project's style guidelines and static analysis rules before submitting a pull request

```bash
cd mosaicod
cargo lint
```

## Developing the Python SDK

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) 0.13.1 or newer, then set up the SDK with Python 3.10 or newer:

```bash
cd mosaico-sdk-py
uv sync --locked --extra cli
uv run --locked --extra cli pre-commit install
uv run --locked --extra cli mosaico --help
```

uv creates a local `.venv` and installs the SDK, CLI extra, and development tools from `uv.lock`. Include `--extra cli` when running SDK commands so synchronization keeps the optional CLI dependencies installed. An existing Poetry environment can be replaced by running the same sync command; Poetry is no longer required.

Use `uv add PACKAGE` for runtime dependencies, `uv add --dev PACKAGE` for development tools, and `uv lock --upgrade-package PACKAGE` for a targeted update. Commit both `pyproject.toml` and `uv.lock` when changing dependencies. Build distributable packages with `uv build` from the SDK directory.

The Python documentation has its own environment and lockfile and requires Python 3.11 or newer:

```bash
cd docs/py # From the repository root
uv sync --locked
uv run --locked mkdocs build
```

## Testing

The project includes a comprehensive suite of unit and integration tests to validate functionality and prevent regressions.

The `justfile` at the repository root runs the test suites with [just](https://just.systems/man/en/), which we install with `brew install just` or `cargo install just`. Running `just` alone lists the recipes:

```bash
just test                        # All the tests
just test-mosaicod               # mosaicod tests
just test-sdk                    # Python SDK unit tests
just test-full-stack             # Full-stack tests, add --tls, --api-key or --gzip for a variant
just test-full-stack-all         # Full-stack tests in every variant
```

The recipes forward extra options to `cargo test` or pytest, e.g. `just test-sdk -x`. To test a built wheel instead of the sources, we set `wheel`:

```bash
uv build mosaico-sdk-py
just wheel=mosaico-sdk-py/dist/mosaicolabs-0.8.0-py3-none-any.whl test-sdk
```

The recipes only run the commands below, so we can also run them by hand, from the repository root.

### mosaicod

The `mosaicod` tests need the PostgreSQL database of `docker/testing`. We start it, run the tests, and then remove it with its data:

```bash
docker compose -f docker/testing/compose.yml up -d --wait
DATABASE_URL=postgresql://postgres:password@localhost:6543/mosaico SQLX_OFFLINE=true \
    cargo test --manifest-path mosaicod/Cargo.toml
docker compose -f docker/testing/compose.yml down -v
```

### Python SDK unit tests

The unit tests do not need a server:

```bash
cd mosaico-sdk-py
uv run --locked --extra cli pytest testing -k unit
```

### Full-stack tests

The full-stack tests run the Python SDK against a real `mosaicod`. With `--start-mosaicod`, pytest starts the databases of `docker/testing` and the `mosaicod` binary, and stops both at the end. Therefore they only need Docker and a `mosaicod` build:

```bash
cargo build --manifest-path mosaicod/Cargo.toml --bin mosaicod
cd mosaico-sdk-py
uv run --locked --extra cli pytest testing -k integration \
    --start-mosaicod --mosaicod-bin ../mosaicod/target/debug/mosaicod
```

Add `--tls`, `--gzip` or `--api-key` to start `mosaicod` with that feature enabled. Each run recreates the databases empty, so it also removes the data of a running `./scripts/dev_env`.

### Testing a wheel

By default, the Python SDK tests run against the sources. To test a built wheel instead, we install it in an isolated environment, so the tests import the SDK as users install it. `MOSAICO_TEST_WHEEL` makes the tests fail if the SDK is imported from the sources:

```bash
uv build mosaico-sdk-py
cd mosaico-sdk-py
MOSAICO_TEST_WHEEL=1 uv run --isolated --no-project \
    --with "$(ls "$PWD"/dist/mosaicolabs-*.whl)[cli]" --with pytest \
    pytest testing -k unit
```

The same command runs the full-stack tests with the options above. The release workflow tests the wheel of every release this way.

## Development Environment

The project provides a script that generates a disposable development environment. This environment launches a clean `mosaicod` instance without any data, allowing you to test and interact with the daemon without needing to set up your own data.

This is particularly useful when developing client applications or testing the API, as it provides a consistent and isolated environment for experimentation.

The environment can be launched with:

```bash
./scripts/dev_env
```

Use `--help` to see available options.
