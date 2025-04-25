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
- `$FILE`: Full path to the included file.
- `$FILE_STEM`: Filename without extension.
- `$PACKAGE_NAME`: (For `pkg:` only) Name of the package.
- ... and others related to time/size.

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

See [Includes Concepts](../concepts/composition.md#includes) for more background.
