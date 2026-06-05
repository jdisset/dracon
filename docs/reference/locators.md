# Locators

An axis-aware, predicate-capable path expression evaluated from a frame node over a pluggable tree. A locator is the union of a [KeyPath](keypaths.md)'s *navigation* (root/relative frames, `.` `/` `..` `*` `**`) and a CSS-selector's *predicates* (type + attribute conditions). It has two faces:

- **pull** — `!ref` / `!refs`: one node asks "who do I point at?" and gets the value(s).
- **push** — a locator-keyed cascade: many locators ask "which nodes do I apply to?" and merge a payload into each match.

```python
from dracon import Locator, parse_locator, resolve, resolve_one, matches
```

---

## Grammar

A locator is `frame × (axis, predicate)*`. The frame is where resolution starts; each step moves along an axis and filters by a predicate.

### Axes

| Surface | Axis | Meaning |
|---------|------|---------|
| `.` or `/` between segments | child | descend one level |
| whitespace | descendant | any depth below (in order, not necessarily adjacent) |
| `>` | child | CSS child combinator |
| `~` | sibling | a sibling of the current node |
| `..` or bare `^` | parent | one level up |
| `^[pred]` or `closest(pred)` | ancestor | walk up to the nearest match |
| `*` | child, any | one level, no predicate |
| `**` | descendant, any | any depth, no predicate |
| leading `/` | — | anchor the frame at the document root |

A bare segment with no axis token is a child step. A chunk beginning `**` is a descendant step regardless of the preceding token.

### Predicates

A predicate is an optional type name plus zero or more bracketed attribute conditions. The type name matches against the node's type chain (class MRO names for constructed objects, tag chain for nodes); a bare word is a type match.

| Form | Meaning |
|------|---------|
| `Type` | node whose type chain contains `Type` |
| `[name=value]` | string equality (`str(attr) == value`) |
| `[name!=value]` | inequality |
| `[name=~value]` | case-insensitive equality |
| `[name^=value]` | starts with |
| `[name$=value]` | ends with |
| `[name*=value]` | contains |
| `[name=/regex/ism]` | regex search (`i`/`s`/`m` flags optional) |
| `[name<n]` `[<=]` `[>]` `[>=]` | numeric comparison |
| `[name]` | attribute present and truthy |
| `[!name]` | attribute absent or falsy |
| `[a.b.0=x]` | dotted attribute path (walks fields / dict keys / list indices) |

`value` may be quoted. `none` is a keyword (`[x=none]` matches a `None` attribute). When the attribute is a list / tuple / set, a condition matches if **any** element matches. Conditions stack: `Service[enabled=true][port>8000]`.

---

## Specificity and ambiguity

Each step contributes `(id_count, attr_class_count, type_count)`; a locator's specificity is the sum, compared lexicographically (this is the CSS specificity rule). When a locator matches more than one node and one is expected (`resolve_one`, `!ref`), the winner is the nearest by tree distance, then the lowest `(skipped_ancestors, mro_distance)` inexactness. A genuine tie logs a warning and returns the first.

---

## Pull: `!ref` / `!refs`

| Tag | Returns |
|-----|---------|
| `!ref LOCATOR` | the single best match; errors if nothing matches |
| `!ref? LOCATOR` | the single best match, or `None` if nothing matches |
| `!refs LOCATOR` | the list of matches (possibly empty) |
| `!refs? LOCATOR` | alias of `!refs` (already total) |

`!ref` lowers to the same lazy, post-construction machinery as `@`, so predicates read **constructed** values (even ones computed in `model_post_init`) and resolution runs over the merged tree (unlike `&` anchors, which copy a raw node at compose time).

```yaml
# nearest-enclosing reference — impossible with root+positional @
services:
  api:
    kind: Service               # a discriminator field the predicate reads
    version: 2.3
    endpoints:
      health:
        on: !ref ^[kind=Service].version    # my enclosing Service, however deep

# sibling, define-once (survives !include merges, unlike &anchors)
database:
  primary: { host: db1, port: 5432 }
  replica: { host: db2, port: !ref ^.primary.port }   # no predicate, so flow style is fine

# predicate fan-out — truthy filter (see the boolean note below)
services:
  api:    { enabled: true,  port: 8080 }
  worker: { enabled: false, port: 8081 }
  cron:   { enabled: true,  port: 8082 }
monitoring:
  scrape: !refs /services.*[enabled].port    # [8080, 8082]

# insertion-robust pipeline — reference by identity, not index
pipeline:
  - id: load
    out: raw
  - id: clean
    in: !ref ^.*[id=load].out    # block style: a [..] predicate can't sit inside flow {}
```

