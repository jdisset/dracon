# Instruction Tags

Dracon provides special YAML tags that add programming-like capabilities to your configuration files.

!!! important
    All instructions (`!define`, `!if`, `!each`) must appear as **mapping key tags** — they tag the key, not the value.

## Variable Definition

### `!define` - Define Variables

Define variables for use throughout the configuration:

```yaml
# simple variable definition
!define api_version: v2

# expression-based definition
!define max_workers: ${int(getenv('NUM_CPUS', '4')) * 2}

# dictionary definition
!define database_config:
  host: localhost
  port: 5432
  ssl: true

# use defined variables
api_endpoint: https://api.example.com/${api_version}
workers: ${max_workers}
database: ${database_config}
```

### `!define` with Typed Objects (Lazy Construction)

When the value of a `!define` has a type tag (a Pydantic model or other Python class), construction is **lazy** -- it happens on first access, not when the `!define` is encountered. This means the object's interpolations are resolved later, when the full context is available.

```yaml
# construction of SimpleModel happens when ${model} is first accessed
!define model: !SimpleModel { field: 42 }

# works even though 'y' is defined AFTER 'obj'
!define obj: !MyModel
  value: ${y}
!define y: ${42}

result: ${obj.value}  # triggers construction, returns 42
```

This is the natural way to bind Python objects to variables. You can call methods, access attributes, chain objects:

```yaml
!define data: !DataLoader { path: ${data_path} }
!define cleaned: !DataCleaner { data: ${data}, strategy: outlier }
!define predictions: ${cleaned.predict()}
output: ${predictions}
```

!!! tip "Pipeline-style YAML"
    Each `!define` with a type tag is a pipeline stage. Dependencies are explicit through `${...}` references. If a variable is never referenced, the object is never constructed -- no wasted work.

Key behaviors:

- The result is the **real Python object**, not a proxy. `isinstance`, `type()`, attribute access, method calls all work normally.
- Construction happens **at most once** per variable (cached after first access).
- Forward references work: `!define x: !T { field: ${y} }` followed by `!define y: 42` is fine.
- Circular references are detected: `!define a: !T { ref: ${a} }` raises `CompositionError`.

This replaces the old `!noconstruct` + `construct()` pattern:

```yaml
# before (verbose, manual):
!noconstruct data: !DataLoader
  path: ${data_path}
!define result: ${construct(&/data).process()}

# after (just works):
!define data: !DataLoader { path: ${data_path} }
!define result: ${data.process()}
```

### `!define:type` - Typed Variable Definition

Force a specific type on the defined value. Useful when YAML's implicit type inference doesn't match what you want -- for example, defining `1` as a float or `42` as a string:

```yaml
!define:float learning_rate: 1   # float 1.0, not int 1
!define:int batch_size: 32.0     # int 32, not float
!define:str zipcode: 02134       # string "2134", not int
!define:bool verbose: 1          # True, not int 1
```

Supported types: `int`, `float`, `str`, `bool`, `list`, `dict`.

Works with expressions too:

```yaml
!define:float total: ${2 + 3}    # float 5.0
```

!!! note
    Plain `!define` already preserves YAML's natural type inference -- `1.2` is a float, `42` is an int, `true` is a bool. You only need `!define:type` when you want to **override** that inference.

The typed syntax also works with `!define?` and `!set_default`:

```yaml
!define?:float default_rate: 1   # soft define, float 1.0
!set_default:int retries: 3.0    # soft define, int 3
```

### `!set_default` / `!define?` - Conditional Definition

Set variables only if they don't already exist. `!define?` is an alias for `!set_default` -- use whichever reads better in context:

```yaml
# set default only if not already defined
!set_default environment: development
!define? log_level: INFO              # same as !set_default

# later definitions won't override
!set_default environment: production  # ignored if already set

app_config:
  env: ${environment}     # uses first definition
  logging: ${log_level}   # uses default
```

### `!require` - Mandatory Variable Declaration

Declare that a variable **must** be provided by an outer scope (parent file, cascade overlay, CLI `++var=value`, or `!define`). If nobody provides it by end of composition, a clear error is raised with the hint message.

