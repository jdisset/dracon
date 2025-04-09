# File Inclusion

Dracon's file inclusion system allows you to break down your configurations into reusable, modular files. This is particularly useful for handling environment-specific settings, separating credentials, or organizing large configurations.

## Inclusion Syntax

Dracon offers two ways to include files:

### 1. Tag Syntax

The `!include` tag is the most explicit way to include a file:

```yaml
# Include a file using the default (file) loader
settings: !include "config/settings.yaml"

# Explicitly specify the file loader
database: !include file:config/database.yaml

# Include from a Python package
templates: !include pkg:my_package:configs/templates.yaml
```

### 2. Anchor Syntax

The `*loader:` syntax is shorter and can be used in more contexts:

```yaml
# Include a file using the file loader
database: *file:config/database.yaml

# Include an environment variable
api_key: *env:API_KEY

# Include from a package
defaults: *pkg:my_package:configs/defaults.yaml
```

Both syntaxes work in most cases, but the anchor syntax (`*`) is more concise and has better compatibility with other YAML processors.

## Available Loaders

Dracon comes with these built-in loaders:

### File Loader

Loads files from the filesystem:

```yaml
# Absolute path
config: *file:/etc/myapp/config.yaml

# Relative path (to current file)
settings: *file:./settings.yaml

# Path with filename only (searches in relative paths)
logging: *file:logging.yaml
```

### Environment Variables

Loads values from environment variables:

```yaml
api_key: *env:API_KEY
debug_mode: *env:DEBUG
port: ${int(env.get('PORT', '8080'))}
```

### Package Resources

Loads files from installed Python packages:

```yaml
defaults: *pkg:my_package:configs/defaults.yaml
```

## Context Variables

When Dracon loads a file, it adds special variables to the context that you can use in expressions:

```yaml
# These values are set automatically for each included file
file_info:
  directory: ${$DIR} # Directory containing the current file
  full_path: ${$FILE} # Full path to the current file
  filename: ${$FILE_STEM} # Filename without extension
  extension: ${$FILE_EXT} # File extension
  load_time: ${$FILE_LOAD_TIME} # Timestamp when the file was loaded
```

These variables are particularly useful when including files that need to reference their location:

```yaml
# In config/app.yaml
log_directory: ${$DIR}/logs
templates: ${$DIR}/templates
log_file: ${$FILE_STEM}.log # Will resolve to "app.log"
```

## Including Specific Keys

You can include just a part of another file using the `@` syntax:

```yaml
# Include only the database section from settings.yaml
database: *file:settings.yaml@database

# Include a deeply nested key
timeout: *file:config.yaml@services.api.timeout

# Note: Keys with dots must be escaped
dotted_key: *file:config.yaml@section\.with\.dots
```

## Variables in Paths

You can use interpolation in include paths:

```yaml
# Use environment-specific settings
!define env: "production"
settings: !include "configs/${env}/settings.yaml"

# Use version-specific configurations
version_config: *file:configs/v${version}/config.yaml
```

## Best Practices

### 1. Organize by Feature or Component

Group related settings into separate files:

```yaml
# main.yaml
database: !include "components/database.yaml"
api: !include "components/api.yaml"
logging: !include "components/logging.yaml"
```

### 2. Layer by Environment

Create a base config and environment-specific overrides:

```yaml
# prod.yaml
<<{+<}: *file:base.yaml
database:
  host: "prod-db.example.com"
  ssl: true
```

### 3. Manage Secrets Separately

Keep sensitive data in separate files:

```yaml
# app.yaml
database:
  host: "db.example.com"
  port: 5432
  credentials: !include "secrets/db_creds.yaml"
```

### 4. Use Relative Paths

For portable configurations, use relative paths:

```yaml
# utils/config.yaml
templates: *file:${$DIR}/templates
resources: *file:${$DIR}/../resources
```

## Error Handling

Dracon will raise an error if an included file cannot be found. For optional includes, use interpolation with fallbacks:

```yaml
# Try to include a file, fallback to an empty dict if not found
overrides: ${try_include('file:overrides.yaml', {})}

# Helper function in your context
def try_include(path, default=None):
  try: return loader.load(path)
  except FileNotFoundError: return default
```

## Custom Loaders

You can create custom loaders for additional sources:

```python
def read_from_redis(path: str, loader=None):
    """Load configuration from Redis"""
    import redis
    r = redis.Redis()

    # Path format: redis:key
    key = path
    yaml_data = r.get(key)

    if yaml_data is None:
        raise FileNotFoundError(f"Redis key not found: {key}")

    return yaml_data.decode('utf-8'), {
        '$REDIS_KEY': key,
        '$REDIS_TIMESTAMP': time.time()
    }

# Register the loader
loader = DraconLoader(
    custom_loaders={'redis': read_from_redis}
)

# Now you can use it
# config: *redis:app:settings
```
