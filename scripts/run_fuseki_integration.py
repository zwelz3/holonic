#!/usr/bin/env python3
"""Boot dockerized Apache Jena Fuseki, run the integration suite, tear down.

Wraps the three steps the Fuseki integration tests need into one command
with guaranteed cleanup (the container is always stopped, even if the tests
fail or the run is interrupted):

    docker compose -f docker-compose.fuseki.yml up -d --wait
    pytest --integration -m integration
    docker compose -f docker-compose.fuseki.yml down

Usage (pixi)::

    pixi run test-integration

Requires Docker (with the Compose plugin) on PATH. Exits non-zero if the
container fails to start or any integration test fails.
"""

from __future__ import annotations

import subprocess
import sys

COMPOSE = ["docker", "compose", "-f", "docker-compose.fuseki.yml"]
PYTEST = ["pytest", "--integration", "-m", "integration"]


def main() -> int:
    """Start Fuseki, run the integration suite, tear down; return its exit code."""
    try:
        up = subprocess.run([*COMPOSE, "up", "-d", "--wait"], check=False)
    except FileNotFoundError:
        print(
            "docker (with the compose plugin) is required for test-integration",
            file=sys.stderr,
        )
        return 127
    if up.returncode != 0:
        print("Fuseki container failed to become healthy", file=sys.stderr)
        subprocess.run([*COMPOSE, "down"], check=False)
        return up.returncode

    try:
        return subprocess.run(PYTEST, check=False).returncode
    finally:
        subprocess.run([*COMPOSE, "down"], check=False)


if __name__ == "__main__":
    sys.exit(main())
