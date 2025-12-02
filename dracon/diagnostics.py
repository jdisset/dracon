# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

from dataclasses import dataclass, field
from typing import Any, Optional, Tuple, Type, Sequence
import os

## {{{                    --     Source Context     --


@dataclass(frozen=True)
class SourceLocation:
    file_path: str
    line: int
    column: int = 0
    keypath: Optional[str] = None  # path within the file (e.g. "db.host")

    def __str__(self) -> str:
        base = os.path.basename(self.file_path) if self.file_path else "<unknown>"
        s = f"{base}:{self.line}"
        if self.keypath:
            s += f" ({self.keypath})"
        return s

    @classmethod
    def from_mark(cls, mark, keypath: Optional[str] = None) -> "SourceLocation":
        if mark is None:
            return cls(file_path="<unknown>", line=0, column=0, keypath=keypath)
        return cls(
            file_path=getattr(mark, "name", "<unknown>") or "<unknown>",
            line=getattr(mark, "line", -1) + 1,
            column=getattr(mark, "column", -1) + 1,
            keypath=keypath,
        )


@dataclass(frozen=True)
class SourceContext:
    file_path: str
    line: int
    column: int = 0
    keypath: Optional[str] = None
    include_trace: Tuple[SourceLocation, ...] = field(default_factory=tuple)
    operation_context: Optional[str] = None

    def __str__(self) -> str:
        base = os.path.basename(self.file_path) if self.file_path else "<unknown>"
        s = f"{base}:{self.line}"
        if self.keypath:
            s += f" ({self.keypath})"
        return s

    @classmethod
    def from_mark(cls, mark, include_trace: Tuple[SourceLocation, ...] = (), keypath: Optional[str] = None) -> "SourceContext":
        loc = SourceLocation.from_mark(mark, keypath=keypath)
        return cls(
            file_path=loc.file_path,
            line=loc.line,
            column=loc.column,
            keypath=keypath,
            include_trace=include_trace,
        )

    @classmethod
    def unknown(cls) -> "SourceContext":
        return cls(file_path="<unknown>", line=0, column=0)

    def with_keypath(self, keypath: str) -> "SourceContext":
        return SourceContext(
            file_path=self.file_path, line=self.line, column=self.column,
            keypath=keypath, include_trace=self.include_trace,
            operation_context=self.operation_context,
        )

    def with_operation(self, operation: str) -> "SourceContext":
        return SourceContext(
            file_path=self.file_path, line=self.line, column=self.column,
            keypath=self.keypath, include_trace=self.include_trace,
            operation_context=operation,
        )

    def with_child(self, file_path: str, line: int, column: int = 0, keypath: Optional[str] = None) -> "SourceContext":
        parent_loc = SourceLocation(
            file_path=self.file_path, line=self.line, column=self.column, keypath=self.keypath
        )
        return SourceContext(
            file_path=file_path, line=line, column=column, keypath=keypath,
            include_trace=self.include_trace + (parent_loc,),
        )

    def to_location(self) -> SourceLocation:
        return SourceLocation(file_path=self.file_path, line=self.line, column=self.column, keypath=self.keypath)


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                    --     Exception Hierarchy     --


class DraconError(Exception):
    def __init__(self, message: str, context: Optional[SourceContext] = None, cause: Optional[Exception] = None):
        super().__init__(message)
        self.context = context
        if cause is not None:
            self.__cause__ = cause

    def __str__(self) -> str:
        return self.args[0] if self.args else ""


class CompositionError(DraconError):
    pass


class EvaluationError(DraconError):
    def __init__(self, message: str, context: Optional[SourceContext] = None,
                 cause: Optional[Exception] = None, expression: Optional[str] = None,
                 available_symbols: Optional[dict[str, Any]] = None):
        super().__init__(message, context, cause)
        self.expression = expression
        # store a filtered version of available symbols (exclude internal/large objects)
        self.available_symbols = _filter_symbols_for_display(available_symbols) if available_symbols else None


def _filter_symbols_for_display(symbols: Optional[dict[str, Any]], max_keys: int = 20) -> Optional[dict[str, str]]:
    """Filter symbols dict for error display, keeping only user-relevant keys with type info."""
    if not symbols:
        return None
    result = {}
    for k, v in symbols.items():
        if k.startswith('__') or k.startswith('_'):
            continue
        if callable(v) and not hasattr(v, '__self__'):  # skip standalone functions
            continue
        # format value with type info, truncating large representations
        try:
            type_name = type(v).__name__
            if isinstance(v, (str, int, float, bool, type(None))):
                val_repr = repr(v)
                if len(val_repr) > 50:
                    val_repr = val_repr[:47] + '...'
                result[k] = f"{val_repr} ({type_name})"
            elif isinstance(v, (list, tuple)):
                result[k] = f"{type_name} with {len(v)} items"
            elif isinstance(v, dict):
                result[k] = f"{type_name} with {len(v)} keys"
            else:
                result[k] = f"<{type_name}>"
        except Exception:
            result[k] = f"<{type(v).__name__}>"
        if len(result) >= max_keys:
            result['...'] = f"(and {len(symbols) - max_keys} more)"
            break
    return result if result else None


