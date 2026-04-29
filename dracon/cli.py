"""dracon CLI — unified tool for inspecting and resolving dracon configs.

Replaces the standalone dracon-print tool. The `dracon` command is itself
a @dracon_program (eat your own dog food).

Usage:
    dracon show config.yaml -cr          # raw YAML mode
    dracon show myprogram --schema       # program-aware mode (future)
"""
import json
import logging
import os
import sys
from io import StringIO
from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel

from dracon import (
    Arg,
    DraconError,
    DraconLoader,
    KeyPath,
    Subcommand,
    dracon_program,
    dump,
    resolve_all_lazy,
    subcommand,
)
from dracon.utils import build_nested_dict

log = logging.getLogger("dracon")


# ── helpers (from dracon_print) ──────────────────────────────────────────────


def _parse_yaml_value(val: str) -> Any:
    """Parse a string as YAML so '5' -> int, '[1,2]' -> list, etc."""
    from ruamel.yaml import YAML
    yaml = YAML()
    try:
        return yaml.load(StringIO(val))
    except Exception:
        return val


def _apply_overrides(loader, composition, overrides: Dict[str, Any]):
    """Merge dotted-path overrides into a CompositionResult."""
    from dracon.composer import CompositionResult
    from dracon.merge import MergeKey
    from dracon.nodes import DraconMappingNode

    nested = build_nested_dict(overrides)

    def dict_to_node(d):
        if isinstance(d, dict):
            pairs = []
            for k, v in d.items():
                key_node = loader.yaml.representer.represent_data(k)
                val_node = dict_to_node(v)
                pairs.append((key_node, val_node))
            return DraconMappingNode(tag="tag:yaml.org,2002:map", value=pairs)
        return loader.yaml.representer.represent_data(d)

    override_node = dict_to_node(nested)
    override_comp = CompositionResult(root=override_node)
    return loader.merge(
        composition, override_comp, merge_key=MergeKey(raw="<<{<+}[<~]"),
    )


def _to_plain(obj) -> Any:
    """Recursively convert Dracontainers/Nodes/models to plain Python types."""
    from collections.abc import Mapping, Sequence as AbcSequence
    from pydantic import BaseModel
    from ruamel.yaml.nodes import Node
    from dracon.lazy import LazyInterpolable

    if isinstance(obj, LazyInterpolable):
        try:
            return _to_plain(obj.resolve())
        except Exception:
            return str(obj)
    if isinstance(obj, Node):
        return _node_to_dict(obj)
    if isinstance(obj, BaseModel):
        return {k: _to_plain(v) for k, v in obj.model_dump().items()}
    if isinstance(obj, Mapping):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(item) for item in obj]
    if isinstance(obj, AbcSequence) and not isinstance(obj, (str, bytes)):
        return [_to_plain(item) for item in obj]
    return obj


def _node_to_dict(node) -> Any:
    """Convert a YAML node tree to plain Python types."""
    from ruamel.yaml.nodes import MappingNode, ScalarNode, SequenceNode

    if isinstance(node, MappingNode):
        return {
            str(_node_to_dict(k)): _node_to_dict(v)
            for k, v in node.value
        }
    elif isinstance(node, SequenceNode):
        return [_node_to_dict(item) for item in node.value]
    elif isinstance(node, ScalarNode):
        tag = node.tag
        if tag == 'tag:yaml.org,2002:null':
            return None
        if tag == 'tag:yaml.org,2002:bool':
            return node.value.lower() in ('true', 'yes')
        if tag == 'tag:yaml.org,2002:int':
            try:
                return int(node.value)
            except ValueError:
                return node.value
        if tag == 'tag:yaml.org,2002:float':
            try:
                return float(node.value)
            except ValueError:
                return node.value
        return node.value
    return node


# ── DraconPrint (raw mode engine) ───────────────────────────────────────────


