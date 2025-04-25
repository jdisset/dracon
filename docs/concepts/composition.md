# Concepts: Composition (Includes & Merges)

Dracon's power lies in its ability to compose configurations from multiple sources using includes and merge directives. This allows for modularity, layering, and overrides. Composition happens _before_ the final Python objects are constructed.

## Includes (`!include`)

The `!include` directive fetches content from a specified source and inserts it into the current node tree during the composition phase.

**Resolution Process:**

1.  **Path Evaluation:** The include string (e.g., `file:$DIR/settings.yaml`, `pkg:lib:conf`, `$var@key`) is evaluated. Any `${...}` or `$VAR` interpolations are resolved using the context available _at the `!include` directive's location_.
2.  **Source Loading:** The appropriate loader (file, pkg, env, custom, or anchor/path lookup within the current document) fetches the raw content or target node.
3.  **Recursive Composition:** If the source provides new YAML content (e.g., from a file), Dracon _recursively composes_ that content. This means the included content can itself have includes, merges, instructions, etc., which are processed within their own scope. Context variables like `$DIR` are injected for file/pkg includes.
4.  **Sub-key Extraction (`@`):** If the include path specified a sub-key (`source@path.to.key`), only that specific part of the composed include result is selected.
5.  **Insertion:** The resulting node (or node tree) replaces the `!include` directive in the main configuration tree.
6.  **Context Merging:** The context of the original `!include` node is merged onto the _root_ of the included node structure (respecting merge key priority, default `{>~}` - existing wins). This allows passing context down into includes.

**Key Behavior:**

- **Copying (Anchors/Paths):** When including via anchors (`*anchor`) or relative/absolute paths (`/path`, `./sibling`), Dracon performs a **deep copy** of the target node structure. This prevents modifications in one part of the config from accidentally affecting another part that included the same anchor.
- **Recursion:** Includes are processed recursively until no `!include` directives remain. Dracon detects and prevents circular includes.

## Merging (`<<:`)

The YAML merge key (`<<:`), extended by Dracon, combines nodes during composition. Standard YAML merge (`<<: *anchor`) roughly corresponds to Dracon's `{~<}` (Replace keys, New wins). Dracon's extended syntax provides much finer control.

**Resolution Process:**

1.  **Identify Merge Pairs:** Dracon identifies mappings containing one or more `<<...: source` keys.
2.  **Source Resolution:** For each merge key, the `source` node is resolved (similar to `!include` - it could be an anchor `*ref`, an include `!include ...`, or an inline mapping/sequence).
3.  **Target Identification:** The target node for the merge is determined:
    - If `@path` is present, the target is the node at `path` relative to the current mapping.
    - Otherwise, the target is the current mapping itself.
4.  **Merge Operation:** The resolved `source` node is merged into the `target` node according to the `{dict_opts}` and `[list_opts]` specified in the merge key.
    - Dictionaries are merged key-by-key based on mode (`+`/`~`), priority (`<`/`>`), and depth.
    - Lists are merged (if both source and target values for a key are lists) based on mode (`+`/`~`) and priority (`<`/`>`).
    - Conflicts between different types are resolved based on dictionary priority (`<`/`>`).
5.  **Merge Key Removal:** After merging, the `<<...:` key itself is removed from the mapping.

**Order of Operations:**

Within a single mapping, if multiple `<<:` keys exist, they are processed **in the order they appear in the YAML source**. This is crucial for layering configurations correctly.

```yaml
# base.yaml: { setting: base_value }
# override.yaml: { setting: override_value, new: override_new }

config:
  # 1. Merge base.yaml (new wins)
  <<{<+}: !include file:base.yaml
  # Current state: { setting: base_value }

  # 2. Merge override.yaml onto the result (new wins)
  <<{<+}: !include file:override.yaml
  # Current state: { setting: override_value, new: override_new }

  # 3. Define an inline key
  final: final_value

# Final config: { setting: override_value, new: override_new, final: final_value }
```

If the merge keys were `<<{>+}` (existing wins), the result would be `{ setting: base_value, new: override_new, final: final_value }`.

Understanding this composition process—includes resolving recursively, then merges applying according to specified strategies and order—is key to mastering Dracon's configuration layering capabilities.
