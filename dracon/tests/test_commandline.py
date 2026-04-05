import pytest
import sys
from pathlib import Path
from pydantic import (
    BaseModel,
    Field,
    AfterValidator,
    BeforeValidator,
    PlainValidator,
    WrapValidator,
    ValidationError,
)
from typing import Annotated, Optional, List, Literal, Union, Dict, Any, Tuple, Set, get_args, get_origin
import subprocess
import os
from datetime import datetime

from dracon import Arg, DeferredNode, construct, DraconLoader, make_program, DraconError
from dracon.commandline import ArgParseError
from dracon.loader import dump_to_node
from dracon.lazy import LazyDraconModel
from dracon import CompositionResult, DraconMappingNode, resolve_all_lazy


class DatabaseConfig(BaseModel):
    host: str
    port: int = 5432
    username: str
    password: str


class AppConfig(BaseModel):
    environment: Annotated[str, Arg(short='e', help="Deployment environment (dev, staging, prod).")]
    log_level: Annotated[str, Arg(help="Logging level.")] = "INFO"
    workers: Annotated[int, Arg(help="Number of worker processes.")] = 1
    database: Annotated[DatabaseConfig, Arg(help="Database configuration.")]
    output_path: Annotated[DeferredNode[str], Arg(help="Path for output files.")] = "default_output"
    float_var: Annotated[float, Arg(help="A float variable.")] = 0.0

    def run(self):
        print("----- AppConfig.run() starting -----")
        print(f"Running in {self.environment} mode with {self.workers} workers.")
        db_path = self.get_base_path_from_db()
        print(f"got base path from db: {db_path}")
        print(f"constructing output_path: {self.output_path}")
        constructed_output = construct(self.output_path, context={'base_output_path': db_path})
        print(f"constructed output path: {constructed_output}")
        print("----- AppConfig.run() finished -----")
        return constructed_output

    def get_base_path_from_db(self):
        print("... simulating db fetch for base path ...")
        return f"{self.database.host}_{self.database.port}"


class AnyTypeApp(BaseModel):
    value: Annotated[Any, Arg(help="An argument of any type.")]


class NestedForFile(BaseModel):
    value_from_file: int


class FileArgConfig(BaseModel):
    # test is_file=true with a nested model
    nested_conf: Annotated[NestedForFile, Arg(is_file=True, help="load nested config from file.")]
    # test is_file=true with a deferred node (simple type)
    deferred_nested: Annotated[
        DeferredNode[NestedForFile],
        Arg(is_file=True, help="load deferred nested config from file."),
    ]
    # test explicit '+' with a deferred node (model type)
    deferred_db_explicit: Annotated[DeferredNode[DatabaseConfig], Arg(help="deferred db via +file")]
    # test implicit (is_file) with a deferred node (model type)
    deferred_db_implicit: Annotated[
        DeferredNode[DatabaseConfig], Arg(is_file=True, help="deferred db via is_file")
    ]
    # required field for validation
    required_field: str


class NestedListConfig(BaseModel):
    items: List[str] = ["itemA", "itemB"]


class ComplexCliConfig(BaseModel):
    input_file: Annotated[
        str, Arg(positional=True, help="The primary input data file.")
    ]  # first positional
    output_dir: Annotated[
        str, Arg(positional=True, help="Directory for output results.")
    ]  # second positional
    verbose: Annotated[bool, Arg(short='v', help="Enable verbose logging.")] = False
    tags: Annotated[List[str], Arg(help="List of tags to apply.")] = ["default1"]
    nested_list: NestedListConfig = Field(default_factory=NestedListConfig)
    optional_pos: Annotated[
        Optional[str], Arg(positional=True, help="Optional positional arg.")
    ] = None


# --- fixtures ---


@pytest.fixture(scope="module")
def config_files(tmp_path_factory):
    """create dummy config files for testing"""
    tmp_path = tmp_path_factory.mktemp("cmd_configs")
    print(f"creating config files in: {tmp_path}")

    # --- localconf.yaml ---
    local_content = """
environment: local
log_level: DEBUG
workers: 2
database:
  host: db.local
  username: local_user
  password: local_password
output_path: /data/local_output/${base_output_path}
float_var: 3.14
"""
    (tmp_path / "localconf.yaml").write_text(local_content)
    print("created localconf.yaml")

    # --- dev.yaml ---
    dev_content = """
environment: dev
log_level: INFO
database:
  host: db.dev
  port: 5432
  username: dev_user
  password: dev_password
output_path: /data/dev_output/${base_output_path}
"""
    (tmp_path / "dev.yaml").write_text(dev_content)
    print("created dev.yaml")

    # --- db_prod.yaml ---
    db_prod_content = """
database:
  host: db.prod.override
  port: 6000
  username: prod_user
  password: prod_password
"""
    (tmp_path / "db_prod.yaml").write_text(db_prod_content)
    print("created db_prod.yaml")

    # --- prod.yaml ---
    prod_content = """
workers: 8
database:
  host: db.prod.main
  port: 5432
"""
    (tmp_path / "prod.yaml").write_text(prod_content)
    print("created prod.yaml")

    # --- context_var_test.yaml ---
    context_var_content = """
workers: ${my_var}
environment: ctx_test
database:
    host: ctx_host
    username: ctx_user
    password: ctx_password
output_path: /tmp/ctx_output
"""
    (tmp_path / "context_var_test.yaml").write_text(context_var_content)
    print("created context_var_test.yaml")

    # --- pkg structure (simulated) ---
    pkg_dir = tmp_path / "mypackage" / "configs"
    pkg_dir.mkdir(parents=True)
    pkg_default_content = """
log_level: WARNING
database:
    host: pkg.default.host
    username: pkg_default
    password: pkg_default_pass
"""
    (pkg_dir / "default.yaml").write_text(pkg_default_content)
    print(f"created package structure at: {tmp_path / 'mypackage'}")
    # add pkg_dir to sys.path for pkg: loader simulation
    sys.path.insert(0, str(tmp_path))

    # --- files for is_file / deferred tests ---
    nested_override_content = "value_from_file: 99"
    (tmp_path / "nested_override.yaml").write_text(nested_override_content)
    print("created nested_override.yaml")

    deferred_path_content = "/explicit/path/from/file"
    (tmp_path / "deferred_path_content.txt").write_text(deferred_path_content)
    print("created deferred_path_content.txt")

    deferred_db_content = """
host: deferred_host
port: 1234
username: deferred_user
password: deferred_pass
"""
    (tmp_path / "deferred_db_content.yaml").write_text(deferred_db_content)
    print("created deferred_db_content.yaml")

    # --- file for complex cli tests ---
    complex_cli_content = """
verbose: true
tags:
  - from_file1
  - from_file2
nested_list:
  items:
    - item_file_A
    - item_file_B
"""
    (tmp_path / "complex_cli.yaml").write_text(complex_cli_content)
    print("created complex_cli.yaml")

    # dummy files for required args
    (tmp_path / "dummy_path.txt").touch()
    (tmp_path / "dummy_db.yaml").write_text("host: dummy\nusername: dummy\npassword: dummy")
    (tmp_path / "dummy_nested.yaml").write_text("value_from_file: 0")

    yield tmp_path

    # clean up sys.path
    sys.path.pop(0)
    print(f"cleaned up tmp path: {tmp_path}")


@pytest.fixture
def program():
    """create the dracon program instance for AppConfig"""
    print("creating Program instance for AppConfig...")
    prog = make_program(
        AppConfig,
        name="simple-app",
        description="My cool application.",
        context={
            'DatabaseConfig': DatabaseConfig,
            'AppConfig': AppConfig,  # add appconfig too if needed by includes/tags
        },
    )
    print("program instance created.")
    return prog


@pytest.fixture
def anythingprogram():
    prog = make_program(
        AnyTypeApp,
        name="any-app",
        context={},
    )
    return prog


@pytest.fixture
def file_arg_program():
    """create the dracon program instance for FileArgConfig"""
    print("creating Program instance for FileArgConfig...")
    prog = make_program(
        FileArgConfig,
        name="file-arg-app",
        description="app for testing file args",
        context={
            'DatabaseConfig': DatabaseConfig,
            'NestedForFile': NestedForFile,
            'FileArgConfig': FileArgConfig,
        },
    )
    print("program instance created.")
    return prog


@pytest.fixture
def complex_program():
    """create the dracon program instance for ComplexCliConfig"""
    print("creating Program instance for ComplexCliConfig...")
    prog = make_program(
        ComplexCliConfig,
        name="complex-cli-app",
        description="app for testing complex cli features",
        context={
            'NestedListConfig': NestedListConfig,
            'ComplexCliConfig': ComplexCliConfig,
        },
    )
    print("program instance created.")
    return prog


def test_cli_help(program, capfd):
    """scenario 1: print help"""
    print("\n--- test_cli_help ---")
    with pytest.raises(SystemExit) as e:
        print("parsing ['--help']...")
        program.parse_args(["--help"])
    assert e.value.code == 0
    captured = capfd.readouterr()
    print(f"captured help output:\n{captured.out}")
    assert "Usage: simple-app [OPTIONS]" in captured.out
    assert "Deployment environment" in captured.out
    assert "--output-path" in captured.out
    assert "--database" in captured.out


def test_base_config_overrides(program, config_files):
    """scenario 2: use a base config file, override some values"""
    print("\n--- test_base_config_overrides ---")
    local_conf = config_files / "localconf.yaml"
    args = [
        f"+{local_conf}",
        "-e",
        "dev",  # override environment
        "--workers",
        "4",  # override workers
        "--database.port",
        "5433",  # override nested value
        "--float-var",
        "42.14",  # override float var
    ]
    print(f"parsing args: {args}")
    config, raw_args = program.parse_args(args)
    print(f"parsed config: {config}")
    print(f"raw args dict: {raw_args}")

    assert isinstance(config, AppConfig)
    assert config.environment == "dev"  # overridden by cli
    assert config.log_level == "DEBUG"  # from localconf.yaml
    assert config.workers == 4  # overridden by cli
    assert config.database.host == "db.local"  # from localconf.yaml
    assert config.database.port == 5433  # overridden by cli
    assert config.database.username == "local_user"  # from localconf.yaml
    assert config.database.password == "local_password"  # from localconf.yaml
    assert config.float_var == 42.14
    assert isinstance(config.output_path, DeferredNode)
    print(f"output_path before run: {config.output_path}")

    # test deferred construction
    print("calling config.run()...")
    output = config.run()
    print(f"config.run() returned: {output}")
    assert output == "/data/local_output/db.local_5433"


def test_cli_only(program):
    """scenario 3: no config file, just cli args"""
    print("\n--- test_cli_only ---")
    args = [
        "-e",
        "cli_env",
        "--database.host",
        "cli_host",
        "--database.username",
        "cli_user",
        "--database.password",
        "cli_pass",
        "--output-path",
        "/tmp/cli_output/${base_output_path}",
        "--workers",
        "5",
    ]
    print(f"parsing args: {args}")
    config, raw_args = program.parse_args(args)
    print(f"parsed config: {config}")
    print(f"raw args dict: {raw_args}")

    assert isinstance(config, AppConfig)
    assert config.environment == "cli_env"
    assert config.log_level == "INFO"  # default
    assert config.workers == 5
    assert config.database.host == "cli_host"
    assert config.database.port == 5432  # default
    assert config.database.username == "cli_user"
    assert config.database.password == "cli_pass"
    assert isinstance(config.output_path, DeferredNode)
    print(f"output_path before run: {config.output_path}")
    print(f"output_path node value: {config.output_path.value}")

    # test deferred construction
    print("calling config.run()...")
    output = config.run()
    print(f"config.run() returned: {output}")
    assert output == "/tmp/cli_output/cli_host_5432"


def test_merge_files(program, config_files):
    """scenario 4: merge config files (pkg and fs)"""
    print("\n--- test_merge_files ---")
    dev_conf = config_files / "dev.yaml"
    # order: pkg default -> dev.yaml
    args = [
        "+pkg:mypackage:configs/default",  # loads pkg default first
        f"+{dev_conf}",  # merges dev.yaml onto it
    ]
    print(f"parsing args: {args}")
    config, raw_args = program.parse_args(args)
    print(f"parsed config: {config}")
    print(f"raw args dict: {raw_args}")

    assert isinstance(config, AppConfig)
    assert config.environment == "dev"  # from dev.yaml (new wins)
    assert config.log_level == "INFO"  # from dev.yaml (new wins)
    assert config.workers == 1  # default (not in files)
    assert config.database.host == "db.dev"  # from dev.yaml (new wins)
    assert config.database.port == 5432  # from dev.yaml (new wins)
    assert config.database.username == "dev_user"  # from dev.yaml (new wins)
    assert config.database.password == "dev_password"  # from dev.yaml (new wins)
    assert isinstance(config.output_path, DeferredNode)
    print(f"output_path before run: {config.output_path}")

    # test deferred construction
    print("calling config.run()...")
    output = config.run()
    print(f"config.run() returned: {output}")
    assert output == "/data/dev_output/db.dev_5432"


