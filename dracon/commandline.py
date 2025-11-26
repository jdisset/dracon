# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.
import sys
import typing
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import (
    List,
    Dict,
    Tuple,
    Optional,
    Annotated,
    Any,
    TypeVar,
    Generic,
    Callable,
    ForwardRef,
    Union,
    Type,
    Literal,
    get_args,
    get_origin as typing_get_origin,
)

from dracon.composer import CompositionResult
from dracon.nodes import DraconMappingNode
from dracon.diagnostics import DraconError, print_dracon_error
from pydantic import BaseModel, ValidationError, ConfigDict
from pydantic_core import PydanticUndefined
from rich.box import ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from dracon import DraconLoader
from dracon.deferred import DeferredNode
from dracon.keypath import KeyPath
from dracon.lazy import resolve_all_lazy
from dracon.merge import MergeKey
from dracon.resolvable import Resolvable, get_inner_type
from dracon.utils import build_nested_dict, list_like, dict_like

COLOR_RED = "#EC7D76"
COLOR_BLUE = "#8D5DE9"
COLOR_YELLOW = "#F3CD73"
COLOR_BOLD_CYAN = "bold #5DE6B6"
COLOR_CYAN = "#5DE6B6"
COLOR_BRIGHT_BLACK = "bright_black"
COLOR_DIM = "dim"
COLOR_ITALIC = "italic"
COLOR_BOLD = "bold"
COLOR_WHITE = "white"
COLOR_DEFAULT = "default"
COLOR_BOLD_RED = "bold #EC7D76"

logger = logging.getLogger(__name__)

B = TypeVar("B", bound=BaseModel)
ProgramType = ForwardRef("Program")


def get_root_exception(e):
    while e.__cause__ is not None:
        e = e.__cause__
    return e


@dataclass(frozen=True)
class Arg:
    """maps a pydantic field to cli arguments."""

    real_name: Optional[str] = None
    short: Optional[str] = None
    long: Optional[str] = None
    help: Optional[str] = None
    arg_type: Optional[Type[Any]] = None
    action: Optional[Callable[[ProgramType, Any], Any]] = None
    default_str: Optional[str] = None
    positional: bool = False
    resolvable: bool = False
    is_file: bool = False
    is_flag: Optional[bool] = None  # none means auto-detect
    auto_dash_alias: Optional[bool] = None  # none means overridden by the program


def _get_arg_resolvable_status(arg_type: Optional[Type[Any]]) -> bool:
    """determine if an arg type implies resolvable status."""
    origin = getattr(arg_type, '__origin__', None)
    try:
        return issubclass(origin, (DeferredNode, Resolvable))
    except TypeError:
        return isinstance(arg_type, type) and issubclass(arg_type, (DeferredNode, Resolvable))


def getArg(program: "Program", name: str, pydantic_field) -> Arg:
    """creates the final Arg object based on model field and program defaults."""
    base_arg = Arg(
        real_name=name,
        arg_type=pydantic_field.annotation,
        auto_dash_alias=program.default_auto_dash_alias,
    )
    user_settings = next((m for m in pydantic_field.metadata if isinstance(m, Arg)), None)
    user_arg_settings = (
        {k: v for k, v in vars(user_settings).items() if v is not None and k != 'real_name'}
        if user_settings
        else {}
    )
    final_settings = {**vars(base_arg), **user_arg_settings}

    # use field description as fallback help text
    if final_settings.get('help') is None and pydantic_field.description:
        final_settings['help'] = pydantic_field.description

    if final_settings.get('is_flag') is None:
        final_settings['is_flag'] = final_settings.get('arg_type') is bool

    auto_dash = final_settings.get('auto_dash_alias')
    final_settings['long'] = final_settings.get('long') or (
        name.replace('_', '-') if auto_dash and '_' in name else name
    )
    final_settings['resolvable'] = _get_arg_resolvable_status(final_settings.get('arg_type'))
    logger.debug(f"field {name}: resolvable={final_settings['resolvable']}")
    return Arg(**final_settings)


T = TypeVar("T")


## {{{                        --     Help Printing     --

console = Console()


