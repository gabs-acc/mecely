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
    enunciado: str | None = None
    briefing_entrevistador: str | None = None
    exhibit_recovered: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> Case:
        return cls(
            id=data["id"],
            book=data["book"],
            title=data.get("title"),
            type=_join_type(data.get("type")),
            difficulty=data.get("difficulty"),
            texto_completo=data["texto_completo"],
            enunciado=data.get("enunciado"),
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

    def label(self, *, include_book: bool = True) -> str:
        parts = [self.title or self.id]
        tags = [tag for tag in (self.type, self.difficulty) if tag]
        if tags:
            parts.append(f"({', '.join(tags)})")
        if include_book:
            parts.append(f"· {self.book}")
        return " ".join(parts)


def _join_type(value: object) -> str | None:
    """The library's `type` field can be a single string or a list of tags
    (as produced by newer extractions); either way, Case.type stays a
    plain string so filter_cases and label() don't need to special-case it."""
    if value is None:
        return None
    if isinstance(value, list):
        tags = [str(tag) for tag in value if tag]
        return ", ".join(tags) if tags else None
    return str(value)


def load_library(path: Path) -> list[Case]:
    if not path.exists():
        raise CaseLibraryError(f"{path} não encontrado")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CaseLibraryError(f"não foi possível ler {path}: {error}") from error
    if not isinstance(data, list):
        raise CaseLibraryError(f"{path} deve conter uma lista de cases")
    return [Case.from_dict(item) for item in data]


_FILTER_FIELD_ALIASES = {
    "titulo": "title",
    "tipo": "type",
    "dificuldade": "difficulty",
    "livro": "book",
    "casebook": "book",
}


def filter_cases(cases: list[Case], query: str) -> list[Case]:
    """Free-text filter matched against title, book, type and difficulty.

    The query is split on whitespace into terms that must ALL match, each
    anywhere among title/book/type/difficulty, so the words don't need to
    sit next to each other or land in the same field: "columbia difícil"
    finds a hard case from a Columbia casebook even though those two words
    live in different fields. A term can also scope itself to a single
    field with `campo:valor` (titulo:, tipo:, dificuldade:, livro: or
    casebook:), e.g. "dificuldade:difícil tipo:mercado" for a precise
    combination instead of relying on a word showing up anywhere.
    """
    terms = query.split()
    if not terms:
        return list(cases)

    def field_text(case: Case, field: str) -> str:
        return str(getattr(case, field, None) or "").lower()

    def haystack(case: Case) -> str:
        return " ".join(
            value for value in (case.title, case.book, case.type, case.difficulty) if value
        ).lower()

    def term_matches(case: Case, term: str) -> bool:
        prefix, sep, value = term.partition(":")
        field = _FILTER_FIELD_ALIASES.get(prefix.lower()) if sep else None
        if field and value:
            return value.lower() in field_text(case, field)
        return term.lower() in haystack(case)

    return [case for case in cases if all(term_matches(case, term) for term in terms)]


def pick_random(cases: list[Case], rng: Random | None = None) -> Case | None:
    if not cases:
        return None
    return (rng or Random()).choice(cases)
