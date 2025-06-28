# How-To: Merge Configurations

Dracon excels at layering configurations, applying overrides, and combining settings from multiple sources. This is primarily achieved through the extended YAML merge key (`<<:`).

## Basic Merging (Multiple Files)

When loading multiple files with `dracon.load`, they are merged sequentially.

```python
import dracon as dr

# Loads base.yaml, then merges prod.yaml onto it
# Default strategy for multi-file load: <<{<+}[<~]
# (Dict: Recursive Append, New wins; List: Replace, New wins)
config = dr.load(["config/base.yaml", "config/prod.yaml"], context={...})
```

## Explicit Merging (`<<:`)

You can explicitly merge nodes within a single YAML file using the `<<:` key.

```yaml
defaults: &defaults
  timeout: 30
  retries: 3
  features: [a, b]

service_config:
  # Inherit from defaults using the plain merge key
  <<: *defaults # standard YAML merge (existing wins, replace keys - non recursive). Equivalent to <<{>~}[>~]: *defaults
  # Override specific values
  timeout: 60
  # Add new values
  endpoint: /api/v1
  # Add new list - default for list merge is REPLACE, EXISTING wins
  # So, the 'features' key from *defaults is kept.
  # If we added 'features: [c, d]' here *after* the merge key,
  # it would simply overwrite the merged key.
# Resulting service_config (using <<: *defaults default {+>}[~>]):
# { timeout: 30, retries: 3, features: [a, b], endpoint: /api/v1 }
# Note: timeout: 60 defined *after* the merge would override the merged value.
```

## Advanced Merging with Options

Dracon extends `<<:` with options to control dictionary and list merging precisely:

`<<{dict_opts}[list_opts]@target_path: source_node`

- `{dict_opts}`: Controls dictionary merging.
  - `~`: (Default) **Replace.** Overwrites entire value for conflicting keys.
  - `+` **Append/Recurse.** Merges nested dicts.
  - `>` (Default): **Existing value wins** priority.
  - `<`: **New value (i.e. source_node) wins** priority.
  - `N` (e.g., `+2`): Limit recursion depth.
- `[list_opts]`: Controls list merging (only if both existing and new values are lists).
  - `~` (Default): **Replace** full list.
  - `+`: **Concatenate** lists.
  - `>` (Default): **Existing list wins** / Appends new list in `+` mode.
  - `<`: **New list (i.e. from source_node) wins** / Prepends new list in `+` mode.
- `@target_path`: (Optional) Apply the merge to a sub-key relative to the current node. Uses [KeyPath](../reference/keypaths.md) syntax.
- `source_node`: The node to merge in (e.g., `*anchor`, `!include file:other.yaml`, or a regular YAML mapping).

**Default `<<:` key (no options):** Equivalent to `<<{+>}[~>]` (Dict: Append/Recurse, Existing Wins; List: Replace, Existing Wins).

**Examples:**

1.  **Recursive Dict Merge, New Wins:**

    ```yaml
    base: &base
      db: { host: localhost, port: 5432 }
      settings: { theme: light }

    prod:
      <<{+<}: *base # Merge recursively (+), new wins (<)
      db:
        host: prod.db # Overrides base host
        # port inherited from base
      settings:
        workers: 4 # Added

    # Result prod: { db: { host: prod.db, port: 5432 }, settings: { theme: light, workers: 4 } }
    ```

2.  **Replace and Append to List, Existing First:**

    ```yaml
    defaults: &defaults
      middlewares: [logging, auth]

    # Replace
    custom:
      <<[~>]: *defaults # Replace lists (~), existing first (>)
      middlewares: [cors, caching] # This definition *overwrites* the merged list
    # Result custom: { middlewares: [cors, caching] }

    # Append
    custom_append:
      <<[+>]: *defaults # Concatenates, existing ([cors, caching]) first
      middlewares: [cors, caching]
    # Result custom_append: { middlewares: [cors, caching, logging, auth] }
    ```

3.  **Merge into Sub-key:**

    ```yaml
    common_settings: &common
      timeout: 10
      retries: 2

    app_config:
      service_a:
        endpoint: /a
      service_b:
        endpoint: /b

    <<@app_config.service_b: *common

    # Result app_config:
    # { service_a: { endpoint: /a },
    #   service_b: { endpoint: /b, timeout: 10, retries: 2 } }
    ```

See [Merging Concepts](../concepts/composition.md#merging-configurations) and the [Merge Key Reference](../reference/merge_syntax.md) for full details and strategy explanations.
