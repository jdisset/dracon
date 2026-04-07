# YAML Functions

You have repeated config patterns. You want to parameterize them without copy-pasting, and compose them into pipelines.

## When to use what

Before reaching for `!fn`, check if a simpler tool fits:

| Pattern | Use case | Returns |
|---------|----------|---------|
| YAML anchors (`&`/`*`) | Reuse identical subtrees within one file | Exact copy, no parameters |
| `!include` | Pull in a file or subtree | Static content, no parameters |
| `!fn` (inline) | Parameterized template, called from YAML | Mapping or scalar |
| `!fn file:path` | Same, but template lives in a separate file | Mapping or scalar |
| `!fn:dotted.path` | Wrap a Python function with stored kwargs | Whatever the function returns |
| `!pipe` | Chain multiple callables, output threading | Final stage's return value |

If you just need the same block twice without changes, anchors work. If you need parameters, use `!fn`.

## Defining callables: three forms

### From a file

```yaml
!define make_endpoint: !fn file:$DIR/templates/endpoint.yaml
```

The file at `templates/endpoint.yaml` becomes the function body. It can use `!require` and `!set_default` for parameters, just like an inline body. `$DIR` in the file resolves to the template file's directory, not the caller's.

### Inline mapping

```yaml
!define make_endpoint: !fn
  !require name: "service name"
  !set_default port: 8080
  url: "https://${name}.example.com:${port}"
  health: "https://${name}.example.com:${port}/health"
```

The body is a mapping with parameter declarations and the template content mixed together. `!require` and `!set_default` lines are stripped from the output; they only define the interface.

### Expression lambda

```yaml
!define double: !fn ${x * 2}
!define greet: !fn "Hello, ${name}!"
```

For when the whole function is a single expression. The result is whatever the expression evaluates to.

## Scalar return with !fn key

Sometimes you want a function that takes parameters but returns a single value, not a mapping. Use `!fn` as a key inside the body to mark the return value:

```yaml
!define connection_string: !fn
  !require host: "database host"
  !set_default port: 5432
  !set_default db: "myapp"
  !fn : "postgresql://${host}:${port}/${db}"
```

```yaml
db_url: !connection_string { host: db.prod.internal }
# result: "postgresql://db.prod.internal:5432/myapp"
```

Without the `!fn :` return marker, calling this would produce a mapping. The marker says "return this value instead."

You can also use `!fn :` without an outer `!fn` tag on the `!define`. If Dracon sees a `!fn` key inside a `!define` body, it implicitly treats the whole thing as a callable:

```yaml
!define connection_string:
  !require host: "database host"
  !fn : "postgresql://${host}:5432/myapp"
```

Same result, slightly less nesting.

## Calling from YAML (tag syntax)

Any callable in scope can be used as a YAML tag. The tag name is the variable name with a `!` prefix:

```yaml
!define make_endpoint: !fn
  !require name: "service name"
  !set_default port: 8080
  url: "https://${name}.example.com:${port}"

endpoints:
  api: !make_endpoint { name: api, port: 443 }
  admin: !make_endpoint { name: admin }
  docs: !make_endpoint
    name: docs
    port: 9090
```

Both flow syntax (`{ key: value }`) and block syntax work. The result is the template body with arguments substituted in:

```yaml
endpoints:
  api:
    url: https://api.example.com:443
  admin:
    url: https://admin.example.com:8080
  docs:
    url: https://docs.example.com:9090
```

This works for any callable in context, not just `!fn` templates. Python functions passed via `context` or `context_types` work too.

## Calling from expressions

Inside `${...}`, call functions with Python syntax:

```yaml
fast_api: ${make_endpoint(name='api', port=443)}
```

This is useful for list comprehensions, conditionals, and chaining:

```yaml
!define names:
  - api
  - admin
  - docs

all_urls: ${[make_endpoint(name=n)['url'] for n in names]}
primary: ${make_endpoint(name='api') if production else make_endpoint(name='dev-api')}
```

## Parameters: !require and !set_default

- `!require name: "hint"` -- mandatory. If the caller doesn't provide it, composition fails with an error that includes the hint text.
- `!set_default port: 8080` -- optional. Uses 8080 if the caller doesn't override it.

Both are stripped from the output. They only define the callable's interface.

```yaml
!define make_service: !fn
  !require name: "service identifier"
  !require region: "deployment region"
  !set_default replicas: 1
  !set_default health_path: "/health"

  endpoint: "https://${name}.${region}.example.com"
  health: "https://${name}.${region}.example.com${health_path}"
  replicas: ${replicas}
```

## Isolation

Each call gets a fresh scope. Variables set inside one call don't leak into the next:

```yaml
!define counter: !fn
  !require x: "input"
  !define doubled: ${x * 2}
  result: ${doubled}

a: !counter { x: 3 }   # result: 6
b: !counter { x: 5 }   # result: 10
# 'doubled' from the first call doesn't affect the second
```

The template node is deep-copied before each invocation, so there's no shared mutable state between calls.

## !fn:path -- partial application of Python functions