```yaml
# base config expects overlays to fill in
!require environment: "set via ++environment or create a .myapp.yaml overlay"
!require api_key: "set API_KEY env var or provide in overlay"

endpoint: https://${environment}.api.example.com
auth:
  key: ${api_key}
```

If the requirement is not satisfied:

```
CompositionError: required variable 'environment' not provided
  hint: set via ++environment or create a .myapp.yaml overlay
  required by: base.yaml:2
```

The variable definition gradient:

- `!define` -- always set, overwrites previous values
- `!set_default` -- set if nobody else does (optional with fallback)
- `!require` -- must be provided by someone else (mandatory, no fallback)

### When Does Construction Happen?

With `!define`, the timing depends on what you're defining:

| Pattern | Resolves | Use case |
|---------|----------|----------|
| `!define x: 42` | Immediately (literal) | Constants, simple values |
| `!define x: ${expr}` | Composition time (expression) | Derived strings, comprehensions |
| `!define x: !Type { ... }` | On first `${x}` access (lazy) | Pipeline stages, Python objects |
| `!deferred` | Runtime (manual `.construct()`) | Objects needing live runtime state |

The lazy construction for typed objects is what makes `!define` work as a pipeline mechanism. The `!noconstruct` + `construct()` pattern that was previously needed for this is now unnecessary.

### Processing Order

Instructions are processed in this order: `!set_default` → `!define` → `!each` → `!if`. This means `!define` can override `!set_default`, and `!if`/`!each` can use variables defined by both. `!require` is checked after all instructions and includes are resolved.

## Conditional Logic

### `!if` - Conditional Inclusion

Include or exclude content based on conditions. The `!if` tag goes on the **key** (not the value):

```yaml
# then/else format — content is injected into the parent mapping
!if ${getenv('ENVIRONMENT') == 'prod'}:
  then:
    database_host: prod-db.example.com
    database_ssl: true
  else:
    database_host: localhost
    database_ssl: false

# without else clause
!if ${getenv('DEBUG', 'false') == 'true'}:
  then:
    log_level: DEBUG
    verbose: true

# shorthand format — include content directly if condition is true
!if ${getenv('ENABLE_CACHE', 'true') == 'true'}:
  cache_type: redis
  cache_size: 2GB
```

!!! note
    The `then`/`else` format checks for keys literally named `then` and `else` in the value mapping. If those keys are present, it uses them as branches. Otherwise, the entire value is included as-is when the condition is true (shorthand format).

### Nested Conditionals

```yaml
!if ${getenv('ENVIRONMENT') == 'prod'}:
  then:
    !if ${getenv('REGION') == 'us-east-1'}:
      then:
        cluster: prod-us-east
        replicas: 5
      else:
        cluster: prod-eu-west
        replicas: 3
  else:
    cluster: dev
    replicas: 1
```

## Loops and Iteration

### `!each(var)` - Loop over Collections

Iterate over sequences and mappings. Takes a **single** variable name:

```yaml
# loop over list
!define environments: [dev, staging, prod]

!each(env) ${environments}:
  ${env}_config:
    database_url: postgres://db.${env}.local/myapp
    redis_url: redis://cache.${env}.local

# loop over mapping keys
!define services:
  auth: 8001
  api: 8002
  web: 8080

# iterating a dict yields its keys
!each(service) ${services}:
  ${service}_url: http://localhost:${services[service]}

# to iterate over key-value pairs, use .items()
!each(item) ${services.items()}:
  ${item[0]}_service:
    name: ${item[0]}
    port: ${item[1]}
    url: http://localhost:${item[1]}
```

### Advanced Loop Patterns

```yaml
# loop with complex content
!define replicas: 3

!each(i) ${range(replicas)}:
  worker_${i}:
    name: worker-${i}
    cpu: ${0.5 + i * 0.1}
    memory: ${512 + i * 256}MB
    env:
      WORKER_ID: ${i}
      WORKER_TYPE: standard

# conditional within loop
!define features: [auth, api, cache, metrics]

!each(feature) ${features}:
  !if ${getenv(f'{feature.upper()}_ENABLED', 'true') == 'true'}:
    then:
      ${feature}_service:
        enabled: true
        config: !include file:config/${feature}.yaml
```

