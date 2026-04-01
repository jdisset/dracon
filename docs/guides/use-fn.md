# YAML Functions with `!fn`

`!fn` turns a YAML template into a callable function. Define it once, call it anywhere -- from YAML tags or `${...}` expressions.

```yaml
!define service: !fn file:templates/service.yaml

services:
  auth: !service { name: auth, port: 8001 }
  api: !service { name: api, port: 8002 }

# or from expressions
all: ${[service(name=n, port=p) for n, p in svc_map.items()]}
```

## Defining a callable

`!fn` has three forms, from full templates to expression lambdas.

### From a file

```yaml
!define make_endpoint: !fn file:templates/endpoint.yaml
```

Where `endpoint.yaml` declares its parameters with `!require` and `!set_default`:

```yaml
# templates/endpoint.yaml
!require name: "service name"
!set_default port: 8080
url: https://${name}.example.com:${port}
health: https://${name}.example.com:${port}/health
```

Any loader works: `file:`, `pkg:`, etc.

### Inline mapping

```yaml
!define make_endpoint: !fn
  !require name: "service name"
  !set_default port: 8080
  url: https://${name}.example.com:${port}
  health: https://${name}.example.com:${port}/health
```

Same result, no extra file. Good for small templates used in a single config. Returns the mapping after instruction stripping.

### Inline scalar (expression lambda)

For simple transforms, `!fn` can take a single expression:

```yaml
!define double: !fn ${x * 2}
!define greet: !fn ${"Hello " + name}
```

These are expression lambdas -- no `!require`/`!set_default`, parameters come implicitly from kwargs:

```yaml
result: ${double(x=21)}          # => 42
msg: ${greet(name="world")}      # => "Hello world"
squares: ${[sq(x=i) for i in range(5)]}
```

### Scalar return with `!fn :`

Mapping templates normally return the whole mapping. If you need parameters (`!require`/`!set_default`) but want to return a single value, use `!fn :` inside the body as a return marker:

```yaml
!define double:
  !require x: "number to double"
  !fn : ${x * 2}

result: ${double(x=21)}  # => 42, not {__something__: 42}
```

The `!fn :` key marks "this is what the function computes." The rest of the body (`!require`, `!set_default`, `!define` helpers) is processed normally but only the `!fn :` value is returned.

This works with or without the outer `!fn` tag:

```yaml
# explicit outer !fn (redundant but valid)
!define double: !fn
  !require x: "number"
  !fn : ${x * 2}

# implicit -- !fn : inside the body is enough
!define double:
  !require x: "number"
  !fn : ${x * 2}
```

The return value can be anything -- a scalar, a mapping, a list:

```yaml
!define extract:
  !require data: "input list"
  !fn :
    count: ${len(data)}
    first: ${data[0]}

result: ${extract(data=[10, 20, 30])}
# => {count: 3, first: 10}
```

Use `!define` for intermediate values in the body:

```yaml
!define compute:
  !require x: "number"
  !define intermediate: ${x + 1}
  !fn : ${intermediate * 2}

result: ${compute(x=4)}  # => 10
```

## Calling from YAML (tag syntax)

Any callable in context becomes a valid YAML tag. This includes `!fn` templates, `!pipe` pipelines, and plain Python functions passed in context. The mapping under the tag provides keyword arguments:

```yaml
!define make_endpoint: !fn file:templates/endpoint.yaml

api: !make_endpoint
  name: api
  port: 443

internal: !make_endpoint { name: internal }
```

Result:

```yaml
api:
  url: https://api.example.com:443
  health: https://api.example.com:443/health
internal:
  url: https://internal.example.com:8080
  health: https://internal.example.com:8080/health
```

From the caller's perspective, `!make_endpoint { name: api }` looks and works exactly like a Python type tag (`!MyModel { field: value }`). The implementation -- YAML or Python -- is invisible.

### Python functions as tags

Any non-type callable in context works as a tag too, not just `!fn` templates:

```yaml
# function passed via loader context
result: !make_url { host: example.com, port: 443 }

# scalar argument (single positional arg)
!define upper: ${str.upper}
greeting: !upper "hello"   # => "HELLO"

# no arguments
result: !get_timestamp
```

With a mapping node, kwargs are unpacked. With a scalar node, the value is passed as a single positional argument. With an empty/null value, the function is called with no arguments.

## Calling from expressions

In `${...}`, the callable is a regular Python callable:

```yaml
api: ${make_endpoint(name='api', port=443)}
```

This enables composition patterns like:

```yaml
# list comprehension
endpoints: ${[make_endpoint(name=n, port=p) for n, p in services.items()]}

# chaining
upper_url: ${make_endpoint(name='api')['url'].upper()}

# conditional
ep: ${make_endpoint(name='prod') if is_prod else make_endpoint(name='staging')}
```

## Parameters

Templates declare parameters with `!require` (mandatory) and `!set_default` (optional):

