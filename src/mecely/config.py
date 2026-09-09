from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    pass


_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


@dataclass(frozen=True)
class Palette:
    background: str = "#0b1020"
    surface: str = "#11182b"
    panel: str = "#151d34"
    border: str = "#526b9b"
    border_focus: str = "#7896d1"
    selected: str = "#24457a"
    selected_text: str = "#ffffff"
    visual: str = "#4a2f78"
    visual_text: str = "#ffffff"
    text: str = "#edf2f7"
    muted: str = "#9fb8e8"
    header_text: str = "#edf2f7"
    footer_text: str = "#c8d6ef"
    input_background: str = "#0b1020"
    input_border: str = "#526b9b"
    input_border_focus: str = "#7896d1"
    scrollbar: str = "#526b9b"
    scrollbar_hover: str = "#7896d1"
    scrollbar_active: str = "#9fb8e8"
    scrollbar_background: str = "#0b1020"
    scrollbar_background_hover: str = "#11182b"
    scrollbar_background_active: str = "#151d34"
    scrollbar_corner: str = "#0b1020"
    link: str = "#9fb8e8"
    link_hover: str = "#ffffff"
    link_background: str = "#0b1020"
    link_background_hover: str = "#24457a"
    information: str = "#24457a"
    warning: str = "#8a6518"
    error: str = "#8a2f3b"
    notification_text: str = "#ffffff"


@dataclass(frozen=True)
class UIConfig:
    show_clock: bool = False
    palette: Palette = field(default_factory=Palette)


@dataclass(frozen=True)
class StorageConfig:
    autosave: bool = False


@dataclass(frozen=True)
class WebConfig:
    host: str = "localhost"
    port: int = 8000
    public_url: str | None = None


@dataclass(frozen=True)
class CasesConfig:
    directory: str | None = None


@dataclass(frozen=True)
class MecelyConfig:
    ui: UIConfig = field(default_factory=UIConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    web: WebConfig = field(default_factory=WebConfig)
    cases: CasesConfig = field(default_factory=CasesConfig)


def default_config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "mecely" / "config.toml"


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] deve ser uma tabela TOML")
    return value


def _known_values(cls: type, values: dict[str, Any], section: str) -> dict[str, Any]:
    known = {item.name for item in fields(cls)}
    unknown = set(values) - known
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ConfigError(f"opção desconhecida em [{section}]: {names}")
    return values


def load_config(path: Path | None = None) -> tuple[MecelyConfig, Path]:
    resolved = path or default_config_path()
    if not resolved.exists():
        return MecelyConfig(), resolved
    try:
        data = tomllib.loads(resolved.read_text())
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"não foi possível ler {resolved}: {error}") from error

    unknown_sections = set(data) - {"ui", "storage", "web", "cases"}
    if unknown_sections:
        raise ConfigError(f"seção desconhecida: {', '.join(sorted(unknown_sections))}")

    ui_data = _section(data, "ui")
    palette_data = ui_data.pop("palette", {})
    if not isinstance(palette_data, dict):
        raise ConfigError("[ui.palette] deve ser uma tabela TOML")
    try:
        palette = Palette(**_known_values(Palette, palette_data, "ui.palette"))
        ui = UIConfig(palette=palette, **_known_values(UIConfig, ui_data, "ui"))
        storage = StorageConfig(**_known_values(StorageConfig, _section(data, "storage"), "storage"))
        web = WebConfig(**_known_values(WebConfig, _section(data, "web"), "web"))
        cases = CasesConfig(**_known_values(CasesConfig, _section(data, "cases"), "cases"))
    except TypeError as error:
        raise ConfigError(f"tipo inválido na configuração: {error}") from error

    if cases.directory is not None and not isinstance(cases.directory, str):
        raise ConfigError("cases.directory deve ser texto")

    if not isinstance(web.port, int) or isinstance(web.port, bool) or not 1 <= web.port <= 65535:
        raise ConfigError("web.port deve estar entre 1 e 65535")
    if not isinstance(web.host, str) or not web.host:
        raise ConfigError("web.host deve ser texto não vazio")
    if web.public_url is not None and not isinstance(web.public_url, str):
        raise ConfigError("web.public_url deve ser texto")
    for item in fields(Palette):
        value = getattr(palette, item.name)
        if not isinstance(value, str) or not _HEX_COLOR.match(value):
            raise ConfigError(f"ui.palette.{item.name} deve ser uma cor hexadecimal, como #0b1020")
    if not isinstance(ui.show_clock, bool) or not isinstance(storage.autosave, bool):
        raise ConfigError("show_clock e autosave devem ser booleanos")
    return MecelyConfig(ui=ui, storage=storage, web=web, cases=cases), resolved