def test_sub_arg_override_file(program, config_files):
    """scenario 5: override sub-arg with a file"""
    print("\n--- test_sub_arg_override_file ---")
    dev_conf = config_files / "dev.yaml"
    db_prod_conf = config_files / "db_prod.yaml"
    args = [
        f"+{dev_conf}",
        f"--database",  # use the parent argument name
        f"+{db_prod_conf}@database",  # override entire database section
    ]
    print(f"parsing args: {args}")
    config, raw_args = program.parse_args(args)
    print(f"parsed config: {config}")
    print(f"raw args dict: {raw_args}")

    assert isinstance(config, AppConfig)
    assert config.environment == "dev"  # from dev.yaml
    assert config.log_level == "INFO"  # from dev.yaml
    assert config.workers == 1  # default
    # database section completely replaced by db_prod.yaml
    assert config.database.host == "db.prod.override"
    assert config.database.port == 6000
    assert config.database.username == "prod_user"
    assert config.database.password == "prod_password"
    assert isinstance(config.output_path, DeferredNode)
    print(f"output_path before run: {config.output_path}")

    # test deferred construction
    print("calling config.run()...")
    output = config.run()
    print(f"config.run() returned: {output}")
    # uses db_prod path logic because output_path is from dev.yaml but db is overridden
    assert output == "/data/dev_output/db.prod.override_6000"


def test_key_override_from_file(program, config_files):
    """scenario 6: use key from another config as override"""
    print("\n--- test_key_override_from_file ---")
    dev_conf = config_files / "dev.yaml"
    prod_conf = config_files / "prod.yaml"
    args = [
        f"+{dev_conf}",
        "--database.host",
        f"+{prod_conf}@database.host",  # override only host
    ]
    print(f"parsing args: {args}")
    config, raw_args = program.parse_args(args)
    print(f"parsed config: {config}")
    print(f"raw args dict: {raw_args}")

    assert isinstance(config, AppConfig)
    assert config.environment == "dev"  # from dev.yaml
    assert config.log_level == "INFO"  # from dev.yaml
    assert config.workers == 1  # default
    # only host overridden from prod.yaml
    assert config.database.host == "db.prod.main"
    assert config.database.port == 5432  # from dev.yaml
    assert config.database.username == "dev_user"  # from dev.yaml
    assert config.database.password == "dev_password"  # from dev.yaml
    assert isinstance(config.output_path, DeferredNode)
    print(f"output_path before run: {config.output_path}")

    # test deferred construction
    print("calling config.run()...")
    output = config.run()
    print(f"config.run() returned: {output}")
    assert output == "/data/dev_output/db.prod.main_5432"


def test_define_context_vars(program, config_files):
    """scenario 7: define context variables"""
    print("\n--- test_define_context_vars ---")
    context_conf = config_files / "context_var_test.yaml"
    args = [
        f"+{context_conf}",
        "--define.my_var",  # separate key
        "42",  # separate value
    ]
    print(f"parsing args: {args}")
    config, raw_args = program.parse_args(args)
    print(f"parsed config: {config}")
    print(f"raw args dict: {raw_args}")

    assert isinstance(config, AppConfig)
    assert config.environment == "ctx_test"  # from context_var_test.yaml
    assert config.log_level == "INFO"  # default
    assert config.workers == 42  # from context variable
    assert config.database.host == "ctx_host"  # from context_var_test.yaml
    assert config.database.username == "ctx_user"  # from context_var_test.yaml
    assert isinstance(config.output_path, DeferredNode)
    print(f"output_path before run: {config.output_path}")

    # test deferred construction
    print("calling config.run()...")
    output = config.run()
    print(f"config.run() returned: {output}")
    # output_path isn't interpolated in context_var_test.yaml
    assert output == "/tmp/ctx_output"


def test_plusplus_shorthand_define(program, config_files):
    """test ++ shorthand for defining context variables"""
    print("\n--- test_plusplus_shorthand_define ---")
    context_conf = config_files / "context_var_test.yaml"
    args = [
        f"+{context_conf}",
        "++my_var",  # shorthand syntax
        "42",  # value
    ]
    print(f"parsing args: {args}")
    config, raw_args = program.parse_args(args)
    print(f"parsed config: {config}")
    print(f"raw args dict: {raw_args}")

    assert isinstance(config, AppConfig)
    assert config.environment == "ctx_test"  # from context_var_test.yaml
    assert config.log_level == "INFO"  # default
    assert config.workers == 42  # from context variable
    assert config.database.host == "ctx_host"  # from context_var_test.yaml
    assert config.database.username == "ctx_user"  # from context_var_test.yaml
    assert isinstance(config.output_path, DeferredNode)
    print(f"output_path before run: {config.output_path}")

    # test deferred construction
    print("calling config.run()...")
    output = config.run()
    print(f"config.run() returned: {output}")
    # output_path isn't interpolated in context_var_test.yaml
    assert output == "/tmp/ctx_output"


def test_plusplus_multiple_defines(program, config_files):
    """test multiple ++ shorthand defines in combination with --define"""
    print("\n--- test_plusplus_multiple_defines ---")

    # create a config file that uses multiple context variables
    multi_var_content = """
workers: ${my_var}
environment: ${third_var}
database:
    host: ctx_host
    port: ${another_var}
    username: ctx_user
    password: ctx_password
output_path: /tmp/ctx_output
"""
    multi_var_file = config_files / "multi_var_test.yaml"
    multi_var_file.write_text(multi_var_content)

    args = [
        f"+{multi_var_file}",
        "++my_var",  # shorthand syntax
        "42",
        "--define.another_var",  # regular syntax
        "100",
        "++third_var",  # another shorthand
        "foo",
    ]
    print(f"parsing args: {args}")
    config, raw_args = program.parse_args(args)
    print(f"parsed config: {config}")
    print(f"raw args dict: {raw_args}")

    assert isinstance(config, AppConfig)
    assert config.workers == 42  # from ++my_var
    assert config.database.port == 100  # from --define.another_var
    assert config.environment == "foo"  # from ++third_var


def test_plusplus_list_defines(anythingprogram, config_files):
    anything_context = """
!set_default my_var: 42
value: 
    itsadict: hehe
    var: ${my_var}
"""
    anything_file = config_files / "anything_test.yaml"
    anything_file.write_text(anything_context)

    args = [
        f"+{anything_file}",
        "++my_var",
        "${[42, 1]}",
    ]

    print(f"parsing args: {args}")
    config, raw_args = anythingprogram.parse_args(args)
    print(f"parsed config: {config}")
    print(f"raw args dict: {raw_args}")

    assert config.value == {'itsadict': 'hehe', 'var': [42, 1]}


def test_define_equals_syntax(program, config_files):
    """test --define with equals syntax as documented"""
    print("\n--- test_define_equals_syntax ---")
    context_conf = config_files / "context_var_test.yaml"
    args = [
        f"+{context_conf}",
        "--define.my_var=42",  # equals syntax
    ]
    print(f"parsing args: {args}")
    config, raw_args = program.parse_args(args)
    print(f"parsed config: {config}")
    print(f"raw args dict: {raw_args}")

    assert isinstance(config, AppConfig)
    assert config.environment == "ctx_test"  # from context_var_test.yaml
    assert config.log_level == "INFO"  # default
    assert config.workers == 42  # from context variable
    assert config.database.host == "ctx_host"  # from context_var_test.yaml
    assert config.database.username == "ctx_user"  # from context_var_test.yaml


def test_plusplus_equals_syntax(program, config_files):
    """test ++ shorthand with equals syntax"""
    print("\n--- test_plusplus_equals_syntax ---")
    context_conf = config_files / "context_var_test.yaml"
    args = [
        f"+{context_conf}",
        "++my_var=42",  # shorthand with equals
    ]
    print(f"parsing args: {args}")
    config, raw_args = program.parse_args(args)
    print(f"parsed config: {config}")
    print(f"raw args dict: {raw_args}")

    assert isinstance(config, AppConfig)
    assert config.workers == 42  # from context variable


def test_required_args_missing(program, capfd):
    """test error handling when required args are missing"""
    print("\n--- test_required_args_missing ---")
    with pytest.raises(SystemExit):  # expecting sys.exit(0) after printing help
        print("parsing []...")
        program.parse_args([])  # missing environment and database fields

    captured = capfd.readouterr()
    print(f"captured stderr:\n{captured.err}")
    print(f"captured stdout:\n{captured.out}")
    # check for missing argument error messages in stdout
    assert "Arg 'environment' is missing" in captured.out
    assert "Arg 'database' is missing" in captured.out
    assert "Usage: simple-app [OPTIONS]" in captured.out  # help should be printed


def test_unknown_argument(program, capfd):
    """test error handling for unknown arguments"""
    print("\n--- test_unknown_argument ---")
    with pytest.raises(SystemExit):  # expect exit after printing help
        print("parsing ['--unknown-arg', 'value']...")
        program.parse_args(["--unknown-arg", "value"])

    captured = capfd.readouterr()
    print(f"captured stderr:\n{captured.err}")
    print(f"captured stdout:\n{captured.out}")
    # check stderr after stripping whitespace
    assert "Error: unknown argument --unknown-arg" in captured.err.strip()
    assert "Usage: simple-app [OPTIONS]" in captured.out  # help should be printed


def test_missing_value_for_option(program, capfd):
    """test error handling when an option expects a value but none is provided"""
    print("\n--- test_missing_value_for_option ---")
    with pytest.raises(SystemExit):  # expect exit after printing help
        print("parsing ['-e']...")
        program.parse_args(["-e"])  # missing value for environment

    captured = capfd.readouterr()
    print(f"captured stderr:\n{captured.err}")
    print(f"captured stdout:\n{captured.out}")
    # check stderr after stripping whitespace
    assert "Error: expected value for argument -e" in captured.err.strip()
    assert "Usage: simple-app [OPTIONS]" in captured.out  # help should be printed

    with pytest.raises(SystemExit):  # expect exit after printing help
        print("parsing ['--workers']...")
        program.parse_args(["--workers"])  # missing value for workers

    captured = capfd.readouterr()
    print(f"captured stderr:\n{captured.err}")
    print(f"captured stdout:\n{captured.out}")
    # check stderr after stripping whitespace
    assert "Error: expected value for argument --workers" in captured.err.strip()
    assert "Usage: simple-app [OPTIONS]" in captured.out  # help should be printed


def test_is_file_arg_nested(file_arg_program, config_files):
    """test Arg(is_file=True) correctly loads a file for a nested model."""
    print("\n--- test_is_file_arg_nested ---")
    nested_file = config_files / "nested_override.yaml"
    dummy_path = config_files / "dummy_path.txt"
    dummy_db = config_files / "dummy_db.yaml"

    args = [
        "--nested-conf",
        str(nested_file),
        "--required-field",
        "dummy",
        "--deferred-nested",
        str(nested_file),
        "--deferred-db-implicit",
        str(dummy_db),
        "--deferred-db-explicit",  # added missing required arg
        f"+{dummy_db}",  # use explicit '+' syntax for this one
    ]
    print(f"parsing args: {args}")
    config, raw_args = file_arg_program.parse_args(args)
    print(f"parsed config: {config}")

    assert isinstance(config.nested_conf, NestedForFile)
    assert config.nested_conf.value_from_file == 99
    assert isinstance(config.deferred_nested, DeferredNode)
    constructed = construct(config.deferred_nested)
    print(f"constructed deferred nested: {constructed}")
    assert isinstance(constructed, NestedForFile)
    assert constructed.value_from_file == 99

    assert isinstance(config.deferred_db_implicit, DeferredNode)
    constructed_db = construct(config.deferred_db_implicit)
    print(f"constructed deferred db: {constructed_db}")
    assert isinstance(constructed_db, DatabaseConfig)
    assert constructed_db.host == "dummy"
    assert constructed_db.port == 5432

    assert isinstance(config.deferred_db_explicit, DeferredNode)
    constructed_db_explicit = construct(config.deferred_db_explicit)
    print(f"constructed deferred db explicit: {constructed_db_explicit}")
    assert isinstance(constructed_db_explicit, DatabaseConfig)
    assert constructed_db_explicit.host == "dummy"
    assert constructed_db_explicit.port == 5432
    assert constructed_db_explicit.username == "dummy"