class SchemaError(DraconError):
    def __init__(self, message: str, context: Optional[SourceContext] = None,
                 cause: Optional[Exception] = None, field_path: Optional[Tuple[str, ...]] = None,
                 expected_type: Optional[Type] = None, actual_value: Any = None):
        super().__init__(message, context, cause)
        self.field_path = field_path
        self.expected_type = expected_type
        self.actual_value = actual_value


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                    --     Error Formatting     --


def _simplify_path(path: str, base_dir: str) -> str:
    """Make path relative to base_dir if it doesn't require too many '../'."""
    if not path or not base_dir or path.startswith('<'):
        return path
    try:
        from pathlib import Path
        p = Path(path)
        b = Path(base_dir)
        if not p.is_absolute() or not b.is_absolute():
            return path
        try:
            rel = p.relative_to(b)
            return str(rel)
        except ValueError:
            # not a subpath, try relative_to common parent
            rel = os.path.relpath(path, base_dir)
            if rel.count('..') <= 1:
                return rel
            return path
    except Exception:
        return path


def _get_base_dir(ctx: SourceContext) -> Optional[str]:
    """Get the base directory from the first file in the include trace."""
    if ctx.include_trace and ctx.include_trace[0].file_path:
        fp = ctx.include_trace[0].file_path
        if not fp.startswith('<'):
            return os.path.dirname(fp)
    if ctx.file_path and not ctx.file_path.startswith('<'):
        return os.path.dirname(ctx.file_path)
    return None


def _format_include_trace(ctx: SourceContext) -> list[str]:
    if not ctx.include_trace:
        return []

    base_dir = _get_base_dir(ctx)
    lines = ["", "Include trace:"]

    for i, loc in enumerate(ctx.include_trace, 1):
        fp = _simplify_path(loc.file_path, base_dir) if base_dir else loc.file_path
        # first entry shows full path as reference
        if i == 1:
            fp = loc.file_path
        kp = f" ({loc.keypath})" if loc.keypath else ""
        lines.append(f"  {i}. {fp}:{loc.line}{kp}")

    fp = _simplify_path(ctx.file_path, base_dir) if base_dir else ctx.file_path
    kp = f" ({ctx.keypath})" if ctx.keypath else ""
    lines.append(f"  {len(ctx.include_trace) + 1}. {fp}:{ctx.line}{kp} <- error")
    return lines


def format_error(error: DraconError, source_lines: Optional[dict[str, Sequence[str]]] = None) -> str:
    lines = [f"Error: {error}"]

    if error.context is not None:
        ctx = error.context
        kp = f" at {ctx.keypath}" if ctx.keypath else ""
        lines.append(f"  in '{ctx.file_path}' line {ctx.line}{kp}")

        if source_lines and ctx.file_path in source_lines:
            file_lines = source_lines[ctx.file_path]
            if 0 < ctx.line <= len(file_lines):
                if ctx.line > 1:
                    lines.append(f"    {ctx.line - 1}: {file_lines[ctx.line - 2]}")
                lines.append(f" -> {ctx.line}: {file_lines[ctx.line - 1]}")
                if ctx.line < len(file_lines):
                    lines.append(f"    {ctx.line + 1}: {file_lines[ctx.line]}")

        if ctx.operation_context:
            lines.append(f"  {ctx.operation_context}")

        lines.extend(_format_include_trace(ctx))

    if isinstance(error, EvaluationError):
        if error.expression:
            lines.append(f"  Expression: {error.expression}")
        if error.available_symbols:
            lines.append("  Available variables:")
            for k, v in error.available_symbols.items():
                lines.append(f"    {k}: {v}")

    if isinstance(error, SchemaError):
        if error.field_path:
            lines.append(f"  Field: {'.'.join(str(p) for p in error.field_path)}")
        if error.expected_type:
            lines.append(f"  Expected: {error.expected_type.__name__}")
        if error.actual_value is not None:
            r = repr(error.actual_value)
            lines.append(f"  Got: {r[:47] + '...' if len(r) > 50 else r}")

    return "\n".join(lines)


