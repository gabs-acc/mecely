from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Header, Input, Label, ListItem, ListView, Static, TextArea

from .calculator import CalculationError, evaluate, format_number
from .cases import Case, CaseLibraryError, filter_cases, load_library, pick_random
from .config import Palette
from .evaluation import build_note_reply_prompt, build_prompt
from .model import IssueTree, Node

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
    #tree Horizontal {{ height: 1; background: {palette.selected}; }}
    .insert-prefix {{
        width: auto;
        height: 1;
        background: {palette.selected};
        color: {palette.selected_text};
    }}
    #insert-input {{
        width: 1fr;
        height: 1;
        border: none;
        padding: 0;
        background: {palette.selected};
        color: {palette.selected_text};
    }}
    #mode-indicator {{
        height: auto;
        padding: 0 1;
        background: {palette.selected};
        color: {palette.selected_text};
        text-style: bold;
    }}
    #mode-indicator.visual {{
        background: {palette.visual};
        color: {palette.visual_text};
    }}
    #mode-indicator.insert {{
        background: {palette.warning};
        color: {palette.notification_text};
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
    EvaluationScreen {{ align: center middle; }}
    #evaluation-dialog {{
        width: 90;
        max-width: 95%;
        height: 90%;
        padding: 1 2;
        background: {palette.panel};
        color: {palette.text};
        border: tall {palette.border_focus};
    }}
    NotesScreen {{ align: center middle; }}
    #notes-dialog {{
        width: 90;
        max-width: 95%;
        height: 90%;
        padding: 1 2;
        background: {palette.panel};
        color: {palette.text};
        border: tall {palette.border_focus};
    }}
    #notes-history {{ height: 1fr; }}
    #notes-input {{ height: 6; margin-top: 1; border: tall {palette.input_border}; }}
    #notes-input:focus {{ border: tall {palette.input_border_focus}; }}
    #notes-hint {{ height: auto; color: {palette.footer_text}; }}
    #notes-mode {{
        height: auto;
        padding: 0 1;
        background: {palette.selected};
        color: {palette.selected_text};
        text-style: bold;
    }}
    Input {{ background: {palette.input_background}; color: {palette.text}; border: tall {palette.input_border}; }}
    Input:focus {{ border: tall {palette.input_border_focus}; }}
    Toast.-information {{ background: {palette.information}; color: {palette.notification_text}; }}
    Toast.-warning {{ background: {palette.warning}; color: {palette.notification_text}; }}
    Toast.-error {{ background: {palette.error}; color: {palette.notification_text}; }}
    TextPrompt > Vertical {{ background: {palette.panel}; border: tall {palette.border_focus}; }}
    ConfirmScreen > Vertical {{ background: {palette.panel}; border: tall {palette.border_focus}; }}
    CaseLibraryScreen {{ align: center middle; }}
    #case-library-dialog {{
        width: 90;
        max-width: 95%;
        height: 90%;
        padding: 1 2;
        background: {palette.panel};
        color: {palette.text};
        border: tall {palette.border_focus};
    }}
    #case-list {{ height: 1fr; margin-top: 1; background: {palette.surface}; }}
    """


class IssueTreeList(ListView):
    """Vim-style tree controls, active only while the tree has focus."""

    _pending_g: float | None = None

    BINDINGS = [
        Binding("j", "cursor_down", "Descer", show=False),
        Binding("down", "cursor_down", "Descer", show=False),
        Binding("k", "cursor_up", "Subir", show=False),
        Binding("up", "cursor_up", "Subir", show=False),
        Binding("h", "parent_or_collapse", "Pai/recolher"),
        Binding("left", "parent_or_collapse", "Pai/recolher", show=False),
        Binding("l", "child_or_expand", "Filho/expandir"),
        Binding("right", "child_or_expand", "Filho/expandir", show=False),
        Binding("a", "add_child", "Adicionar filho", priority=True),
        Binding("tab", "add_child", "Adicionar filho", priority=True, show=False),
        Binding("o", "add_sibling", "Adicionar irmão", priority=True),
        Binding("enter", "add_sibling", "Adicionar irmão", priority=True, show=False),
        Binding("i", "edit", "Editar"),
        Binding("x", "delete", "Excluir"),
        Binding("delete", "delete", "Excluir", show=False),
        Binding("equals_sign", "numeric", "Número/operação"),
        Binding("plus", "set_operation('+')", "Soma"),
        Binding("minus", "set_operation('-')", "Subtração"),
        Binding("asterisk", "set_operation('*')", "Multiplicação"),
        Binding("slash", "set_operation('/')", "Divisão"),
        Binding("backspace", "clear_operation", "Limpar operação"),
        Binding("c", "view_notes", "Conversar com a IA"),
        Binding("exclamation_mark", "evaluate", "Avaliar"),
        Binding("u", "undo", "Desfazer"),
        Binding("ctrl+r", "redo", "Refazer"),
        Binding("V", "visual", "Visual"),
        Binding("escape", "escape_visual", "Normal", show=False),
        Binding("y", "yank", "Copiar"),
        Binding("p", "paste", "Colar"),
        Binding("g", "maybe_first", "Primeiro (gg)", show=False),
        Binding("G", "last", "Último", show=False),
        Binding("ctrl+d", "half_down", "Avançar", show=False),
        Binding("ctrl+u", "half_up", "Recuar", show=False),
        Binding("question_mark", "help", "Ajuda", show=False),
    ]

    def move(self, delta: int) -> None:
        if not self.children:
            return
        current = self.index or 0
        self.index = min(max(current + delta, 0), len(self.children) - 1)
        self.app.update_visual_selection()

    def on_click(self, event: events.Click) -> None:
        """A single click already selects the row (ListView's own
        behavior); a double click also opens it for editing, mirroring `i`,
        for anyone who reaches for the mouse instead of the keyboard."""
        if event.chain >= 2:
            self.action_edit()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """While a row is being edited inline (INSERT mode), the tree's own
        priority bindings (a/Tab/o/Enter) would otherwise steal those keys
        away from the Input before it ever sees them, and bare Up/Down would
        shift the list selection out from under the row being typed into."""
        if self.app.insert_node_id is not None and action in (
            "add_child",
            "add_sibling",
            "cursor_up",
            "cursor_down",
            "redo",
        ):
            return False
        return True

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

    def action_set_operation(self, symbol: str) -> None:
        self.app.action_set_operation(symbol)

    def action_clear_operation(self) -> None:
        self.app.action_clear_operation()

    def action_view_notes(self) -> None:
        self.app.action_view_notes()

    def action_evaluate(self) -> None:
        self.app.action_evaluate()

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

    def action_maybe_first(self) -> None:
        """`gg` moves to the first node, matching Vim. `g` alone does nothing."""
        now = time.monotonic()
        if self._pending_g is not None and now - self._pending_g < 0.6:
            self._pending_g = None
            self.action_first()
        else:
            self._pending_g = now

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


class InsertInput(Input):
    """Vim-style INSERT-mode editor for a tree row's text, so editing
    happens in place instead of in a pop-up. Escape is bound here, on the
    Input itself, rather than left to the tree's own Escape binding, since
    the focused widget's own bindings are checked before an ancestor's."""

    BINDINGS = [Binding("escape", "cancel_insert", "Cancelar", show=False)]

    def action_cancel_insert(self) -> None:
        self.app.cancel_insert()


class PersistentFocusInput(Input):
    """An Input that reclaims focus if the mouse blurs it. Used by modal
    screens that have nothing else worth focusing, so a stray click
    shouldn't lose the cursor."""

    def on_blur(self, event: events.Blur) -> None:
        if self.is_mounted and self.screen.is_current:
            self.focus()