def test_deferred_node_explicit_plus(file_arg_program, config_files):
    """test DeferredNode with explicit '+' file syntax."""
    print("\n--- test_deferred_node_explicit_plus ---")
    deferred_db_file = config_files / "deferred_db_content.yaml"
    dummy_nested = config_files / "dummy_nested.yaml"
    dummy_db = config_files / "dummy_db.yaml"
    args = [
        "--deferred-db-explicit",
        f"+{deferred_db_file}",
        "--required-field",
        "dummy",
        "--nested-conf",
        str(dummy_nested),
        "--deferred-nested",
        f"+{dummy_nested}",
        "--deferred-db-implicit",
        str(dummy_db),
    ]
    print(f"parsing args: {args}")
    config, raw_args = file_arg_program.parse_args(args)
    print(f"parsed config: {config}")

    assert isinstance(config.deferred_db_explicit, DeferredNode)
    print("calling construct() on deferred_db_explicit...")
    constructed_db = construct(config.deferred_db_explicit)
    print(f"constructed db: {constructed_db}")

    assert isinstance(constructed_db, DatabaseConfig)
    assert constructed_db.host == "deferred_host"
    assert constructed_db.port == 1234
    assert constructed_db.username == "deferred_user"

    assert isinstance(config.deferred_nested, DeferredNode)
    print("calling construct() on deferred_nested...")
    constructed_nested = construct(config.deferred_nested)
    print(f"constructed nested: {constructed_nested}")
    assert isinstance(constructed_nested, NestedForFile)
    assert constructed_nested.value_from_file == 0
    assert isinstance(config.nested_conf, NestedForFile)
    print("calling construct() on nested_conf...")
    constructed_nested_conf = construct(config.nested_conf)
    print(f"constructed nested_conf: {constructed_nested_conf}")
    assert isinstance(constructed_nested_conf, NestedForFile)
    assert constructed_nested_conf.value_from_file == 0


def test_deferred_node_implicit_is_file(file_arg_program, config_files):
    """test DeferredNode with implicit file loading via is_file=True."""
    print("\n--- test_deferred_node_implicit_is_file ---")
    deferred_db_file = config_files / "deferred_db_content.yaml"
    dummy_nested = config_files / "dummy_nested.yaml"
    dummy_path = config_files / "dummy_path.txt"
    dummy_db = config_files / "dummy_db.yaml"
    args = [
        "--deferred-db-implicit",
        str(deferred_db_file),
        "--required-field",
        "dummy",
        "--nested-conf",
        str(dummy_nested),
        "--deferred-nested",
        str(dummy_nested),
        "--deferred-db-explicit",  # added missing required arg
        f"+{dummy_db}",
    ]
    print(f"parsing args: {args}")
    config, raw_args = file_arg_program.parse_args(args)
    print(f"parsed config: {config}")

    assert isinstance(config.deferred_db_implicit, DeferredNode)
    print("calling construct() on deferred_db_implicit...")
    constructed_db = construct(config.deferred_db_implicit)
    print(f"constructed db: {constructed_db}")

    assert isinstance(constructed_db, DatabaseConfig)
    assert constructed_db.host == "deferred_host"
    assert constructed_db.port == 1234
    assert constructed_db.username == "deferred_user"

    assert isinstance(config.deferred_nested, DeferredNode)
    print("calling construct() on deferred_nested...")
    constructed_nested = construct(config.deferred_nested)
    print(f"constructed nested: {constructed_nested}")
    assert isinstance(constructed_nested, NestedForFile)
    assert constructed_nested.value_from_file == 0
    assert isinstance(config.nested_conf, NestedForFile)


def test_boolean_flags(complex_program):
    """test behavior of boolean flags with and without defaults."""
    print("\n--- test_boolean_flags ---")
    args1 = ["input.txt", "output_dir"]
    print(f"parsing args: {args1}")
    config1, _ = complex_program.parse_args(args1)
    print(f"parsed config1: {config1}")
    assert config1.verbose is False
    args2 = ["input.txt", "output_dir", "-v"]
    print(f"parsing args: {args2}")
    config2, _ = complex_program.parse_args(args2)
    print(f"parsed config2: {config2}")
    assert config2.verbose is True


def test_complex_merge_command(program, config_files):
    """test a complex command combining file merge, context def, and overrides."""
    print("\n--- test_complex_merge_command ---")
    dev_conf = config_files / "dev.yaml"
    args = [
        "+pkg:mypackage:configs/default",  # base from package
        f"+{dev_conf}",  # merge dev config
        "--define.extra_context",
        "my_value",  # define context var
        "--database.port",
        "9999",  # override nested value
        "--log-level",
        "TRACE",  # override simple value
    ]
    print(f"parsing args: {args}")
    config, raw_args = program.parse_args(args)
    print(f"parsed config: {config}")
    print(f"raw args dict: {raw_args}")
    assert isinstance(config, AppConfig)
    assert config.environment == "dev"  # from dev.yaml
    assert config.log_level == "TRACE"  # overridden by cli
    assert config.workers == 1  # default (not in pkg or dev)
    assert config.database.host == "db.dev"  # from dev.yaml (wins over pkg)
    assert config.database.port == 9999  # overridden by cli
    assert config.database.username == "dev_user"  # from dev.yaml (wins over pkg)
    assert config.database.password == "dev_password"  # from dev.yaml (wins over pkg)
    assert isinstance(config.output_path, DeferredNode)
    # check context variable doesn't appear in config itself
    assert not hasattr(config, 'extra_context')


def test_cli_type_error(program, config_files, capfd):
    """test providing an incorrect type via the command line."""
    print("\n--- test_cli_type_error ---")
    dev_conf = config_files / "dev.yaml"
    args = [
        f"+{dev_conf}",
        "--workers",
        "not_an_int",  # incorrect type
    ]
    print(f"parsing args: {args}")
    with pytest.raises(SystemExit):
        program.parse_args(args)
    captured = capfd.readouterr()
    print(f"captured stderr:\n{captured.err}")
    print(f"captured stdout:\n{captured.out}")
    # check for pydantic validation error message
    assert "Input should be a valid integer" in captured.out
    assert "Usage: simple-app [OPTIONS]" in captured.out  # help should be printed


class InnerModelForFileTest(BaseModel):
    value: int
    name: str


class OuterModelDeferredFileTest(BaseModel):
    inner_field: Annotated[
        DeferredNode[InnerModelForFileTest], Arg(is_file=True, help="Load inner model from file.")
    ]
    required_str: Annotated[str, Arg(help="A required string field.")]


@pytest.fixture
def file_deferred_complex_program():
    """Create the dracon program instance for OuterModelDeferredFileTest"""
    print("creating Program instance for OuterModelDeferredFileTest...")
    prog = make_program(
        OuterModelDeferredFileTest,
        name="file-deferred-complex-app",
        description="app for testing is_file+deferrednode with complex types",
        context={
            'InnerModelForFileTest': InnerModelForFileTest,
            'OuterModelDeferredFileTest': OuterModelDeferredFileTest,
        },
    )
    print("program instance created.")
    return prog


@pytest.fixture(scope="module")
def complex_config_files(tmp_path_factory):
    """Create dummy config files for complex type loading"""
    tmp_path = tmp_path_factory.mktemp("complex_cmd_configs")
    print(f"creating complex config files in: {tmp_path}")

    included_name = """
name: "with ${extra_context} and ${computed_context}"
"""

    inner_content = """
value: 123
name: "Loaded from file"
<<{<+}: !include file:$DIR/included_name
"""
    (tmp_path / "inner_data.yaml").write_text(inner_content)
    (tmp_path / "included_name.yaml").write_text(included_name)
    print("created inner_data.yaml")
    yield tmp_path


def test_is_file_deferred_with_complex_type(file_deferred_complex_program, complex_config_files):
    """
    Test Arg(is_file=True) on a DeferredNode field expecting a complex Pydantic model.
    This aims to reproduce the error seen in calibrie more closely.
    The error should occur during the construct() call if the bug exists.
    """
    print("\n--- test_is_file_deferred_with_complex_type ---")
    inner_file = complex_config_files / "inner_data"
    args = [
        "--inner-field",
        str(inner_file),
        "--required-str",
        "some_value",
        "--define.extra_context",
        "extra_value",  # define context var
        "--inner-field.value",  # override inner field value (of a deferred node!)
        "456",  # override value
    ]
    print(f"parsing args: {args}")

    config, raw_args = file_deferred_complex_program.parse_args(args)
    print(f"parsed config (pre-construct): {config}")

    assert isinstance(config, OuterModelDeferredFileTest)
    assert isinstance(config.inner_field, DeferredNode)
    assert config.required_str == "some_value"

    print("calling construct() on config.inner_field...")
    constructed_inner = construct(
        config.inner_field, context={'computed_context': "computed_value"}
    )
    print(f"constructed inner field: {constructed_inner}")

    assert isinstance(constructed_inner, InnerModelForFileTest)
    assert constructed_inner.value == 456
    assert constructed_inner.name == "with extra_value and computed_value"
    print("test_is_file_deferred_with_complex_type PASSED")


class InnerModelManual(BaseModel):
    data_value: int
    source_name: str


@pytest.fixture(scope="module")
def manual_config_files(tmp_path_factory):
    """Create dummy config files for manual deferred file loading test"""
    tmp_path = tmp_path_factory.mktemp("manual_deferred_configs")
    print(f"creating manual deferred config files in: {tmp_path}")

    inner_content = """
data_value: 999
source_name: "Manually Loaded"
"""
    (tmp_path / "inner_manual.yaml").write_text(inner_content)
    print("created inner_manual.yaml")
    yield tmp_path


def test_positional_args_with_options_and_file(complex_program, config_files):
    """test positional arguments mixed with options and loading a file."""
    print("\n--- test_positional_args_with_options_and_file ---")
    complex_conf = config_files / "complex_cli.yaml"
    args = [
        f"+{complex_conf}",  # load file first
        "-v",  # set verbose flag (overrides file)
        "my_input.dat",  # first positional
        "/path/to/output",  # second positional
        "optional_value",  # third (optional) positional
    ]
    print(f"parsing args: {args}")
    config, raw_args = complex_program.parse_args(args)
    print(f"parsed config: {config}")
    print(f"raw args dict: {raw_args}")
    assert isinstance(config, ComplexCliConfig)
    assert config.input_file == "my_input.dat"
    assert config.output_dir == "/path/to/output"
    assert config.optional_pos == "optional_value"
    assert config.verbose is True  # from cli flag -v
    assert config.nested_list.items == ["item_file_A", "item_file_B"]  # from file


class InnerData(BaseModel):
    raw_value: int
    # This value depends on a context variable (RUNTIME_VAR)
    # that will only be provided when construct() is called.
    computed_value: int = "${RUNTIME_VAR * 10 }"
    another_value: str = "Static"


class OuterConfig(BaseModel):
    deferred_inner: Annotated[
        DeferredNode[InnerData],
        Arg(is_file=True, help="Load inner data from file, construction deferred."),
    ]
    required_str: Annotated[str, Arg(help="A required string.")]


@pytest.fixture(scope="module")
def deferred_config_files(tmp_path_factory):
    """Create the YAML file for the inner deferred data."""
    tmp_path = tmp_path_factory.mktemp("deferred_cli_configs")
    print(f"Creating config files in: {tmp_path}")

    # inner_data.yaml - Contains the interpolation requiring runtime context
    inner_content = """
!InnerData
raw_value: 5
computed_value: "${RUNTIME_VAR * 10 }" # Requires RUNTIME_VAR
another_value: "From File"
"""
    inner_file = tmp_path / "inner_data.yaml"
    inner_file.write_text(inner_content)
    print(f"Created {inner_file}")

    yield {"inner": inner_file}
    print(f"Cleaned up tmp path: {tmp_path}")


@pytest.fixture
def deferred_program():
    """Create the dracon program instance for testing."""
    print("Creating Program instance for OuterConfig...")
    prog = make_program(
        OuterConfig,
        name="deferred-cli-app",
        description="App for testing deferred loading with runtime context.",
        context={
            'InnerData': InnerData,
            'OuterConfig': OuterConfig,
        },
    )
    print("Program instance created.")
    return prog


