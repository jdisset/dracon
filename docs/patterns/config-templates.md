# Pattern: Config Templates

## The problem

You have the same config structure repeated N times with small variations. Three services that differ by name and port. Five database connections that share pooling settings. Copy-pasting means N points of maintenance, and every time you change the shared structure you have to update all N copies.

Dracon gives you several ways to define a template once and stamp it out with variations. Which one to use depends on where the template lives and how many times you call it.

## 1. Same-file templates with anchors

The simplest approach. Use a `__dracon__` key (excluded from output), a YAML anchor, and `!set_default`/`!require` for parameters.

```yaml
# services.yaml

__dracon__: &service
  !require name: "service name"
  !require port: "port number"
  !set_default replicas: 1
  !set_default protocol: http
  image: myapp/${name}:latest
  port: ${port}
  deploy:
    replicas: ${replicas}
  health_check: "${protocol}://localhost:${port}/health"

services:
  auth:
    !define name: auth
    !define port: 8001
    !define replicas: 3
    <<: *service

  api:
    !define name: api
    !define port: 8002
    <<: *service

  worker:
    !define name: worker
    !define port: 8003
    !define replicas: 5
    !define protocol: https
    <<: *service
```

Result:

```yaml
services:
  auth:
    image: myapp/auth:latest
    port: 8001
    deploy:
      replicas: 3
    health_check: http://localhost:8001/health
  api:
    image: myapp/api:latest
    port: 8002
    deploy:
      replicas: 1
    health_check: http://localhost:8002/health
  worker:
    image: myapp/worker:latest
    port: 8003
    deploy:
      replicas: 5
    health_check: https://localhost:8003/health
```

How it works:

- `__dracon__` keys are stripped from the final output. They exist only to hold anchors and other template machinery.
- `*service` creates a copy of the anchor. Each instantiation gets its own copy, so there's no cross-talk.
- `!require` declares mandatory parameters. If you forget `name` or `port`, composition fails with a clear error.
- `!set_default` provides fallback values. `!define` in the caller wins because `!set_default` only sets a variable when nobody else has. That's the key: `!define` is hard, `!set_default` is soft.
- The `<<:` merge splices the template content into the mapping where it appears.

## 2. Cross-file templates with !include

Same idea, but the template lives in its own file. Better when multiple config files need the same template, or when the template is large enough to warrant its own file.

The template file:

```yaml
# templates/service.yaml

!require name: "service name"
!require port: "port number"
!set_default replicas: 1
!set_default protocol: http

image: myapp/${name}:latest
port: ${port}
deploy:
  replicas: ${replicas}
health_check: "${protocol}://localhost:${port}/health"
```

The config that uses it:

```yaml
# services.yaml

services:
  auth:
    !define name: auth
    !define port: 8001
    !define replicas: 3
    <<: !include file:$DIR/templates/service.yaml

  api:
    !define name: api
    !define port: 8002
    <<: !include file:$DIR/templates/service.yaml
```

Each `!include` creates a fresh copy. No anchor sharing issues, and the template is reusable across files. `$DIR` resolves to the directory of the file containing the `!include`, so relative paths work regardless of where you run dracon from.

## 3. !fn as parameterized templates

When you're calling the same template many times, `!fn` is cleaner than `!define` + merge. It wraps the template into a callable.

```yaml
# services.yaml

!define make_service: !fn file:templates/service.yaml

services:
  auth: !make_service { name: auth, port: 8001, replicas: 3 }
  api: !make_service { name: api, port: 8002 }
  worker: !make_service
    name: worker
    port: 8003
    replicas: 5
    protocol: https
```

Or inline, if the template is short:

```yaml
!define make_service: !fn
  !require name: "service name"
  !require port: "port number"
  !set_default replicas: 1
  image: myapp/${name}:latest
  port: ${port}
  replicas: ${replicas}

services:
  auth: !make_service { name: auth, port: 8001, replicas: 3 }
  api: !make_service { name: api, port: 8002 }
```

Advantages over the anchor approach:

- Calling syntax is more compact. No `!define` lines + `<<:` merge per instance.
- Works from expressions: `${make_service(name='auth', port=8001)}`.
- Composes with `!each` for generating many instances from a list.
- Each call gets a fresh, isolated scope. No variable leaking between calls.

## 4. Vocabulary files

When templates stop being one-off helpers and start becoming a real public surface, you are in vocabulary territory.

The basic version is still:

```yaml
<<(<): !include pkg:mypackage:vocabulary.yaml
```

That propagates `!define` and `!set_default` values from the included file into the parent scope, so exported callables can be used as tags in the importing file.

The more interesting version is when vocabularies build on earlier vocabularies, and imported templates use other imported templates internally. That is now a separate pattern because it deserves its own treatment:

- [Layered Vocabularies](layered-vocabularies.md)

## When to use what

| Pattern | Best for |
|---------|----------|
| Anchors + `__dracon__` | Same-file templates, simple cases, few instantiations |
| `!include` + merge | Cross-file, one-shot includes, large templates |
| `!fn` | Reusable, parameterized, multiple calls, expression-friendly |
| Vocabulary + `(<)` | Package-level shared templates and layered config DSLs |

They're not mutually exclusive. A vocabulary file might define `!fn` templates internally. An `!fn` template might use `!include` in its body. Pick the one that fits the scale and reuse pattern of your situation.

### A note on anchor copies

YAML anchors produce shallow references by default, but Dracon deep-copies anchor content when it encounters `*ref` in a merge. This means each `<<: *service` gets independent data. You don't need to worry about mutations in one instance affecting another.

### A note on !require error messages

The string after `!require` is a hint shown in the error. Make it useful:

```yaml
# good
!require notify_email: "alert recipient (e.g. ops@example.com)"

# not helpful
!require notify_email: "required"
```
