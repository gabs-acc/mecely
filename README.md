# Mecely

[![Tests](https://github.com/gabs-acc/mecely/actions/workflows/tests.yml/badge.svg)](https://github.com/gabs-acc/mecely/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

A Vim-first TUI for modeling issue trees and numerical estimations without
leaving the terminal.

## Features

- create, edit, delete, and collapse branches;
- navigation and visual selection with Vim-inspired shortcuts;
- undo, redo, copy, and paste of subtrees;
- algebraic operations between sibling nodes and automatic estimate rollup;
- explicit JSON documents, with manual saving by default;
- runs in the terminal or in the browser.

## Demo

[![asciicast](https://asciinema.org/a/1263261.svg)](https://asciinema.org/a/1263261)

## Run it

Requires Python 3.11 or newer.

```bash
git clone https://github.com/gabs-acc/mecely.git
cd mecely
python -m venv .venv
source .venv/bin/activate
pip install -e .
mecely
```

To check the installation before opening the interface:

```bash
python -c "import mecely; print(mecely.__version__)"
```

Without a path, Mecely opens a new buffer and writes nothing automatically.
Use `Ctrl+S` to choose a JSON name. With a positional path, the file is
opened if it exists or created on first save.

## Command line

```text
mecely [file] [options]
```

Examples:

```bash
# Open a new buffer, still without a file
mecely

# Start a clean tree associated with a file
mecely estimate.json --new --title "Market estimate"

# Work on a specific file
mecely cases/profitability.json

# Explicitly enable autosave or prevent any writes
mecely example.json --autosave
mecely interview.json --read-only

# Log diagnostics to mecely.log (use -vv for debug level)
mecely -v

mecely --help
mecely --version
```

### Browser

Install the optional support and serve the app locally:

```bash
pip install -e '.[web]'
mecely --web
```

Open `http://localhost:8000`. You can also choose the address and port:

```bash
mecely cases/profitability.json --web --host localhost --port 8080
```

If the requested port is busy, Mecely automatically looks for the next free
port among the following 20 and shows the chosen address.

`--public-url` sets the external URL when the server is behind a proxy. The
server stays local by default; don't use `--host 0.0.0.0` on an untrusted
network without authentication and appropriate firewall rules.

## Configuration

Preferences live outside the application, at:

```text
~/.config/mecely/config.toml
```

The path respects `XDG_CONFIG_HOME`. A different file can be selected with
`mecely --config profile.toml`. Use
[`config.example.toml`](config.example.toml) as a base — it ships the
complete default color palette, ready to copy and edit. General structure:

```toml
[ui]
show_clock = false

[ui.palette]
background = "#0b1020"
text = "#edf2f7"
# ... remaining colors in config.example.toml

[storage]
autosave = false

[web]
host = "localhost"
port = 8000
# public_url = "https://mecely.example.com"
```

There's no preferences menu or command palette inside the TUI. Explicit CLI
options, like `--port` and `--autosave`, take precedence over the file only
for that run.

Textual renders true-color backgrounds and doesn't preserve the transparency
configured in the terminal emulator. Colors with alpha are composited against
the app's internal background, so they don't offer real window transparency.

## Vim shortcuts

| Key | Action |
|---|---|
| `J` / `K` | select next node / previous node |
| `H` | collapse branch or select the parent |
| `L` | expand branch or select the first child |
| `A` | create child node |
| `O` | create sibling node |
| `I` | edit node |
| `X` | delete node |
| `N` or `=` | set a leaf's value |
| `R` | set relation to the previous sibling |
| `U` | undo change |
| `Ctrl+R` | redo change |
| `V` | start or end visual selection |
| `Y` | copy the selection or subtree |
| `P` | paste after the current node |
| `g` / `G` | first / last node |
| `Ctrl+D` / `Ctrl+U` | forward / back five lines |
| `Ctrl+S` | save |
| `Q` | quit |
| `?` | open or close help |

Arrows, `Tab`, `Enter`, `E`, and `Delete` remain available as alternatives.
Inside the editor, `Enter` confirms and `Esc` cancels.

In visual mode, use `J/K` to extend the selection. `Y` copies the top-level
subtrees of the selection and `X` deletes them. `Esc` returns to normal mode.

## Numeric estimations in the tree

On a leaf, press `N` (or `=`) to enter the value. On each child from the
second onward, press `R` to set how it relates to the previous sibling
(`+`, `-`, `*`, or `/`). The first child starts the expression, and the
hierarchy determines the groupings.

```text
Profit = 20k
├─ Revenue = 50k
│  ├─ Units sold = 1k
│  └─ [*] Price per unit = 50
└─ [-] Cost = 30k
   ├─ Cost per unit = 30
   └─ [*] Units sold = 1k
```

Values accept expressions, percentages, and the `k`, `m`, and `b`
abbreviations. The numeric tree is saved in the same JSON as the case
structure.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Contributing

Contributions are welcome.

- Run the test suite before opening a PR:
  `PYTHONPATH=src python -m unittest discover -s tests -v`.
- Keep the existing code style and avoid adding dependencies without a clear
  need.
- Describe the problem solved or the motivation for the change in the PR.

For bugs or suggestions, open an issue.

## Usage principle

Mecely organizes and makes a candidate's reasoning visible. It isn't
designed to provide hidden answers or assistance incompatible with a hiring
process's rules.

## License

MIT.