def test_deferred_cli_context_resolution_failure(deferred_program, deferred_config_files):
    """
    is called after construct, but without the necessary context override.
    """
    inner_file = deferred_config_files["inner"]
    args = [
        "--deferred-inner",
        str(inner_file),
        "--required-str",
        "test",
    ]

    config, raw_args = deferred_program.parse_args(args)

    assert isinstance(config, OuterConfig)
    assert isinstance(config.deferred_inner, DeferredNode)

    runtime_context = {'RUNTIME_VAR': 42}

    constructed_inner = config.deferred_inner.construct(context=runtime_context)

    cval = constructed_inner.computed_value
    assert cval == 420  # 42 * 10 = 420


# Tests for Field description as CLI help string
class TestFieldDescriptionAsCLIHelp:
    """Test that Pydantic Field descriptions can be used as CLI help strings."""

    def test_field_description_fallback(self, capfd):
        """field description used when no arg help provided"""

        class Config(BaseModel):
            name: str = Field(default="default_name", description="The name of the user")
            age: Annotated[int, Arg()] = Field(
                default=18, description="The age of the user in years"
            )

        program = make_program(Config, name="test", context={'Config': Config})

        with pytest.raises(SystemExit) as e:
            program.parse_args(["--help"])
        assert e.value.code == 0

        captured = capfd.readouterr()
        assert "The name of the user" in captured.out
        assert "The age of the user in years" in captured.out

    def test_arg_help_precedence(self, capfd):
        """arg help takes precedence over field description"""

        class Config(BaseModel):
            name: Annotated[str, Arg(help="CLI help for name")] = Field(
                default="default", description="Field description for name"
            )

        program = make_program(Config, name="test", context={'Config': Config})

        with pytest.raises(SystemExit) as e:
            program.parse_args(["--help"])
        assert e.value.code == 0

        captured = capfd.readouterr()
        assert "CLI help for name" in captured.out
        assert "Field description for name" not in captured.out

    def test_nested_field_descriptions(self, capfd):
        """nested fields show field descriptions for parent field"""

        class DatabaseConfig(BaseModel):
            host: str = Field(description="Database host address")
            port: int = Field(default=5432, description="Database port number")

        class Config(BaseModel):
            database: DatabaseConfig = Field(description="Database configuration settings")

        program = make_program(
            Config, name="test", context={'Config': Config, 'DatabaseConfig': DatabaseConfig}
        )

        with pytest.raises(SystemExit) as e:
            program.parse_args(["--help"])
        assert e.value.code == 0

        captured = capfd.readouterr()
        # nested models show their type and parent field description
        assert "Database configuration settings" in captured.out
        assert "DatabaseConfig" in captured.out

    def test_literal_type_with_description(self, capfd):
        """literal types with field descriptions"""
        LogLevel = Literal["debug", "info", "warning", "error"]

        class Config(BaseModel):
            log_level: LogLevel = Field(
                default="info", description="Logging level for the application"
            )

        program = make_program(Config, name="test", context={'Config': Config})

        # test help shows choices
        with pytest.raises(SystemExit) as e:
            program.parse_args(["--help"])
        assert e.value.code == 0

        captured = capfd.readouterr()
        assert "Logging level for the application" in captured.out
        assert "{debug,info,warning,error}" in captured.out or all(
            level in captured.out for level in ["debug", "info", "warning", "error"]
        )

        # test parsing valid choice
        config, _ = program.parse_args(["--log-level", "debug"])
        assert config.log_level == "debug"

        # test invalid choice
        with pytest.raises(SystemExit):
            program.parse_args(["--log-level", "invalid"])


# Tests for Pydantic v2 Annotated functional validators
# validator functions
add_one = lambda v: v + 1
validate_positive = lambda v: v if v > 0 else (_ for _ in ()).throw(ValueError("must be positive"))
parse_and_add_one = lambda v: int(v) + 1
uppercase = lambda v: v.upper()


def validate_timestamp(v, handler):
    """wrap validator for timestamp"""
    return datetime.fromisoformat(v) if isinstance(v, str) else handler(v)


def test_after_validator():
    """after validator transforms cli input"""
    IntPlusOne = Annotated[int, AfterValidator(add_one)]

    class Config(BaseModel):
        count: Annotated[IntPlusOne, Arg(help="Counter value")] = Field(
            default=0, description="A counter that adds one"
        )

    program = make_program(Config, name="test", context={'Config': Config})

    config, _ = program.parse_args(["--count", "5"])
    assert config.count == 6

    config, _ = program.parse_args([])
    assert config.count == 0  # default value unchanged


def test_before_validator(capfd):
    """before validator validates before type conversion"""
    PositiveInt = Annotated[int, BeforeValidator(validate_positive)]

    class Config(BaseModel):
        port: Annotated[PositiveInt, Arg()] = Field(
            default=8080, description="Server port (must be positive)"
        )

    program = make_program(Config, name="test", context={'Config': Config})

    config, _ = program.parse_args(["--port", "3000"])
    assert config.port == 3000

    with pytest.raises(SystemExit):
        program.parse_args(["--port", "0"])

    captured = capfd.readouterr()
    assert "must be positive" in captured.out


def test_plain_validator():
    """plain validator with custom parsing"""
    IntPlusOne = Annotated[int, PlainValidator(parse_and_add_one)]

    class Config(BaseModel):
        value: Annotated[IntPlusOne, Arg()] = Field(
            default=0, description="Value that gets incremented"
        )

    program = make_program(Config, name="test", context={'Config': Config})

    config, _ = program.parse_args(["--value", "10"])
    assert config.value == 11


def test_wrap_validator():
    """wrap validator for custom type handling"""
    MyTimestamp = Annotated[datetime, WrapValidator(validate_timestamp)]

    class Config(BaseModel):
        timestamp: Annotated[MyTimestamp, Arg()] = Field(
            default_factory=datetime.now, description="Timestamp value"
        )

    program = make_program(Config, name="test", context={'Config': Config})

    config, _ = program.parse_args(["--timestamp", "2024-01-01T12:00:00"])
    assert config.timestamp == datetime(2024, 1, 1, 12, 0, 0)


def test_chained_validators(capfd):
    """multiple validators in sequence"""
    ProcessedInt = Annotated[int, BeforeValidator(validate_positive), AfterValidator(add_one)]

    class Config(BaseModel):
        number: Annotated[ProcessedInt, Arg()] = Field(
            default=1, description="Positive number that gets incremented"
        )

    program = make_program(Config, name="test", context={'Config': Config})

    config, _ = program.parse_args(["--number", "5"])
    assert config.number == 6

    with pytest.raises(SystemExit):
        program.parse_args(["--number", "0"])  # 0 not positive


def test_validator_with_literal():
    """validators work with literal types"""
    LogLevel = Literal["debug", "info", "warning", "error"]
    UppercaseLevel = Annotated[LogLevel, AfterValidator(uppercase)]

    class Config(BaseModel):
        level: UppercaseLevel = Field(default="info", description="Log level (will be uppercased)")

    program = make_program(Config, name="test", context={'Config': Config})

    config, _ = program.parse_args(["--level", "debug"])
    assert config.level == "DEBUG"


def test_validator_field_combo(capfd):
    """validators work with field description and arg"""
    Email = Annotated[
        str,
        AfterValidator(
            lambda v: v if "@" in v else (_ for _ in ()).throw(ValueError("invalid email"))
        ),
    ]

    class Config(BaseModel):
        email: Annotated[Email, Arg()] = Field(description="User email address")

    program = make_program(Config, name="test", context={'Config': Config})

    config, _ = program.parse_args(["--email", "user@example.com"])
    assert config.email == "user@example.com"

    with pytest.raises(SystemExit):
        program.parse_args(["--email", "not-an-email"])

    captured = capfd.readouterr()
    assert "invalid email" in captured.out


def test_validator_with_file_loading(tmp_path):
    """validators work with file loading syntax"""
    ProcessedInt = Annotated[int, AfterValidator(lambda v: v * 2)]

    class Config(BaseModel):
        multiplied: ProcessedInt = Field(default=10)

    # create test file
    config_file = tmp_path / "config.yaml"
    config_file.write_text("multiplied: 5")

    program = make_program(Config, name="test", context={'Config': Config})

    config, _ = program.parse_args([f"+{config_file}"])
    assert config.multiplied == 10  # 5 * 2


def test_dir_context_cli_vs_direct_loading(tmp_path):
    from dracon import load
    from pydantic import BaseModel
    from dracon import make_program

    base = tmp_path / "base"
    sub = base / "sub"
    base.mkdir()
    sub.mkdir()

    target_file = sub / "target.yaml"
    target_file.write_text("result: success")

    # Nested file using $(DIR) to reference target
    nested_file = sub / "nested.yaml"
    nested_file.write_text("data: !include file:$DIR/target.yaml")

    main_file = base / "main.yaml"
    main_file.write_text("""!define nested_path: sub/nested.yaml
config: !include file:$DIR/${nested_path}""")

    # Direct loading
    direct_config = load(str(main_file))
    assert direct_config['config']['data']['result'] == "success"

    class Config(BaseModel):
        config: dict = {}

    program = make_program(Config)
    cli_config, _ = program.parse_args([f'+{main_file}'])

    assert cli_config.config['data']['result'] == "success"


def test_list_args_1(program):
    class ListConfig(BaseModel):
        items: Annotated[List[str], Arg(help="List of items", positional=True)] = []
        other: Annotated[List[str], Arg(help="List of stuff with --other")] = []

    program = make_program(ListConfig, name="list-app", context={'ListConfig': ListConfig})
    items = ["i1", "i2", "i3"]

    args1 = ["--items", "['i1', 'i2', 'i3']"]  # using --items with a string representation
    print(f"parsing args: {args1}")
    config1, _ = program.parse_args(args1)
    print(f"parsed config1: {config1}")
    assert isinstance(config1, ListConfig)
    assert config1.items == items

    args1 = ["['i1', 'i2', 'i3']"]  # using positional with a string representation
    print(f"parsing args: {args1}")
    config1, _ = program.parse_args(args1)
    print(f"parsed config1: {config1}")
    assert isinstance(config1, ListConfig)
    assert config1.items == items

    args2 = ["--items", *items]  # using --items with unpacking
    print(f"parsing args: {args2}")
    config2, _ = program.parse_args(args2)
    print(f"parsed config1: {config2}")
    assert isinstance(config2, ListConfig)
    assert config2.items == items

    args2 = [*items]  # using positional with unpacking (space separated)
    print(f"parsing args: {args2}")
    config2, _ = program.parse_args(args2)
    print(f"parsed config1: {config2}")
    assert isinstance(config2, ListConfig)
    assert config2.items == items

    args = ["['i1', 'i2', 'i3']", "--other", "['o1', 'o2']"]
    config, _ = program.parse_args(args)
    assert isinstance(config, ListConfig)
    assert config.items == items
    assert config.other == ["o1", "o2"]

    args = [*items, "--other", "['o1', 'o2']"]
    config, _ = program.parse_args(args)
    assert isinstance(config, ListConfig)
    assert config.items == items
    assert config.other == ["o1", "o2"]

    args = [*items, "--other", 'o1', 'o2']
    config, _ = program.parse_args(args)
    assert isinstance(config, ListConfig)
    assert config.items == items
    assert config.other == ["o1", "o2"]

    args = ["--other", 'o1', 'o2', *items]
    config, _ = program.parse_args(args)
    assert isinstance(config, ListConfig)
    assert len(config.items) == 0  # no items provided since they are after --other
    assert config.other == ["o1", "o2"] + items

    args = ["--other", 'o1', 'o2', '--items', *items]
    config, _ = program.parse_args(args)
    assert isinstance(config, ListConfig)
    assert config.items == items
    assert config.other == ["o1", "o2"]

    args = [*items, "--other", '"o1 with space"', '""with " quotes""']
    config, _ = program.parse_args(args)
    assert isinstance(config, ListConfig)
    assert config.items == items
    assert config.other == ["o1 with space", '"with " quotes"']


def test_list_args_2(program):
    class ListConfig(BaseModel):
        items: Annotated[List[str], Arg(help="List of items", positional=True)] = []
        other: Annotated[List[str], Arg(help="List of stuff", positional=True)] = []

    # creating the program should fail because when a positional argument is a list, no other positional arguments can be defined
    with pytest.raises(
        ValueError,
        match="When a positional argument is a list, no other positional arguments are allowed.",
    ):
        make_program(ListConfig, name="list-app", context={'ListConfig': ListConfig})


