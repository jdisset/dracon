# Instruction Tags

Dracon provides special YAML tags that add programming-like capabilities to your configuration files.

## Variable Definition

### `!define` - Define Variables

Define variables for use throughout the configuration:

```yaml
# Simple variable definition
!define api_version: v2

# Expression-based definition
!define max_workers: ${os.cpu_count() * 2}

# Dictionary definition
!define database_config:
  host: localhost
  port: 5432
  ssl: true

# Use defined variables
api_endpoint: https://api.example.com/${api_version}
workers: ${max_workers}
database: ${database_config}
```

### `!set_default` - Conditional Definition

Set variables only if they don't already exist:

```yaml
# Set default only if not already defined
!set_default environment: development
!set_default log_level: INFO

# Later definitions won't override
!set_default environment: production  # Ignored if already set

app_config:
  env: ${environment}     # Uses first definition
  logging: ${log_level}   # Uses default
```

## Conditional Logic

### `!if` - Conditional Inclusion

Include content based on conditions:

```yaml
# Simple conditional
database: !if ${getenv('ENVIRONMENT') == 'prod'}
  then:
    host: prod-db.example.com
    ssl: true
  else:
    host: localhost
    ssl: false

# Without else clause
debug_settings: !if ${getenv('DEBUG', 'false') == 'true'}
  then:
    log_level: DEBUG
    verbose: true

# Complex conditions
cache_config: !if ${int(getenv('MEMORY_GB', '4')) >= 8}
  then:
    type: redis
    size: 2GB
  else:
    type: memory
    size: 512MB
```

### Nested Conditionals

```yaml
deployment: !if ${getenv('ENVIRONMENT') == 'prod'}
  then: !if ${getenv('REGION') == 'us-east-1'}
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

Iterate over sequences and mappings:

```yaml
# Loop over list
!define environments: [dev, staging, prod]

!each(env) ${environments}:
  ${env}_config:
    database_url: postgres://db.${env}.local/myapp
    redis_url: redis://cache.${env}.local

# Loop over mapping
!define services:
  auth: 8001
  api: 8002
  web: 8080

!each(service, port) ${services}:
  ${service}_service:
    name: ${service}
    port: ${port}
    url: http://localhost:${port}
```

### Advanced Loop Patterns

```yaml
# Loop with complex content
!define replicas: 3

!each(i) ${range(replicas)}:
  worker_${i}:
    name: worker-${i}
    cpu: ${0.5 + i * 0.1}
    memory: ${512 + i * 256}MB
    env:
      WORKER_ID: ${i}
      WORKER_TYPE: standard

# Conditional within loop
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

  # Dynamic items spliced directly into the sequence
  - !each(svc) ${services}:
      - name: deploy_${svc}
        command: kubectl apply -f ${svc}.yaml

  - name: verify
    command: healthcheck

  # Another dynamic section
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

## Construction Control

### `!noconstruct` - Prevent Construction

Prevent automatic Pydantic model construction:

```yaml
# Raw data without model construction
raw_config: !noconstruct
  database:
    host: localhost
    port: 5432
  
# Later construct manually if needed
app_config: !DatabaseConfig ${raw_config.database}
```

## Deferred Execution

### `!deferred` - Deferred Construction

Delay construction until runtime context is available:

```yaml
# Simple deferred
output_path: !deferred /data/${runtime_id}/output

# Deferred with context clearing
clean_path: !deferred::clear_ctx=old_context /new/${new_runtime_var}

# Deferred with tag
model_config: !deferred:MyModel
  setting1: ${runtime_value}
  setting2: computed
```

## Advanced Instruction Combinations

### Instructions with Includes

```yaml
# Conditional includes
config: !if ${getenv('USE_LOCAL_CONFIG', 'false') == 'true'}
  then: !include file:local.yaml
  else: !include file:default.yaml

# Loop with includes
!define config_files: [database, cache, logging]

!each(config_name) ${config_files}:
  ${config_name}: !include file:config/${config_name}.yaml
```

### Instructions with Variables

```yaml
!define base_port: 8000
!define services: [auth, api, worker]

!each(service, index) ${enumerate(services)}:
  !define service_port: ${base_port + index}
  
  ${service}_config:
    name: ${service}
    port: ${service_port}
    health_check: http://localhost:${service_port}/health
```

### Nested Instructions

```yaml
!define deployment_type: ${getenv('DEPLOYMENT', 'standard')}

app_config: !if ${deployment_type == 'microservices'}
  then:
    !each(service) ${services}:
      ${service}: !include file:services/${service}.yaml
  else:
    monolith: !include file:monolith.yaml
```

## Error Handling

### Graceful Failures

```yaml
# Optional variable definition
!if ${hasattr(os, 'getenv')}:
  then:
    !define api_key: ${getenv('API_KEY', '')}
  else:
    !define api_key: ''

# Conditional execution with validation
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

### Environment-based Configuration

```yaml
!define environment: ${getenv('ENVIRONMENT', 'dev')}

database: !if ${environment == 'prod'}
  then: !include file:config/prod-db.yaml
  else: !include file:config/dev-db.yaml

features: !if ${environment in ['staging', 'prod']}
  then:
    - feature_flags
    - monitoring
    - alerts
  else:
    - debug_mode
    - hot_reload
```

### Service Discovery

```yaml
!define service_discovery: ${getenv('SERVICE_DISCOVERY', 'static')}

services: !if ${service_discovery == 'consul'}
  then: ${discover_services_from_consul()}
  else:
    !each(service, port) ${static_services}:
      ${service}: http://localhost:${port}
```

### Feature Flags

```yaml
!define enabled_features: ${getenv('FEATURES', '').split(',')}

!each(feature) ${enabled_features}:
  !if ${feature.strip() != ''}:
    then:
      ${feature}_config: !include file:features/${feature}.yaml
```