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
global_config: !include file:/etc/myapp/config # note: specifying the .yaml (or .yml) extension is always optional
```

### File with KeyPath

```yaml
# Include specific key from file
db_host: !include file:config/database.yaml@host

# Include nested key
redis_config: !include file:config/cache@redis.connection # note: specifying the .yaml (or .yml) extension is always optional
```

## Package Includes

Load resources from Python packages:

```yaml
# Include from package
defaults: !include pkg:mypackage:config/defaults # note: specifying the .yaml (or .yml) extension is always optional

# With keypath
db_defaults: !include pkg:mypackage:config/database@development
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

## Cascade Includes

The `cascade:` loader finds **all** files matching a name by walking up the directory tree from the current working directory, then merges them in order -- root-level files form the base, closest files have the highest priority. This is the same pattern used by `.gitconfig`, `.editorconfig`, and similar tools.

```yaml
# Find and merge all config.yaml files from cwd up to /
settings: !include cascade:config.yaml

# With @keypath -- extract a subtree from the merged result
db: !include cascade:app.yaml@database

# Optional -- no error if nothing found
overrides: !include? cascade:local.yaml
```

### Start Directory

By default, the cascade walks up from the current working directory. Use `${DIR}` to start from the including file's directory instead:

```yaml
settings: !include cascade:${DIR}/config.yaml
```

The path is resolved identically to `file:` before the walk begins, so interpolation and `~` expansion work as expected.

### Custom Merge Strategy

By default, cascaded files are merged with `<<{<+}[<~]` (recursive dict append, new wins; list replace, new wins). You can override this by prefixing the path with a merge key spec:

```yaml
# Existing (root) values win for dicts
settings: !include cascade:{>+}[>~]:config.yaml

# Append lists instead of replacing them
plugins: !include cascade:{<+}[+>]:plugins.yaml

# Dict-only spec (list behavior stays default)
settings: !include cascade:{<~}:config.yaml
```

The merge key spec uses the same `{dict}[list]` syntax as [merge keys](merge_syntax.md), without the `<<` prefix. A `:` separates it from the file path.

### Extension Probing

Like `file:`, the cascade loader probes extensions automatically. `cascade:config` will match `config`, `config.yaml`, or `config.yml` at each directory level (first match wins per level).

### Example

Given this directory structure:

```
/home/user/.tool.yaml          # theme: dark, fontsize: 12
/home/user/projects/.tool.yaml # fontsize: 16, plugins: [lint]
```

And a config file at `/home/user/projects/myapp/main.yaml`:

```yaml
settings: !include cascade:.tool.yaml
```

Running from `/home/user/projects/myapp/`, the cascade finds both files. The result:

```yaml
settings:
  theme: dark      # inherited from /home/user/
  fontsize: 16     # overridden by /home/user/projects/
  plugins: [lint]  # added by /home/user/projects/
```

## Advanced Include Patterns

### Conditional Includes

```yaml
!if ${getenv('ENVIRONMENT') == 'prod'}:
  then:
    database: !include file:config/prod-db.yaml
  else:
    database: !include file:config/dev-db.yaml
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
  <<: !include &base # Include from anchor

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

Use environment variables or `!if` to conditionally include files:

```yaml
# conditionally include based on an environment variable
!if ${getenv('USE_LOCAL_CONFIG', 'false') == 'true'}:
  then:
    local_config: !include file:local.yaml

# or use a variable to select the config file
!define config_file: ${getenv('CONFIG_FILE', 'default.yaml')}
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
