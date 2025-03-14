from pydantic import BaseModel, ValidationError, ConfigDict
from pydantic_core import PydanticUndefined
from typing import List, Dict, Any
from dracon import DraconLoader
from dracon.composer import DRACON_UNSET_VALUE
import sys
from rich.console import Console
from rich.box import ROUNDED
from rich.text import Text
from rich.panel import Panel
from typing import (
    Optional,
    Annotated,
    Any,
    TypeVar,
    Generic,
    Callable,
    ForwardRef,
    Union,
)
from dracon.lazy import resolve_all_lazy
from dracon.resolvable import Resolvable, get_inner_type
from dracon.deferred import DeferredNode
from dracon.keypath import KeyPath
from dracon.loader import DEFAULT_LOADERS
import traceback
import logging


logger = logging.getLogger(__name__)

B = TypeVar("B", bound=BaseModel)

ProgramType = ForwardRef("Program")


class Arg:
    def __init__(
        self,
        real_name: Optional[str] = None,
        short: Optional[str] = None,
        long: Optional[str] = None,
        help: Optional[str] = None,
        arg_type: Optional[type] = None,
        expand_help: Optional[bool] = False,
        action: Optional[Callable[[ProgramType, Any], Any]] = None,
        positional: Optional[bool] = False,
        resolvable: Optional[bool] = False,
        is_file: Optional[bool] = False,
    ):
        self.real_name = real_name
        self.short = short
        self.long = long
        self.help = help
        self.arg_type = arg_type
        self.expand_help = expand_help
        self.action = action
        self.positional = positional
        self.resolvable = resolvable
        self.is_file = is_file

    def merge(self, other):
        arg = Arg(
            real_name=self.real_name,
            short=self.short if self.short else other.short,
            long=self.long if self.long else other.long,
            help=self.help if self.help else other.help,
            arg_type=self.arg_type if self.arg_type else other.arg_type,
            action=self.action if self.action else other.action,
            positional=self.positional if self.positional else other.positional,
            resolvable=self.resolvable if self.resolvable else other.resolvable,
            is_file=self.is_file if self.is_file else other.is_file,
        )
        return arg


def getArg(name, field):
    arg = Arg(real_name=name)
    for m in field.metadata:
        if isinstance(m, Arg):
            arg = arg.merge(m)

    if not arg.long:
        arg.long = name

    if not arg.arg_type:
        arg.arg_type = field.annotation

    if arg.arg_type is Resolvable:
        arg.resolvable = True

    assert arg.real_name is not None
    return arg


T = TypeVar("T")


## {{{                        --     print help     --

console = Console()


def format_type_str(arg_type: type) -> str:
    if arg_type is None:
        return ""
    if hasattr(arg_type, "__origin__"):
        if (
            arg_type.__origin__ is Annotated
            or arg_type.__origin__ is Resolvable
            or arg_type.__origin__ is DeferredNode
        ):
            return format_type_str(arg_type.__args__[0])
        elif arg_type.__origin__ is Union:
            types = [t for t in arg_type.__args__ if t is not type(None)]
            if len(types) == 1:
                return format_type_str(types[0])
            return arg_type.__origin__.__name__.upper()
        return format_type_str(arg_type.__args__[0])
    return arg_type.__name__.upper()


