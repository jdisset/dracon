# Dracon

Dracon is a modular configuration system for Python that extends YAML with powerful features. It bridges the gap between simple configuration files and more complex application needs with features like file inclusion, expression interpolation, and type validation.

## Why Dracon?

Regular configuration systems often fall short when your application gets more complex:

- Need to share settings across multiple files? Dracon lets you include and merge files.
- Have environment-specific settings? Use expressions and interpolation.
- Want type safety? Dracon integrates with Pydantic for validation.
- Building a CLI? Generate full command-line interfaces from your config models.

## Core Features

- **File Inclusion**: Include and merge other configuration files
- **Expression Interpolation**: Use Python expressions within your YAML files
- **Advanced Merging**: Control exactly how configurations combine with flexible merge strategies
- **Deferred Construction**: Postpone object creation until you have all the context you need
- **Pydantic Integration**: Build type-safe configuration models
- **CLI Support**: Generate full-featured command-line programs from your models

## Quick Start

### Installation

```bash
pip install dracon
```

### Basic Usage

```python
from dracon import DraconLoader

# Load a configuration file with some context variables
loader = DraconLoader(context={"instance_id": 1})
config = loader.load("config.yaml")

# Access your configuration values
print(config.database.host)
print(config.service.port)
```

### Example Configuration

Here's a simple configuration file that shows some of Dracon's features:

```yaml
# Define variables for use throughout the config
!define env: ${os.getenv('ENV', 'development')}
!define debug: ${env != 'production'}

# Include common settings
common: !include file:./common.yaml

# Database configuration
database:
  host: ${env.get('DB_HOST', 'localhost')}
  port: 5432
  # Include credentials from a separate file
  credentials: !include file:./credentials/${env}.yaml

# Service configuration
service:
  name: "MyService"
  # Dynamic port calculation
  port: ${8080 + instance_id}
  # Include environment-specific settings
  settings: !include file:./settings/${env}.yaml
  # Conditional configuration
  !if ${debug}:
    log_level: "DEBUG"
    profiling: true
```

## Working with Models

Dracon integrates well with Pydantic for type validation:

```python
from pydantic import BaseModel
from typing import List, Optional
from dracon import DraconLoader

class DatabaseConfig(BaseModel):
    host: str
    port: int
    user: str
    password: str

class ServiceConfig(BaseModel):
    name: str
    port: int
    log_level: Optional[str] = "INFO"
    profiling: bool = False

class AppConfig(BaseModel):
    database: DatabaseConfig
    service: ServiceConfig
    version: str

# Load and validate configuration
loader = DraconLoader()
config_data = loader.load("config.yaml")
app_config = AppConfig(**config_data)

# Now you have a fully validated configuration
print(f"Connecting to database at {app_config.database.host}:{app_config.database.port}")
```

## Architecture Overview

Dracon works in several phases:

1. **Composition**: Parse YAML and handle includes and merges
2. **Interpolation**: Resolve expressions and references
3. **Construction**: Build Python objects from the composed config
4. **Validation**: Optionally validate using Pydantic models

```
┌──────────┐   ┌─────────────┐   ┌─────────────┐   ┌───────────┐
│ YAML File│──>│ Composition │──>│Construction │──>│  Python   │
└──────────┘   │  (include,  │   │ (objects,   │   │  Objects  │
               │   interp,   │   │ validation) │   └───────────┘
               │    merge)   │   └─────────────┘
               └─────────────┘
```

## Next Steps

Check out the detailed guides for each feature:

- [File Inclusion](includes.md): Learn how to modularize your configurations
- [Expression Interpolation](interpolation.md): Add dynamic expressions to your configs
- [Advanced Merging](merging.md): Control how configurations are combined
- [Node Instructions](instructions.md): Use special directives like `!if` and `!each`
- [Command Line Programs](cli.md): Generate CLIs from your config models
- [Advanced Usage](advanced.md): Explore deferred nodes and more advanced features
