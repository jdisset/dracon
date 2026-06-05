# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""The push face of the locator atom: a locator-backed `CascadeStrategy`.

`make_locator_cascade_strategy` turns any `TreeAdapter` into a select-mode
cascade: keys compile to `Locator`s, `matches`/`specificity` route through the
step-1 evaluator, and merge defaults to dracon's `_default_merge`. The adapter
is closed over, so dispatch only supplies the node to test.

`compose_nested_locators` is the SSOT for "nesting == descendant combinator":
it walks a nested mapping and flattens it to `{Locator: leaf}`, composing each
nested key onto its parent (DESCENDANT by default; leading `>`/`~`/`&` change
the relation). This generalizes jeanplot's `parse_jstyle_rule_tree`.
"""

from typing import Any, Callable

from dracon.cascade import CascadeStrategy, register_cascade_strategy
from dracon.locator import Locator, get_inexactness, parse_locator
from dracon.locator import matches as locator_matches
from dracon.tree_adapter import NodeTreeAdapter, TreeAdapter
from dracon.utils import dict_like, raw_items


def default_locator_key_parse(key: Any) -> Locator | None:
    if isinstance(key, Locator):
        return key
    if isinstance(key, str):
        return parse_locator(key)
    return None


def make_locator_cascade_strategy(
    name: str,
    adapter: TreeAdapter,
    *,
    input_param: str = "node",
    parse: Callable[[Any], Locator | None] = default_locator_key_parse,
) -> CascadeStrategy:
    def _matches(loc: Locator, node: Any) -> bool:
        return locator_matches(node, loc, adapter)

    def _specificity(loc: Locator, node: Any) -> tuple:
        skip, mro = get_inexactness(node, loc, adapter)
        return (tuple(loc.specificity), -skip, -mro)

    return CascadeStrategy(
        name=name,
        input_params=(input_param,),
        parse=parse,
        matches=_matches,
        specificity=_specificity,
    )


# ── nested-key composition (nesting == descendant combinator) ────────────────


def _looks_like_locator(key: Any) -> bool:
    if isinstance(key, Locator):
        return True
    if not isinstance(key, str) or not key:
        return False
    head = key.lstrip()
    if not head:
        return False
    first = head[0]
    if first in ('>', '~', '&'):
        return True
    if '.' in key:
        return False
    return first.isupper() or first in ('[', '#', '*')


def _key_str(key: Any) -> str:
    return key if isinstance(key, str) else str(key)


def _join(prefix: str, key: str) -> str:
    k = key.strip()
    if k.startswith('>'):
        return f"{prefix} > {k[1:].strip()}"
    if k.startswith('~'):
        return f"{prefix} ~ {k[1:].strip()}"
    if k.startswith('&'):  # self-qualify: same node, append predicate
        return f"{prefix}{k[1:].strip()}"
    return f"{prefix} {k}"


def compose_nested_locators(
    body: Any, *, parse: Callable[[str], Locator] = parse_locator
) -> dict[Locator, Any]:
    out: dict[Locator, Any] = {}

    def emit(prefix: str, leaf: dict[Any, Any]):
        if not leaf:
            return
        loc = parse(prefix)
        out[loc] = {**out[loc], **leaf} if loc in out else leaf

    def walk(prefix: str, node: Any):
        leaf: dict[Any, Any] = {}
        for key, value in raw_items(node):
            if dict_like(value) and _looks_like_locator(key):
                walk(_join(prefix, _key_str(key)), value)
            else:
                leaf[key] = value
        emit(prefix, leaf)

    for key, decls in raw_items(body):
        if dict_like(decls):
            walk(_key_str(key), decls)
    return out


# generic select dialect over the canonical node-tree adapter, for non-jeanplot
# consumers (`!cascade:select` dispatched with a PathNode `node=...`).
register_cascade_strategy(make_locator_cascade_strategy("select", NodeTreeAdapter()))
