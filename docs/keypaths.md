# Advanced: KeyPaths

Internally, Dracon uses a dot-separated `KeyPath` system to reference specific locations within a configuration structure during its composition and interpolation phases. Understanding KeyPaths helps clarify how features like value references (`@`), merge targets (`@target`), include sub-key targeting (`source@target`), and `deferred_paths` work.

## What is a KeyPath?

A `KeyPath` represents a navigation path from a root (either the absolute document root or a relative starting point) to a specific node or value within the nested configuration structure. It's similar to filesystem paths or dictionary/attribute access in code.

## Syntax

KeyPaths use a dot (`.`) separated notation, with special characters for root and parent navigation:

- **Segment Separator (`.`):** Separates keys in a mapping or indices in a sequence.
  - Example: `database.host`, `users.0.name`
- **Absolute Root (`/`):** When present at the beginning, indicates the path starts from the absolute root of the configuration document being processed.
  - Example: `/app/name`, `/services/0/port`
- **Parent (`..`):** Navigates one level up in the hierarchy. Can be chained (`...` for two levels up, etc.). These are simplified during resolution (e.g., `a.b..c` becomes `a.c`).
  - Example: `database.connection_pool..timeout` (accesses `timeout` sibling of `connection_pool`)
- **Escaping (`\.` and `\/`):** If a key name _itself_ contains a literal dot or slash, it must be escaped with a backslash in the KeyPath string representation.
  - Example: `config\.with\.dots.value`, `path\/segment.key`
- **Wildcards (for matching only):**
  - `*`: Matches any single segment name/index.
  - `**`: Matches zero or more segments consecutively.
  - Used primarily in `deferred_paths` for pattern matching. `a.*.c` matches `a.b.c`, `a.x.c`. `a.**.d` matches `a.d`, `a.b.d`, `a.b.c.d`.

!!! note
The forward slash (`/`) is _only_ used to indicate the absolute root at the _beginning_ of a path. It is **not** used as a segment separator like in file paths. `a/b` is invalid; use `a.b`. A path like `a.b/c.d` is interpreted as absolute path `/c.d`.

## How KeyPaths are Used

1.  **Value References (`@` in `${...}`):**

    - `${@/path.from.root}`: Uses an absolute KeyPath starting from the root.
    - `${@.sibling_key}` or `${@../parent.key}`: Uses a relative KeyPath, resolved from the location of the interpolation expression.
    - Dracon calculates the target KeyPath and retrieves the final constructed value from that location during lazy evaluation. See [Interpolation](interpolation.md).

2.  **Merge Targets (`<<...@target_path:`):**

    - The `target_path` after the `@` is parsed as a KeyPath relative to the mapping containing the merge key.
    - Dracon applies the merge operation at the node identified by this KeyPath. See [Merging](merging.md).

3.  **Deferred Paths (`DraconLoader(deferred_paths=...)`):**

    - The strings in the `deferred_paths` list are treated as KeyPath patterns (supporting `*` and `**`).
    - Any node whose absolute KeyPath matches one of these patterns during composition will be wrapped in a `DeferredNode`. See [Deferred Nodes](deferred.md).

4.  **Include Sub-key Targeting (`!include source@target_path`):**
    - The `target_path` after the `@` is parsed as a KeyPath.
    - Dracon first loads the entire `source`, then extracts only the node structure located at `target_path` within that source. See [Includes](includes.md).

## Internal Representation

While you typically interact with KeyPaths as strings, Dracon internally parses them into a list of segments and special tokens (like `ROOT`, `UP`). It performs simplification (e.g., `a.b..c` simplifies to `a.c`) before using them for lookups or matching.
