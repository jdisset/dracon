# Merging Configurations

Dracon extends YAML's basic merge key (`<<:`) with a powerful syntax to precisely control how dictionaries and lists are combined when merging configuration sources. This is essential for layering configurations, such as applying environment-specific overrides to a base configuration.

## The Merge Syntax

Dracon's extended merge key follows this pattern:

`<<{dict_opts}[list_opts]@target_path: merge_source`

- `<<:`: The standard YAML merge key indicator.
- `{dict_opts}`: (Optional) Controls how **dictionaries** are merged.
- `[list_opts]`: (Optional) Controls how **lists** are merged.
- `@target_path`: (Optional) A [KeyPath](keypaths.md) specifying a sub-key within the _current_ mapping where the merge should be applied. If omitted, the merge applies directly to the current mapping.
- `merge_source`: The node providing the data to be merged in. This is often an alias (`*anchor`) or an `!include` directive, but can also be an inline mapping or sequence.

## Dictionary Merging Options (`{dict_opts}`)

These options control behavior when merging two dictionaries (mappings).

- **Mode:**
  - `+` (Append/Recurse - Default): Adds new keys from `merge_source`. For existing keys, if both values are dictionaries, it merges them recursively. If values are not both dictionaries (or are lists), the conflict is resolved by priority.
  - `~` (Replace): Adds new keys from `merge_source`. For existing keys, the value is _always_ determined by the priority setting, completely replacing the other value (no recursion).
- **Priority:**
  - `>` (Existing Wins - Default for `+`): If a key exists in both, the value from the _existing_ dictionary (the one containing the `<<:` key) is kept.
  - `<` (New Wins - Default for `~`): If a key exists in both, the value from the `merge_source` dictionary is kept.
- **Depth (`N`):**
  - `+N` (e.g., `{+2>}`): Limits recursive merging (`+` mode) to `N` levels deep. Beyond this depth, conflicts are resolved by priority without further recursion.

**Examples:**

```yaml
base: &base
  x: 1
  y:
    a: 10
  z: 100
  list1: [a, b]

# Example 1: Default-like (Append keys, Existing wins, No dict recursion unless forced)
merged1:
  <<: *base
  x: 2 # base.x (1) wins because existing wins by default
  y:
    b: 20 # Added, y is replaced because base dict merge isn't recursive by default
  w: 300 # Added

# Result merged1: { x: 1, y: { b: 20 }, z: 100, w: 300, list1: [a, b] }

# Example 2: Recursive Append, New wins
merged2:
  <<{+<}: *base # Recursively merge dicts, new values win
  x: 2 # New x (2) wins
  y:
    b: 20 # Added to existing y
  w: 300 # Added

# Result merged2: { x: 2, y: { a: 10, b: 20 }, z: 100, w: 300, list1: [a, b] }

# Example 3: Replace, Existing wins
merged3:
  <<{~>}: *base # Replace conflicting, existing wins
  x: 2 # Existing x (1) wins
  y:
    b: 20 # Existing y ({a: 10}) wins entirely, {b: 20} is ignored
  w: 300 # Added

# Result merged3: { x: 1, y: { a: 10 }, z: 100, w: 300, list1: [a, b] }
```

## List Merging Options (`[list_opts]`)

These options control behavior when a key exists in both dictionaries being merged, and _both_ values are lists.

- **Mode:**
  - `~` (Replace - Default): The entire list is replaced by either the existing list or the new list, based on priority.
  - `+` (Concatenate): The lists are combined into one.
- **Priority:**
  - `<` (New Wins/Prepends - Default):
    - In `~` (Replace) mode: The _new_ list from `merge_source` is kept.
    - In `+` (Concatenate) mode: The _new_ list elements come _before_ the existing elements (`new + existing`).
  - `>` (Existing Wins/Appends):
    - In `~` (Replace) mode: The _existing_ list is kept.
    - In `+` (Concatenate) mode: The _existing_ list elements come _before_ the new elements (`existing + new`).
- **Depth (`N`):**
  - `+N` (e.g., `[+2<]`): If lists contain nested structures, limits recursive merging within those structures to `N` levels when concatenating. (Less common).

**Examples:**

```yaml
base: &base
  items: [a, b]
  config:
    ports: [80, 443]

# Example 1: Replace list, New wins (Default list behavior)
merged_list1:
  <<: *base # Implicitly uses [~<]
  items: [c, d]

# Result merged_list1: { items: [c, d], config: { ports: [80, 443] } }

# Example 2: Concatenate, Existing first (Append new)
merged_list2:
  <<[+>]: *base # Concatenate, existing items first
  items: [c, d]

# Result merged_list2: { items: [a, b, c, d], config: { ports: [80, 443] } }

# Example 3: Concatenate, New first (Prepend new)
merged_list3:
  <<[+<]: *base # Concatenate, new items first
  items: [c, d]
# Result merged_list3: { items: [c, d, a, b], config: { ports: [80, 443] } }
```

## Targeting Sub-keys (`@target_path`)

Apply the merge operation specifically to a nested key within the current mapping.

```yaml
base: &base
  host: base_host
  port: 1000

config:
  service_a:
    host: service_a_host
    port: 8001
  common:
    timeout: 30
    # Merge *base into the 'common' sub-dictionary
    # Using recursive append, new values win for dictionaries
    <<{+<}@common: *base # Result: common: { timeout: 30, host: base_host, port: 1000 }

# Result config:
# { service_a: { host: service_a_host, port: 8001 },
#   common: { timeout: 30, host: base_host, port: 1000 } }
```

## Combining Options

You can specify both dictionary and list options together.

```yaml
defaults: &defaults
  settings:
    retries: 3
    active: false
  users: ["admin"]

production:
  # For dicts: Recursive Append, New wins
  # For lists: Concatenate, Existing first (Append new)
  <<{+<}[+>]: *defaults
  settings:
    active: true # Overrides default
    threads: 4 # Added
  users: ["ops", "dev"] # Appended to defaults

# Result production:
# { settings: { retries: 3, active: true, threads: 4 },
#   users: ['admin', 'ops', 'dev'] }
```

## Standard YAML Merge (`<<: *anchor`)

Dracon still respects the standard YAML merge key `<<: *anchor` if no specific Dracon options (`{}`, `[]`, `@`) are provided _on that specific key_. However, the standard YAML merge has semantics roughly equivalent to Dracon's `{~<}` (Replace keys, New value wins). If you need finer control or different behavior (like recursion), use Dracon's explicit syntax.
