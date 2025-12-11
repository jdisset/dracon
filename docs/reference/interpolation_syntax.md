# Interpolation Syntax

Dracon provides powerful expression interpolation using `${...}` syntax for dynamic values.

## Basic Interpolation

### Simple Expressions

```yaml
# Environment variables
log_level: ${getenv('LOG_LEVEL', 'INFO')}

# Mathematical expressions
max_workers: ${os.cpu_count() * 2}

# String operations
app_name: ${getenv('APP_NAME', 'myapp').lower()}
```

### Immediate vs Lazy Evaluation

```yaml
# Lazy evaluation (default) - resolved at construction time
computed_at_runtime: ${time.time()}

# Immediate evaluation - resolved during loading
computed_at_load: $(time.time())
```

## Shorthand Variables

When `enable_shorthand_vars=True` (default):

```yaml
# These are equivalent:
user_home: $HOME
user_home: ${HOME}

# Complex expressions still need full syntax
computed: ${$HOME + '/data'}
```

## Reference System

### Construction-time References (`@`)

Reference other keys in the same configuration:

```yaml
environment: prod
database:
  host: "db.${@/environment}.local" # References /environment
  backup_host: "backup.${@host}" # References database/host
```

#### Reference Syntax

!!! note
KeyPaths use a dot-separated syntax to navigate the YAML structure. The slash (`/`) is a special character that means "root".

- `@/key`: Absolute reference from root
- `@key.subkey`: Relative reference from current level
- `@..key`: Parent level reference
- `@/nested.deep.key`: Deep nested reference (starting at root)

### Node (composition-time) Copies (`&`)

Will duplicate the referenced node:

```yaml
defaults:
  timeout: 30
  retries: 3

service_config:
  name: my-service
  timeout: ${&/defaults.timeout * 2} # References anchor content
```

## Built-in Functions

### OS Functions

```yaml
# Environment variables
api_url: ${getenv('API_URL', 'http://localhost:8080')}

# File system
data_dir: ${expanduser('~/data')}
current_dir: ${getcwd()}
config_files: ${listdir('/etc/myapp')}

# Path operations
log_file: ${join(expanduser('~/logs'), 'app.log')}
script_name: ${basename(__file__)}
script_dir: ${dirname(__file__)}
```

### Date/Time Functions

```yaml
# Current datetime (default format: YYYY-MM-DD HH:MM:SS)
timestamp: ${now()}

# Custom format using strftime codes
date_only: ${now('%Y-%m-%d')}
time_only: ${now('%H:%M:%S')}
iso_format: ${now('%Y-%m-%dT%H:%M:%S')}
filename_safe: ${now('%Y%m%d_%H%M%S')}
```

### Dracon Functions

```yaml
# Construct deferred nodes
output_path: ${construct(deferred_node, {'runtime_var': 'value'})}

# Access current file context
config_dir: ${__DRACON__CURRENT_PATH}
parent_dir: ${__DRACON__PARENT_PATH}
```

## Context Variables

### Automatic Context (in file loading)

```yaml
# File information
config_backup: ${DIR}/backup/${FILE_STEM}.backup
load_timestamp: ${FILE_LOAD_TIME}
config_size: ${FILE_SIZE}
```

### Custom Context

```python
# Provided when loading
loader.load('config.yaml', context={
    'version': '1.2.3',
    'deployment': 'production',
    'custom_func': lambda x: x.upper()
})
```

```yaml
# Used in YAML
app_version: ${version}
deployment_type: ${deployment}
service_name: ${custom_func('myservice')}
```

## Advanced Patterns

### Conditional Expressions

```yaml
# Simple conditionals
debug_mode: ${getenv('DEBUG', 'false').lower() == 'true'}

# Complex conditionals
log_level: ${
  'DEBUG' if getenv('ENVIRONMENT') == 'dev'
  else 'WARNING' if getenv('ENVIRONMENT') == 'prod'
  else 'INFO'
}
```

### List Comprehensions

```yaml
# Generate lists
service_ports: ${[8000 + i for i in range(int(getenv('REPLICAS', '3')))]}

# Filter lists
enabled_services: ${[s for s in services if s.get('enabled', True)]}
```

### Dictionary Operations

```yaml
# Merge dictionaries
merged_config: ${dict(base_config, **override_config)}

# Filter dictionaries
prod_settings: ${
  {k: v for k, v in all_settings.items()
   if not k.startswith('dev_')}
}
```

## Key Interpolation

Generate dynamic keys:

```yaml
!define environments: ["dev", "staging", "prod"]

!each(env) ${environments}:
  ${env}_database_url: postgres://db.${env}.local/myapp
  ${env}_redis_url: redis://cache.${env}.local
```

## Nested Interpolation

```yaml
# Environment-based configuration selection
!define config_key: ${getenv('ENVIRONMENT', 'dev')}_settings

# Use the computed key
app_config: ${globals()[config_key]}

# Nested expressions
complex_value: ${getenv('PREFIX', 'app') + '_' + str(getenv('VERSION', '1'))}
```

## Escaping

Escape interpolation when you need literal `${}`:

```yaml
# Escaped - will be literal "${version}"
escaped_template: \${version}

# Not escaped - will interpolate
interpolated: ${version}

# Mixed
docker_command: echo \${VERSION} > /tmp/version && echo ${actual_version}
```

## Error Handling

### Safe Navigation

```yaml
# Handle missing keys gracefully
optional_value: ${config.get('optional_key', 'default')}

# Chain operations safely
nested_value: ${config.get('section', {}).get('key', 'fallback')}
```

### Try-Catch Patterns

```yaml
# Using Python's exception handling
database_url: ${
  getenv('DATABASE_URL') if getenv('DATABASE_URL')
  else f"postgresql://{getenv('DB_USER')}:{getenv('DB_PASS')}@{getenv('DB_HOST')}/myapp"
}
```

## Performance Notes

- Expressions are cached when possible
- References (`@` and `&`) are resolved efficiently
- Complex expressions may impact loading time
- Use immediate evaluation `$()` for values that don't change

## Common Use Cases

### Environment-based Configuration

```yaml
database:
  host: db.${getenv('ENVIRONMENT', 'dev')}.local
  pool_size: ${int(getenv('DB_POOL_SIZE', '10'))}
  ssl_mode: ${
    'require' if getenv('ENVIRONMENT') == 'prod'
    else 'prefer'
  }
```

### Dynamic Service Discovery

```yaml
services:
  auth_service: http://${getenv('AUTH_HOST', 'localhost')}:${getenv('AUTH_PORT', '8001')}
  data_service: http://${getenv('DATA_HOST', 'localhost')}:${getenv('DATA_PORT', '8002')}

service_mesh: ${
  [f"http://{service}:{port}"
   for service, port in zip(service_hosts, service_ports)]
}
```

### Configuration Validation

```yaml
# Validate required environment variables
database_url: ${
  getenv('DATABASE_URL') or
  (_ for _ in ()).throw(ValueError('DATABASE_URL is required'))
}
```