### Nested Loops

```yaml
!define environments: [dev, prod]
!define services: [api, worker, scheduler]

!each(env) ${environments}:
  ${env}:
    !each(service) ${services}:
      ${service}:
        image: myapp/${service}:${env}
        replicas: ${1 if env == 'dev' else 3}
```

### Inline Sequence Expansion (Auto-Splice)

When `!each` appears as an item inside a sequence and produces a sequence, the generated items are **spliced inline** into the parent sequence. This enables mixing static and dynamic items without explicit concatenation:

```yaml
!define services: [auth, api, worker]

deployment_steps:
  - name: initialize
    command: setup

  # dynamic items spliced directly into the sequence
  - !each(svc) ${services}:
      - name: deploy_${svc}
        command: kubectl apply -f ${svc}.yaml

  - name: verify
    command: healthcheck

  # another dynamic section
  - !each(svc) ${services}:
      - name: test_${svc}
        command: pytest tests/${svc}/

  - name: cleanup
    command: teardown
```

Result:
```yaml
deployment_steps:
  - {name: initialize, command: setup}
  - {name: deploy_auth, command: kubectl apply -f auth.yaml}
  - {name: deploy_api, command: kubectl apply -f api.yaml}
  - {name: deploy_worker, command: kubectl apply -f worker.yaml}
  - {name: verify, command: healthcheck}
  - {name: test_auth, command: pytest tests/auth/}
  - {name: test_api, command: pytest tests/api/}
  - {name: test_worker, command: pytest tests/worker/}
  - {name: cleanup, command: teardown}
```

This also works with nested `!each`:

```yaml
!define envs: [dev, prod]
!define regions: [us, eu]

deployments:
  - name: init
  - !each(env) ${envs}:
      !each(region) ${regions}:
        - name: deploy_${env}_${region}
  - name: finalize

# Result: [init, deploy_dev_us, deploy_dev_eu, deploy_prod_us, deploy_prod_eu, finalize]
```

## Validation

### `!assert` - Composition-Time Assertions

Validate invariants over the composed tree. The expression uses the same interpolation engine as `${...}`. Runs after all other instructions are resolved but before construction.

```yaml
!assert ${port > 0 and port < 65536}: "port out of range"
!assert ${engine in ('postgres', 'mysql', 'sqlite')}: "unknown db engine"
!assert ${not (environment == 'prod' and debug)}: "debug must be off in prod"
```

Assertions are removed from the final tree -- pure validation, zero runtime overhead. If an assertion fails:

```
CompositionError: assertion failed: debug must be off in prod
```

### Combining `!require` and `!assert`

```yaml
!require environment: "set via ++environment"
!require port: "provide a port number"

!assert ${port > 0 and port < 65536}: "port must be 1-65535"
!assert ${environment in ('dev', 'staging', 'prod')}: "invalid environment"

server:
  env: ${environment}
  port: ${port}
```

## Construction Control

### `!noconstruct` - Skip During Construction

