# Welcome to Dracon!

Managing configuration for Python applications can quickly become complex. Juggling static YAML files, environment variables, complex override logic, and writing boilerplate for command-line interfaces is often cumbersome.

Dracon is a modular configuration system and CLI generator built upon YAML, designed to streamline this process. It extends standard YAML with powerful, intuitive features for building robust and maintainable Python applications.

## Why Dracon?

Dracon addresses common configuration challenges by providing:

- **Seamless Modularity (`!include`):** Load and compose configuration from files, Python packages, environment variables, or even reuse parts of the same document using includes and anchors (with copy-by-default semantics).
- **Dynamic Values (Interpolation):** Embed Python expressions (`${...}`) directly in YAML for values computed lazily at runtime. Reference context variables, other configuration keys (`@path`), or even YAML nodes (`&node`). Use immediate evaluation (`$(...)`) for dynamic tags or parse-time values.
- **Powerful Merging (`<<{opts}[opts]@path:`):** Precisely control how configuration sources are combined using flexible strategies for dictionaries and lists (append/replace, new/existing wins, recursive depth).
- **Type Safety (Pydantic Integration):** Define your configuration structure with Pydantic models (`!MyModel`) and let Dracon handle validation and construction, catching errors early.
- **Effortless CLI Generation:** Automatically build type-safe, documented command-line interfaces directly from your Pydantic configuration models (`make_program`, `Arg`), integrating config file loading (`+file.yaml`) and argument overrides (`--key value`).
- **Fine-Grained Control Flow:** Delay object construction (`!deferred`) for late context binding or manage initialization order. Defer final value processing (`Resolvable[T]`) for post-load adjustments, especially useful with CLIs.

## Quick Start: Configuration & CLI Example

Let's illustrate how Dracon combines configuration loading and CLI generation.

**1. Define Your Configuration Model (`models.py`):**

```python
# models.py
from pydantic import BaseModel
from typing import Annotated
from dracon import Arg, Resolvable # Import Arg for CLI customization

class DatabaseConfig(BaseModel):
    host: str
    port: int = 5432
    username: str
    password: str # Loaded via include

class AppConfig(BaseModel):
    app_name: Annotated[str, Arg(help="The name of the application.")] = "MyAwesomeApp"
    environment: Annotated[str, Arg(short='e', help="Deployment environment (dev, staging, prod).")]
    log_level: Annotated[str, Arg(help="Logging level.")] = "INFO"
    workers: Annotated[int, Arg(help="Number of worker processes.")] = 1
    database: DatabaseConfig # Nested model
    # Example of a value that might be finalized after CLI parsing
    output_path: Annotated[Resolvable[str], Arg(resolvable=True, help="Path for output files.")] = "/tmp/output"

```

**2. Base Configuration (`config/base.yaml`):**

```yaml
# Use the AppConfig model - Dracon finds it via context
!AppConfig # Use environment variables with defaults
environment: ${getenv('APP_ENV', 'development')}
log_level: ${getenv('LOG_LEVEL', 'INFO')}

database:
  # Use a value from the main config section via @ reference
  # KeyPaths allow navigating the structure. See KeyPaths page for details.
  host: "db.${@/environment}.myapp.com"
  port: 5432
  # Include sensitive data from another file
  # $DIR is automatically provided, points to the directory of this file.
  username: !include file:$DIR/db_user.txt
  password: !include file:$DIR/db_pass.secret

# Default output path, potentially overridden
output_path: "/data/default_output"
```

**3. Environment Override (`config/prod.yaml`):**

```yaml
# Include the base configuration first
<<: !include file:base.yaml

# Override specific values for production
environment: production
log_level: WARNING
workers: 4 # Increase workers for prod

database:
  # Merge new/override values into the database section from base.yaml
  # {+<} = recursively merge dicts, new values win. See Merging page.
  <<{+<}:
    host: "db.prod.myapp.com" # Specific prod host

# Override output path for production
output_path: "/data/prod_output"
```

**4. Secret Files (`config/db_user.txt`, `config/db_pass.secret`):**

```yaml
# config/db_user.txt
prod_db_user
```

```yaml
# config/db_pass.secret
very_$ecret_Pa$$word
```

**5. Main Application (`main.py`):**

