# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""`!ref` / `!refs` -- the pull face of the locator atom.

`!ref LOCATOR` resolves to a single value (best match on ambiguity, error on
zero unless optional); `!refs LOCATOR` to the (possibly empty) list of matches.

Both lower, at compose time, to a lazy `${...}` call on `dracon_ref` carrying
the same frame `@` uses (`__DRACON__PARENT_PATH` + `__DRACON__CURRENT_ROOT_OBJ`),
so they inherit `@`'s post-construction timing. The parsed `Locator` lives in a
small interned registry and only its integer id (a bare literal, no escaping)
travels in the eval string, so arbitrary predicate text and the node-context
resets of the `+file` CLI path can't lose or corrupt it.
"""

from dataclasses import dataclass

from dracon.locator import Locator, parse_locator

REF_TAGS = frozenset({'!ref', '!ref?', '!refs', '!refs?'})


class RefResolutionError(Exception):
    pass


@dataclass(frozen=True)
class RefSpec:
    raw: str
    loc: Locator
    single: bool
    optional: bool


_REF_SPECS: dict[int, RefSpec] = {}
_REF_IDS: dict[tuple[str, bool, bool], int] = {}


def _intern(spec: RefSpec) -> int:
    k = (spec.raw, spec.single, spec.optional)
    i = _REF_IDS.get(k)
    if i is None:
        i = len(_REF_SPECS)
        _REF_SPECS[i] = spec
        _REF_IDS[k] = i
    return i


def _value(node):
    # raw enumeration leaves leaf lazies unresolved; fetch the matched value
    # through the resolving path so the ref yields a concrete value.
    from dracon.lazy import LazyInterpolable

    return node.path.get_obj(node.root) if isinstance(node.value, LazyInterpolable) else node.value


def dracon_ref(ref_id: int, parent_path, root_obj):
    from dracon.locator import resolve, resolve_one
    from dracon.tree_adapter import NodeTreeAdapter, PathNode

    spec = _REF_SPECS[ref_id]
    adapter = NodeTreeAdapter()
    frame = PathNode(parent_path.get_obj(root_obj), parent_path, root_obj)
    if not spec.single:
        return [_value(n) for n in resolve(frame, spec.loc, adapter)]
    found = resolve_one(frame, spec.loc, adapter)
    if found is None:
        if spec.optional:
            return None
        raise RefResolutionError(f"!ref matched no node for locator {spec.raw!r}")
    return _value(found)


def lower_ref_node(node):
    from dracon.interpolation import InterpolableNode
    from dracon.interpolation_utils import outermost_interpolation_exprs

    raw = str(node.value).strip()
    single = node.tag in ('!ref', '!ref?')
    spec = RefSpec(raw=raw, loc=parse_locator(raw), single=single, optional=node.tag.endswith('?'))
    expr = f"${{__dracon_ref({_intern(spec)}, __DRACON__PARENT_PATH, __DRACON__CURRENT_ROOT_OBJ)}}"
    return InterpolableNode(
        value=expr,
        start_mark=node.start_mark,
        end_mark=node.end_mark,
        tag='tag:yaml.org,2002:str',
        anchor=node.anchor,
        comment=node.comment,
        init_outermost_interpolations=outermost_interpolation_exprs(expr),
    )
