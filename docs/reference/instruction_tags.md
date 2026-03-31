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

### `!set_default` - Conditional Definition

Set variables only if they don't already exist:

```yaml
# set default only if not already defined
!set_default environment: development
!set_default log_level: INFO

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
