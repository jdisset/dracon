# Dracon

<img src="https://raw.githubusercontent.com/jdisset/dracon/main/docs/dracon_logo.svg" alt="Dracon Logo" width="250"/>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Dracon is a modular configuration system and command-line interface (CLI) generator for Python, built upon YAML. It extends standard YAML with powerful features to help manage complex application configurations effectively, integrating seamlessly with Pydantic.

Need to juggle static config files, environment variables, complex overrides, and boilerplate CLI argument parsing? Dracon provides a unified approach:

#### Compose Your Configurations

Load, merge, reuse and include configurations from whole YAML files or parts of them, from packages, environment variables or custom sources, using a powerful merge and include syntax (`!include`, `<<{dict_opts}[list_opts]@path.to.subey`). Manipulate the configuration graph with instructions like `!each(...)` and `!if`.

#### Generate CLIs Automatically

Create elegant, robust, type-safe CLIs that leverage all of dracon's features, and is generated directly from your app class.
Dracon will automatically handle argument parsing, config file loading and layering, positional arguments, flags and overrides.
You can extend, override, or merge any part - even deeply nested - of your app's configuration at runtime, either from inline command-line arguments (`-k value`, `--nested.arg 42`) or from sources like files (`+localfile.yaml`, `--nested.object +from/file`, `--arg +from/file@specific.key`,...).
You can distribute your app with some default configuration values and files, and the user can override any part with their own.
A detailed help and usage message is automatically generated:

<img
  src="https://raw.githubusercontent.com/jdisset/dracon/dev/docs/assets/cli_help.png"
  alt="CLI help screenshot"
    width="650"
    height="auto"
    />

#### Add (Lazy-Evaluated) Expressions

Embed Python expressions (`${...}`) for lazy evaluation, reference other keys (`@path`), or use immediate evaluation (`$(...)`) for values computed at runtime based on context or other configuration parts. Define scoped and global variables with `!define` and `!set_default`.

#### Define Configuration Once

Use Pydantic models for type-safe configuration structures (`!MyModel`). Dracon will handle the conversion between YAML and Pydantic seamlessly.

## Quick Start: CLI

Let's build a simple application configured via YAML and CLI arguments.

**1. Define Models (`models.py`):**

```python
from pydantic import BaseModel, Field
from typing import Annotated, Literal
from dracon import Arg, DeferredNode, construct

class DatabaseConfig(BaseModel):
    host: str = 'localhost'
    port: int = 5432
    username: str
    password: str

class AppConfig(BaseModel):

    input_path: Annotated[Optionalpstr, Arg(help="Example of positional argument.", positional=True), ]
    database: Annotated[DatabaseConfig, Arg(help="Database conf.")] = Field(default_factory=DatabaseConfig) # Use default_factory for nested models
    environment: Annotated[Literal['dev','prod','test'], Arg(short='e', help="Deployment env.")] # required arg since no default
    log_level: Annotated[Literal["DEBUG", "INFO", "WARNING", "ERROR"], Arg(help="Logging level")] = "INFO"
    workers: Annotated[int, Arg(help="Number of worker processes.")] = 1
    output_path: Annotated[DeferredNode[str], Arg(help="Path for output files.")] # Output path depends on runtime context (e.g., based on other config)

    def process_data(self):
        # Example method using the config
        print(f"Processing for environment: {self.environment}")
        print(f"  DB: {self.database.username}@{self.database.host}:{self.database.port}")
        print(f"  Workers: {self.workers}, Log Level: {self.log_level}")

        # Provide needed context for the deferred output_path field.
        # 'construct' takes the DeferredNode and context to produce the final value.
        final_output = construct(
            self.output_path,
            context={'computed_runtime_value': self.generate_unique_id()}
        )
        print(f"  Output Path: {final_output}")

    def generate_unique_id(self):
        # Example helper function to generate a value based on config
        from time import time
        return f"{self.environment}_{self.database.host}_{self.workers}_{int(time())}"
```

**2. Base Configuration (`config/base.yaml`):**

```yaml title="config/base.yaml"
log_level: ${getenv('LOG_LEVEL', 'INFO')} # Use env var or default INFO

database:
  host: "db.${@/environment}.local" # Dynamically set host based on 'environment' key in the final config
  port: 5432
  username: !include file:$DIR/db_user.secret # $DIR contains the path to the current file's directory
  password: !include env:DB_PASS # Load from environment variable DB_PASS

output_path: "/data/${computed_runtime_value}/output" # Output path uses interpolation needing runtime context
```

**3. Production Overrides (`config/prod.yaml`):**

```yaml title="config/prod.yaml"
environment: production # Set environment directly
log_level: WARNING
workers: 4

database: # Only override specific DB fields for prod
  host: "db.prod.svc.cluster.local"
  username: prod_db_user

<<: !include file:base.yaml # merge base
```

