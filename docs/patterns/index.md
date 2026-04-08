# Patterns

Patterns show how Dracon's primitives compose into real-world solutions. They assume you're comfortable with the basics from the [tutorials](../tutorials/01-first-config.md).

## Start Here

- [**Runtime Contracts**](runtime-contracts.md) - Keep runtime-only config declarative with `!deferred`, `!require`, and `!assert`.
- [**Constructor Slots**](constructor-slots.md) - Let config choose types and builders with dynamic tags like `!$(...)`.
- [**Layered Vocabularies**](layered-vocabularies.md) - Build a reusable config language in layers with `<<(<):`.
- [**Hybrid Pipelines**](hybrid-pipelines.md) - Compose Python callables, YAML templates, and partials into one pipeline.
- [**Higher-Order Config**](higher-order-config.md) - Use config to manufacture configured callables, not just data.

## More Patterns

- [**Dynamic Skeleton**](dynamic-skeleton.md) - You have M datasets and N configs. Without composition, that's M*N files. With the skeleton pattern, it's M+N.
- [**Weighted Registries**](weighted-registries.md) - Define the full list once, then make variants by turning a few items up, down, or off.
- [**Config Templates**](config-templates.md) - Repeated config blocks that differ by a few parameters. Parameterize them once, stamp them out.
- [**Sweep Generation**](sweep-generation.md) - Generate experiment grids with `!each` and expressions instead of writing them by hand.
- [**Composition Stack**](composition-stack.md) - Push, pop, and fork config layers at runtime for multi-phase pipelines.
- [**Anti-Patterns**](anti-patterns.md) - Common mistakes and what to do instead.
