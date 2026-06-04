---
title: 'Dracon: composable configuration and command-line interface generation for Python research workflows'
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

I present Dracon, a Python library for composing configuration files and generating command-line programs for research workflows. It works on top of YAML and adds several capabilities that plain YAML does not provide on its own once a project grows: a way to merge layered files with fine-grained control over how nested structures combine, includes that can pull from local paths, installed packages, or environment variables, the ability to compute values with ordinary Python expressions, and user-defined tags and templates so that a project can build up its own declarative vocabulary instead of copying YAML around. Configuration values turn directly into validated Python objects through Pydantic models [@Pydantic2022], and because the same Pydantic schema also describes a command-line interface, one typed definition yields both the runtime objects and a complete CLI with flags, subcommands, and layered config files.

Underneath, Dracon keeps composition and construction as separate steps: a set of layered files is first assembled into an intermediate tree that can be inspected on its own, and only afterwards turned into typed objects, with any part that depends on runtime-only values left as an explicitly deferred subtree to be constructed later [@DraconSoftware].

# Statement of need

Research software and experiments tend to accumulate configuration from several places at the same time, including package defaults, local YAML files, command-line overrides, environment variables, and values that only become available once a program is already running. In machine learning and computational biology in particular this often produces a combinatorial file problem, where a project with $M$ datasets, $N$ architecture families, and $K$ training presets drifts toward something close to $M \times N \times K$ near-duplicate files, usually together with small wrapper scripts whose only real job is to derive file names, route overrides, or stitch several layers together.

I wrote Dracon while running into the limits of existing configuration tools on exactly this kind of project. I wanted to layer and merge files with precise control over how nested structures combine, to pull defaults from installed packages as easily as from local files, to define reusable declarative building blocks instead of copying YAML around, to construct and round-trip real typed Python objects rather than untyped dictionaries, and to get a proper command-line interface out of the same definitions without hand-writing argument parsers. No single tool I tried covered that whole range, so configuration logic kept leaking into application code and earlier runs became hard to reproduce. Dracon is aimed at researchers and engineers who want all of that to stay declarative and composable, so that the full configuration behind a run stays auditable and reproducible, while still being able to postpone the parts that genuinely depend on runtime state.

# State of the field

Hydra [@Yadan2019] is probably the most widely used Python tool for structured configuration in research workflows, and it builds its output by processing a defaults list on top of OmegaConf [@OmegaConf2020]. That model is powerful but rests on several interacting concepts, including defaults lists, `_self_` ordering, config groups, and package directives, which together carry a fairly steep learning curve, and OmegaConf provides variable references without an expression engine, so even simple arithmetic inside an interpolation needs a custom resolver. Dracon covers the same composition ground with two primitives, a merge operator and an include directive, and allows ordinary Python expressions anywhere inside `${...}`. On the command-line side, Hydra takes over argument parsing with its own grammar and does not expose standard flags, short options, positionals, or subcommands, whereas tools such as Typer [@Typer] and jsonargparse [@jsonargparse] generate conventional interfaces from typed signatures but are not themselves multi-file YAML composition systems. Hydra is also limited to dataclass-based schemas and hands back wrapper objects rather than the user's own types, which is why third-party libraries exist to bridge it to Pydantic.

Dracon's contribution is mostly that these properties come together in a single tool: one Pydantic V2 [@Pydantic2022] schema validates the configuration, constructs the real typed objects, and generates a conventional CLI, on a composition layer with expressive merging, includes from local files and installed packages, conditionals and loops, and user-defined tags and templates that let a project extend the configuration language itself. I built it for users who would rather have a small and explicit YAML-centric model with that range of composition than a larger application framework.

# Software design

Dracon processes a configuration in three phases.

In the composition phase, the layered YAML is assembled into a single node tree. A merge operator combines mappings and lists with explicit control over strategy, priority, list handling, and the target subtree, so an override can be deep or shallow and can be aimed at any path rather than only the document root. Include directives pull in other files by several schemes, from local paths and installed-package resources to environment variables and in-memory values, which is what lets package-shipped defaults and local overrides sit side by side. Composition-time instructions such as `!define`, `!set_default`, `!if`, and `!each` add variables, conditionals, and iteration, and `!fn` templates let a project define its own tags so that a recurring structure becomes a short declarative call rather than repeated boilerplate. Ordinary Python expressions are available inside `${...}` throughout.

In the construction phase, the assembled tree becomes Python objects. YAML tags resolve to Python types and any value can construct a validated instance through Pydantic V2, so a configuration populates real typed objects instead of untyped dictionaries, and `dracon.dump` runs the same path in reverse to serialize objects back to tagged YAML. Because the schema used for validation is also the schema used for the command line, one typed definition yields a complete CLI with flags, short options, nested overrides, and discriminated-union subcommands, and the same `+file.yaml` layering and `--field value` overrides work on the command line as they do across files.

In the resolution and deferral phase, lazy `${...}` interpolations resolve when they are first accessed, and `!deferred` subtrees can be constructed later with extra runtime context, which lets a configuration stay declarative even when some values depend on objects that do not exist at load time, such as trained models or run-specific identifiers.

A short example brings these together:

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

The same Pydantic model both validates `app.yaml` and produces the command line, so `--workers 8` overrides the value the file supplies, while `env` is a YAML-declared knob that surfaces as `--env` and resolves `host` to `db.prod.internal` once it has a value. The `credentials` entry is the deferred part: it stays unconstructed until it is built later with a runtime `vault` object through `.construct(context=...)`.

Because composition and construction are separate steps, the assembled tree can also be inspected before any objects are built, and a final value can be traced back to the file and layer it came from. Dracon also has what I call an "open vocabulary", where values, types, callables, templates, and pipelines all live in the same scope and can be selected or invoked through the same mechanisms, which is what lets layered vocabularies, constructor slots, and reusable declarative building blocks be expressed without a separate plugin system.

# Research impact

I use Dracon in my own machine learning and computational biology research, where it composes training, design, plotting, and job-launch configurations across datasets, architecture families, and hyperparameter presets, and where it supports patterns such as dynamic skeletons, layered vocabularies, weighted registries, runtime contracts, and YAML-defined pipelines. It is also the configuration substrate for a related job-orchestration layer called Broodmon, which launches and manages experiment sweeps and relies on Dracon's composition and deferral model to describe its jobs, edges, and resource pools in a single declarative format.

# AI usage disclosure

I used generative AI tools to help draft the documentation and this manuscript.

# Acknowledgements

Dracon builds on Pydantic [@Pydantic2022] for type validation, ruamel.yaml [@ruamel] for structure-preserving YAML parsing, and asteval [@asteval] for evaluating expressions.

# References