!!! note "Mostly superseded by lazy `!define`"
    The common pattern of `!noconstruct` + `construct(&/name)` to build Python objects from YAML is no longer needed. Use `!define name: !Type { ... }` instead -- it handles lazy construction automatically. See [lazy construction above](#define-with-typed-objects-lazy-construction).

    `!noconstruct` is still useful for its original purpose: excluding nodes from construction entirely (template anchors, metadata, tooling hints).

Tag a key or value with `!noconstruct` to skip it during Pydantic model construction. The node is kept in the YAML tree during composition but ignored when building Python objects.

```yaml
# this key-value pair will be excluded from the constructed object
!noconstruct metadata:
  internal_note: this is for tooling only

# regular keys are constructed normally
app_name: my-service
port: 8080
```

## Deferred Execution

### `!deferred` - Deferred Construction

Delay construction until runtime context is available:

```yaml
# simple deferred
output_path: !deferred /data/${runtime_id}/output

# deferred with context clearing
clean_path: !deferred::clear_ctx=old_context /new/${new_runtime_var}

# deferred with tag
model_config: !deferred:MyModel
  setting1: ${runtime_value}
  setting2: computed
```

## Advanced Instruction Combinations

### Instructions with Includes

```yaml
# conditional includes
!if ${getenv('USE_LOCAL_CONFIG', 'false') == 'true'}:
  then:
    config: !include file:local.yaml
  else:
    config: !include file:default.yaml

# loop with includes
!define config_files: [database, cache, logging]

!each(config_name) ${config_files}:
  ${config_name}: !include file:config/${config_name}.yaml
```

### Instructions with Variables

```yaml
!define base_port: 8000
!define services: [auth, api, worker]

!each(item) ${list(enumerate(services))}:
  !define service_port: ${base_port + item[0]}

  ${item[1]}_config:
    name: ${item[1]}
    port: ${service_port}
    health_check: http://localhost:${service_port}/health
```

### Nested Instructions

```yaml
!define deployment_type: ${getenv('DEPLOYMENT', 'standard')}

!if ${deployment_type == 'microservices'}:
  then:
    !each(service) ${services}:
      ${service}: !include file:services/${service}.yaml
  else:
    monolith: !include file:monolith.yaml
```

## Error Handling

### Graceful Defaults

```yaml
# optional variable definition
!set_default api_key: ${getenv('API_KEY', '')}

# conditional execution with validation
!if ${getenv('CONFIG_FILE', '') != ''}:
  then:
    external_config: !include file:${getenv('CONFIG_FILE')}
```

## Performance Notes

- Instructions are processed during composition, not at runtime
- Complex loops and conditionals can slow loading
- Variables are resolved once and cached
- Deferred instructions delay computation until needed

## Common Patterns

### Config Templates

Define a reusable, parameterized config fragment using `__dracon__`, YAML anchors, and merge. Use `!require` for mandatory parameters and `!set_default` for optional ones:

```yaml
__dracon__: &service
  !require name: "service name"
  !require port: "port number"
  !set_default replicas: 1
  image: myapp/${name}:latest
  port: ${port}
  replicas: ${replicas}

services:
  auth:
    !define name: auth
    !define port: 8001
    !define replicas: 3
    <<: *service

  api:
    !define name: api
    !define port: 8002
    <<: *service     # replicas defaults to 1
```

`!set_default` values are "soft" -- they yield to the caller's `!define` values across merge boundaries. For file-based templates, use `!include` instead of anchors:

```yaml
auth:
  !define name: auth
  !define port: 8001
  <<: !include file:templates/service.yaml
```

See the [templates guide](../guides/use-templates.md) for more patterns.

### Environment-based Configuration

```yaml
!define environment: ${getenv('ENVIRONMENT', 'dev')}

!if ${environment == 'prod'}:
  then:
    database: !include file:config/prod-db.yaml
  else:
    database: !include file:config/dev-db.yaml

!if ${environment in ['staging', 'prod']}:
  then:
    features:
      - feature_flags
      - monitoring
      - alerts
  else:
    features:
      - debug_mode
      - hot_reload
```

### Feature Flags

```yaml
!define enabled_features: ${getenv('FEATURES', '').split(',')}

!each(feature) ${enabled_features}:
  !if ${feature.strip() != ''}:
    then:
      ${feature}_config: !include file:features/${feature}.yaml
```

## Custom Instructions

Dracon's instruction system is extensible. You can register your own instruction tags that run during composition.

### `register_instruction()`

Register a custom instruction class:

```python
from dracon import Instruction, register_instruction

class MyTag(Instruction):
    """Custom instruction that runs during composition."""

    @staticmethod
    def match(value: str) -> bool:
        return value == '!my_tag'

    @staticmethod
    def process(key_node, value_node, **kwargs):
        # manipulate the node tree during composition
        ...

register_instruction('!my_tag', MyTag)
```

The `!` prefix is optional when calling `register_instruction` -- it's added automatically if missing. The class must subclass `Instruction` and implement `match()` and `process()`.

Set `deferred = True` on your class to run the instruction after all other instructions (like `!assert` does).
