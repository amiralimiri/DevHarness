"""Terminal presentation layer.

Knows nothing about LLMs, providers or tools - it only receives plain strings
and dicts and decides how they look.
"""

import json
import re
from contextlib import contextmanager

import arabic_reshaper
from bidi.algorithm import get_display
from rich.console import Console, Group
from rich.json import JSON
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from . import prompt
from .todos import MARKS

ACCENT = "#7aa2f7"
USER = "#9ece6a"
TOOL = "#e0af68"
MUTED = "#565f89"

MAX_TOOL_OUTPUT_LINES = 12

TODO_STYLES = {
    "done": f"{MUTED} strike",
    "in_progress": f"bold {ACCENT}",
    "pending": MUTED,
}

_RTL_PATTERN = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
)

_reshaper = arabic_reshaper.ArabicReshaper(
    configuration={
        "delete_harakat": False,
        "support_ligatures": True,
    }
)


def _has_rtl(text: str) -> bool:
    return bool(_RTL_PATTERN.search(text))


def _rtl_line(line: str) -> str:
    """Reshape and reorder a single line if it contains RTL characters."""
    if not line or not _has_rtl(line):
        return line
    return str(get_display(_reshaper.reshape(line)))


def _rtl(text: str) -> str:
    """Format multiline text for proper bidirectional terminal display."""
    if not text or not _has_rtl(text):
        return text
    return "\n".join(_rtl_line(line) for line in text.splitlines())


def _rtl_markdown(md_text: str) -> str:
    """Format RTL text inside Markdown while preserving code blocks and structural prefixes."""
    if not md_text or not _has_rtl(md_text):
        return md_text

    lines = md_text.splitlines()
    out = []
    in_code_block = False

    # Preserve Markdown line prefixes (e.g., #, *, -, 1., >) at the start of lines
    md_prefix_re = re.compile(r"^(\s*(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+|>\s+)*)(.*)$")

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            out.append(line)
            continue

        if in_code_block:
            out.append(_rtl_line(line))
            continue

        if not _has_rtl(line):
            out.append(line)
            continue

        match = md_prefix_re.match(line)
        if match:
            prefix, content = match.groups()
            out.append(f"{prefix}{_rtl_line(content)}")
        else:
            out.append(_rtl_line(line))

    return "\n".join(out)


