# Dracon and Broodmon

Dracon handles configuration composition, type-safe construction, and CLI generation. It stops there. It doesn't run jobs, manage processes, or coordinate parallel execution.

[Broodmon](https://github.com/jdisset/broodmon) picks up where Dracon leaves off. It's a PTY-based job manager built on top of Dracon's config system: parallel execution, dependency edges, supervisor protocols, resource-aware scheduling, and inter-process communication.

The two tools share a config format and compose naturally. Dracon generates the configs; Broodmon runs them.

## The boundary

| Concern | Tool |
|---------|------|
| Config composition, merging, includes | Dracon |
| Type-safe CLI generation | Dracon |
| `!define`, `!if`, `!each`, `!fn`, `!pipe` | Dracon |
| Deferred construction, lazy evaluation | Dracon |
| Parallel job execution | Broodmon |
| PTY management, output capture | Broodmon |
| Dependency edges, reactive rules | Broodmon |
| Supervisor protocols (ask/tell loops) | Broodmon |
| Multi-host execution, resource pools | Broodmon |

## How they compose

A Broodmon config file is a Dracon config file. All of Dracon's YAML features work inside it: `!each` for generating job lists, `!if` for conditional jobs, `!fn` for parameterized job templates, `!define` for shared variables.

```yaml
# sweep.yaml -- a Broodmon config using Dracon's !each
!set_default lrs: [0.001, 0.01, 0.1]
!set_default batch_sizes: [16, 32, 64]

parallelism: 4
jobs:
  !each(lr) ${lrs}:
    !each(bs) ${batch_sizes}:
      - name: "lr${lr}-bs${bs}"
        run: "python train.py --lr ${lr} --batch-size ${bs}"
        group: sweep
```

```bash
# Dracon generates the job list; Broodmon runs them
broodmon +sweep.yaml

# Override from CLI (Dracon's ++ syntax)
broodmon +sweep.yaml ++lrs="[0.0001, 0.001]" -j 8
```

You can also use `dracon show sweep.yaml -cr` to inspect the expanded config before running it.

## Typical patterns

**Grid sweeps:** Use `!each` to enumerate parameter combinations. Broodmon runs them in parallel with `-j N`. See [Sweep Generation](../patterns/sweep-generation.md).

**Optimization loops:** Broodmon's supervisor protocol implements ask/tell. A Python optimizer proposes parameters; Broodmon runs the trial and feeds results back. Dracon generates the initial config.

**Reactive edges:** Broodmon edges watch job output and trigger actions (kill on OOM, forward metrics, early stopping). The edge definitions use Dracon's interpolation for pattern matching expressions.

**Multi-host execution:** Broodmon distributes jobs across hosts with per-host resource pools. The host and resource configs are Dracon YAML with all the usual composition features.

## When you don't need Broodmon

If you just need to generate configs and run them one at a time, Dracon is enough. Use `dracon show` to expand configs, pipe the output to your runner, or use `@dracon_program` to build a CLI that loads configs and calls your code directly.

Broodmon adds value when you need parallel execution, dependency management, output capture, or coordination between processes.

For more on Broodmon, see its [documentation](https://github.com/jdisset/broodmon).
