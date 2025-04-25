# Concepts: Composition Instructions

Dracon provides special instruction tags (`!define`, `!if`, `!each`, `!noconstruct`) that allow you to embed logic directly into your YAML. These instructions operate _during the composition phase_, manipulating the YAML node tree and context _before_ includes, merges, or final Python object construction occurs.

## Defining Variables (`!define`, `!set_default`)

These instructions create variables within the configuration's context, making them available for subsequent interpolation (`${...}`, `$(...)`) or use within other instructions (`!if`, `!each`).

- **`!define var_name: node_value`**

  - Evaluates `node_value` _at composition time_. If `node_value` itself contains interpolations (`${...}` or `$(...)`), they are resolved immediately based on the context _at that point_.
  - Assigns the resulting value to `var_name` in the context of the current node and its descendants.
  - **Overwrites** any existing variable with the same name in the current scope.
  - The `!define var_name: ...` entry is **removed** from the final configuration structure.

- **`!set_default var_name: node_value`**
  - Similar to `!define`, but only sets `var_name` if it does _not_ already exist in the current context scope.
  - Useful for providing defaults that can be overridden by parent contexts or earlier includes.
  - Also removed from the final configuration structure.

```yaml
# --- Example ---
!define app_version: "1.2.0" # Simple string definition
!define is_prod: ${getenv('ENV') == 'production'} # Evaluated now using env var
!set_default log_level: "INFO" # Set only if not already defined

config:
  version: ${app_version} # Uses "1.2.0" (available from parent scope)
  debug_mode: ${not is_prod} # Uses the boolean calculated earlier
  logging:
    level: ${log_level} # Uses "INFO" unless overridden elsewhere
```

**Final `config` object:** `{ "version": "1.2.0", "debug_mode": ..., "logging": { "level": "INFO" } }` (The `!define` keys are gone).

## Conditional Composition (`!if`)

Includes or excludes configuration blocks based on a condition evaluated _at composition time_.

- **Syntax:** `!if <condition_expr>: <node_value>`
- **Behavior:**
  - `<condition_expr>` is evaluated. It can be a boolean literal (`true`/`false`), an integer (0 is false, others true), a string (non-empty is true), or an interpolation (`${...}` or `$(...)`) resolving to a truthy/falsy value _at composition time_.
  - **If True:**
    - If `<node_value>` is a mapping, its key-value pairs are merged into the parent mapping (using default merge).
    - If `<node_value>` is a scalar/sequence, the _entire_ `!if ...: ...` entry is replaced by `<node_value>` (mainly useful if the parent is a sequence).
  - **If False:** The _entire_ `!if ...: ...` entry is **removed**.

```yaml
!define enable_feature_x: ${getenv('FEATURE_X') == 'true'}
!define env: "prod"

settings:
  base_setting: true
  # This block included only if enable_feature_x is true
  !if ${enable_feature_x}:
    feature_x_url: "http://feature-x.svc"
    retries: 5

  # This block included because env == "prod" evaluates to true
  !if ${env == "prod"}:
    monitoring: full
    sampling: 0.1

  # This block removed because env == "dev" is false
  !if ${env == "dev"}:
    debug_endpoint: "/_debug"
```

## Iterative Composition (`!each`)

Generates multiple configuration nodes by iterating over a list or other iterable evaluated _at composition time_.

- **Syntax:** `!each(<loop_var>) <iterable_expr>: <node_template>`
- **Behavior:**
  - `<iterable_expr>` (e.g., `${list_variable}`, `${range(3)}`) is evaluated at composition time to produce an iterable.
  - For each `item` in the iterable:
    - A **deep copy** of `<node_template>` is made.
    - A temporary context `{ <loop_var>: item }` is merged into the copied node's context (overriding any existing `<loop_var>`).
    - If `<node_template>` is a sequence item (`- value`), the processed copy is appended to the resulting list.
    - If `<node_template>` is a mapping (`key: value`), the processed copy's key-value pairs are added to the resulting dictionary. Keys within the mapping template often _must_ use interpolation (e.g., `key_${loop_var}`) to ensure uniqueness.
  - The original `!each...` entry is replaced by the generated list or dictionary.

```yaml
!define user_list: ["alice", "bob"]
!define service_ports: { web: 80, api: 8080 }

config:
  # Generate a list of user objects
  users:
    !each(name) ${user_list}: # Iterate over the list variable
      - user_id: ${name.upper()} # Use loop_var 'name'
        home: "/home/${name}"

  # Generate a dictionary of service configs
  services:
    ? !each(svc_name) ${service_ports.keys()} # Iterate over dict keys
      # Use loop_var in the key for uniqueness
    : ${svc_name}_config:
        port: ${service_ports[svc_name]} # Access original dict using loop_var
        protocol: http
```

**Resulting `config` (before final construction):**

```yaml
config:
  users:
    - user_id: ALICE
      home: "/home/alice"
    - user_id: BOB
      home: "/home/bob"
  services:
    web_config:
      port: 80
      protocol: http
    api_config:
      port: 8080
      protocol: http
```

## Excluding Nodes (`!noconstruct`, `__dracon__`)

Sometimes you need helper nodes or templates during composition that shouldn't appear in the final constructed configuration object.

- **`!noconstruct <node>`**

  - Applies to any node (scalar, sequence, mapping).
  - The node exists during composition (can be referenced via anchors `&`, includes `!include`, or defines `!define`) but it and its children are **completely removed** before the final construction phase begins.

- **`__dracon__<key>: ...`**
  - Applies only to top-level keys in a mapping.
  - Any key starting with `__dracon__` behaves as if `!noconstruct` was applied to its _value_.
  - Provides a convenient namespace for composition-only helpers.

```yaml
# Define a template but hide it from the final output
!noconstruct &service_defaults:
  timeout: 60
  protocol: https

# Alternative using __dracon__ namespace for organization
__dracon__templates:
  db_defaults: &db_defaults
    pool_size: 10
    encoding: utf8

# --- Use the templates ---
http_service:
  <<: *service_defaults # Include the copy (deep copy)
  protocol: http        # Override protocol

database:
  <<: *db_defaults     # Include the copy
```

**Final constructed config:**

```python
{
  "http_service": {"timeout": 60, "protocol": "http"},
  "database": {"pool_size": 10, "encoding": "utf8"}
}
# The '!noconstruct' node and '__dracon__templates' key are gone.
```
