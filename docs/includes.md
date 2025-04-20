# Includes (Modularity)

As configurations grow, keeping everything in one file becomes unwieldy. Dracon's `!include` system lets you split your configuration into logical, reusable parts and compose them together.
You can include YAML files from the filesystem or embedded in Python packages, and even include environment variables or other nodes defined in the document.

## Basic Syntax: `!include`

The primary way to include content is using the `!include` tag followed by a source identifier string.

```yaml
# Include content from settings.yaml in the same directory
app_settings: !include file:$DIR/settings.yaml # $DIR holds the current file's directory. see [Automatic Context Variables](#automatic-context-variables)

# Include default config from an installed Python package
defaults: !include pkg:my_package:path/to/configs/defaults.yaml

# Include an API key directly from an environment variable
api_key: !include env:MY_API_KEY

common_config: &common
  timeout: 30
  retries: 3

# Include a block defined by an anchor in THIS document
service_a:
  <<: !include common # Include using anchor name
  endpoint: /a
```

## Include Sources

Dracon supports several source types for `!include`:

1.  **Loaders (`loader:path`):**

    - `file:path/to/file.yaml`: Loads from the filesystem. Relative paths are resolved based on the including file's directory.
    - `pkg:package_name:path/to/resource.yaml`: Loads from resources within an installed Python package.
    - `env:VARIABLE_NAME`: Directly includes the string value of an environment variable.
    - `custom_loader:identifier`: Uses a custom loader function registered with `DraconLoader`.

2.  **Anchors (`anchor_name`):**

    - If the source string matches an anchor (`&anchor_name`) defined _earlier_ in the current effective document (including previous includes), Dracon includes a **deep copy** of the anchored node structure.

    ```yaml
    base_params:
      rate: 0.5
      limit: 100

    feature1:
      # Gets a copy of the base_params dictionary
      params: !include params
      specific: value1
    ```

    !!! warning "Copy vs. Reference (`*anchor`)"
    Standard YAML uses `*anchor_name` (aliases) to create **references** to the _same object instance_. Dracon intercepts `*anchor_name` syntax during composition and treats it like `!include anchor_name`, performing a **deep copy** of the node structure. This is useful for templating but differs from standard YAML behavior regarding object identity, especially for mutable types like lists and dicts. If you need object identity, use value references (`${@/path}`).

3.  **Context Variables (`$variable_name`):**

    - If the source string starts with `$` and matches a key in the _current node's context_, Dracon includes the value associated with that variable. The value is typically expected to be a node or something Dracon can represent as a node.

    ```yaml
    !define template_node: &tpl
      setting: default

    config:
      # Includes the node referenced by the 'template_node' variable
      instance1: !include $template_node
    ```

## Targeting Sub-keys (`source@path.to.key`)

You can include just a specific part of a source document by appending `@` followed by a [KeyPath](keypaths.md) to the key you want to extract.

```yaml
# settings.yaml
database:
  host: db.example.com
  port: 5432
  pool:
    size: 10
logging:
  level: INFO
```

```yaml
# main.yaml
# Include only the database host
db_host: !include file:settings.yaml@database.host # Result: "db.example.com"

# Include the entire database section
database_config: !include file:settings.yaml@database

# Include the pool size
pool_size: !include file:settings.yaml@database.pool.size # Result: 10
```

!!! note
Keys containing literal dots (`.`) within the source document need to be escaped with a backslash (`\.`) in the KeyPath target. E.g., `source@section\.with\.dots`.

## Interpolation in Include Paths

Include paths themselves can contain [Interpolation](interpolation.md) expressions, allowing for dynamic includes based on context.

```yaml
!define ENV: ${getenv('DEPLOY_ENV', 'dev')}

# Include environment-specific settings
env_settings: !include file:./config/settings_${ENV}.yaml

# Include version-specific config from a package
versioned_api: !include pkg:my_api:v${API_VERSION}/config.yaml
```

## Automatic Context Variables

When using `file:` or `pkg:` loaders, Dracon automatically adds variables to the context of the _included_ file's nodes, which are useful for relative path resolution:

- `$DIR`: The directory containing the included file.
- `$FILE`: The full path to the included file.
- `$FILE_STEM`: The filename without the extension.
- `$FILE_EXT`: The file extension (including the dot).
- `$FILE_LOAD_TIME`: Timestamp (YYYY-MM-DD HH:MM:SS).
- `$FILE_LOAD_TIME_UNIX`: Unix timestamp (seconds).
- `$FILE_LOAD_TIME_UNIX_MS`: Unix timestamp (milliseconds).
- `$FILE_SIZE`: File size in bytes.
- `$PACKAGE_NAME`: (For `pkg:` loader only) The name of the package.

```yaml
# Example: inside includes/component.yaml
template_dir: ${$DIR}/templates # Path relative to this file
log_file: /var/log/${$FILE_STEM}.log # Log file named after this file
```

## Best Practices

- **Organize:** Group related settings (database, logging, features) into separate files.
- **Layer:** Create a `base.yaml` and environment-specific files (`dev.yaml`, `prod.yaml`) that include and merge the base.
- **Secrets:** Keep sensitive data in separate, appropriately permissioned files and include them.
- **Relative Paths:** Use `$DIR` for includes within the same component/directory structure to make configurations more portable.
