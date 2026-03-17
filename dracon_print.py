#!/usr/bin/env python3
"""dracon-print — Inspect and dry-run Dracon configuration files.

Load one or more Dracon config files, apply composition (merging, includes,
instructions), and display the result. Files are layered left-to-right;
later files override earlier ones.
"""
import json
import logging
import os
import sys
from io import StringIO
from typing import Any, Dict, List, Optional

from dracon import DraconLoader, KeyPath, dump, resolve_all_lazy
from dracon.utils import build_nested_dict

VERSION = "0.2.0"
log = logging.getLogger("dracon-print")


def _parse_yaml_value(val: str) -> Any:
    """Parse a string as YAML so '5' -> int, '[1,2]' -> list, etc."""
    from ruamel.yaml import YAML
    yaml = YAML()
    try:
        return yaml.load(StringIO(val))
    except Exception:
        return val


def _apply_overrides(loader, composition, overrides: Dict[str, Any]):
    """Merge dotted-path overrides into a CompositionResult.

    Uses dracon's own build_nested_dict + merge — same mechanism as the CLI.
    """
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


class DraconPrint:
    """Core logic for inspecting dracon configs."""

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
        # -r and -j imply -c (resolve/json need constructed objects)
        self.construct = construct or resolve or json_output

    def run(self) -> str:
        """Load, process, and format config. Returns output string."""
        loader = DraconLoader(context=self.context.copy())
        cr = None

        try:
            if self.construct and not self.overrides:
                res = loader.load(self.config_files)
            else:
                cr = loader.compose(self.config_files)
                if self.overrides:
                    cr = _apply_overrides(loader, cr, self.overrides)
                if self.construct:
                    res = loader.load_node(cr.root)
                else:
                    res = cr.root
        except FileNotFoundError as e:
            self._error(f"File not found: {e}")
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

        return self._format(res, loader)

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
        try:
            from rich.box import ROUNDED
            from rich.console import Console
            from rich.table import Table

            console = Console(stderr=True)

            internal_prefixes = (
                '__DRACON', 'construct', 'getenv', 'getcwd', 'listdir',
                'join', 'basename', 'dirname', 'expanduser', 'now',
            )
            system_vars = (
                'DIR', 'FILE', 'FILE_PATH', 'FILE_STEM', 'FILE_EXT',
                'FILE_LOAD_TIME', 'FILE_LOAD_TIME_UNIX', 'FILE_LOAD_TIME_UNIX_MS', 'FILE_SIZE',
            )

            table = Table(title="Defined Variables", box=ROUNDED)
            table.add_column("Variable", style="cyan")
            table.add_column("Value", style="white")
            table.add_column("Source", style="dim")

            for name, value in sorted(self.context.items()):
                val_repr = repr(value)[:60] + ('...' if len(repr(value)) > 60 else '')
                table.add_row(name, val_repr, "CLI (++/--define)")

            defined = cr.defined_vars if cr and hasattr(cr, 'defined_vars') else {}
            for name, value in sorted(defined.items()):
                if name in self.context:
                    continue
                val_repr = repr(value)[:60] + ('...' if len(repr(value)) > 60 else '')
                table.add_row(name, val_repr, "config (!define)")

            for name, value in sorted(loader.context.items()):
                if name in self.context or name in defined:
                    continue
                if any(name.startswith(p) for p in internal_prefixes):
                    continue
                if name in system_vars:
                    continue
                if callable(value):
                    continue
                val_repr = repr(value)[:60] + ('...' if len(repr(value)) > 60 else '')
                table.add_row(name, val_repr, "context")

            console.print(table)
        except ImportError:
            print("--- Defined Variables ---", file=sys.stderr)
            for name, value in sorted(self.context.items()):
                print(f"  {name} = {value!r}  [CLI]", file=sys.stderr)


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
        result = {}
        for key_node, val_node in node.value:
            result[str(_node_to_dict(key_node))] = _node_to_dict(val_node)
        return result
    elif isinstance(node, SequenceNode):
        return [_node_to_dict(item) for item in node.value]
    elif isinstance(node, ScalarNode):
        tag = node.tag
        if tag == 'tag:yaml.org,2002:null' or node.value in ('null', 'None', '~', ''):
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