def test_dict_args_1(program):
    class DictConfig(BaseModel):
        config: Annotated[Dict[str, Any], Arg(help="Configuration dict", positional=True)] = {}
        settings: Annotated[Dict[str, str], Arg(help="Settings dict with --settings")] = {}

    program = make_program(DictConfig, name="dict-app", context={'DictConfig': DictConfig})

    # test JSON-like syntax
    args1 = ["--config", '{"key1": "value1", "key2": "value2"}']
    print(f"parsing args: {args1}")
    config1, _ = program.parse_args(args1)
    print(f"parsed config1: {config1}")
    assert isinstance(config1, DictConfig)
    assert config1.config == {"key1": "value1", "key2": "value2"}

    args1 = ['{"key1": "value1", "key2": "value2"}']  # positional JSON
    print(f"parsing args: {args1}")
    config1, _ = program.parse_args(args1)
    print(f"parsed config1: {config1}")
    assert isinstance(config1, DictConfig)
    assert config1.config == {"key1": "value1", "key2": "value2"}

    # test key=value space-separated syntax
    args2 = ["--config", "key1=value1", "key2=value2"]
    print(f"parsing args: {args2}")
    config2, _ = program.parse_args(args2)
    print(f"parsed config1: {config2}")
    assert isinstance(config2, DictConfig)
    assert config2.config == {"key1": "value1", "key2": "value2"}

    args2 = ["key1=value1", "key2=value2"]  # positional key=value
    print(f"parsing args: {args2}")
    config2, _ = program.parse_args(args2)
    print(f"parsed config1: {config2}")
    assert isinstance(config2, DictConfig)
    assert config2.config == {"key1": "value1", "key2": "value2"}

    # test nested key syntax
    args3 = ["--config", "key1=value1", "nested.subkey=subvalue", "key2=value2"]
    config3, _ = program.parse_args(args3)
    assert isinstance(config3, DictConfig)
    assert config3.config == {"key1": "value1", "nested": {"subkey": "subvalue"}, "key2": "value2"}

    args3 = ["key1=value1", "nested.subkey=subvalue", "key2=value2"]  # positional nested
    config3, _ = program.parse_args(args3)
    assert isinstance(config3, DictConfig)
    assert config3.config == {"key1": "value1", "nested": {"subkey": "subvalue"}, "key2": "value2"}

    # test mixed usage
    args = ['{"existing": "json"}', "--settings", "opt1=val1", "opt2=val2"]
    config, _ = program.parse_args(args)
    assert isinstance(config, DictConfig)
    assert config.config == {"existing": "json"}
    assert config.settings == {"opt1": "val1", "opt2": "val2"}

    args = ["key1=value1", "key2=value2", "--settings", '{"json": "style"}']
    config, _ = program.parse_args(args)
    assert isinstance(config, DictConfig)
    assert config.config == {"key1": "value1", "key2": "value2"}
    assert config.settings == {"json": "style"}

    # test quoted values
    args = ["key1=value1", 'key2="value with spaces"', "key3='quoted value'"]
    config, _ = program.parse_args(args)
    assert isinstance(config, DictConfig)
    assert config.config == {"key1": "value1", "key2": "value with spaces", "key3": "quoted value"}


def test_dict_args_2(program):
    class DictConfig(BaseModel):
        config: Annotated[Dict[str, Any], Arg(help="Configuration dict", positional=True)] = {}
        settings: Annotated[Dict[str, str], Arg(help="Settings dict", positional=True)] = {}

    # creating the program should fail because when a positional argument is a dict, no other positional arguments can be defined
    with pytest.raises(
        ValueError,
        match="When a positional argument is a dict, no other positional arguments are allowed.",
    ):
        make_program(DictConfig, name="dict-app", context={'DictConfig': DictConfig})


def test_list_like_containers(program):
    """Test that tuple, set and other list-like containers work with space-separated syntax"""

    class TupleConfig(BaseModel):
        items: Annotated[Tuple[str, ...], Arg(help="Tuple of items", positional=True)] = ()
        other: Annotated[Tuple[str, str], Arg(help="Fixed size tuple")] = ("default1", "default2")

    program = make_program(TupleConfig, name="tuple-app", context={'TupleConfig': TupleConfig})

    # test tuple with space-separated syntax
    args = ["--items", "i1", "i2", "i3"]
    config, _ = program.parse_args(args)
    assert isinstance(config, TupleConfig)
    assert config.items == ("i1", "i2", "i3")

    # test tuple with YAML syntax
    args = ["--items", "['t1', 't2']"]
    config, _ = program.parse_args(args)
    assert isinstance(config, TupleConfig)
    assert config.items == ("t1", "t2")

    # test positional tuple
    args = ["i1", "i2", "i3"]
    config, _ = program.parse_args(args)
    assert isinstance(config, TupleConfig)
    assert config.items == ("i1", "i2", "i3")

    # test fixed-size tuple
    args = ["--other", "a", "b"]
    config, _ = program.parse_args(args)
    assert isinstance(config, TupleConfig)
    assert config.other == ("a", "b")


def test_set_containers(program):
    """Test that set containers work with space-separated syntax"""

    class SetConfig(BaseModel):
        tags: Annotated[Set[str], Arg(help="Set of tags")] = set()

    program = make_program(SetConfig, name="set-app", context={'SetConfig': SetConfig})

    # test set with space-separated syntax
    args = ["--tags", "tag1", "tag2", "tag1"]  # duplicate should be removed
    config, _ = program.parse_args(args)
    assert isinstance(config, SetConfig)
    assert config.tags == {"tag1", "tag2"}

    # test set with YAML syntax
    args = ["--tags", "['s1', 's2', 's1']"]
    config, _ = program.parse_args(args)
    assert isinstance(config, SetConfig)
    assert config.tags == {"s1", "s2"}


def test_interpolable_args(program):
    """Test that interpolated arguments work correctly"""

    class InterpolatedConfig(
        LazyDraconModel
    ):  # using LazyDraconModel will allow lazy evaluation of the value
        value: Annotated[str, Arg(help="String value")] = "${INTERPOLATED_VAR}"
        list_of_values: Annotated[List[str], Arg(help="List of values")] = []

    program = make_program(
        InterpolatedConfig,
        name="interpolated-app",
        context={'InterpolatedConfig': InterpolatedConfig, 'INTERPOLATED_VAR': 'default_value'},
    )

    # test without interpolation
    args = ["--value", "static_value"]
    config, _ = program.parse_args(args)
    assert isinstance(config, InterpolatedConfig)
    assert config.value == "static_value"

    # test with interpolation
    args = ["--value", "${INTERPOLATED_VAR}"]
    config, _ = program.parse_args(args, context={'INTERPOLATED_VAR': 'interpolated_value'})
    assert isinstance(config, InterpolatedConfig)
    assert config.value == "interpolated_value"

    args = ["--list-of-values", "item1", "item2"]
    config, _ = program.parse_args(args)
    assert isinstance(config, InterpolatedConfig)
    assert all(isinstance(v, str) for v in config.list_of_values)
    assert config.list_of_values == ["item1", "item2"]

    args = ["--list-of-values", "item1", "${INTERPOLATED_VAR}"]
    config, _ = program.parse_args(args, context={'INTERPOLATED_VAR': 'interpolated_item'})
    assert isinstance(config, InterpolatedConfig)
    assert all(isinstance(v, str) for v in config.list_of_values)
    assert config.list_of_values == ["item1", "interpolated_item"]


class ClassA(BaseModel):
    name: str = ''


def test_define_context_file_loading_direct(tmp_path):
    # control test: direct loading with context works
    config_file = tmp_path / "test_define.yaml"
    config_file.write_text("""!ClassA
!define variable: 1
name: val_${variable}
""")
    loader = DraconLoader(context={'ClassA': ClassA})
    direct_config = loader.load(str(config_file))
    assert isinstance(direct_config, ClassA)
    assert direct_config.name == 'val_1'


def test_define_context_file_loading_explicit(tmp_path):
    config_file = tmp_path / "test_define.yaml"
    config_file.write_text("""!ClassA
!define variable: 1
name: val_${variable}
""")

    # CLI with explicit +file.yaml syntax, should work (just like direct loading above)
    class ConfigWithExplicitInclude(BaseModel):
        data: ClassA

    program1 = make_program(
        ConfigWithExplicitInclude, name="test-explicit-include", context={'ClassA': ClassA}
    )

    config1, _ = program1.parse_args(["--data", f"+{config_file}"])
    assert isinstance(config1, ConfigWithExplicitInclude)
    assert isinstance(config1.data, ClassA)
    assert config1.data.name == 'val_1'


def test_equals_syntax_long_option(config_files):
    """--workers=4 should work like --workers 4"""
    program = make_program(AppConfig, name="test-eq")
    cfg, _ = program.parse_args([
        f"+{config_files / 'localconf.yaml'}",
        "--workers=8",
    ])
    assert cfg.workers == 8


def test_equals_syntax_short_option(config_files):
    """-e=staging should work like -e staging"""
    program = make_program(AppConfig, name="test-eq")
    cfg, _ = program.parse_args([
        f"+{config_files / 'localconf.yaml'}",
        "-e=staging",
    ])
    assert cfg.environment == "staging"


def test_equals_syntax_nested_dotted_arg(config_files):
    """--database.port=9999 should set nested value"""
    program = make_program(AppConfig, name="test-eq")
    cfg, _ = program.parse_args([
        f"+{config_files / 'localconf.yaml'}",
        "--database.port=9999",
    ])
    assert cfg.database.port == 9999


def test_equals_syntax_value_containing_equals(config_files):
    """--log-level=A=B=C should preserve = in the value"""
    program = make_program(AppConfig, name="test-eq")
    cfg, _ = program.parse_args([
        f"+{config_files / 'localconf.yaml'}",
        "--log-level=A=B=C",
    ])
    assert cfg.log_level == "A=B=C"


def test_equals_syntax_is_file_arg(tmp_path):
    """--nested_conf=/path should work with is_file=True"""
    nested_file = tmp_path / "nested.yaml"
    nested_file.write_text("value_from_file: 42\n")

    db_file = tmp_path / "db.yaml"
    db_file.write_text("host: h\nport: 1\nusername: u\npassword: p\n")

    program = make_program(FileArgConfig, name="test-eq-file")
    cfg, _ = program.parse_args([
        f"--nested-conf={nested_file}",
        f"--deferred-nested={nested_file}",
        f"--deferred-db-explicit=+{db_file}",
        f"--deferred-db-implicit={db_file}",
        "--required-field=yes",
    ])
    assert cfg.nested_conf.value_from_file == 42
    assert cfg.required_field == "yes"


def test_equals_syntax_mixed_with_space(config_files):
    """mix of --opt=val and --opt val in same invocation"""
    program = make_program(AppConfig, name="test-eq")
    cfg, _ = program.parse_args([
        f"+{config_files / 'localconf.yaml'}",
        "--workers=16",
        "--log-level", "ERROR",
        "-e=production",
    ])
    assert cfg.workers == 16
    assert cfg.log_level == "ERROR"
    assert cfg.environment == "production"


def test_define_context_cli_file_loading_is_file(tmp_path):
    config_file = tmp_path / "test_define.yaml"
    config_file.write_text("""!ClassA
!define variable: 1
name: val_${variable}
""")

    # CLI with is_file=True syntax (allow to skip the +)
    class ConfigWithFileArg(BaseModel):
        data: Annotated[ClassA, Arg(is_file=True, help="Load ClassA from file")]

    program2 = make_program(ConfigWithFileArg, name="test-file-arg", context={'ClassA': ClassA})
    config2, _ = program2.parse_args(["--data", str(config_file)])
    assert isinstance(config2, ConfigWithFileArg)
    assert isinstance(config2.data, ClassA)
    assert config2.data.name == 'val_1'


# --- YAML parsing of ++/--define values ---


def test_plusplus_yaml_list_parsing(anythingprogram, config_files):
    """++var=[[5,60]] should produce a list, not the string '[[5,60]]'"""
    cfg_file = config_files / "yaml_parse_test.yaml"
    cfg_file.write_text("value: ${my_var}\n")

    config, _ = anythingprogram.parse_args([f"+{cfg_file}", "++my_var=[[5,60]]"])
    assert config.value == [[5, 60]]


def test_plusplus_yaml_nested_list_parsing(anythingprogram, config_files):
    cfg_file = config_files / "yaml_parse_test2.yaml"
    cfg_file.write_text("value: ${my_var}\n")

    config, _ = anythingprogram.parse_args([f"+{cfg_file}", "++my_var=[[0,5],[10,20],[30,40]]"])
    assert config.value == [[0, 5], [10, 20], [30, 40]]


