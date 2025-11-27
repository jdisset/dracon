# Reference: Merge Key Syntax

!!! abstract
Dracon extends the standard YAML merge key (`<<:`) to provide fine-grained control over how dictionaries (mappings) and lists (sequences) are combined during configuration composition.

## Syntax

The extended merge key follows the pattern:

```
<<{dict_opts}[list_opts](ctx_opts)@target_path: source_node
```

- **`<<:`**: The merge key indicator.
- **`{dict_opts}`** (Optional): Controls dictionary merging.
- **`[list_opts]`** (Optional): Controls list merging.
- **`(ctx_opts)`** (Optional): Controls context/variable propagation.
- **`@target_path`** (Optional): [KeyPath](./keypaths.md) specifying a sub-key within the current mapping where the merge should apply (relative path). Defaults to the current mapping.
- **`source_node`**: The node providing data to merge (e.g., `*anchor`, `!include ...`, inline mapping/list).

## Dictionary Options (`{dict_opts}`)

Placed inside `{}`. Combine one mode option with one priority option. Optional depth modifier.

- **Mode:**
  - `+` (Default): **Append/Recurse.** Adds new keys. For existing keys, recursively merges if both values are dicts (up to `dict_depth`). Otherwise, resolves conflict based on priority.
  - `~`: **Replace.** Adds new keys. For existing keys, _always_ replaces the entire value based on priority (no recursion).
- **Priority:**
  - `>` (Default with `+`): **Existing Wins.** Keep the value from the dictionary containing the `<<:` key.
  - `<` (Default with `~`): **New Wins.** Keep the value from the `source_node`.
- **Depth:**
  - `N` (integer, e.g., `{+2>}`): Limits recursion depth for `+` mode to `N` levels. Deeper levels are resolved by priority without recursion.

!!! note default
If `{}` is omitted or empty _and_ no `@target_path` is specified, defaults to `{+>}` (Append/Recurse, Existing Wins). If `@target_path` _is_ specified, the default usually implies an override intent, changing to `{<+}` (Append/Recurse, New Wins).

## List Options (`[list_opts]`)

Placed inside `[]`. Combine one mode option with one priority option. Applies only when _both_ the existing and new values for a key are lists.

- **Mode:**
  - `~` (Default): **Replace.** The entire list is replaced by one of the lists based on priority.
  - `+`: **Concatenate.** The lists are combined into a single list.
- **Priority:**
  - `>` (Default): **Existing Wins / Appends.** In `~` mode, keeps the _existing_ list. In `+` mode, appends the _new_ list's elements (`existing + new`).
  - `<`: **New Wins / Prepends.** In `~` mode, keeps the _new_ list. In `+` mode, prepends the _new_ list's elements (`new + existing`).
- **Depth:**
  - `N` (integer, e.g., `[+1<]`): Limits recursion depth within nested structures _during list concatenation_ (less common).

!!! note default
If `[]` is omitted or empty, it defaults to `[~>]` (Replace, **Existing** Wins).

## Context Propagation Options (`(ctx_opts)`)

Placed inside `()`. Controls whether `!define` variables from the included source are propagated to the including document's scope.

- **`<`**: **Propagate context.** Variables defined via `!define` in the included file become available in the including file's interpolation scope.

!!! note default
If `()` is omitted, context propagation is disabled—variables defined in included files stay local to those files.

**Use Case:** When including a file that defines shared variables (e.g., constants, reusable objects), use `<<(<):` to make those definitions available for interpolation in the including document.

```yaml
# common.yaml
!define TIMEOUT: 30
!define RETRY_COUNT: 3
defaults:
  timeout: ${TIMEOUT}

# main.yaml
<<(<): !include file:common.yaml  # propagate TIMEOUT and RETRY_COUNT

service:
  timeout: ${TIMEOUT}      # works because of (<)
  retries: ${RETRY_COUNT}  # works because of (<)
```

Without `(<)`, the `${TIMEOUT}` interpolation in `main.yaml` would fail because the variable wouldn't be in scope.

## Combined Default (`<<:`)

If only `<<:` is used without any `{}` or `[]` options and no `@target_path`, the effective default behavior is **`<<{+>}[~>]`**:

- Dictionaries: Append/Recurse, Existing Wins.
- Lists: Replace, Existing Wins.

## Examples

| Syntax        | Dictionary Behavior                      | List Behavior                       | Description                                               |
| :------------ | :--------------------------------------- | :---------------------------------- | :-------------------------------------------------------- |
| `<<:`         | Append/Recurse, Existing Wins (`{~>}`)   | Replace, **Existing** Wins (`[~>]`) | Default merge.                                            |
| `<<{<+}:`     | Append/Recurse, New Wins                 | Replace, Existing Wins (`[~>]`)     | Common override pattern (new file wins dict keys)         |
| `<<[+>]:`     | Append/Recurse, Existing Wins (`{~>}`)   | Concatenate, Existing first         | Append new list items to existing list                    |
| `<<[+<]:`     | Append/Recurse, Existing Wins (`{~>}`)   | Concatenate, **New** first          | Prepend new list items to existing list                   |
| `<<{~<}[~>]:` | Replace, New Wins                        | Replace, Existing Wins              | Dict values fully replaced (new wins), list kept existing |
| `<<@target:`  | Append/Recurse, **target Wins** (`{<+}`) | Replace, Existing Wins (`[~>]`)     | Default merge on specified target subkey                  |
| `<<(<):`      | Append/Recurse, Existing Wins (`{+>}`)   | Replace, Existing Wins (`[~>]`)     | Default merge + propagate `!define` vars to parent scope  |

!!! note
The order of `{}`, `[]`, and `()` does not matter (e.g., `<<{+<}[+>](<)` is the same as `<<(<)[+>]{+<}`).
