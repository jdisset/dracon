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
  - name: Department of Biological Engineering, Massachusetts Institute of Technology, Cambridge, MA, USA
    index: 1
date: 4 June 2026
bibliography: paper.bib
---

# Summary

I present Dracon, a Python library for building, combining, and inspecting the configuration files that drive research workflows and command-line programs. It works on top of YAML, adding a small number of composition features such as file includes, conditional blocks, loops, reusable templates, and pipelines, and it then turns the composed result into validated Python objects through Pydantic models [@Pydantic2022]. Because the same Pydantic schema can also describe a command-line interface, the structure of the configuration, the runtime objects it produces, and the CLI that drives it are all defined in one place rather than kept in step by hand.

The idea that shapes most of the library is that a configuration is handled as a staged artifact rather than as a single load step. A set of files is first composed into an intermediate tree that can be inspected on its own, and only afterwards is that tree constructed into typed Python objects, with the parts that depend on runtime-only inputs left to be filled in later. In practice this staging is what makes larger configurations easier to inspect, debug, and reproduce, which matters in scientific codebases where a single run can pull values from many different sources at once [@DraconSoftware].

# Statement of need

Research software tends to accumulate configuration from several places at the same time, including package defaults, local YAML files, command-line overrides, environment variables, and values that only become available once a program is already running. In machine learning and computational biology in particular this often produces a combinatorial file problem, where a project with $M$ datasets, $N$ architecture families, and $K$ training presets drifts toward something close to $M \times N \times K$ near-duplicate files, usually together with small wrapper scripts whose only real job is to derive file names, route overrides, or supply values that are not known until runtime.

The usual ad hoc remedies, built on nested dictionaries, hand-written argparse logic, or environment variables, do not hold up well as a project grows, since final values become hard to audit and reproducing an earlier run can mean reconstructing several layers of behavior that were never written down explicitly. I wrote Dracon for researchers and engineers who would like their configuration to stay declarative while still allowing composition, validation, deferral of runtime values, and command-line use. The question that motivated much of the design is an ordinary one: when a final value looks wrong, the user should be able to inspect the composed configuration, see where that value came from, and still leave the genuinely runtime-dependent parts unresolved until they can be filled in.

# State of the field

Hydra [@Yadan2019] is probably the most widely used Python tool for structured configuration, composition, and interpolation in research workflows, and it is built on top of OmegaConf [@OmegaConf2020], which supplies the underlying node model and interpolation engine. Together they cover much of the same problem space, and they are the tools I compare Dracon against most directly. On the command-line side, libraries such as Typer [@Typer] and jsonargparse [@jsonargparse] generate interfaces from typed Python signatures, although on their own they are not multi-file YAML composition systems, and Pydantic and the libraries built around it give a solid foundation for validation and typed objects but do not provide an inspectable workflow for layered YAML configuration.

Configuration composition in Python is not itself new, so what Dracon adds is mostly a particular combination of properties that I have found useful in research workflows: an explicit composition phase that produces an inspectable intermediate representation, optional provenance tracing for final values, delayed construction of runtime-only subtrees, and schema-driven CLI generation from the same Pydantic models already used for validation. I built it for users who would rather have a smaller and more explicit YAML-centric composition model, with staged inspection and runtime deferral as first-class features, than a broader application framework.

# Software design

Dracon processes a configuration in three phases, taken here in the order they run.

In the composition phase, the raw YAML is parsed into a node tree and rewritten according to instructions such as `!define`, `!if`, `!each`, `!fn`, and `!include`, while merge keys fold the layers together using a configurable strategy. The output is a `CompositionResult`, an inspectable intermediate representation that reflects the includes, merges, and control-flow decisions but may still contain subtrees that were explicitly marked to be deferred.

In the construction phase, that tree is turned into Python objects: YAML tags resolve to Python types, mappings are validated through Pydantic V2, and the result becomes the runtime object model the application uses. Because Dracon uses the same Pydantic schemas for both validation and CLI generation, one schema definition can drive field validation, help text, nested overrides, and subcommands at once.

In the resolution and deferral phase, lazy interpolations resolve when they are first accessed, and `!deferred` nodes can be composed and constructed later with additional runtime context, which lets a configuration stay declarative even when some of its values depend on objects that do not exist at load time, such as trained models, database handles, or run-specific identifiers.

The following small example brings the three phases together:

```yaml
# app.yaml
!set_default env: dev
workers: 4
database:
  host: db.${env}.internal
  credentials: !deferred
    password: ${vault.get('db')}
```

```python
# app.py
from pydantic import BaseModel
from dracon import dracon_program, DeferredNode

class Database(BaseModel):
    host: str
    credentials: DeferredNode[dict]

@dracon_program()
class App(BaseModel):
    workers: int = 1
    database: Database

App.cli()
```

```
$ python app.py +app.yaml --env prod --workers 8
```

Here `app.yaml` supplies the `workers` value and `--workers 8` overrides it again at the command line, while `env` is declared in the YAML rather than on the model and surfaces as `--env`, so that `host` resolves to `db.prod.internal` once `env` is known. The `credentials` entry stays a deferred subtree, unresolved until it is constructed later with a runtime `vault` object through `.construct(context=...)`.

I chose to keep the composition steps visible, rather than hide them inside a single load call, because that is what makes features like `dracon show`, provenance tracing, and the mutable `CompositionStack` possible, since each of them depends on there being an inspectable intermediate state. The same scope also holds what I call an "open vocabulary", in which values, types, callables, templates, serializable partials, and pipelines can be selected or invoked through the same mechanisms, which is what supports patterns such as layered vocabularies, constructor slots, runtime contracts, and hybrid pipelines.

# Research impact

I use Dracon in my own computational biology work, where it composes training, design, plotting, and job-launch configurations across datasets, architecture families, and hyperparameter presets, and where it supports patterns such as dynamic skeletons, layered vocabularies, weighted registries, runtime contracts, and YAML-defined pipelines. It is also the configuration substrate for a related job-orchestration layer called Broodmon, which launches and manages experiment sweeps and relies on Dracon's composition and deferral model to describe its jobs, edges, and resource pools in a single declarative format. Beyond these examples, an ongoing modernization effort applies Dracon to a legacy collection of more than 1,200 YAML files in an experiment-management stack, with the aim of collapsing duplicated configuration families into a much smaller set of reusable templates, registries, and sweep definitions.

# AI usage disclosure

I used generative AI tools to help with documentation and with drafting the manuscript, and I reviewed, edited, and checked all of the resulting text and the technical claims against the codebase and the behavior of the software before submission.

# Acknowledgements

Dracon builds on Pydantic [@Pydantic2022] for type validation, ruamel.yaml [@ruamel] for structure-preserving YAML parsing, and asteval [@asteval] for evaluating expressions.

# References