class TextPrompt(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "Cancelar")]
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
            yield PersistentFocusInput(value=self.value, id="value")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "confirm", "Sim", show=False),
        Binding("enter", "confirm", "Confirmar", show=False),
        Binding("n", "cancel", "Não", show=False),
        Binding("escape", "cancel", "Cancelar", show=False),
    ]
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Vertical { width: 60%; height: auto; padding: 1 2; }
    ConfirmScreen Label#confirm-hint { margin-top: 1; }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.message)
            yield Label("[Y] sim   [N] / Esc não", id="confirm-hint")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


HELP_TEXT = """MECELY · ATALHOS

NAVEGAÇÃO
  j / k ou ↓ / ↑    próximo nó / nó anterior
  h ou ←            recolher ramo ou ir ao pai
  l ou →            expandir ramo ou ir ao primeiro filho
  gg / G            primeiro / último nó
  Ctrl+D / Ctrl+U   avançar / recuar cinco linhas
  clique            selecionar nó com o mouse
  clique duplo      editar nó com o mouse

EDIÇÃO (a/o/i/= entram no modo INSERT, editando na própria linha)
  a ou Tab          adicionar nó filho
  o ou Enter        adicionar nó irmão
  i                 editar texto do nó
  =                 definir valor ou expressão numérica
  Enter             confirma (sai do INSERT)
  Esc               cancela (sai do INSERT)
  x ou Delete       excluir nó
  +  -  *  /        definir operação com o irmão anterior
  Backspace         limpar a operação do nó
  c                 conversar com a IA (pergunta, explicação, recomendação;
                    Ctrl+J envia, Esc sai da edição pra rolar com j/k/
                    Ctrl+D/Ctrl+U/PgUp/PgDn, i volta a editar, Esc fecha)
  !                 avaliar case com IA (pede confirmação; requer o CLI
                    "claude" instalado; na tela de avaliação, y copia)
  R                 sortear/escolher case de uma biblioteca local (requer
                    cases.directory no config.toml; troca a árvore atual)

HISTÓRICO E SELEÇÃO
  u / Ctrl+R        desfazer / refazer
  V                 iniciar ou encerrar modo visual
  Esc               sair do modo visual
  y / p             copiar / colar subárvore

ARQUIVO E APLICAÇÃO
  Ctrl+S            salvar
  q                 sair
  ?                 abrir ou fechar esta ajuda

VALORES NUMÉRICOS
  Operações: +, -, *, /
  Exemplos: 1250, 1.25m, 5%, 215m * 5% * 120

Pressione ?, Esc ou q para fechar.
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("question_mark", "close", "Fechar", show=False),
        Binding("escape", "close", "Fechar", show=False),
        Binding("q", "close", "Fechar", show=False),
        Binding("pageup,kp_page_up", "page_up", "Rolar página", show=False),
        Binding("pagedown,kp_page_down", "page_down", "Rolar página", show=False),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-dialog"):
            yield Static(Text(HELP_TEXT))

    def on_mount(self) -> None:
        self.query_one(VerticalScroll).focus()

    def action_close(self) -> None:
        self.dismiss(None)

    def action_page_up(self) -> None:
        self.query_one(VerticalScroll).scroll_page_up()

    def action_page_down(self) -> None:
        self.query_one(VerticalScroll).scroll_page_down()


class EvaluationScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("y", "copy", "Copiar", show=False),
        Binding("question_mark", "close", "Fechar", show=False),
        Binding("escape", "close", "Fechar", show=False),
        Binding("q", "close", "Fechar", show=False),
        Binding("pageup,kp_page_up", "page_up", "Rolar página", show=False),
        Binding("pagedown,kp_page_down", "page_down", "Rolar página", show=False),
    ]

    def __init__(self, text: str) -> None:
        super().__init__()
        self.evaluation_text = text

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="evaluation-dialog"):
            yield Static(Text(self.evaluation_text))

    def on_mount(self) -> None:
        self.query_one(VerticalScroll).focus()

    def action_copy(self) -> None:
        self.app.copy_to_clipboard(self.evaluation_text)
        self.app.notify("Avaliação copiada")

    def action_close(self) -> None:
        self.dismiss(None)

    def action_page_up(self) -> None:
        self.query_one(VerticalScroll).scroll_page_up()

    def action_page_down(self) -> None:
        self.query_one(VerticalScroll).scroll_page_down()


class NotesScreen(ModalScreen[None]):
    """Shows the note/reply history and lets the user keep the conversation
    going without leaving the screen: one entry point for both."""

    BINDINGS = [
        Binding("ctrl+j", "send", "Enviar", show=False),
        Binding("i", "focus_input", "Editar", show=False),
        Binding("j", "scroll_history_down", "Rolar", show=False),
        Binding("k", "scroll_history_up", "Rolar", show=False),
        Binding("ctrl+d", "scroll_history_page_down", "Rolar página", show=False),
        Binding("ctrl+u", "scroll_history_page_up", "Rolar página", show=False),
        Binding(
            "pagedown,kp_page_down", "scroll_history_page_down", "Rolar página", show=False
        ),
        Binding("pageup,kp_page_up", "scroll_history_page_up", "Rolar página", show=False),
        Binding("escape", "escape_or_close", "Fechar", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="notes-dialog"):
            with VerticalScroll(id="notes-history"):
                yield Static(id="notes-content")
            yield TextArea(id="notes-input")
            yield Static("EDITANDO", id="notes-mode")
            yield Label(
                "Ctrl+J envia · Esc sai da edição p/ rolar com j/k/Ctrl+D/Ctrl+U/"
                "PgUp/PgDn, i volta a editar, Esc de novo fecha",
                id="notes-hint",
            )

    def on_mount(self) -> None:
        self.refresh_notes()
        self.query_one(TextArea).focus()

    def refresh_notes(self) -> None:
        tree = self.app.issue_tree
        if tree.notes:
            text = "\n\n".join(f"[{note.author}] {note.text}" for note in tree.notes)
        else:
            text = "(nenhuma anotação ainda, escreva abaixo)"
        self.query_one("#notes-content", Static).update(Text(text))
        self.query_one("#notes-history", VerticalScroll).scroll_end(animate=False)

    def action_send(self) -> None:
        text_area = self.query_one(TextArea)
        text = text_area.text.strip()
        if not text:
            return
        text_area.clear()
        self.app.add_note_and_reply(text)
        self.refresh_notes()

    def action_focus_input(self) -> None:
        self.query_one(TextArea).focus()
        self.query_one("#notes-mode", Static).update("EDITANDO")

    def action_scroll_history_down(self) -> None:
        self.query_one("#notes-history", VerticalScroll).scroll_down()

    def action_scroll_history_up(self) -> None:
        self.query_one("#notes-history", VerticalScroll).scroll_up()

    def action_scroll_history_page_down(self) -> None:
        self.query_one("#notes-history", VerticalScroll).scroll_page_down()

    def action_scroll_history_page_up(self) -> None:
        self.query_one("#notes-history", VerticalScroll).scroll_page_up()

    def action_escape_or_close(self) -> None:
        """Esc leaves the input for history browsing first (like leaving Vim
        insert mode); pressed again while already browsing, it closes."""
        if self.focused is self.query_one(TextArea):
            self.query_one("#notes-history", VerticalScroll).focus()
            self.query_one("#notes-mode", Static).update("NAVEGANDO")
        else:
            self.dismiss(None)


class CaseLibraryScreen(ModalScreen[Case | None]):
    """Lists cases from the local library configured via `[cases]
    directory`, filterable by free text; Ctrl+R jumps to a random case
    among the current matches instead of requiring one to be highlighted."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancelar", show=False),
        Binding("down", "move(1)", "Descer", show=False),
        Binding("up", "move(-1)", "Subir", show=False),
        Binding("ctrl+r", "randomize", "Sortear", priority=True, show=False),
    ]

    def __init__(self, cases: list[Case]) -> None:
        super().__init__()
        self.all_cases = cases
        self.filtered: list[Case] = cases

    def compose(self) -> ComposeResult:
        with Vertical(id="case-library-dialog"):
            yield Label(
                f"{len(self.all_cases)} cases na biblioteca. "
                "Ctrl+R sorteia dentre os filtrados, Enter escolhe o destacado, Esc cancela"
            )
            yield PersistentFocusInput(placeholder="Filtrar por título, tipo ou dificuldade...", id="case-filter")
            yield ListView(id="case-list")

    def on_mount(self) -> None:
        self.refresh_list(self.all_cases)
        self.query_one("#case-filter", Input).focus()

    def refresh_list(self, cases: list[Case]) -> None:
        self.filtered = cases
        view = self.query_one("#case-list", ListView)
        view.clear()
        for case in cases:
            view.append(ListItem(Label(case.label())))

    def on_input_changed(self, event: Input.Changed) -> None:
        self.refresh_list(filter_cases(self.all_cases, event.value))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.pick_index(self.query_one("#case-list", ListView).index or 0)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.pick_index(event.list_view.index or 0)

    def pick_index(self, index: int) -> None:
        if 0 <= index < len(self.filtered):
            self.dismiss(self.filtered[index])
        else:
            self.dismiss(None)

    def action_move(self, delta: int) -> None:
        if not self.filtered:
            return
        view = self.query_one("#case-list", ListView)
        view.index = max(0, min(len(self.filtered) - 1, (view.index or 0) + delta))

    def action_randomize(self) -> None:
        case = pick_random(self.filtered)
        if case is not None:
            self.dismiss(case)

    def action_cancel(self) -> None:
        self.dismiss(None)


