# Patterns

Patterns show how Dracon's primitives compose into real-world solutions. They assume you're comfortable with the basics from the [tutorials](../tutorials/01-first-config.md).

Each pattern addresses a specific problem:

- [**Dynamic Skeleton**](dynamic-skeleton.md) - You have M datasets and N configs. Without composition, that's M*N files. With the skeleton pattern, it's M+N.
- [**Config Templates**](config-templates.md) - Repeated config blocks that differ by a few parameters. Parameterize them once, stamp them out.
- [**Sweep Generation**](sweep-generation.md) - Generate experiment grids with `!each` and expressions instead of writing them by hand.
- [**Composition Stack**](composition-stack.md) - Push, pop, and fork config layers at runtime for multi-phase pipelines.
- [**Anti-Patterns**](anti-patterns.md) - Common mistakes and what to do instead.
