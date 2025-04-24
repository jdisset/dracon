import pytest
import sys
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Annotated, Optional, List
import subprocess
import os

from dracon import Arg, DeferredNode, construct, DraconLoader, make_program, DraconError
from dracon.commandline import ArgParseError
from dracon.loader import dump_to_node
from dracon import CompositionResult, DraconMappingNode


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
        f"+{db_prod_conf}",  # override entire database section
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


def test_required_args_missing(program, capfd):
    """test error handling when required args are missing"""
    print("\n--- test_required_args_missing ---")
    with pytest.raises(SystemExit):  # expecting sys.exit(0) after printing help
        print("parsing []...")
        program.parse_args([])  # missing environment and database fields

    captured = capfd.readouterr()
    print(f"captured stderr:\n{captured.err}")
    print(f"captured stdout:\n{captured.out}")
    # check for pydantic-style error messages in stderr
    assert "error: field 'environment': Field required" in captured.err
    assert "error: field 'database': Field required" in captured.err
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
    assert "error: field 'workers': Input should be a valid integer" in captured.err
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
        "--inner-field.value",  # override inner field value
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