class UI:
    def __init__(self):
        self.console = Console()
        self._totals = {}

    # ---------------------------------------------------------------- input

    def banner(self, sandbox_name="none"):
        self.console.print()
        self.console.print(
            Rule(Text(" coding agent ", style=f"bold {ACCENT}"), style=MUTED)
        )
        self.console.print(
            Padding(
                Text(
                    f"sandbox: {sandbox_name}  ·  alt-enter for a newline  ·  ctrl-d to exit",
                    style=MUTED,
                ),
                (0, 0, 0, 2),
            )
        )

    def clear(self):
        self.console.clear()

    def resumed(self, messages, label="resumed"):
        turns = sum(1 for m in messages if m["role"] == "user")
        self.console.print(
            Padding(
                Text(f"{label} · {len(messages)} messages · {turns} turns", style=MUTED),
                (0, 0, 0, 2),
            )
        )

    def replay(self, messages):
        """Redraw a loaded transcript so the screen matches the history."""
        results = {m["tool_call_id"]: m["content"] for m in messages if m["role"] == "tool"}
        for message in messages:
            if message["role"] == "user":
                self.user(message["content"])
            elif message["role"] == "assistant":
                if message.get("content"):
                    self.agent(message["content"])
                for call in message.get("tool_calls") or []:
                    self.tool(
                        call["function"]["name"],
                        json.loads(call["function"]["arguments"]),
                        results.get(call["id"], ""),
                    )

    def approve(self, reason):
        self.console.print(Padding(Text(_rtl(reason), style=f"bold {TOOL}"), (1, 0, 0, 2)))
        try:
            answer = prompt.read("  allow? (y/n)> ").strip()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer.lower().startswith("y")

    def note(self, text):
        self.console.print(Padding(Text(_rtl(text), style=MUTED), (1, 0, 0, 2)))

    def pick(self, title, rows):
        """Numbered list; returns the chosen index or None."""
        self.console.print(Padding(Text(_rtl(title), style=f"bold {ACCENT}"), (1, 0, 0, 2)))
        for i, row in enumerate(rows):
            self.console.print(Padding(Text(f"{i:>3}  {_rtl(str(row))}", style=MUTED), (0, 0, 0, 2)))
        try:
            answer = prompt.read("\n  number> ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        return int(answer) if answer.isdigit() and int(answer) < len(rows) else None

    def ask(self):
        self.console.print()
        try:
            return prompt.read("> ").strip()
        except (EOFError, KeyboardInterrupt):
            self.console.print()
            return ""

    # --------------------------------------------------------------- output

    def user(self, text):
        self.console.print(
            Padding(Text(_rtl(text.strip()), style=f"bold {USER}"), (1, 0, 0, 2))
        )

    def agent(self, text):
        self.console.print(
            Padding(
                Group(
                    Text("agent", style=f"bold {ACCENT}"),
                    Padding(Markdown(_rtl_markdown(text.strip())), (1, 0, 0, 0)),
                ),
                (1, 2, 0, 2),
            )
        )

    def tool(self, name, args, result, nested=False):
        if name == "write_todos" and args.get("todos"):
            return self.todos(args["todos"])

        header = Text.assemble(
            (f"{name} ", f"bold {TOOL}"),
            (_rtl(self._format_args(args)), MUTED),
        )
        self.console.print(
            Padding(
                Panel(
                    Group(header, Rule(style=MUTED), self._format_result(result)),
                    border_style=MUTED,
                    padding=(0, 1),
                ),
                (1, 2, 0, 6 if nested else 2),
            )
        )

    def subagent(self, description):
        """Shown to you, never to the main agent - it only gets the report."""
        self.console.print(
            Padding(
                Panel(
                    Text(_rtl(description.strip()), style=MUTED),
                    title=Text("subagent · own context", style=f"bold {ACCENT}"),
                    title_align="left",
                    border_style=ACCENT,
                    padding=(0, 1),
                ),
                (1, 2, 0, 4),
            )
        )

    def injection(self, text):
        self.console.print(
            Padding(
                Panel(
                    Text(_rtl(text.strip()), style=MUTED),
                    title=Text("late injection", style=f"italic {MUTED}"),
                    title_align="left",
                    border_style=MUTED,
                    padding=(0, 1),
                ),
                (1, 2, 0, 2),
            )
        )

    def debug(self, data):
        raw_json = json.dumps(data, indent=2, ensure_ascii=False)
        self.console.print(
            Padding(
                Panel(
                    JSON(_rtl(raw_json)),
                    title=Text("raw response", style=f"italic {MUTED}"),
                    title_align="left",
                    border_style=TOOL,
                    padding=(0, 1),
                ),
                (1, 2, 0, 2),
            )
        )

    @contextmanager
    def working(self, label="thinking"):
        with self.console.status(
            Text(_rtl(label), style=MUTED), spinner="dots", spinner_style=ACCENT
        ):
            yield

    # ---------------------------------------------------------------- usage

    def usage(self, stats):
        for key, value in stats.items():
            self._totals[key] = self._totals.get(key, 0) + (value or 0)

        parts = " · ".join(
            f"{value:,} {key.replace('_tokens', '')}"
            for key, value in stats.items()
            if value
        )
        self.console.print(Padding(Text(parts, style=MUTED), (1, 0, 0, 2)))

    def summary(self):
        if not self._totals:
            return

        table = Table.grid(padding=(0, 2))
        table.add_column(style=MUTED)
        table.add_column(style=f"bold {ACCENT}", justify="right")
        for key, value in self._totals.items():
            table.add_row(key.replace("_", " "), f"{value:,}")

        self.console.print(Padding(table, (1, 2)))
        self.console.print(Rule(style=MUTED))
        self.console.print()

    def compacted(self, before, messages):
        summary = next(
            (m["content"] for m in messages if "<summary>" in (m.get("content") or "")),
            "",
        )
        clean_summary = summary.replace("<summary>", "").replace("</summary>", "")
        self.console.print(
            Padding(
                Panel(
                    Markdown(_rtl_markdown(clean_summary)),
                    title=Text(
                        f"compacted · {before} → {len(messages)} messages",
                        style=f"bold {TOOL}",
                    ),
                    title_align="left",
                    border_style=TOOL,
                    padding=(0, 1),
                ),
                (1, 2, 0, 2),
            )
        )

    def todos(self, todos):
        """The plan, as a checklist. The raw tool output is never worth showing."""
        done = sum(1 for t in todos if t["status"] == "done")

        rows = Table.grid(padding=(0, 1))
        rows.add_column(no_wrap=True)
        rows.add_column(overflow="fold")
        for todo in todos:
            status = todo["status"]
            style = TODO_STYLES[status]
            rows.add_row(
                Text(MARKS[status], style=style),
                Text(_rtl(todo["content"]), style=style),
            )

        self.console.print(
            Padding(
                Panel(
                    rows,
                    title=Text(f"todos {done}/{len(todos)}", style=f"bold {TOOL}"),
                    title_align="left",
                    border_style=MUTED,
                    padding=(0, 1),
                ),
                (1, 2, 0, 2),
            )
        )

    # -------------------------------------------------------------- helpers

    def _format_args(self, args):
        if len(args) == 1:
            return str(next(iter(args.values())))
        return json.dumps(args, ensure_ascii=False)

    def _format_result(self, result):
        lines = result.strip().splitlines() or ["(no output)"]
        shown = [_rtl_line(line) for line in lines[:MAX_TOOL_OUTPUT_LINES]]
        body = Text("\n".join(shown), style=MUTED)
        hidden = len(lines) - len(shown)
        if hidden > 0:
            body.append(f"\n… {hidden} more lines", style=f"italic {TOOL}")
        return body


ui = UI()