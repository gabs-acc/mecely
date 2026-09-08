from __future__ import annotations

import logging
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Header, Input, Label, ListItem, ListView, Static

from .calculator import CalculationError, evaluate, format_number
from .config import Palette
from .model import IssueTree

LOGGER = logging.getLogger(__name__)


def build_css(palette: Palette) -> str:
    return f"""
    Screen {{
        background: {palette.background};
        color: {palette.text};
        scrollbar-color: {palette.scrollbar};
        scrollbar-color-hover: {palette.scrollbar_hover};
        scrollbar-color-active: {palette.scrollbar_active};
        scrollbar-background: {palette.scrollbar_background};
        scrollbar-background-hover: {palette.scrollbar_background_hover};
        scrollbar-background-active: {palette.scrollbar_background_active};
        scrollbar-corner-color: {palette.scrollbar_corner};
        link-color: {palette.link};
        link-color-hover: {palette.link_hover};
        link-background: {palette.link_background};
        link-background-hover: {palette.link_background_hover};
    }}
    Header {{ background: {palette.panel}; color: {palette.header_text}; }}
    #tree {{ height: 1fr; margin: 1 2; border: round {palette.border}; background: {palette.surface}; }}
    #tree:focus {{ border: round {palette.border_focus}; }}
    ListItem {{ padding: 0 2; }}
    #tree > ListItem.--highlight,
    #tree:focus > ListItem.--highlight {{
        background: {palette.selected};
        color: {palette.selected_text};
    }}
    #tree > ListItem.visual,
    #tree:focus > ListItem.visual {{
        background: {palette.visual};
        color: {palette.visual_text};
    }}
    #shortcuts {{
        height: auto;
        padding: 0 1;
        background: {palette.background};
        color: {palette.footer_text};
    }}
    HelpScreen {{ align: center middle; }}
    #help-dialog {{
        width: 76;
        max-width: 95%;
        height: 90%;
        padding: 1 2;
        background: {palette.panel};
        color: {palette.text};
        border: tall {palette.border_focus};
    }}
    Input {{ background: {palette.input_background}; color: {palette.text}; border: tall {palette.input_border}; }}
    Input:focus {{ border: tall {palette.input_border_focus}; }}
    Toast.-information {{ background: {palette.information}; color: {palette.notification_text}; }}
    Toast.-warning {{ background: {palette.warning}; color: {palette.notification_text}; }}
    Toast.-error {{ background: {palette.error}; color: {palette.notification_text}; }}
    TextPrompt > Vertical {{ background: {palette.panel}; border: tall {palette.border_focus}; }}
    """


class IssueTreeList(ListView):
    """Vim-style tree controls, active only while the tree has focus."""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("h", "parent_or_collapse", "Parent/collapse"),
        Binding("left", "parent_or_collapse", "Parent/collapse", show=False),
        Binding("l", "child_or_expand", "Child/expand"),
        Binding("right", "child_or_expand", "Child/expand", show=False),
        Binding("a", "add_child", "Add child", priority=True),
        Binding("tab", "add_child", "Add child", priority=True, show=False),
        Binding("o", "add_sibling", "Add sibling", priority=True),
        Binding("enter", "add_sibling", "Add sibling", priority=True, show=False),
        Binding("i", "edit", "Edit"),
        Binding("e", "edit", "Edit", show=False),
        Binding("x", "delete", "Delete"),
        Binding("delete", "delete", "Delete", show=False),
        Binding("n", "numeric", "Number/operation"),
        Binding("equals_sign", "numeric", "Number/operation", show=False),
        Binding("r", "relation", "Relation"),
        Binding("u", "undo", "Undo"),
        Binding("ctrl+r", "redo", "Redo"),
        Binding("V", "visual", "Visual"),
        Binding("escape", "escape_visual", "Normal", show=False),
        Binding("y", "yank", "Copy"),
        Binding("p", "paste", "Paste"),
        Binding("g", "first", "First", show=False),
        Binding("G", "last", "Last", show=False),
        Binding("ctrl+d", "half_down", "Forward", show=False),
        Binding("ctrl+u", "half_up", "Back", show=False),
        Binding("question_mark", "help", "Help", show=False),
    ]

    def move(self, delta: int) -> None:
        if not self.children:
            return
        current = self.index or 0
        self.index = min(max(current + delta, 0), len(self.children) - 1)
        self.app.update_visual_selection()

    def action_cursor_down(self) -> None:
        self.move(1)

    def action_cursor_up(self) -> None:
        self.move(-1)

    def action_add_child(self) -> None:
        self.app.action_add_child()

    def action_add_sibling(self) -> None:
        self.app.action_add_sibling()

    def action_edit(self) -> None:
        self.app.action_edit()

    def action_delete(self) -> None:
        self.app.action_delete()

    def action_numeric(self) -> None:
        self.app.action_numeric()

    def action_relation(self) -> None:
        self.app.action_relation()

    def action_parent_or_collapse(self) -> None:
        self.app.action_parent_or_collapse()

    def action_child_or_expand(self) -> None:
        self.app.action_child_or_expand()

    def action_undo(self) -> None:
        self.app.action_undo()

    def action_redo(self) -> None:
        self.app.action_redo()

    def action_visual(self) -> None:
        self.app.action_visual()

    def action_escape_visual(self) -> None:
        self.app.action_escape_visual()

    def action_yank(self) -> None:
        self.app.action_yank()

    def action_paste(self) -> None:
        self.app.action_paste()

    def action_help(self) -> None:
        self.app.action_help()

    def action_first(self) -> None:
        self.index = 0
        self.app.update_visual_selection()

    def action_last(self) -> None:
        if self.children:
            self.index = len(self.children) - 1
            self.app.update_visual_selection()

    def action_half_down(self) -> None:
        self.move(5)

    def action_half_up(self) -> None:
        self.move(-5)


