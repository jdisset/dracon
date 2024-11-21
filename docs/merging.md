# Advanced Merging

Dracon provides a flexible merging system that allows you to combine configurations in sophisticated ways using merge operators.

## Basic Merge Syntax

The merge operator follows this pattern:

```yaml
<<{dict_options}[list_options]@keypath: value
```

- `{dict_options}`: How to merge dictionaries
  - `~`: Overwrite same-key values (default)
  - `+`: Recursively append values (i.e., deep merge)
    - `number`: Limit recursion depth
  - `<`: Priority to existing values (default)
  - `>`: Priority to new values

- `[list_options]`: How to merge lists
  - `~`: Overwrite lists entirely (default)
  - `+`: Concatenate lists
  - `<`: Priority to new items when overwriting, prepend new when concatenating (default)
  - `>`: Priority to existing items when overwriting, prepend existing when concatenating

- `@keypath`: Where to apply the merge (optional) (default = no path = in-place merge)

## Merge Options

### Dictionary Merging

```yaml
<<: *file:base.yaml # Default merge, priority to existing values, non-recursive
# Equivalent to
<<{>~}: !include file:override.yaml
# or (order doesn't matter)
<<{~>}: !include file:override.yaml

# Recursive merge with priority to new values
<<{+<}: *file:new_values.yaml

# Recursive merge with priority to new values, limit recursion depth
<<{+<2}: *file:new_values.yaml

# Recursive merge with priority to existing values
<<{+>}: !include file:defaults.yaml
```

### List Merging

```yaml
# Replace lists
<<[~<]: [new_item1, new_item2] # new list overwrites existing list
<<[~>]: [new_item1, new_item2] # existing list overwrites new list

# Merge with priority
<<[+<]: [priority_items] # Existing items at the end
<<[+>]: [fallback_items] # New items at the end
```

## Targeting Specific Paths

```yaml
# Merge at a specific path
<<{+}@settings.database: *file:db_override.yaml

# Merge multiple paths
<<{+}@settings.logging: *file:logging.yaml
<<{+}@settings.cache: *file:cache.yaml
```

## Misc Examples

```yaml
# Merge only 2 levels deep
<<{+2}: *file:shallow_merge.yaml

# Deep merge for dictionaries, shallow for lists
<<{+<}[~]: *file:mixed_merge.yaml
```

```yaml
# base.yaml
app:
  name: "MyApp"
  database:
    host: localhost
    port: 5432
```

```yaml
# prod.yaml
<<{+>}: *file:base.yaml # priority to the new values, recursively
app:
  database:
    host: "prod-db.example.com"
    ssl: true
```

```yaml
# features.yaml
features:
  base: &base_features
    logging: true
    metrics: true

  development:
    <<: *base_features # default yaml merge, priority to the new value, non-recursive merge
    debug: true

  production:
    <<: *base_features
    audit: true
    ssl: true
```

```yaml
# service_base.yaml
service:
  timeout: 30
  retries: 3
  endpoints:
    - "/api/v1"
    - "/health"
```

```yaml
# service_override.yaml
<<{+<}[+<]@service: # Recursive merge with service config (override timeout), append new endpoints at the end
  timeout: 60
  endpoints:
    - "/metrics"
```