def _format_type_str(arg_type, is_file: bool = False) -> str:
    """formats a type annotation into a display string for help."""
    if arg_type is None:
        return ""

    # handle ForwardRef first
    if isinstance(arg_type, ForwardRef):
        try:
            return _format_type_str(typing._eval_type(arg_type, globals(), locals()))  # type: ignore
        except (NameError, AttributeError):
            return arg_type.__forward_arg__

    origin = typing_get_origin(arg_type)
    args = get_args(arg_type)

    # unwrap Annotated, DeferredNode, Resolvable
    if origin is Annotated:
        return _format_type_str(args[0], is_file) if args else ""
    if origin is DeferredNode:
        return _format_type_str(args[0], is_file) if args else "Any"
    if origin is Resolvable:
        return _format_type_str(args[0], is_file) if args else "Any"

    # handle specific origins
    if origin is Literal:
        vals = [repr(a) for a in args]
        return f"{', '.join(vals[:-1])}, or {vals[-1]}" if len(vals) > 1 else vals[0]
    if origin is Union:
        non_none = [_format_type_str(t, is_file) for t in args if t is not type(None)]
        return non_none[0] if len(non_none) == 1 else f"Union[{', '.join(non_none)}]"
    if origin in (list, List):
        return f"List[{_format_type_str(args[0], is_file) if args else 'Any'}]"
    if origin in (dict, Dict):
        key_type = _format_type_str(args[0], is_file) if args else 'Any'
        val_type = _format_type_str(args[1], is_file) if len(args) > 1 else 'Any'
        return f"Dict[{key_type}, {val_type}]"

    type_name = getattr(arg_type, "__name__", str(arg_type))
    if is_file:
        if type_name in ("str", "Path", "os.PathLike"):
            return "file path"
        return f"File path to {type_name}"
    if type_name in ('str', 'int', 'float', 'bool'):
        return type_name
    return type_name


def _format_default_value(value: Any) -> Optional[str]:
    """formats a field's default value for display."""
    if value is PydanticUndefined:
        return None
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, DeferredNode):  # show inner value for deferred defaults
        inner = getattr(value, 'value', None)
        return _format_default_value(inner)
    return str(value)


def _is_optional_field(field) -> bool:
    """checks if a pydantic field is optional."""
    return field.default is not PydanticUndefined or field.default_factory is not None


def _append_arg_details(content: Text, arg: Arg, field: Optional[Any], is_positional: bool) -> None:
    """appends details for a single argument to the help text."""
    help_text = arg.help or ""
    arg_type_str = _format_type_str(arg.arg_type, is_file=arg.is_file)
    default = _format_default_value(field.default) if field else None
    if arg.default_str is not None:  # for custom default strings
        default = arg.default_str
    required = not _is_optional_field(field) if field else False
    required_marker = (
        Text(" (required)", style=COLOR_RED)
        if required and (is_positional or '.' not in arg.real_name)
        else Text("")
    )

    if is_positional:
        content.append(f"  {arg.real_name.upper()}", style=COLOR_YELLOW)
        content.append(required_marker)
        content.append(f" ({arg_type_str})\n", style=COLOR_BLUE if arg_type_str else "")
    else:
        parts = [f"-{arg.short}"] if arg.short else []
        if arg.long:
            parts.append(f"--{arg.long}")
        option_str = ", ".join(parts)
        is_flag = get_inner_type(arg.arg_type) is bool

        if not is_flag:
            content.append(f"  {option_str}", style=COLOR_YELLOW)
            if arg_type_str:
                content.append(f" {arg_type_str}", style=COLOR_BLUE)
            content.append(required_marker)
            content.append("\n")
        else:
            content.append(f"  {option_str}", style=COLOR_YELLOW)  # flags can't be required
            content.append("\n")

    # indented details
    if help_text:
        content.append(f"    {help_text}\n")
    if default is not None:
        content.append(f"    [default: {default}]\n", style=COLOR_DIM)
    content.append("\n")


