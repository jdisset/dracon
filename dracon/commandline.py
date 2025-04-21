from pydantic import BaseModel, ValidationError, ConfigDict
from pydantic_core import PydanticUndefined
from dracon import DraconLoader
from dracon.composer import DRACON_UNSET_VALUE
import sys
from rich.console import Console
from rich.box import ROUNDED
from rich.text import Text
from rich.panel import Panel
import typing
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
)
from dataclasses import dataclass, field
from dracon.lazy import resolve_all_lazy
from dracon.resolvable import Resolvable, get_inner_type
from dracon.deferred import DeferredNode
from dracon.keypath import KeyPath
from dracon.loader import DEFAULT_LOADERS
import traceback
import logging
from dracon.merge import MergeKey, merged

logger = logging.getLogger(__name__)

B = TypeVar("B", bound=BaseModel)

ProgramType = ForwardRef("Program")


@dataclass(frozen=True)
class Arg:
    """
    configuration for command-line argument generation.

    maps a pydantic field to cli arguments like --my-arg, -m.
    """

    real_name: Optional[str] = None
    short: Optional[str] = None
    long: Optional[str] = None
    help: Optional[str] = None
    arg_type: Optional[Type[Any]] = None
    action: Optional[Callable[[ProgramType, Any], Any]] = None
    positional: bool = False
    resolvable: bool = False
    is_file: bool = False
    auto_dash_alias: Optional[bool] = None  # defaults handled by Program


def getArg(program: "Program", name: str, pydantic_field) -> Arg:
    """creates the final Arg object based on model field and program defaults."""
    base_arg = Arg(
        real_name=name,
        arg_type=pydantic_field.annotation,
        auto_dash_alias=program.default_auto_dash_alias,
    )

    user_arg_settings = {}
    for m in pydantic_field.metadata:
        if isinstance(m, Arg):
            user_arg_settings = {
                k: v for k, v in vars(m).items() if v is not None and k != 'real_name'
            }
            break  # assume only one Arg instance in metadata

    final_settings = {**vars(base_arg), **user_arg_settings}

    # determine final 'long' name
    final_long = final_settings.get('long')
    auto_dash = final_settings.get('auto_dash_alias')

    if final_long is None:  # user didn't specify long
        if auto_dash and '_' in name:
            final_long = name.replace('_', '-')
        else:
            final_long = name
    final_settings['long'] = final_long

    # determine final 'resolvable' status
    type_to_check = final_settings.get('arg_type')
    # use getattr to safely access __origin__ which might not exist on all types
    origin = getattr(type_to_check, '__origin__', None)
    if origin is Resolvable:
        final_settings['resolvable'] = True
    elif isinstance(type_to_check, type) and issubclass(type_to_check, DeferredNode):
        # also mark as resolvable if it's DeferredNode (which implies late construction)
        final_settings['resolvable'] = True

    return Arg(**final_settings)


T = TypeVar("T")


## {{{                        --     print help     --

console = Console()


def format_type_str(arg_type) -> str:
    if arg_type is None:
        return ""
    if isinstance(arg_type, ForwardRef):
        try:
            evaluated_type = typing._eval_type(arg_type, globals(), locals())  # type: ignore
            return format_type_str(evaluated_type)
        except (NameError, AttributeError):  # Fallback if eval fails or _eval_type not available
            return arg_type.__forward_arg__.upper()

    origin = getattr(arg_type, "__origin__", None)
    args = getattr(arg_type, "__args__", [])

    if origin:
        if origin is Annotated:
            return format_type_str(args[0]) if args else ""
        if origin is Resolvable:
            inner_type_str = format_type_str(args[0]) if args else "ANY"
            return f"RESOLVABLE[{inner_type_str}]"
        if origin is DeferredNode:
            inner_type_str = format_type_str(args[0]) if args else "ANY"
            return f"DEFERREDNODE[{inner_type_str}]"

        if origin is Union:
            non_none_types = [t for t in args if t is not type(None)]
            if len(non_none_types) == 1:
                return format_type_str(non_none_types[0])
            type_names = [format_type_str(t) for t in non_none_types]
            return f"UNION[{', '.join(type_names)}]"
        origin_name = getattr(origin, "__name__", str(origin)).upper()
        arg_strs = [format_type_str(arg) for arg in args]
        return f"{origin_name}[{', '.join(arg_strs)}]"

    if hasattr(arg_type, "__name__"):
        return arg_type.__name__.upper()
    return str(arg_type).upper()


