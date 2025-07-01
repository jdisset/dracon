# Advanced Features

This guide covers advanced Dracon features that go beyond basic configuration loading.

## Advanced Merge Strategies

### Depth-Limited Merging

Control how deep recursive merging goes:

```yaml
# Merge only 2 levels deep
<<{+2}: !include file:base.yaml

# Different limits for different sources
base_config:
  <<{+1}: !include file:shallow.yaml # Only merge top level
  <<{+3}: !include file:deep.yaml # Merge 3 levels deep
```

### Keypath Redirection

Redirect merge operations to specific paths:

```yaml
# Merge into specific nested location
app_config:
  database:
    <<@/staging/database: !include file:staging.yaml
```

### Independent Dict/List Control

Set different merge strategies for dictionaries and lists:

```yaml
# Append lists, replace dictionaries
<<{~}[+]: !include file:source.yaml

# Replace lists, merge dictionaries recursively
<<{+}[~]: !include file:source.yaml

# Custom depth for each
<<{+2}[+1]: !include file:source.yaml
```

## Advanced CLI Features

### File Loading Arguments

Mark Pydantic fields to automatically load files:

```python
from dracon import Arg

class Config(BaseModel):
    # Automatically prefixes with '+' to load file
    secrets: Annotated[dict, Arg(is_file=True, help="Secrets file")]

    # Manual file loading syntax
    override: Annotated[dict, Arg(help="Config override")]
    # Usage: --override +config.yaml
```

### Nested Argument Overrides

Override deeply nested configuration from CLI:

```bash
# Override nested fields
myapp --database.connection.pool_size 20
myapp --logging.handlers.file.level DEBUG

# Load entire nested section from file
myapp --database +db-prod.yaml

# Load specific key from file
myapp --database.host +config.yaml@database.prod_host
```

### Context Variable Definition

Define variables for use in configuration interpolation:

```bash
# Define context variables (preferred shorthand)
myapp ++region us-west-2 ++version 1.2.3

# Also supports equals syntax
myapp ++region=us-west-2 ++version=1.2.3

# Legacy longer form (still supported)
myapp --define.region us-west-2 --define.version=1.2.3

# Use in YAML files
region_config: ${region}
app_version: ${version}
```

## Advanced Interpolation

### Reference System

Use `@` for keypath references and `&` for anchor references:

```yaml
environment: prod

# Keypath references
database:
  host: "db.${@/environment}.local" # References /environment
  backup: "backup.${@host}.local" # References database/host

# Anchor references
defaults: &defaults
  timeout: 30
  retries: 3

service:
  timeout: ${&defaults.timeout * 2} # References anchor content
```

### Key Interpolation

Generate dynamic keys using interpolation:

```yaml
!define theme:
  t1: primary
  t2: secondary

# Generate keys dynamically
styles:
  ${theme.t1}_color: "#007bff"
  ${theme.t2}_color: "#6c757d"
```

### Context-Aware Interpolation

Access file and runtime context:

```yaml
# File context
config_backup: ${DIR}/backup/${FILE_STEM}.backup
load_time: ${FILE_LOAD_TIME}

# Runtime context (provided during loading)
deployment_url: https://${region}.example.com
version_tag: ${app_name}:${version}
```

## Advanced Deferred Execution

### Selective Deferral

Force specific paths to be deferred:

```python
loader = DraconLoader(
    deferred_paths=[
        'app.output_path',
        'services.*.endpoint'  # Wildcards supported
    ]
)
```

### Context Clearing

Clear specific context variables in deferred nodes:

```yaml
# Clear old context variables
clean_config: !deferred::clear_ctx=old_var,temp_value
  new_value: ${fresh_runtime_var}
```

### Query Parameters in Deferred Tags

Pass parameters to deferred construction:

```yaml
# With query-style parameters
computed_path: !deferred::base_path=/data&suffix=.log ${base_path}/app${suffix}
```

## Advanced Include Patterns

### Package Resources

Load from Python packages:

```yaml
# Include from installed package
defaults: !include pkg:mypackage:config/defaults.yaml

# With keypath selection
db_config: !include pkg:mypackage:config/db.yaml@production
```

### Environment and Variable Includes

```yaml
# From environment variables
api_key: !include env:API_SECRET

# From defined variables
!define config_name: advanced
current_config: !include var:config_name
```

