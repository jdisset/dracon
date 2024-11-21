# File Inclusion

Dracon provides powerful file inclusion capabilities that let you modularize your configurations and handle environment-specific settings effectively.

## Basic Inclusion

There are two main syntaxes for including files:

```yaml
# Using !include tag
settings: !include "config/settings.yaml"

# Using *loader: syntax
database: *file:config/database.yaml
```

## Available Loaders

### File Loader

Load files from the filesystem:

```yaml
# Absolute path
config: *file:/etc/myapp/config.yaml

# Relative path
settings: *file:./settings.yaml
```

### Environment Variables

Load values from environment variables:

```yaml
api_key: *env:API_KEY
debug_mode: *env:DEBUG
```

### Package Resources

Load files from Python packages:

```yaml
defaults: *pkg:my_package:configs/defaults.yaml
```

## Advanced Features

### Including Specific Keys

You can include specific parts of other files using the `@` syntax:

```yaml
# Include only the database section from settings.yaml
database: *file:settings.yaml@database

# Include a deeply nested key
timeout: *file:config.yaml@services.api.timeout
```

### Variables in Paths

Interpolate variables in include paths:

```yaml
# Use environment-specific settings
settings: !include "configs/${env}/settings.yaml"

# Use version-specific configurations
version_config: !include "configs/v${version}/config.yaml"
```

c.f. [Expression Interpolation](interpolation.md)

### Circular References

Dracon detects and prevents circular inclusions:

```yaml
# This will raise an error
# config_a.yaml includes config_b.yaml
# config_b.yaml includes config_a.yaml
```

## Context Awareness

Included files have access to special variables:

```yaml
# Inside an included file
path_info:
  directory: ${$DIR} # Directory of the current file
  filename: ${$FILE} # Path of the current file
  stem: ${$FILE_STEM} # Filename without extension
```

## Tips and Best Practices

1. **Modularize Configurations**:

   ```yaml
   # main.yaml
   <<: *file:common/base.yaml
   database: !include "db/config.yaml"
   logging: !include "logging/${env}.yaml"
   ```

2. **Environment Management**:

   ```yaml
   # Use environment-specific includes
   settings:
     <<: *file:base_settings.yaml
     <<: !include "env/${env}/settings.yaml"
   ```

3. **Secrets Handling**:
   ```yaml
   database:
     host: localhost
     credentials: !include "secrets/db_creds.yaml"
   ```
4. **Include and Overwrite some keys**:
   ```yaml
   # base.yaml
   app:
     name: "MyApp"
     database:
       host: localhost
       port: 5432
   ```
   ```yaml
   # prod.yaml
   app:
     database:
       host: "prod-db.example.com"
       ssl: true
   <<{+>}: !include file:$DIR/base.yaml # priority to the existing values, recursively

   ```
   c.f. [Merging](merging.md)