def format_error_rich(error: DraconError, source_lines: Optional[dict[str, Sequence[str]]] = None) -> "Panel":
    from rich.panel import Panel
    from rich.text import Text
    from rich.box import ROUNDED

    t = Text()
    t.append(str(error), style="bold red")
    t.append("\n\n")

    if error.context is not None:
        ctx = error.context
        base_dir = _get_base_dir(ctx)
        display_path = ctx.file_path
        if base_dir and ctx.include_trace:
            display_path = _simplify_path(ctx.file_path, base_dir)

        t.append("Location: ", style="bold")
        t.append(display_path, style="cyan")
        t.append(f" line {ctx.line}", style="yellow")
        if ctx.keypath:
            t.append(f" at ", style="dim")
            t.append(ctx.keypath, style="green")
        t.append("\n")

        if source_lines and ctx.file_path in source_lines:
            file_lines = source_lines[ctx.file_path]
            if 0 < ctx.line <= len(file_lines):
                t.append("\n")
                for n in range(max(1, ctx.line - 1), min(len(file_lines), ctx.line + 1) + 1):
                    content = file_lines[n - 1].rstrip()
                    if n == ctx.line:
                        t.append(f"-> {n:4d} | ", style="bold red")
                        t.append(f"{content}\n", style="bold")
                    else:
                        t.append(f"   {n:4d} | ", style="dim")
                        t.append(f"{content}\n", style="dim")
                t.append("\n")

        if ctx.operation_context:
            t.append("Context: ", style="bold")
            t.append(f"{ctx.operation_context}\n", style="italic")

        if ctx.include_trace:
            t.append("\nInclude trace:\n", style="bold cyan")
            for i, loc in enumerate(ctx.include_trace, 1):
                fp = loc.file_path if i == 1 else _simplify_path(loc.file_path, base_dir)
                t.append(f"  {i}. ", style="dim")
                t.append(fp, style="cyan")
                t.append(f":{loc.line}", style="yellow")
                if loc.keypath:
                    t.append(f" ({loc.keypath})", style="green dim")
                t.append("\n")
            t.append(f"  {len(ctx.include_trace) + 1}. ", style="dim")
            t.append(display_path, style="cyan bold")
            t.append(f":{ctx.line}", style="yellow bold")
            if ctx.keypath:
                t.append(f" ({ctx.keypath})", style="green")
            t.append(" <- error\n", style="red bold")

    if isinstance(error, EvaluationError):
        if error.expression:
            t.append("\nExpression: ", style="bold")
            t.append(f"{error.expression}\n", style="magenta")
        if error.available_symbols:
            t.append("\nAvailable variables:\n", style="bold")
            for k, v in error.available_symbols.items():
                t.append(f"  {k}", style="cyan")
                t.append(": ", style="dim")
                t.append(f"{v}\n", style="yellow")

    if isinstance(error, SchemaError):
        t.append("\n")
        if error.field_path:
            t.append("Field: ", style="bold")
            t.append(f"{'.'.join(str(p) for p in error.field_path)}\n", style="cyan")
        if error.expected_type:
            t.append("Expected: ", style="bold")
            t.append(f"{error.expected_type.__name__}\n", style="green")
        if error.actual_value is not None:
            r = repr(error.actual_value)
            t.append("Got: ", style="bold")
            t.append(f"{r[:77] + '...' if len(r) > 80 else r}\n", style="red")

    return Panel(t, title="[bold red]Configuration Error[/]", box=ROUNDED, border_style="red", expand=False, padding=(1, 2))


def print_dracon_error(error: DraconError, source_lines: Optional[dict[str, Sequence[str]]] = None, use_rich: bool = True) -> None:
    import sys
    debug = os.environ.get("DRACON_DEBUG", "").lower() in ("1", "true", "yes")

    if use_rich:
        try:
            from rich.console import Console
            console = Console(stderr=True)
            console.print(format_error_rich(error, source_lines))
            if debug and error.__cause__:
                import traceback
                console.print("\n[dim]Python traceback:[/dim]")
                console.print("".join(traceback.format_exception(type(error.__cause__), error.__cause__, error.__cause__.__traceback__)), style="dim")
            return
        except ImportError:
            pass

    print(format_error(error, source_lines), file=sys.stderr)
    if debug and error.__cause__:
        import traceback
        print("\nPython traceback:", file=sys.stderr)
        traceback.print_exception(type(error.__cause__), error.__cause__, error.__cause__.__traceback__)


def load_source_lines(error: DraconError) -> dict[str, Sequence[str]]:
    """Load source lines from files referenced in the error's context and include trace."""
    result: dict[str, Sequence[str]] = {}
    if error.context is None:
        return result

    ctx = error.context
    files_to_load = set()
    if ctx.file_path and not ctx.file_path.startswith('<'):
        files_to_load.add(ctx.file_path)
    for loc in ctx.include_trace:
        if loc.file_path and not loc.file_path.startswith('<'):
            files_to_load.add(loc.file_path)

    for fp in files_to_load:
        try:
            with open(fp, 'r') as f:
                result[fp] = f.readlines()
        except Exception:
            pass  # skip files we can't read

    return result


def handle_dracon_error(error: DraconError, exit_code: int = 1, use_rich: bool = True) -> None:
    """Handle a DraconError by printing formatted output and optionally exiting.

    This is the recommended way to handle DraconErrors at the CLI level.
    It loads source lines for context and displays a nicely formatted error message.

    Args:
        error: The DraconError to handle
        exit_code: If >= 0, call sys.exit with this code. If < 0, just print and return.
        use_rich: Whether to use rich formatting if available
    """
    import sys
    source_lines = load_source_lines(error)
    print_dracon_error(error, source_lines=source_lines, use_rich=use_rich)
    if exit_code >= 0:
        sys.exit(exit_code)


##────────────────────────────────────────────────────────────────────────────}}}
