# Expression Interpolation

Dracon's interpolation system enables you to embed Python expressions in your YAML configurations. This brings dynamic value generation, calculations, and complex logic to what would otherwise be static configuration files.

## Interpolation Types

Dracon supports two distinct types of interpolation:

### 1. Lazy Interpolation - `${...}`

The primary syntax uses curly braces and evaluates expressions when the value is accessed:

```yaml
port: ${8080 + instance_id}
debug: ${env != 'production'}
greeting: ${"Hello, " + username + "!"}
```

Lazy interpolation means the expression is calculated "just in time" when the value is actually used. This allows referencing values that might not be available during parsing.

### 2. Immediate Interpolation - `$(...)`

This alternative syntax with parentheses evaluates expressions during parsing:

```yaml
!define current_time: $(time.strftime('%Y-%m-%d'))
tag_immediate: !$(str('float')) 5.0 # Results in: !float 5.0
```

Immediate interpolation is useful for type tags and other values needed during the parsing phase.

## Using Python Expressions

You can use most Python expressions inside interpolation:

### Basic Operations

```yaml
# Arithmetic
memory_mb: ${1024 * 8}
timeout_sec: ${timeout_min * 60}

# String operations
greeting: ${"Hello, " + username.title() + "!"}
uppercase: ${service_name.upper()}

# Boolean logic
is_admin: ${role == 'admin' or username in admin_list}
debug_logging: ${env != 'production' and enable_debug}
```

### Conditional Expressions

```yaml
# Ternary conditionals
mode: ${'production' if env == 'prod' else 'development'}
log_level: ${'DEBUG' if debug else 'INFO'}
```

### Working with Collections

```yaml
# List operations
first_item: ${items[0]}
item_count: ${len(items)}
filtered: ${[x for x in items if x > threshold]}

# Dictionary operations
api_url: ${urls.get('api', 'https://api.default.com')}
```

## Path References

Dracon has a special syntax for referencing other values in your configuration using `@`:

### Absolute Paths

Use a leading slash (`/`) to reference from the root of the configuration:

```yaml
database:
  host: "db.example.com"
  port: 5432
  url: ${"postgresql://" + @/database/host + ":" + str(@/database/port)}
# This references database.host from the root config
```

### Relative Paths

Reference values relative to the current location:

```yaml
service:
  name: "api-service"
  # Reference the sibling "name" field
  log_prefix: ${@name + ": "}

  logging:
    # Reference parent's "name" field
    file: ${@../name + ".log"}
```

### Parent References

Navigate up the tree with `..`:

```yaml
deep:
  nested:
    structure:
      value: 42
      # Go up two levels and access a sibling
      reference: ${@../../sibling}
  sibling: "hello"
```

## Node References

Use `&` to reference entire nodes (not just their values):

```yaml
__dracon__template: # This node won't appear in final config
  base_service: &base_service
    created_at: ${datetime.now()}
    version: ${VERSION}

# Create multiple objects from the template
services:
  web: &base_service
  api:
    <<: &base_service
    port: 8080
```

The difference between `&` and `@`:

- `&` creates a reference to a node, which can be duplicated and modified
- `@` references a value in the final, constructed configuration

## Context and Variables

### Predefined Variables

Dracon provides several built-in variables:

```yaml
# Environment variables
host: ${env.get('HOST', 'localhost')}

# Special file context variables (available in included files)
file_dir: ${$DIR}
file_name: ${$FILE_STEM}
```

### Custom Context Variables

You can provide additional variables when loading configurations:

```python
loader = DraconLoader(
    context={
        'VERSION': '1.0.0',
        'ENVIRONMENT': 'production',
        'get_uuid': lambda: str(uuid.uuid4()),
        'now': datetime.now
    }
)
```

Then use them in your YAML:

```yaml
app:
  version: ${VERSION}
  env: ${ENVIRONMENT}
  id: ${get_uuid()}
  start_time: ${now()}
```

## Type Interpolation

You can interpolate both values and types:

```yaml
# Interpolate the type tag
value: !${type_name} ${value}

# Examples
as_int: !${'int'} ${2.5}          # Results in integer 2
as_str: !${'str'} ${123}          # Results in string "123"
dynamic_type: !${chosen_type} 42  # Type from variable
```

## Advanced Techniques

### Multiple Interpolations

You can nest interpolations:

```yaml
# Nested interpolations
double: ${int(${value} * 2)}

# Multiple interpolations in a string
connection: ${"Host=" + host + ";Port=" + str(${port})}
```

### Function Calls

Call functions from your context:

```yaml
# Assuming these are in your context
uuid: ${generate_uuid()}
timestamp: ${time.time()}
random_value: ${random.choice(['a', 'b', 'c'])}
```

### Working with Defaults

Handle potentially undefined values:

```yaml
# Default if the variable doesn't exist
region: ${globals().get('AWS_REGION', 'us-east-1')}

# Using or with interpolation
db_url: ${database_url or "sqlite:///app.db"}
```

## Best Practices

1. **Keep expressions simple** - Complex logic belongs in your code, not config
2. **Use meaningful defaults** - Handle missing values gracefully
3. **Watch for side effects** - Avoid expressions with unintended consequences
4. **Define common values** - Use `!define` for values referenced multiple times

By using interpolation effectively, you can create flexible configurations that adapt to their environment without sacrificing readability or maintainability.
