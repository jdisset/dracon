# Dracon

A modular configuration system for Python that extends YAML with powerful features like file inclusion, interpolation, dynamic object construction and allow to generate extensible, documented command line interfaces.

## Key Features

- **File Inclusion**: Include and merge other configuration files
- **Advanced Merging**: Flexible merge strategies for complex configurations
- **Expression Interpolation**: Use Python expressions within your YAML files
- **Deferred Construction**: Control when and how objects are constructed
- **Pydantic Integration**: Build type-safe configuration models
- **CLI Support**: Generate full-fledged, extensible command-line programs from Pydantic models

## Quick Start

```python
from dracon import DraconLoader

# Load a configuration file
loader = DraconLoader(context={"instance_id": 1}) # Define context variables
config = loader.load("config.yaml")

# Access configuration values
print(config.database.host)
print(config.service.port)
```

### Basic Configuration Example

```yaml
# config.yaml
database:
  host: ${env:DB_HOST or 'localhost'}
  port: 5432
  credentials: !include "file:./secrets.yaml"

service:
  name: "MyService"
  port: ${8080 + instance_id} # assuming instance_id is defined in context
  settings: !include "pkg:mypackage:settings/${env:ENV}.yaml"
```

## Core Features

### File Inclusion

Include other configuration files using `!include` or `*loader:` syntax:

```yaml
# Multiple include syntaxes
settings: !include "config/settings.yaml" # default is file loader
database: !include file:config/database.yaml
database_2: *file:config/database.yaml # can use the * syntax also
api_key: *env:API_KEY # environment variable loader
defaults: !include pkg:my_package:configs/defaults.yaml
```

### Expression Interpolation

Use Python expressions with `${...}` syntax:

```yaml
!define env: prod # Define a variable

service:
  port: ${base_port + instance_id}
  url: "http://${host}:${@/service.port}"
  mode: ${'production' if env == 'prod' else 'development'}
```

### Flexible Merging

Control how configurations are merged using merge operators:

```yaml
# Merge with different strategies
<<{+>}[>+]: *file:base.yaml          # Merge dictionnaries recursively, existing values take priority, existing lists are appended
<<{~<}: *file:overrides.yaml     # Replace values, new values take priority
<<{+>}@settings: *file:settings  # Merge at specific path
```

### Type-Safe Configurations

Use Pydantic models for type validation:

```python
from pydantic import BaseModel
from typing import List

class DatabaseConfig(BaseModel):
    host: str
    port: int
    replicas: List[str]

class ServiceConfig(BaseModel):
    name: str
    db: DatabaseConfig
    port: int

# Load and validate configuration
config = loader.load("config.yaml")
service_config = ServiceConfig(**config)
```

## Why Dracon?

Dracon solves common configuration management challenges:

- **Environment-Specific Configs**: Easily handle different environments using file inclusion and interpolation
- **Complex Deployments**: Use advanced merging to handle layered configurations
- **Type Safety**: Validate configurations at load time with Pydantic integration
- **Command-Line Programs**: Generate CLI programs from Pydantic models

## Installation

```bash
pip install dracon
```

## Documentation

Visit [full documentation](https://dracon.readthedocs.io/) for detailed guides and examples.
