# The Primitives

Dracon has a small set of building blocks. Each one does one thing. The interesting part is how they combine.

## Primitive table

| Primitive | Phase | What it does |
|---|---|---|
| `!include` | Composition | Inject external YAML content into the tree |
| `<<:` | Composition | Merge nodes with strategy control |
| `!define` | Composition | Bind a name in scope (hard, not overridable) |
| `!set_default` | Composition | Bind a name in scope (soft, overridable) |
| `!require` | Composition | Declare a variable must exist |
| `!assert` | Composition | Enforce a boolean condition |
| `!if` | Composition | Conditional inclusion of nodes |
| `!each` | Composition | Iterate and generate nodes |
| `!fn` | Composition | Create a callable YAML template |
| `!pipe` | Composition | Chain callables sequentially |
| `!fn:path` | Construction | Partial-apply a Python function |
| `!deferred` | Construction | Pause a subtree for later construction |
| `${...}` | Resolution | Evaluate a Python expression lazily |
| `@path` | Resolution | Reference a value elsewhere in the tree |
| `&path` | Resolution | Copy a node from elsewhere in the tree |

!!! note
    For the full syntax of each primitive, see the [Instruction Tags](../reference/instruction-tags.md) and [Interpolation](../reference/interpolation.md) reference pages.

---

## The key insight

These primitives are orthogonal. `!define` does not know about `!include`. `!each` does not know about `<<:`. They compose because they all operate on the same thing: the node tree.

This means you can combine them freely. A few patterns show up over and over.

---

## Combination examples

### 1. `!define` + `!each` + `!if` -- conditional sweep

Generate a list of experiments, but only include ones that meet a condition:

```yaml
!define num_layers: 4

experiments:
  !each layer_sizes: [[64, 128], [128, 256], [256, 512]]
  !if ${len(layer_sizes) <= num_layers}:
    name: exp_${layer_sizes[0]}
    layers: ${layer_sizes}
```

`!define` sets a variable. `!each` iterates over a list, producing one child node per item. `!if` filters based on an expression that can reference both the `!each` variable and the `!define` variable.

### 2. `!fn` + `!include` + `<<:` -- parameterized templates

A vocabulary file defines a reusable template. Callers include it and override specific fields:

```yaml
# model_template.yaml
!set_default hidden_size: 256
!set_default num_heads: 8

architecture:
  hidden: ${hidden_size}
  heads: ${num_heads}
  ff_dim: ${hidden_size * 4}
```

```yaml
# config.yaml
!define hidden_size: 512
!define num_heads: 16

<<: !include file:model_template.yaml
training:
  lr: 0.001
```

The template uses `!set_default` for its parameters. The caller uses `!define` to override them. Because hard values beat soft values during merging, the caller's values win. See [Context and Scope](context-and-scope.md) for the full priority story.

### 3. `!define` + `!fn` + `!pipe` -- processing pipeline

Define reusable transforms and chain them:

```yaml
!define normalize: !fn
  !require input
  result: ${input.strip().lower()}
  !fn result: ${result}

!define prefix: !fn
  !require input
  !set_default tag: "v"
  !fn result: ${tag + "_" + input}

!define process: !pipe
  - ${normalize}
  - ${prefix}

output: ${process(input="  Hello World  ", tag="prod")}
# -> "prod_hello world"
```

`!fn` creates callable templates. `!pipe` chains them so each stage's output feeds into the next. The whole thing is just YAML.

### 4. `!deferred` + `${...}` + `@path` -- runtime cross-references

A config that adapts at runtime:

```yaml
!deferred:
  !require runtime_env

  database:
    host: ${runtime_env}_db.internal
    pool_size: ${20 if runtime_env == "production" else 5}

  cache:
    backend: redis
    host: $@database.host  # reference the database host
```

The `!deferred` tag pauses composition until `.construct(context={"runtime_env": "production"})` is called. At that point, `${...}` expressions evaluate with the runtime context, and `@path` references resolve against the constructed tree.

---

## The callable spectrum

Dracon has several ways to make things callable, from simple to complex:

| Mechanism | What it is |
|---|---|
| `${expr}` | Inline expression, evaluated in context |
| `!define x: value` | Named constant (not callable, but feeds into expressions) |
| `!fn` (inline body) | YAML template wrapped as a callable |
| `!fn:module.func` | Partial application of a Python function |
| `!pipe` | Chain of callables, output feeds forward |
| `!include` | Structural inclusion (not callable, but parameterizable via `!set_default`) |

The first three live entirely in YAML-land. `!fn:path` bridges to Python. `!pipe` composes any of them. `!include` is the coarsest tool, for pulling in whole config sections.

### `!fn` vs `!fn:path`

These look similar but work differently:

- **`!fn`** creates a `DraconCallable`. Each call deep-copies the template node, injects kwargs as context, and runs the full composition + construction pipeline. The template is YAML.
- **`!fn:path`** creates a `DraconPartial`. It resolves `path` to a Python function and stores the provided kwargs. Each call merges runtime kwargs with stored kwargs and calls the function directly. No YAML involved at call time.

```yaml
# YAML template callable
!define greet: !fn
  !require name
  message: Hello, ${name}!
  !fn result: ${message}

# Python function partial
!define tokenize: !fn:transformers.AutoTokenizer.from_pretrained
  pretrained_model_name_or_path: bert-base-uncased
```

---

## How primitives interact with phases

One thing worth internalizing: composition primitives run before construction primitives, always. This means:

- `!define` values are available to `!if` and `!each` conditions during composition
- But they are also available to `${...}` expressions during construction/resolution
- `!fn` templates are created during composition, but their bodies are composed + constructed on each call
- `!deferred` nodes are identified during composition, but their contents are untouched until `.construct()` is called at runtime

The phase boundary is the `CompositionResult`. Everything before it is tree manipulation. Everything after it is object creation. This is covered in detail in [The Three Phases](lifecycle.md).