```yaml
# templates/deploy_config.yaml
!require service: "service name"
!require region: "AWS region"
!set_default replicas: 3
!set_default memory: 512

service: ${service}
region: ${region}
replicas: ${replicas}
resources:
  memory: ${memory}Mi
```

- `!require` parameters are mandatory. Missing args produce a clear error with a hint and source location.
- `!set_default` parameters are optional with fallback values.
- Arguments that match `!require`/`!set_default` names are consumed and don't appear in the output.

## Isolation

Each call gets its own scope. Arguments don't leak into the caller:

```yaml
!define name: my_app
!define make_endpoint: !fn file:templates/endpoint.yaml

# "name" inside the template doesn't shadow the outer "name"
ep: ${make_endpoint(name='inner_service')}
app: ${name}  # still "my_app"
```

Multiple calls are fully independent:

```yaml
a: ${make_endpoint(name='alpha', port=1)}
b: ${make_endpoint(name='beta', port=2)}
# a and b have different values, no cross-contamination
```

## Templates can use any dracon feature

The body of a template is full dracon. Conditionals, loops, includes, type tags -- everything works:

```yaml
# templates/service_with_monitoring.yaml
!require name: "service name"
!set_default is_prod: false

url: https://${name}.example.com

!if ${is_prod}:
  monitoring: https://${name}.example.com/metrics
```

```yaml
!define service: !fn file:templates/service_with_monitoring.yaml

prod_api: ${service(name='api', is_prod=True)}
dev_api: ${service(name='api', is_prod=False)}
```

`prod_api` gets the `monitoring` key; `dev_api` doesn't.

## Recipes

### Service config factory

```yaml
!define deploy: !fn file:templates/deploy_config.yaml

services:
  api: !deploy { service: api, region: us-east-1, replicas: 5 }
  worker: !deploy { service: worker, region: us-east-1, memory: 1024 }
  cron: !deploy { service: cron, region: eu-west-1 }
```

### Map over a collection

```yaml
!define service_names: ${['auth', 'api', 'worker']}
!define make_endpoint: !fn file:templates/endpoint.yaml

endpoints: ${[make_endpoint(name=n) for n in service_names]}
```

Or with `!each`:

```yaml
!define services: ${['web', 'api', 'worker']}
!define make_endpoint: !fn
  !require name: "svc"
  url: https://${name}.example.com

endpoints:
  !each(svc) ${services}:
    ${svc}: ${make_endpoint(name=svc)}
```

### Nested composition

```yaml
!define load: !fn file:templates/loader.yaml
!define clean: !fn file:templates/cleaner.yaml

pipeline:
  raw: ${load(path=data_path)}
  cleaned: ${clean(data=load(path=data_path))}
```

### Typed object return

Templates that construct a Pydantic model return the real object:

```yaml
!define make_model: !fn
  !require val: "field value"
  !set_default model_name: default
  field: ${val}
  name: ${model_name}

result: !SimpleModel ${make_model(val=42)}
```

## Composing functions with `!pipe`

If you have several `!fn` templates that form a pipeline, `!pipe` chains them into a single callable:

```yaml
!define load: !fn file:templates/load.yaml
!define clean: !fn file:templates/clean.yaml
!define train: !fn file:templates/train.yaml
!define evaluate: !fn file:templates/evaluate.yaml

!define ml: !pipe [load, clean, train, evaluate]
```

Each stage's mapping output is kwarg-unpacked into the next stage. So if `load` returns `{data: ..., metadata: ...}`, `clean` receives those as named arguments.

Pre-fill kwargs per stage:

```yaml
!define ml: !pipe
  - load
  - clean: { strategy: aggressive }
  - train: { model_type: xgb }
  - evaluate
```

Pipeline kwargs (from the call site) flow through to all stages:

```yaml
# 'path' reaches load, 'epochs' reaches train
result: ${ml(path='/data/train.csv', epochs=200)}
```

Pipes compose with pipes:

```yaml
!define preprocess: !pipe [load, clean, normalize]
!define train_eval: !pipe [train, evaluate]
!define full: !pipe [preprocess, train_eval]
```

And since pipes are callables, they work in sweeps:

```yaml
!define fast: !pipe [load, downsample, train_quick]
!define full: !pipe [load, clean, augment, train_full, evaluate]

results: ${[p(path=data_path) for p in [fast, full]]}
```

## When to use what

| Pattern | Best for |
|---|---|
| `!fn` inline mapping | Reusable templates returning mappings, isolated scope |
| `!fn` with `!fn :` | Templates with params that return a single value |
| `!fn ${expr}` | Simple expression transforms (lambdas) |
| `!pipe` | Chaining callables into pipelines, sweep over methodologies |
| Python callable as tag | Applying Python functions directly in YAML |
| `!include` with merge | One-shot includes that merge into the parent scope |
| `__dracon__` + anchor | Same-file composition helpers that don't need parameterization |
