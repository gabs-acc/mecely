import ast
import tomllib
import unittest
from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mecely.calculator import CalculationError, evaluate
from mecely.cli import build_app_command, build_parser, find_available_port, resolve_file
from mecely.config import ConfigError, Palette, load_config
from mecely.evaluation import RUBRIC, build_note_reply_prompt, build_prompt, render_tree
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
        child.relation = "*"
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
        self.assertIsNone(copies[0].relation)

    def test_deleting_first_child_clears_new_first_relation(self) -> None:
        tree = IssueTree.new()
        first = tree.add_child(tree.root.id, "A")
        second = tree.add_child(tree.root.id, "B")
        second.relation = "-"
        tree.delete(first.id)
        self.assertIsNone(second.relation)


class ApplicationSourceTests(unittest.TestCase):
    def test_subtitle_describes_general_use(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        self.assertIn('SUB_TITLE = "Vim-first TUI for issue tree modeling"', app_source)
        self.assertNotIn("structured reasoning for interviews", app_source)

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
            'Binding("r", "relation"',
            'Binding("c", "note"',
            'Binding("N", "view_notes"',
            'Binding("ctrl+a", "evaluate"',
            'Binding("question_mark", "help"',
        ):
            self.assertIn(binding, tree_widget)

    def test_evaluation_screen_supports_copy_shortcut(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        evaluation_screen = app_source.split("class EvaluationScreen", 1)[1].split("class NotesScreen", 1)[0]
        self.assertIn('Binding("y", "copy"', evaluation_screen)
        self.assertIn("self.app.copy_to_clipboard(self.evaluation_text)", evaluation_screen)

    def test_scrollable_modal_screens_focus_their_scroll_container(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        for screen_class, next_class in (
            ("HelpScreen", "EvaluationScreen"),
            ("EvaluationScreen", "NotesScreen"),
            ("NotesScreen", "class MecelyApp"),
        ):
            screen_source = app_source.split(f"class {screen_class}", 1)[1].split(next_class, 1)[0]
            self.assertIn(
                "self.query_one(VerticalScroll).focus()",
                screen_source,
                f"{screen_class} should focus its VerticalScroll on mount so keyboard scrolling works",
            )

    def test_finish_note_backgrounds_ai_reply_as_a_worker(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        finish_note = app_source.split("def finish_note", 1)[1].split("async def reply_to_note", 1)[0]
        self.assertIn("self.reply_to_note()", finish_note)
        decorator_section, reply_to_note = app_source.split("async def reply_to_note", 1)
        reply_to_note = reply_to_note.split("def action_view_notes", 1)[0]
        self.assertTrue(decorator_section.rstrip().endswith("@work"))
        notify_index = reply_to_note.index('self.notify("Aguardando resposta da IA...")')
        call_index = reply_to_note.index("await self._call_claude(build_note_reply_prompt")
        self.assertLess(notify_index, call_index)

    def test_action_evaluate_runs_as_a_worker(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        # rsplit: "def action_evaluate" also matches the IssueTreeList
        # delegate earlier in the file; the real implementation is the last one.
        before, action_evaluate = app_source.rsplit("async def action_evaluate", 1)
        self.assertTrue(before.rstrip().endswith("@work"))
        notify_index = action_evaluate.index('self.notify("Avaliando com IA...")')
        call_index = action_evaluate.index("await self._call_claude(build_prompt")
        self.assertLess(notify_index, call_index)

    def test_compact_shortcut_bar_keeps_contextual_groups(self) -> None:
        app_source = Path("src/mecely/app.py").read_text()
        for group in (
            "? ajuda", "j/k mover", "h/l nível", "a filho", "o irmão",
            "i editar", "x excluir", "n/= valor", "r relação",
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
            "a ou Tab", "o ou Enter", "n ou =", "Ctrl+D / Ctrl+U",
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



class EvaluationTests(unittest.TestCase):
    def test_render_tree_shows_relation_and_result(self) -> None:
        tree = IssueTree.new("Case")
        revenue = tree.add_child(tree.root.id, "Receita")
        revenue.value = 100
        cost = tree.add_child(tree.root.id, "Custo")
        cost.relation = "-"
        cost.value = 40
        rendered = render_tree(tree)
        self.assertIn("Receita = 100", rendered)
        self.assertIn("[-] Custo = 40", rendered)

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
        cost.relation = "-"
        units = tree.add_child(revenue.id, "Units sold")
        price = tree.add_child(revenue.id, "Price per unit")
        price.relation = "*"
        unit_cost = tree.add_child(cost.id, "Cost per unit")
        cost_units = tree.add_child(cost.id, "Units sold")
        cost_units.relation = "*"
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
        b.relation, c.relation = "+", "*"
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
        self.assertEqual(tree.root.children[1].relation, "*")
        self.assertEqual(tree.root.result(), 6)


if __name__ == "__main__":
    unittest.main()
