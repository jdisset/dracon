# Reference

Syntax and API reference for looking things up.

| Page | What it covers |
|------|----------------|
| [Loader API](loader-api.md) | `DraconLoader` constructor, methods, module-level functions, `CompositionStack`, tracing |
| [CLI API](cli-api.md) | `Arg`, `Subcommand`, `@dracon_program`, `ConfigFile`, `make_callable`, YAML-declared CLI flags |
| [Instruction Tags](instruction-tags.md) | `!define`, `!if`, `!each`, `!fn`, `!pipe`, `!require`, `!assert`, `!include`, `!deferred`, `!unset`, `!noconstruct` |
| [Merge Syntax](merge-syntax.md) | Merge key grammar, dict/list modes, priority, depth, context propagation |
| [Interpolation](interpolation.md) | `${...}` expressions, `@path` references, `&path` copies, built-in functions |
| [KeyPaths](keypaths.md) | Dot-separated paths, root, parent, wildcards, escaping |
| [Locators](locators.md) | Axis + predicate path expressions, `!ref` / `!refs`, locator-keyed cascades, `TreeAdapter` |
| [Include Schemes](include-schemes.md) | `file:`, `pkg:`, `env:`, `var:`, `raw:`, `rawpkg:`, `cascade:`, custom loaders |
| [Progress Events](progress-events.md) | `step`, `use_subscriber`, `each`, `tee`, `min_duration`, `name_filter`, JSONL persistence |
| [dracon CLI](dracon-cli.md) | `dracon show`, `dracon completions`, environment variables |
