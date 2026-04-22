# `!if ${expr}:` — multiple `!if` blocks in same sequence break `resolve_all_lazy` on interpolated targets

## Summary

When a sequence contains **two or more** `!if ${expr}:` blocks that each
carry a `target:` mapping with `${...}` interpolations, and the condition
evaluates false at construct time, `resolve_all_lazy` tries to walk a
path like `.../then/0/${not pipe}/then/0/target` and crashes because the
raw interpolation text `${not pipe}` is still present as a path segment
— dracon never pruned or collapsed it.

One `!if` alone does not trigger this. Two or more do.

## Minimal reproduction

```python
# /tmp/dracon_if_bug_min.py
import dracon
from dracon import resolve_all_lazy

YAML = """
!define MakeJob: !fn
  !set_default pipe: false
  !set_default prompt: "hello"
  !fn :
    then:
      - !if ${not pipe}:
          then:
            - target:
                input: ${prompt}
              name: boot
      - !if ${not pipe}:
          then:
            - target:
                input: ${prompt}
              name: first

job_pipe: !MakeJob { pipe: true, prompt: "x" }
"""

out = dracon.DraconLoader().loads(YAML)
resolved = resolve_all_lazy(out, permissive=True)  # crashes
```

### Expected

Both `!if` branches evaluate false. The sequence entries should either
be pruned (compacting the list) or emitted as None/empty and stripped by
`resolve_all_lazy`. Either way, the composed path should never contain
`${not pipe}` as a literal segment.

### Actual

```
AttributeError: Could not get object from path:
  /job_pipe.then.0.${not pipe}.then.0.target
```

The construct phase leaves nodes shaped like
`Mapping({False: Mapping({'then': Sequence([...])})})` — i.e. the
condition key was resolved to `False` but the `!if` node itself was not
collapsed; the child sequence (the `then:` branch) remains, and
`resolve_all_lazy` tries to walk into its `target.input` LazyInterpolable.

## Variant: single `!if` works

```yaml
!fn :
  then:
    - !if ${not pipe}:
        then:
          - target: {input: ${prompt}}
```

With only one `!if`, the node gets collapsed correctly and
`resolve_all_lazy` returns `then: []`. Adding a second `!if` sibling
triggers the bug. The pattern feels like a `!fn` return-value scan
visits the collapsed-but-not-pruned `!if` node only when siblings remain
alive — a pruning pass is skipping entries when the enclosing sequence
still has work to do.

## Impact on manoir

This is the root cause of **four pre-existing test failures** in the
manoir repo (220 pass / 4 fail baseline):

```
manoir/tests/test_research_campaign_template.py::test_research_campaign_template_composes
manoir/tests/test_research_campaign_template.py::test_research_campaign_template_seed_from_renders
manoir/tests/test_critic_role.py::test_critic_smoke_recipe_dry_run_shape
manoir/tests/test_claim_verifier.py::test_claim_verifier_role_dry_run
```

All four test paths materialize a pipe-mode `!Agent` through
`_compose_raw`, which invokes `resolve_all_lazy`. The `!Agent`
template in `manoir/vocabulary.yaml` (lines ~125-180) has three
sibling `!if ${not pipe}:` clauses (boot / first-pass / continuation).
When `pipe: true` is passed, all three evaluate false, and dracon
emits the crashing path.

The same bug blocks Step 05 Phase 2 (`manoir run +alfred --dry-run`
with `enable_subconscious=true`) and Phase 3 (`manoir run
+mixed-runtime-test --dry-run`).

## Context

- Found during manoir refactor Step 05 (local validation, 2026-04-22).
- Pre-existing: reverting `manoir/` to commit `5216777` (before Steps
  01-04) reproduces the failures.
- Manoir commit `bcb7109` ("add list cleaning for empty dracon if
  branches") papered over an adjacent symptom (empty-dict list entries
  confusing broodmon's shorthand parser). That cleanup runs *after*
  `resolve_all_lazy`, so it cannot rescue this case — the crash is
  inside `resolve_all_lazy` itself.

## Preferred resolution

Inside `resolve_all_lazy` (or the composition pass that handles `!if`
under sequences), prune sequence entries whose `!if` condition evaluated
false. The collapsed `Mapping({False: ...})` shape is the evidence that
evaluation happened; the sibling `then:` subtree should not survive to
construction.

Alternatively: skip lazy-interpolation resolution for any path segment
that contains `${...}`. The current code at
`dracon/lazy.py:324` → `keypath.py:426-430` unconditionally tries to
traverse unresolved path tokens.