# ── CLI argument parsing ─────────────────────────────────────────────────────


def parse_argv(argv: List[str]) -> DraconPrint:
    """Parse command-line arguments into a DraconPrint instance."""
    SHORT_FLAGS = {
        'c': 'construct',
        'r': 'resolve',
        'p': 'permissive',
        'j': 'json_output',
        'v': 'verbose',
    }
    LONG_FLAGS = {
        '--construct': 'construct',
        '--resolve': 'resolve',
        '--permissive': 'permissive',
        '--json': 'json_output',
        '--str-output': 'str_output',
        '--show-vars': 'show_vars',
        '--verbose': 'verbose',
    }
    SHORT_OPTIONS = {'s': 'select', 'f': 'file'}  # options that take a value
    LONG_OPTIONS = {'--select': 'select', '--file': 'file'}

    config_files: List[str] = []
    context: Dict[str, Any] = {}
    overrides: Dict[str, Any] = {}
    flags: Dict[str, Any] = {}

    i = 0
    while i < len(argv):
        token = argv[i]

        # help / version (exit immediately)
        if token in ('--help', '-h'):
            _print_help()
            sys.exit(0)
        if token == '--version':
            print(f"dracon-print {VERSION}")
            sys.exit(0)

        # long flags (no value)
        if token in LONG_FLAGS:
            flags[LONG_FLAGS[token]] = True
            i += 1
            continue

        # long options with = or space-separated value
        if '=' in token and token.split('=', 1)[0] in LONG_OPTIONS:
            key, val = token.split('=', 1)
            name = LONG_OPTIONS[key]
            if name == 'file':
                config_files.append(val)
            else:
                flags[name] = val
            i += 1
            continue
        if token in LONG_OPTIONS:
            if i + 1 >= len(argv):
                print(f"Error: {token} requires a value", file=sys.stderr)
                sys.exit(1)
            name = LONG_OPTIONS[token]
            if name == 'file':
                config_files.append(argv[i + 1])
            else:
                flags[name] = argv[i + 1]
            i += 2
            continue

        # context variables: ++name value or ++name=value
        if token.startswith('++'):
            var_part = token[2:]
            if '=' in var_part:
                name, val = var_part.split('=', 1)
                context[name] = _parse_yaml_value(val)
            elif i + 1 < len(argv):
                context[var_part] = _parse_yaml_value(argv[i + 1])
                i += 1
            else:
                print(f"Error: {token} requires a value", file=sys.stderr)
                sys.exit(1)
            i += 1
            continue

        # --define.name value
        if token.startswith('--define.'):
            name_part = token[len('--define.'):]
            if '=' in name_part:
                name, val = name_part.split('=', 1)
                context[name] = _parse_yaml_value(val)
            elif i + 1 < len(argv):
                context[name_part] = _parse_yaml_value(argv[i + 1])
                i += 1
            else:
                print(f"Error: {token} requires a value", file=sys.stderr)
                sys.exit(1)
            i += 1
            continue

        # short flags/options: -c, -r, -cr, -s PATH, -crs PATH, etc.
        if token.startswith('-') and not token.startswith('--') and len(token) > 1:
            chars = token[1:]
            j = 0
            while j < len(chars):
                ch = chars[j]
                if ch in SHORT_FLAGS:
                    flags[SHORT_FLAGS[ch]] = True
                    j += 1
                elif ch in SHORT_OPTIONS:
                    name = SHORT_OPTIONS[ch]
                    remaining = chars[j + 1:]
                    if remaining:
                        val = remaining
                    elif i + 1 < len(argv):
                        i += 1
                        val = argv[i]
                    else:
                        print(f"Error: -{ch} requires a value", file=sys.stderr)
                        sys.exit(1)
                    if name == 'file':
                        config_files.append(val)
                    else:
                        flags[name] = val
                    break  # consumed rest of token
                else:
                    print(f"Error: unknown option: -{ch}", file=sys.stderr)
                    sys.exit(1)
            i += 1
            continue

        # --dotted.path=value or --dotted.path value (config path overrides)
        if token.startswith('--') and '.' in token.lstrip('-'):
            key_part = token[2:]
            if '=' in key_part:
                name, val = key_part.split('=', 1)
                overrides[name] = _parse_yaml_value(val)
            elif i + 1 < len(argv):
                overrides[key_part] = _parse_yaml_value(argv[i + 1])
                i += 1
            else:
                print(f"Error: {token} requires a value", file=sys.stderr)
                sys.exit(1)
            i += 1
            continue

        # unknown long flags
        if token.startswith('--'):
            print(f"Error: unknown option: {token}", file=sys.stderr)
            sys.exit(1)

        # +file syntax (dracon convention)
        if token.startswith('+'):
            config_files.append(token[1:])
            i += 1
            continue

        # positional: config file
        config_files.append(token)
        i += 1

    if not config_files:
        print("Error: no config files specified\n", file=sys.stderr)
        _print_help(file=sys.stderr)
        sys.exit(1)

    return DraconPrint(
        config_files=config_files,
        construct=flags.get('construct', False),
        resolve=flags.get('resolve', False),
        permissive=flags.get('permissive', False),
        select=flags.get('select'),
        json_output=flags.get('json_output', False),
        str_output=flags.get('str_output', False),
        show_vars=flags.get('show_vars', False),
        verbose=flags.get('verbose', False),
        context=context,
        overrides=overrides,
    )


