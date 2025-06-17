# Include Syntax

Dracon's include system allows you to load content from various sources and merge it into your configuration.

## Basic Include Tag

```yaml
# Include entire file
data: !include file:config/database.yaml

# Include from environment variable
api_key: !include env:API_KEY

# Include from defined variable
user_data: !include var:current_user
```

## File Includes

### File Paths

```yaml
# Relative to current file
config: !include file:../shared/base.yaml

# Using $DIR for current directory
secrets: !include file:$DIR/secrets.yaml

# Absolute path
global_config: !include file:/etc/myapp/config.yaml
```

### File with KeyPath

```yaml
# Include specific key from file
db_host: !include file:config/database.yaml@host

# Include nested key
redis_config: !include file:config/cache.yaml@redis.connection
```

## Package Includes

Load resources from Python packages:

```yaml
# Include from package
defaults: !include pkg:mypackage:config/defaults.yaml

# With keypath
db_defaults: !include pkg:mypackage:config/database.yaml@development
```

## Environment Variable Includes

```yaml
# Simple environment variable
api_url: !include env:API_BASE_URL

# With default value (handled by shell or getenv)
debug_mode: !include env:DEBUG_MODE
```

## Variable Includes

Reference variables defined with `!define` or `!set_default`:

```yaml
# Define a variable
!define user_type: premium

# Use the variable elsewhere
config: !include var:user_type
```

## Advanced Include Patterns

### Conditional Includes

```yaml
database: !if ${getenv('ENVIRONMENT') == 'prod'}
  then: !include file:config/prod-db.yaml
  else: !include file:config/dev-db.yaml
```

### Includes in Loops

```yaml
!each(env_name) ["dev", "staging", "prod"]:
  ${env_name}: !include file:config/${env_name}.yaml
```

### Anchor-based Includes

```yaml
base_config: &base
  timeout: 30
  retries: 3

service_a:
  name: service-a
  <<: !include &base  # Include from anchor
```

## Merge with Includes

Use merge keys with includes:

```yaml
# Merge included content
database:
  host: override.example.com
  <<: !include file:config/db-defaults.yaml

# Advanced merge strategy
app_config:
  environment: production
  <<{>+}: !include file:config/base.yaml
```

## Context Variables in Includes

Includes have access to the current context:

```yaml
# File context variables
config_dir: !include file:$DIR/subconfig.yaml
config_name: !include file:${FILE_STEM}-override.yaml

# Custom context variables
user_config: !include file:config/${username}.yaml
```

## Error Handling

### Optional Includes

While not directly supported, you can use conditionals:

```yaml
optional_config: !if ${file_exists('optional.yaml')}
  then: !include file:optional.yaml
  else: {}
```

### Include with Fallbacks

```yaml
config: !include file:local.yaml
fallback: !include file:default.yaml

# Or use variables with conditionals
!define config_file: !if ${file_exists('local.yaml')}
  then: local.yaml
  else: default.yaml

final_config: !include file:${config_file}
```

## Performance Notes

- Includes are cached when `use_cache=True` (default)
- Large files are only loaded once per session
- Recursive includes are detected and prevented
- Context variables are efficiently passed down the include chain

## Common Patterns

### Configuration Layering

```yaml
# base.yaml
base:
  <<: !include file:defaults.yaml
  <<{>+}: !include file:environment/${ENVIRONMENT}.yaml
  <<{>+}: !include file:local-overrides.yaml
```

### Secret Management

```yaml
database:
  host: db.example.com
  port: 5432
  username: !include file:$DIR/secrets/db-user.txt
  password: !include env:DB_PASSWORD
```

### Dynamic Configuration

```yaml
!define service_name: ${getenv('SERVICE_NAME', 'default')}

service_config: !include file:services/${service_name}.yaml
monitoring: !include file:monitoring/${service_name}-metrics.yaml
```