def _gather_all_args(prg: "Program") -> Tuple[List[Arg], List[Arg]]:
    """gathers top-level and nested args for help display."""
    top_level_args = {a.real_name: a for a in prg._args}
    # options_flags = sorted(top_level_args.values(), key=lambda a: (a.long or a.real_name).lower())
    options_flags = list(top_level_args.values())
    nested_args = []
    processed_models = set()
    queue = [(prg.conf_type, "")]

    while queue:
        model_type, prefix = queue.pop(0)
        if id(model_type) in processed_models:
            continue
        processed_models.add(id(model_type))

        for name, field in getattr(model_type, 'model_fields', {}).items():
            if not prefix and name in top_level_args:
                continue  # already handled

            current_prefix = f"{prefix}{name}"
            long_name = (
                current_prefix.replace('_', '-') if prg.default_auto_dash_alias else current_prefix
            )
            # check if this specific nested arg long name was already generated (e.g., from another branch)
            if any(a.long == long_name for a in options_flags + nested_args):
                continue

            field_type = get_inner_type(field.annotation)
            if isinstance(field_type, type) and issubclass(field_type, BaseModel):
                queue.append((field_type, f"{current_prefix}."))

            # check if the field itself corresponds to a registered top-level Arg (e.g., for is_file)
            # this happens if a nested structure is also a top-level argument field
            corresponding_arg = top_level_args.get(current_prefix)
            is_file_hint = corresponding_arg.is_file if corresponding_arg else False

            nested_args.append(
                Arg(
                    real_name=current_prefix,
                    long=long_name,
                    help=field.description or "",
                    arg_type=field.annotation,
                    is_file=is_file_hint,
                )
            )

    return options_flags, nested_args


def print_help(prg: "Program", _) -> None:
    """prints the help message and exits."""
    positionals = [a for a in prg._args if a.positional]
    options_flags, nested_args = _gather_all_args(prg)
    all_options_flags = sorted(
        [a for a in options_flags if not a.positional and a.real_name != 'help'] + nested_args,
        key=lambda a: (a.long or a.real_name).lower(),
    )
    help_arg = next((a for a in options_flags if a.real_name == 'help'), None)

    content = Text()
    if prg.description:
        content.append(f"\n{prg.description}\n\n", style=COLOR_ITALIC)
        content.append("─" * min(console.width - 4, 80) + "\n\n", style=COLOR_BRIGHT_BLACK)

    usage = [prg.name or "command"] + ["[OPTIONS]"] if all_options_flags else []
    usage.extend(pos.real_name.upper() for pos in positionals)
    content.append("Usage: ", style=COLOR_BOLD)
    content.append(" ".join(usage) + "\n\n", style=COLOR_YELLOW)

    if positionals:
        content.append("Arguments:\n", style=COLOR_BOLD_CYAN)
        for arg in positionals:
            field = prg.conf_type.model_fields.get(arg.real_name)
            _append_arg_details(content, arg, field, is_positional=True)

    if all_options_flags or help_arg:
        content.append("Options:\n", style=COLOR_BOLD_CYAN)
        for arg in all_options_flags:
            # find corresponding field definition if possible
            field, model = None, prg.conf_type
            try:
                for part in arg.real_name.split('.'):
                    field = getattr(model, 'model_fields', {}).get(part)
                    annotation = get_inner_type(field.annotation) if field else None
                    if field and isinstance(annotation, type) and issubclass(annotation, BaseModel):
                        model = annotation
                    elif not field:
                        break
            except (AttributeError, TypeError):
                field = None
            _append_arg_details(content, arg, field, is_positional=False)
        if help_arg:  # ensure help is always last
            _append_arg_details(content, help_arg, None, is_positional=False)

    title = Text(prg.name or "Command", style=COLOR_BOLD_CYAN)
    if prg.version:
        title.append(f" (v{prg.version})", style=COLOR_CYAN)
    console.print(
        Panel(content, title=title, box=ROUNDED, border_style=COLOR_BRIGHT_BLACK, expand=False)
    )
    sys.exit(0)


##────────────────────────────────────────────────────────────────────────────}}}


class ArgParseError(Exception):
    pass


