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
  <<: *defaults
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

If you want the standard YAML merge behavior (replace keys, new wins), use `<<{~<}: *defaults`.

## Advanced Merging with Options

Dracon extends `<<:` with options to control dictionary and list merging precisely:

`<<{dict_opts}[list_opts]@target_path: source_node`

- `{dict_opts}`: Controls dictionary merging.
  - `+` (Default): **Append/Recurse.** Merges nested dicts.
  - `~`: **Replace.** Overwrites entire value for conflicting keys.
  - `<`: **New value wins** priority. (Default for `~`)
  - `>` (Default for `+`): **Existing value wins** priority.
  - `N` (e.g., `+2`): Limit recursion depth.
- `[list_opts]`: Controls list merging (only if both existing and new values are lists).
  - `~` (Default): **Replace** list.
  - `+`: **Concatenate** lists.
  - `<`: **New list wins** / Prepends in `+` mode.
  - `>` (Default): **Existing list wins** / Appends in `+` mode.
- `@target_path`: (Optional) Apply the merge to a sub-key relative to the current node. Uses [KeyPath](../reference/keypaths.md) syntax.
- `source_node`: The node to merge in (e.g., `*anchor`, `!include file:other.yaml`).

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

2.  **Append to List, Existing First:**

    ```yaml
    defaults: &defaults
      middlewares: [logging, auth]

    custom:
      <<[+>]: *defaults # Concatenate lists (+), existing first (>)
      middlewares: [cors, caching] # This definition *overwrites* the merged list

    # Result custom: { middlewares: [cors, caching] }
    # To actually append, define the list *before* the merge key:
    custom_append:
      middlewares: [cors, caching]
      <<[+>]: *defaults # Concatenates, existing ([cors, caching]) first

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
        # Merge common settings only into service_b
        # Default for targeted merge is often {<+} (new wins)
        <<@service_b: *common # Equivalent to <<{<+}@service_b: *common

    # Result app_config:
    # { service_a: { endpoint: /a },
    #   service_b: { endpoint: /b, timeout: 10, retries: 2 } }
    ```

See [Merging Concepts](../concepts/composition.md#merging-configurations) and the [Merge Key Reference](../reference/merge_syntax.md) for full details and strategy explanations.
