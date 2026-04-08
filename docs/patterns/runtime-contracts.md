# Pattern: Runtime Contracts

## The problem

Some parts of a config only make sense once the program is already running.

- a run ID that does not exist yet
- a trained model object
- a database connection
- a list of files discovered at runtime

The usual fallback is to move that logic into Python. The config stops being the source of truth, and the runtime boundary turns into hand-written glue.

Dracon gives you a cleaner option: keep the runtime boundary in YAML, and make that boundary explicit.

## The pattern

Use `!deferred` to pause a subtree, then declare its runtime interface with `!require` and `!assert`.

```yaml
reporting: !deferred
  !require run_id: "runtime run identifier"
  !require model: "trained model object"
  !assert ${len(run_id) > 0}: "run_id must not be empty"

  output_dir: "/runs/${run_id}"
  summary:
    model_name: ${model.name}
    path: "/runs/${run_id}/summary.json"
```

At load time, `reporting` stays as a `DeferredNode`. Nothing inside it is composed or constructed yet.

Later, when the runtime values exist:

```python
reporting = config["reporting"].construct(
    context={"run_id": run_id, "model": trained_model},
)
```

Now the deferred subtree is composed and constructed with the runtime context you passed in.

## Why this is better than Python glue

The main win is not just "late evaluation". The main win is that the config itself says:

- what runtime values it expects
- what conditions must hold
- what gets built once those values exist

That makes the runtime boundary inspectable and testable.

Without this pattern, it is easy to end up with Python code that quietly does:

- string formatting
- ad hoc validation
- object wiring
- path conventions

all outside the config system.

With runtime contracts, the Python side just supplies the live values and calls `.construct(...)`.

## A typed version

If the deferred subtree should build a typed object, tag it with the final type:

```yaml
job: !deferred:JobConfig
  !require worker_names: "list of workers"
  !require use_gpu: "runtime GPU flag"

  workers:
    !each(name) ${worker_names}:
      - !Worker
        name: ${name}
        gpu: ${use_gpu}

  total: ${len(worker_names)}
```

When you construct that node, Dracon builds a `JobConfig`, not just a plain mapping.

## Common use cases

- runtime-only output paths and artifact trees
- logger and tracker configuration
- report generation
- deployment fragments that need live credentials
- object graphs that depend on runtime resources

## A good rule of thumb

If a subtree depends on values that do not exist yet, keep that subtree declarative and wrap it in `!deferred`.

If it only needs ordinary composition-time values, do not defer it. Use normal `!define`, `!if`, `!each`, and interpolation instead.

## Related pages

- [Deferred Execution](../guides/deferred-execution.md)
- [The Three Phases](../concepts/lifecycle.md)
- [The Open Vocabulary](../concepts/open-vocabulary.md)
