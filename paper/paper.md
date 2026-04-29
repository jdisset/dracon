---
title: 'Dracon: staged, inspectable configuration and CLI generation for Python research workflows'
tags:
  - Python
  - configuration management
  - YAML
  - CLI generation
  - Pydantic
  - reproducibility
  - research software
authors:
  - name: Jean Disset
    orcid: 0009-0008-7047-2026
    corresponding: true
    affiliation: 1
affiliations:
  - name: Independent researcher
    index: 1
date: 8 April 2026
bibliography: paper.bib
---

# Summary

Dracon is a Python library for building, combining, and inspecting configuration files for research workflows and command-line programs. It extends YAML with a small set of composition features (includes, conditional blocks, loops, reusable templates, pipelines, and dynamic tags) and constructs validated Python objects through Pydantic models [@Pydantic2022]. The same Pydantic schema can also define a standard command-line interface, so the configuration structure, runtime object model, and CLI stay aligned from a single source.

Dracon's main design choice is to treat configuration as a staged artifact instead of a single load step. Files are first composed into an inspectable intermediate tree, then constructed into typed Python objects, while explicitly deferred parts can wait for runtime-only inputs. This staging makes complex configurations easier to inspect, debug, and reproduce in scientific and engineering codebases [@DraconSoftware].

# Statement of need

Research software often accumulates configuration from many places at once: package defaults, local YAML files, command-line overrides, environment variables, and runtime values that only become available once a program is already running. In machine learning and computational biology workflows, this frequently produces a combinatorial file problem. A project with $M$ datasets, $N$ architecture families, and $K$ training presets can easily drift toward $M \times N \times K$ near-duplicate configurations, along with extra wrapper scripts whose only purpose is to derive filenames, route overrides, or fill in runtime-dependent values.

Ad hoc solutions based on nested dictionaries, handwritten `argparse` logic, or environment variables do not scale well in this setting. Final parameter values become hard to audit, configuration logic leaks into application code, and reproducing a run requires reconstructing several layers of implicit behavior. Dracon was developed to address this problem for researchers and engineers who want configuration to remain declarative while still supporting composition, validation, runtime deferral, and command-line use.

The target audience is users building experiment pipelines, data-processing jobs, and configurable Python applications where the final configuration needs to be both flexible and understandable. The practical question behind Dracon is simple: when a final value looks wrong, can the user inspect the composed configuration, see where that value came from, and still postpone the parts that genuinely depend on runtime state?

# State of the field

Hydra [@Yadan2019] is the most widely used Python tool for structured configuration, composition, and interpolation in research workflows. It is built on top of OmegaConf [@OmegaConf2020], which provides the underlying node model and interpolation engine. Together they address important parts of the same problem space and are the main reference points for Dracon. On the CLI side, libraries such as Typer [@Typer] and jsonargparse [@jsonargparse] generate command-line interfaces from typed Python signatures, but they are not by themselves multi-file YAML composition systems. Pydantic itself, and libraries built around it, provide a strong foundation for validation and typed runtime objects, but likewise do not ship an inspectable workflow for layered YAML configuration.

Dracon's contribution is therefore not the introduction of configuration composition to Python. It is a narrower combination of properties that are particularly useful in research workflows: an explicit composition phase that produces an inspectable intermediate representation, optional provenance tracing for final values, delayed construction of runtime-only subtrees, and schema-driven CLI generation from the same Pydantic models used for validation. Dracon is aimed at users who want a smaller, explicit YAML-centric composition model with staged inspection and runtime deferral as first-class features, rather than a broader application framework.

# Software design

Dracon processes configuration in three phases.

In the **composition** phase, raw YAML is parsed as a node graph and rewritten by instructions such as `!define`, `!if`, `!each`, `!fn`, and `!include`. Merge keys fold layers together with configurable strategy. The result is a `CompositionResult`: an inspectable intermediate representation that already reflects includes, merges, and control-flow decisions, but may still contain explicitly deferred subtrees.

In the **construction** phase, the composed tree is converted into Python objects. YAML tags resolve to Python types, mappings are validated through Pydantic V2, and the result becomes the runtime object model used by the application. Because Dracon uses the same Pydantic schemas for both validation and CLI generation, a single schema definition can drive field validation, help text, nested overrides, and subcommands.

In the **resolution and deferral** phase, lazy interpolations may resolve on demand and `!deferred` nodes may be composed and constructed later with extra runtime context. This allows a configuration to remain declarative even when some values depend on objects that do not exist at load time, such as trained models, database handles, experiment trackers, or run-specific identifiers.

A minimal example shows the three phases in one place:

```yaml
# app.yaml
workers: 4
database:
  host: db.${env}.internal
  credentials: !deferred
    password: ${vault.get('db')}
```

```python
# app.py
from pydantic import BaseModel
from dracon import dracon_program

class Database(BaseModel):
    host: str
    credentials: dict

@dracon_program()
class App(BaseModel):
    env: str = "dev"
    workers: int = 1
    database: Database

App.cli()
```

```
$ python app.py +app.yaml --env prod --workers 8
```

The same Pydantic model validates the YAML, produces the CLI, and accepts overrides; `host` resolves during composition; `credentials` waits for a runtime `vault` object supplied to `.construct(context=...)`.

This staged design reflects an explicit trade-off: Dracon favors visible composition steps over hiding configuration behavior inside a one-shot loader. That choice enables features such as `dracon show`, provenance tracing, and mutable `CompositionStack` layer manipulation, all aimed at making configuration behavior inspectable instead of implicit.

Another design choice is what the documentation calls an "open vocabulary": values, types, Python callables, YAML templates, serializable partials, and pipelines can all live in the same scope and can often be selected or invoked through the same mechanisms. This supports higher-level patterns such as layered vocabularies, constructor slots, runtime contracts, and hybrid pipelines without requiring users to define a separate plugin system for each one.

# Use in research

Dracon is in active use in computational biology research workflows, where it composes training, design, plotting, and job-launch configurations across datasets, architecture families, and hyperparameter presets. In these workflows, Dracon supports patterns such as dynamic skeletons, layered vocabularies, weighted registries, runtime contracts, and YAML-defined pipelines. It also serves as the configuration substrate for a related job-orchestration layer (Broodmon) used to launch and manage experiment sweeps, which relies on Dracon's composition and deferral model to describe jobs, edges, and resource pools in a single declarative format.

Use is not limited to toy examples. A current modernization effort applies Dracon to a legacy corpus of more than 1,200 YAML files in an experiment-management stack, with the goal of collapsing duplicated configuration families into a much smaller set of reusable templates, registries, and sweep definitions. That is precisely the class of problem Dracon was designed to address: reducing configuration sprawl while keeping the final topology inspectable and reproducible.

# AI usage disclosure

Generative AI tools were used to assist with documentation and manuscript drafting. The author reviewed, edited, and verified all resulting text and technical claims against the codebase and software behavior before submission.

# Acknowledgements

Dracon builds on Pydantic [@Pydantic2022] for type validation, ruamel.yaml [@ruamel] for YAML parsing with structure preservation, and asteval [@asteval] for expression evaluation.

# References
