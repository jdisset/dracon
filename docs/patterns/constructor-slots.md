# Pattern: Constructor Slots

## The problem

You want the config to choose what gets constructed.

Different model classes. Different task types. Different endpoint builders. Different backends.

The usual alternatives are all a bit annoying:

- `_target_`-style strings
- `!if` ladders
- Python `if/elif` dispatch
- a pile of duplicated blocks that differ only by the constructor

Dracon can do this more directly.

## The pattern

Store constructors in config scope, then select them with a dynamic tag.

```yaml
!define model_types:
  resnet: ResNet
  transformer: Transformer

!set_default model_kind: resnet

model: !$(model_types[model_kind])
  layers: 12
```

If `model_kind` is `resnet`, this behaves like:

```yaml
model: !ResNet
  layers: 12
```

If `model_kind` is `transformer`, the tag resolves to `!Transformer` instead.

That means the body stays normal YAML. Only the constructor slot is dynamic.

## You do not always need a registry or factory mapping

For short internal cases, a plain symbolic tag variable is enough:

```yaml
!set_default tag_value: ResNet

model: !$(tag_value)
  layers: 12
```

There is no factory here and no lookup table. `tag_value` just resolves to the tag name you want.

This is fine when:

- the config author already knows the allowed tags
- you do not mind exposing raw constructor names
- you want the shortest possible form

The mapping form is still useful when you want a safer public interface:

```yaml
!define model_types:
  resnet: ResNet
  transformer: Transformer

!set_default model_kind: resnet

model: !$(model_types[model_kind])
  layers: 12
```

Now the user selects `resnet`, not the raw Python-facing name `ResNet`.

## Why this is nice

The object body stays declarative.

Compare this:

```yaml
model: !$(model_types[model_kind])
  layers: 12
```

to the more expression-heavy alternative:

```yaml
model: ${model_types[model_kind](layers=12)}
```

Both work. The dynamic-tag version is easier to read once the body is more than one or two fields.

## CLI selection

This pattern is especially useful with CLI overrides:

```yaml
!define model_types:
  resnet: ResNet
  transformer: Transformer

!set_default model_kind: resnet
```

Now:

```bash
++model_kind=transformer
```

switches the constructor cleanly.

The important detail is that the CLI is selecting a symbolic key like `transformer`, not trying to inject a raw Python symbol.

## Aliasing the chosen constructor

If you want to reuse the selected constructor several times, alias it once:

```yaml
!define model_types:
  mlp: MLP
  transformer: Transformer

!set_default model_kind: mlp

!define Net: ${model_types[model_kind]}

encoder: !Net { hidden: 256 }
decoder: !Net { hidden: 128 }
```

That keeps the rest of the file stable even if the slot logic changes.

There is another reason to use the alias form: it works well when the selected value is an actual Python type or callable object, not just a tag-name string.

```yaml
!define Tag: ${ResNet}

model: !Tag
  layers: 12
```

So the practical split is:

- `!$(tag_value)` when `tag_value` is a short symbolic tag name
- `!define Tag: ${...}` then `!Tag` when the selected value is an actual object or the selection logic is more complex

## Local tag aliases for more complex choices

The same aliasing move is useful even when you only use the chosen constructor once.

If the tag expression is simple, `!$(...)` is fine:

```yaml
model: !$(model_types[model_kind])
  layers: 12
```

But once the selection logic gets longer, it starts fighting YAML tag syntax.

This is especially true for expressions with spaces, commas, or nested calls. In practice, the cleaner move is usually:

1. compute the constructor once with `!define`
2. give it a short local tag name
3. use that tag normally

```yaml
do: !deferred
  !define Action: ${llm_decide(prompt='triage', metrics=jobs.meta(group='trials'))}
  !Action {}
```

That is easier to read than trying to inline the whole choice into a tag:

```yaml
do: !deferred
  !$(llm_decide(prompt='triage', metrics=jobs.meta(group='trials'))) {}
```

The alias form also gives you a nice place to inspect or override the chosen constructor if needed.

## Local aliases work for plain callables too

You can also promote a callable into a short local tag name before invoking it:

```yaml
!define Decide: ${llm_decide}

decision: !Decide
  prompt: triage
  metrics: ${jobs.meta(group='trials')}
```

This is often the nicest way to call a `!fn:path` value with a larger argument mapping.

## It works for callables too

Constructor slots are not limited to Python types.

The same dynamic-tag pattern works for callable builders:

```yaml
!define endpoint_factories:
  http: make_http_endpoint
  grpc: make_grpc_endpoint

!set_default transport: http

service: !$(endpoint_factories[transport])
  name: api
  port: 443
```

That gives you swappable construction behavior without writing a dispatch function in Python.

## Good use cases

- selecting model classes
- selecting task or job schemas
- choosing transport-specific builders
- switching between implementations in tests vs production
- parameterizing reusable vocabularies

## Related pages

- [The Open Vocabulary](../concepts/open-vocabulary.md)
- [Layered Vocabularies](layered-vocabularies.md)
- [Hybrid Pipelines](hybrid-pipelines.md)
