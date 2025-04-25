# Concepts: Deferred vs Resolvable

Dracon offers two mechanisms for delaying parts of the configuration processing: `DeferredNode` (using `!deferred` tag or `deferred_paths`) and `Resolvable` (using `Resolvable[T]` type hint, often with `Arg(resolvable=True)`). While both involve deferral, they serve distinct purposes and operate at different stages.

## `DeferredNode` (`!deferred`)

- **What it does:** Pauses the _entire construction_ of the tagged YAML node branch. Dracon stops processing this branch during the initial load.
- **Mechanism:** Creates a `dracon.deferred.DeferredNode` object as a placeholder in the configuration structure. This object holds:
  - The original YAML node structure.
  - A snapshot of the context available when the node was encountered.
  - A reference to the `DraconLoader` instance.
  - Information about which context variables to potentially ignore (`clear_ctx`).
- **When to Use:**
  - **Late Context Binding:** When the construction of a component requires context (variables, functions) that is only available _after_ the main configuration load (e.g., secrets fetched from a vault, runtime parameters).
  - **Resource Management:** To delay the initialization of resource-intensive objects (like database connections) until they are actually needed.
  - **Conditional Construction:** To decide _whether_ or _how_ to construct a component based on other parts of the _already loaded_ configuration (though `!if` might be simpler for basic cases).
  - **Manual Orchestration:** To explicitly control the initialization order of components with dependencies.
- **Trigger:** Manual call to the `deferred_node.construct(context=...)` method. This resumes the Dracon loading process (composition, construction, validation) specifically for that node branch, merging the provided runtime `context` with the captured context.
- **Granularity:** Affects an entire node and its children in the YAML tree.

**Analogy:** `DeferredNode` is like receiving a flat-pack furniture box (`DeferredNode`) with instructions (`captured node/context`). You need to manually assemble it (`.construct()`) later, possibly using extra tools (`runtime context`).

## `Resolvable[T]`

- **What it does:** Delays the _final processing or validation_ of a _single field's value_ within an _already constructed_ configuration object.
- **Mechanism:** Typically used as a type hint (`Resolvable[str]`) often combined with `Arg(resolvable=True)` for CLI arguments. Dracon constructs the main configuration object (e.g., a Pydantic model), but for fields marked as `Resolvable`, it creates a `dracon.resolvable.Resolvable` object instead of the final type `T`. This object holds:
  - The underlying YAML node representing the value.
  - A reference to the constructor.
  - The expected inner type `T`.
- **When to Use:**
  - **CLI Argument Post-Processing:** When a CLI argument's final value or validation depends on _other_ arguments or loaded configuration values that become available only _after_ `program.parse_args()` completes.
  - **Inter-dependent Field Finalization:** When one field's final form depends on another field within the same configuration object, allowing you to resolve them in a specific order _after_ the main object is loaded.
  - **Application-Specific Logic:** Injecting a final transformation or check on a value based on application state _after_ configuration loading.
- **Trigger:** Manual call to the `resolvable_value.resolve(context=...)` method. This triggers the constructor to process the stored node, aiming to produce a value of the inner type `T`, using any provided context.
- **Granularity:** Affects a single value associated with a specific field.

**Analogy:** `Resolvable` is like getting a gift voucher (`Resolvable`) for a specific item (`T`). You have the voucher now, but you need to go redeem it (`.resolve()`) later, possibly providing extra information (`context`), to get the actual item.

## Comparison Summary

| Feature            | `DeferredNode` (`!deferred`)        | `Resolvable[T]`                         |
| :----------------- | :---------------------------------- | :-------------------------------------- |
| **What's Delayed** | Entire Node Branch **Construction** | Single Field **Value Processing**       |
| **Stage**          | During initial `load`/`loads`       | After initial load, before final use    |
| **Placeholder**    | `DeferredNode` instance             | `Resolvable` instance                   |
| **Trigger**        | `.construct(context=...)`           | `.resolve(context=...)`                 |
| **Input Held**     | YAML Node, Context Snapshot         | YAML Node, Expected Type `T`, Ctor Ref  |
| **Granularity**    | Whole Node Tree Branch              | Single Field/Value                      |
| **Primary Use**    | Late Context, Resource Init, Order  | CLI Post-Processing, Field Finalization |

Use `DeferredNode` when you need to postpone building a component. Use `Resolvable` when the component is built, but a specific value within it needs a final touch based on later information.