**4. Secret File (`config/db_user.secret`):**

```text title="config/db_user.secret"
base_user
```

**5. Main CLI Script (`main.py`):**

```python title="main.py"
import sys
from dracon import make_program

program = make_program(AppConfig, name="my-cool-app", description="My cool application using Dracon.")

if __name__ == "__main__":
    cli_config, raw_args = program.parse_args(sys.argv[1:])
    # cli_config is now a fully populated and validated AppConfig instance
    cli_config.process_data() # Use the final config object
```

**6. Running the CLI:**

```bash
$ python main.py --help # Show help

# Run with development environment (required arg). Needs DB_PASS env var.
$ export DB_PASS="dev_secret"
$ python main.py -e dev
# Output uses defaults from base.yaml and Pydantic, env var for password.
# DB Host will be db.dev.local

# Set LOG_LEVEL env var and run for prod using prod.yaml overrides
$ export LOG_LEVEL=DEBUG
$ export DB_PASS="prod_secret"
$ python main.py +config/prod.yaml --workers 8 # Load prod config, override workers
# Output uses values from prod.yaml (merged onto base.yaml),
# DB_PASS=prod_secret, LOG_LEVEL=DEBUG (from env var), workers=8 (from CLI override).
# DB Host will be db.prod.svc.cluster.local

# Define a context variable (only useful if YAML used ${my_var})
$ python main.py -e prod --define.my_var=some_value

# Pass a file path as a value for an argument marked with is_file=True
# (or use '+' prefix to force loading even without is_file)
$ echo "cli_user" > local_user.secret
$ python main.py -e prod --database.username +local_user.secret

# Use the prod config but override the entire database block with a different file
$ python main.py +config/prod --database +config/staging_db.yaml

# Use default settings but pass some manual overrides
$ python main.py -e test --database.port 4567

# Override a nested value using a value from *another* file's nested path
$ python main.py +config/prod --database.port +config/base@database.port
```

## Quick Start: YAML Loader + Dump

```python
import dracon as dr
from pydantic import BaseModel

# --- Define a Pydantic Model ---
class MyPydanticModel(BaseModel):
    some_key: str
    some_attr: dict
    log_level: str = "INFO"

# --- Loading ---
# Load a config file (requires models in context if using tags like !MyPydanticModel)
conf_obj = dr.load('examples/config/base.yaml', context={'AppConfig': AppConfig, 'DatabaseConfig': DatabaseConfig})

# Load a config file and provide runtime context for interpolation
conf_obj_ctx = dr.load('examples/config/prod.yaml', context={'AppConfig': AppConfig, 'DatabaseConfig': DatabaseConfig, 'base_path': '/runtime/data'})

# Load a config from a string
yaml_string = """
!MyPydanticModel
some_key: !include file:some_file.txt # Include another file
some_attr:
  key1: val1
log_level: ${getenv('LOG_LEVEL', 'INFO')} # Interpolate from environment
"""
conf_from_str = dr.loads(yaml_string, context={'MyPydanticModel': MyPydanticModel})
assert isinstance(conf_from_str, MyPydanticModel)

# Load and merge multiple YAML files sequentially (later files override earlier ones by default)
stacked_conf_obj = dr.load(
    ['examples/config/base.yaml', 'examples/config/prod.yaml'],
    context={'AppConfig': AppConfig, 'DatabaseConfig': DatabaseConfig, 'base_path': '/runtime/data'}
)

# --- Dumping ---
# Dump a Pydantic object back to YAML
obj = MyPydanticModel(some_key="key_val", some_attr={'nested': True}, log_level="DEBUG")
yaml_str = dr.dump(obj)
print(yaml_str)
# Output (example):
# !MyPydanticModel
# some_key: key_val
# some_attr:
#   nested: true
# log_level: DEBUG

# Note: Dracon uses ruamel.yaml internally and supports custom serialization
# via a `dracon_dump_to_node` method on your classes.
```

## Where to Go Next?

- **[Tutorial: Building a CLI App](tutorials/cli_app.md):** A step-by-step guide to build the example above from scratch.
- **[How-To Guides](guides/index.md):** Find recipes for common configuration and CLI tasks.
- **[Conceptual Guides](concepts/index.md):** Understand the principles behind Dracon's features.
- **[Reference](reference/index.md):** Look up detailed syntax and API information.

## Acknowledgements

- [Pydantic](https://docs.pydantic.dev/) for its powerful data validation and settings management.
- [ruamel.yaml](https://yaml.readthedocs.io/en/latest/) for the core YAML parsing and serialization.
- [asteval](https://lmfit.github.io/asteval/) for the safe expression evaluation engine.
- [Diátaxis Framework](https://diataxis.fr/) which heavily inspired the documentation structure.
