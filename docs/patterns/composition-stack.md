# Pattern: Composition Stack

## The problem

`load(["base.yaml", "override.yaml"])` works fine when your layers are fixed at startup. But what if you need to push a runtime patch, try speculative changes, undo a layer, or hot-reload a config file? You need a mutable layer list, not a one-shot merge.

## What CompositionStack is

`CompositionStack` is an ordered, mutable list of config layers. The source of truth is the layer list. The `composed` property is a cached left-fold over those layers: layer 0 is the base, each subsequent layer is merged on top.

The cache is prefix-based. If you have 5 layers cached and push a 6th, only layer 6 needs to be composed. If you pop layer 3, the cache is invalidated from index 3 onward, but layers 0-2 stay cached.

```python
from dracon import DraconLoader, CompositionStack, LayerSpec, LayerScope
```

## Basic API

```python
loader = DraconLoader()

# create a stack from files
stack = loader.stack("base.yaml", "override.yaml")

# or build it incrementally
stack = CompositionStack(loader)
stack.push("base.yaml")
stack.push("override.yaml")

# get the composed result and construct Python objects
config = stack.construct()
```

### push

Append a layer. Returns the index. You can pass a file path string or a `LayerSpec` for more control. Extra keyword arguments become layer context (equivalent to CLI `++key=value` overrides).

```python
stack.push("base.yaml")
stack.push("patch.yaml", debug=True, log_level="DEBUG")
stack.push(LayerSpec(source="ml.yaml", scope=LayerScope.EXPORTS))
```

### pop

Remove a layer by index (default: last). Invalidates the cache from that point onward.

```python
stack.pop()      # remove last layer
stack.pop(1)     # remove layer at index 1
```

### replace

Swap a layer in-place. Useful for hot-reloading a config file without rebuilding the entire stack.

```python
stack.replace(2, "new_override.yaml")
```

### fork

Create an independent copy that shares the cached prefix. Changes to the fork don't affect the original, and vice versa.

```python
branch = stack.fork()
branch.push("experimental.yaml")
# branch has the experimental layer; stack does not
```

### composed / construct

`composed` returns the raw `CompositionResult` (the merged node tree before construction). `construct(**kwargs)` goes one step further and builds Python objects from it.

```python
comp = stack.composed         # CompositionResult
config = stack.construct()    # dict / Pydantic model / Dracontainer
```

## Layer scopes

By default, each layer is isolated: it can't see variables defined in other layers. This matches the behavior of `load([a, b, c])`. But sometimes you want layers to communicate.

### ISOLATED (default)

No variable sharing. Each layer is composed independently, then merged with the accumulated result.

```python
stack.push("base.yaml")                        # defines model=resnet
stack.push("training.yaml")                    # can't see ${model}
```

### EXPORTS

Later layers can see `!define` and `!set_default` variables from earlier layers. Hard/soft priority is preserved: a `!define` from layer 1 beats a `!set_default` from layer 2, and a `!define` from layer 2 beats a `!set_default` from layer 1.

```python
stack.push("base.yaml")                                          # !define model: resnet
stack.push(LayerSpec(source="training.yaml", scope=LayerScope.EXPORTS))  # ${model} resolves to "resnet"
```

Example files:

```yaml
# base.yaml
!define model: resnet
!set_default lr: 0.001
training: true
```

```yaml
# training.yaml
!if ${model == 'resnet'}:
  augmentation: heavy
!if ${model == 'vgg'}:
  augmentation: light
lr_used: ${lr}
```

With the EXPORTS scope, `training.yaml` sees `model=resnet` and `lr=0.001` from `base.yaml`. The result includes `augmentation: heavy` and `lr_used: 0.001`.

### EXPORTS_AND_PREV

Like EXPORTS, but also injects a `PREV` dict containing the full accumulated result from all prior layers. This lets a layer inspect and react to the merged state so far.

```python
stack.push("base.yaml")
stack.push(LayerSpec(source="adapter.yaml", scope=LayerScope.EXPORTS_AND_PREV))
```

```yaml
# adapter.yaml
!if ${len(PREV.get('surfaces', {})) > 2}:
  layout: dense
!if ${len(PREV.get('surfaces', {})) <= 2}:
  layout: spacious

inherited_count: ${len(PREV)}
deep_val: !include var:PREV@level1.level2.secret
```

`PREV` is a plain dict snapshot. Mutating it doesn't affect the cached layers. You can access nested values with `!include var:PREV@dotted.path` or with `${PREV['key']}` expressions.

## Example: runtime patching and A/B testing

```python
loader = DraconLoader()
stack = loader.stack("base.yaml", "model.yaml")

# get the baseline config
baseline = stack.construct()

# push a runtime patch
stack.push("high_lr_patch.yaml")
patched = stack.construct()

# undo the patch
stack.pop()
assert stack.construct() == baseline  # back to baseline

# fork for A/B testing
branch_a = stack.fork()
branch_b = stack.fork()

branch_a.push("experiment_a.yaml")
branch_b.push("experiment_b.yaml")

config_a = branch_a.construct()
config_b = branch_b.construct()

# original stack is untouched
original = stack.construct()
```

The prefix cache makes this efficient. Forking copies the cached results, so `branch_a` and `branch_b` don't recompute the base layers.

## Example: EXPORTS for cross-layer templates

Define templates in one layer, use them in another:

```yaml
# templates.yaml
!define make_url: !fn
  !require host: "hostname"
  !set_default port: 80
  url: https://${host}:${port}
```

```yaml
# endpoints.yaml
api: ${make_url(host='api.example.com', port=443)}
internal: ${make_url(host='internal.local')}
```

```python
stack = CompositionStack(loader)
stack.push("templates.yaml")
stack.push(LayerSpec(source="endpoints.yaml", scope=LayerScope.EXPORTS))
config = stack.construct()
# config["api"]["url"] == "https://api.example.com:443"
# config["internal"]["url"] == "https://internal.local:80"
```

Without `EXPORTS`, `endpoints.yaml` would fail because `make_url` wouldn't be in scope.

## Example: per-layer merge strategy

Each layer can specify its own merge key. Useful when you want different merge behavior for different layers.

```python
stack.push("base.yaml")                                                   # items: [1, 2]
stack.push(LayerSpec(source="extra.yaml", merge_key="<<{<+}[<+]"))       # items: [3] -> [3, 1, 2]
```

The default merge key is `<<{<+}[<~]` (recurse dicts with new-wins priority, replace lists with new-wins priority). You can override it per layer to get list concatenation, existing-wins priority, or any other combination.

## Use cases

- **Runtime config patching**: push a layer, construct, pop it. No file editing.
- **A/B testing**: fork the stack, push different layers to each fork, compare results.
- **Interactive exploration**: in a notebook or REPL, push/pop layers to try different configurations.
- **Hot-reload**: `replace(index, new_file)` swaps a layer without rebuilding the rest.
- **Multi-phase pipelines**: each phase pushes its config layer, inheriting from previous phases via EXPORTS.
