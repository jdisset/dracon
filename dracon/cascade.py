# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""Inherit-mode cascade helper. Built on top of `MergeKey.key_normalize`.

Walks a nested mapping top-down: at each level, for every child mapping whose
normalized key matches one of its ancestors' normalized keys, that ancestor's
contents flow in as a base. Local pins still win because the descent uses a
new-wins merge.
"""

from typing import Callable, Optional, Any
from dracon.utils import dict_like, deepcopy
from dracon.merge import MergeKey, merged


def cascade_inherit(tree: Any, *, key_normalize: Callable[[str], Optional[str]]) -> Any:
    """Apply inherit-mode cascade: ancestor mappings with the same normalized key
    flow into descendant mappings. Returns a new tree, never mutates input."""
    op = MergeKey(raw='<<{+<}[~<]', key_normalize=key_normalize)
    return _recurse(deepcopy(tree), ancestors={}, op=op, norm=key_normalize)


def _norm_str(key, norm):
    return norm(key) if isinstance(key, str) else None


def _project(d, exclude_norm, norm):
    """Recursively strip same-norm children to break self-cycles on inheritance."""
    out = {}
    for k, v in d.items():
        if _norm_str(k, norm) == exclude_norm:
            continue
        out[k] = _project(v, exclude_norm, norm) if dict_like(v) else v
    return out


def _recurse(node, ancestors: dict, op: MergeKey, norm) -> Any:
    if not dict_like(node):
        return node

    # siblings: descendants inherit from same-level mappings too
    siblings = {nk: node[k] for k in node.keys() if dict_like(node[k])
                and (nk := _norm_str(k, norm)) is not None}

    out = type(node)() if hasattr(node, 'copy') else {}
    for k, v in node.items():
        nk = _norm_str(k, norm)
        if dict_like(v):
            scope = {**ancestors, **siblings}
            if nk is not None and nk in ancestors:
                v = merged(_project(ancestors[nk], nk, norm), v, op)
                # consumed: descendants don't re-merge against same-norm ancestor
                scope.pop(nk, None)
            elif nk is not None:
                scope[nk] = v
            v = _recurse(v, scope, op, norm)
        out[k] = v
    return out