## Instruction-Based Programming

### Complex Loops

```yaml
# Loop with complex content generation
!define services: [auth, api, worker]
!define environments: [dev, staging, prod]

!each(service) ${services}:
  !each(env) ${environments}:
    ${service}_${env}:
      image: myapp/${service}:${env}
      replicas: ${1 if env == 'dev' else 3}
      resources:
        cpu: ${0.5 if service == 'worker' else 1.0}
        memory: ${512 if env == 'dev' else 1024}MB
```



### Variable Scoping

```yaml
!define global_timeout: 30

services:
  !define service_timeout: ${global_timeout * 2}

  auth:
    timeout: ${service_timeout} # Uses local definition

  api:
    !define service_timeout: ${global_timeout / 2}
    timeout: ${service_timeout} # Uses redefined local value
```

## Performance Optimizations

### Caching Control

```python
# Disable caching for dynamic content
loader = DraconLoader(use_cache=False)

# Custom cache settings (implementation dependent)
loader = DraconLoader(use_cache=True)  # Uses LRU cache with 128 items
```

### Custom Container Types

Use specialized data structures:

```python
from collections import OrderedDict, deque

# Custom container types for performance
loader = DraconLoader(
    base_dict_type=OrderedDict,  # Maintain key order
    base_list_type=deque         # Efficient appends/prepends
)
```

### Parallel Processing Support

Dracon configurations work with multiprocessing:

```python
import multiprocessing as mp
from dracon import load

def worker(config_data):
    # config_data is picklable and works across processes
    return process_with_config(config_data)

if __name__ == '__main__':
    config = load('config.yaml')

    with mp.Pool() as pool:
        results = pool.map(worker, [config] * 4)
```

## Error Handling and Debugging

### Rich Error Messages

Dracon provides detailed error context:

```python
try:
    config = load('config.yaml')
except Exception as e:
    # Rich error formatting with context
    print(e)  # Shows file location, line numbers, validation details
```

### Validation with Custom Messages

```python
from pydantic import BaseModel, validator

class Config(BaseModel):
    port: int

    @validator('port')
    def validate_port(cls, v):
        if not (1024 <= v <= 65535):
            raise ValueError(f"Port {v} must be between 1024 and 65535")
        return v
```

# Safe environment variable access

api_url: ${getenv('API_URL') or 'http://localhost:8080'}

````

## Integration Patterns

### Custom Loaders

Extend the loader system:

```python
from dracon.loaders import BaseLoader

class DatabaseLoader(BaseLoader):
    def load(self, path, context):
        # Load configuration from database
        return fetch_config_from_db(path)

# Register custom loader
loader = DraconLoader()
loader.register_loader('db', DatabaseLoader())

# Use in YAML
config: !include db:config_table@prod_settings
````

### Pre-commit Hook Integration

Validate configurations before commit:

```python
#!/usr/bin/env python3
# pre-commit hook
import sys
from dracon import load
from myapp.models import AppConfig

try:
    config = load(sys.argv[1], context={'AppConfig': AppConfig})
    print(f"✓ Configuration {sys.argv[1]} is valid")
except Exception as e:
    print(f"✗ Configuration error: {e}")
    sys.exit(1)
```

### CI/CD Integration

```yaml
# .github/workflows/validate-config.yml
name: Validate Configuration
on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Validate configs
        run: |
          python -c "
          from dracon import load
          from myapp.models import AppConfig

          configs = ['config/base.yaml', 'config/prod.yaml']
          for config_file in configs:
              load(config_file, context={'AppConfig': AppConfig})
              print(f'✓ {config_file} is valid')
          "
```

## Best Practices

### Configuration Architecture

```yaml
# Layered configuration with clear precedence
app_config:
  # 1. Defaults (lowest priority)
  <<{<+}: !include file:defaults.yaml

  # 2. Environment-specific (medium priority)
  <<{<+}: !include file:environments/${ENVIRONMENT}.yaml

  # 3. Local overrides (highest priority)
  <<{<+}: !include file:local.yaml
```

### Secret Management

```yaml
# Separate secret loading
database:
  host: db.prod.example.com
  port: 5432
  username: !include file:$DIR/secrets/db-user.txt
  password: !include env:DB_PASSWORD
```
