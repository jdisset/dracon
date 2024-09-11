import argparse
from pydantic import BaseModel, Field, ValidationError
from typing import List, Dict, Any
from dracon import DraconLoader, with_indent
from dracon.composer import DRACON_UNSET_VALUE
from dracon.utils import node_print
from typing import Optional, Annotated, Any, TypeVar, Generic, Callable, ForwardRef
from dracon.resolvable import Resolvable, get_inner_type
from dracon.keypath import KeyPath
from dracon.loader import DEFAULT_LOADERS
import logging
import traceback

B = TypeVar("B", bound=BaseModel)

ProgramType = ForwardRef("Program")

logger = logging.getLogger("dracon.commandline")


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

    def help_str(self):
        names = []
        if self.positional:
            return f"{self.real_name.upper()}: {self.help}"
        if self.short:
            names.append(f"-{self.short}")
        if self.long:
            names.append(f"--{self.long}")
        return f"{', '.join(names)}: {self.help}"


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


def print_help(prg, _):
    print(f"Usage: {prg.name} [options]")
    print("Options:")
    for arg in prg._args:
        print(with_indent(arg.help_str(), 2))


T = TypeVar("T")


class ArgParseError(Exception):
    pass


class Program(BaseModel, Generic[T]):
    conf_type: type[T]

    name: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None

    class Config:
        extra = "allow"
        arbitrary_types_allowed = True

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

    def parse_args(self, argv: List[str]) -> tuple[Optional[T], Dict[str, Any]]:
        self._positionals = [arg for arg in self._args if arg.positional]
        self._positionals.reverse()
        self._arg_map = {f'-{arg.short}': arg for arg in self._args if arg.short} | {
            f'--{arg.long}': arg for arg in self._args if arg.long
        }

        args, defined_vars, actions, confs_to_merge = {}, {}, [], []

        i = 0
        while i < len(argv):
            i = self._parse_single_arg(argv, i, args, defined_vars, actions, confs_to_merge)

        conf = self.generate_config(args, defined_vars, confs_to_merge)
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

        if argstr.startswith('--define.'): # a define statement
            return self._handle_define(argv, i, defined_vars)

        elif argstr.startswith('+'): # conf merge
            confs_to_merge.append(argv[i][1:])
            return i + 1

        elif not argstr.startswith('-'): # positional argument
            return self._handle_positional(argv, i, args)

        else: # regular optionnal argument
            return self._handle_option(argv, i, args, actions)

    def _handle_define(self, argv: List[str], i: int, defined_vars: Dict) -> int:
        var_name = argv[i][9:]
        var_value, i = self._read_value(argv, i)
        defined_vars[f'${var_name}'] = var_value
        return i


    def _handle_positional(self, argv: List[str], i: int, args: Dict) -> int:
        if not self._positionals:
            raise ArgParseError(f"Unexpected positional argument {argv[i]}")
        arg_obj = self._positionals.pop()
        args[arg_obj.real_name] = argv[i]
        return i + 1

    def _handle_option(self, argv: List[str], i: int, args: Dict, actions: List) -> int:
        argstr = argv[i]
        if argstr not in self._arg_map:
            raise ArgParseError(f"Unknown argument {argstr}")

        arg_obj = self._arg_map[argstr]

        if arg_obj.action is not None:
            actions.append(arg_obj.action)
            return i + 1

        if arg_obj.arg_type is bool:
            args[arg_obj.real_name] = True
            return i + 1

        modifier = lambda x: f"*file:{x}" if arg_obj.is_file else lambda x: x
        v, i = self._read_value(argv, i)
        args[arg_obj.real_name] = modifier(v)
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
            # key = f"<<{DEFAULT_MERGE_ARGS}"
            # if starts with any of DEFAULT_LOADERS.keys(), assume it's a loader
            if conf.startswith(tuple(DEFAULT_LOADERS.keys())):
                yield f"{key}: !include \"{conf}\""
            else:  # assume it's a file
                yield f"{key}: !include \"file:{conf}\""

    def generate_config(
        self, args: dict[str, str], defined_vars: dict[str, str], confs_to_merge: list[str]
    ) -> Optional[T]:
        def make_override(argname, value):
            argname = argname.lstrip('-')
            if '@' in argname:
                return f"<<{argname}: {value}"
            return f"<<@{argname}: {value}"

        override_str = "\n".join([make_override(k, v) for k, v in args.items()])
        custom_types = {self.conf_type.__name__: self.conf_type}
        loader = DraconLoader(
            custom_types=custom_types,
            enable_interpolation=True,
            base_list_type=list,
            base_dict_type=dict,
        )
        # loader.yaml.representer.full_module_path = False

        empty_model = self.conf_type.model_construct()

        for field_name, field in self.conf_type.model_fields.items():
            # If the field is missing in the instance, set it to "???"
            if not hasattr(empty_model, field_name):
                setattr(empty_model, field_name, DRACON_UNSET_VALUE)

        dmp = loader.dump(empty_model)

        merge_str = "\n".join(list(self.make_merge_str(confs_to_merge)))
        if merge_str:
            dmp += '\n' + merge_str
        dmp += '\n' + override_str

        logger.debug(f"Parsed all args passed to commandline prog: {args}")
        logger.debug(f"Defined vars: {defined_vars}")
        logger.debug(f"Going to parse generated config:\n{dmp}\n")

        try:
            loader.reset_context()
            loader.update_context(defined_vars)
            comp = loader.compose_config_from_str(dmp)
            logger.debug(f"Composition result: {comp}")

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

            return loader.load_from_composition_result(comp)
        except ValidationError as e:
            # Intercept the validation error
            print()
            for error in e.errors():
                if error['type'] == 'missing':
                    print(f"Error: '{error['loc'][0]}' is required but was not provided.")
                else:
                    print(f"Validation Error: {error['loc'][0]} - {error['msg']}")
            print_help(self, None)
            print()
        except Exception as e:
            print(f"Error: {e}")
            print(traceback.format_exc())


def make_program(conf_type: type, **kwargs):
    if not issubclass(conf_type, BaseModel):
        raise ValueError("make_program requires a BaseModel subclass")
    return Program[conf_type](conf_type=conf_type, **kwargs)
