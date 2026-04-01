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

Use `!fn` with a file reference or an inline mapping.

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

### Inline

```yaml
!define make_endpoint: !fn
  !require name: "service name"
  !set_default port: 8080
  url: https://${name}.example.com:${port}
  health: https://${name}.example.com:${port}/health
```

Same result, no extra file. Good for small templates used in a single config.

## Calling from YAML (tag syntax)

When you define a callable named `make_endpoint`, the tag `!make_endpoint` becomes available. The mapping under it provides keyword arguments:

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

## When to use what

| Pattern | Best for |
|---|---|
| `!fn` (callable) | Reusable templates, expression composability, isolated scope |
| `!include` with merge | One-shot includes that merge into the parent scope |
| `__dracon__` + anchor | Same-file composition helpers that don't need parameterization |
