# Basic Features

This guide covers the fundamental features that make Dracon a powerful configuration management system.

## Configuration Loading

### Simple Loading

```python
from dracon import load, loads

# Load from file
config = load('config.yaml')

# Load from string
config = loads("""
database:
  host: localhost
  port: 5432
""")

# Load multiple files (later overrides earlier)
config = load(['base.yaml', 'prod.yaml'])
```

### Pydantic Integration

```python
from pydantic import BaseModel
from dracon import load

class DatabaseConfig(BaseModel):
    host: str = 'localhost'
    port: int = 5432

class AppConfig(BaseModel):
    database: DatabaseConfig

# Automatic validation and type conversion
config = load('config.yaml', context={'AppConfig': AppConfig})
# Returns validated AppConfig instance
```

## YAML Extensions

### Basic Interpolation

```yaml
# Environment variables
log_level: ${getenv('LOG_LEVEL', 'INFO')}
api_url: ${getenv('API_URL', 'http://localhost:8080')}

# Mathematical expressions
max_workers: ${os.cpu_count() * 2}
timeout: ${30 + 10}

# String operations
app_name: ${getenv('APP_NAME', 'myapp').lower()}
```

### File Includes

```yaml
# Include entire files
database: !include file:config/database.yaml
secrets: !include file:secrets/api-keys.yaml

# Include with path context
config: !include file:$DIR/local.yaml # $DIR = current file's directory

# Include specific keys
db_host: !include file:config/database.yaml@host
redis_config: !include file:config/cache.yaml@redis.settings
```

### Environment and Variable Loading

```yaml
# Load from environment variables
api_key: !include env:API_SECRET
database_url: !include env:DATABASE_URL

# Define and use variables
!define app_name: myapp
!define version: 1.2.3

service_name: ${app_name}-service
image_tag: ${app_name}:${version}
```

## Configuration Merging

### Basic Merge Operations

```yaml
# Simple merge (base values win conflicts)
app_config:
  environment: prod
  workers: 4
  <<: !include file:base.yaml

# Recursive merge (override specific nested values)
database:
  host: prod-db.example.com
  pool_size: 20
  <<{+}: !include file:base-db.yaml # Merges recursively
```

### Merge Strategies

```yaml
# Different merge behaviors
<<{+}: !include file:base.yaml # Recursive merge, new wins
<<{>+}: !include file:base.yaml # Recursive merge, existing wins
<<{~}: !include file:base.yaml # Replace completely
<<[+]: !include file:base.yaml # Append lists
<<[~]: !include file:base.yaml # Replace lists
```

## CLI Generation

### Automatic CLI from Models

```python
from typing import Annotated, Literal
from pydantic import BaseModel
from dracon import Arg, make_program

class AppConfig(BaseModel):
    # Required argument (no default)
    environment: Annotated[
        Literal['dev', 'prod', 'test'],
        Arg(short='e', help="Deployment environment")
    ]

    # Optional arguments (have defaults)
    port: Annotated[int, Arg(help="Server port")] = 8080
    debug: Annotated[bool, Arg(help="Enable debug mode")] = False
    workers: Annotated[int, Arg(help="Worker processes")] = 1

# Create CLI program
program = make_program(AppConfig, name="myapp", description="My application")

# Parse arguments and get validated config
config, raw_args = program.parse_args(['--environment', 'prod', '--port', '9090'])
```

### CLI Usage Patterns

```bash
# Basic arguments
myapp --environment prod --port 9090 --debug

# Short flags
myapp -e prod --workers 4

# Load configuration files
myapp +config/base.yaml +config/prod.yaml

# Override nested values
myapp --database.host db.example.com --database.port 5433

# Load values from files
myapp --api-key +secrets/api.key

# Define runtime variables
myapp --define.region us-west-2 --define.version 1.2.3
```

## Basic Instructions

### Variable Definition

```yaml
# Define variables for reuse
!define database_host: db.example.com
!define api_version: v2
!define retry_count: 3

# Use variables
database:
  host: ${database_host}
  connection_string: postgresql://${database_host}/myapp

api:
  endpoint: https://api.example.com/${api_version}
  retries: ${retry_count}
```

### Simple Loops

