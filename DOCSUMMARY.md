Dracon is a modular configuration system and command-line interface (CLI) generator for Python, built on top of YAML. It extends standard YAML with powerful features for composing complex configurations and seamlessly integrates with Pydantic for type safety and validation.

# 1. Configuration Loading & Pydantic Integration

Dracon loads YAML from files or strings, validates it against Pydantic models, and returns structured Python objects.

## Loading Functions

```python
from dracon import load, loads, DraconLoader
from pydantic import BaseModel

class DBConfig(BaseModel):
    host: str = 'localhost'
    port: int = 5432

class AppConfig(BaseModel):
    database: DBConfig

# Load from file, validating against a Pydantic model
config = load('config.yaml', context={'AppConfig': AppConfig})

# Load from string
config = loads("database: {host: 'db.prod', port: 5433}", context={'AppConfig': AppConfig})

# Load and merge multiple files (later files override earlier ones)
config = load(['base.yaml', 'prod.yaml'], context={'AppConfig': AppConfig})

# For more control, use DraconLoader
loader = DraconLoader(context={'AppConfig': AppConfig})
config = loader.load('config.yaml')
```

## Pydantic Model Construction in YAML

Use `!TagName` to map a YAML node to a Pydantic model provided in the `context`. Using `!module.TypeName` is also supported; Dracon will attempt to import the module and resolve the type.

```yaml
# config.yaml
# Dracon uses the DBConfig model from the context to validate this section
database: !DBConfig
  host: db.example.com
  port: 5433

# If a section matches the structure but lacks a tag, Dracon still attempts construction.
# Using tags is more explicit and robust.
app: !AppConfig
  database:
    host: db.example.com
```

## Dracon Containers vs. `raw_dict`

By default, `load()` returns `dracon.dracontainer.Mapping` and `Sequence` objects. These custom containers automatically resolve lazy `${...}` expressions upon attribute or item access (e.g., `config.my_key` or `config['my_key']`).

For standard Python types, use `load(..., raw_dict=True)`. With this option, the return value will contain unresolved `LazyInterpolable` objects for any `${...}` expressions. You must then manually call `dracon.resolve_all_lazy(config)` to evaluate all interpolations before use.

# 2. YAML Language Extensions

Dracon enhances YAML with instructions, includes, advanced merging, and interpolation.

## 2.1. Composition Instructions

Instructions manipulate the YAML structure and context during the composition phase.

### Variable Definition: `!define` & `!set_default`

Define variables for reuse within the configuration.

- `!define`: Sets or overwrites a variable.
- `!set_default`: Sets a variable only if it's not already defined.

```yaml
!define app_name: my-service
!set_default env: ${getenv('ENV', 'dev')} # Set env only if not inherited

service_name: ${app_name}-${env} # "my-service-dev"
```

### Conditional Logic: `!if`

Include configuration blocks based on a condition evaluated at composition time.

```yaml
!define is_prod: ${getenv('ENV') == 'production'}

settings:
  # This block is only included if is_prod is true
  !if ${is_prod}:
    monitoring: full
    retries: 5
  # An if/then/else structure is also supported
  !if ${is_prod}:
    then: { workers: 8 }
    else: { workers: 2 }
```

### Loops: `!each`

Generate configuration nodes by iterating over a list or dictionary.

```yaml
!define environments: [dev, staging, prod]
!define services: { web: 80, api: 8080 }

# Generate a dict of environment-specific databases (shorthand syntax)
databases:
  !each(env) ${environments}:
    ${env}_db:
      host: db.${env}.local

# Generate a list of service objects
service_list:
  !each(name , port) ${services.items()}:
    - name: ${name}
      port: ${port}
```

!!! note "Formal Dictionary Syntax"
Dracon's shorthand is common, but for full YAML compliance, you can use the formal _complex key_ syntax (`? :`) to generate dictionaries:
`yaml
    databases:
      ? !each(env) ${environments}
      : ${env}_db: { host: db.${env}.local }
    `

### Construction Control: `!noconstruct` & `__dracon__`

Define helper nodes or templates that are available during composition but are removed from the final output.

```yaml
# Define a template but hide it from the final config
!noconstruct &service_defaults:
  timeout: 60
  retries: 3

# Alternative using a namespaced key
__dracon__templates:
  db_defaults: &db_defaults
    pool_size: 10

# Use the templates
http_service:
  <<: *service_defaults
database:
  <<: *db_defaults
```

## 2.2. Includes (`!include`)

Compose configurations by including content from various sources.

### Include Sources

