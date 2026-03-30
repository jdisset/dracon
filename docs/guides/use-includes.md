# How-To: Include Files and Variables

Dracon's `!include` directive allows you to structure your configuration by composing it from multiple sources.

## Including YAML Files

Load content from another YAML file into the current structure.

```yaml
# main.yaml
database: !include file:database.yaml
logging: !include file:./logging_config.yaml # Relative path

# --- database.yaml ---
host: localhost
port: 5432
user: db_user

# --- logging_config.yaml ---
level: INFO
format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

**Resulting `main.yaml` structure:**

```yaml
database:
  host: localhost
  port: 5432
  user: db_user
logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

## Including from Packages

Load configuration bundled within installed Python packages.

```yaml
# Assuming 'my_package' has 'configs/defaults.yaml'
defaults: !include pkg:my_package:configs/defaults.yaml
```

## Using `$DIR` and Other Automatic Variables

When including via `file:` or `pkg:`, Dracon injects context variables into the _included_ file's scope:

- `$DIR`: Directory of the included file.
- `$FILE`: Full path to the included file (same as `$FILE_PATH`).
- `$FILE_STEM`: Filename without extension.
- `$FILE_EXT`: File extension (e.g., `.yaml`).
- `$FILE_LOAD_TIME`: Human-readable load timestamp.
- `$FILE_SIZE`: File size in bytes.
- `$PACKAGE_NAME`: (For `pkg:` only) Name of the package.

This is useful for relative includes _within_ the included file.

```yaml
# components/webserver/config.yaml
port: 8080
# Include sibling file using automatic $DIR
logging: !include file:$DIR/logging.yaml

# --- components/webserver/logging.yaml ---
level: DEBUG
file: /var/log/$FILE_STEM.log # -> /var/log/config.log
```

## Including Environment Variables

Directly insert the value of an environment variable during composition.

```yaml
# Load API_KEY directly into the config structure
api_key: !include env:API_KEY
secret: !include env:MY_APP_SECRET
```

!!! note
`!include env:VAR` fetches the variable during the _composition_ phase.
Using `${getenv('VAR')}` fetches it during _interpolation_ (usually lazy evaluation). Choose based on when you need the value.

## Including YAML Anchors (`*anchor`)

Dracon treats standard YAML aliases (`*anchor`) like `!include anchor_name`. It performs a **deep copy** of the anchored node structure, not a reference share.

```yaml
base_params: &params # Define anchor
  rate: 0.5
  limit: 100

feature1:
  # Gets a deep copy of base_params
  <<: *params # Use alias for merge
  specific: value1

feature2:
  # Also gets a deep copy
  params: *params
  other: value2
# Modifying feature1.rate will NOT affect feature2.params.rate
```

If you need actual object identity (reference sharing), use `${@/path}` references within interpolations.

## Including Specific Keys (`source@path`)

Load only a specific part of a source file or anchor using `@` followed by a [KeyPath](../reference/keypaths.md).

```yaml
# --- settings.yaml ---
database:
  host: db.example.com
  port: 5432
logging:
  level: INFO

# --- main.yaml ---
# Include only the database host
db_host: !include file:settings.yaml@database.host # Result: "db.example.com"

# Include only the logging level
log_level: !include file:settings.yaml@logging.level # Result: INFO
```

## Dynamic Includes with Interpolation

The include path itself can use interpolation.

```yaml
!define ENV: ${getenv('DEPLOY_ENV', 'dev')}

# Include environment-specific settings
env_settings: !include file:./config/settings_${ENV}.yaml

# Include versioned config from package
versioned_api: !include pkg:my_api:v${API_VERSION}/config.yaml
```

## Cascading Config Files

When you have config files scattered at different directory levels (home dir, project root, subdirectory), use `cascade:` to find and layer them all automatically. This is the same pattern as `.gitconfig` or `.editorconfig` -- closer files override further ones.

```yaml
# main.yaml
settings: !include cascade:defaults.yaml
```

If your directory tree looks like this:

```
~/.config/defaults.yaml         # base defaults
~/projects/defaults.yaml        # project-level overrides
~/projects/myapp/defaults.yaml  # app-specific overrides
```

Running from `~/projects/myapp/`, cascade finds all three files and merges them. The app-specific file wins for any conflicting keys, but values only defined at higher levels are preserved.

### Starting from the Current File's Directory

By default, cascade walks up from the current working directory. To walk up from the file that contains the `!include` directive:

```yaml
settings: !include cascade:${DIR}/settings.yaml
```

### Controlling How Lists Merge

By default, lists from closer files **replace** lists from further files. To **append** instead, add a merge key prefix:

```yaml
# Append plugins from all levels instead of replacing
plugins: !include cascade:{<+}[+>]:plugins.yaml
```

### Extracting a Subtree

Combine cascade with `@keypath` to extract just the part you need from the merged result:

```yaml
# Only grab the database section from cascaded app configs
database: !include cascade:app.yaml@database
```

### Optional Cascade

Use `!include?` if it's fine for no matching files to exist:

```yaml
local_overrides: !include? cascade:local.yaml
```

See [Includes Concepts](../concepts/composition.md#includes) for more background.
