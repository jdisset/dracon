# Expression Interpolation

Dracon's interpolation system allows you to embed Python expressions in your YAML configurations. This enables dynamic value generation and complex configuration logic.
The expressions are evaluated using the [asteval](https://lmfit.github.io/asteval/) library, which provides a safe environment for executing Python code.

An interpolated expression is enclosed in `${...}` and can contain any valid Python. By default, the expression is evaluated lazily when the parameter is accessed, allowing you to reference other values, environment variables, or custom context variables.
Some specific fields trigger immediate evaluation, such as type tags and keys in the `!include` directive, or the `!define` instruction. (see [Inclusion](includes.md) and [Instructions](instructions.md))

An interpolated expression can generally be used in most fields of a dracon YAML file, including keys, values, and even type tags.

## Basic Syntax

Use `${expression}` to interpolate Python expressions:

```yaml
# Basic arithmetic
port: ${8080 + instance_id}

# String operations
greeting: ${"Hello, " + username + "!"}

# Conditional expressions
mode: ${'production' if env == 'prod' else 'development'}
```

## Referencing Values

### Path References

Use `@` to reference other values in the configuration:

```yaml
database:
  host: localhost
  port: 5432
  url: ${"postgresql://" + @/database/host + ":" + str(@/database/port)}

service:
  name: "api"
  # Reference parent values with relative paths
  log_prefix: ${@name + ": "}
  # Reference root values with absolute paths
  connection: ${@/database/url}
```

### Self References

Reference values within the same object:

```yaml
user:
  first_name: "John"
  last_name: "Doe"
  # Reference sibling fields
  full_name: ${@first_name + " " + @last_name}
```

## Node References

Use `&` to reference and duplicate configuration nodes:

```yaml
__dracon__: # Special key that won't be included in the final configuration, super convenient for this type of thing
  template: &template_alias # create an alias for the node
    created_at: ${datetime.now()}
    version: ${VERSION}

# Create multiple objects from template
objects: ${[&template for _ in range(3)]}
```

> [!INFO] What's the difference between `&` and `@`?
>
> - `&` creates a reference to a node, which can be duplicated or reused.
> - `@` references a value in the final, constructed configuration. (great for lazy evaluation)

## Context and Variables

### Environment Variables

Access environment variables:

```yaml
database:
  host: ${env.get('DB_HOST', 'localhost')}
  password: ${env.get('DB_PASSWORD', '')}
```

### Custom Context

You can provide custom variables and functions when loading the configuration:

```python
loader = DraconLoader(
    enable_interpolation=True,
    context={
        'VERSION': '1.0.0',
        'ENVIRONMENT': 'production',
        'compute_value': lambda x: x * 2
    }
)
```

Then use them in your YAML:

```yaml
app:
  version: ${VERSION}
  env: ${ENVIRONMENT}
  doubled: ${compute_value(21)}
```

## Type Interpolation

Interpolate both values and types:

```yaml
# Interpolate the type tag
value: !${type_name} ${value}

# Example
number: !${'int'} ${2.1 + 3.1}  # Results in integer 5
```