class DraconPrint:
    """Core logic for inspecting dracon configs (raw YAML mode)."""

    def __init__(
        self,
        config_files: List[str],
        construct: bool = False,
        resolve: bool = False,
        permissive: bool = False,
        select: Optional[str] = None,
        json_output: bool = False,
        str_output: bool = False,
        show_vars: bool = False,
        verbose: bool = False,
        context: Optional[Dict[str, Any]] = None,
        overrides: Optional[Dict[str, Any]] = None,
        trace: Optional[str] = None,
        trace_all: bool = False,
    ):
        self.config_files = config_files
        self.resolve = resolve
        self.permissive = permissive
        self.select = select
        self.json_output = json_output
        self.str_output = str_output
        self.show_vars = show_vars
        self.verbose = verbose
        self.context = context or {}
        self.overrides = overrides or {}
        self.trace = trace
        self.trace_all = trace_all
        self.construct = construct or resolve or json_output

    def run(self) -> str:
        """Load, process, and format config. Returns output string."""
        trace_enabled = self.trace is not None or self.trace_all
        loader = DraconLoader(context=self.context.copy(), trace=trace_enabled)
        cr = None

        try:
            if self.construct and not self.overrides and not trace_enabled:
                res = loader.load(self.config_files)
            else:
                cr = loader.compose(self.config_files)
                if self.overrides:
                    cr = _apply_overrides(loader, cr, self.overrides)
                    if cr.trace is not None:
                        from dracon.composition_trace import TraceEntry
                        for dotted_path, value in self.overrides.items():
                            cr.trace.record(dotted_path, TraceEntry(
                                value=value, source=None,
                                via="cli_override",
                                detail=f"--{dotted_path}={value}",
                            ))
                if self.construct:
                    res = loader.load_node(cr.root)
                else:
                    res = cr.root
        except FileNotFoundError as e:
            self._error(f"File not found: {e}")
        except DraconError as e:
            from dracon.diagnostics import handle_dracon_error
            handle_dracon_error(e, exit_code=1)
        except Exception as e:
            self._error(f"Failed to load config: {e}")

        if self.resolve:
            try:
                res = resolve_all_lazy(res, permissive=self.permissive)
            except Exception as e:
                self._error(f"Failed to resolve: {e}")

        if self.select:
            try:
                kp = KeyPath(self.select)
                res = kp.get_obj(res)
            except Exception as e:
                self._error(f"Cannot select '{self.select}': {e}")

        if self.show_vars:
            self._print_vars(loader, cr)

        if trace_enabled and cr is not None and cr.trace is not None:
            if self.trace_all:
                return cr.trace.format_all()
            elif self.trace:
                return cr.trace.format_path(self.trace)
            return ""

        return self._format(res, loader)

    def run_rich_trace(self):
        """Run and return rich trace renderable (for TTY output)."""
        trace_enabled = self.trace is not None or self.trace_all
        if not trace_enabled:
            return None
        loader = DraconLoader(context=self.context.copy(), trace=True)
        cr = loader.compose(self.config_files)
        if self.overrides:
            cr = _apply_overrides(loader, cr, self.overrides)
        if cr.trace is None:
            return None
        if self.trace_all:
            return cr.trace.format_all_rich()
        elif self.trace:
            return cr.trace.format_path_rich(self.trace)
        return None

    def _error(self, msg: str):
        print(msg, file=sys.stderr)
        sys.exit(1)

    def _format(self, res, loader) -> str:
        if self.str_output:
            return str(res)
        elif self.json_output:
            return self._to_json(res)
        else:
            return dump(res, loader=loader)

    def _to_json(self, res) -> str:
        from dracon.lazy import LazyInterpolable

        def default_serializer(obj):
            if isinstance(obj, LazyInterpolable):
                try:
                    return obj.resolve()
                except Exception:
                    return str(obj)
            if hasattr(obj, 'model_dump'):
                return obj.model_dump()
            return str(obj)

        data = _to_plain(res)
        return json.dumps(data, indent=2, default=default_serializer)

    def _print_vars(self, loader, cr=None):
        """Print defined variables table to stderr."""
        def _trunc(value, maxlen=60):
            r = repr(value)
            return r[:maxlen] + '...' if len(r) > maxlen else r

        try:
            from rich.box import ROUNDED
            from rich.console import Console
            from rich.table import Table

            console = Console(stderr=True)
            _INTERNAL = (
                '__DRACON', 'construct', 'getenv', 'getcwd', 'listdir',
                'join', 'basename', 'dirname', 'expanduser', 'now',
            )
            _SYSTEM = {
                'DIR', 'FILE', 'FILE_PATH', 'FILE_STEM', 'FILE_EXT',
                'FILE_LOAD_TIME', 'FILE_LOAD_TIME_UNIX', 'FILE_LOAD_TIME_UNIX_MS', 'FILE_SIZE',
            }

            table = Table(title="Defined Variables", box=ROUNDED)
            table.add_column("Variable", style="cyan")
            table.add_column("Value", style="white")
            table.add_column("Source", style="dim")

            for name, value in sorted(self.context.items()):
                table.add_row(name, _trunc(value), "CLI (++/--define)")

            defined = cr.defined_vars if cr and hasattr(cr, 'defined_vars') else {}
            for name, value in sorted(defined.items()):
                if name not in self.context:
                    table.add_row(name, _trunc(value), "config (!define)")

            for name, value in sorted(loader.context.items()):
                if name in self.context or name in defined:
                    continue
                if any(name.startswith(p) for p in _INTERNAL) or name in _SYSTEM or callable(value):
                    continue
                table.add_row(name, _trunc(value), "context")

            console.print(table)
        except ImportError:
            print("--- Defined Variables ---", file=sys.stderr)
            for name, value in sorted(self.context.items()):
                print(f"  {name} = {value!r}  [CLI]", file=sys.stderr)


