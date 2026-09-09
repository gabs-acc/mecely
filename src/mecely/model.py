from __future__ import annotations

import json
import operator as arithmetic
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

OPERATIONS = {
    "+": arithmetic.add,
    "-": arithmetic.sub,
    "*": arithmetic.mul,
    "/": arithmetic.truediv,
}


@dataclass
class Node:
    text: str
    id: str = field(default_factory=lambda: uuid4().hex[:10])
    children: list[Node] = field(default_factory=list)
    collapsed: bool = False
    operation: str | None = None
    value: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Node:
        node = cls(
            id=data["id"],
            text=data["text"],
            collapsed=data.get("collapsed", False),
            # "operation" is the current field name; "relation" is what it
            # was called before, and bare "operator" (applied uniformly to
            # every child below) is older still — both are read as fallbacks
            # so cases saved under either older format keep loading.
            operation=data.get("operation", data.get("relation")),
            value=float(data["value"]) if data.get("value") is not None else None,
            children=[cls.from_dict(child) for child in data.get("children", [])],
        )
        legacy_operator = data.get("operator")
        if legacy_operator in OPERATIONS:
            for child in node.children[1:]:
                if child.operation is None:
                    child.operation = legacy_operator
        return node

    def result(self) -> float | None:
        if not self.children:
            return self.value
        child_values = [child.result() for child in self.children]
        if any(value is None for value in child_values):
            return None
        if any(child.operation not in OPERATIONS for child in self.children[1:]):
            return None
        try:
            terms = [float(child_values[0])]  # type: ignore[arg-type]
            additive: list[str] = []
            for child, value in zip(self.children[1:], child_values[1:], strict=True):
                if child.operation == "*":
                    terms[-1] *= float(value)
                elif child.operation == "/":
                    terms[-1] /= float(value)
                else:
                    additive.append(child.operation)  # type: ignore[arg-type]
                    terms.append(float(value))
            result = terms[0]
            for operation, term in zip(additive, terms[1:], strict=True):
                result = OPERATIONS[operation](result, term)
            return float(result)
        except (ArithmeticError, OverflowError):
            return None

    def clone(self) -> Node:
        return Node(
            text=self.text,
            collapsed=self.collapsed,
            operation=self.operation,
            value=self.value,
            children=[child.clone() for child in self.children],
        )


@dataclass
class Note:
    author: str
    text: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Note:
        return cls(author=data["author"], text=data["text"])


@dataclass
class IssueTree:
    title: str
    root: Node
    prompt: str | None = None
    notes: list[Note] = field(default_factory=list)

    @classmethod
    def new(cls, title: str = "Novo case", prompt: str | None = None) -> IssueTree:
        return cls(title=title, root=Node("Qual é a pergunta principal?"), prompt=prompt)

    def add_note(self, author: str, text: str) -> Note:
        note = Note(author=author, text=text)
        self.notes.append(note)
        return note

    def walk(self, visible_only: bool = False) -> Iterator[tuple[Node, int]]:
        def visit(node: Node, depth: int) -> Iterator[tuple[Node, int]]:
            yield node, depth
            if not (visible_only and node.collapsed):
                for child in node.children:
                    yield from visit(child, depth + 1)

        yield from visit(self.root, 0)

    def find(self, node_id: str) -> Node | None:
        return next((node for node, _ in self.walk() if node.id == node_id), None)

    def parent_of(self, node_id: str) -> Node | None:
        for candidate, _ in self.walk():
            if any(child.id == node_id for child in candidate.children):
                return candidate
        return None

    def add_child(self, parent_id: str, text: str = "Novo ramo") -> Node:
        parent = self.find(parent_id)
        if parent is None:
            raise KeyError(parent_id)
        node = Node(text)
        parent.children.append(node)
        parent.collapsed = False
        parent.value = None
        return node

    def add_sibling(self, node_id: str, text: str = "Novo ramo") -> Node:
        parent = self.parent_of(node_id)
        if parent is None:
            return self.add_child(node_id, text)
        index = next(i for i, child in enumerate(parent.children) if child.id == node_id)
        node = Node(text)
        parent.children.insert(index + 1, node)
        return node

    def delete(self, node_id: str) -> bool:
        parent = self.parent_of(node_id)
        if parent is None:
            return False
        parent.children = [child for child in parent.children if child.id != node_id]
        if parent.children:
            parent.children[0].operation = None
        return True

    def insert_after(self, node_id: str, nodes: list[Node]) -> list[Node]:
        copies = [node.clone() for node in nodes]
        if copies:
            copies[0].operation = None
        parent = self.parent_of(node_id)
        if parent is None:
            self.root.children.extend(copies)
            self.root.collapsed = False
            return copies
        index = next(i for i, child in enumerate(parent.children) if child.id == node_id)
        parent.children[index + 1:index + 1] = copies
        return copies

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "prompt": self.prompt,
            "notes": [note.to_dict() for note in self.notes],
            "root": self.root.to_dict(),
        }

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n")

    @classmethod
    def from_dict(cls, data: dict) -> IssueTree:
        return cls(
            title=data["title"],
            prompt=data.get("prompt"),
            notes=[Note.from_dict(note) for note in data.get("notes", [])],
            root=Node.from_dict(data["root"]),
        )

    @classmethod
    def load(cls, path: Path) -> IssueTree:
        return cls.from_dict(json.loads(path.read_text()))
