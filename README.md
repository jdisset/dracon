# Dracon

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

![Dracon Logo](https://raw.githubusercontent.com/jdisset/dracon/main/docs/logo_dracon.svg)

Dracon is a modular configuration system and command-line interface (CLI) generator for Python, built upon YAML. It extends standard YAML with powerful features to help manage complex application configurations effectively.

Tired of juggling static config files, environment variables, complex overrides, and boilerplate CLI argument parsing? Dracon provides a unified approach, integrating configuration loading, dynamic value generation, type safety via Pydantic, and CLI creation into a cohesive system.

## Key Features

- **Modular Configurations (`!include`):** Load and compose configuration from files, Python packages, environment variables, or even other parts of the same document using includes and anchors (with copy-by-default semantics for reuse).
- **Dynamic Values (Interpolation):** Embed Python expressions (`${...}`) directly in your YAML for values computed at runtime, referencing context variables or other configuration keys (`@path`). Use immediate evaluation (`$(...)`) for dynamic tags or parse-time values.
- **Advanced Merging (`<<{opts}[opts]@path:`):** Precisely control how different configuration sources (files, defaults, overrides) are merged using flexible strategies for dictionaries and lists.
- **Type Safety (Pydantic Integration):** Use familiar Pydantic models (`!MyModel`) to automatically validate your configuration structure and data types upon loading, catching errors early.
- **Controlled Construction (`!deferred`):** Delay the creation of specific configuration objects until needed, allowing for late-binding of context or manual initialization order.
- **CLI Generation:** Automatically build type-safe, documented command-line interfaces directly from your Pydantic configuration models, complete with loading settings from a config file (`+file.yaml`) and single or double dash option overrides (`--key value`, `-k value`).

## Installation

```bash
pip install dracon
```

## Quick Start

Here's a taste of using Dracon with Pydantic:

**1. Your Python Code (`main.py`):**

```python
import sys
from pydantic import BaseModel
from typing import Annotated
from dracon import DraconLoader, make_program, Arg

# Define your configuration structure
class AppConfig(BaseModel):
    host: str
    port: int = 8080
    user: str
    log_level: str = "INFO"

# Create a loader, telling it about your model
loader = DraconLoader(context={'AppConfig': AppConfig})

# Load configuration (Dracon handles finding AppConfig via the tag)
config = loader.load("config.yaml")

# Access validated data
print(f"User: {config.user}")
print(f"Host: {config.host}:{config.port}")
print(f"Logging at: {config.log_level}")

assert isinstance(config, AppConfig) # It's the validated Pydantic model!

# --- Optional: Generate a CLI ---
program = make_program(AppConfig, name="my_app")
if __name__ == "__main__":
     cli_config, _ = program.parse_args(sys.argv[1:])
     print("\nCLI Loaded Config:")
     print(f"User: {cli_config.user}")
     print(f"Host: {cli_config.host}:{cli_config.port}")
```

**2. Your Configuration (`config.yaml`):**

```yaml
# Use the AppConfig model for validation and construction
!AppConfig
host: ${getenv('APP_HOST', 'localhost')} # Use env var or default
# port: 8080 # Omitted, uses Pydantic default
user: !include file:user.secret # Include user from another file
log_level: ${getenv('LOG_LEVEL', 'WARNING')}
```

**3. Secret File (`user.secret`):**

```yaml
app_user
```

**4. Run it:**

```bash
# Set environment variable (optional)
export APP_HOST=db.example.com
export LOG_LEVEL=DEBUG

# Run the script
python main.py

# Or use the generated CLI (if __main__ block included)
# python main.py # Uses defaults and config.yaml
# python main.py --host cli.host --port 9000 # Override via CLI
# python main.py +prod_config.yaml # Load another config file
```

This example shows type-tagging (`!AppConfig`), environment variable interpolation (`${getenv}`), file inclusion (`!include`), and how the result is a validated Pydantic object.

## Core Concepts Overview

- **Loading:** Use `DraconLoader` to parse YAML strings or files, providing runtime `context`.
- **Includes:** Break down configs using `!include` with sources like `file:`, `pkg:`, `env:`, or anchor names (which copy).
- **Interpolation:** Use `${...}` for lazy evaluation referencing context or other values (`@path`), and `$(...)` for immediate evaluation (often for tags).
- **Merging:** Combine configurations using `<<{dict_opts}[list_opts]@target_path:` for fine-grained control.
- **Types:** Leverage Pydantic models with `!ModelName` tags for validation and construction. Define custom types via context or the `dracon_dump_to_node` hook.
- **Instructions:** Embed composition logic with `!define`, `!if`, `!each`, `!noconstruct`.
- **Control:** Use `!deferred` to delay construction and `Resolvable[T]` to delay final value processing.
- **CLI:** Define CLIs with Pydantic and `Arg` annotations via `make_program`.

## Full Documentation

For detailed explanations, guides, and advanced usage, please refer to the **[Full Dracon Documentation](https://jdisset.github.io/dracon/)**.