# ── program-aware helpers ────────────────────────────────────────────────────


def _get_program_schema(program_cls) -> dict:
    """Extract JSON Schema from a @dracon_program class."""
    return program_cls.model_json_schema()


def _construct_defaults(program_cls):
    """Construct a model instance using only fields that have defaults.

    Skips required fields (like Subcommand) so we can show the config
    defaults of any program without needing a valid subcommand selection.
    """
    from pydantic.fields import PydanticUndefined
    defaults = {}
    for name, field in program_cls.model_fields.items():
        if field.default is not PydanticUndefined:
            defaults[name] = field.default
        elif field.default_factory is not None:
            defaults[name] = field.default_factory()
    return program_cls.model_construct(**defaults)


def _full_defaults(model_cls, depth: Optional[int] = None, _current_depth: int = 0) -> dict:
    """Recursively build a dict of all defaults, expanding nested models.

    - Optional[Model] fields with None default -> expanded with model defaults
    - list[Model] fields with [] default -> one example item with defaults
    - Respects depth limit: stops recursing at the limit
    """
    import typing
    from pydantic.fields import PydanticUndefined

    result = {}
    at_limit = depth is not None and _current_depth >= depth

    for name, field in model_cls.model_fields.items():
        ann = field.annotation
        has_default = field.default is not PydanticUndefined or field.default_factory is not None
        list_model = _is_list_of_model(ann)
        inner_model = _extract_model_type(ann)

        if list_model and not at_limit:
            item = _full_defaults(list_model, depth, _current_depth + 1)
            result[name] = [item]
        elif inner_model and not at_limit:
            result[name] = _full_defaults(inner_model, depth, _current_depth + 1)
        elif has_default:
            val = field.default if field.default is not PydanticUndefined else field.default_factory()
            if isinstance(val, BaseModel):
                if at_limit:
                    result[name] = {}
                else:
                    result[name] = _full_defaults(type(val), depth, _current_depth + 1)
            else:
                result[name] = val
    return result


def _extract_model_type(ann) -> Optional[type]:
    """Extract a BaseModel subclass from an annotation (handles Optional[M], M | N, etc.)."""
    import types
    import typing
    origin = getattr(ann, '__origin__', None)
    if origin is typing.Union or isinstance(ann, types.UnionType):
        args = [a for a in ann.__args__ if a is not type(None)]
        for a in args:
            if isinstance(a, type) and issubclass(a, BaseModel):
                return a
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return ann
    return None


