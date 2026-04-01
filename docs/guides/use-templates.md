# Reusable Config Templates

Dracon lets you define parameterized config templates using existing primitives -- no special syntax needed. A template is just a config fragment that declares its parameters with `!require` and `!set_default`, and callers instantiate it via YAML anchors + merge.

## The pattern

Define a template under `__dracon__` (excluded from the final config) with a YAML anchor:

```yaml
__dracon__: &service
  !require name: "service name"
  !require port: "port number"
  !set_default replicas: 1
  !set_default protocol: http
  image: myapp/${name}:latest
  port: ${port}
  replicas: ${replicas}
  protocol: ${protocol}
```

Instantiate it by merging the anchor into a scope that `!define`s the parameters:

```yaml
services:
  auth:
    !define name: auth
    !define port: 8001
    !define replicas: 3
    <<: *service

  api:
    !define name: api
    !define port: 8002
    !define protocol: https
    <<: *service
```

Result:

```yaml
services:
  auth:
    image: myapp/auth:latest
    port: 8001
    replicas: 3          # overridden
    protocol: http       # default
  api:
    image: myapp/api:latest
    port: 8002
    replicas: 1          # default
    protocol: https      # overridden
```

## How it works

Three existing primitives compose to form this pattern:

| Primitive | Role in template |
|---|---|
| `!require var: "hint"` | Mandatory parameter -- error if caller doesn't provide it |
| `!set_default var: value` | Optional parameter with fallback |
| `!define var: value` | Caller passes an argument |

`!set_default` values are "soft" -- they yield to `!define` values from the caller's scope, even though the template's instructions run before the merge happens. This is handled automatically.

## File-based templates

For templates shared across projects, use a separate file instead of `__dracon__`:

```yaml
# templates/service.yaml
!require name: "service name"
!require port: "port number"
!set_default replicas: 1

image: myapp/${name}:latest
port: ${port}
replicas: ${replicas}
```

```yaml
# main.yaml
services:
  auth:
    !define name: auth
    !define port: 8001
    !define replicas: 3
    <<: !include file:templates/service.yaml

  api:
    !define name: api
    !define port: 8002
    <<: !include file:templates/service.yaml
```

Each `!include` creates a fresh copy of the template, so per-instance parameters work naturally.

## Templates with conditionals and loops

Templates can use all of Dracon's instructions internally:

```yaml
__dracon__: &deployment
  !require name: "deployment name"
  !require env: "target environment"
  !set_default replicas: ${3 if env == 'prod' else 1}

  name: ${name}
  replicas: ${replicas}
  !if ${env == 'prod'}:
    resources:
      cpu: 2
      memory: 4Gi
```

## Templates with nested content

The caller can add keys alongside the merged template content:

```yaml
auth:
  !define name: auth
  !define port: 8001
  <<: *service
  # caller-specific additions
  oauth_provider: google
  session_ttl: 3600
```

Caller keys take priority over template keys (default merge behavior: existing wins).

## Templates with `!assert`

Use `!assert` inside templates to validate parameter values:

```yaml
__dracon__: &service
  !require name: "service name"
  !require port: "port number"
  !assert ${port > 0 and port < 65536}: "port must be 1-65535"
  !assert ${len(name) > 0}: "name cannot be empty"
  image: myapp/${name}:latest
  port: ${port}
```

## Callable templates with `!fn`

If you're calling the same template multiple times or need expression-level composability, `!fn` wraps the template into a callable with isolated scope:

```yaml
!define service: !fn file:templates/service.yaml

services:
  auth: !service { name: auth, port: 8001, replicas: 3 }
  api: !service { name: api, port: 8002 }
```

Or from expressions:

```yaml
all_services: ${[service(name=n, port=p) for n, p in svc_map.items()]}
```

`!fn` eliminates the `!define` + merge boilerplate, prevents argument leakage into the caller's scope, and enables patterns like list comprehensions and chaining that aren't possible with `!include`. See the [YAML Functions guide](use-fn.md) for details.

## When to use what

| Approach | Best for |
|---|---|
| `__dracon__` + anchor | Small composition helpers (< 10 lines), same-file reuse |
| `!define` + `!include` | One-shot includes that merge into the parent scope |
| `!fn` (callable) | Templates called more than once, expression composability, isolated scope |
| Separate file + `!include` | Shared across projects, large templates, template libraries |

All approaches support `!require`, `!set_default`, `!assert`, and all other instructions.