> **Block style for predicates.** A `[...]` predicate uses brackets, which YAML flow style (`{ ... }`) cannot hold. Put a predicate-bearing `!ref` in block style, or quote the whole locator. A bracket-free ref (`^.primary.port`) is fine in flow.
>
> **Booleans — no `=true` / `=false`.** `[enabled=true]` does **not** match: it compares the string `true` against `str(True)` == `True` (and `=false` fails the same way). Select on truthiness instead:
> - `[enabled]` — truthy (excludes `enabled: false`)
> - `[!enabled]` — its complement: falsy **or** absent (a missing key counts as disabled)
> - `[enabled=~false]` / `[enabled=~true]` — strictly the value `false` / `true`, present only (`=~` is a case-insensitive string compare)
>
> **`[type=X]` is a field condition**, not a type test: it matches a node whose attribute literally named `type` equals `X`. To match by the node's *type* (class MRO / tag, or key for dracon's node tree), use a bare type-name step, e.g. `closest(Service)` or `Service > …`.

---

## Push: locator-keyed cascade

A select-mode [`!cascade`](instruction-tags.md) keyed on locators. `make_locator_cascade_strategy` turns any `TreeAdapter` into a dialect; `compose_nested_locators` is the SSOT for "nesting == descendant combinator".

```python
from dracon import make_locator_cascade_strategy, register_cascade_strategy
register_cascade_strategy(make_locator_cascade_strategy("style", adapter=my_adapter))
```

A built-in `!cascade:select` over the node tree ships for non-domain consumers.

```yaml
rules: !cascade:select
  PlotPanel: { dpi: 300 }            # type (MRO) match
  "A > B":   { ... }                 # child combinator
  A:                                 # nesting == descendant; deep-merges via <<{+<}:
    B: { ... }                       # => "A B"
    "&[k=v]": { ... }                # => "A[k=v]" (self-qualify)
```

Nested keys compose onto their parent with the descendant axis by default; a leading `>` / `~` / `&` switches to child / sibling / self-qualify. Because rules stay plain mappings, `<<{+<}:` still deep-merges two cascades.

---

## TreeAdapter

The locator engine is tree-agnostic. The only tree-specific surface is a four-method adapter; the grammar, evaluator, and specificity never touch the concrete tree.

```python
from typing import Any, Protocol, Sequence

class TreeAdapter(Protocol):
    def parent(self, node: Any) -> Any | None: ...
    def children(self, node: Any) -> Sequence[Any]: ...
    def type_names(self, node: Any) -> Sequence[str]: ...   # nearest-first (MRO / tag chain)
    def attr(self, node: Any, name: str) -> Any: ...         # single field/key; None if absent
```

Dracon ships `NodeTreeAdapter` over its own constructed dict/list trees (its node handle, `PathNode`, carries the keypath since constructed objects have no parent back-pointer). Downstream trees (e.g. a live UI component graph) implement the same four methods and reuse the entire engine.

---

## API

| Symbol | Purpose |
|--------|---------|
| `parse_locator(text) -> Locator` | compile a locator string |
| `resolve(frame, loc, adapter) -> list` | all matches, forward from `frame` |
| `resolve_one(frame, loc, adapter) -> Any \| None` | best single match; logs on tie |
| `matches(node, loc, adapter) -> bool` | does `node` satisfy the locator (relative ancestor-chain test) |
| `get_inexactness(node, loc, adapter)` | `(skip, mro)` ambiguity tiebreak |
| `make_locator_cascade_strategy(name, adapter, *, input_param, parse)` | build a select-mode cascade dialect |
| `compose_nested_locators(body, *, parse)` | flatten a nested locator mapping to `{Locator: leaf}` |
| `TreeAdapter`, `NodeTreeAdapter`, `PathNode` | the tree seam |