def _is_list_of_model(ann) -> Optional[type]:
    """If ann is list[SomeModel], return SomeModel. Else None."""
    origin = getattr(ann, '__origin__', None)
    if origin is list:
        args = getattr(ann, '__args__', ())
        if args:
            inner = _extract_model_type(args[0])
            if inner:
                return inner
    return None


def _iter_dracon_entry_points():
    """Yield (ep_name, dracon_program_class) for all installed dracon programs."""
    import importlib
    from importlib.metadata import entry_points
    for ep in entry_points(group='console_scripts'):
        try:
            mod = importlib.import_module(ep.value.split(':')[0])
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type) and hasattr(attr, '_dracon_program_config'):
                    yield ep.name, attr
                    break
        except Exception:
            continue


def _discover_program(name: str):
    """Try to find a @dracon_program class by entry point name.

    Fast path: look up the specific entry point directly instead of
    scanning all console_scripts.
    """
    import importlib
    from importlib.metadata import entry_points
    try:
        eps = entry_points(group='console_scripts', name=name)
        for ep in eps:
            mod = importlib.import_module(ep.value.split(':')[0])
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type) and hasattr(attr, '_dracon_program_config'):
                    return attr
    except Exception:
        pass
    return None


# ── ShowCmd subcommand ───────────────────────────────────────────────────────


