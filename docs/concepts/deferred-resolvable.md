# Concepts: Deferred vs Resolvable

Dracon offers two mechanisms for delaying parts of the configuration processing: `DeferredNode` (using `!deferred` tag or `deferred_paths`) and `Resolvable` (using `Resolvable[T]` type hint, often with `Arg(resolvable=True)`). While both involve deferral, they serve distinct purposes and operate at different stages.

## `DeferredNode` (`!deferred`)

- **What it does:** Pauses the _entire composition and construction_ of the tagged YAML node branch. Dracon stores the raw subtree without evaluating composition directives (`!each`, `!if`, `!fn`, `<<:`, `!include`) inside it.
- **Mechanism:** Creates a `dracon.deferred.DeferredNode` object as a placeholder in the configuration structure. This object holds:
  - The raw, pre-composition YAML node structure (directives preserved as-is).
  - A snapshot of the context available when the node was encountered.
  - A reference to the `DraconLoader` instance.
  - Information about which context variables to potentially ignore (`clear_ctx`).
- **When to Use:**
  - **Late Context Binding:** When the construction of a component requires context (variables, functions) that is only available _after_ the main configuration load (e.g., secrets fetched from a vault, runtime parameters).
  - **Runtime Directives:** When composition directives like `!if` or `!each` depend on runtime values (e.g., `!if ${gpu_available}:`).
  - **Resource Management:** To delay the initialization of resource-intensive objects (like database connections) until they are actually needed.
  - **Conditional Construction:** To decide _whether_ or _how_ to construct a component based on other parts of the _already loaded_ configuration (though `!if` might be simpler for basic cases).
  - **Manual Orchestration:** To explicitly control the initialization order of components with dependencies.
- **Trigger:** Either a one-step `deferred_node.construct(context=...)` call, or a two-step `dracon.compose(node, context=...)` followed by `dracon.construct(composed)`. Both resume the Dracon loading process (composition, construction, validation) specifically for that node branch, merging the provided runtime `context` with the captured context. The two-step API lets you inspect the composed tree before construction.
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

## Where Does Lazy `!define` Fit?

Before reaching for `!deferred` or `Resolvable`, consider whether lazy `!define` solves your problem. When you write `!define x: !MyType { ... }`, the object is constructed automatically on first access to `${x}`. This covers the common case where you need to build a Python object from YAML but its fields depend on other `!define`d variables:

```yaml
!define data: !DataLoader { path: ${data_path} }
!define model: !Predictor { data: ${data} }
result: ${model.predict()}
```

No manual `.construct()` call, no `!noconstruct`, no `&` anchor juggling. If all the information you need is available at composition time (from `!define`, `!set_default`, environment variables, etc.), lazy `!define` is the right tool.

You still need `!deferred` when:

- The context is only available at **runtime** (e.g. secrets fetched after load, user input, runtime IDs).
- You want to **re-construct** the same node multiple times with different contexts.
- You need explicit control over **when** construction happens relative to other application logic.

## Comparison Summary

| Feature            | Lazy `!define`                      | `DeferredNode` (`!deferred`)        | `Resolvable[T]`                         |
| :----------------- | :---------------------------------- | :---------------------------------- | :-------------------------------------- |
| **What's Delayed** | Object construction in `!define`    | Entire Node Branch **Composition + Construction** | Single Field **Value Processing**       |
| **Stage**          | During composition, on first access | During initial `load`/`loads`       | After initial load, before final use    |
| **Trigger**        | Automatic (first `${x}` access)    | Manual `.construct()` or two-step `compose()`/`construct()` | Manual `.resolve(context=...)`          |
| **Context**        | Full composition context            | Captured snapshot + runtime context | YAML Node, Expected Type `T`, Ctor Ref  |
| **Granularity**    | Single variable binding             | Whole Node Tree Branch              | Single Field/Value                      |
| **Primary Use**    | Object pipelines, forward refs      | Late Context, Resource Init, Order  | CLI Post-Processing, Field Finalization |

Use lazy `!define` for composition-time object pipelines. Use `DeferredNode` when you need runtime context. Use `Resolvable` when a single field needs post-load finalization.
