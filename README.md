# Dracon

<img src="https://raw.githubusercontent.com/jdisset/dracon/main/docs/dracon_logo.svg" alt="Dracon Logo" width="250"/>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Documentation](https://img.shields.io/badge/docs-available-brightgreen.svg)](https://jdisset.github.io/dracon/)

Dracon is a configuration system and CLI generator for Python, built on YAML. It's for projects that need flexible, explicit, and composable configs, without magic or friction.

### Why Dracon?

Most config systems I've had the pleasure to deal with were either:

- **Too simple** ("just a dict, argparse, and pain")
- **Too magical** (opaque, sometimes bespoke frameworks that obscure what's actually in use), or
- **Too rigid** (I have a lot of respect for Hydra, but often found myself fighting the "Proper Way" instead of getting work done).

I built Dracon to hit the "powerful but transparent" sweet spot, especially for
modern ML and research codebases, where you need to juggle random YAML files
coming from your packages, your local machine, and your users. Adding to that
are environment variables, N layers of overrides, and boilerplate CLI argument
parsing. Dracon gives you simple tools to catch all of these moving pieces and
turn them into a structured, type safe, highly configurable system.
Minimal ceremony, maximum efficiency.

### Seamless Python Integration

A single decorator turns any Pydantic model into a complete CLI application:

```python
@dracon_program(name="my-app")
class Config(BaseModel):
    learning_rate: float = 0.001
    epochs: int = 100

    def run(self):
        train(self.learning_rate, self.epochs)

# That's it. Now you have:
Config.cli()                    # Full CLI with --help, config files, overrides
Config.invoke("+config.yaml")   # Load config and run
Config.from_config("cfg.yaml")  # Load config as validated instance
```

Turn YAML configs into reusable factory functions:

```python
create_model = make_callable("model.yaml", context_types=[ModelConfig])
model1 = create_model(layers=3)
model2 = create_model(layers=5)
```

### Key Features

- **`@dracon_program` decorator**: Turn any Pydantic model into a CLI app with one line
- **`make_callable`**: Transform YAML configs into reusable factory functions
- **Layered config**: YAML with environment/CLI overrides, includes, variables, and Python expressions
- **Pydantic integration**: Type safety and validation out of the box
- **Auto CLI generation**: Every field becomes a CLI flag, including nested ones
- **Deferred execution**: Runtime injection of values not available at load time
- **Composability**: Mix and match configs for experiments, environments, model variants

#### Compose Your Configurations

Merge configs from files, packages, or environment variables using `!include` and `<<{...}@path`. Manipulate configs with `!each` and `!if`.

#### Generate CLIs Automatically

Generate type-safe CLIs directly from Pydantic models. Override any field-even nested ones-via command line (`--nested.arg 42`) or files (`+config.yaml`, `--arg +file@key`). Help is auto-generated:

<img
  src="https://raw.githubusercontent.com/jdisset/dracon/main/docs/assets/cli_help.png"
  alt="CLI help screenshot"
    width="650"
    height="auto"
    />

#### Add Expressions

Embed Python expressions (`${...}`), reference other keys (`@path`), or compute values at runtime (`$(...)`). Define variables with `!define` and `!set_default`.

#### Define Configuration Once

Use Pydantic models for type-safe configs (`!MyModel`). Dracon handles YAML <-> Pydantic conversion seamlessly.

## Quick Start: CLI with `@dracon_program`

The `@dracon_program` decorator is the easiest way to turn a Pydantic model into a full CLI application:

```python
from pydantic import BaseModel
from typing import Annotated, Literal
from dracon import dracon_program, Arg, DeferredNode

class DatabaseConfig(BaseModel):
    host: str = 'localhost'
    port: int = 5432
    username: str = "admin"
    password: str = ""

@dracon_program(
    name="my-app",
    description="My application with database support",
    context_types=[DatabaseConfig],  # Make DatabaseConfig available for !Tags
)
class AppConfig(BaseModel):
    database: DatabaseConfig
    environment: Annotated[Literal['dev', 'prod'], Arg(short='e', help="Deployment env")]
    workers: Annotated[int, Arg(help="Number of workers")] = 4
    output_path: DeferredNode[str] = "/tmp/output"  # Resolved at runtime

    def run(self):
        """Called by .invoke() after config is loaded."""
        print(f"Running in {self.environment} with {self.workers} workers")
        # Construct deferred value with runtime context
        final_output = self.output_path.construct(
            context={'run_id': f"{self.environment}_{self.workers}"}
        )
        print(f"Output: {final_output}")
        return self.workers

# Multiple ways to use:
if __name__ == "__main__":
    AppConfig.cli()  # Run as CLI (parses sys.argv)
```

**Config file (`config.yaml`):**

```yaml
database:
  host: "db.${@/environment}.local"
  port: 5432
  username: !include env:DB_USER
  password: !include env:DB_PASS

environment: prod
workers: 8
output_path: "/data/${run_id}/output"
```

**Running:**

```bash
# Run with config file
$ python main.py +config.yaml

# Override specific values
$ python main.py +config.yaml -e dev --workers 2

# Pass context variables for interpolation
$ python main.py +config.yaml ++run_id my_experiment

# Load config programmatically
result = AppConfig.invoke("+config.yaml")           # Load, validate, run()
instance = AppConfig.from_config("config.yaml")     # Load and validate only
```

## Alternative: `make_program`

For more control over the CLI program, use `make_program` directly:

```python
from dracon import make_program

program = make_program(AppConfig, name="my-app")
config, raw_args = program.parse_args()
config.run()
```

## Reusable Config Functions: `make_callable`

Turn a YAML config into a reusable callable:

```python
from dracon import make_callable

# Create a callable from a config file
create_model = make_callable(
    "model_config.yaml",
    context_types=[ModelConfig],
)

# Call with different parameters
model1 = create_model(learning_rate=0.01)
model2 = create_model(learning_rate=0.001)
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

- **[Tutorial: Building a CLI App](https://jdisset.github.io/dracon/tutorials/cli_app/)**: Step-by-step guide to build the example above
- **[How-To Guides](https://jdisset.github.io/dracon/guides/)**: Recipes for common tasks
- **[Conceptual Guides](https://jdisset.github.io/dracon/concepts/)**: Understand Dracon's design
- **[Reference](https://jdisset.github.io/dracon/reference/)**: Syntax and API details

## Acknowledgements

- [Pydantic](https://docs.pydantic.dev/) for data validation and settings management
- [ruamel.yaml](https://yaml.dev/doc/ruamel.yaml/) for YAML parsing and serialization
- [asteval](https://lmfit.github.io/asteval/) for safe expression evaluation
- [Diataxis Framework](https://diataxis.fr/) for documentation structure inspiration