@subcommand("show")
class ShowCmd(BaseModel):
    """Compose, inspect, and resolve dracon configurations."""
    targets: Annotated[list[str], Arg(positional=True, help="files or program name")]
    do_construct: Annotated[bool, Arg(short="c", long="construct", help="construct into Python objects")] = False
    resolve: Annotated[bool, Arg(short="r", help="resolve lazy interpolations")] = False
    permissive: Annotated[bool, Arg(short="p", help="leave unresolvable ${...} as strings")] = False
    select: Annotated[Optional[str], Arg(short="s", help="extract subtree at keypath")] = None
    json_output: Annotated[bool, Arg(short="j", long="json", help="output as JSON")] = False
    no_docs: Annotated[bool, Arg(help="suppress inline descriptions")] = False
    emit_schema: Annotated[bool, Arg(long="schema", help="emit JSON Schema for a program model")] = False
    full: Annotated[bool, Arg(help="exhaustive config template with all nested defaults expanded")] = False
    diff: Annotated[bool, Arg(help="show delta from bare defaults")] = False
    depth: Annotated[Optional[int], Arg(help="limit recursion depth")] = None
    show_vars: Annotated[bool, Arg(help="print defined variables table")] = False
    symbols: Annotated[bool, Arg(help="list symbols in scope (human-readable)")] = False
    symbols_json: Annotated[bool, Arg(help="list symbols in scope (JSON for tooling)")] = False
    trace: Annotated[Optional[str], Arg(help="provenance chain for a config path")] = None
    trace_all: Annotated[bool, Arg(help="provenance for all values")] = False
    verbose: Annotated[bool, Arg(short="v", help="debug logging")] = False

    def _is_raw_mode(self) -> bool:
        """Detect mode from targets: yaml files / + prefix = raw, else program-aware."""
        if not self.targets:
            return True
        first = self.targets[0]
        return first.startswith('+') or first.endswith(('.yaml', '.yml')) or os.path.isfile(first)

    def run(self, ctx=None):
        _setup_logging(self.verbose)

        if self.emit_schema and not self._is_raw_mode():
            return self._run_schema_mode()

        if self._is_raw_mode():
            return self._run_raw_mode()

        return self._run_program_mode()

    def _split_targets(self) -> tuple[List[str], Dict[str, Any], Dict[str, Any]]:
        """split self.targets into (config_files, context, overrides).

        ++name=value / --define.name=value go to context; +file and bare paths
        go to config_files. Overrides start empty; reserved for dotted-key
        --x.y=z forms when those land back in raw mode."""
        config_files: List[str] = []
        context: Dict[str, Any] = {}
        overrides: Dict[str, Any] = {}
        for t in self.targets:
            if t.startswith('++'):
                var_part = t[2:]
                if '=' in var_part:
                    name, val = var_part.split('=', 1)
                    context[name] = _parse_yaml_value(val)
                else:
                    context[var_part] = True
            elif t.startswith('--define.'):
                var_part = t[9:]
                if '=' in var_part:
                    name, val = var_part.split('=', 1)
                    context[name] = _parse_yaml_value(val)
            elif t.startswith('+'):
                config_files.append(t[1:])
            else:
                config_files.append(t)
        return config_files, context, overrides

    def _build_printer(self) -> DraconPrint:
        """Build the DraconPrint engine matching this ShowCmd's argv state.

        Pure: no I/O, no sys.exit. Used by `_run_raw_mode` and by tests that
        want to introspect the parsed argv without actually running compose."""
        config_files, context, overrides = self._split_targets()
        return DraconPrint(
            config_files=config_files,
            construct=self.do_construct,
            resolve=self.resolve,
            permissive=self.permissive,
            select=self.select,
            json_output=self.json_output,
            show_vars=self.show_vars,
            verbose=self.verbose,
            context=context,
            overrides=overrides,
            trace=self.trace,
            trace_all=self.trace_all,
        )

    def _run_raw_mode(self) -> str:
        """Delegate to DraconPrint for raw YAML processing."""
        config_files, context, _ = self._split_targets()

        # handle --symbols / --symbols-json: compose, then render from symbol table
        if self.symbols or self.symbols_json:
            loader = DraconLoader(context=context.copy())
            cr = loader.compose(config_files)
            # merge composition-time !define vars into the symbol table for rendering
            scope = loader.context.copy()
            if hasattr(cr, 'defined_vars') and cr.defined_vars:
                scope.update(cr.defined_vars)
            if self.symbols_json:
                output = json.dumps(scope.to_json(), indent=2, sort_keys=True, default=str)
            else:
                output = scope.describe()
            print(output)
            return output

        printer = self._build_printer()

        is_tty = sys.stdout.isatty()
        no_color = os.environ.get("NO_COLOR", "")
        trace_mode = self.trace is not None or self.trace_all

        # rich trace for TTY
        if trace_mode and is_tty and not no_color:
            try:
                from rich.console import Console
                renderable = printer.run_rich_trace()
                if renderable is not None:
                    Console().print(renderable)
                    return ""
            except ImportError:
                pass

        output = printer.run()
        if not output:
            return ""

        # syntax highlight for TTY
        if is_tty and not no_color and not trace_mode:
            try:
                from rich.console import Console
                from rich.syntax import Syntax
                lang = "json" if self.json_output else "yaml"
                Console().print(Syntax(output, lang, theme="monokai", line_numbers=False))
                return output
            except ImportError:
                pass

        print(output)
        return output

    def _run_program_mode(self) -> str:
        """Program-aware mode: discover program, show resolved config."""
        program_name = self.targets[0]
        program_cls = _discover_program(program_name)
        if program_cls is None:
            print(f"Error: could not find dracon program '{program_name}'", file=sys.stderr)
            sys.exit(1)

        extra_configs = self.targets[1:]

        if self.full:
            data = _full_defaults(program_cls, depth=self.depth)
        elif extra_configs:
            try:
                instance = program_cls.from_config(*extra_configs)
            except SystemExit:
                print(f"Error: failed to load config for '{program_name}'", file=sys.stderr)
                sys.exit(1)
            except Exception as e:
                print(f"Error loading program config: {e}", file=sys.stderr)
                sys.exit(1)
            data = instance.model_dump()
        else:
            instance = _construct_defaults(program_cls)
            data = instance.model_dump()

        if not data:
            print(f"'{program_name}' has no config defaults. Use --schema to see its model.", file=sys.stderr)
            return ""
        if self.select:
            kp = KeyPath(self.select)
            data = kp.get_obj(data)
        if self.json_output or self.no_docs:
            output = json.dumps(data, indent=2, default=str)
        else:
            output = dump(data)

        print(output)
        return output

    def _run_schema_mode(self) -> str:
        """Emit JSON Schema for a program found by name."""
        program_name = self.targets[0]
        program_cls = _discover_program(program_name)
        if program_cls is None:
            print(f"Error: could not find dracon program '{program_name}'", file=sys.stderr)
            sys.exit(1)
        output = json.dumps(_get_program_schema(program_cls), indent=2)
        print(output)
        return output