def format_default_value(value: Any) -> str:
    if value is PydanticUndefined:
        return None
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, DeferredNode):
        inner_value = getattr(value, 'value', None)
        if isinstance(inner_value, (str, int, float, bool)):
            return f'deferred({format_default_value(inner_value)})'
        elif isinstance(inner_value, (list, dict)) and len(str(inner_value)) < 30:
            return f'deferred({inner_value!r})'
        else:
            return 'deferred(...)'
    return str(value)


def is_optional_field(field) -> bool:
    return (
        (field.default is not None and field.default is not PydanticUndefined)
        or field.default_factory is not None
        or (
            hasattr(field.annotation, "__origin__")
            and field.annotation.__origin__ is Union
            and type(None) in field.annotation.__args__
        )
    )


def format_type_display(name: str, arg_type: str, text: Text) -> None:
    text.append(f"  {name}", style="yellow")
    if arg_type:
        text.append(f" ")
        text.append(arg_type, style="blue")
    text.append("\n")


def print_help(prg: "Program", _) -> None:
    positionals = []
    options = []
    flags = []

    for arg in prg._args:
        if arg.positional:
            positionals.append(arg)
        elif arg.arg_type is bool:
            flags.append(arg)
        else:
            options.append(arg)

    # generate nested options for help display only
    processed_nested = set()
    queue = [(prg.conf_type, "")]
    while queue:
        model_type, prefix = queue.pop(0)
        # use id for set check as types might be dynamically created
        if id(model_type) in processed_nested:
            continue
        processed_nested.add(id(model_type))

        for name, field in model_type.model_fields.items():
            if not prefix and name in [a.real_name for a in prg._args]:
                continue

            current_prefix = f"{prefix}{name}"
            # use program default for dash alias in help for nested fields
            long_name_base = (
                current_prefix.replace('_', '-') if prg.default_auto_dash_alias else current_prefix
            )
            current_long = f"--{long_name_base}"

            # check if this exact long name already exists
            if any(a.long == current_long[2:] for a in options + flags):
                continue

            field_type = get_inner_type(field.annotation)

            if isinstance(field_type, type) and issubclass(field_type, BaseModel):
                queue.append((field_type, f"{current_prefix}."))

            nested_arg = Arg(
                real_name=current_prefix,
                long=current_long[2:],
                help=field.description or "",
                arg_type=field.annotation,
            )

            if get_inner_type(nested_arg.arg_type) is bool:  # handle Annotated[bool, ...]
                flags.append(nested_arg)
            elif not isinstance(field_type, type) or not issubclass(field_type, BaseModel):
                options.append(nested_arg)

    content = Text()

    if prg.description:
        content.append("\n" + prg.description + "\n\n", style="italic")
        content.append("─" * min(console.width - 4, 80) + "\n\n", style="bright_black")

    usage = [prg.name or "command"]
    if options or flags:
        usage.append("[OPTIONS]")
    for pos in positionals:
        usage.append(pos.real_name.upper())

    content.append("Usage: ", style="bold")
    content.append(" ".join(usage) + "\n\n", style="yellow")

    if positionals:
        content.append("Arguments:\n", style="bold green")
        for arg in positionals:
            name = arg.real_name.upper()
            help_text = arg.help or ""
            arg_type = format_type_str(arg.arg_type)

            field = prg.conf_type.model_fields.get(arg.real_name)
            default = None
            required = False

            if field:
                if field.default is not None and field.default is not PydanticUndefined:
                    default = format_default_value(field.default)
                elif field.default_factory is not None:
                    default = "<factory>"
                else:
                    required = not is_optional_field(field)

            content.append(f"  {name}\n", style="yellow")
            content.append(f"    type: ", style="bright_black")
            content.append(f"{arg_type}\n", style="blue")
            if required:
                content.append("    REQUIRED\n", style="red")
            elif default is not None:
                content.append("    default: ", style="bright_black")
                content.append(f"{default}\n", style="dim")
            if help_text:
                content.append(f"    {help_text}\n", style="default")
            content.append("\n")

    if options or flags:
        content.append("Options:\n", style="bold green")
        sorted_options = sorted(options + flags, key=lambda a: a.long)  # sort by long name
        for arg in sorted_options:
            parts = []
            if arg.short:
                parts.append(f"-{arg.short}")
            if arg.long:
                parts.append(f"--{arg.long}")  # use long here

            option_str = ", ".join(parts)
            # check inner type for bools to handle Annotated[bool] etc.
            is_flag = get_inner_type(arg.arg_type) is bool

            if not is_flag:
                name = option_str
                type_str = format_type_str(arg.arg_type)
                format_type_display(name, type_str, content)
            else:
                content.append(f"  {option_str}\n", style="yellow")

            help_text = arg.help or ""

            field = None
            model = prg.conf_type
            path_parts = arg.real_name.split('.')
            try:
                for part in path_parts:
                    current_model_fields = getattr(model, 'model_fields', {})
                    field = current_model_fields.get(part)
                    if field and hasattr(field.annotation, 'model_fields'):
                        # check if annotation is actually a model type
                        anno_type = get_inner_type(field.annotation)
                        if isinstance(anno_type, type) and issubclass(anno_type, BaseModel):
                            model = anno_type
                        else:  # stop traversing if not a model
                            break
                    elif not field:
                        break
            except (AttributeError, TypeError):
                field = None

            default = None
            required = False

            if field:
                if field.default is not None and field.default is not PydanticUndefined:
                    default = format_default_value(field.default)
                elif field.default_factory is not None:
                    default = "<factory>"
                else:
                    required = not is_optional_field(field)

            if help_text:
                content.append(f"    {help_text}\n")
            if '.' not in arg.real_name and required:
                content.append("    REQUIRED\n", style="red")
            elif default is not None:
                content.append("    default: ", style="bright_black")
                content.append(f"{default}\n", style="dim")
            content.append("\n")

    title = Text()
    title.append(prg.name if prg.name else "Command", style="bold cyan")
    if prg.version:
        title.append(f" (v{prg.version})", style="cyan")

    console.print(
        Panel(content, title=title, box=ROUNDED, border_style="bright_black", expand=False)
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
        self._arg_map = {}
        for arg in self._args:
            if arg.short:
                self._arg_map[f'-{arg.short}'] = arg
            if arg.long:
                self._arg_map[f'--{arg.long}'] = arg

    def parse_args(self, argv: List[str], **kwargs) -> tuple[Optional[T], Dict[str, Any]]:
        self._positionals = [arg for arg in self._args if arg.positional]
        self._positionals.reverse()

        logger.debug(f"positional args: {self._positionals}")
        logger.debug(f"arg map: {self._arg_map}")
        logger.debug(f"args: {self._args}")

        raw_args, defined_vars, actions, confs_to_merge = {}, {}, [], []
        nested_args = {}

        i = 0
        while i < len(argv):
            i = self._parse_single_arg(
                argv, i, raw_args, nested_args, defined_vars, actions, confs_to_merge
            )

        logger.debug(f"defined vars: {defined_vars}")

        conf = self.generate_config(raw_args, nested_args, defined_vars, confs_to_merge, **kwargs)
        if conf is not None:
            for action in actions:
                action_result = action(self, conf)
                if action_result is not None:
                    conf = action_result

        final_raw_args = raw_args.copy()
        for path_str, value in nested_args.items():
            # use the dashed version for the output dict key if preferred
            output_key = path_str.replace('_', '-') if self.default_auto_dash_alias else path_str
            final_raw_args[output_key] = value

        return conf, final_raw_args

    def _parse_single_arg(
        self,
        argv: List[str],
        i: int,
        raw_args: Dict,
        nested_args: Dict,
        defined_vars: Dict,
        actions: List,
        confs_to_merge: List,
    ) -> int:
        argstr = argv[i]

        if argstr.startswith('--define.'):
            return self._handle_define(argv, i, defined_vars)

        elif argstr.startswith('+'):
            confs_to_merge.append(argv[i][1:])
            return i + 1

        elif not argstr.startswith('-'):
            return self._handle_positional(argv, i, raw_args)

        else:
            return self._handle_option(argv, i, raw_args, nested_args, actions)

    def _handle_define(self, argv: List[str], i: int, defined_vars: Dict) -> int:
        var_name = argv[i][9:]
        var_value, i = self._read_value(argv, i)
        defined_vars[var_name] = var_value
        return i

    def _handle_positional(self, argv: List[str], i: int, raw_args: Dict) -> int:
        if not self._positionals:
            raise ArgParseError(f"Unexpected positional argument {argv[i]}")
        arg_obj = self._positionals.pop()
        raw_args[arg_obj.real_name] = argv[i]
        return i + 1

    def _handle_option(
        self, argv: List[str], i: int, raw_args: Dict, nested_args: Dict, actions: List
    ) -> int:
        logger.debug(f"handling option {argv[i]}")
        argstr = argv[i]

        if argstr in self._arg_map:
            arg_obj = self._arg_map[argstr]
            real_name = arg_obj.real_name
            target_dict = raw_args
        elif argstr.startswith('--') and '.' in argstr:
            # use the full dot.path as the key, preserving dashes
            real_name = argstr[2:]
            target_dict = nested_args
            arg_obj = None
        else:
            raise ArgParseError(f"Unknown argument {argstr}")

        if arg_obj and arg_obj.action is not None:
            actions.append(arg_obj.action)
            logger.debug(f"adding action {arg_obj.action} to the list of actions")
            return i + 1

        if arg_obj and get_inner_type(arg_obj.arg_type) is bool:
            target_dict[real_name] = True
            logger.debug(f"setting {real_name} to true")
            return i + 1

        v, i = self._read_value(argv, i)
        modifier = (lambda x: f"file:{x}") if (arg_obj and arg_obj.is_file) else (lambda x: x)
        modified_v = modifier(v)
        target_dict[real_name] = modified_v  # store using original field name
        logger.debug(f"setting {real_name} to {modified_v}")
        return i

    def _read_value(self, argv: List[str], i: int) -> tuple[str, int]:
        i += 1
        if i >= len(argv) or argv[i].startswith('-'):
            raise ArgParseError(f"Expected value for argument {argv[i - 1]}")
        return argv[i], i + 1

    def make_merge_str(self, confs_to_merge):
        DEFAULT_MERGE_ARGS = "{~<}[~<]"
        for i, conf in enumerate(confs_to_merge):
            key = f"<<{DEFAULT_MERGE_ARGS}_merge{i}"
            has_prefix = any(conf.startswith(f"{prefix}:") for prefix in DEFAULT_LOADERS.keys())
            if has_prefix:
                yield f"{key}: !include \"{conf}\""
            else:
                safe_conf = conf.replace('\\', '\\\\')
                yield f"{key}: !include \"file:{safe_conf}\""

    def _build_nested_override(self, nested_args: Dict[str, str]) -> Dict[str, Any]:
        override_dict = {}
        for key_path, value in nested_args.items():
            # important: convert dashes back to underscores for internal dict structure
            parts = key_path.replace('-', '_').split('.')
            current_level = override_dict
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    current_level[part] = value
                else:
                    current_level = current_level.setdefault(part, {})
        return override_dict

    def generate_config(
        self,
        raw_args: dict[str, str],
        nested_args: dict[str, str],
        defined_vars: dict[str, str],
        confs_to_merge: list[str],
        **kwargs,
    ) -> Optional[T]:
        nested_override_dict = self._build_nested_override(nested_args)

        loader = DraconLoader(
            enable_interpolation=True,
            base_dict_type=dict,
            base_list_type=list,
            **kwargs,
        )
        loader.update_context(defined_vars)

        empty_model = self.conf_type.model_construct()
        as_dict = empty_model.model_dump(exclude_unset=False)

        if confs_to_merge:
            try:
                merged_from_files = loader.load(confs_to_merge, merge_key="<<{<+}[<~]")
                as_dict = merged(as_dict, merged_from_files, MergeKey(raw="{<+}[<~]"))
            except FileNotFoundError as e:
                print(f"\nerror: configuration file not found: {e}", file=sys.stderr)
                sys.exit(1)
            except Exception as e:
                print(f"\nerror loading configuration files: {e}", file=sys.stderr)
                traceback.print_exc()
                sys.exit(1)

        if raw_args:
            processed_raw_args = {}
            for k, v in raw_args.items():
                if isinstance(v, str) and v.startswith('+'):
                    try:
                        temp_loader = DraconLoader(context=loader.context.copy(), **kwargs)
                        processed_raw_args[k] = temp_loader.load(v[1:])
                    except Exception as e:
                        logger.warning(f"failed to load override value '{v}' for key '{k}': {e}")
                        processed_raw_args[k] = v
                else:
                    processed_raw_args[k] = v

            as_dict = merged(as_dict, processed_raw_args, MergeKey(raw="{<+}[<~]"))

        if nested_override_dict:
            as_dict = merged(as_dict, nested_override_dict, MergeKey(raw="{<+}[<~]"))

        logger.debug(f"parsed all args passed to commandline prog: {raw_args}")
        logger.debug(f"nested args passed: {nested_args}")
        logger.debug(f"defined vars: {defined_vars}")
        logger.debug(f"final dict before pydantic validation:\n{as_dict}\n")

        try:
            res = self.conf_type.model_validate(as_dict)

            real_name_map = {arg.real_name: arg for arg in self._args}
            for field_name, field in self.conf_type.model_fields.items():
                if field_name in real_name_map:
                    arg = real_name_map[field_name]
                    if arg.resolvable:
                        current_value = getattr(res, field_name)
                        if not isinstance(current_value, DeferredNode):
                            # ensure loader context is attached if available
                            loader_context = loader.context if loader else None
                            setattr(
                                res,
                                field_name,
                                DeferredNode(
                                    value=current_value, loader=loader, context=loader_context
                                ),
                            )

            resolve_all_lazy(res)
            if not isinstance(res, self.conf_type):
                raise ArgParseError(f"expected {self.conf_type} but got {type(res)}")
            return res
        except ValidationError as e:
            print()
            for error in e.errors():
                loc_str = '.'.join(map(str, error['loc'])) if error['loc'] else 'root'
                print(f"error: field '{loc_str}': {error['msg']} (type: {error['type']})")
                if 'input' in error and isinstance(error['input'], (str, int, float, bool)):
                    print(f"  input value: {repr(error['input'])}")
                elif 'input' in error:
                    print(f"  input type: {type(error['input']).__name__}")
            print()

            print_help(self, None)
            sys.exit(2)  # command line usage errors


def make_program(conf_type: type, **kwargs):
    if not issubclass(conf_type, BaseModel):
        raise ValueError("make_program requires a BaseModel subclass")
    return Program[conf_type](conf_type=conf_type, **kwargs)
