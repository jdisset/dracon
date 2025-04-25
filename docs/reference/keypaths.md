# Reference: KeyPaths

Dracon uses KeyPaths internally to reference specific locations within a nested configuration structure during composition and interpolation. Understanding KeyPaths is essential for using features like value references (`@`), merge targets (`@`), include sub-key targeting (`@`), and deferred paths.

## Syntax

KeyPaths use **dot (`.`) notation** as the primary separator, with special characters for root, parent navigation, and pattern matching:

- **Segment Separator (`.`):** Separates keys in mappings or indices in sequences.
  - _Example:_ `database.host`, `users.0.name`
- **Absolute Root (`/`):** When used _only_ at the **beginning** of a path, it indicates the path starts from the absolute root of the configuration document being processed. It is **not** used as a separator between segments.
  - _Example:_ `/app/name` (Incorrect!), `/app.name` (Correct), `/services.0.port` (Correct)
- **Parent (`..`):** Navigates one level up in the hierarchy. Can be chained (`...` for two levels up, etc.). These are often resolved during path simplification (e.g., `a.b..c` becomes `a.c`).
  - _Example:_ `config.database..timeout` (accesses `timeout` sibling of `database`)
- **Current (`.`):** Represents the current level. Often used implicitly for relative paths in interpolation, e.g., `${@.sibling}` refers to a sibling key. A leading `.` like `.!include .sibling_file` would typically be resolved relative to the current node's location context (often the parent directory).
- **Escaping (`\.`, `\/`):** Use a backslash (`\`) to escape literal dots (`.`) or slashes (`/`) _if they appear within a key name itself_. This is necessary to distinguish them from separators or the root indicator.
  - _Example:_ `section\.with\.dots.value`, `a.path\/segment.key` (References keys named "section.with.dots" and "path/segment" respectively).
- **Wildcards (for Matching Only):** Used primarily in patterns like `deferred_paths` in `DraconLoader` or potentially custom logic. Not used for direct value retrieval via `@`.
  - `*`: Matches any _single_ segment name/index (e.g., `a.*.c` matches `a.b.c`).
  - `**`: Matches _zero or more_ consecutive segments (e.g., `a.**.d` matches `a.d`, `a.b.d`, and `a.b.c.d`).
  - Partial segment matching with `*` is also supported within patterns (e.g., `a.b*.c` matches `a.b.c` and `a.bcd.c`).

!!! warning "Separator is `.` not `/`"
Remember that `/` is _only_ valid as the very first character to denote the absolute root. All subsequent levels in the path _must_ be separated by dots (`.`). `a/b/c` is **invalid** KeyPath syntax; use `a.b.c`.

## Usage in Dracon

KeyPaths are the standard way to target nodes in various Dracon features:

1.  **Value References (`@` in `${...}`):**

    - `${@/path.from.root}`: Absolute KeyPath.
    - `${@.sibling_key}`: Relative KeyPath (sibling).
    - `${@../parent.key}`: Relative KeyPath (navigating up).
    - _Example:_ `${@/database.host}`, `${@.name}`
    - See [Interpolation Syntax](./interpolation_syntax.md).

2.  **Merge Targets (`<<...@target_path:`):**

    - `target_path` is a relative KeyPath from the mapping containing the merge key.
    - _Example:_ `<<{+<}@database: *db_defaults` (merges into the `database` key).
    - See [Merge Key Syntax](./merge_syntax.md).

3.  **Deferred Paths (`DraconLoader(deferred_paths=...)`):**

    - List of absolute KeyPath _patterns_ (supporting `*`, `**`) identifying nodes to defer automatically.
    - _Example:_ `['/services.*.connection', '/external_apis/**']`
    - See [Deferred Execution Guide](../guides/use-deferred.md).

4.  **Include Sub-key Targeting (`!include source@target_path`):**
    - `target_path` is a KeyPath within the `source` document.
    - _Example:_ `!include file:settings.yaml@database.host` (loads only the host value).
    - See [Include Syntax](./include_syntax.md).

## Internal Representation & Simplification

While you typically interact with KeyPaths as strings, Dracon internally parses them into a list of segments and special tokens (like `ROOT`, `UP`). It performs simplification _before_ using them for lookups or matching, resolving `.` and `..` segments where possible (e.g., `a.b..c` simplifies to `a.c`, `/a/b..` simplifies to `/a`). You generally don't need to worry about this unless debugging complex path issues.