# ── logging setup ────────────────────────────────────────────────────────────


def _setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.WARNING
    handlers = []
    if verbose:
        try:
            from rich.logging import RichHandler
            handlers.append(RichHandler(rich_tracebacks=True))
        except ImportError:
            pass
    logging.basicConfig(
        level=level, format="%(message)s", datefmt="[%X]",
        handlers=handlers if handlers else None, force=True,
    )


# ── completions helpers ──────────────────────────────────────────────────────


def _find_module_source(dotted: str) -> Optional[str]:
    """Locate a module's source file without importing it."""
    parts = dotted.split('.')
    for base in sys.path:
        if not base or not os.path.isdir(base):
            continue
        rel = os.path.join(*parts)
        for candidate in [f"{rel}.py", os.path.join(rel, "__init__.py")]:
            full = os.path.join(base, candidate)
            if os.path.isfile(full):
                return full
    return None


def _discover_dracon_programs() -> list[str]:
    """Find installed console_scripts that are @dracon_program powered.

    Locates each entry point's source file on disk and greps for
    'dracon_program' without importing anything. Fast even with
    many installed packages.
    """
    from importlib.metadata import entry_points

    results = []
    try:
        for ep in entry_points(group='console_scripts'):
            mod_path = ep.value.split(':')[0]
            src = _find_module_source(mod_path)
            if src:
                try:
                    with open(src) as f:
                        head = f.read(4096)
                    if 'dracon_program' in head:
                        results.append(ep.name)
                except Exception:
                    pass
    except Exception:
        pass
    return results or ["dracon"]


_BASH_SCRIPT = """\
_dracon_complete() {{
    local cur="${{COMP_WORDS[COMP_CWORD]}}"
    local IFS=$'\\n'
    # fast path: +file completion handled in shell (no python)
    if [[ "$cur" == +* && "$cur" != ++* ]]; then
        local prefix="${{cur:1}}"
        local files=($(compgen -f -- "$prefix" | while read -r f; do
            if [[ -d "$f" ]]; then echo "+$f/";
            elif [[ "$f" == *.yaml || "$f" == *.yml ]]; then echo "+$f";
            fi
        done))
        COMPREPLY=("${{files[@]}}")
        return
    fi
    COMPREPLY=($(COMP_LINE="$COMP_LINE" COMP_POINT="$COMP_POINT" \\
        dracon _complete "${{COMP_WORDS[0]}}" 2>/dev/null))
}}
{register_lines}
"""

_ZSH_SCRIPT = """\
_dracon_complete() {{
    local cur="${{words[CURRENT]}}"
    # +file: strip the + prefix, do native zsh path completion, re-add +
    if [[ "$cur" == +* && "$cur" != ++* ]]; then
        compset -P '+'
        _files -g '*.yaml *.yml'
        return
    fi
    local completions
    completions=(${{(f)"$(COMP_LINE="$BUFFER" COMP_POINT="$CURSOR" \\
        dracon _complete "${{words[1]}}" 2>/dev/null)"}})
    compadd -a completions
}}
{register_lines}
"""

_FISH_SCRIPT = """\
{register_lines}
"""


def _emit_shell_script(shell: str) -> str:
    programs = _discover_dracon_programs()
    if shell == "bash":
        lines = "\n".join(f"complete -o default -F _dracon_complete {p}" for p in programs)
        return _BASH_SCRIPT.format(register_lines=lines)
    elif shell == "zsh":
        lines = "\n".join(f"compdef _dracon_complete {p}" for p in programs)
        return _ZSH_SCRIPT.format(register_lines=lines)
    elif shell == "fish":
        lines = "\n".join(
            f"complete -c {p} -a '(COMP_LINE=(commandline) COMP_POINT=(commandline -C) dracon _complete {p} 2>/dev/null)'"
            for p in programs
        )
        return _FISH_SCRIPT.format(register_lines=lines)
    raise ValueError(f"unsupported shell: {shell}")