```yaml
# From a file (relative path is robust with $DIR)
database: !include file:$DIR/database.yaml

# From an installed Python package
defaults: !include pkg:my_package:configs/defaults.yaml

# From an environment variable
api_key: !include env:API_KEY

# From a defined variable
!define config_name: advanced
current_config: !include var:config_name

# From a YAML anchor (performs a deep copy)
base_config: &base { timeout: 30 }
service:
  <<: *base
```

### Sub-key Selection (`@`)

Load only a specific part of a source using `@` followed by a [KeyPath](#41-keypaths).

```yaml
# Include only the database host from settings.yaml
db_host: !include file:settings.yaml@database.host
```

### Automatic Context Variables

When including files (`file:`, `pkg:`), Dracon provides context variables like `$DIR` (directory of current file), `$FILE`, and `$FILE_STEM`.

## 2.3. Merging (`<<:`)

Dracon extends the YAML merge key (`<<:`) with fine-grained control over dictionary and list merging.

**Syntax**: `<<{dict_opts}[list_opts]@target_path: source_node`

- **Dictionary Options `{}`**:
  - **Mode**: `+` (recursive merge, default) or `~` (replace keys).
  - **Priority**: `>` (existing value wins, default) or `<` (new value wins).
  - **Depth**: `+N` limits recursion depth to N levels.
- **List Options `[]`**:
  - **Mode**: `+` (concatenate) or `~` (replace, default).
  - **Priority**: `>` (existing first/wins, default) or `<` (new first/wins).
- **Target Path `@`**: Optional relative [KeyPath](#41-keypaths) to merge into.

**Default Behavior**: `<<:` alone is equivalent to `<<{+>}[~>]` (recursive dict merge, existing wins; list replace, existing wins).

```yaml
# base.yaml: { a: 1, b: { x: 10 }, c: [1, 2] }

# Recursive merge, new/source values win for dicts
# <<{+<}: !include base.yaml
# With { a: 2, b: { y: 20 } } -> { a: 2, b: { x: 10, y: 20 }, c: [1, 2] }

# Concatenate lists, new/source list prepended (<)
# <<[+<]: !include base.yaml
# With { c: [3, 4] } -> { a: 1, b: { x: 10 }, c: [3, 4, 1, 2] }

# Replace dictionaries completely, new/source wins
# <<{~<}: !include base.yaml
# With { b: { y: 20 } } -> { a: 1, b: { y: 20 }, c: [1, 2] }
```

## 2.4. Interpolation

Embed dynamic Python expressions in YAML strings. The default engine is `asteval` (safe); `eval` can be enabled.

### Lazy (`${...}`) vs. Immediate (`$(...)`)

- **`${...}` (Lazy)**: Evaluated when the value is accessed. Can reference other final config values. Most common.
- **`$(...)` (Immediate)**: Evaluated during YAML parsing. Useful for dynamic tags. Cannot reference other values.

```yaml
# Lazy: evaluated on access
runtime_value: ${time.time()}

# Immediate: evaluated during parsing
load_time: $(time.time())
config: !$(my_type_var) { ... }
```

### Triggering Resolution: `resolve_all_lazy()`

By default, Dracon's custom containers (`Mapping`, `Sequence`) resolve `${...}` expressions on access. When using standard types (`raw_dict=True`) or needing all values finalized for inspection (like in tests), use `resolve_all_lazy()` to walk the configuration and evaluate all pending interpolations.

```python
from dracon import loads, resolve_all_lazy

# config contains LazyInterpolable objects initially
config = loads("value: ${1+1}", raw_dict=True)

# Now, config['value'] will be the integer 2
resolve_all_lazy(config)
assert config['value'] == 2
```

### Value Referencing (`@` and `&`)

- **`@` (KeyPath Reference)**: References the _final, constructed value_ of another key.
- **`&` (Anchor Node Copy)**: References the _raw YAML node_ at an anchor, performing a deep copy.

```yaml
environment: prod
defaults: &defaults { timeout: 30 }

# KeyPath reference to final 'environment' value
db_host: "db.${@/environment}.local" # -> "db.prod.local"

# Node copy of 'timeout' from anchor
service_timeout: ${&defaults.timeout * 2} # -> 60
```

### Key Interpolation

Generate dynamic dictionary keys using `!each` to create a mapping.

```yaml
# Generate top-level keys like dev_database_url, staging_database_url, etc.
!define environments: [dev, staging, prod]
!each(env) ${environments}:
  ${env}_database_url: "postgres://db.${env}.local"
```

# 3. CLI Generation

Generate a full-featured, type-safe CLI directly from a Pydantic model.

## Automatic Generation and Customization (`Arg`)

Use `make_program` to create a CLI. Customize arguments with `typing.Annotated` and `dracon.Arg`.

```python
from typing import Annotated, Literal
from pydantic import BaseModel
from dracon import Arg, make_program

class CliConfig(BaseModel):
    # Required positional argument
    input_file: Annotated[str, Arg(positional=True, help="Input data file.")]
    # Optional argument with short flag
    env: Annotated[Literal['dev', 'prod'], Arg(short='e', help="Environment.")]
    # Boolean flag
    debug: Annotated[bool, Arg(help="Enable debug mode.")] = False
    # List argument (accepts space-separated values)
    tags: Annotated[list[str], Arg(help="Tags to apply.")] = []
    # Argument that loads a file's content
    secrets: Annotated[dict, Arg(is_file=True, help="Path to secrets file.")]

program = make_program(CliConfig, name="myapp")
config, raw_args = program.parse_args()
```

## Usage Patterns and Precedence

Configuration is applied in the following order (later steps override earlier ones):

1.  Pydantic model defaults.
2.  Configuration files loaded via `+file.yaml`.
3.  Context variables defined via `++var=value` (or `--define.var value` or `++var value`).
4.  CLI argument overrides (`--arg value`).

```bash
# Show auto-generated help
myapp --help

# Basic usage
myapp /path/to/data -e prod --tags web api --debug

# Load config files (merged in order)
myapp /path/to/data +base.yaml +prod.yaml

# Override nested values
myapp /path/to/data -e prod --database.host db.override --database.port 5433

# Load a file's content as an argument's value
myapp /path/to/data -e prod --secrets +secrets.yaml
# ...or for any argument by prefixing with +
myapp /path/to/data -e prod --api-key +/path/to/key.txt

# Define a context variable for use in YAML interpolation
myapp /path/to/data -e prod ++region=us-west-2
# Space-separated syntax also works
myapp /path/to/data -e prod ++region us-west-2
```

# 4. Advanced Topics

## 4.1. KeyPaths

Dracon uses dot-separated paths to reference specific locations in a configuration.

- **Separator**: `.` (dot).
- **Root**: `/` at the beginning of a path.
- **Parent**: `..` navigates up one level.
- **Wildcards**: `*` (single segment), `**` (zero or more segments) in matching patterns.
- **Escaping**: `\.` to escape a literal dot in a key name.

**Example**: `@/database.host`, `!include file.yaml@services.0.port`, `deferred_paths=['/users/*/profile']`.

## 4.2. Deferred Execution

Delay construction or evaluation of parts of the configuration until runtime.

- **`DeferredNode`**: Pauses the _entire construction_ of a YAML node branch. Created with `!deferred` tag or `deferred_paths`. Manually triggered with `construct(node, context={...})`. Use for late-binding of context or delaying resource-intensive object creation.

  ```yaml
  # In YAML
  output_path: !deferred "/data/${runtime_id}/logs"

  # In Python
  final_path = construct(config.output_path, context={'runtime_id': 'job_123'})
  ```

- **`Resolvable[T]`**: Delays the _final processing_ of a _single field's value_. Used as a type hint, often with `Arg(resolvable=True)`. Manually triggered with `value.resolve(context={...})`. Use for post-processing CLI args that depend on other values.

## 4.3. Secret Management

Combine Dracon features for secure secret handling.

```yaml
# secrets.yaml
database:
  # Load from environment variable (recommended for deployment)
  password: !include env:DB_PASSWORD

  # Load from a gitignored file (useful for local dev)
  username: !include file:$DIR/secrets/db_user.txt

# Load from a secrets manager via a custom loader (advanced)
api_key: !include vault:secret/data/myapp#api_key
```

# 5. Design Philosophy

> Dracon is designed to hit a "powerful but transparent" sweet spot. It avoids being overly simplistic (requiring manual boilerplate) or overly magical (hiding configuration details). The goal is to provide explicit, composable tools to manage configuration layers from files, environment variables, and the CLI in a structured, type-safe, and predictable way.

# Loading Lifecycle

When `load()` is called, the process unfolds in distinct stages:

1.  **Composition:** The raw YAML is parsed. Instructions like `!define`, `!if`, and `!each` are executed immediately, manipulating the internal YAML structure and context _before_ anything else.
2.  **Include Resolution:** `!include` directives are resolved recursively. The content from included sources is loaded, composed, and inserted into the main tree.
3.  **Merging:** `<<:` keys are processed in the order they appear. The strategies you define (`{+<}`, `[+>]`, etc.) are applied to combine different parts of the configuration tree.
4.  **Construction:** The final, composed YAML tree is traversed to build Python objects. Pydantic models are validated and instantiated at this stage. Values containing `${...}` are wrapped in `LazyInterpolable` objects.
5.  **Lazy Interpolation Resolution:** `${...}` expressions are only evaluated when their corresponding values are accessed in your Python code (or when `resolve_all_lazy()` is called). This allows them to reference other fully constructed values in the configuration.
