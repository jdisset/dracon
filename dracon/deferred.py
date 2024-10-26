## {{{                          --     imports     --
from typing import Optional, Any, List, Dict, Union, TypeVar, Generic, Type
import re
from pydantic import BaseModel
from enum import Enum
from dracon.utils import dict_like, DictLike, ListLike, ftrace, deepcopy
from dracon.composer import (
    CompositionResult,
    walk_node,
    DraconMappingNode,
    DraconSequenceNode,
    IncludeNode,
)
from ruamel.yaml.nodes import Node, ScalarNode
from dracon.nodes import DraconScalarNode

from dracon.keypath import KeyPath, ROOTPATH
from dracon.merge import merged, MergeKey, add_to_context

from dracon.interpolation import evaluate_expression, InterpolableNode
from functools import partial


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                         --     DeferredNode     --


T = TypeVar('T')


class DeferredNode(DraconScalarNode, Generic[T]):
    def __init__(
        self,
        value: Node,
        path: KeyPath,
        context: Optional[Dict[str, Any]] = None,
        obj_type: Optional[Type[T]] = None,
        **kwargs,
    ):
        super().__init__(tag='', value=value, **kwargs)

        self.path = path
        self.context = context or {}
        self.obj_type = obj_type

        from dracon.loader import DraconLoader

        self._loader: Optional[DraconLoader] = None
        self._full_composition: Optional[CompositionResult] = None

    def update_context(self, context):
        add_to_context(context, self)

    def compose(
        self,
        context: Optional[Dict[str, Any]] = None,
        deferred_paths: Optional[list[KeyPath | str]] = None,
    ) -> Node:
        # rather than composing just this node, we can hold a copy of the entire composition
        # and simply unlock the deferred node when we need to compose it. This way we can
        # have references to other nodes in the entire conf

        assert self._loader
        assert self._full_composition
        assert isinstance(self.path, KeyPath)
        assert isinstance(self.value, Node)

        self._loader.update_context(context or {})
        self._loader.deferred_paths = deferred_paths or []

        composition = self._full_composition
        composition.replace_node_at(self.path, self.value)
        walk_node(
            node=self.path.get_obj(composition.root),
            callback=partial(add_to_context, self.context),
        )
        compres = self._loader.post_process_composed(composition)

        return self.path.get_obj(compres.root)

    def construct(self, **kwargs) -> T:  # type: ignore
        assert self._loader, "DeferredNode must have a loader to be constructed"
        compres = self.compose(**kwargs)
        return self._loader.load_node(compres)

    @property
    def keypath_passthrough(self):
        # a deferred node should be transparent (we should be able to traverse it with a keypath)
        # A node that is not yet resolved, just a wrapper to another node
        return self.value

    def dracon_dump_to_node(self, representer) -> Node:
        val = deepcopy(self.value)
        if len(val.tag):
            val.tag = '!deferred:' + val.tag
        else:
            val.tag = '!deferred'
        return val


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                     --     process deferred     --


@ftrace(watch=[])
def process_deferred(comp: CompositionResult, force_deferred_at: List[KeyPath | str] | None = None):
    from dracon.nodes import reset_tag

    force_deferred_at = force_deferred_at or []
    force_deferred_at = [KeyPath(p) if isinstance(p, str) else p for p in force_deferred_at]
    deferred_nodes = []

    def find_deferred_nodes(node, path: KeyPath):
        if (
            not isinstance(node, DeferredNode)
            and node.tag.startswith('!deferred')
            or any(p.match(path) for p in force_deferred_at)  # type: ignore
        ):
            deferred_nodes.append((node, path))

    comp.walk(find_deferred_nodes)
    deferred_nodes = sorted(deferred_nodes, key=lambda x: len(x[1]), reverse=True)

    # filter to only take higher up nodes
    deferred_nodes = [
        (node, path)
        for node, path in deferred_nodes
        if not any((path.startswith(p) and path != p) for _, p in deferred_nodes)
    ]

    for node, path in deferred_nodes:
        if isinstance(node, DeferredNode):
            continue

        if path == ROOTPATH:
            raise ValueError("Cannot use !deferred at the root level")

        if node.tag.startswith('!deferred'):
            node.tag = node.tag[len('!deferred') :]
            if node.tag.startswith(':'):
                node.tag = '!' + node.tag[1:]
        else:
            assert any(
                p.match(path) for p in force_deferred_at
            ), f"node at path {path} is not deferred"

        if node.tag == "":
            reset_tag(node)

        new_node = DeferredNode(value=node, path=path)

        comp.replace_node_at(path, new_node)

    return comp


##────────────────────────────────────────────────────────────────────────────}}}