_SHELL_RC = {"bash": ".bashrc", "zsh": ".zshrc"}

# source from cache file; regen in background if stale (>1h)
_SHELL_SOURCE = {
    "bash": """\
[[ -f ~/.dracon/completions.bash ]] && source ~/.dracon/completions.bash
(dracon completions --regen bash &>/dev/null &)""",
    "zsh": """\
[[ -f ~/.dracon/completions.zsh ]] && source ~/.dracon/completions.zsh
(dracon completions --regen zsh &>/dev/null &)""",
}


def _cache_path(shell: str) -> str:
    return os.path.join(os.path.expanduser("~"), ".dracon", f"completions.{shell}")


def _write_cache(shell: str):
    """Write completion script to cache file."""
    path = _cache_path(shell)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    script = _emit_shell_script(shell)
    with open(path, "w") as f:
        f.write(script)
    return path


def _regen_if_stale(shell: str):
    """Regenerate cache if older than 1 hour."""
    import time
    path = _cache_path(shell)
    try:
        age = time.time() - os.path.getmtime(path)
        if age < 3600:
            return  # fresh enough
    except OSError:
        pass  # file doesn't exist, regen
    _write_cache(shell)


def _install_completions():
    """Auto-detect shell, write cache file, add source line to rc."""
    shell_path = os.environ.get("SHELL", "")
    shell = os.path.basename(shell_path)
    if shell not in ("bash", "zsh", "fish"):
        print(f"unsupported shell: {shell}", file=sys.stderr)
        sys.exit(1)

    home = os.path.expanduser("~")

    if shell == "fish":
        conf_dir = os.path.join(home, ".config", "fish", "conf.d")
        os.makedirs(conf_dir, exist_ok=True)
        target = os.path.join(conf_dir, "dracon.fish")
        script = _emit_shell_script("fish")
        with open(target, "w") as f:
            f.write(script)
        print(f"wrote {target}")
        return

    # write the cache file
    cache = _write_cache(shell)
    print(f"wrote {cache}")

    # add source line to rc
    rc_file = os.path.join(home, _SHELL_RC[shell])
    source_lines = _SHELL_SOURCE[shell]

    existing = ""
    if os.path.exists(rc_file):
        with open(rc_file) as f:
            existing = f.read()

    if f"completions.{shell}" in existing:
        print(f"already installed in {rc_file}")
        return

    with open(rc_file, "a") as f:
        f.write(f"\n{source_lines}\n")
    print(f"added to {rc_file}")


# ── CompletionsCmd subcommand ────────────────────────────────────────────────


@subcommand("completions")
class CompletionsCmd(BaseModel):
    """Install or emit shell completion scripts for dracon programs."""
    targets: Annotated[list[str], Arg(positional=True, help="shell name (bash/zsh/fish) or 'install'")] = []
    regen: Annotated[bool, Arg(help="regenerate cache if stale (called from shell bg)")] = False

    def run(self, ctx=None):
        if self.regen and self.targets:
            _regen_if_stale(self.targets[0])
            return ""

        if not self.targets:
            print("usage: dracon completions {bash|zsh|fish|install}", file=sys.stderr)
            sys.exit(1)

        action = self.targets[0]
        if action == "install":
            _install_completions()
            return ""
        if action in ("bash", "zsh", "fish"):
            print(_emit_shell_script(action))
            return ""

        print(f"unknown completions action: {action}", file=sys.stderr)
        print("usage: dracon completions {bash|zsh|fish|install}", file=sys.stderr)
        sys.exit(1)


# ── DraconCLI (the root @dracon_program) ────────────────────────────────────

def _get_version():
    try:
        from importlib.metadata import version
        return version("dracon")
    except Exception:
        return "0.1.1"


@dracon_program(name="dracon", version=_get_version())
class DraconCLI(BaseModel):
    """Dracon configuration toolkit."""
    command: Subcommand(ShowCmd, CompletionsCmd)


def main():
    DraconCLI.cli()


if __name__ == "__main__":
    main()
