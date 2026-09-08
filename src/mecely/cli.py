from __future__ import annotations

import argparse
import logging
import shlex
import socket
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mecely",
        description="Issue trees and numerical estimations in a Vim-first TUI.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        help="tree JSON file; created on first save if it doesn't exist",
    )
    parser.add_argument("-n", "--new", action="store_true", help="start a clean tree, ignoring the existing file")
    parser.add_argument("-t", "--title", help="title for the new tree (used with --new)")
    autosave = parser.add_mutually_exclusive_group()
    autosave.add_argument("--autosave", action="store_true", help="save after every change")
    autosave.add_argument("--no-autosave", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--read-only", action="store_true", help="open without allowing any writes")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="log diagnostics; repeat for debug level")
    parser.add_argument("--log-file", type=Path, default=Path("mecely.log"), help="destination for --verbose logs")
    parser.add_argument("--config", type=Path, help="configuration TOML file")
    parser.add_argument("--web", action="store_true", help="serve the TUI locally in the browser")
    parser.add_argument("--host", help="override the host defined in config")
    parser.add_argument("--port", type=int, help="override the port defined in config")
    parser.add_argument("--public-url", help="public URL when the server is behind a proxy")
    parser.add_argument("--version", action="version", version=f"Mecely {__version__}")
    return parser


def resolve_file(explicit: Path | None, start_new: bool) -> Path | None:
    return explicit


def configure_logging(verbosity: int, log_file: Path) -> None:
    if verbosity <= 0:
        return
    level = logging.DEBUG if verbosity > 1 else logging.INFO
    logging.basicConfig(
        filename=log_file,
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def build_app_command(args: argparse.Namespace, data_file: Path | None) -> str:
    command = [sys.executable, "-m", "mecely.cli"]
    if data_file is not None:
        command.append(str(data_file))
    if args.new:
        command.append("--new")
    if args.title:
        command.extend(("--title", args.title))
    if args.no_autosave:
        command.append("--no-autosave")
    elif args.autosave:
        command.append("--autosave")
    if args.read_only:
        command.append("--read-only")
    if args.verbose:
        command.append("-" + "v" * args.verbose)
        command.extend(("--log-file", str(args.log_file)))
    if args.config:
        command.extend(("--config", str(args.config)))
    return shlex.join(command)


def port_is_available(host: str, port: int) -> bool:
    sockets: list[socket.socket] = []
    addresses: set[tuple] = set()
    try:
        for family, sock_type, proto, _, address in socket.getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        ):
            key = (family, address)
            if key in addresses:
                continue
            addresses.add(key)
            candidate = socket.socket(family, sock_type, proto)
            candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            candidate.bind(address)
            sockets.append(candidate)
        return bool(sockets)
    except OSError:
        return False
    finally:
        for candidate in sockets:
            candidate.close()


def find_available_port(host: str, preferred: int, attempts: int = 20) -> int | None:
    last_port = min(preferred + attempts, 65536)
    return next((port for port in range(preferred, last_port) if port_is_available(host, port)), None)


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config, config_path = load_config(args.config)
    except ConfigError as error:
        parser.error(str(error))
    if args.title and not args.new:
        parser.error("--title requires --new")
    if args.read_only and args.autosave:
        parser.error("--read-only cannot be combined with --autosave")
    host = args.host or config.web.host
    port = args.port if args.port is not None else config.web.port
    public_url = args.public_url if args.public_url is not None else config.web.public_url
    if not 1 <= port <= 65535:
        parser.error("--port must be between 1 and 65535")
    web_specific = args.host is not None or args.port is not None or args.public_url is not None
    if web_specific and not args.web:
        parser.error("--host, --port, and --public-url require --web")

    configure_logging(args.verbose, args.log_file)
    data_file = resolve_file(args.file, args.new)
    logging.getLogger(__name__).info("configuration: %s", config_path)
    logging.getLogger(__name__).info("opening %s (new=%s)", data_file, args.new)

    if args.web:
        try:
            from textual_serve.server import Server
        except ImportError:
            parser.error("web mode not installed; run: pip install -e '.[web]'")
        selected_port = find_available_port(host, port)
        if selected_port is None:
            parser.exit(1, f"mecely: no free port between {port} and {min(port + 19, 65535)}\n")
        if selected_port != port:
            print(f"Mecely: port {port} is busy; using {selected_port}.")
        server = Server(
            build_app_command(args, data_file),
            host=host,
            port=selected_port,
            title="Mecely",
            public_url=public_url,
        )
        try:
            server.serve()
        except OSError as error:
            parser.exit(1, f"mecely: could not start the web server: {error}\n")
        return

    from .app import MecelyApp

    MecelyApp(
        data_file=data_file,
        start_new=args.new,
        title=args.title,
        autosave=(args.autosave or config.storage.autosave) and not args.no_autosave,
        read_only=args.read_only,
        palette=config.ui.palette,
        show_clock=config.ui.show_clock,
    ).run()


if __name__ == "__main__":
    main()
