# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal, Optional
from copy import deepcopy
import os

from dracon.keypath import KeyPath, KeyPathToken, MAPPING_KEY

if __name__ != '____always_import__':
    from dracon.diagnostics import SourceContext


def keypath_to_dotted(kp: KeyPath) -> Optional[str]:
    """Convert a KeyPath to dotted notation (e.g. 'db.port'), skipping MAPPING_KEY paths."""
    parts = kp.parts
    # fast check: MAPPING_KEY only appears at parts[-2] in valid keypaths
    if len(parts) >= 2 and parts[-2] is MAPPING_KEY:
        return None
    result = []
    for p in parts:
        if p.__class__ is not str:  # skip KeyPathToken (ROOT, etc.)
            continue
        result.append(p)
    return '.'.join(result) if result else None


ViaKind = Literal[
    "definition", "file_layer", "include", "merge",
    "if_branch", "each_expansion", "cli_override",
    "set_default", "define", "context_variable",
]


@dataclass(slots=True)
class TraceEntry:
    """One step in a value's provenance chain."""
    value: Any
    source: Optional[SourceContext]  # file/line/column
    via: ViaKind
    detail: str = ""                 # human-readable context
    replaced: Optional[TraceEntry] = None

    def __repr__(self):
        src = str(self.source) if self.source else "?"
        return f"TraceEntry({self.via}: {self.value!r} <- {src})"


def _format_entry(entry: TraceEntry, indent: int = 4) -> str:
    """Format a single trace entry as a readable line."""
    pad = " " * indent
    src = str(entry.source) if entry.source else "<unknown>"
    detail = f" ({entry.detail})" if entry.detail else ""
    line = f"{pad}= {entry.value!r}  <- {src}{detail}"
    if entry.replaced:
        line += f"  (was {entry.replaced.value!r})"
    return line


class CompositionTrace:
    """Opt-in trace store. Accumulates provenance entries keyed by dotted path."""
    __slots__ = ('entries',)

    def __init__(self):
        self.entries: dict[str, list[TraceEntry]] = {}

    def record(self, path: str, entry: TraceEntry):
        """Record a trace entry for the given dotted path. Auto-links replaced."""
        history = self.entries.get(path)
        if history:
            entry.replaced = history[-1]
        else:
            history = []
            self.entries[path] = history
        history.append(entry)

    def get(self, path: str) -> list[TraceEntry]:
        return self.entries.get(path, [])

    def all(self) -> dict[str, list[TraceEntry]]:
        return dict(self.entries)

    def merge_from(self, other: CompositionTrace, prefix: str = ""):
        """Merge entries from another trace, optionally prefixing paths.
        Preserves the original replaced chains from the source trace."""
        for path, entries in other.entries.items():
            full_path = f"{prefix}.{path}" if prefix else path
            existing = self.entries.get(full_path, [])
            # link first imported entry to last existing entry
            if entries:
                from copy import copy
                imported = [copy(e) for e in entries]
                if existing:
                    imported[0].replaced = existing[-1]
                self.entries[full_path] = existing + imported

    def format_path(self, path: str) -> str:
        """Pretty-print the trace for a single path."""
        entries = self.get(path)
        if not entries:
            return f"# {path}: no trace recorded"
        last = entries[-1]
        lines = [f"# {path} = {last.value!r}"]
        for i, entry in enumerate(entries, 1):
            lines.append(f"#   {i}. {_format_entry(entry, indent=0)}")
        return "\n".join(lines)

    def format_all(self) -> str:
        """Pretty-print the full provenance tree."""
        if not self.entries:
            return "# (no trace entries)"
        lines = []
        for path in sorted(self.entries):
            entries = self.entries[path]
            last = entries[-1]
            src = str(last.source) if last.source else "?"
            detail = f" ({last.detail})" if last.detail else ""
            summary = f"# {path} = {last.value!r}  <- {src}{detail}"
            if last.replaced:
                summary += f"  (was {last.replaced.value!r})"
            lines.append(summary)
            if len(entries) > 1:
                for i, entry in enumerate(entries, 1):
                    lines.append(_format_entry(entry))
        return "\n".join(lines)

    def format_path_rich(self, path: str):
        """Rich-formatted trace for a single path. Returns a Panel."""
        from rich.panel import Panel
        from rich.text import Text
        from rich.box import ROUNDED
        entries = self.get(path)
        t = Text()
        if not entries:
            t.append(f"{path}: no trace recorded", style="dim")
            return Panel(t, box=ROUNDED, border_style="dim", expand=False, padding=(1, 2))

        last = entries[-1]
        t.append(path, style="bold #5DE6B6")
        t.append(" = ", style="dim")
        t.append(repr(last.value), style="bold #F3CD73")
        t.append("\n\n")

        for i, entry in enumerate(entries, 1):
            t.append(f"  {i}. ", style="dim")
            t.append(repr(entry.value), style="#F3CD73")
            t.append("  ← ", style="dim")
            src = str(entry.source) if entry.source else "?"
            t.append(src, style="dim")
            t.append("  ")
            t.append(entry.via, style=_via_style(entry.via))
            if entry.detail:
                t.append(f" ({entry.detail})", style="dim")
            if entry.replaced:
                t.append(f"\n     replaces ", style="dim")
                t.append(repr(entry.replaced.value), style="dim")
            t.append("\n")

        title = f"[bold #5DE6B6]Trace: {path}[/]"
        return Panel(t, title=title, box=ROUNDED, border_style="#5DE6B6", expand=False, padding=(1, 2))

    def format_all_rich(self):
        """Rich-formatted full trace. Returns a Panel with table."""
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
        from rich.box import SIMPLE_HEAVY

        if not self.entries:
            return Text("(no trace entries)", style="dim")

        table = Table(box=SIMPLE_HEAVY, show_edge=False, pad_edge=False, expand=False)
        table.add_column("Path", style="#5DE6B6", no_wrap=True)
        table.add_column("Value", style="#F3CD73")
        table.add_column("Source", style="dim")
        table.add_column("Via", no_wrap=True)

        for path in sorted(self.entries):
            entries = self.entries[path]
            last = entries[-1]
            src = str(last.source) if last.source else "?"
            via_text = Text(last.via, style=_via_style(last.via))
            if last.detail:
                via_text.append(f" ({last.detail})", style="dim")
            val_text = Text(repr(last.value))
            if last.replaced:
                val_text.append(f" (was {last.replaced.value!r})", style="dim")
            table.add_row(path, val_text, src, via_text)

        return table

    def __deepcopy__(self, memo):
        new = CompositionTrace()
        new.entries = deepcopy(self.entries, memo)
        return new

    def __repr__(self):
        return f"CompositionTrace({len(self.entries)} paths)"


# ── styling ──────────────────────────────────────────────────────────────────

_VIA_STYLES = {
    "definition": "dim",
    "file_layer": "#F3CD73",
    "include": "#5DE6B6",
    "merge": "#8D5DE9",
    "if_branch": "green",
    "each_expansion": "green",
    "cli_override": "bold #F3CD73",
    "set_default": "dim",
    "define": "dim",
    "context_variable": "italic",
}


def _via_style(via: str) -> str:
    return _VIA_STYLES.get(via, "default")


def trace_enabled_from_env() -> bool:
    return os.environ.get('DRACON_TRACE', '').lower() in ('1', 'true', 'yes')