class Program(BaseModel, Generic[T]):
    conf_type: type[T]

    name: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    default_auto_dash_alias: bool = True

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    def model_post_init(self, *args, **kwargs):
        super().model_post_init(*args, **kwargs)
        self._args = [getArg(self, name, f) for name, f in self.conf_type.model_fields.items()]
        self._args.append(
            Arg(
                real_name="help",
                short="h",
                long="help",
                help="Print this help message",
                action=print_help,
            )
        )
        self._arg_map = {f'-{a.short}': a for a in self._args if a.short}
        self._arg_map.update({f'--{a.long}': a for a in self._args if a.long})

        # validate positional arguments - if any positional arg is a collection, no other positional args allowed
        positional_args = [arg for arg in self._args if arg.positional]
        for arg in positional_args:
            collection_type = self._get_collection_type(arg)
            if collection_type == "list_like" and len(positional_args) > 1:
                raise ValueError(
                    "When a positional argument is a list, no other positional arguments are allowed."
                )
            elif collection_type == "dict_like" and len(positional_args) > 1:
                raise ValueError(
                    "When a positional argument is a dict, no other positional arguments are allowed."
                )

    def parse_args(self, argv: List[str], **kwargs) -> tuple[Optional[T], Dict[str, Any]]:
        """parses command line arguments and generates configuration."""

        self._positionals = [arg for arg in self._args if arg.positional][::-1]  # reverse for pop()
        logger.debug(f"positional args: {self._positionals}, arg map: {self._arg_map}")

        raw_args, defined_vars, actions, confs_to_merge = {}, {}, [], []
        nested_args = {}

        # we parse each argument in argv, updating the raw_args and nested_args dicts
        try:
            i = 0
            while i < len(argv):
                i = self._parse_single_arg(
                    argv, i, raw_args, nested_args, defined_vars, actions, confs_to_merge
                )
        except ArgParseError as e:
            print(f"\nError: {e}\n", file=sys.stderr)
            print_help(self, None)  # exits

        logger.debug(
            f"parsed raw_args: {raw_args}, nested_args: {nested_args}, defined_vars: {defined_vars}"
        )
        conf = None
        if print_help in actions:
            print_help(self, None)
        try:
            # merge stored context from Program instance with kwargs
            program_context = getattr(self, 'context', None)
            if program_context:
                kwargs = {'context': program_context, **kwargs}
            conf = self._generate_config(
                raw_args, nested_args, defined_vars, confs_to_merge, **kwargs
            )
            for action in actions:  # process actions like --help after config generation
                action_result = action(self, conf)
                if action_result is not None:
                    conf = action_result
        except DraconError as e:
            # print dracon errors with full context information
            print_dracon_error(e)
            sys.exit(1)
        except ValidationError as e:
            self.print_validation_error(e)
        except Exception as e:  # catch other config generation errors
            root_exception = get_root_exception(e)
            if isinstance(root_exception, DraconError):
                print_dracon_error(root_exception)
                sys.exit(1)
            elif isinstance(root_exception, ValidationError):
                self.print_validation_error(root_exception)
            else:
                logger.error(f"Error when generating configuration: {root_exception}")
                logger.exception(e)
                sys.exit(1)

        # prepare final raw args dict for return
        final_raw_args = raw_args.copy()
        final_raw_args.update(
            {
                (k.replace('_', '-') if self.default_auto_dash_alias else k): v
                for k, v in nested_args.items()
            }
        )
        return conf, final_raw_args

    def _format_error_item_text(self, error: dict) -> Text:
        from .loader import dump

        loc_str = "[request root]" if not error['loc'] else ".".join(map(str, error['loc']))
        msg = error['msg']
        input_val = error.get('input')
        error_type = error['type']

        item_text = Text()
        bullet_line = Text("  • ", style=COLOR_DEFAULT)
        bullet_line.append("Arg ", style=COLOR_WHITE)
        bullet_line.append(f"'{loc_str}'", style=COLOR_CYAN)

        if error_type == 'missing':
            bullet_line.append(" is missing.")
        else:
            bullet_line.append(f": {msg}", style=COLOR_WHITE)

        item_text.append(bullet_line)

        def truncate_repr(value: Any, max_len: int, ellipsis: str = "...") -> str:
            s = repr(value)
            return s if len(s) <= max_len else s[: max_len - len(ellipsis)] + ellipsis

        if error_type != 'missing' and input_val is not None:
            input_repr = '\n     '.join([''] + dump(input_val).splitlines())
            details_line = Text(f"\n    Input: {input_repr}", style=COLOR_DIM)
            details_line.append(f"\n    Type: {type(input_val).__name__}", style=COLOR_DIM)

            if error.get('ctx'):
                ctx_items = []
                for k, v_ctx in error['ctx'].items():
                    if k == 'error' and hasattr(v_ctx, 'message'):
                        v_ctx = v_ctx.message
                        continue
                    if isinstance(v_ctx, (dict, list)) and len(str(v_ctx)) > 50:
                        continue

                    v_ctx_repr = truncate_repr(v_ctx, 20)
                    ctx_items.append(f"{k}={v_ctx_repr}")
                if ctx_items:
                    ctx_display_str = ", ".join(ctx_items)
                    details_line.append(f"\n    Context: {ctx_display_str}", style=COLOR_DIM)
            item_text.append(details_line)
        return item_text

    def print_validation_error(self, e: 'ValidationError'):
        error_types = defaultdict(list)
        for error_detail in e.errors():
            error_types[error_detail['type']].append(error_detail)

        def format_error_type_title(type_key: str):
            if type_key == "missing":
                return "Missing Arguments"

            type_display_name = ' '.join(
                part.replace('_', ' ') for part in type_key.split('.')
            ).title()

            return (
                type_display_name
                if type_display_name.endswith(("Error", "Errors"))
                else f"{type_display_name} Errors"
            )

        all_error_text_segments = []
        is_first_group = True
        for error_type_key, errors_in_group in sorted(error_types.items()):
            if not is_first_group:
                all_error_text_segments.append(Text("\n"))
            is_first_group = False

            title = format_error_type_title(error_type_key)
            all_error_text_segments.append(Text(f"{title}:\n", style=COLOR_BOLD_RED))

            for error_item_data in errors_in_group:
                all_error_text_segments.append(self._format_error_item_text(error_item_data))
                all_error_text_segments.append(Text("\n"))

        if all_error_text_segments and all_error_text_segments[-1].plain == "\n":
            all_error_text_segments.pop()

        assembled_text = Text.assemble(*all_error_text_segments)

        final_content = (
            assembled_text
            if assembled_text.plain.strip()
            else Text("No specific error details to display.", style=COLOR_DIM)
        )

        error_panel = Panel(
            final_content,
            # title=Text("Errors", style="bold red"),
            box=ROUNDED,
            border_style=COLOR_RED,
            expand=False,
            padding=(1, 5),
        )

        console.print(error_panel)
        print_help(self, None)

    def _parse_single_arg(
        self,
        argv: List[str],
        i: int,
        raw_args: Dict,  # raw args are
        nested_args: Dict,
        defined_vars: Dict,
        actions: List,
        confs_to_merge: List,
    ) -> int:
        """parses one argument from argv at index i, returning the next index."""

        argstr = argv[i]
        target_dict, real_name, arg_obj = raw_args, None, None  # default target is raw_args

        if argstr.startswith('--define.'):  # it's a variable definition
            var_part = argstr[9:]
            if not var_part:
                raise ArgParseError("empty variable name after --define.")
            # check for equals syntax: --define.VAR=value
            if '=' in var_part:
                var_name, var_value = var_part.split('=', 1)
            else:
                var_name = var_part
                var_value, i = self._read_value(argv, i)
            defined_vars[var_name] = var_value

        elif argstr.startswith('++'):  # shorthand for --define
            var_part = argstr[2:]
            if not var_part:
                raise ArgParseError("empty variable name after ++")
            # check for equals syntax: ++VAR=value
            if '=' in var_part:
                var_name, var_value = var_part.split('=', 1)
            else:
                var_name = var_part
                var_value, i = self._read_value(argv, i)
            defined_vars[var_name] = var_value

        elif argstr.startswith('+'):  # it's an include
            confs_to_merge.append(argstr[1:])

        elif not argstr.startswith('-'):  # it's a positional argument
            if not self._positionals:
                raise ArgParseError(f"unexpected positional argument {argstr}")
            arg_obj = self._positionals.pop()

            # handle collection positional arguments
            collection_type = self._get_collection_type(arg_obj)
            if collection_type == "list_like":
                value, i = self._collect_list_values(argv, i)
                raw_args[arg_obj.real_name] = value
            elif collection_type == "dict_like":
                value, i = self._collect_dict_values(argv, i)
                raw_args[arg_obj.real_name] = value
            else:
                raw_args[arg_obj.real_name] = argstr

        else:  # handle options (-s, --long, --nested.key)
            arg_obj = self._arg_map.get(argstr)
            if arg_obj:  # known top-level option
                logger.debug(f"arg_obj: {arg_obj}")
                real_name = arg_obj.real_name
            elif argstr.startswith('--') and '.' in argstr:
                real_name = argstr[2:]  # use full dotted name as key for nested_args
                target_dict = nested_args
            else:
                raise ArgParseError(f"unknown argument {argstr}")

            if arg_obj and arg_obj.action:
                actions.append(arg_obj.action)

            elif arg_obj and arg_obj.is_flag:  # flag option, no need for value
                target_dict[real_name] = True

            else:  # option requires a value
                v, i = self._read_value(argv, i, arg_obj)
                # if is_file=true, prepend '+' to trigger loading, ensure 'file:' scheme
                if arg_obj and arg_obj.is_file and not v.startswith('+'):
                    v = f"+{v}"  # allow pkg:path etc. with is_file

                target_dict[real_name] = v
                logger.debug(f"setting {real_name} to {target_dict[real_name]}")
        return i + 1

    def _get_collection_type(self, arg_obj: Arg) -> Optional[str]:
        """checks if an argument expects a collection type and returns the type"""
        if not arg_obj or not arg_obj.arg_type:
            return None

        # unwrap Annotated types
        actual_type = arg_obj.arg_type
        origin = typing_get_origin(actual_type)
        if origin is Annotated:
            actual_type = get_args(actual_type)[0]
            origin = typing_get_origin(actual_type) or actual_type
        elif not origin:
            origin = actual_type

        try:  # test by creating an empty instance
            dummy = origin()
            if dict_like(dummy):
                return "dict_like"
            elif list_like(dummy) or isinstance(dummy, set):
                return "list_like"
        except:
            pass
        return None

    def _read_value(
        self, argv: List[str], i: int, arg_obj: Optional[Arg] = None
    ) -> tuple[str, int]:
        """reads the value for an option, advancing the index."""
        original_arg = argv[i]
        i += 1
        if i >= len(argv) or argv[i].startswith('-'):
            raise ArgParseError(f"expected value for argument {original_arg}")

        # check if this argument expects a collection type
        if arg_obj:
            collection_type = self._get_collection_type(arg_obj)
            if collection_type == "list_like":
                return self._collect_list_values(argv, i)
            elif collection_type == "dict_like":
                return self._collect_dict_values(argv, i)

        return argv[i], i

    def _collect_list_values(self, argv: List[str], i: int) -> tuple[str, int]:
        """collect multiple values for list arguments"""
        values = []
        start_i = i
        while i < len(argv) and not argv[i].startswith('-'):
            value = argv[i]
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            values.append(value)
            i += 1
        # if we only got one value, check if it looks like YAML syntax
        if len(values) == 1 and (argv[start_i].startswith('[') or "'" in argv[start_i]):
            return argv[start_i], i - 1  # use original unstripped value for YAML

        # convert to a proper YAML list representation that preserves interpolable elements
        yaml_list_items = []
        for value in values:
            yaml_list_items.append(repr(value))

        yaml_list = '[' + ', '.join(yaml_list_items) + ']'
        return yaml_list, i - 1

    def _collect_dict_values(self, argv: List[str], i: int) -> tuple[str, int]:
        """collect multiple key=value pairs for dict arguments"""
        pairs = []
        start_i = i
        while i < len(argv) and not argv[i].startswith('-'):
            value = argv[i]
            if value.startswith('{') or value.startswith('['):  # looks like JSON/YAML syntax
                if not pairs:
                    return value, i
                break
            if '=' in value:  # check for key=value syntax
                pairs.append(value)
            else:
                break
            i += 1

        if len(pairs) == 0 and i > start_i:
            return argv[start_i], i - 1

        flat_dict = {}
        for pair in pairs:
            key, value = pair.split('=', 1)
            # strip quotes from value
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            flat_dict[key] = value

        nested_dict = build_nested_dict(flat_dict)
        return str(nested_dict), i - 1

    def _compose_value(self, value: str, loader: DraconLoader) -> Any:
        """start composition from file/key reference if value starts with +"""
        if isinstance(value, str) and value.startswith('+'):
            include_str = value[1:]
            print(f"loading value from file/key reference: {include_str}")
            try:
                comp_val = loader.compose(include_str)
                logger.debug(f"loaded override value '{include_str}' as: {type(comp_val)}")
                return comp_val.root
            except Exception as e:
                logger.error(f"failed to load override value '{value}': {e}")
                raise ArgParseError(
                    f"Failed to load override reference '{include_str}': {e}"
                ) from e
        # else we parse the value from scratch
        return loader.compose_config_from_str(value)

    def _generate_config(
        self, raw_args: dict, nested_args: dict, defined_vars: dict, confs_to_merge: list, **kwargs
    ) -> Optional[T]:
        """generates the final configuration object by merging sources and validating."""

        from dracon.composer import CompositionResult

        loader = DraconLoader(
            enable_interpolation=True, base_dict_type=dict, base_list_type=list, **kwargs
        )
        loader.update_context(defined_vars)
        loader.yaml.representer.exclude_defaults = False
        pdump_str = loader.dump(self.conf_type.__new__(self.conf_type))

        logger.debug(f"pdump_str: {pdump_str}")

        # mark fields for deferral
        deferred_paths = []
        real_name_map = {arg.real_name: arg for arg in self._args}
        for field_name, field in self.conf_type.model_fields.items():
            arg = real_name_map.get(field_name)
            if arg and arg.resolvable:
                arg_path = KeyPath(f"/{field_name}")
                obj_type = get_inner_type(field.annotation)
                logger.debug(f"resolvable field: {field_name} -> {arg_path}. type={obj_type}")
                if arg_path not in loader.deferred_paths:
                    deferred_paths.append((arg_path, obj_type))
        loader.deferred_paths.extend(deferred_paths)

        # compose initial structure from defaults
        current_composition = loader.compose_config_from_str(pdump_str)

        # merge included config files
        if confs_to_merge:
            for conf in confs_to_merge:
                this_conf = loader.compose(conf)
                if not isinstance(this_conf, CompositionResult):
                    raise ArgParseError(f"invalid include file: {conf}")
                current_composition = loader.merge(
                    current_composition, this_conf, merge_key=MergeKey(raw="<<{<~}[<~]")
                )

        from dracon.nodes import Node

        def compose_value(v):
            if isinstance(v, Node):
                val = v
            else:
                val = self._compose_value(str(v), loader)
                if isinstance(val, CompositionResult):
                    val = val.root
            return val

        def dict_to_node(d):
            """convert a dict to DraconMappingNode, without dumping the full string first."""
            if isinstance(d, Node):
                return d
            elif isinstance(d, dict):
                node = DraconMappingNode(tag='tag:yaml.org,2002:map', value=[])
                for k, v in d.items():
                    key_node = loader.yaml.representer.represent_data(k)
                    value_node = dict_to_node(v)
                    node.value.append((key_node, value_node))
                return node
            else:
                return loader.yaml.representer.represent_data(d)

        processed_raw_args = {k: compose_value(v) for k, v in raw_args.items()}
        raw_args_dict = build_nested_dict(processed_raw_args)
        if raw_args_dict:
            raw_args_node = dict_to_node(raw_args_dict)
            raw_args_composition = CompositionResult(root=raw_args_node)
            current_composition = loader.merge(
                current_composition, raw_args_composition, merge_key=MergeKey(raw="<<{<+}[<~]")
            )

        # merge nested args
        processed_nested_args = {k: compose_value(v) for k, v in nested_args.items()}
        nested_arg_dict = build_nested_dict(processed_nested_args)

        if nested_arg_dict:
            # reuse the dict_to_node function defined above
            nested_args_node = dict_to_node(nested_arg_dict)
            nested_args_composition = CompositionResult(root=nested_args_node)
            current_composition = loader.merge(
                current_composition, nested_args_composition, merge_key=MergeKey(raw="<<{<+}[<~]")
            )

        res = loader.load_node(current_composition.root)
        res = self.conf_type.model_validate(res)

        resolve_all_lazy(res, root_obj=res, context_override=loader.context)

        if not isinstance(res, self.conf_type):
            raise ArgParseError(f"internal error: expected {self.conf_type} but got {type(res)}")
        return res


def make_program(conf_type: type, **kwargs):
    if not issubclass(conf_type, BaseModel):
        raise ValueError("make_program requires a BaseModel subclass")
    return Program[conf_type](conf_type=conf_type, **kwargs)
