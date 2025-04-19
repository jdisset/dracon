# Instructions (Composition Logic)

Beyond includes and merges, Dracon provides special `!instruction` tags that allow you to embed logic directly into your YAML to control how the configuration structure is assembled _during the composition phase_. These instructions operate on the YAML node tree _before_ final Python objects are constructed.

## Defining Variables: `!define` and `!set_default`

These instructions let you create variables within the configuration's context, which can then be used in subsequent [Interpolation](interpolation.md) expressions (`${...}` or `$(...)`).

- **`!define var_name: node_value`**

  - Assigns the constructed value of `node_value` to `var_name` in the context of the current node and its children.
  - If `node_value` contains an interpolation expression (`${...}` or `$(...)`), it is evaluated _at composition time_.
  - The `!define var_name: ...` entry itself is **removed** from the final configuration mapping.
  - Overwrites any existing variable with the same name in the current context scope.

- **`!set_default var_name: node_value`**
  - Similar to `!define`, but only sets `var_name` if it doesn't _already exist_ in the current context scope.
  - Useful for providing default values that can be overridden by earlier includes or parent contexts.
  - Also removed from the final configuration mapping.

```yaml
# --- Example ---
!define app_version: "1.2.0"
!define is_prod: ${getenv('ENV') == 'production'} # Evaluated now
!set_default log_level: "INFO" # Set only if not already defined

config:
  version: ${app_version} # Uses "1.2.0"
  debug_mode: ${not is_prod} # Uses calculated boolean
  logging:
    level: ${log_level} # Uses "INFO" unless overridden earlier

# The final 'config' object will NOT contain keys like '!define app_version'.
# It will only have 'version', 'debug_mode', and 'logging'.
```

## Conditional Composition: `!if`

Conditionally includes or excludes configuration blocks based on an expression evaluated at composition time.

- **Syntax:** `!if condition_expr: node_value`
- **Behavior:**
  - `condition_expr` is evaluated. It can be a boolean, an integer, a string evaluating to true/false, or an interpolation expression (`${...}` or `$(...)`) that resolves to a truthy/falsy value _at composition time_.
  - If the condition is **truthy**:
    - If `node_value` is a mapping, its key-value pairs are merged into the parent mapping.
    - If `node_value` is a scalar or sequence, the entire `!if condition_expr: node_value` entry is replaced by `node_value` (this typically only makes sense if the parent is a sequence).
  - If the condition is **falsy**, the entire `!if condition_expr: node_value` entry is **removed**.

```yaml
!define enable_feature_x: ${getenv('FEATURE_X_ENABLED', 'false') == 'true'}
!define env: "prod"

settings:
  base: true
  # This block is only included if enable_feature_x is true
  !if ${enable_feature_x}:
    feature_x_url: "http://feature-x.svc"
    feature_x_retries: 5

  # This block is included because env == "prod"
  !if ${env == "prod"}:
    monitoring_level: full
    sampling_rate: 0.1

  # This block is removed because env != "dev"
  !if ${env == "dev"}:
    debug_endpoint: "/_debug"
```

## Iterative Composition: `!each`

Generates multiple configuration nodes by iterating over a list or other iterable evaluated at composition time.

- **Syntax:** `!each(loop_var) iterable_expr: node_template`
- **Behavior:**
  - `iterable_expr` (often an interpolation like `${range(3)}` or `${list_variable}`) is evaluated at composition time to produce an iterable.
  - For each `item` in the iterable:
    - A temporary context is created where `loop_var` is set to the current `item`.
    - A **deep copy** of `node_template` is made.
    - The context `{loop_var: item}` is merged into the copied node's context.
    - If `node_template` is a sequence (`- value`), the processed copy is appended to the resulting list.
    - If `node_template` is a mapping (`key: value`), the processed key-value pairs are added to the resulting dictionary. Keys within the mapping template _must_ often be interpolations themselves (e.g., `key_${loop_var}: ...`) to ensure uniqueness.
  - The original `!each...` entry is replaced by the generated list or dictionary.

```yaml
!define user_list: ["alice", "bob"]

config:
  # Generate a list of user objects
  users:
    !each(name) ${user_list}:
      - user_id: ${name.upper()} # Use loop_var 'name'
        home_dir: "/home/${name}"
        enabled: true

  # Generate a dictionary of service ports
  ports:
    !each(i) ${range(2)}:
      # Keys must be unique, often use interpolation
      service_${i}: ${9000 + i}
      # Value can also use loop_var
      service_${i}_admin: ${9000 + i + 100}
```

```yaml
# Resulting structure after !each processing (before final construction):
config:
  users:
    - user_id: ALICE
      home_dir: "/home/alice"
      enabled: true
    - user_id: BOB
      home_dir: "/home/bob"
      enabled: true
  ports:
    service_0: 9000
    service_0_admin: 9100
    service_1: 9001
    service_1_admin: 9101
```

## Excluding Nodes: `!noconstruct` and `__dracon__`

Sometimes you need helper nodes or templates during composition that shouldn't appear in the final constructed configuration object.

- **`!noconstruct node`**

  - Applies to any node (scalar, sequence, mapping).
  - The node exists during composition and can be referenced (e.g., by `!define`, `!include`, or `&` references), but it and its children are completely **removed** before the final construction phase begins.

- **`__dracon__key: ...`**
  - Applies only to top-level keys in a mapping.
  - Any key starting with `__dracon__` (e.g., `__dracon__templates:`) behaves exactly as if it had `!noconstruct` applied to its _value_.
  - This provides a convenient namespace for composition-only helpers without needing the `!noconstruct` tag everywhere.

```yaml
# Define a template but hide it from the final output
!noconstruct &service_defaults:
  timeout: 60
  protocol: https

# Alternative using __dracon__ namespace
__dracon__templates:
  db_defaults: &db_defaults
    pool_size: 10
    encoding: utf8

# Use the templates
http_service:
  <<: *service_defaults # Include the copy
  protocol: http # Override

database:
  <<: *db_defaults # Include the copy
```

```yaml
# Final constructed config:
# {
#   "http_service": {"timeout": 60, "protocol": "http"},
#   "database": {"pool_size": 10, "encoding": "utf8"}
# }
# The '!noconstruct' node and '__dracon__templates' are gone.
```
