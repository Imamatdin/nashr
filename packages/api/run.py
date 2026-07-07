"""Uvicorn entry point: ``python -m packages.api.run`` (compose `api` service)."""

from __future__ import annotations

import os

import uvicorn

from packages.api.app import create_app


def main() -> None:
    """Serve the API on API_PORT (default 8090; Caddy terminates TLS in front)."""

    port_raw = os.environ.get("API_PORT", "8090")
    port = int(port_raw) if port_raw.isdigit() else 8090
    uvicorn.run(create_app(), host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