def test_plusplus_yaml_dict_parsing(anythingprogram, config_files):
    cfg_file = config_files / "yaml_parse_dict.yaml"
    cfg_file.write_text("value: ${my_var}\n")

    config, _ = anythingprogram.parse_args([f"+{cfg_file}", "++my_var={a: 1, b: 2}"])
    assert config.value == {"a": 1, "b": 2}


def test_plusplus_yaml_scalar_parsing(anythingprogram, config_files):
    """++var=42 should produce int 42, not string '42'"""
    cfg_file = config_files / "yaml_parse_scalar.yaml"
    cfg_file.write_text("value: ${my_var}\n")

    config, _ = anythingprogram.parse_args([f"+{cfg_file}", "++my_var=42"])
    assert config.value == 42
    assert isinstance(config.value, int)


def test_plusplus_yaml_preserves_interpolation(anythingprogram, config_files):
    """++var=${[42, 1]} should still work (dracon interpolation, not plain YAML)"""
    cfg_file = config_files / "yaml_parse_interp.yaml"
    cfg_file.write_text("value:\n    itsadict: hehe\n    var: ${my_var}\n")

    config, _ = anythingprogram.parse_args([f"+{cfg_file}", "++my_var", "${[42, 1]}"])
    assert config.value == {'itsadict': 'hehe', 'var': [42, 1]}


def test_define_yaml_list_parsing(anythingprogram, config_files):
    """--define.var=[[5,60]] should also parse as list"""
    cfg_file = config_files / "yaml_parse_define.yaml"
    cfg_file.write_text("value: ${my_var}\n")

    config, _ = anythingprogram.parse_args([f"+{cfg_file}", "--define.my_var=[[5,60]]"])
    assert config.value == [[5, 60]]


# ── HelpSection / epilog tests ─────────────────────────────────────────────

from dracon.commandline import HelpSection


def test_cli_help_sections(capsys):
    """sections appear with title and body in help output."""
    sections = [
        HelpSection(title="Keybindings", body="j  next\nk  prev"),
        HelpSection(title="Examples", body="myapp --foo bar"),
    ]
    prog = make_program(AppConfig, name="test-app", sections=sections)
    with pytest.raises(SystemExit):
        prog.parse_args(["--help", "-e", "x", "--database.host", "h",
                          "--database.username", "u", "--database.password", "p"])
    out = capsys.readouterr().out
    assert "Keybindings:" in out
    assert "j  next" in out
    assert "k  prev" in out
    assert "Examples:" in out
    assert "myapp --foo bar" in out


def test_cli_help_epilog(capsys):
    """epilog text appears in help output."""
    prog = make_program(AppConfig, name="test-app", epilog="See docs for more info.")
    with pytest.raises(SystemExit):
        prog.parse_args(["--help", "-e", "x", "--database.host", "h",
                          "--database.username", "u", "--database.password", "p"])
    out = capsys.readouterr().out
    assert "See docs for more info." in out


def test_cli_help_no_sections_unchanged(capsys):
    """no sections = no extra content (backward compat)."""
    prog = make_program(AppConfig, name="test-app")
    with pytest.raises(SystemExit):
        prog.parse_args(["--help", "-e", "x", "--database.host", "h",
                          "--database.username", "u", "--database.password", "p"])
    out = capsys.readouterr().out
    assert "Options:" in out
    # sections/epilog markers should not appear
    assert "Keybindings:" not in out
    assert "See docs" not in out


def test_dracon_program_sections_epilog(capsys):
    """@dracon_program threads sections/epilog through to help."""
    from dracon import dracon_program

    sections = [HelpSection(title="Custom", body="custom content")]

    @dracon_program(name="decorated-app", sections=sections, epilog="footer text")
    class DecConfig(BaseModel):
        name: str = "default"

    with pytest.raises(SystemExit):
        DecConfig.cli(["--help"])
    out = capsys.readouterr().out
    assert "Custom:" in out
    assert "custom content" in out
    assert "footer text" in out


# ──────────────────────────────────────────────────────────────────────────────
# Subcommand system tests
# ──────────────────────────────────────────────────────────────────────────────

from dracon import Subcommand, subcommand, dracon_program
from dracon.commandline import HelpSection


# -- fixtures for subcommand tests --

class TrainCmd(BaseModel):
    """Train a model on the dataset."""
    action: Literal['train'] = 'train'
    epochs: Annotated[int, Arg(help="Number of epochs")] = 10
    lr: float = 0.001

    def run(self, ctx):
        return {'action': 'train', 'epochs': self.epochs, 'lr': self.lr, 'verbose': ctx.verbose}


class EvalCmd(BaseModel):
    """Evaluate a model on test data."""
    action: Literal['eval'] = 'eval'
    dataset: Annotated[str, Arg(help="Test dataset path")] = "test.csv"

    def run(self, ctx):
        return {'action': 'eval', 'dataset': self.dataset, 'verbose': ctx.verbose}


class SubCmdCLI(BaseModel):
    verbose: Annotated[bool, Arg(short='v', help="Verbose output")] = False
    command: Subcommand(TrainCmd, EvalCmd)


# -- test Subcommand() type factory --

def test_subcommand_produces_annotated_union():
    """Subcommand() returns an Annotated[Union[...], Field(discriminator=...), Arg(subcommand=True)]"""
    from typing import get_args, get_origin
    import typing
    ann = Subcommand(TrainCmd, EvalCmd)
    # should be Annotated
    assert typing.get_origin(ann) is Annotated
    inner_args = typing.get_args(ann)
    # first arg is the Union
    union_type = inner_args[0]
    assert typing.get_origin(union_type) is Union
    union_members = set(typing.get_args(union_type))
    assert union_members == {TrainCmd, EvalCmd}
    # metadata should contain an Arg with subcommand=True
    metadata = inner_args[1:]
    arg_meta = [m for m in metadata if isinstance(m, Arg)]
    assert len(arg_meta) == 1
    assert arg_meta[0].subcommand is True
    assert arg_meta[0].positional is True


# -- test @subcommand decorator --

def test_subcommand_decorator_injects_discriminator():
    """@subcommand('name') injects action: Literal['name'] = 'name' into the model."""

    @subcommand('deploy')
    class DeployCmd(BaseModel):
        target: str = "prod"

    assert 'action' in DeployCmd.model_fields
    field = DeployCmd.model_fields['action']
    assert field.default == 'deploy'
    # the annotation should be Literal['deploy']
    args = get_args(field.annotation)
    assert 'deploy' in args

    # should be instantiable
    inst = DeployCmd(target="staging")
    assert inst.action == 'deploy'
    assert inst.target == "staging"


def test_subcommand_decorator_custom_discriminator():
    """@subcommand supports custom discriminator field name."""

    @subcommand('build', discriminator='cmd')
    class BuildCmd(BaseModel):
        output: str = "dist"

    assert 'cmd' in BuildCmd.model_fields
    inst = BuildCmd()
    assert inst.cmd == 'build'


# -- test Program detects subcommand fields --

def test_program_detects_subcommand_map():
    """Program.model_post_init builds _subcommand_map from Subcommand fields."""
    prog = make_program(SubCmdCLI, name="test")
    assert hasattr(prog, '_subcommand_map')
    assert 'train' in prog._subcommand_map
    assert 'eval' in prog._subcommand_map
    assert prog._subcommand_map['train'] is TrainCmd
    assert prog._subcommand_map['eval'] is EvalCmd
    assert prog._subcommand_field_name == 'command'


# -- test parsing --

def test_parse_subcommand_basic():
    """tool train --epochs 10 -> correct TrainCmd with epochs=10"""
    prog = make_program(SubCmdCLI, name="tool")
    conf, _ = prog.parse_args(["train", "--epochs", "50"])
    assert isinstance(conf.command, TrainCmd)
    assert conf.command.epochs == 50
    assert conf.command.action == 'train'
    assert conf.verbose is False


def test_parse_subcommand_shared_before():
    """tool --verbose train --epochs 10 -> verbose=True on root, epochs=10 on subcmd"""
    prog = make_program(SubCmdCLI, name="tool")
    conf, _ = prog.parse_args(["--verbose", "train", "--epochs", "10"])
    assert conf.verbose is True
    assert isinstance(conf.command, TrainCmd)
    assert conf.command.epochs == 10


def test_parse_subcommand_shared_after():
    """tool train --epochs 10 --verbose -> same as shared before"""
    prog = make_program(SubCmdCLI, name="tool")
    conf, _ = prog.parse_args(["train", "--epochs", "10", "--verbose"])
    assert conf.verbose is True
    assert isinstance(conf.command, TrainCmd)
    assert conf.command.epochs == 10


def test_parse_subcommand_eval():
    """tool eval --dataset mydata.csv"""
    prog = make_program(SubCmdCLI, name="tool")
    conf, _ = prog.parse_args(["eval", "--dataset", "mydata.csv"])
    assert isinstance(conf.command, EvalCmd)
    assert conf.command.dataset == "mydata.csv"


def test_parse_subcommand_defaults():
    """subcommand with all defaults"""
    prog = make_program(SubCmdCLI, name="tool")
    conf, _ = prog.parse_args(["train"])
    assert isinstance(conf.command, TrainCmd)
    assert conf.command.epochs == 10
    assert conf.command.lr == 0.001


def test_parse_subcommand_equals_syntax():
    """tool train --epochs=50"""
    prog = make_program(SubCmdCLI, name="tool")
    conf, _ = prog.parse_args(["train", "--epochs=50"])
    assert conf.command.epochs == 50


# -- test shared option with space-separated value before subcommand --

def test_shared_option_space_value_before_subcommand():
    """tool --name myvalue subcmd should not treat 'myvalue' as a subcommand.

    Regression: the pre-subcommand scan didn't know which flags take values,
    so --name myvalue would parse 'myvalue' as an unknown subcommand name.
    """

    @subcommand('run')
    class RunCmd(BaseModel):
        count: int = 1

    @subcommand('check')
    class CheckCmd(BaseModel):
        deep: bool = False

    class NamedCLI(BaseModel):
        name: Annotated[str, Arg(help="Daemon name")] = "default"
        command: Subcommand(RunCmd, CheckCmd)

    prog = make_program(NamedCLI, name="tool")

    # space-separated value: --name myvalue run
    conf, _ = prog.parse_args(["--name", "myvalue", "run", "--count", "5"])
    assert conf.name == "myvalue"
    assert isinstance(conf.command, RunCmd)
    assert conf.command.count == 5

    # equals syntax should still work: --name=myvalue run
    conf2, _ = prog.parse_args(["--name=myvalue", "run"])
    assert conf2.name == "myvalue"
    assert isinstance(conf2.command, RunCmd)

    # flag (bool) before subcommand should not skip the next token
    class FlagCLI(BaseModel):
        verbose: Annotated[bool, Arg(short='v', help="Verbose")] = False
        name: Annotated[str, Arg(help="Name")] = "default"
        command: Subcommand(RunCmd, CheckCmd)

    prog2 = make_program(FlagCLI, name="tool")
    conf3, _ = prog2.parse_args(["-v", "--name", "foo", "check"])
    assert conf3.verbose is True
    assert conf3.name == "foo"
    assert isinstance(conf3.command, CheckCmd)


# -- test config file scoping --

def test_parse_subcommand_root_scoped_config(tmp_path):
    """tool +base.yaml train -> root-scoped merge"""
    config = tmp_path / "base.yaml"
    config.write_text("verbose: true\n")
    prog = make_program(SubCmdCLI, name="tool")
    conf, _ = prog.parse_args([f"+{config}", "train"])
    assert conf.verbose is True
    assert isinstance(conf.command, TrainCmd)


def test_parse_subcommand_scoped_config(tmp_path):
    """tool train +training.yaml -> subcommand-scoped merge"""
    config = tmp_path / "training.yaml"
    config.write_text("epochs: 99\nlr: 0.01\n")
    prog = make_program(SubCmdCLI, name="tool")
    conf, _ = prog.parse_args(["train", f"+{config}"])
    assert isinstance(conf.command, TrainCmd)
    assert conf.command.epochs == 99
    assert conf.command.lr == 0.01


def test_parse_subcommand_full_config(tmp_path):
    """full config at root with command: {action: train, epochs: 50}"""
    config = tmp_path / "full.yaml"
    config.write_text("verbose: true\ncommand:\n  action: train\n  epochs: 50\n")
    prog = make_program(SubCmdCLI, name="tool")
    conf, _ = prog.parse_args([f"+{config}"])
    assert conf.verbose is True
    assert isinstance(conf.command, TrainCmd)
    assert conf.command.epochs == 50