HELP_TEXT = """\
dracon-print — Inspect and dry-run Dracon configurations

Usage: dracon-print [OPTIONS] CONFIG [CONFIG ...]

  Load one or more Dracon config files, apply composition (merging, includes,
  instructions), and display the result. Files are layered left-to-right;
  later files override earlier ones.

Options:
  -c, --construct       Fully construct into Python objects (default: compose only)
  -r, --resolve         Resolve all lazy interpolations (implies -c)
  -p, --permissive      Leave unresolvable ${...} as strings (use with -r)
  -s, --select PATH     Extract subtree at keypath (e.g., database.host)
  -j, --json            Output as JSON (implies -c)
      --str-output      Output raw str() instead of YAML
      --show-vars       Print table of all defined variables (to stderr)
  -v, --verbose         Enable debug logging
  -f, --file PATH       Config file (legacy, prefer positional args)
  -h, --help            Show this help
      --version         Show version

Context Variables:
  ++name value          Set context variable for ${...} expressions
  ++name=value          Equals form
  --define.name value   Long form

Config Overrides:
  --path.to.key value   Override a config value at a dotted keypath
  --path.to.key=value   Equals form

Examples:
  dracon-print config.yaml                      Compose and print
  dracon-print base.yaml override.yaml -c       Layer and construct
  dracon-print config.yaml -cr                  Construct and resolve
  dracon-print config.yaml -s database          Select subtree
  dracon-print config.yaml ++env=prod -cj       Inject var, JSON output
  dracon-print +base.yaml +prod.yaml -r         Dracon-style +file syntax
  dracon-print config.yaml --db.port=9999       Override nested config value"""


def _print_help(file=None):
    print(HELP_TEXT, file=file or sys.stdout)


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


def main():
    printer = parse_argv(sys.argv[1:])
    _setup_logging(printer.verbose)
    output = printer.run()
    if not output:
        return

    # syntax highlight when outputting to a TTY
    is_tty = sys.stdout.isatty()
    no_color = os.environ.get("NO_COLOR", "")
    if is_tty and not no_color and not printer.str_output:
        try:
            from rich.console import Console
            from rich.syntax import Syntax
            lang = "json" if printer.json_output else "yaml"
            console = Console()
            console.print(Syntax(output, lang, theme="monokai", line_numbers=False))
        except ImportError:
            print(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
