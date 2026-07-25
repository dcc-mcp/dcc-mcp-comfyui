"""Command-line entry point for dcc-mcp-comfyui sidecar mode."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Optional


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ComfyUI MCP Server")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Optional fixed MCP instance port (default: OS-assigned)",
    )
    parser.add_argument(
        "--gateway-port",
        type=int,
        default=None,
        help="Gateway port (None = core default, 0 = disabled)",
    )
    parser.add_argument(
        "--comfyui-base-url",
        default=None,
        help="ComfyUI server base URL (default: http://127.0.0.1:8188)",
    )
    parser.add_argument(
        "--comfyui-timeout",
        type=float,
        default=None,
        help="ComfyUI request timeout in seconds (default: 120)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from dcc_mcp_comfyui import start_server, stop_server  # noqa: PLC0415

    server = start_server(
        port=args.port,
        gateway_port=args.gateway_port,
        comfyui_base_url=args.comfyui_base_url,
        comfyui_timeout=args.comfyui_timeout,
    )

    print(f"ComfyUI MCP server started: {server.mcp_url}")
    print(f"ComfyUI target: {server.comfyui_base_url}")
    print("Press Ctrl+C to stop...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        stop_server()

    return 0


if __name__ == "__main__":
    sys.exit(main())
