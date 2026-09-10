import ast
import json
import tomllib
import unittest
from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mecely.calculator import CalculationError, evaluate
from mecely.cases import Case, CaseLibraryError, filter_cases, load_library, pick_random
from mecely.cli import build_app_command, build_parser, find_available_port, resolve_file
from mecely.config import ConfigError, Palette, load_config
from mecely.evaluation import (
    RUBRIC,
    STRICT_NOTE_REPLY_INSTRUCTIONS,
    build_note_reply_prompt,
    build_prompt,
    render_tree,
)
from mecely.model import IssueTree


class IssueTreeTests(unittest.TestCase):
    def test_add_child_and_sibling(self) -> None:
        tree = IssueTree.new()
        first = tree.add_child(tree.root.id, "Revenue")
        second = tree.add_sibling(first.id, "Costs")
        self.assertEqual([node.text for node in tree.root.children], ["Revenue", "Costs"])
        self.assertIs(tree.parent_of(second.id), tree.root)

    def test_delete_preserves_root(self) -> None:
        tree = IssueTree.new()
        child = tree.add_child(tree.root.id, "Revenue")
        self.assertFalse(tree.delete(tree.root.id))
        self.assertTrue(tree.delete(child.id))
        self.assertEqual(tree.root.children, [])

    def test_round_trip(self) -> None:
        tree = IssueTree.new("Profitability")
        child = tree.add_child(tree.root.id, "Revenue")
        child.operation = "*"
        child.collapsed = True
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tree.json"
            tree.save(path)
            loaded = IssueTree.load(path)
        self.assertEqual(loaded.to_dict(), tree.to_dict())

    def test_prompt_round_trips_and_defaults_to_none(self) -> None:
        tree = IssueTree.new("Case", prompt="Nosso cliente é uma rede de farmácias...")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tree.json"
            tree.save(path)
            loaded = IssueTree.load(path)
        self.assertEqual(loaded.prompt, tree.prompt)
        self.assertIsNone(IssueTree.new("Case sem prompt").prompt)

    def test_loads_legacy_file_without_prompt_field(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text('{"title": "Legado", "root": {"id": "root", "text": "Raiz"}}')
            loaded = IssueTree.load(path)
        self.assertIsNone(loaded.prompt)

    def test_case_source_round_trips_and_defaults_to_none(self) -> None:
        tree = IssueTree.new("Case", case_source="Texto integral do case sourced...")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tree.json"
            tree.save(path)
            loaded = IssueTree.load(path)
        self.assertEqual(loaded.case_source, tree.case_source)
        self.assertIsNone(IssueTree.new("Case sem case_source").case_source)

    def test_loads_legacy_file_without_case_source_field(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text('{"title": "Legado", "root": {"id": "root", "text": "Raiz"}}')
            loaded = IssueTree.load(path)
        self.assertIsNone(loaded.case_source)

    def test_notes_round_trip_with_author_and_text(self) -> None:
        tree = IssueTree.new("Case")
        tree.add_note("user", "Qual a taxa de churn mensal?")
        tree.add_note("ai", "5% ao mês, estável nos últimos 3 trimestres.")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tree.json"
            tree.save(path)
            loaded = IssueTree.load(path)
        self.assertEqual(loaded.notes, tree.notes)
        self.assertEqual(
            [(note.author, note.text) for note in loaded.notes],
            [
                ("user", "Qual a taxa de churn mensal?"),
                ("ai", "5% ao mês, estável nos últimos 3 trimestres."),
            ],
        )

    def test_new_tree_starts_with_no_notes(self) -> None:
        self.assertEqual(IssueTree.new().notes, [])

    def test_loads_legacy_file_without_notes_field(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text('{"title": "Legado", "root": {"id": "root", "text": "Raiz"}}')
            loaded = IssueTree.load(path)
        self.assertEqual(loaded.notes, [])

    def test_paste_clones_subtree_with_new_ids(self) -> None:
        tree = IssueTree.new()
        branch = tree.add_child(tree.root.id, "Revenue")
        leaf = tree.add_child(branch.id, "Price")
        copies = tree.insert_after(branch.id, [branch])
        self.assertEqual(copies[0].text, branch.text)
        self.assertNotEqual(copies[0].id, branch.id)
        self.assertNotEqual(copies[0].children[0].id, leaf.id)
        self.assertIsNone(copies[0].operation)

    def test_deleting_first_child_clears_new_first_operation(self) -> None:
        tree = IssueTree.new()
        first = tree.add_child(tree.root.id, "A")
        second = tree.add_child(tree.root.id, "B")
        second.operation = "-"
        tree.delete(first.id)
        self.assertIsNone(second.operation)


class ApplicationSourceTests(unittest.TestCase):
    def test_subtitle_describes_general_use(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        self.assertIn(
            'SUB_TITLE = "Modelagem de issue trees para cases de consultoria"', app_source
        )
        self.assertNotIn("structured reasoning for interviews", app_source)
        # first-time users shouldn't be greeted with a subtitle implying
        # Vim knowledge is a prerequisite.
        self.assertNotIn("Vim-first", app_source)

    def test_does_not_shadow_textual_tree_property(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        self.assertNotIn("self.tree =", app_source)
        self.assertNotIn("self.clipboard =", app_source)
        self.assertIn("self.subtree_clipboard =", app_source)
        self.assertIn("Label(Text(line))", app_source)
        self.assertNotIn("Label(line)", app_source)
        self.assertIn("ENABLE_COMMAND_PALETTE = False", app_source)
        self.assertNotIn("yield Footer(", app_source)
        self.assertIn('id="shortcuts"', app_source)
        self.assertIn("#shortcuts {{", app_source)
        self.assertIn("height: auto", app_source)
        self.assertNotIn("text-wrap:", app_source)

    def test_modal_submit_keys_are_not_priority_bindings(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        app_bindings = app_source.split("class MecelyApp", 1)[1].split("def __init__", 1)[0]
        self.assertNotIn('Binding("enter", "add_sibling"', app_bindings)
        self.assertNotIn('Binding("tab", "add_child"', app_bindings)
        self.assertIn("class IssueTreeList(ListView):", app_source)
        self.assertIn("if isinstance(self.screen, ModalScreen):", app_source)

    def test_configured_selection_overrides_textual_focus_style(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        self.assertIn("#tree:focus > ListItem.--highlight", app_source)
        self.assertIn("background: {palette.selected}", app_source)
        self.assertIn("color: {palette.selected_text}", app_source)
        self.assertIn("#tree:focus > ListItem.visual", app_source)
        self.assertIn("item.styles.background = self.palette.selected", app_source)
        self.assertIn("item.styles.color = self.palette.selected_text", app_source)
        self.assertIn("def on_list_view_highlighted", app_source)

    def test_list_view_highlighted_ignores_other_list_views(self) -> None:
        """Other ListViews (e.g. the case library's) bubble Highlighted up
        to the app too; reacting to them crashes, since query_one("#tree")
        can't reach the tree while another screen sits on top of it."""
        app_source = Path("src/mecely/app.py").read_text()
        handler = app_source.split("def on_list_view_highlighted", 1)[1].split(
            "def selected_node_ids", 1
        )[0]
        guard_index = handler.index('if event.list_view.id != "tree":\n            return')
        update_index = handler.index("self.update_visual_selection()")
        self.assertLess(guard_index, update_index)

    def test_custom_css_is_installed_before_textual_initializes(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        constructor = app_source.split("class MecelyApp", 1)[1].split("def compose", 1)[0]
        css_position = constructor.index("self.CSS = build_css(self.palette)")
        super_position = constructor.index("super().__init__()")
        self.assertLess(css_position, super_position)

    def test_vim_bindings_live_on_the_tree_widget(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        tree_widget = app_source.split("class IssueTreeList", 1)[1].split("class TextPrompt", 1)[0]
        for binding in (
            'Binding("j", "cursor_down"',
            'Binding("k", "cursor_up"',
            'Binding("h", "parent_or_collapse"',
            'Binding("l", "child_or_expand"',
            'Binding("a", "add_child"',
            'Binding("o", "add_sibling"',
            'Binding("i", "edit"',
            'Binding("x", "delete"',
            'Binding("u", "undo"',
            'Binding("ctrl+r", "redo"',
            'Binding("V", "visual"',
            'Binding("y", "yank"',
            'Binding("p", "paste"',
            'Binding("plus", "set_operation(\'+\')"',
            'Binding("minus", "set_operation(\'-\')"',
            'Binding("asterisk", "set_operation(\'*\')"',
            'Binding("slash", "set_operation(\'/\')"',
            'Binding("backspace", "clear_operation"',
            'Binding("c", "view_notes"',
            'Binding("exclamation_mark", "evaluate"',
            'Binding("question_mark", "help"',
        ):
            self.assertIn(binding, tree_widget)

    def test_evaluation_screen_supports_copy_shortcut(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        evaluation_screen = app_source.split("class EvaluationScreen", 1)[1].split("class NotesScreen", 1)[0]
        self.assertIn('Binding("y", "copy"', evaluation_screen)
        self.assertIn("self.app.copy_to_clipboard(self.evaluation_text)", evaluation_screen)

    def test_text_prompt_reclaims_focus_after_a_stray_click(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        persistent_input = app_source.split("class PersistentFocusInput", 1)[1].split("class TextPrompt", 1)[0]
        self.assertIn("def on_blur", persistent_input)
        self.assertIn("self.focus()", persistent_input)
        text_prompt = app_source.split("class TextPrompt", 1)[1].split("class ", 1)[0]
        self.assertIn("PersistentFocusInput(value=self.value, id=\"value\")", text_prompt)

    def test_scrollable_modal_screens_focus_their_scroll_container(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        for screen_class, next_class in (
            ("HelpScreen", "EvaluationScreen"),
            ("EvaluationScreen", "CaseBriefingScreen"),
            ("CaseBriefingScreen", "NotesScreen"),
        ):
            screen_source = app_source.split(f"class {screen_class}", 1)[1].split(next_class, 1)[0]
            self.assertIn(
                "self.query_one(VerticalScroll).focus()",
                screen_source,
                f"{screen_class} should focus its VerticalScroll on mount so keyboard scrolling works",
            )
            # Some terminals report PageUp/PageDown as kp_page_up/kp_page_down
            # (a Kitty-keyboard-protocol keypad variant) instead of plain
            # pageup/pagedown, which VerticalScroll's own bindings don't
            # cover, so these screens bind both explicitly.
            self.assertIn('Binding("pageup,kp_page_up", "page_up"', screen_source)
            self.assertIn('Binding("pagedown,kp_page_down", "page_down"', screen_source)

    def test_case_library_screen_shares_scroll_shortcuts_with_notes_screen(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        screen_source = app_source.split("class CaseLibraryScreen", 1)[1].split(
            "class MecelyApp", 1
        )[0]
        self.assertIn('Binding("ctrl+d", "move(5)"', screen_source)
        self.assertIn('Binding("ctrl+u", "move(-5)"', screen_source)
        self.assertIn('Binding("pagedown,kp_page_down", "move(5)"', screen_source)
        self.assertIn('Binding("pageup,kp_page_up", "move(-5)"', screen_source)

    def test_case_library_randomize_highlights_instead_of_picking(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        action_randomize = app_source.split("def action_randomize", 1)[1].split(
            "def action_cancel", 1
        )[0]
        self.assertNotIn("self.dismiss(case)", action_randomize)
        self.assertIn(
            '.index = self.filtered.index(case)',
            action_randomize,
        )

    def test_case_briefing_screen_hints_at_reopening_with_e(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        screen_source = app_source.split("class CaseBriefingScreen", 1)[1].split(
            "class NotesScreen", 1
        )[0]
        self.assertIn("E reabre a qualquer momento", screen_source)
        self.assertIn('id="case-briefing-hint"', screen_source)

    def test_add_note_and_reply_backgrounds_ai_reply_as_a_worker(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        add_note_and_reply = app_source.split("def add_note_and_reply", 1)[1].split(
            "async def reply_to_note", 1
        )[0]
        self.assertIn("self.reply_to_note()", add_note_and_reply)
        decorator_section, reply_to_note = app_source.split("async def reply_to_note", 1)
        reply_to_note = reply_to_note.split("def action_view_notes", 1)[0]
        self.assertTrue(decorator_section.rstrip().endswith("@work"))
        notify_index = reply_to_note.index('self.notify("Aguardando resposta da IA...")')
        call_index = reply_to_note.index("await self._call_claude(build_note_reply_prompt")
        self.assertLess(notify_index, call_index)
        self.assertIn("isinstance(self.screen, NotesScreen)", reply_to_note)
        self.assertIn("self.screen.refresh_notes()", reply_to_note)

    def test_notes_screen_sends_via_ctrl_j_and_stays_open(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        notes_screen = app_source.split("class NotesScreen", 1)[1].split("class MecelyApp", 1)[0]
        self.assertIn('Binding("ctrl+j", "send"', notes_screen)
        self.assertIn("self.app.add_note_and_reply(text)", notes_screen)
        self.assertIn("self.refresh_notes()", notes_screen)
        self.assertIn("text_area.clear()", notes_screen)

    def test_notes_screen_toggles_between_editing_and_vim_style_browsing(self) -> None:
        # TextArea binds j/k/ctrl+d/ctrl+u/pageup/pagedown internally for text
        # editing while it has focus, so real Vim scroll keys only work once
        # focus has moved off it, which is the point of the escape/i toggle.
        # kp_page_up/kp_page_down are separate key names some terminals send
        # for PageUp/PageDown (confirmed via a Kitty-keyboard-protocol capable
        # terminal); TextArea doesn't claim those, so they're bound explicitly
        # rather than relying on the inherited plain pageup/pagedown bindings.
        app_source = Path("src/mecely/app.py").read_text()
        notes_screen = app_source.split("class NotesScreen", 1)[1].split("class MecelyApp", 1)[0]
        for binding in (
            'Binding("i", "focus_input"',
            'Binding("j", "scroll_history_down"',
            'Binding("k", "scroll_history_up"',
            'Binding("ctrl+d", "scroll_history_page_down"',
            'Binding("ctrl+u", "scroll_history_page_up"',
            'Binding(\n            "pagedown,kp_page_down", "scroll_history_page_down"',
            'Binding("pageup,kp_page_up", "scroll_history_page_up"',
            'Binding("escape", "escape_or_close"',
        ):
            self.assertIn(binding, notes_screen)
        self.assertIn('self.query_one("#notes-history", VerticalScroll).scroll_down()', notes_screen)
        self.assertIn('self.query_one("#notes-history", VerticalScroll).scroll_up()', notes_screen)
        self.assertIn('self.query_one("#notes-history", VerticalScroll).scroll_page_down()', notes_screen)
        self.assertIn('self.query_one("#notes-history", VerticalScroll).scroll_page_up()', notes_screen)
        # escape while the TextArea is focused moves focus to the history
        # instead of closing; only escape from history closes the screen.
        self.assertIn('self.focused is self.query_one(TextArea)', notes_screen)
        self.assertIn('self.query_one("#notes-history", VerticalScroll).focus()', notes_screen)
        self.assertIn("self.dismiss(None)", notes_screen)
        # NotesScreen's own editing/browsing toggle should be visible, not
        # just inferable from where the cursor happens to be.
        self.assertIn('yield Static("EDITANDO", id="notes-mode")', notes_screen)
        self.assertIn('self.query_one("#notes-mode", Static).update("EDITANDO")', notes_screen)
        self.assertIn('self.query_one("#notes-mode", Static).update("NAVEGANDO")', notes_screen)

    def test_mode_indicator_reflects_normal_and_visual_state(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        self.assertIn('yield Static("NORMAL", id="mode-indicator")', app_source)
        update_visual_selection = app_source.split("def update_visual_selection", 1)[1].split(
            "def on_list_view_highlighted", 1
        )[0]
        self.assertIn('mode_indicator.update("NORMAL")', update_visual_selection)
        self.assertIn('mode_indicator.remove_class("visual")', update_visual_selection)
        self.assertIn('mode_indicator.update("VISUAL")', update_visual_selection)
        self.assertIn('mode_indicator.add_class("visual")', update_visual_selection)
        # a third state, INSERT, is checked first so it wins over a lingering
        # visual_anchor from before the edit started.
        self.assertIn('mode_indicator.update("INSERT")', update_visual_selection)
        self.assertIn('mode_indicator.add_class("insert")', update_visual_selection)
        self.assertIn("if self.insert_node_id is not None:", update_visual_selection)

    def test_double_click_on_tree_edits_like_i(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        tree_widget = app_source.split("class IssueTreeList", 1)[1].split(
            "class PersistentFocusInput", 1
        )[0]
        on_click = tree_widget.split("def on_click", 1)[1]
        self.assertIn("event.chain >= 2", on_click)
        self.assertIn("self.action_edit()", on_click)

    def test_tree_edits_are_inline_insert_mode_not_a_popup(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        self.assertIn("class InsertInput(Input):", app_source)
        insert_input = app_source.split("class InsertInput", 1)[1].split(
            "class PersistentFocusInput", 1
        )[0]
        self.assertIn('Binding("escape", "cancel_insert"', insert_input)
        self.assertIn("self.app.cancel_insert()", insert_input)

        tree_widget = app_source.split("class IssueTreeList", 1)[1].split(
            "class InsertInput", 1
        )[0]
        # a/Tab/o/Enter are priority bindings so IssueTreeList itself can
        # override ListView's own same-key defaults; without check_action
        # disabling them while inline-editing, they'd steal those keys away
        # from the focused Input before it ever saw them, and bare Up/Down
        # would shift the selection out from under the row being typed into.
        check_action = tree_widget.split("def check_action", 1)[1]
        for disabled_action in (
            '"add_child"', '"add_sibling"', '"cursor_up"', '"cursor_down"', '"redo"',
        ):
            self.assertIn(disabled_action, check_action)
        self.assertIn("self.app.insert_node_id is not None", check_action)

        app_body = app_source.split("class MecelyApp", 1)[1]
        self.assertIn("self.insert_node_id: str | None = None", app_body)
        self.assertNotIn(
            'self.push_screen(TextPrompt("Novo ramo filho")', app_body
        )
        self.assertNotIn('self.push_screen(TextPrompt("Editar nó"', app_body)
        self.assertIn(
            'def start_insert(self, node_id: str, is_new: bool, field: str = "text")', app_body
        )
        self.assertIn("def commit_insert(self, text: str)", app_body)
        self.assertIn("def cancel_insert(self)", app_body)
        # commit only checkpoints for an edit of an existing node; a brand
        # new node was already checkpointed once, at creation time.
        commit_insert = app_body.split("def commit_insert", 1)[1].split("def cancel_insert", 1)[0]
        self.assertIn("if not self.insert_is_new:\n                self.checkpoint()", commit_insert)
        # canceling a brand-new node deletes it and pops the checkpoint
        # taken for it, leaving no trace and no stray undo entry.
        cancel_insert = app_body.split("def cancel_insert", 1)[1]
        self.assertIn("self.issue_tree.delete(node_id)", cancel_insert.split("\n\n", 1)[0])
        self.assertIn("self.undo_stack.pop()", cancel_insert.split("\n\n", 1)[0])
        self.assertIn(
            "def on_input_submitted(self, event: Input.Submitted)", app_body
        )
        self.assertIn("isinstance(event.input, InsertInput)", app_body)

    def test_operation_symbols_apply_directly_without_a_prompt(self) -> None:
        # +/-/*// used to open a TextPrompt that only ever accepted one of
        # those four symbols anyway, so binding them directly removes a
        # pointless round trip. Backspace clears the operation.
        app_source = Path("src/mecely/app.py").read_text()
        tree_widget = app_source.split("class IssueTreeList", 1)[1].split(
            "class InsertInput", 1
        )[0]
        for binding in (
            "Binding(\"plus\", \"set_operation('+')\"",
            "Binding(\"minus\", \"set_operation('-')\"",
            "Binding(\"asterisk\", \"set_operation('*')\"",
            "Binding(\"slash\", \"set_operation('/')\"",
            'Binding("backspace", "clear_operation"',
        ):
            self.assertIn(binding, tree_widget)
        self.assertIn("def action_set_operation(self, symbol: str) -> None:", tree_widget)
        self.assertIn("self.app.action_set_operation(symbol)", tree_widget)
        self.assertIn("def action_clear_operation(self) -> None:", tree_widget)
        self.assertIn("self.app.action_clear_operation()", tree_widget)

        app_body = app_source.split("class MecelyApp", 1)[1]
        self.assertNotIn("def action_operation(self)", app_body)
        self.assertNotIn("def finish_operation(self", app_body)
        self.assertIn("def node_needing_operation(self) -> Node | None:", app_body)
        self.assertIn("def action_set_operation(self, symbol: str) -> None:", app_body)
        self.assertIn("def action_clear_operation(self) -> None:", app_body)
        clear_operation = app_body.split("def action_clear_operation", 1)[1].split(
            "\n\n", 1
        )[0]
        self.assertIn("if node is None or node.operation is None:", clear_operation)
        self.assertIn("node.operation = None", clear_operation)
        # Backspace must not reuse node_needing_operation: that warns with
        # wording meant for *setting* an operation ("o primeiro filho inicia
        # a expressão"), which is confusing for a clear that had nothing to
        # clear anyway; it should just no-op silently instead.
        self.assertNotIn("node_needing_operation", clear_operation)

    def test_numeric_value_is_also_edited_inline_not_in_a_popup(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        app_body = app_source.split("class MecelyApp", 1)[1]
        self.assertNotIn("def finish_numeric(self", app_body)
        self.assertNotIn("Valor estimado (aceita", app_body)
        action_numeric = app_body.split("def action_numeric", 1)[1].split(
            "def node_needing_operation", 1
        )[0]
        # a leaf with children can't carry a value; the warning names the
        # keys that actually exist now, not the old "R" shortcut.
        self.assertIn("Defina as operações nos filhos com +/-/*//", action_numeric)
        self.assertIn('self.start_insert(node_id, is_new=False, field="value")', action_numeric)

        self.assertIn('def start_insert(self, node_id: str, is_new: bool, field: str = "text")', app_body)
        self.assertIn("def commit_value_insert(self, text: str)", app_body)
        commit_value_insert = app_body.split("def commit_value_insert", 1)[1].split(
            "def cancel_insert", 1
        )[0]
        self.assertIn("value = evaluate(text)", commit_value_insert)
        self.assertIn("except CalculationError as error:", commit_value_insert)
        self.assertIn("node.value = value", commit_value_insert)

        refresh_tree = app_body.split("def refresh_tree", 1)[1].split(
            "def _focus_insert_input", 1
        )[0]
        self.assertIn('self.insert_field == "value"', refresh_tree)
        self.assertIn(
            'prefix = f"{\'  \' * depth}{marker} {operation}{node.text}  = "', refresh_tree
        )

    def test_tree_marks_a_missing_operation_only_when_a_number_is_involved(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        app_body = app_source.split("class MecelyApp", 1)[1]
        self.assertIn(
            "def is_missing_operation(self, node: Node, result: float | None) -> bool:",
            app_body,
        )
        is_missing_operation, rest = app_body.split("def is_missing_operation", 1)[1].split(
            "def refresh_tree", 1
        )
        # A qualitative tree with no values anywhere shouldn't get flagged;
        # only a node that already has a real number to combine.
        self.assertIn("if result is None:\n            return False", is_missing_operation)
        self.assertIn("parent.children[0].id != node.id", is_missing_operation)
        refresh_tree = rest.split("def update_visual_selection", 1)[0]
        self.assertIn("self.is_missing_operation(node, result)", refresh_tree)
        self.assertIn('operation = "[?] "', refresh_tree)

    def test_action_evaluate_runs_as_a_worker(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        # rsplit: "def action_evaluate" also matches the IssueTreeList
        # delegate earlier in the file; the real implementation is the last one.
        before, action_evaluate = app_source.rsplit("async def action_evaluate", 1)
        self.assertTrue(before.rstrip().endswith("@work"))
        confirm_index = action_evaluate.index("await self.push_screen_wait(ConfirmScreen(")
        notify_index = action_evaluate.index('self.notify("Avaliando com IA...")')
        call_index = action_evaluate.index("await self._call_claude(build_prompt")
        self.assertLess(confirm_index, notify_index)
        self.assertLess(notify_index, call_index)
        self.assertIn("if not confirmed:\n            return", action_evaluate)

    def test_action_case_library_prompts_for_a_session_only_path_when_unset(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        before, action_case_library = app_source.rsplit("async def action_case_library", 1)
        self.assertTrue(before.rstrip().endswith("@work"))
        self.assertIn("if file is None:", action_case_library)
        self.assertIn("if not entered:\n                return", action_case_library)
        self.assertIn("file = Path(entered).expanduser()", action_case_library)
        prompt_index = action_case_library.index("await self.push_screen_wait(\n                TextPrompt(")
        load_index = action_case_library.index("library = load_library(file)")
        remember_index = action_case_library.index("self.cases_file = file")
        self.assertLess(prompt_index, load_index)
        self.assertLess(load_index, remember_index)

    def test_action_case_library_shows_enunciado_after_loading_a_case(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        action_case_library = app_source.split("async def action_case_library", 1)[1].split(
            "def action_show_case_briefing", 1
        )[0]
        self.assertIn('prompt=case.enunciado or case.label(),', action_case_library)
        refresh_index = action_case_library.index("self.refresh_tree()")
        briefing_index = action_case_library.index(
            "self.call_after_refresh(self.action_show_case_briefing)"
        )
        self.assertLess(refresh_index, briefing_index)

    def test_action_show_case_briefing_warns_when_nothing_is_loaded(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        action_show_case_briefing = app_source.split("def action_show_case_briefing", 1)[1].split(
            "def action_delete", 1
        )[0]
        self.assertIn("if not self.issue_tree.prompt:", action_show_case_briefing)
        self.assertIn('severity="warning"', action_show_case_briefing)
        self.assertIn(
            "self.push_screen(CaseBriefingScreen(self.issue_tree.title, self.issue_tree.prompt))",
            action_show_case_briefing,
        )

    def test_confirm_screen_supports_yes_and_no(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        confirm_screen = app_source.split("class ConfirmScreen", 1)[1].split("HELP_TEXT", 1)[0]
        self.assertIn('Binding("y", "confirm"', confirm_screen)
        self.assertIn('Binding("n", "cancel"', confirm_screen)
        self.assertIn('Binding("escape", "cancel"', confirm_screen)
        self.assertIn("self.dismiss(True)", confirm_screen)
        self.assertIn("self.dismiss(False)", confirm_screen)

    def test_gg_chord_moves_to_first_node(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        tree_widget = app_source.split("class IssueTreeList", 1)[1].split("class PersistentFocusInput", 1)[0]
        self.assertIn('Binding("g", "maybe_first"', tree_widget)
        self.assertIn("def action_maybe_first(self) -> None:", tree_widget)
        self.assertIn("self.action_first()", tree_widget)
        self.assertIn("_pending_g", tree_widget)

    def test_compact_shortcut_bar_keeps_contextual_groups(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        for group in (
            "? ajuda", "j/k mover", "h/l nível", "a filho", "o irmão",
            "i editar", "x excluir", "= valor", "+-*/ operação",
        ):
            self.assertIn(group, app_source)
        shortcut_text = app_source.split('yield Static(\n            "? ajuda', 1)[1].split('id="shortcuts"', 1)[0]
        for advanced_group in ("desfazer/refazer", "visual/copiar/colar", "salvar · q sair"):
            self.assertNotIn(advanced_group, shortcut_text)

    def test_redundant_status_bar_is_not_rendered(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        self.assertNotIn('Static(id="status")', app_source)
        self.assertNotIn("def refresh_status", app_source)
        self.assertNotIn("#status {", app_source)

    def test_help_screen_documents_advanced_bindings(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        self.assertIn("class HelpScreen(ModalScreen[None]):", app_source)
        for detail in (
            "a ou Tab", "o ou Enter", "gg / G", "Ctrl+D / Ctrl+U",
            "Operações: +, -, *, /", "215m * 5% * 120",
        ):
            self.assertIn(detail, app_source)

    def test_every_tree_delegate_exists_on_the_app(self) -> None:
        module = ast.parse(Path("src/mecely/app.py").read_text())
        classes = {node.name: node for node in module.body if isinstance(node, ast.ClassDef)}
        tree_class = classes["IssueTreeList"]
        app_class = classes["MecelyApp"]
        app_methods = {
            node.name for node in app_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        delegates = {
            call.func.attr
            for method in tree_class.body
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
            for call in ast.walk(method)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Attribute)
            and isinstance(call.func.value.value, ast.Name)
            and call.func.value.value.id == "self"
            and call.func.value.attr == "app"
            and call.func.attr.startswith("action_")
        }
        self.assertTrue(delegates)
        self.assertEqual(delegates - app_methods, set())
        self.assertIn("action_edit", app_methods)


class CommandLineTests(unittest.TestCase):
    def test_help_documents_main_modes(self) -> None:
        help_text = build_parser().format_help()
        for option in (
            "--new", "--title", "--autosave", "--read-only", "--verbose", "--version",
            "--web", "--host", "--port", "--public-url", "--config",
        ):
            self.assertIn(option, help_text)

    def test_explicit_file_wins(self) -> None:
        path = Path("case.json")
        self.assertEqual(resolve_file(path, start_new=False), path)

    def test_invocation_without_file_uses_unnamed_buffer(self) -> None:
        self.assertIsNone(resolve_file(None, start_new=False))
        self.assertIsNone(resolve_file(None, start_new=True))

    def test_web_child_command_preserves_options_without_recursion(self) -> None:
        args = build_parser().parse_args([
            "case with spaces.json", "--new", "--title", "Brazilian market",
            "--no-autosave", "-vv", "--web",
        ])
        command = build_app_command(args, args.file)
        self.assertIn("'case with spaces.json'", command)
        self.assertIn("'Brazilian market'", command)
        self.assertIn("--no-autosave", command)
        self.assertIn("-vv", command)
        self.assertNotIn("--web", command)

    def test_web_child_can_preserve_unnamed_buffer(self) -> None:
        args = build_parser().parse_args(["--web"])
        command = build_app_command(args, None)
        self.assertNotIn(".mecely.json", command)

    def test_save_as_requires_json_and_associates_file(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        self.assertIn('TextPrompt("Salvar como arquivo JSON", "case.json")', app_source)
        self.assertIn('path = path.with_suffix(".json")', app_source)
        self.assertIn('path.suffix.lower() != ".json"', app_source)
        self.assertIn("self.data_file = path", app_source)

    def test_web_chooses_next_available_port(self) -> None:
        availability = {8000: False, 8001: False, 8002: True}
        with patch("mecely.cli.port_is_available", side_effect=lambda host, port: availability[port]):
            self.assertEqual(find_available_port("localhost", 8000, attempts=3), 8002)


class ConfigurationTests(unittest.TestCase):
    def test_autosave_is_disabled_by_default(self) -> None:
        with TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.toml"
            config, _ = load_config(missing)
        self.assertFalse(config.storage.autosave)

    def test_does_not_advertise_unsupported_terminal_opacity(self) -> None:
        config_source = Path("src/mecely/config.py").read_text()
        example = Path("config.example.toml").read_text()
        self.assertNotIn("background_opacity", config_source)
        self.assertNotIn("background_opacity", example)

    def test_example_declares_every_palette_color(self) -> None:
        example = tomllib.loads(Path("config.example.toml").read_text())
        declared = set(example["ui"]["palette"])
        expected = {item.name for item in fields(Palette)}
        self.assertEqual(declared, expected)

    def test_rejects_malformed_palette_color(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('[ui.palette]\nbackground = "not-a-color"\n')
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_accepts_palette_color_with_alpha_channel(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('[ui.palette]\nbackground = "#0b1020cc"\n')
            config, _ = load_config(path)
        self.assertEqual(config.ui.palette.background, "#0b1020cc")

    def test_loads_palette_storage_and_web_defaults(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                """
[ui]
show_clock = false
[ui.palette]
background = "#000000"
[storage]
autosave = false
[web]
host = "127.0.0.1"
port = 9000
"""
            )
            config, resolved = load_config(path)
        self.assertEqual(resolved, path)
        self.assertFalse(config.ui.show_clock)
        self.assertEqual(config.ui.palette.background, "#000000")
        self.assertFalse(config.storage.autosave)
        self.assertEqual(config.web.port, 9000)

    def test_rejects_unknown_configuration(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("[ui]\nunknown = true\n")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_cases_file_defaults_to_none(self) -> None:
        with TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.toml"
            config, _ = load_config(missing)
        self.assertIsNone(config.cases.file)

    def test_loads_cases_file_from_config(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('[cases]\nfile = "/some/cases/cases_full.json"\n')
            config, _ = load_config(path)
        self.assertEqual(config.cases.file, "/some/cases/cases_full.json")

    def test_rejects_unknown_cases_option(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("[cases]\nunknown = true\n")
            with self.assertRaises(ConfigError):
                load_config(path)


class EvaluationTests(unittest.TestCase):
    def test_render_tree_shows_operation_and_result(self) -> None:
        tree = IssueTree.new("Case")
        revenue = tree.add_child(tree.root.id, "Receita")
        revenue.value = 100
        cost = tree.add_child(tree.root.id, "Custo")
        cost.operation = "-"
        cost.value = 40
        rendered = render_tree(tree)
        self.assertIn("Receita = 100", rendered)
        self.assertIn("[-] Custo = 40", rendered)

    def test_render_tree_flags_a_non_first_sibling_missing_its_operation(self) -> None:
        tree = IssueTree.new("Case")
        first = tree.add_child(tree.root.id, "Receita")
        first.value = 100
        second = tree.add_child(tree.root.id, "Custo")
        second.value = 40  # operation left unset on purpose
        rendered = render_tree(tree)
        self.assertIn("- Receita = 100", rendered)  # first child: no marker needed
        self.assertIn("[?] Custo", rendered)

    def test_render_tree_does_not_flag_a_purely_qualitative_branch(self) -> None:
        tree = IssueTree.new("Case")
        tree.add_child(tree.root.id, "Fator A")
        tree.add_child(tree.root.id, "Fator B")  # no value, no operation, on purpose
        rendered = render_tree(tree)
        self.assertNotIn("[?]", rendered)

    def test_build_prompt_includes_rubric_prompt_and_notes(self) -> None:
        tree = IssueTree.new("Case", prompt="Nosso cliente é uma rede de farmácias...")
        tree.add_note("user", "Qual a taxa de churn mensal?")
        tree.add_note("ai", "5% ao mês.")
        prompt = build_prompt(tree)
        self.assertIn(RUBRIC, prompt)
        self.assertIn("Nosso cliente é uma rede de farmácias...", prompt)
        self.assertIn("[user] Qual a taxa de churn mensal?", prompt)
        self.assertIn("[ai] 5% ao mês.", prompt)
        self.assertIn(tree.root.text, prompt)

    def test_build_prompt_omits_empty_sections(self) -> None:
        tree = IssueTree.new("Case sem prompt nem notas")
        prompt = build_prompt(tree)
        self.assertNotIn("Enunciado do case", prompt)
        self.assertNotIn("Anotações e diálogo", prompt)

    def test_note_reply_prompt_flags_most_recent_note(self) -> None:
        tree = IssueTree.new("Case")
        tree.add_note("user", "Primeira pergunta")
        tree.add_note("ai", "Primeira resposta")
        tree.add_note("user", "Segunda pergunta, mais recente")
        prompt = build_note_reply_prompt(tree)
        self.assertIn("entrevistador", prompt)
        self.assertIn("[user] Segunda pergunta, mais recente", prompt)
        self.assertIn("[ai] Primeira resposta", prompt)
        self.assertIn(tree.root.text, prompt)

    def test_note_reply_prompt_switches_to_strict_fidelity_with_case_source(self) -> None:
        tree = IssueTree.new("Case", case_source="Texto integral do case sourced, com dados reais.")
        tree.add_note("user", "Qual o tamanho do mercado?")
        prompt = build_note_reply_prompt(tree)
        self.assertIn(STRICT_NOTE_REPLY_INSTRUCTIONS, prompt)
        self.assertIn("Texto integral do case sourced, com dados reais.", prompt)
        self.assertNotIn("Fornecer um valor específico e plausível", prompt)

    def test_note_reply_prompt_stays_permissive_without_case_source(self) -> None:
        tree = IssueTree.new("Case", prompt="Enunciado curto")
        prompt = build_note_reply_prompt(tree)
        self.assertNotIn(STRICT_NOTE_REPLY_INSTRUCTIONS, prompt)
        self.assertIn("Fornecer um valor específico e plausível", prompt)

    def test_build_prompt_prefers_case_source_over_short_prompt(self) -> None:
        tree = IssueTree.new(
            "Case",
            prompt="Resumo curto",
            case_source="Texto integral do case sourced.",
        )
        prompt = build_prompt(tree)
        self.assertIn("Texto integral do case sourced.", prompt)
        self.assertNotIn("Resumo curto", prompt)


class CalculatorTests(unittest.TestCase):
    def test_arithmetic_percentages_and_suffixes(self) -> None:
        self.assertEqual(evaluate("215m * 5% * 120"), 1_290_000_000)

    def test_rejects_unsafe_expressions(self) -> None:
        with self.assertRaises(CalculationError):
            evaluate("__import__('os').system('echo unsafe')")


class NumericTreeTests(unittest.TestCase):
    def test_profit_estimation_rolls_up_from_leaves(self) -> None:
        tree = IssueTree.new("Profit")
        tree.root.text = "Profit"
        revenue = tree.add_child(tree.root.id, "Revenue")
        cost = tree.add_child(tree.root.id, "Cost")
        cost.operation = "-"
        units = tree.add_child(revenue.id, "Units sold")
        price = tree.add_child(revenue.id, "Price per unit")
        price.operation = "*"
        unit_cost = tree.add_child(cost.id, "Cost per unit")
        cost_units = tree.add_child(cost.id, "Units sold")
        cost_units.operation = "*"
        units.value, price.value = 1_000, 50
        unit_cost.value, cost_units.value = 30, 1_000
        self.assertEqual(revenue.result(), 50_000)
        self.assertEqual(cost.result(), 30_000)
        self.assertEqual(tree.root.result(), 20_000)

    def test_incomplete_branch_has_no_result(self) -> None:
        tree = IssueTree.new()
        first = tree.add_child(tree.root.id, "Part A")
        second = tree.add_child(tree.root.id, "Part B")
        first.value, second.value = 1, 2
        self.assertIsNone(tree.root.result())

    def test_mixed_sibling_operations_use_algebraic_precedence(self) -> None:
        tree = IssueTree.new()
        a = tree.add_child(tree.root.id, "A")
        b = tree.add_child(tree.root.id, "B")
        c = tree.add_child(tree.root.id, "C")
        a.value, b.value, c.value = 10, 2, 3
        b.operation, c.operation = "+", "*"
        self.assertEqual(tree.root.result(), 16)

    def test_migrates_legacy_parent_operator(self) -> None:
        tree = IssueTree.from_dict({
            "title": "Legacy",
            "root": {
                "id": "root",
                "text": "Revenue",
                "operator": "*",
                "children": [
                    {"id": "a", "text": "A", "value": 2},
                    {"id": "b", "text": "B", "value": 3},
                ],
            },
        })
        self.assertEqual(tree.root.children[1].operation, "*")
        self.assertEqual(tree.root.result(), 6)

    def test_migrates_files_saved_under_the_old_relation_field_name(self) -> None:
        tree = IssueTree.from_dict({
            "title": "Old field name",
            "root": {
                "id": "root",
                "text": "Revenue",
                "children": [
                    {"id": "a", "text": "A", "value": 2},
                    {"id": "b", "text": "B", "value": 3, "relation": "*"},
                ],
            },
        })
        self.assertEqual(tree.root.children[1].operation, "*")
        self.assertEqual(tree.root.result(), 6)


class CaseLibraryTests(unittest.TestCase):
    def _write_library(self, path: Path, cases: list[dict]) -> None:
        path.write_text(json.dumps(cases), encoding="utf-8")

    def test_load_library_parses_every_case(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cases_full.json"
            self._write_library(
                path,
                [
                    {
                        "id": "book-01",
                        "book": "Some Casebook",
                        "title": "Widget Co.",
                        "type": "Profitability",
                        "difficulty": "Medium",
                        "texto_completo": "Enunciado e solução completos.",
                    }
                ],
            )
            cases = load_library(path)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].id, "book-01")
        self.assertEqual(cases[0].title, "Widget Co.")
        self.assertIsNone(cases[0].enunciado)

    def test_load_library_parses_enunciado_when_present(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cases_full.json"
            self._write_library(
                path,
                [
                    {
                        "id": "book-01",
                        "book": "Some Casebook",
                        "title": "Widget Co.",
                        "type": None,
                        "difficulty": None,
                        "texto_completo": "Enunciado e solução completos.",
                        "enunciado": "Enunciado limpo, sem a solução.",
                    }
                ],
            )
            cases = load_library(path)
        self.assertEqual(cases[0].enunciado, "Enunciado limpo, sem a solução.")

    def test_load_library_joins_a_list_shaped_type_field(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cases_full.json"
            self._write_library(
                path,
                [
                    {
                        "id": "book-01",
                        "book": "Some Casebook",
                        "title": "Widget Co.",
                        "type": ["Estimativa de mercado", "Entrada em mercado"],
                        "difficulty": "Médio",
                        "texto_completo": "Enunciado e solução completos.",
                    }
                ],
            )
            cases = load_library(path)
        self.assertEqual(cases[0].type, "Estimativa de mercado, Entrada em mercado")

    def test_load_library_raises_when_file_is_missing(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(CaseLibraryError):
                load_library(Path(directory) / "cases_full.json")

    def test_full_text_appends_recovered_exhibit_when_present(self) -> None:
        with_exhibit = Case(
            id="a",
            book="Book",
            title="Case A",
            type=None,
            difficulty=None,
            texto_completo="Corpo do case.",
            exhibit_recovered="Dados do gráfico recuperados do PDF.",
        )
        without_exhibit = Case(
            id="b", book="Book", title="Case B", type=None, difficulty=None, texto_completo="Corpo do case."
        )
        self.assertIn("Dados do gráfico recuperados do PDF.", with_exhibit.full_text())
        self.assertIn("Corpo do case.", with_exhibit.full_text())
        self.assertEqual(without_exhibit.full_text(), "Corpo do case.")

    def test_filter_cases_matches_title_type_and_difficulty_case_insensitively(self) -> None:
        cases = [
            Case(id="a", book="Book", title="Widget Co.", type="Profitability", difficulty="Medium", texto_completo=""),
            Case(id="b", book="Book", title="Gizmo Inc.", type="Market Sizing", difficulty="Easy", texto_completo=""),
        ]
        self.assertEqual(filter_cases(cases, "widget"), [cases[0]])
        self.assertEqual(filter_cases(cases, "EASY"), [cases[1]])
        self.assertEqual(filter_cases(cases, ""), cases)
        self.assertEqual(filter_cases(cases, "nonexistent"), [])

    def test_pick_random_returns_none_for_empty_list(self) -> None:
        self.assertIsNone(pick_random([]))

    def test_pick_random_only_returns_cases_from_the_given_list(self) -> None:
        cases = [
            Case(id="a", book="Book", title="A", type=None, difficulty=None, texto_completo=""),
            Case(id="b", book="Book", title="B", type=None, difficulty=None, texto_completo=""),
        ]
        for _ in range(10):
            self.assertIn(pick_random(cases), cases)


if __name__ == "__main__":
    unittest.main()