```python
# main.py
import sys
from dracon import DraconLoader, make_program, Resolvable
from models import AppConfig, DatabaseConfig # Import your models

# --- Configuration Loading ---
# Provide models to the loader's context
loader = DraconLoader(context={'AppConfig': AppConfig, 'DatabaseConfig': DatabaseConfig})

# Load base config, then merge production overrides
config = loader.load(["config/base.yaml", "config/prod.yaml"]) # Load sequence implies merge

print("--- Loaded Config (prod) ---")
print(f"App Name: {config.app_name}")
print(f"Environment: {config.environment}")
print(f"Log Level: {config.log_level}")
print(f"Workers: {config.workers}")
print(f"DB Host: {config.database.host}") # Note: uses 'prod' from override
print(f"DB User: {config.database.username}")
print(f"Output Path (initial): {config.output_path}") # Still Resolvable
print("-" * 20)

assert isinstance(config, AppConfig)
assert isinstance(config.output_path, Resolvable) # Not resolved yet

# Resolve the output path later in the app if needed
final_output = config.output_path.resolve()
print(f"Output Path (resolved): {final_output}")
print("-" * 20)


# --- CLI Generation ---
program = make_program(
    AppConfig,
    name="my-cool-app",
    description="My cool application using Dracon."
)

if __name__ == "__main__":
    try:
        # Parse arguments, loads files starting with '+' and applies CLI overrides
        cli_config, raw_args = program.parse_args(sys.argv[1:])

        print("\n--- CLI Result ---")
        print(f"Environment: {cli_config.environment}")
        print(f"Log Level: {cli_config.log_level}")
        print(f"Workers: {cli_config.workers}")
        print(f"DB Host: {cli_config.database.host}")
        print(f"Output Path (CLI): {cli_config.output_path.resolve()}") # Resolve it
        print("-" * 20)

        # Example: Run the app with the final config
        # run_application(cli_config)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
```

**6. Running the CLI:**

```bash
# See the auto-generated help message
$ python main.py --help
```

_(Example `--help` Output)_

```text
 Usage: my-cool-app [OPTIONS]

 My cool application using Dracon.

 ────────────────────────────────────────────────────────────────────────────

 Options:
  --app-name          STR      The name of the application.
                               default: "MyAwesomeApp"

  -e, --environment   STR      Deployment environment (dev, staging, prod).
                               REQUIRED

  --log-level         STR      Logging level.
                               default: "INFO"

  --workers           INTEGER  Number of worker processes.
                               default: 1

  --database.host     STR
  --database.port     INTEGER
                               default: 5432

  --database.username STR
  --database.password STR
  --output-path       STR      Path for output files.
                               default: "/tmp/output"

  -h, --help                   Print this help message

```

```bash
# Run with defaults, loading base.yaml (implicitly if named config.yaml)
# python main.py -e dev

# Run loading production config first, then overriding log level via CLI
$ python main.py +config/prod.yaml --log-level DEBUG -e prod

# Define a context variable for interpolation (if YAML used ${MY_VAR})
# $ python main.py --define.MY_VAR=some_value -e prod
```

This example demonstrates includes, environment variables, `@` references, Pydantic model integration, CLI generation with help text, config file loading (`+`), and CLI overrides.

## Core Concepts

Explore the core features in more detail:

- **[Loading Configuration](loading.md):** Using `DraconLoader` and providing context.
- **[Includes (Modularity)](includes.md):** Combining configurations with `!include`.
- **[Interpolation (Dynamic Values)](interpolation.md):** Using `${...}`, `$(...)`, `@`, and `&` for dynamic configurations.
- **[Merging Configurations](merging.md):** Advanced control over combining dictionaries and lists using `<<{...}[...]@`.
- **[Instructions (Composition Logic)](instructions.md):** Embedding logic with `!define`, `!if`, `!each`.
- **[Working with Types](types.md):** Leveraging Pydantic and custom types.
- **[Command-Line Interfaces](cli.md):** Generating CLIs from Pydantic models.
- **[Advanced Control Flow](deferred.md):** Using `!deferred` and `Resolvable[T]` for complex initialization.

## Next Steps

Dive deeper into the documentation sections linked above to master Dracon's capabilities.
