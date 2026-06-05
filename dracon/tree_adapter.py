# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable

from dracon.keypath import KeyPath, KeyPathToken, ROOTPATH
from dracon.utils import dict_like, list_like


@runtime_checkable
class TreeAdapter(Protocol):
    def parent(self, node: Any) -> Any | None: ...
    def children(self, node: Any) -> Sequence[Any]: ...
    def type_names(self, node: Any) -> Sequence[str]: ...  # nearest-first (key / MRO / tag chain)
    def attr(self, node: Any, name: str) -> Any: ...  # single field/key, None if absent


def descend_value(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    name = str(name)
    if name.isdigit() and list_like(obj):
        idx = int(name)
        return obj[idx] if 0 <= idx < len(obj) else None
    if dict_like(obj):
        return obj[name] if name in obj else None
    return getattr(obj, name, None)


# dracon's constructed objects carry no parent back-pointer, so the handle carries its
# keypath; parent() truncates + re-descends from the root (same trick `@` uses).
@dataclass(frozen=True)
class PathNode:
    value: Any = field(compare=False)
    path: KeyPath = field(compare=True)
    root: Any = field(compare=False)


def node_root(value: Any) -> PathNode:
    return PathNode(value, ROOTPATH, value)


def _is_root_path(path: KeyPath) -> bool:
    parts = path.simplified().parts
    return not parts or (len(parts) == 1 and parts[0] == KeyPathToken.ROOT)


def _path_key(path: KeyPath) -> str | None:
    for part in reversed(path.simplified().parts):
        if isinstance(part, str):
            return part
    return None


class NodeTreeAdapter:
    def parent(self, node: PathNode) -> PathNode | None:
        if _is_root_path(node.path):
            return None
        pp = node.path.parent
        return PathNode(pp.get_obj(node.root), pp, node.root)

    def children(self, node: PathNode) -> Sequence[PathNode]:
        v = node.value
        if dict_like(v):
            return [PathNode(v[k], node.path + str(k), node.root) for k in v.keys()]
        if list_like(v):
            return [PathNode(v[i], node.path + str(i), node.root) for i in range(len(v))]
        return []

    def type_names(self, node: PathNode) -> Sequence[str]:
        names = [c.__name__ for c in type(node.value).__mro__]
        key = _path_key(node.path)
        return [key, *names] if key is not None else names

    def attr(self, node: PathNode, name: str) -> Any:
        return descend_value(node.value, name)
