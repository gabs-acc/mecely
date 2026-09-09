"""Reads a local library of sourced consulting cases (built outside Mecely,
see the README's "Biblioteca de cases" section) so the user can sortear or
choose one to practice against, with the AI interviewer held to strict
fidelity to that case's real text instead of improvising data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from random import Random


class CaseLibraryError(ValueError):
    pass


@dataclass(frozen=True)
class Case:
    id: str
    book: str
    title: str | None
    type: str | None
    difficulty: str | None
    texto_completo: str
    briefing_entrevistador: str | None = None
    exhibit_recovered: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> Case:
        return cls(
            id=data["id"],
            book=data["book"],
            title=data.get("title"),
            type=data.get("type"),
            difficulty=data.get("difficulty"),
            texto_completo=data["texto_completo"],
            briefing_entrevistador=data.get("briefing_entrevistador"),
            exhibit_recovered=data.get("exhibit_recovered"),
        )

    def full_text(self) -> str:
        """The case's source text plus any exhibit data recovered by hand
        from the original PDF, concatenated into one block the interviewer
        can be told to treat as the sole source of fact."""
        if not self.exhibit_recovered:
            return self.texto_completo
        return (
            f"{self.texto_completo}\n\n"
            f"[Dados de exhibit recuperados manualmente do PDF original, "
            f"pois a conversão automática os perdeu]\n{self.exhibit_recovered}"
        )

    def label(self) -> str:
        parts = [self.title or self.id]
        tags = [tag for tag in (self.type, self.difficulty) if tag]
        if tags:
            parts.append(f"({', '.join(tags)})")
        parts.append(f"· {self.book}")
        return " ".join(parts)


def load_library(directory: Path) -> list[Case]:
    path = directory / "cases_full.json"
    if not path.exists():
        raise CaseLibraryError(f"{path} não encontrado")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CaseLibraryError(f"não foi possível ler {path}: {error}") from error
    if not isinstance(data, list):
        raise CaseLibraryError(f"{path} deve conter uma lista de cases")
    return [Case.from_dict(item) for item in data]


def filter_cases(cases: list[Case], query: str) -> list[Case]:
    """Free-text filter matched against title, book, type and difficulty."""
    needle = query.strip().lower()
    if not needle:
        return list(cases)

    def matches(case: Case) -> bool:
        haystack = " ".join(
            value for value in (case.title, case.book, case.type, case.difficulty) if value
        ).lower()
        return needle in haystack

    return [case for case in cases if matches(case)]


def pick_random(cases: list[Case], rng: Random | None = None) -> Case | None:
    if not cases:
        return None
    return (rng or Random()).choice(cases)
