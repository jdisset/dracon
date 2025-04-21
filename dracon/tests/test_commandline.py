import pytest
import sys
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Annotated, Optional
import subprocess
import os

from dracon import Arg, DeferredNode, construct, DraconLoader, make_program, DraconError
from dracon.commandline import ArgParseError
from dracon.loader import dump_to_node


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

    def run(self):
        print("----- AppConfig.run() starting -----")
        print(f"Running in {self.environment} mode with {self.workers} workers.")
        db_path = self.get_base_path_from_db()
        print(f"got base path from db: {db_path}")
        print(f"constructing output_path: {self.output_path}")
        # constructed_output = construct(self.output_path, context={'base_output_path': db_path})
        constructed_output = self.output_path.construct(context={'base_output_path': db_path})
        print(f"constructed output path: {constructed_output}")
        print("----- AppConfig.run() finished -----")
        return constructed_output

    def get_base_path_from_db(self):
        print("... simulating db fetch for base path ...")
        return f"{self.database.host}_{self.database.port}"


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

    yield tmp_path

    # clean up sys.path
    sys.path.pop(0)
    print(f"cleaned up tmp path: {tmp_path}")


@pytest.fixture
def program():
    """create the dracon program instance"""
    # pass the model definitions to the context
    print("creating Program instance...")
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
    assert "--database.host" in captured.out
    assert "--output-path" in captured.out
    assert "--database" in captured.out  # check the parent arg exists


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
        "--define.my_var=42",  # define context variable
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
    assert "Field 'environment': Field required" in captured.err
    assert "Field 'database': Field required" in captured.err
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
    assert "Error: Unknown argument '--unknown-arg'" in captured.err
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
    assert "Error: Expected value for argument -e" in captured.err
    assert "Usage: simple-app [OPTIONS]" in captured.out  # help should be printed

    with pytest.raises(SystemExit):  # expect exit after printing help
        print("parsing ['--workers']...")
        program.parse_args(["--workers"])  # missing value for workers

    captured = capfd.readouterr()
    print(f"captured stderr:\n{captured.err}")
    print(f"captured stdout:\n{captured.out}")
    assert "Error: Expected value for argument --workers" in captured.err
    assert "Usage: simple-app [OPTIONS]" in captured.out  # help should be printed

    # TODO
    # add more tests for boolean flags, different data types, etc.