`!fn:path` wraps a Python function (identified by its dotted import path) with optional pre-filled keyword arguments. The result is a `DraconPartial`: a callable that's serializable via both pickle and YAML.

```yaml
!define sqrt: !fn:math.sqrt
!define log10: !fn:math.log { base: 10 }
!define my_transform: !fn:myproject.transforms.normalize { strategy: "minmax" }
```

Call them from expressions:

```yaml
root: ${sqrt(16)}           # 4.0
log_val: ${log10(x=1000)}   # 3.0
normed: ${my_transform(data=raw_values)}
```

Or use as a tag when no args are pre-filled:

```yaml
!define greet: !fn:myproject.utils.greet { greeting: hey }
message: ${greet(name='world')}  # "hey world"
```

### Resolution order

When Dracon encounters `!fn:some.name`, it looks up the function in this order:

1. The current loader context (variables passed via `context`, `context_types`, or `!define`)
2. Dotted import from Python's module system

This means you can override an importable function with a context variable of the same name.

### Serialization

`DraconPartial` is pickle-safe and round-trips through YAML. When dumped to YAML, it produces `!fn:dotted.path { kwargs }`. When pickled, it stores the path and kwargs, then re-imports the function on unpickle.

Context-only names (no dots) can't be pickled since there's no import path to reconstruct from.

### !fn vs !fn:path

| | `!fn` (template) | `!fn:path` (partial) |
|---|---|---|
| Wraps | YAML template | Python function |
| Parameters | `!require` / `!set_default` | Function signature |
| Serializable | YAML only | YAML + pickle |
| Isolation | Full (deepcopy per call) | Standard Python |
| Use case | Config generation | Connecting Python code to YAML |

## !pipe -- function composition

`!pipe` chains multiple callables into a pipeline. The output of each stage feeds into the next.

```yaml
!define process: !pipe
  - load_data
  - clean
  - train
```

### Output threading

How the output of one stage reaches the next depends on its type:

- **Mapping output**: kwarg-unpacked into the next stage. If `clean` returns `{'data': [...], 'stats': {...}}`, then `train` receives `data=[...]` and `stats={...}` as keyword arguments.
- **Typed (non-mapping) output**: passed as a single positional value to the next stage's lone unfilled `!require` parameter. If `clean` returns a list, it fills whatever `!require` parameter `train` has that isn't already satisfied.

### Pre-filling kwargs per stage

You can give per-stage keyword arguments using mapping syntax:

```yaml
!define process: !pipe
  - load_data
  - clean: { strategy: aggressive, min_length: 10 }
  - train: { epochs: 50 }
```

The pre-filled kwargs are merged with the piped output. Pre-filled values take priority over values from the previous stage.

### Mixing !fn templates and !fn:path

Pipe stages can be any callable: `!fn` templates, `!fn:path` partials, context variables, or expression references.

```yaml
!define normalize: !fn
  !require data: "input data"
  !set_default method: "zscore"
  result: ${do_normalize(data, method)}

!define pipeline: !pipe
  - normalize
  - !fn:myproject.models.fit { max_iter: 100 }
```

### Pipes compose with pipes

If a pipe stage is itself a `DraconPipe`, its stages are flattened into the parent. No nesting overhead:

```yaml
!define preprocess: !pipe
  - load
  - clean

!define full: !pipe
  - preprocess    # flattened: load, clean
  - train
```

`full` has three stages, not two.

### Calling a pipe

Pipes are called like any other callable:

```yaml
result: ${process(input_path='data.csv')}
```

The initial kwargs go to every stage (each stage picks what it needs). The first stage also receives no piped value; subsequent stages get both the piped output and the initial kwargs.

## Recipes

### Service config factory

Generate config blocks for multiple services from a template:

```yaml
!define make_service: !fn
  !require name: "service name"
  !set_default port: 8080
  !set_default replicas: 1
  url: "https://${name}.example.com:${port}"
  health_check: "https://${name}.example.com:${port}/health"
  replicas: ${replicas}

services:
  api: !make_service { name: api, port: 443, replicas: 3 }
  auth: !make_service { name: auth, port: 443, replicas: 2 }
  docs: !make_service { name: docs }
```

### Map over a collection

With `!each`:

```yaml
!define make_check: !fn
  !require site: "domain"
  url: "https://${site}"
  interval: 30

!define sites:
  - example.com
  - api.example.com

checks:
  !each(site) ${sites}:
    ${site}: !make_check { site: "${site}" }
```

With an expression:

```yaml
checks: ${[make_check(site=s) for s in sites]}
```

### Nested composition

Functions can call other functions:

```yaml
!define make_endpoint: !fn
  !require name: "name"
  !set_default port: 8080
  url: "https://${name}.example.com:${port}"

!define make_service: !fn
  !require name: "service name"
  !set_default port: 8080
  !set_default replicas: 1
  endpoint: ${make_endpoint(name=name, port=port)}
  replicas: ${replicas}
  monitoring:
    url: ${make_endpoint(name=name, port=port)['url']}/metrics
```

Each nested call is fully isolated. The inner `make_endpoint` calls don't share state with each other or with the outer `make_service`.