def format_default_value(value: Any) -> str:
    if value is PydanticUndefined:
        return None
    if isinstance(value, str):
        return f'"{value}"'
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
            elif default:
                content.append("    default: ", style="bright_black")
                content.append(f"{default}\n", style="dim")
            if help_text:
                content.append(f"    {help_text}\n", style="default")
            content.append("\n")

    if options or flags:
        content.append("Options:\n", style="bold green")
        for arg in options + flags:
            parts = []
            if arg.short:
                parts.append(f"-{arg.short}")
            if arg.long:
                parts.append(f"--{arg.long}")

            option_str = ", ".join(parts)
            if not arg.arg_type is bool:
                name = option_str
                type_str = format_type_str(arg.arg_type)
                format_type_display(name, type_str, content)
            else:
                content.append(f"  {option_str}\n", style="yellow")

            help_text = arg.help or ""
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

            if help_text:
                content.append(f"    {help_text}\n")
            if required:
                content.append("    REQUIRED\n", style="red")
            elif default:
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

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    def model_post_init(self, *args, **kwargs):
        super().model_post_init(*args, **kwargs)
        self._args = [getArg(name, f) for name, f in self.conf_type.model_fields.items()]
        self._args.append(
            Arg(
                real_name="help",
                short="h",
                long="help",
                help="Print this help message",
                action=print_help,
            )
        )

    def parse_args(self, argv: List[str], **kwargs) -> tuple[Optional[T], Dict[str, Any]]:
        self._positionals = [arg for arg in self._args if arg.positional]
        self._positionals.reverse()
        self._arg_map = {f'-{arg.short}': arg for arg in self._args if arg.short} | {
            f'--{arg.long}': arg for arg in self._args if arg.long
        }

        logger.debug(f"Positional args: {self._positionals}")
        logger.debug(f"Arg map: {self._arg_map}")
        logger.debug(f"Args: {self._args}")

        args, defined_vars, actions, confs_to_merge = {}, {}, [], []

        i = 0
        while i < len(argv):
            i = self._parse_single_arg(argv, i, args, defined_vars, actions, confs_to_merge)

        logger.debug(f"Defined vars: {defined_vars}")

        conf = self.generate_config(args, defined_vars, confs_to_merge, **kwargs)
        if conf is not None:
            for action in actions:
                action(self, conf)
        return conf, args

    def _parse_single_arg(
        self,
        argv: List[str],
        i: int,
        args: Dict,
        defined_vars: Dict,
        actions: List,
        confs_to_merge: List,
    ) -> int:
        argstr = argv[i]

        if argstr.startswith('--define.'):  # a define statement
            return self._handle_define(argv, i, defined_vars)

        elif argstr.startswith('+'):  # conf merge
            confs_to_merge.append(argv[i][1:])
            return i + 1

        elif not argstr.startswith('-'):  # positional argument
            return self._handle_positional(argv, i, args)

        else:  # regular optionnal argument
            return self._handle_option(argv, i, args, actions)

    def _handle_define(self, argv: List[str], i: int, defined_vars: Dict) -> int:
        var_name = argv[i][9:]
        var_value, i = self._read_value(argv, i)
        defined_vars[var_name] = var_value
        return i

    def _handle_positional(self, argv: List[str], i: int, args: Dict) -> int:
        if not self._positionals:
            raise ArgParseError(f"Unexpected positional argument {argv[i]}")
        arg_obj = self._positionals.pop()
        args[arg_obj.real_name] = argv[i]
        return i + 1

    def _handle_option(self, argv: List[str], i: int, args: Dict, actions: List) -> int:
        logger.debug(f"Handling option {argv[i]}")
        argstr = argv[i]
        if argstr not in self._arg_map:
            raise ArgParseError(f"Unknown argument {argstr}")

        arg_obj = self._arg_map[argstr]

        if arg_obj.action is not None:
            actions.append(arg_obj.action)
            logger.debug(f"Adding action {arg_obj.action} to the list of actions")
            return i + 1

        if arg_obj.arg_type is bool:
            args[arg_obj.real_name] = True
            logger.debug(f"Setting {arg_obj.real_name} to True")
            return i + 1

        modifier = (lambda x: f"*file:{x}") if arg_obj.is_file else (lambda x: x)
        v, i = self._read_value(argv, i)
        modified_v = modifier(v)
        args[arg_obj.real_name] = modified_v
        logger.debug(f"Setting {arg_obj.real_name} to {modified_v}")
        return i

    def _read_value(self, argv: List[str], i: int) -> tuple[str, int]:
        i += 1
        if i >= len(argv) or argv[i].startswith('-'):
            raise ArgParseError(f"Expected value for argument {argv[i-1]}")
        return argv[i], i + 1

    def make_merge_str(self, confs_to_merge):
        DEFAULT_MERGE_ARGS = "{~<}[~<]"
        for i, conf in enumerate(confs_to_merge):
            key = f"<<{DEFAULT_MERGE_ARGS}_merge{i}"
            if conf.startswith(tuple(DEFAULT_LOADERS.keys())):
                yield f"{key}: !include \"{conf}\""
            else:  # assume it's a file
                yield f"{key}: !include \"file:{conf}\""

    def generate_config(
        self,
        args: dict[str, str],
        defined_vars: dict[str, str],
        confs_to_merge: list[str],
        **kwargs,
    ) -> Optional[T]:
        def make_override(argname, value):
            argname = argname.lstrip('-')
            if '@' in argname:
                return f"<<{argname}: {value}"
            return f"<<@{argname}: {value}"

        override_str = "\n".join([make_override(k, v) for k, v in args.items()])
        loader = DraconLoader(
            enable_interpolation=True,
            base_dict_type=dict,
            base_list_type=list,
            **kwargs,
        )
        loader.update_context(defined_vars)

        empty_model = self.conf_type.model_construct()

        as_dict = empty_model.model_dump()

        for field_name, field in self.conf_type.model_fields.items():
            if not hasattr(empty_model, field_name):
                as_dict[field_name] = DRACON_UNSET_VALUE

        dmp = loader.dump(as_dict)

        merge_str = "\n".join(list(self.make_merge_str(confs_to_merge)))

        if merge_str:
            dmp += '\n' + merge_str
        dmp += '\n' + override_str

        logger.debug(f"Parsed all args passed to commandline prog: {args}")
        logger.debug(f"Defined vars: {defined_vars}")
        logger.debug(f"Going to parse generated config:\n{dmp}\n")

        try:
            comp = loader.compose_config_from_str(dmp)
            real_name_map = {arg.real_name: arg for arg in self._args}
            # then we wrap all resolvable args in a !Resolvable[...] tag
            for field_name, field in self.conf_type.model_fields.items():
                if field_name in real_name_map:
                    arg = real_name_map[field_name]
                    if arg.resolvable:
                        field_t = get_inner_type(field.annotation)
                        if field_t is Any:
                            field_t = field.annotation
                        field_path = KeyPath(f'/{field_name}')
                        resolvable_node = field_path.get_obj(comp.root)
                        new_tag = f"!Resolvable[{field_t.__name__}]"
                        resolvable_node.tag = new_tag

            res = loader.load_composition_result(comp)
            resolve_all_lazy(res)
            res = self.conf_type(**res)
            if not isinstance(res, self.conf_type):
                raise ArgParseError(f"Expected {self.conf_type} but got {type(res)}")
            return res
        except ValidationError as e:
            # Intercept the validation error
            print()
            for error in e.errors():
                if error['type'] == 'missing':
                    print(f"Error: '{error['loc'][0]}' is required but was not provided.")
                else:
                    print(f"Validation Error: {error['loc']} - {error['msg']} - {error['type']}")
                    if 'ctx' in error:
                        print(f"Context: {error['ctx']}")
            print()

            print_help(self, None)
            print()


def make_program(conf_type: type, **kwargs):
    if not issubclass(conf_type, BaseModel):
        raise ValueError("make_program requires a BaseModel subclass")
    return Program[conf_type](conf_type=conf_type, **kwargs)
