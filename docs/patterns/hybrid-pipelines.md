# Pattern: Hybrid Pipelines

## The problem

Real pipelines rarely live in one place.

Some stages are best expressed as Python functions. Some stages are better as config. Some need a little pre-filled configuration. Some need to be swappable.

The common result is a split brain:

- part of the workflow in Python
- part of it in config
- one more wrapper function to connect the two

Dracon lets you keep the pipeline itself in YAML while still using ordinary Python functions for the stages.

## The pattern

Use `!pipe` to compose stages. A stage can be:

- a Python callable from context
- a `!fn` template
- a `!fn:path` partial
- another pipe

```yaml
!define vit_pipeline: !pipe
  - load_data
  - validate: { minimum: 2 }
  - train_vit

report: ${vit_pipeline(source='s3://raw')}
```

With Python functions like:

```python
def load_data(source):
    return {"records": [1, 2, 3, 4], "source": source}


def validate(records, source, minimum=0):
    return {"records": [x for x in records if x >= minimum], "source": source}


def train_vit(records, source):
    return {"model": "vit", "count": len(records), "source": source}
```

the pipeline stays fully declared in YAML, while the heavy lifting still happens in normal Python.

## Why this works well

`!pipe` threads outputs into later stages automatically:

- mapping outputs are unpacked into keyword arguments
- non-mapping outputs go into the next stage's remaining required input

That means the pipeline wiring lives in config instead of in hand-written orchestration code.

## Stage families

Once a pipeline is just another callable value, you can keep several of them in the same config:

```yaml
!define pipelines:
  resnet: !pipe
    - load_data
    - validate: { minimum: 2 }
    - train_resnet

  vit: !pipe
    - load_data
    - validate: { minimum: 2 }
    - train_vit

!set_default pipeline_kind: vit

chosen: ${pipelines[pipeline_kind](source='s3://raw')}
```

Now the config is choosing between whole workflow shapes, not just scalar values.

## Mixing YAML and Python stages

You do not have to choose one style.

A pipeline can combine:

- plain Python functions from the loader context
- `!fn` templates for lightweight YAML-side transforms
- `!fn:path` partials for configured Python callables

That is why "hybrid pipeline" is a better description than just "function composition". The point is the mix.

## Good use cases

- ETL and data validation chains
- preprocessing plus model training
- evaluation workflows
- report-generation pipelines
- small orchestration layers around ordinary Python code

## A useful boundary

Keep stage logic in Python when it is real code.

Keep pipeline shape in YAML when what varies is:

- ordering
- pre-filled stage parameters
- which backend or stage family to use

That split tends to stay readable.

## Related pages

- [YAML Functions](../guides/yaml-functions.md)
- [Constructor Slots](constructor-slots.md)
- [The Open Vocabulary](../concepts/open-vocabulary.md)
