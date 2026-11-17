# Mosaico development commands. Run `just` to list them.
#
# The Python SDK recipes test the sources. To test a built wheel instead, set `wheel`:
#
#     just wheel=mosaico-sdk-py/dist/mosaicolabs-0.8.0-py3-none-any.whl test-sdk

# Path of the wheel to test, empty to test the sources
wheel := ""

compose_file := "docker/testing/compose.yml"
# Cargo profile of the mosaicod build, e.g. `just profile=release dev`
profile := "dev"
target_dir := if profile == "dev" { "debug" } else { profile }
mosaicod_bin := justfile_directory() / "mosaicod/target" / target_dir / "mosaicod"

# The `docker compose` plugin, or the legacy `docker-compose` when it is missing
compose := if `docker compose version >/dev/null 2>&1 && echo plugin || echo legacy` == "plugin" { "docker compose" } else { "docker-compose" }

# Runs pytest from the SDK directory, against the sources or the wheel. With a wheel,
# MOSAICO_TEST_WHEEL makes the tests fail if the SDK is imported from the sources.
pytest := if wheel == "" { "uv run --locked --extra cli pytest" } else { "MOSAICO_TEST_WHEEL=1 uv run --isolated --no-project --with '" + absolute_path(wheel) + "[cli]' --with pytest pytest" }

[private]
default:
    @just --list

# Run all the tests
test: test-mosaicod test-sdk test-full-stack-all

# Run the mosaicod tests on new testing databases
test-mosaicod *options:
    {{ compose }} -f {{ compose_file }} down -v
    {{ compose }} -f {{ compose_file }} up -d --wait
    cd mosaicod && DATABASE_URL=postgresql://postgres:password@localhost:6543/mosaico \
        SQLX_OFFLINE=true cargo test {{ options }}
    {{ compose }} -f {{ compose_file }} down -v

# Run the Python SDK unit tests
test-sdk *options:
    cd mosaico-sdk-py && {{ pytest }} testing -k unit {{ options }}

# Run the full-stack tests, with `--tls`, `--api-key` or `--gzip` for a variant
test-full-stack *options: build-mosaicod
    cd mosaico-sdk-py && {{ pytest }} testing -k integration \
        --start-mosaicod --mosaicod-bin {{ mosaicod_bin }} {{ options }}

# Run the full-stack tests in every variant
test-full-stack-all: build-mosaicod
    just wheel='{{ wheel }}' profile='{{ profile }}' test-full-stack
    just wheel='{{ wheel }}' profile='{{ profile }}' test-full-stack --tls
    just wheel='{{ wheel }}' profile='{{ profile }}' test-full-stack --api-key
    just wheel='{{ wheel }}' profile='{{ profile }}' test-full-stack --gzip

# Run a disposable mosaicod on empty databases, removed on Ctrl-C. Options: `--tls`, `--api-key`
dev *options: build-mosaicod
    cd mosaico-sdk-py && uv run --locked --extra cli python -m testing.dev_env \
        --mosaicod-bin {{ mosaicod_bin }} {{ options }}

# Build the mosaicod binary used by the full-stack tests and `dev`
build-mosaicod:
    cd mosaicod && cargo build --profile {{ profile }} --bin mosaicod
