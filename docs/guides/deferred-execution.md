# Deferred Execution

Some values aren't available when the config loads. A runtime ID, a trained model, a database connection pool. Dracon gives you several ways to defer evaluation until the information exists.

If what you want is a clean declarative runtime boundary, start with [Runtime Contracts](../patterns/runtime-contracts.md). This guide covers the underlying mechanisms.

## When to use what

| Situation | Tool | Why |
|---|---|---|
| All info is available at composition time, you just need forward references | `!define x: !Type` (lazy) | Construction is deferred, but everything is known |
| Need runtime context not available during composition | `!deferred` | Pauses the entire composition subtree |
| Single Pydantic field needing user-driven late binding | `Resolvable[T]` | Field-level pause; resolve when ready |
| Single typed `${...}` value that should resolve on access | `Lazy[T]` | Typed wrapper around one interpolation |
| Model with `${...}` defaults that depend on not-yet-available context | `LazyDraconModel` | Defers interpolation to attribute access time |

The three typed wrappers — `Lazy[T]`, `Resolvable[T]`, `DeferredNode[T]` — round-trip through the same parametric mechanism (see [The Primitives](../concepts/primitives.md#typed-deferred-wrappers)). Pick by what you're pausing:

- **`Lazy[T]`** wraps a single `${...}` value. It resolves automatically on attribute access from a `LazyDraconModel`. Use for typed config values where late interpolation is fine and you don't need to control *when* it happens.
- **`Resolvable[T]`** snapshots a node + the constructor needed to build it. It resolves only when you call `.resolve(context)`. Use when the consumer must control the moment of resolution: runtime-sensitive subtrees, graph mutations, audit-sensitive proposals.
- **`DeferredNode[T]`** is a typed Node subclass that lives in the composition tree and implements the Symbol protocol. Use when the deferred branch must itself be a Symbol (passed around, bound, invoked from another template). `Resolvable[T]` is a value; `DeferredNode[T]` is a tree node.

```python
from pydantic import BaseModel
from dracon import Lazy, LazyDraconModel, Resolvable, DraconLoader

class Cfg(LazyDraconModel):
    port: Lazy[int]                 # ${...} that's typed as int
    host: Lazy[str] = "localhost"   # default + lazy

cfg = DraconLoader().loads("port: ${env_port}\nhost: ${env_host}",
                            context={"env_port": 9000, "env_host": "api.local"})
cfg.port  # -> 9000  (resolved on attribute access, returns int)
```

`Lazy[T]` is the right choice when "the value will exist by the time something reads this field" is acceptable. Reach for `Resolvable[T]` when *when* the value resolves matters for correctness or audit.

Pick the lightest tool that fits. `!define` handles most cases. Reach for `!deferred` only when you truly need runtime injection.

## !deferred tag

### Basic usage

Mark a subtree as deferred, and it comes out as a `DeferredNode` instead of a constructed object:

```yaml
output: !deferred "/tmp/${run_id}/results"
```

When you load this, `output` is a `DeferredNode`. The `${run_id}` expression is *not* evaluated yet.

### One-step construction

The simplest way to resolve a deferred node: call `.construct()` with a context dict.

```python
import dracon

config = dracon.loads("""
output: !deferred "/tmp/${run_id}/results"
""")

# later, when run_id is known:
path = config['output'].construct(context={'run_id': 'abc-123'})
# path == "/tmp/abc-123/results"
```

### Two-step: compose then construct

If you want to inspect the composed tree before constructing, split the process:

```python
from dracon import compose, construct

node = config['output']

# step 1: compose with partial context
composed = compose(node, context={'run_id': 'abc-123'})
# composed is a CompositionResult; you can inspect it

# step 2: construct from the composed result
result = construct(composed)
```

### Type hints

Attach a type to the deferred node so the constructor knows what to build:

```yaml
model: !deferred:MyModel
  name: "${model_name}"
  weights: "${weights_path}"
```

This tells Dracon to construct the resolved subtree as `MyModel`.

### Extended syntax

The `!deferred` tag supports query-parameter-style options after a `::` separator:

```yaml
# drop all inherited context before construction
clean: !deferred::clear_ctx=True
  key: "${injected_value}"

# reroot @path references so they're relative to this subtree
local: !deferred::reroot=true
  ref: "${@/sibling}"
```

You can combine a type hint with options:

```yaml
thing: !deferred::clear_ctx=True:MyModule.MyClass
  param: "${runtime_param}"
```

The format is `!deferred::[options]:[TypeName]`.

### If runtime chooses the constructor, alias it first

Sometimes the deferred branch does not just need runtime values. It needs runtime logic to choose what to build.

The cleanest idiom is usually:

1. compute the constructor with `!define`
2. give it a short local name
3. use that name as a normal tag

```yaml
decision: !deferred
  !define Action: ${llm_decide(prompt='triage', metrics=jobs.meta(group='trials'))}
  !Action {}
```

This is usually clearer than trying to inline the whole choice into a dynamic tag. It also avoids awkward YAML tag syntax once the expression gets long.

### Runtime contracts as interface data

A `DeferredNode` implements the Symbol protocol. Its `interface()` method surfaces the contracts (`!require`, `!assert`) declared inside the deferred branch as structured `InterfaceSpec` data:

```python
node = config['reporting']  # a DeferredNode

iface = node.interface()
# iface.kind == SymbolKind.DEFERRED
# iface.params -- the !require parameters
# iface.contracts -- the !assert contracts
```

This means you can inspect what a deferred section expects before calling `.construct()`. The same data drives:

- error messages when required runtime inputs are missing
- the `--symbols` CLI output
- the `__scope__` introspection API

## Resolvable[T] for Pydantic fields

When you just need one field to stay unresolved, use `Resolvable[T]`. It works through the YAML tag, not the type annotation alone. Tag the YAML value with `!Resolvable[T]` to pause construction on that field:

```python
from dracon import Resolvable
from pydantic import BaseModel

class Pipeline(BaseModel):
    preprocessor: Resolvable[Preprocessor]   # Pydantic accepts Resolvable here
    batch_size: int = 32
```

```yaml
!Pipeline
preprocessor: !Resolvable[Preprocessor]
  tokenizer: "${tokenizer}"
batch_size: 64
```

The `batch_size` resolves immediately. The `preprocessor` stays as a `Resolvable` until you call `.resolve()`:

```python
config = dracon.load('pipeline.yaml', context={'Pipeline': Pipeline, 'Preprocessor': Preprocessor})

# later, when the tokenizer is available:
lazy = config.preprocessor.resolve(context={'tokenizer': my_tokenizer})
prep = lazy.resolve()  # force any remaining lazy interpolations
```

`Resolvable` stores the raw YAML node and the constructor state. It is a snapshot of the construction process that you can resume later with extra context.

A `Resolvable` can be empty-checked with `bool(resolvable)` and copied with `.copy()`.

For most cases, `!deferred` is simpler and more intuitive. Use `Resolvable` when you want the parent model fully constructed and validated, with only specific fields deferred.

## LazyDraconModel

Subclass `LazyDraconModel` instead of `BaseModel` when your model has `${...}` defaults that depend on context not yet available at construction time:

```python
from dracon.lazy import LazyDraconModel

class Experiment(LazyDraconModel):
    name: str
    output_dir: str = "${base_dir}/${name}"
    checkpoint: str = "${output_dir}/checkpoint.pt"
```

Field access triggers resolution. When you do `exp.output_dir`, Dracon evaluates the `${...}` expression at that moment, using whatever context is available on the model.

```python
exp = dracon.loads("""
!Experiment
name: "run-42"
""", context={'base_dir': '/data/experiments'})

print(exp.output_dir)  # /data/experiments/run-42
print(exp.checkpoint)  # /data/experiments/run-42/checkpoint.pt
```

### How it works

- Fields with `${...}` values are stored as `LazyInterpolable` objects instead of being resolved at construction time.
- `LazyDraconModel.__getattribute__` intercepts attribute access and calls `.resolve()` on any `LazyInterpolable` it finds.
- The resolved value replaces the lazy object, so resolution only happens once per field.

### With discriminated unions

If your model has a `Literal` discriminator field (for discriminated unions / subcommands), `LazyDraconModel` automatically excludes it from the lazy validator. No special handling needed on your end.

## Permissive evaluation

Sometimes you have partial context and want to resolve what you can, leaving unknown `${...}` expressions as strings for a later pass.

### Basic permissive mode

```python
from dracon import resolve_all_lazy

config = dracon.loads("""
greeting: "Hello ${name}, welcome to ${place}"
""")

# resolve with partial context:
result = resolve_all_lazy(config, permissive=True,
                          context_override={'name': 'Alice'})
# result['greeting'] == "Hello Alice, welcome to ${place}"
```

The `${name}` part resolved; the `${place}` part stayed as a string because `place` wasn't in context.

### Two-phase resolution

This is useful when different parts of the context become available at different times:

```python
# phase 1: resolve what we know
partial = resolve_all_lazy(config, permissive=True,
                           context_override={'name': 'Alice'})

# phase 2: finish up
final = resolve_all_lazy(partial, permissive=False,
                         context_override={'place': 'Wonderland'})
# final['greeting'] == "Hello Alice, welcome to Wonderland"
```

### Where permissive is available

- `evaluate_expression(..., permissive=True)` - the expression evaluator
- `LazyInterpolable(value, permissive=True)` - individual lazy values
- `resolve_all_lazy(obj, permissive=True)` - recursive resolution
- `dracontainer.resolve_all_lazy(permissive=True)` - on Dracontainer instances

Under the hood, permissive mode uses AST constant folding: it substitutes known variables into the expression, evaluates what it can, and returns the simplified expression string for anything that remains unresolved.
