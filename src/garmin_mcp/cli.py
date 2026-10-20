"""Command line interface: `garmin-mcp login | logout | status | serve`."""

import argparse
import logging
import sys

from . import __version__, config
from .auth import GarminSession, NotLoggedInError, clear_tokens, interactive_login


def _cmd_login(_: argparse.Namespace) -> int:
    garmin = interactive_login()
    print(f"Logged in as {garmin.get_full_name() or garmin.display_name}.")
    print(f"Session tokens saved to {config.tokenstore()}")
    return 0


def _cmd_logout(_: argparse.Namespace) -> int:
    print("Removed saved tokens." if clear_tokens() else "No saved tokens found.")
    return 0


def _cmd_status(_: argparse.Namespace) -> int:
    try:
        garmin = GarminSession().client()
    except NotLoggedInError as e:
        print(f"Not logged in: {e}")
        return 1
    name = garmin.get_full_name() or garmin.display_name
    print(f"Logged in as {name} (tokens: {config.tokenstore()})")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from .server import build_server

    # stdout carries the MCP protocol in stdio mode; all logging must go to stderr.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    server = build_server(args.toolset, args.max_chars)
    if args.transport == "stdio":
        server.run("stdio")
    else:
        print(f"Serving MCP on http://{args.host}:{args.port}{args.path}", file=sys.stderr)
        server.run(
            "streamable-http", host=args.host, port=args.port, streamable_http_path=args.path
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="garmin-mcp", description="Local MCP server for Garmin Connect data."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser(
        "login", help="sign in to Garmin Connect (supports MFA) and save tokens"
    ).set_defaults(func=_cmd_login)
    sub.add_parser("logout", help="delete saved tokens").set_defaults(func=_cmd_logout)
    sub.add_parser("status", help="check the saved session").set_defaults(func=_cmd_status)

    serve = sub.add_parser("serve", help="run the MCP server (default command)")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    serve.add_argument("--host", default="127.0.0.1", help="http only (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8765, help="http only (default: 8765)")
    serve.add_argument("--path", default="/mcp", help="http endpoint path (default: /mcp)")
    serve.add_argument(
        "--toolset",
        choices=["core", "all"],
        default="core",
        help="core: ~60 curated tools + garmin_call for the rest; all: every read method as a tool",
    )
    serve.add_argument(
        "--max-chars",
        type=int,
        default=config.DEFAULT_MAX_CHARS,
        help="cap on characters returned per tool call; long lists are downsampled to fit",
    )
    serve.set_defaults(func=_cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:] or ["serve"])
    if not getattr(args, "func", None):
        args = parser.parse_args(["serve"])
    try:
        sys.exit(args.func(args))
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:  # login failures etc.
        if args.command == "serve":
            raise
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