def test_subcommand_layered_configs_merge(tmp_path):
    """Multiple subcommand-scoped +files merge fields, not replace.

    Regression: subcommand config merge used replace strategy ({<~}),
    so the second file erased fields from the first. Fixed to recursive ({<+}).
    """
    base = tmp_path / "base.yaml"
    base.write_text("epochs: 99\nlr: 0.001\n")
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("lr: 0.5\n")
    prog = make_program(SubCmdCLI, name="tool")
    conf, _ = prog.parse_args(["train", f"+{base}", f"+{overlay}"])
    assert isinstance(conf.command, TrainCmd)
    # epochs from base survives, lr from overlay wins
    assert conf.command.epochs == 99
    assert conf.command.lr == 0.5


# -- test help output --

def test_subcommand_toplevel_help(capsys):
    """top-level --help lists commands with descriptions"""
    prog = make_program(SubCmdCLI, name="ml-tool", version="1.0")
    with pytest.raises(SystemExit):
        prog.parse_args(["--help"])
    out = capsys.readouterr().out
    assert "Commands:" in out or "commands:" in out.lower()
    assert "train" in out
    assert "eval" in out
    assert "Train a model" in out
    assert "Evaluate a model" in out


def test_subcommand_per_cmd_help(capsys):
    """per-subcommand --help shows correct args, hides discriminator"""
    prog = make_program(SubCmdCLI, name="ml-tool")
    with pytest.raises(SystemExit):
        prog.parse_args(["train", "--help"])
    out = capsys.readouterr().out
    assert "epochs" in out
    assert "lr" in out
    # discriminator 'action' should not appear
    assert "--action" not in out


def test_subcommand_help_shows_usage_with_command(capsys):
    """top-level help shows COMMAND in usage line"""
    prog = make_program(SubCmdCLI, name="ml-tool")
    with pytest.raises(SystemExit):
        prog.parse_args(["--help"])
    out = capsys.readouterr().out
    assert "COMMAND" in out


# -- test YAML config validation --

def test_subcommand_yaml_config_validates():
    """YAML config {command: {action: train, epochs: 10}} validates correctly"""
    data = {'verbose': False, 'command': {'action': 'train', 'epochs': 10, 'lr': 0.001}}
    inst = SubCmdCLI.model_validate(data)
    assert isinstance(inst.command, TrainCmd)
    assert inst.command.epochs == 10


# -- test .run() dispatch --

def test_subcommand_run_dispatch():
    """subcommand .run(ctx) receives parent instance"""

    @dracon_program(name="tool")
    class RunCLI(BaseModel):
        verbose: Annotated[bool, Arg(short='v')] = False
        command: Subcommand(TrainCmd, EvalCmd)

    result = RunCLI.cli(["--verbose", "train", "--epochs", "25"])
    assert result == {'action': 'train', 'epochs': 25, 'lr': 0.001, 'verbose': True}


def test_root_run_takes_precedence():
    """.run() on root takes precedence over subcommand .run()"""

    class SubCmd(BaseModel):
        action: Literal['sub'] = 'sub'
        def run(self, ctx):
            return 'subcmd ran'

    @dracon_program(name="tool")
    class RootRunCLI(BaseModel):
        command: Subcommand(SubCmd)
        def run(self):
            return 'root ran'

    result = RootRunCLI.cli(["sub"])
    assert result == 'root ran'


# -- test errors --

def test_unknown_subcommand_error():
    """unknown subcommand name produces an error"""
    prog = make_program(SubCmdCLI, name="tool")
    with pytest.raises(SystemExit):
        prog.parse_args(["nonexistent"])


def test_missing_subcommand_with_no_default():
    """no subcommand provided when field is required -> error"""

    class StrictCLI(BaseModel):
        command: Subcommand(TrainCmd, EvalCmd)

    prog = make_program(StrictCLI, name="tool")
    with pytest.raises(SystemExit):
        prog.parse_args([])


# -- test nested subcommands --

def test_nested_subcommands():
    """tool remote add --name origin"""

    class AddCmd(BaseModel):
        """Add a remote."""
        action: Literal['add'] = 'add'
        name: Annotated[str, Arg(help="Remote name")]

    class RemoveCmd(BaseModel):
        """Remove a remote."""
        action: Literal['remove'] = 'remove'
        name: Annotated[str, Arg(help="Remote name")]

    class RemoteCmd(BaseModel):
        """Manage remotes."""
        action: Literal['remote'] = 'remote'
        sub: Subcommand(AddCmd, RemoveCmd)

    class ListCmd(BaseModel):
        """List items."""
        action: Literal['list'] = 'list'

    class GitLikeCLI(BaseModel):
        command: Subcommand(RemoteCmd, ListCmd)

    prog = make_program(GitLikeCLI, name="git-like")
    conf, _ = prog.parse_args(["remote", "add", "--name", "origin"])
    assert isinstance(conf.command, RemoteCmd)
    assert isinstance(conf.command.sub, AddCmd)
    assert conf.command.sub.name == "origin"


# -- test config layering with subcommand overrides --

def test_config_layering_subcommand_override(tmp_path):
    """CLI args override subcommand-scoped config"""
    config = tmp_path / "training.yaml"
    config.write_text("epochs: 99\nlr: 0.01\n")
    prog = make_program(SubCmdCLI, name="tool")
    conf, _ = prog.parse_args(["train", f"+{config}", "--lr", "0.0001"])
    assert conf.command.epochs == 99
    assert conf.command.lr == 0.0001


# -- test context variables with subcommands --

def test_subcommand_with_define_vars():
    """context variables work with subcommands"""
    prog = make_program(SubCmdCLI, name="tool")
    conf, _ = prog.parse_args(["train", "--epochs", "10"])
    assert conf.command.epochs == 10


def test_subcommand_plusplus_not_parsed_as_config(tmp_path):
    """++var=value after subcommand is a context variable, not a config file.

    Regression test: ++var was parsed as + (config prefix) + +var (filename),
    because startswith('+') matched before startswith('++').
    """
    config = tmp_path / "base.yaml"
    config.write_text("!set_default my_epochs: 5\ncommand:\n  action: train\n  epochs: ${my_epochs}\n")
    prog = make_program(SubCmdCLI, name="tool")
    # ++my_epochs=42 should override the !set_default in the config
    conf, _ = prog.parse_args([f"+{config}", "++my_epochs=42"])
    assert isinstance(conf.command, TrainCmd)
    assert conf.command.epochs == 42


def test_subcommand_plusplus_after_subcmd(tmp_path):
    """++var after subcommand name should be a context variable."""
    config = tmp_path / "train.yaml"
    config.write_text("!set_default ep: 10\nepochs: ${ep}\n")
    prog = make_program(SubCmdCLI, name="tool")
    conf, _ = prog.parse_args(["train", f"+{config}", "++ep=99"])
    assert conf.command.epochs == 99


# -- test CLI raw string fallback --

class MessageApp(BaseModel):
    message: Annotated[str, Arg(positional=True, help="A text message")]


def test_cli_string_with_colons():
    """String values containing colons should fall back to raw string, not YAML-parsed."""
    prog = make_program(MessageApp, name="tool")
    conf, _ = prog.parse_args(["Step 1: do this. Step 2: do that."])
    assert conf.message == "Step 1: do this. Step 2: do that."


def test_cli_string_with_curly_braces():
    """String values with curly braces should not be YAML-parsed as dicts."""
    prog = make_program(MessageApp, name="tool")
    conf, _ = prog.parse_args(["function() { return 42; }"])
    assert conf.message == "function() { return 42; }"


def test_cli_named_arg_with_colons():
    """Named string args with colons should fall back to raw string."""

    class NamedMsg(BaseModel):
        msg: Annotated[str, Arg(help="message")] = ""

    prog = make_program(NamedMsg, name="tool")
    conf, _ = prog.parse_args(["--msg", "Step 1: foo. Step 2: bar."])
    assert conf.msg == "Step 1: foo. Step 2: bar."


# -- test @subcommand decorator with Subcommand() --

def test_decorator_subcommand_in_union():
    """@subcommand decorated classes work with Subcommand()"""

    @subcommand('start')
    class StartCmd(BaseModel):
        """Start the service."""
        port: int = 8080

    @subcommand('stop')
    class StopCmd(BaseModel):
        """Stop the service."""
        force: bool = False

    class SvcCLI(BaseModel):
        command: Subcommand(StartCmd, StopCmd)

    prog = make_program(SvcCLI, name="svc")
    conf, _ = prog.parse_args(["start", "--port", "3000"])
    assert isinstance(conf.command, StartCmd)
    assert conf.command.port == 3000
    assert conf.command.action == 'start'


# -- test LazyDraconModel as subcommand base --

def test_lazy_subcommand_model_with_interpolation():
    """LazyDraconModel subcommands resolve ${...} interpolations."""

    class LazyTrainCmd(LazyDraconModel):
        action: Literal['train'] = 'train'
        output_dir: Annotated[str, Arg(help="Output directory")] = "${BASE_DIR}/training"
        epochs: Annotated[int, Arg(help="Number of epochs")] = 10

        def run(self, ctx):
            return {'output_dir': self.output_dir, 'epochs': self.epochs, 'verbose': ctx.verbose}

    class LazyEvalCmd(LazyDraconModel):
        action: Literal['eval'] = 'eval'
        output_dir: Annotated[str, Arg(help="Output directory")] = "${BASE_DIR}/evaluation"

    @dracon_program(name="lazy-tool", context={
        'BASE_DIR': '/tmp/results',
        'LazyTrainCmd': LazyTrainCmd,
        'LazyEvalCmd': LazyEvalCmd,
    })
    class LazyCLI(BaseModel):
        verbose: Annotated[bool, Arg(short='v')] = False
        command: Subcommand(LazyTrainCmd, LazyEvalCmd)

    # interpolation resolves default
    result = LazyCLI.cli(["--verbose", "train", "--epochs", "5"])
    assert result == {'output_dir': '/tmp/results/training', 'epochs': 5, 'verbose': True}

    # CLI override replaces interpolated default
    conf = LazyCLI.cli(["train", "--output-dir", "/custom/path"])
    assert conf == {'output_dir': '/custom/path', 'epochs': 10, 'verbose': False}


def test_lazy_subcommand_model_eval_branch():
    """second union member also resolves lazy defaults."""

    class LTrainCmd(LazyDraconModel):
        action: Literal['train'] = 'train'

    class LEvalCmd(LazyDraconModel):
        action: Literal['eval'] = 'eval'
        dataset: Annotated[str, Arg(help="Dataset")] = "${DS_ROOT}/test.csv"

    @dracon_program(name="lazy-tool2", context={
        'DS_ROOT': '/data',
        'LTrainCmd': LTrainCmd,
        'LEvalCmd': LEvalCmd,
    })
    class LazyCLI2(BaseModel):
        command: Subcommand(LTrainCmd, LEvalCmd)

    conf = LazyCLI2.cli(["eval"])
    assert conf.command.dataset == '/data/test.csv'


def test_lazy_root_and_subcommand():
    """both root and subcommand can be LazyDraconModel."""

    class LzCmd(LazyDraconModel):
        action: Literal['go'] = 'go'
        path: Annotated[str, Arg()] = "${OUT}/sub"

    @dracon_program(name="all-lazy", context={
        'OUT': '/out',
        'LzCmd': LzCmd,
    })
    class AllLazyCLI(LazyDraconModel):
        base: Annotated[str, Arg()] = "${OUT}/root"
        command: Subcommand(LzCmd)

    conf = AllLazyCLI.cli(["go"])
    assert conf.base == '/out/root'
    assert conf.command.path == '/out/sub'


def test_subcommand_positional_list_str():
    """positional list[str] in subcommand passes list (not stringified) to pydantic"""

    @subcommand('submit')
    class SubmitCmd(BaseModel):
        command: Annotated[list[str], Arg(positional=True, help="Commands")]

    class CLI(BaseModel):
        sub: Subcommand(SubmitCmd)

    prog = make_program(CLI, name="repro")
    conf, _ = prog.parse_args(["submit", "echo hello"])
    assert isinstance(conf.sub, SubmitCmd)
    assert conf.sub.command == ["echo hello"]


class _FreeTextCLI(BaseModel):
    message: Annotated[str, Arg(positional=True)]