```yaml
# Generate configuration for multiple environments
!define environments: [dev, staging, prod]

!each(env) ${environments}:
  ${env}_database:
    host: db.${env}.local
    name: myapp_${env}

# Generate service endpoints
!define services: [auth, api, worker]

!each(service) ${services}:
  ${service}_url: http://${service}.example.com
```

## Pydantic Model Tags

### Model Construction in YAML

```python
class DatabaseConfig(BaseModel):
    host: str
    port: int = 5432
    ssl: bool = False

class AppConfig(BaseModel):
    name: str
    database: DatabaseConfig
```

```yaml
# Direct model construction
app: !AppConfig
  name: myapp
  database: !DatabaseConfig
    host: db.example.com
    port: 5433
    ssl: true

# Alternative syntax
app: !AppConfig
  name: myapp
  database:
    host: db.example.com
    port: 5433
    ssl: true
```

## Keypath References

### Referencing Other Configuration Values

```yaml
environment: prod
region: us-west-2

# Reference other keys in the same config
database:
  host: "db.${@/environment}.${@/region}.local" # db.prod.us-west-2.local
  backup_host: "backup.${@host}" # backup.db.prod.us-west-2.local

# Relative references
api:
  version: v2
  auth_endpoint: "https://auth.api.com/${@version}"
  data_endpoint: "https://data.api.com/${@version}"
```

## Basic Deferred Execution

### Runtime Context Resolution

```python
from dracon import DeferredNode, construct

class Config(BaseModel):
    # Value computed at runtime
    output_path: DeferredNode[str]

# In YAML
output_path: "/data/${runtime_id}/logs"

# Later, provide runtime context
final_config = construct(config.output_path, context={'runtime_id': 'job_123'})
```

## Error Handling

### Validation Errors

```python
from pydantic import BaseModel, validator

class Config(BaseModel):
    port: int

    @validator('port')
    def validate_port(cls, v):
        if not (1024 <= v <= 65535):
            raise ValueError(f"Port must be between 1024-65535, got {v}")
        return v

# Clear error messages with context
try:
    config = load('config.yaml', context={'Config': Config})
except Exception as e:
    print(e)  # Shows file location, validation errors, etc.
```

## File Organization Patterns

### Layered Configuration

```
config/
├── defaults.yaml      # Base defaults
├── environments/
│   ├── dev.yaml      # Development overrides
│   ├── staging.yaml  # Staging overrides
│   └── prod.yaml     # Production overrides
├── secrets/
│   ├── api-keys.yaml
│   └── database.yaml
└── local.yaml        # Local developer overrides (gitignored)
```

```yaml
# Main configuration
app_config:
  # Load in order of precedence (later wins)
  <<: !include file:defaults.yaml
  <<{>+}: !include file:environments/${getenv('ENVIRONMENT', 'dev')}.yaml
  <<{>+}: !include file:local.yaml
```

### Secret Management

```yaml
# Separate secrets from configuration
database:
  host: db.prod.example.com
  port: 5432
  # Load sensitive data separately
  username: !include file:secrets/db-user.txt
  password: !include env:DB_PASSWORD

api:
  base_url: https://api.example.com
  key: !include env:API_SECRET
```

## Built-in Context Functions

### OS and Path Operations

```yaml
# Environment variables
debug_mode: ${getenv('DEBUG', 'false')}
home_dir: ${expanduser('~')}

# File system operations
config_dir: ${getcwd()}/config
log_files: ${listdir('/var/log/myapp')}

# Path operations
data_path: ${join(expanduser('~'), 'data', 'myapp')}
script_name: ${basename(__file__)}
```

### File Context Variables

```yaml
# Automatic context when loading files
backup_config: ${DIR}/backup/${FILE_STEM}.backup.yaml
load_timestamp: "Loaded at ${FILE_LOAD_TIME}"
config_size: "Config file is ${FILE_SIZE} bytes"
```

## Common Patterns

### Environment-Specific Configuration

````yaml
!define env: ${getenv('ENVIRONMENT', 'dev')}

# Environment-specific database
database: !include file:config/database-${env}.yaml


### Service Configuration

```yaml
!define service_name: ${getenv('SERVICE_NAME', 'myapp')}
!define service_port: ${int(getenv('PORT', '8080'))}

service:
  name: ${service_name}
  port: ${service_port}
  health_check: http://localhost:${service_port}/health

# Load service-specific config
service_config: !include file:services/${service_name}.yaml
````
