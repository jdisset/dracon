# Concepts: Loading and Context

The `DraconLoader` is the heart of Dracon's configuration processing system. It handles parsing YAML, processing Dracon's directives, managing context, and constructing the final Python objects.

## The Loading Process

When you call `dracon.load("file.yaml")` or `loader.load("file.yaml")`, several steps occur:

1.  **File Reading:** The appropriate loader (`file:`, `pkg:`, custom) reads the raw YAML content from the source. Caching may be used here.
2.  **YAML Parsing & Composition:** `ruamel.yaml` parses the raw YAML into a basic node tree. Dracon's `DraconComposer` extends this to recognize Dracon-specific syntax like `!include`, `<<{...}`, `!define`, etc., building an initial _composition representation_.
3.  **Instruction Processing:** Instructions like `!define`, `!if`, `!each` are executed, modifying the node tree and context _before_ includes or merges.
4.  **Include Resolution:** `!include` directives are processed recursively. The content from included sources is loaded, composed, and inserted into the main tree. Context variables like `$DIR` are injected into the included scope.
5.  **Merge Processing:** Extended merge keys (`<<{...}[...]@...:`) are processed according to their specified strategies, combining different parts of the node tree.
6.  **Deferred Node Identification:** Nodes tagged with `!deferred` or matching `deferred_paths` are identified and wrapped. Their processing is paused.
7.  **Reference Preprocessing:** Interpolation expressions (`${...}`) are scanned. References using `&anchor` or `&/path` (node references for templating) are prepared.
8.  **Final Construction:** Dracon's `Draconstructor` traverses the final node tree.
    - It constructs basic Python types (dict, list, str, int...). By default, it uses `dracon.dracontainer.Mapping` and `Sequence` for automatic lazy interpolation handling.
    - When it encounters a tag (`!MyModel`), it resolves the corresponding type.
    - If the type is Pydantic, it passes the constructed data to Pydantic for validation and instance creation.
    - If the type is custom, it attempts `YourClass(constructed_data)`.
    - Values containing `${...}` are wrapped in `LazyInterpolable` objects (unless `enable_interpolation=False`).
9.  **Return Value:** The final constructed Python object (often a Pydantic model instance or a Dracon container) is returned.

## The Role of Context

Context is a dictionary (`dracon.utils.ShallowDict` internally) that holds variables and functions accessible during the loading process.

- **Initial Context:** Provided via `DraconLoader(context=...)`. This is the primary way to make Pydantic models, custom types, or helper functions available.
- **Default Context:** Dracon automatically adds `getenv`, `getcwd`, and `construct`.
- **Instruction Context (`!define`, `!set_default`):** Instructions modify the context available to subsequent nodes _within the same scope_ or child scopes during composition.
- **Include Context (`$DIR`, etc.):** File/package loaders inject variables like `$DIR` into the context of the _included_ file's nodes.
- **Interpolation Context (`${...}`):** Lazy interpolation expressions have access to the context captured _at the time the LazyInterpolable object was created_. This includes initial context, definitions, and include-specific variables. Context provided later via `.resolve(context=...)` or `.construct(context=...)` is merged with the captured context.
- **Deferred Node Context:** A `DeferredNode` captures a snapshot of the context available when it was created. Context passed to `.construct(context=...)` merges with this snapshot. `!deferred::clear_ctx` controls which variables are _excluded_ from the snapshot.

**Context Precedence:** Generally, more specific contexts override broader ones. Context provided at runtime (e.g., via `.construct()`) typically overrides context captured during loading. Merge keys (`{<+}` vs `{>+}`) can influence merging behavior for context dictionaries passed down the tree.

## Output Types (`Dracontainer` vs. `dict`/`list`)

By default, mappings become `dracon.dracontainer.Mapping` and sequences become `dracon.dracontainer.Sequence`.

- **Pros:** These containers automatically resolve `${...}` interpolations when you access their elements (`config.key`, `config['key']`, `config.list[0]`).
- **Cons:** They are custom types, not standard `dict` or `list`.

You can use standard types:

```python
loader = DraconLoader(base_dict_type=dict, base_list_type=list)
config = loader.load("config.yaml")
assert isinstance(config, dict)

# IMPORTANT: With standard types, accessing config['key'] will return
# the LazyInterpolable object itself if the value was '${...}'.
# You need to manually call resolve_all_lazy(config) or handle
# resolution yourself if needed before using the values.
```

Choose based on whether you prefer automatic lazy resolution or standard Python types. `Dracontainer` is generally recommended unless you have specific reasons to use standard types.
