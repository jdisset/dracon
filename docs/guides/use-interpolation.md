# How-To: Use Interpolation for Dynamic Values

Dracon allows embedding Python expressions in your YAML strings for dynamic configuration.

## Basic Lazy Interpolation (`${...}`)

Values enclosed in `${...}` are evaluated lazily – only when the configuration value is first accessed in your code.

```yaml
!define base_port: 8000
!define instance_num: ${getenv('INSTANCE_NUM', 0)} # Evaluated lazily

server:
  # Simple math using context variables
  port: ${base_port + instance_num}
  # String formatting
  host: "server-${instance_num}.example.com"
  # Conditional logic
  log_level: ${'DEBUG' if getenv('ENV') == 'dev' else 'INFO'}
```

**In Python:**

```python
import dracon as dr
import os

os.environ['INSTANCE_NUM'] = '3'
os.environ['ENV'] = 'dev'

config = dr.loads(yaml_content_above) # Assuming yaml_content_above holds the YAML

print(config.server.port)       # Output: 8003 (evaluates 8000 + 3)
print(config.server.host)       # Output: server-3.example.com
print(config.server.log_level)  # Output: DEBUG
```

## Referencing Other Config Values (`@`)

Inside a `${...}` expression, use `@` followed by a [KeyPath](../reference/keypaths.md) to reference the _final_ value of another configuration key after all loading, merging, and construction.

- **Absolute Path:** `@/path/from/root`
- **Relative Path:** `@.sibling_key`, `@../parent_key`

```yaml
app:
  name: "MyService"
  port: 9000

logging:
  # Absolute path reference
  filename: "/var/log/${@/app.name}.log" # -> /var/log/MyService.log
  # Relative path reference
  level_info: "Log level for ${@.filename}" # -> Log level for /var/log/MyService.log
```

**Important:** `@` references point to the _final, constructed_ value, but the expression itself is still evaluated lazily.

## Immediate Interpolation (`$(...)`)

Values enclosed in `$(...)` are evaluated _immediately_ during the YAML parsing phase.

**Use Cases:**

- Dynamically generating YAML tags.
- Calculating simple scalar values needed instantly.

**Limitations:**

- Cannot use `@` references (target values don't exist yet).
- Can only reliably access context variables defined _before_ the `$(...)` expression.

```yaml
!define type_name: "str"
!define scale: 10

config:
  # Tag determined immediately
  value: !$(type_name) 123.45 # Node gets tag !str

  # Value calculated immediately
  scaled_value: $(scale * 5.5) # Node gets value 55.0
```

## Using Context Variables

Both `${...}` and `$(...)` can access:

1.  Variables passed via `DraconLoader(context=...)`.
2.  Variables defined using `!define` or `!set_default` in the current or parent scope.
3.  Built-in functions like `getenv`, `getcwd`, `max`, `str`, etc.
4.  Automatic variables like `$DIR`, `$FILE` within included files (see [Includes Guide](use-includes.md)).

```python
# main.py
import dracon as dr
import os

def my_helper(a, b):
  return a * b + 1

context = {
  'ENV': os.getenv('ENVIRONMENT', 'dev'),
  'my_helper': my_helper
}

yaml_string = """
!define factor: 2
calculated: ${my_helper(@/input_value, factor)}
env_based: ${factor if ENV == 'prod' else factor * 2}
input_value: 10
"""

config = dr.loads(yaml_string, context=context)

print(config.calculated) # Output: 21 (my_helper(10, 2))
print(config.env_based)  # Output: 4 (factor * 2 because ENV='dev')
```

See [Interpolation Concepts](../concepts/interpolation.md) for more on the evaluation engine and safety considerations.
