# Interpolation (Dynamic Values)

Interpolation allows you to embed dynamic Python expressions directly within your YAML configuration strings. This makes your configurations more flexible and adaptable to different environments or runtime conditions.

Dracon supports two main types of interpolation:

## 1. Lazy Interpolation: `${...}`

This is the primary and most common form.

- **Syntax:** `${python_expression}`
- **Evaluation:** **Deferred (Lazy)**. The expression is _not_ evaluated immediately when the YAML is parsed. Instead, Dracon creates a special `LazyInterpolable` object. The actual Python expression is evaluated only when the corresponding configuration value is first accessed in your Python code after loading, or when you call `resolve_all_lazy` on the loaded configuration.
- **Engine:** Uses the [asteval](https://asteval.readthedocs.io/en/latest/) library by default for safe evaluation. Can be switched to raw Python `eval` (see [Evaluation Engine](#evaluation-engine)).
- **Use Cases:** Calculating values based on other config keys, environment variables, or context provided at runtime. This is ideal for most dynamic configuration needs.

```yaml
!define base_port: 8000
!define instance_num: ${getenv('INSTANCE_NUM', 0)} # Env var lookup, happens lazily

server:
  # Simple arithmetic, uses context vars evaluated lazily
  port: ${base_port + instance_num}
  # String formatting
  host: "server-${instance_num}.example.com"
  # Conditional logic
  log_level: ${'DEBUG' if getenv('ENV') == 'dev' else 'INFO'}

database:
  # Referencing another final configuration value using @ and KeyPaths
  # See KeyPaths docs for syntax details.
  url: "postgresql://${user}:${password}@${@/server.host}:${@/server.port}/main_db"
  pool_size: ${max(4, instance_num * 2)} # Using built-in functions
```

### Referencing Other Values (`@`)

Inside a `${...}` expression, you can reference the _final, constructed value_ of another key using the `@` symbol followed by a [KeyPath](keypaths.md). KeyPaths allow navigation through the nested structure (e.g., `/path/from/root`, `.sibling`, `../parent`).

- **Absolute Path:** `${@/path/from/root}` starts from the configuration root.
- **Relative Path:** `${@.sibling_key}`, `${@../parent_key}`, `${@../sibling/key}` navigate relative to the current value's location.

```yaml
app:
  name: "MyService"
  port: 9000

logging:
  # Absolute path reference using KeyPath /app.name
  filename: "/var/log/${@/app.name}.log" # -> /var/log/MyService.log
  # Relative path reference using KeyPath .filename
  level_info: "Log level for ${@.filename}" # -> Log level for /var/log/MyService.log

subcomponent:
  value: 10
  # Relative path going up using KeyPath ../app.port
  reference: "App port is ${@../app.port}" # -> App port is 9000
```

!!! note
`@` references point to the value _after_ all composition (includes, merges) and construction (including Pydantic validation) for that target key are complete. The evaluation is still lazy, triggered when the referencing value is accessed.

### Referencing Nodes (`&`)

Inside a `${...}` expression, you can also reference the raw **node object** itself from _before_ construction using `&` followed by an anchor name or a [KeyPath](keypaths.md).

- **Syntax:** `${&anchor_name}`, `${&/path/to/node}`, `${&relative/path}`.
- **Behavior:** This gives the expression access to the YAML node object (e.g., a `DraconMappingNode`) as it exists during the _composition_ phase, potentially modified by includes or merges but _before_ it's converted into a final Python object.
- **Use Cases:** This is primarily useful for **templating**. You can use it inside list comprehensions or function calls to create multiple _copies_ or variations of a base node structure before they get constructed.

```yaml
# Template node (often hidden using !noconstruct or __dracon__)
__dracon__:
  service_template: &service_tpl
    protocol: http
    port: ${port_num} # port_num needs to be in context for this node
    retries: 3

# Generate multiple service configurations from the template
services:
  # Uses a list comprehension with the node reference (&)
  # Note the ':var=value' syntax to provide context to the template node copy
  # For each i, it creates a copy of the node referenced by &service_tpl,
  # providing 'port_num' in its context using ':'.
  ${[&service_tpl:port_num=8080+i for i in range(3)]}
  # Resulting structure before final construction:
  # - !mapping # Copy 1 with port_num=8080 in context
  #   protocol: http
  #   port: ${port_num}
  #   retries: 3
  # - !mapping # Copy 2 with port_num=8081 in context
  #   ...
  # - !mapping # Copy 3 with port_num=8082 in context
  #   ...
```

!!! important "`&` vs `@` Summary" - Use `${@path}` to get the **final constructed value** of another key (most common). - Use `${&node_ref}` (inside expressions) to work with the **node object before construction**, primarily for templating/duplication during composition. Evaluating _just_ `${&node_ref}` typically gives you a deep copy of the node's _value representation_ at evaluation time.

## 2. Immediate Interpolation: `$(...)`

This form is less common and serves specific purposes.

- **Syntax:** `$(python_expression)`
- **Evaluation:** **Immediate**. The expression is evaluated _during_ the initial YAML parsing and composition phase. The result of the expression replaces the `$(...)` token _before_ Dracon proceeds with parsing that part of the structure.
- **Engine:** Always uses the configured evaluation engine (`asteval` or `eval`).
- **Use Cases:**
  - Dynamically generating **YAML tags**: `!$(type_name_var)`
  - Calculating simple scalar values needed immediately during parsing.
- **Limitations:**
  - Cannot use `@` or `&` references (the target nodes/values don't reliably exist yet).
  - Can only access context variables that are already defined _statically_ before this point in the parsing process. Cannot reliably access values defined using `${...}`.

```yaml
!define type_name: "str"
!define scale: 10

config:
  # Tag is determined immediately based on type_name variable
  value: !$(type_name) 123.45 # Node gets tag !str

  # Value calculated immediately
  scaled_value: $(scale * 5.5) # Node gets value 55.0
```

## Context Availability

Expressions within both `${...}` and `$(...)` can access:

- Variables provided in the `DraconLoader(context=...)`.
- Standard Python built-ins (`len`, `str`, `int`, `max`, etc.).
- Variables defined using `!define` or `!set_default` in the current or parent scope _before_ the expression is encountered (more reliable for `$(...)`).
- Special loader context variables like `$DIR`, `$FILE` (available within included files, often used with the shorthand `!include file:$DIR/...`, see [Includes](includes.md)).

## Evaluation Engine

By default, Dracon uses the `asteval` library for evaluating `${...}` and `$(...)` expressions. This provides a restricted environment that prevents execution of arbitrary, potentially unsafe code (like filesystem access or network calls) within your configuration files.

You can choose to use Python's built-in `eval()` function instead, which allows execution of _any_ Python code but carries significant security risks if your configuration files might come from untrusted sources.

**Switching the Engine:**

```python
from dracon import DraconLoader

# Default (safe) engine
loader_safe = DraconLoader(enable_interpolation=True) # interpolation_engine defaults to 'asteval'

# Use Python's raw eval (use with extreme caution!)
loader_raw = DraconLoader(enable_interpolation=True, interpolation_engine='eval')

# Disable interpolation evaluation entirely
loader_no_interp = DraconLoader(enable_interpolation=False) # or engine='none'
```

!!! warning "Security Risk with `eval`"
Using `interpolation_engine='eval'` should only be done if you fully trust the source and content of all your YAML configuration files. Malicious code embedded in `${...}` or `$(...)` could be executed with the permissions of your application. **`asteval` is strongly recommended for most use cases.**

## How Lazy Evaluation Works (`Dracontainer`)

When you load a configuration with `${...}` expressions, Dracon typically constructs mappings and sequences using its internal `dracon.dracontainer.Mapping` and `dracon.dracontainer.Sequence` types. These containers override attribute access (`__getattr__`, `__getitem__`) to automatically trigger the resolution of `LazyInterpolable` objects the first time they are accessed. If you configure `DraconLoader` to use standard `dict` and `list`, this automatic resolution doesn't happen, and you might need to manually trigger resolution if needed (e.g., by iterating through the structure or using helper functions like `resolve_all_lazy`).