def test_cli_string_with_colons():
    """string values containing colons should not be YAML-parsed."""
    prog = make_program(_FreeTextCLI, name="tool")
    conf, _ = prog.parse_args(["Step 1: do this. Step 2: do that."])
    assert conf.message == "Step 1: do this. Step 2: do that."


def test_cli_string_with_braces():
    """string values containing braces should fall back to raw string."""
    prog = make_program(_FreeTextCLI, name="tool")
    conf, _ = prog.parse_args(["{not: valid: yaml: here}"])
    assert conf.message == "{not: valid: yaml: here}"


def test_cli_yaml_parseable_values_still_work():
    """values that are valid YAML and useful (ints, bools) should still be parsed."""

    class TypedCLI(BaseModel):
        count: Annotated[int, Arg(positional=True)]

    prog = make_program(TypedCLI, name="tool")
    conf, _ = prog.parse_args(["42"])
    assert conf.count == 42


def test_str_positional_integer_looking_value_stays_str():
    """str-typed positional arg must not be YAML-coerced to int when value looks like a number."""
    prog = make_program(_FreeTextCLI, name="tool")
    conf, _ = prog.parse_args(["1234567890"])
    assert conf.message == "1234567890"
    assert isinstance(conf.message, str)


def test_str_positional_uuid_stays_str():
    """UUID-shaped strings (all-digits or hex) must not be YAML-coerced."""
    prog = make_program(_FreeTextCLI, name="tool")
    conf, _ = prog.parse_args(["550e8400e29b41d4a716446655440000"])
    assert isinstance(conf.message, str)
    assert conf.message == "550e8400e29b41d4a716446655440000"


def test_str_positional_with_interpolation_still_composes():
    """str-typed positional containing ${var} must still do dracon interpolation."""

    class InterpCLI(BaseModel):
        path: Annotated[str, Arg(positional=True)]

    prog = make_program(InterpCLI, name="tool")
    conf, _ = prog.parse_args(["/home/${USER}/data"], context={"USER": "jean"})
    assert conf.path == "/home/jean/data"


# --- ConfigFile auto-discovery tests ---

from dracon.commandline import ConfigFile, _discover_config_files, dracon_program


class _DiscoverConfig(BaseModel):
    host: str = "default"
    port: int = 80


def test_config_file_home_dir(tmp_path):
    """auto-discovered home-dir config provides base-layer defaults."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("host: from-home\nport: 9090\n")

    @dracon_program(name="test-home", config_files=[ConfigFile(str(cfg_file))])
    class CLI(_DiscoverConfig):
        pass

    result = CLI.cli([])
    assert result.host == "from-home"
    assert result.port == 9090


def test_config_file_cli_override_wins(tmp_path):
    """explicit +file.yaml overrides auto-discovered config."""
    home_cfg = tmp_path / "home.yaml"
    home_cfg.write_text("host: from-home\nport: 9090\n")
    override_cfg = tmp_path / "override.yaml"
    override_cfg.write_text("host: from-override\n")

    @dracon_program(name="test-override", config_files=[ConfigFile(str(home_cfg))])
    class CLI(_DiscoverConfig):
        pass

    result = CLI.cli([f"+{override_cfg}"])
    assert result.host == "from-override"
    assert result.port == 9090  # still from home (not overridden)


def test_config_file_flag_override_wins(tmp_path):
    """--flag overrides both auto-discovered and explicit configs."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("host: from-home\nport: 9090\n")

    @dracon_program(name="test-flag", config_files=[ConfigFile(str(cfg_file))])
    class CLI(_DiscoverConfig):
        pass

    result = CLI.cli(["--host", "from-flag"])
    assert result.host == "from-flag"
    assert result.port == 9090


def test_config_file_required_missing():
    """required=True raises FileNotFoundError for missing files."""
    with pytest.raises(FileNotFoundError):
        _discover_config_files([ConfigFile("/nonexistent/config.yaml", required=True)])


def test_config_file_optional_missing():
    """optional (default) missing file produces no error and no configs."""
    result = _discover_config_files([ConfigFile("/nonexistent/config.yaml")])
    assert result == []


def test_config_file_search_parents(tmp_path):
    """search_parents=True emits cascade: include string for all matching files."""
    cfg_file = tmp_path / ".tool.yaml"
    cfg_file.write_text("host: found-it\n")
    child = tmp_path / "a" / "b" / "c"
    child.mkdir(parents=True)

    old_cwd = os.getcwd()
    try:
        os.chdir(str(child))
        found = _discover_config_files([ConfigFile(".tool.yaml", search_parents=True)])
        assert len(found) == 1
        assert found[0] == "cascade:.tool.yaml"
    finally:
        os.chdir(old_cwd)


def test_config_file_search_parents_not_found(tmp_path):
    """search_parents with no match returns empty list."""
    child = tmp_path / "a" / "b"
    child.mkdir(parents=True)

    old_cwd = os.getcwd()
    try:
        os.chdir(str(child))
        found = _discover_config_files([ConfigFile(".nonexistent.yaml", search_parents=True)])
        assert found == []
    finally:
        os.chdir(old_cwd)


def test_config_file_multiple_layered(tmp_path):
    """multiple ConfigFiles are layered in declaration order."""
    base = tmp_path / "base.yaml"
    base.write_text("host: base\nport: 80\n")
    layer = tmp_path / "layer.yaml"
    layer.write_text("host: layered\n")

    @dracon_program(
        name="test-multi",
        config_files=[ConfigFile(str(base)), ConfigFile(str(layer))],
    )
    class CLI(_DiscoverConfig):
        pass

    result = CLI.cli([])
    assert result.host == "layered"  # second config wins
    assert result.port == 80  # from first config


def test_config_file_from_config(tmp_path):
    """from_config() also applies auto-discovery."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("host: auto-discovered\n")
    extra = tmp_path / "extra.yaml"
    extra.write_text("port: 1234\n")

    @dracon_program(name="test-fc", config_files=[ConfigFile(str(cfg_file))])
    class CLI(_DiscoverConfig):
        pass

    result = CLI.from_config(str(extra))
    assert result.host == "auto-discovered"
    assert result.port == 1234


def test_config_file_selector(tmp_path):
    """ConfigFile with selector extracts a subtree."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("section:\n  host: selected\n  port: 4321\n")

    found = _discover_config_files([ConfigFile(str(cfg_file), selector="section")])
    assert len(found) == 1
    assert found[0].endswith("@section")


def test_config_file_required_search_parents(tmp_path):
    """required=True + search_parents=True raises when not found."""
    child = tmp_path / "deep" / "dir"
    child.mkdir(parents=True)

    old_cwd = os.getcwd()
    try:
        os.chdir(str(child))
        with pytest.raises(FileNotFoundError):
            _discover_config_files([
                ConfigFile(".nonexistent.yaml", search_parents=True, required=True)
            ])
    finally:
        os.chdir(old_cwd)


def test_config_file_search_parents_absolute_path_errors():
    """search_parents with an absolute path raises ValueError."""
    with pytest.raises(ValueError, match="meaningless with absolute path"):
        _discover_config_files([
            ConfigFile("/absolute/path.yaml", search_parents=True)
        ])


def test_subcommand_nested_override_with_config_file(tmp_path):
    """--nested.field on subcommand should win over +config values."""

    class Inner(BaseModel):
        value: int = 100

    @subcommand("run")
    class RunCmd(BaseModel):
        inner: Inner = Inner()

    class CLI(BaseModel):
        command: Subcommand(RunCmd)

    config_file = tmp_path / "config.yaml"
    config_file.write_text("inner:\n  value: 50\n")

    prog = make_program(CLI, name="tool")
    conf, _ = prog.parse_args(["run", f"+{config_file}", "--inner.value", "10"])
    assert conf.command.inner.value == 10


# ---- raw=True Arg tests ----


class RawArgConfig(BaseModel):
    body: Annotated[str, Arg(positional=True, raw=True)]
    name: str = "default"


class RawKeywordConfig(BaseModel):
    command: Annotated[str, Arg(raw=True, help="a command string")]
    count: int = 1


class MixedRawConfig(BaseModel):
    body: Annotated[str, Arg(positional=True, raw=True)]
    workers: Annotated[int, Arg(help="worker count")] = 4
    tag: str = "default"


@pytest.fixture
def raw_positional_program():
    return make_program(RawArgConfig, name="raw-test")


@pytest.fixture
def raw_keyword_program():
    return make_program(RawKeywordConfig, name="raw-kw-test")


@pytest.fixture
def mixed_raw_program():
    return make_program(MixedRawConfig, name="mixed-raw-test")


def test_raw_positional_json_string(raw_positional_program):
    """raw=True positional receives JSON string as-is, not parsed as dict."""
    json_str = '{"type":"question","question":"merge?"}'
    config, _ = raw_positional_program.parse_args([json_str])
    assert config.body == json_str
    assert isinstance(config.body, str)


def test_raw_positional_dollar_sign(raw_positional_program):
    """raw=True positional preserves dollar signs without interpolation."""
    config, _ = raw_positional_program.parse_args(["echo $PATH"])
    assert config.body == "echo $PATH"


def test_raw_positional_colon_yaml(raw_positional_program):
    """raw=True positional keeps 'key: value' as string, not parsed as YAML mapping."""
    config, _ = raw_positional_program.parse_args(["key: value"])
    assert config.body == "key: value"
    assert isinstance(config.body, str)


def test_raw_keyword_json_string(raw_keyword_program):
    """raw=True keyword arg receives JSON string as-is."""
    json_str = '{"cmd":"run","args":[1,2]}'
    config, _ = raw_keyword_program.parse_args(["--command", json_str])
    assert config.command == json_str


def test_raw_keyword_dollar_sign(raw_keyword_program):
    """raw=True keyword arg preserves dollar signs."""
    config, _ = raw_keyword_program.parse_args(["--command", "echo $HOME"])
    assert config.command == "echo $HOME"


def test_raw_keyword_colon_yaml(raw_keyword_program):
    """raw=True keyword arg keeps colon strings as-is."""
    config, _ = raw_keyword_program.parse_args(["--command", "host: localhost"])
    assert config.command == "host: localhost"


def test_raw_keyword_equals_syntax(raw_keyword_program):
    """raw=True works with --arg=value equals syntax."""
    config, _ = raw_keyword_program.parse_args(["--command=echo $PATH"])
    assert config.command == "echo $PATH"


def test_raw_alongside_normal_fields(mixed_raw_program):
    """raw=True field works alongside normal (non-raw) parsed fields."""
    config, _ = mixed_raw_program.parse_args([
        '{"data": true}', "--workers", "8", "--tag", "prod"
    ])
    assert config.body == '{"data": true}'
    assert config.workers == 8
    assert config.tag == "prod"


def test_raw_false_still_parses_normally():
    """raw=False (default) still goes through normal YAML composition."""
    class NormalConfig(BaseModel):
        count: Annotated[int, Arg(positional=True)]

    prog = make_program(NormalConfig, name="normal-test")
    config, _ = prog.parse_args(["42"])
    assert config.count == 42
    assert isinstance(config.count, int)


# ── lazy interpolable resolution before model_validate ───────────────────────

def test_set_default_interpolation_into_typed_field():
    """${...} from !set_default resolves before pydantic validates typed fields."""
    import tempfile

    @subcommand('run')
    class RunCmd(BaseModel):
        action: str = 'run'
        def run(self, ctx):
            return ctx.items

    @dracon_program(name="test-lazy-typed")
    class CLI(BaseModel):
        items: list[str] = []
        command: Subcommand(RunCmd)

    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f1:
        f1.write("!set_default greeting: hello\n")
        f1.flush()
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f2:
            f2.write('items:\n  - "say ${greeting}"\n')
            f2.flush()
            result = CLI.cli([f"+{f1.name}", f"+{f2.name}", "run"])
            assert result == ["say hello"]


def test_interpolation_into_primitive_field():
    """${...} into a plain str field on root model resolves before validation."""
    import tempfile

    @dracon_program(name="test-prim")
    class CLI(BaseModel):
        name: str = "default"

    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write('!set_default who: world\nname: "hello ${who}"\n')
        f.flush()
        conf = CLI.cli([f"+{f.name}"])
        assert conf.name == "hello world"


def test_interpolation_into_int_field():
    """${...} arithmetic into an int field resolves before validation."""
    import tempfile

    @dracon_program(name="test-int")
    class CLI(BaseModel):
        count: int = 0

    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write('!set_default n: 5\ncount: "${n * 2}"\n')
        f.flush()
        conf = CLI.cli([f"+{f.name}"])
        assert conf.count == 10
