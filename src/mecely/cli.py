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
        description="Issue trees e estimativas numéricas em uma TUI Vim-first.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        help="arquivo JSON da árvore; se não existir, será criado ao salvar",
    )
    parser.add_argument(
        "-n", "--new", action="store_true", help="iniciar uma árvore limpa, ignorando o arquivo existente"
    )
    parser.add_argument("-t", "--title", help="título da nova árvore (usado com --new)")
    parser.add_argument("--prompt", help="enunciado do case (usado com --new)")
    autosave = parser.add_mutually_exclusive_group()
    autosave.add_argument("--autosave", action="store_true", help="salvar após cada alteração")
    autosave.add_argument("--no-autosave", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--read-only", action="store_true", help="abrir sem permitir qualquer gravação")
    parser.add_argument(
        "-v", "--verbose", action="count", default=0, help="registrar diagnóstico; repita para nível debug"
    )
    parser.add_argument("--log-file", type=Path, default=Path("mecely.log"), help="destino dos logs de --verbose")
    parser.add_argument("--config", type=Path, help="arquivo TOML de configuração")
    parser.add_argument("--web", action="store_true", help="servir a TUI localmente no navegador")
    parser.add_argument("--host", help="sobrescrever o endereço definido no config")
    parser.add_argument("--port", type=int, help="sobrescrever a porta definida no config")
    parser.add_argument("--public-url", help="URL pública quando o servidor estiver atrás de proxy")
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
    if args.prompt:
        command.extend(("--prompt", args.prompt))
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
        parser.error("--title requer --new")
    if args.prompt and not args.new:
        parser.error("--prompt requer --new")
    if args.read_only and args.autosave:
        parser.error("--read-only não pode ser combinado com --autosave")
    host = args.host or config.web.host
    port = args.port if args.port is not None else config.web.port
    public_url = args.public_url if args.public_url is not None else config.web.public_url
    if not 1 <= port <= 65535:
        parser.error("--port deve estar entre 1 e 65535")
    web_specific = args.host is not None or args.port is not None or args.public_url is not None
    if web_specific and not args.web:
        parser.error("--host, --port e --public-url requerem --web")

    configure_logging(args.verbose, args.log_file)
    data_file = resolve_file(args.file, args.new)
    logging.getLogger(__name__).info("configuração: %s", config_path)
    logging.getLogger(__name__).info("abrindo %s (new=%s)", data_file, args.new)

    if args.web:
        try:
            from textual_serve.server import Server
        except ImportError:
            parser.error("modo web não instalado; execute: pip install -e '.[web]'")
        selected_port = find_available_port(host, port)
        if selected_port is None:
            parser.exit(1, f"mecely: nenhuma porta livre entre {port} e {min(port + 19, 65535)}\n")
        if selected_port != port:
            print(f"Mecely: porta {port} ocupada; usando {selected_port}.")
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
            parser.exit(1, f"mecely: não foi possível iniciar o servidor web: {error}\n")
        return

    from .app import MecelyApp

    cases_directory = (
        Path(config.cases.directory).expanduser() if config.cases.directory else None
    )

    MecelyApp(
        data_file=data_file,
        start_new=args.new,
        title=args.title,
        prompt=args.prompt,
        autosave=(args.autosave or config.storage.autosave) and not args.no_autosave,
        read_only=args.read_only,
        palette=config.ui.palette,
        show_clock=config.ui.show_clock,
        cases_directory=cases_directory,
    ).run()


if __name__ == "__main__":
    main()