class MecelyApp(App):
    TITLE = "Mecely"
    SUB_TITLE = "Modelagem de issue trees para cases de consultoria"
    ENABLE_COMMAND_PALETTE = False
    CSS = build_css(Palette())
    BINDINGS = [
        Binding("ctrl+s", "save", "Salvar"),
        Binding("q", "quit", "Sair"),
        Binding("R", "case_library", "Sortear/escolher case"),
    ]

    def __init__(
        self,
        data_file: Path | None = None,
        start_new: bool = False,
        title: str | None = None,
        prompt: str | None = None,
        autosave: bool = False,
        read_only: bool = False,
        palette: Palette | None = None,
        show_clock: bool = False,
        cases_directory: Path | None = None,
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
        self.cases_directory = cases_directory
        self.issue_tree = (
            IssueTree.new(title or "Novo case", prompt)
            if start_new or data_file is None or not data_file.exists()
            else IssueTree.load(data_file)
        )
        LOGGER.info("árvore carregada: %s nós", len(list(self.issue_tree.walk())))
        self.node_ids: list[str] = []
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        self.subtree_clipboard = []
        self.visual_anchor: int | None = None
        self.insert_node_id: str | None = None
        self.insert_is_new: bool = False
        self.insert_field: str = "text"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=self.show_clock)
        yield IssueTreeList(id="tree")
        yield Static("NORMAL", id="mode-indicator")
        yield Static(
            "? ajuda · j/k mover · h/l nível · a filho · o irmão · "
            "i editar · x excluir · = valor · +-*/ operação",
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

    def is_missing_operation(self, node: Node, result: float | None) -> bool:
        """True for a non-first child that already has a number ready to
        combine (a value or a computed result) but no operation set. Not
        for every bare non-first child, since plenty of issue trees are
        qualitative and never carry numbers at all, so a bare node there is
        normal, not something forgotten."""
        if result is None:
            return False
        parent = self.issue_tree.parent_of(node.id)
        return parent is not None and parent.children[0].id != node.id

    def refresh_tree(self, select_id: str | None = None) -> None:
        view = self.query_one("#tree", ListView)
        view.clear()
        self.node_ids = []
        selected_index = 0
        for node, depth in self.issue_tree.walk(visible_only=True):
            marker = "▸" if node.collapsed and node.children else "▾" if node.children else " "
            result = node.result()
            if node.operation:
                operation = f"[{node.operation}] "
            elif self.is_missing_operation(node, result):
                operation = "[?] "
            else:
                operation = ""
            if node.children and result is not None:
                numeric = f"  = {format_number(result)}"
            elif not node.children and node.value is not None:
                numeric = f"  = {format_number(node.value)}"
            else:
                numeric = ""
            if node.id == select_id:
                selected_index = len(self.node_ids)
            self.node_ids.append(node.id)
            if node.id == self.insert_node_id and self.insert_field == "value":
                prefix = f"{'  ' * depth}{marker} {operation}{node.text}  = "
                initial = format_number(node.value) if node.value is not None else ""
                view.append(
                    ListItem(
                        Horizontal(
                            Static(prefix, classes="insert-prefix"),
                            InsertInput(value=initial, id="insert-input"),
                        )
                    )
                )
            elif node.id == self.insert_node_id:
                prefix = f"{'  ' * depth}{marker} {operation}"
                view.append(
                    ListItem(
                        Horizontal(
                            Static(prefix, classes="insert-prefix"),
                            InsertInput(value=node.text, id="insert-input"),
                        )
                    )
                )
            else:
                line = f"{'  ' * depth}{marker} {operation}{node.text}{numeric}"
                view.append(ListItem(Label(Text(line))))
        view.index = selected_index
        self.update_visual_selection()
        if self.insert_node_id is not None:
            # The Input was just appended; ListView mounts children
            # asynchronously, so focusing it has to wait for that to land.
            self.call_after_refresh(self._focus_insert_input)

    def _focus_insert_input(self) -> None:
        if self.insert_node_id is None:
            return
        try:
            self.query_one("#insert-input", InsertInput).focus()
        except NoMatches:
            pass

    def update_visual_selection(self) -> None:
        view = self.query_one("#tree", ListView)
        current = view.index or 0
        mode_indicator = self.query_one("#mode-indicator", Static)
        if self.visual_anchor is None:
            selected: set[int] = set()
        else:
            start, end = sorted((self.visual_anchor, current))
            selected = set(range(start, end + 1))
        if self.insert_node_id is not None:
            mode_indicator.update("INSERT")
            mode_indicator.remove_class("visual")
            mode_indicator.add_class("insert")
        elif self.visual_anchor is None:
            mode_indicator.update("NORMAL")
            mode_indicator.remove_class("visual")
            mode_indicator.remove_class("insert")
        else:
            mode_indicator.update("VISUAL")
            mode_indicator.add_class("visual")
            mode_indicator.remove_class("insert")
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
        LOGGER.debug("árvore salva em %s", self.data_file)

    def action_add_child(self) -> None:
        parent_id = self.selected_id()
        if parent_id is None:
            return
        self.checkpoint()
        new = self.issue_tree.add_child(parent_id, "")
        self.persist()
        self.start_insert(new.id, is_new=True)

    def action_add_sibling(self) -> None:
        node_id = self.selected_id()
        if node_id is None:
            return
        self.checkpoint()
        new = self.issue_tree.add_sibling(node_id, "")
        self.persist()
        self.start_insert(new.id, is_new=True)

    def action_edit(self) -> None:
        node_id = self.selected_id()
        if node_id is None:
            return
        if self.issue_tree.find(node_id) is None:
            return
        self.start_insert(node_id, is_new=False)

    def start_insert(self, node_id: str, is_new: bool, field: str = "text") -> None:
        """Enters Vim-style INSERT mode on a row: `i` edits the text in
        place, and `a`/`o` land here too, since in Vim they're also just
        ways of entering INSERT mode. `=` reuses the same mode for the
        node's numeric value instead. Either way, a pop-up is avoided."""
        self.insert_node_id = node_id
        self.insert_is_new = is_new
        self.insert_field = field
        self.refresh_tree(node_id)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if isinstance(event.input, InsertInput):
            self.commit_insert(event.value)

    def commit_insert(self, text: str) -> None:
        if self.insert_field == "value":
            self.commit_value_insert(text)
        else:
            self.commit_text_insert(text)

    def commit_text_insert(self, text: str) -> None:
        node_id = self.insert_node_id
        if node_id is None:
            return
        text = text.strip()
        if not text:
            self.cancel_insert()
            return
        node = self.issue_tree.find(node_id)
        if node is not None:
            if not self.insert_is_new:
                self.checkpoint()
            node.text = text
            self.persist()
        self.end_insert(node_id)

    def commit_value_insert(self, text: str) -> None:
        node_id = self.insert_node_id
        if node_id is None:
            return
        node = self.issue_tree.find(node_id)
        if node is None:
            self.end_insert(node_id)
            return
        try:
            value = evaluate(text)
        except CalculationError as error:
            self.notify(str(error), severity="error")
            self.end_insert(node_id)
            return
        self.checkpoint()
        node.value = value
        self.persist()
        self.end_insert(node_id)

    def cancel_insert(self) -> None:
        """Esc while typing cancels: an existing node's text/value is left
        untouched, and a brand-new row (from a/o) is removed entirely along
        with the checkpoint taken for it, exactly as if it had never been
        added, matching what `u` would do anyway, minus the extra step."""
        node_id = self.insert_node_id
        if self.insert_is_new and node_id is not None:
            self.issue_tree.delete(node_id)
            if self.undo_stack:
                self.undo_stack.pop()
            self.persist()
            self.end_insert(None)
        else:
            self.end_insert(node_id)

    def end_insert(self, select_id: str | None) -> None:
        self.insert_node_id = None
        self.insert_is_new = False
        self.insert_field = "text"
        self.refresh_tree(select_id)
        self.query_one("#tree", IssueTreeList).focus()

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
            self.notify("Defina as operações nos filhos com +/-/*//", severity="warning")
            return
        self.start_insert(node_id, is_new=False, field="value")

    def node_needing_operation(self) -> Node | None:
        """The selected node, if it's eligible to carry an operation (has a
        previous sibling to combine with). Notifies and returns None
        otherwise, since +/-/*// apply directly with no prompt to say why
        they didn't do anything. Clearing (Backspace) doesn't use this: a
        first child/root already has no operation to clear, so it should
        stay a silent no-op rather than repeat a warning meant for setting."""
        node_id = self.selected_id()
        if node_id is None:
            return None
        node = self.issue_tree.find(node_id)
        parent = self.issue_tree.parent_of(node_id)
        if node is None or parent is None:
            self.notify("A raiz não possui operação com irmão anterior", severity="warning")
            return None
        index = next(i for i, child in enumerate(parent.children) if child.id == node_id)
        if index == 0:
            self.notify("O primeiro filho inicia a expressão", severity="warning")
            return None
        return node

    def action_set_operation(self, symbol: str) -> None:
        node = self.node_needing_operation()
        if node is None:
            return
        self.checkpoint()
        node.operation = symbol
        self.persist()
        self.refresh_tree(node.id)

    def action_clear_operation(self) -> None:
        node_id = self.selected_id()
        if node_id is None:
            return
        node = self.issue_tree.find(node_id)
        if node is None or node.operation is None:
            return
        self.checkpoint()
        node.operation = None
        self.persist()
        self.refresh_tree(node.id)

    def add_note_and_reply(self, text: str) -> None:
        self.checkpoint()
        self.issue_tree.add_note("user", text)
        self.persist()
        if shutil.which("claude") is not None:
            self.reply_to_note()

    @work
    async def reply_to_note(self) -> None:
        self.notify("Aguardando resposta da IA...")
        reply, error = await self._call_claude(build_note_reply_prompt(self.issue_tree))
        if error is not None or not reply:
            return
        self.checkpoint()
        self.issue_tree.add_note("ai", reply)
        self.persist()
        if isinstance(self.screen, NotesScreen):
            self.screen.refresh_notes()
        else:
            self.notify(reply, title="IA", timeout=10)

    def action_view_notes(self) -> None:
        self.push_screen(NotesScreen())

    async def _call_claude(self, prompt: str) -> tuple[str | None, str | None]:
        """Calls `claude -p <prompt>`. Returns (stdout, error); exactly one is None."""
        try:
            process = await asyncio.create_subprocess_exec(
                "claude",
                "-p",
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
        except OSError as error:
            return None, str(error)
        if process.returncode != 0:
            return None, stderr.decode(errors="replace").strip() or "erro desconhecido"
        return stdout.decode(errors="replace").strip(), None

    @work
    async def action_evaluate(self) -> None:
        if shutil.which("claude") is None:
            self.notify("Claude Code CLI (claude) não encontrado no PATH", severity="error")
            return
        confirmed = await self.push_screen_wait(ConfirmScreen("Avaliar este case com IA agora?"))
        if not confirmed:
            return
        self.notify("Avaliando com IA...")
        result, error = await self._call_claude(build_prompt(self.issue_tree))
        if error is not None:
            self.notify(f"Avaliação falhou: {error}", severity="error")
            return
        self.push_screen(EvaluationScreen(result))

    @work
    async def action_case_library(self) -> None:
        if self.read_only:
            self.notify("Não é possível carregar um case em modo somente leitura", severity="error")
            return
        if self.cases_directory is None:
            self.notify(
                "Nenhum diretório de cases configurado (defina cases.directory no config.toml)",
                severity="error",
            )
            return
        try:
            library = load_library(self.cases_directory)
        except CaseLibraryError as error:
            self.notify(str(error), severity="error")
            return
        if not library:
            self.notify("Biblioteca de cases está vazia", severity="warning")
            return
        case = await self.push_screen_wait(CaseLibraryScreen(library))
        if case is None:
            return
        self.checkpoint()
        self.issue_tree = IssueTree.new(
            title=case.title or case.id,
            prompt=case.label(),
            case_source=case.full_text(),
        )
        self.visual_anchor = None
        self.persist(force=True)
        self.refresh_tree()
        self.notify(f"Case carregado: {case.title or case.id}")

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
            self.notify(f"{len(self.subtree_clipboard)} subárvore(s) copiada(s)")

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
            self.notify("Nada para desfazer")
            return
        selected = self.selected_id()
        self.redo_stack.append(self.issue_tree.to_dict())
        self.issue_tree = IssueTree.from_dict(self.undo_stack.pop())
        self.visual_anchor = None
        self.persist()
        self.refresh_tree(selected)

    def action_redo(self) -> None:
        if not self.redo_stack:
            self.notify("Nada para refazer")
            return
        selected = self.selected_id()
        self.undo_stack.append(self.issue_tree.to_dict())
        self.issue_tree = IssueTree.from_dict(self.redo_stack.pop())
        self.visual_anchor = None
        self.persist()
        self.refresh_tree(selected)

    def action_save(self) -> None:
        if self.read_only:
            self.notify("Arquivo aberto como somente leitura", severity="warning")
            return
        if self.data_file is None:
            self.push_screen(
                TextPrompt("Salvar como arquivo JSON", "case.json"),
                self.finish_save_as,
            )
            return
        self.persist(force=True)
        self.notify(f"Salvo em {self.data_file}")

    def finish_save_as(self, text: str | None) -> None:
        if text is None:
            return
        path = Path(text).expanduser()
        if not path.suffix:
            path = path.with_suffix(".json")
        elif path.suffix.lower() != ".json":
            self.notify("O arquivo deve usar a extensão .json", severity="error")
            return
        try:
            self.issue_tree.save(path)
        except OSError as error:
            self.notify(f"Não foi possível salvar: {error}", severity="error")
            return
        self.data_file = path
        LOGGER.debug("árvore salva em %s", self.data_file)
        self.notify(f"Salvo em {self.data_file}")

    def action_help(self) -> None:
        self.push_screen(HelpScreen())


def main() -> None:
    from .cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
