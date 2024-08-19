import argparse
from pydantic import BaseModel, Field
from dracon import DraconLoader, with_indent
from dracon.composer import DRACON_UNSET_VALUE
from typing import Optional, Annotated, Any, TypeVar, Generic

B = TypeVar("B", bound=BaseModel)

class Arg:
    def __init__(
        self,
        real_name: Optional[str] = None,
        short: Optional[str] = None,
        long: Optional[str] = None,
        help: Optional[str] = None,
        arg_type: Optional[type] = None,
        expand_help: Optional[bool] = False,
    ):
        self.real_name = real_name
        self.short = short
        self.long = long
        self.help = help
        self.arg_type = arg_type
        self.expand_help = expand_help

    def merge(self, other):
        return Arg(
            real_name=self.real_name,
            short=self.short or other.short,
            long=self.long or other.long,
            help=self.help or other.help,
            arg_type=self.arg_type or other.arg_type,
            expand_help=self.expand_help or other.expand_help,
        )

    def help_str(self):
        names = []
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

    assert arg.real_name is not None
    return arg




class Program(BaseModel, Generic[B]):
    conf_type: type[B]

    name: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None

    class Config:
        extra = "allow"
        arbitrary_types_allowed = True

    def model_post_init(self, *args, **kwargs):
        super().model_post_init(*args, **kwargs)
        self._args = [getArg(name, f) for name, f in self.conf_type.model_fields.items()]
        self._arg_map = {}
        for arg in self._args:
            if arg.short:
                assert arg.short not in self._arg_map, f"Short arg {arg.short} already exists"
                self._arg_map[f'-{arg.short}'] = arg
            if arg.long:
                assert arg.long not in self._arg_map, f"Long arg {arg.long} already exists"
                self._arg_map[f'--{arg.long}'] = arg

    def print_help(self):
        print(f"Usage: {self.name} [options]")
        print("Options:")
        for arg in self._args:
            print(with_indent(arg.help_str(), 2))

    def print_error(self, arg):
        print(f"Error: unknown argument {arg}")
        self.print_help()
        raise ValueError(f"Unknown argument {arg}")

    def parse_args(self, argv: list[str]) -> B:
        args = {}
        i = 0

        def read_value(argstr, i):
            i += 1
            if i >= len(argv) or argv[i].startswith('-'):
                raise ValueError(f"Expected value for argument {argstr}")
            return argv[i], i + 1

        while i < len(argv):
            argstr = argv[i]
            if argstr in self._arg_map:
                arg_obj = self._arg_map[argstr]
                if arg_obj.arg_type is bool:
                    args[arg_obj.real_name] = True
                    i += 1
                    continue
            assert argstr.startswith('--'), f"Expected argument {argstr} to start with --"
            v, i = read_value(argstr, i)
            args[argstr] = v

        return self.generate_config(args)

    def generate_config(self, args: dict[str, str]) -> B:
        def make_override(argname, value):
            argname = argname.lstrip('-')
            if '@' in argname:
                return f"<<{argname}: {value}"
            return f"<<@{argname}: {value}"

        override_str = "\n".join([make_override(k, v) for k, v in args.items()])
        custom_types = {self.conf_type.__name__: self.conf_type}
        loader = DraconLoader(custom_types=custom_types)
        loader.yaml.representer.full_module_path = False

        empty_model = self.conf_type.model_construct()
        for field_name, field in self.conf_type.model_fields.items():
            # If the field is missing in the instance, set it to "???"
            if not hasattr(empty_model, field_name):
                setattr(empty_model, field_name, DRACON_UNSET_VALUE)

        dmp = loader.dump(empty_model)
        dmp += '\n' + override_str
        return loader.loads(dmp)


def make_program(conf_type: type, **kwargs):
    if not issubclass(conf_type, BaseModel):
        raise ValueError("make_program requires a BaseModel subclass")
    return Program[conf_type](conf_type=conf_type, **kwargs)



# ideal usage and syntax:

# class MyConfig(BaseModel):
    # required: int
    # a: int = 0
    # b: str = "default"
    # c: Annotated[bool, Arg(short="c", help="A flag")] = False
    # nested: NestedConfig = Field(default_factory=NestedConfig)


# MyConfig.model_construct().model_dump()

# def print_fields(cls):
    # for name, f in cls.model_fields.items():
        # print(name, f)


# print_fields(MyConfig)

# prg = make_program(MyConfig, name="testprog", version="0.1", description="A test program")

# # prg.print_help()

# obj = prg.parse_args(["--nested.a", "5", "--b", "config.yaml", "-c", "--required", "10"])
