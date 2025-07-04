import sys
from typing import Annotated

from pydantic import BaseModel
from dracon import Arg, make_program, DraconLoader, resolve_all_lazy, dump
import logging
from rich.logging import RichHandler


logging.basicConfig(
    level="NOTSET",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)

log = logging.getLogger("dracon-print")


class PrintConfig(BaseModel):
    config_file: Annotated[
        str,
        Arg(
            short="f",
            long="file",
            help="Path to the configuration file",
        ),
    ]

    construct_config: Annotated[
        bool,
        Arg(
            short="c",
            long='construct',
            help="Fully construct configuration into an object instead of showing the config graph",
        ),
    ] = False

    resolve: Annotated[
        bool,
        Arg(short="r", help="Resolve all interpolable nodes and values"),
    ] = False

    str_output: Annotated[
        bool,
        Arg(
            help="Output the configuration in raw string format instead of YAML.",
        ),
    ] = False

    def run(self):
        loader = DraconLoader()
        res = None
        try:
            if not self.construct_config:
                cr = loader.compose(self.config_file)
                res = cr.root
            else:
                res = loader.load(self.config_file)
        except Exception as e:
            log.error(f"Failed to load configuration file: {e}")
            log.exception(e)
            sys.exit(1)

        if self.resolve:
            try:
                resolve_all_lazy(res)
            except Exception as e:
                log.error(f"Failed to resolve all lazy nodes: {e}")
                log.exception(e)
                sys.exit(1)

        if self.raw_output:
            print(str(res))
        else:
            output = dump(res, loader=loader)
            print(output)


def main():
    program = make_program(
        PrintConfig,
        name="dracon-print",
        description=("Debugging tool to print a configuration file."),
    )

    config, raw_args = program.parse_args(sys.argv[1:])
    config.run()


if __name__ == "__main__":
    main()