class TextPrompt(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    TextPrompt { align: center middle; }
    TextPrompt > Vertical { width: 70%; height: auto; padding: 1 2; }
    TextPrompt Input { margin-top: 1; }
    """

    def __init__(self, title: str, value: str = "") -> None:
        super().__init__()
        self.prompt_title = title
        self.value = value

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.prompt_title)
            yield Input(value=self.value, id="value")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


HELP_TEXT = """MECELY — SHORTCUTS

NAVIGATION
  j / k or ↓ / ↑    next node / previous node
  h or ←            collapse branch or go to parent
  l or →            expand branch or go to first child
  g / G             first / last node
  Ctrl+D / Ctrl+U   forward / back five lines

EDITING
  a or Tab          add child node
  o or Enter        add sibling node
  i or e            edit node
  x or Delete       delete node
  n or =            set value or numeric expression
  r                 set relation to the previous sibling

HISTORY AND SELECTION
  u / Ctrl+R        undo / redo
  V                 start or end visual mode
  Esc               leave visual mode
  y / p             copy / paste subtree

FILE AND APPLICATION
  Ctrl+S            save
  q                 quit
  ?                 open or close this help

NUMERIC VALUES
  Operations: +, -, *, /
  Examples: 1250, 1.25m, 5%, 215m * 5% * 120

Press ?, Esc, or q to close.
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("question_mark", "close", "Close", show=False),
        Binding("escape", "close", "Close", show=False),
        Binding("q", "close", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-dialog"):
            yield Static(Text(HELP_TEXT))

    def action_close(self) -> None:
        self.dismiss(None)


class MecelyApp(App):
    TITLE = "Mecely"
    SUB_TITLE = "Vim-first TUI for issue tree modeling"
    ENABLE_COMMAND_PALETTE = False
    CSS = build_css(Palette())
    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        data_file: Path | None = None,
        start_new: bool = False,
        title: str | None = None,
        autosave: bool = False,
        read_only: bool = False,
        palette: Palette | None = None,
        show_clock: bool = False,
    ) -> None:
        # App CSS is collected by Textual during App.__init__, so the
        # instance-specific stylesheet must exist before calling super().
        self.palette = palette or Palette()
        self.CSS = build_css(self.palette)
        super().__init__()
        self.show_clock = show_clock
        self.data_file = data_file
        self.autosave = autosave and not read_only
        self.read_only = read_only
        self.issue_tree = (
            IssueTree.new(title or "New case")
            if start_new or data_file is None or not data_file.exists()
            else IssueTree.load(data_file)
        )
        LOGGER.info("tree loaded: %s nodes", len(list(self.issue_tree.walk())))
        self.node_ids: list[str] = []
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        self.subtree_clipboard = []
        self.visual_anchor: int | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=self.show_clock)
        yield IssueTreeList(id="tree")
        yield Static(
            "? help · j/k move · h/l level · a child · o sibling · "
            "i edit · x delete · n/= value · r relation",
            id="shortcuts",
        )

    def on_mount(self) -> None:
        self.refresh_tree()

    def selected_id(self) -> str | None:
        if isinstance(self.screen, ModalScreen):
            return None
        view = self.query_one("#tree", ListView)
        if not self.node_ids:
            return None
        return self.node_ids[max(0, view.index or 0)]

    def refresh_tree(self, select_id: str | None = None) -> None:
        view = self.query_one("#tree", ListView)
        view.clear()
        self.node_ids = []
        selected_index = 0
        for node, depth in self.issue_tree.walk(visible_only=True):
            marker = "▸" if node.collapsed and node.children else "▾" if node.children else " "
            result = node.result()
            relation = f"[{node.relation}] " if node.relation else ""
            if node.children and result is not None:
                numeric = f"  = {format_number(result)}"
            elif not node.children and node.value is not None:
                numeric = f"  = {format_number(node.value)}"
            else:
                numeric = ""
            line = f"{'  ' * depth}{marker} {relation}{node.text}{numeric}"
            if node.id == select_id:
                selected_index = len(self.node_ids)
            self.node_ids.append(node.id)
            view.append(ListItem(Label(Text(line))))
        view.index = selected_index
        self.update_visual_selection()

    def update_visual_selection(self) -> None:
        view = self.query_one("#tree", ListView)
        current = view.index or 0
        if self.visual_anchor is None:
            selected: set[int] = set()
        else:
            start, end = sorted((self.visual_anchor, current))
            selected = set(range(start, end + 1))
        for index, item in enumerate(view.query(ListItem)):
            is_visual = index in selected
            item.set_class(is_visual, "visual")
            if is_visual:
                item.styles.background = self.palette.visual
                item.styles.color = self.palette.visual_text
            elif index == current:
                item.styles.background = self.palette.selected
                item.styles.color = self.palette.selected_text
            else:
                item.styles.background = self.palette.surface
                item.styles.color = self.palette.text

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Reapply palette colors when mouse or built-in navigation moves."""
        self.update_visual_selection()

    def selected_node_ids(self) -> list[str]:
        view = self.query_one("#tree", ListView)
        current = view.index or 0
        if self.visual_anchor is None:
            return [self.node_ids[current]] if self.node_ids else []
        start, end = sorted((self.visual_anchor, current))
        return self.node_ids[start:end + 1]

    def top_level_selected_nodes(self):
        selected_ids = set(self.selected_node_ids())
        selected_ids.discard(self.issue_tree.root.id)
        nodes = []
        for node_id in self.selected_node_ids():
            if node_id not in selected_ids:
                continue
            parent = self.issue_tree.parent_of(node_id)
            if parent is None or parent.id not in selected_ids:
                node = self.issue_tree.find(node_id)
                if node is not None:
                    nodes.append(node)
        return nodes

    def checkpoint(self) -> None:
        self.undo_stack.append(self.issue_tree.to_dict())
        self.undo_stack = self.undo_stack[-100:]
        self.redo_stack.clear()

    def persist(self, force: bool = False) -> None:
        if self.read_only or self.data_file is None or (not self.autosave and not force):
            return
        self.issue_tree.save(self.data_file)
        LOGGER.debug("tree saved to %s", self.data_file)

    def action_add_child(self) -> None:
        parent_id = self.selected_id()
        if parent_id is None:
            return
        self.push_screen(TextPrompt("New child branch"), lambda text: self.finish_add(parent_id, text, True))

    def action_add_sibling(self) -> None:
        node_id = self.selected_id()
        if node_id is None:
            return
        self.push_screen(TextPrompt("New sibling branch"), lambda text: self.finish_add(node_id, text, False))

    def finish_add(self, node_id: str, text: str | None, child: bool) -> None:
        if text:
            self.checkpoint()
            new = self.issue_tree.add_child(node_id, text) if child else self.issue_tree.add_sibling(node_id, text)
            self.persist()
            self.refresh_tree(new.id)

    def action_edit(self) -> None:
        node_id = self.selected_id()
        if node_id is None:
            return
        node = self.issue_tree.find(node_id)
        if node:
            self.push_screen(TextPrompt("Edit node", node.text), lambda text: self.finish_edit(node.id, text))

    def finish_edit(self, node_id: str, text: str | None) -> None:
        if text:
            node = self.issue_tree.find(node_id)
            if node:
                self.checkpoint()
                node.text = text
                self.persist()
                self.refresh_tree(node_id)

    def action_parent_or_collapse(self) -> None:
        node_id = self.selected_id()
        if node_id is None:
            return
        node = self.issue_tree.find(node_id)
        if node is None:
            return
        if node.children and not node.collapsed:
            node.collapsed = True
            self.persist()
            self.refresh_tree(node.id)
            return
        parent = self.issue_tree.parent_of(node.id)
        if parent is not None:
            self.refresh_tree(parent.id)

    def action_child_or_expand(self) -> None:
        node_id = self.selected_id()
        if node_id is None:
            return
        node = self.issue_tree.find(node_id)
        if node is None or not node.children:
            return
        if node.collapsed:
            node.collapsed = False
            self.persist()
            self.refresh_tree(node.id)
        else:
            self.refresh_tree(node.children[0].id)

    def action_numeric(self) -> None:
        node_id = self.selected_id()
        if node_id is None:
            return
        node = self.issue_tree.find(node_id)
        if node is None:
            return
        if node.children:
            self.notify("Set the children's relations with R", severity="warning")
            return
        prompt = "Estimated value (accepts 10k, 2.5m, 15%, and expressions)"
        current = format_number(node.value) if node.value is not None else ""
        self.push_screen(TextPrompt(prompt, current), lambda text: self.finish_numeric(node.id, text))

    def finish_numeric(self, node_id: str, text: str | None) -> None:
        if text is None:
            return
        node = self.issue_tree.find(node_id)
        if node is None:
            return
        try:
            value = evaluate(text)
        except CalculationError as error:
            self.notify(str(error), severity="error")
            return
        self.checkpoint()
        node.value = value
        self.persist()
        self.refresh_tree(node.id)

    def action_relation(self) -> None:
        node_id = self.selected_id()
        if node_id is None:
            return
        node = self.issue_tree.find(node_id)
        parent = self.issue_tree.parent_of(node_id)
        if node is None or parent is None:
            self.notify("The root has no relation to a previous sibling", severity="warning")
            return
        index = next(i for i, child in enumerate(parent.children) if child.id == node_id)
        if index == 0:
            self.notify("The first child starts the expression", severity="warning")
            return
        self.push_screen(
            TextPrompt("Relation to the previous sibling (+, -, * or /)", node.relation or ""),
            lambda text: self.finish_relation(node.id, text),
        )

    def finish_relation(self, node_id: str, text: str | None) -> None:
        if text is None:
            return
        if text not in {"+", "-", "*", "/"}:
            self.notify("Use a relation: +, -, * or /", severity="error")
            return
        node = self.issue_tree.find(node_id)
        if node is None:
            return
        self.checkpoint()
        node.relation = text
        self.persist()
        self.refresh_tree(node.id)

    def action_delete(self) -> None:
        nodes = self.top_level_selected_nodes()
        if not nodes:
            return
        self.checkpoint()
        for node in nodes:
            self.issue_tree.delete(node.id)
        self.visual_anchor = None
        self.persist()
        self.refresh_tree()

    def action_visual(self) -> None:
        view = self.query_one("#tree", ListView)
        self.visual_anchor = None if self.visual_anchor is not None else (view.index or 0)
        self.update_visual_selection()

    def action_escape_visual(self) -> None:
        self.visual_anchor = None
        self.update_visual_selection()

    def action_yank(self) -> None:
        nodes = self.top_level_selected_nodes()
        if not nodes and self.selected_id() == self.issue_tree.root.id:
            nodes = [self.issue_tree.root]
        self.subtree_clipboard = [node.clone() for node in nodes]
        self.visual_anchor = None
        self.update_visual_selection()
        if self.subtree_clipboard:
            self.notify(f"{len(self.subtree_clipboard)} subtree(s) copied")

    def action_paste(self) -> None:
        node_id = self.selected_id()
        if node_id is None or not self.subtree_clipboard:
            return
        self.checkpoint()
        copies = self.issue_tree.insert_after(node_id, self.subtree_clipboard)
        self.persist()
        self.refresh_tree(copies[0].id if copies else node_id)

    def action_undo(self) -> None:
        if not self.undo_stack:
            self.notify("Nothing to undo")
            return
        selected = self.selected_id()
        self.redo_stack.append(self.issue_tree.to_dict())
        self.issue_tree = IssueTree.from_dict(self.undo_stack.pop())
        self.visual_anchor = None
        self.persist()
        self.refresh_tree(selected)

    def action_redo(self) -> None:
        if not self.redo_stack:
            self.notify("Nothing to redo")
            return
        selected = self.selected_id()
        self.undo_stack.append(self.issue_tree.to_dict())
        self.issue_tree = IssueTree.from_dict(self.redo_stack.pop())
        self.visual_anchor = None
        self.persist()
        self.refresh_tree(selected)

    def action_save(self) -> None:
        if self.read_only:
            self.notify("File opened as read-only", severity="warning")
            return
        if self.data_file is None:
            self.push_screen(
                TextPrompt("Save as JSON file", "case.json"),
                self.finish_save_as,
            )
            return
        self.persist(force=True)
        self.notify(f"Saved to {self.data_file}")

    def finish_save_as(self, text: str | None) -> None:
        if text is None:
            return
        path = Path(text).expanduser()
        if not path.suffix:
            path = path.with_suffix(".json")
        elif path.suffix.lower() != ".json":
            self.notify("The file must use the .json extension", severity="error")
            return
        try:
            self.issue_tree.save(path)
        except OSError as error:
            self.notify(f"Could not save: {error}", severity="error")
            return
        self.data_file = path
        LOGGER.debug("tree saved to %s", self.data_file)
        self.notify(f"Saved to {self.data_file}")

    def action_help(self) -> None:
        self.push_screen(HelpScreen())


def main() -> None:
    from .cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
