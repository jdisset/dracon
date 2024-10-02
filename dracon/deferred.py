## {{{                          --     imports     --
from typing import Optional, Any, List, Dict, Union
from copy import deepcopy
import re
from pydantic import BaseModel
from enum import Enum
from dracon.utils import dict_like, DictLike, ListLike, ftrace
from dracon.composer import (
    CompositionResult,
    walk_node,
    DraconMappingNode,
    DraconSequenceNode,
    IncludeNode,
)
from ruamel.yaml.nodes import Node, ScalarNode

from dracon.keypath import KeyPath, ROOTPATH
from dracon.merge import merged, MergeKey, add_to_context

from dracon.interpolation import evaluate_expression, InterpolableNode
from functools import partial


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                         --     DeferredNode     --


class DeferredNode(ScalarNode):
    # A node that is not yet resolved, just a wrapper to another node
    def __init__(
        self,
        tag,
        value: Node,
        path: KeyPath,
        start_mark=None,
        end_mark=None,
        style=None,
        comment=None,
        anchor=None,
        context=None,
    ):
        ScalarNode.__init__(self, tag, value, start_mark, end_mark, comment=comment, anchor=anchor)
        self.context = context or {}
        self.path = path
        self.loader = None
        self.full_composition = None

    def update_context(self, context):
        add_to_context(context, self)

    def compose(self, **kwargs):
        # rather than composing just this node, we can hold a copy of the entire composition
        # and simply unlock the deferred node when we need to compose it. This way we can
        # have references to other nodes in the entire conf

        assert self.loader
        assert self.full_composition
        assert isinstance(self.path, KeyPath)
        assert isinstance(self.value, Node)

        composition = deepcopy(self.full_composition)
        composition.replace_node_at(self.path, self.value)
        walk_node(
            node=self.path.get_obj(composition.root),
            callback=partial(add_to_context, self.context),
        )
        compres = self.loader.post_process_composed(composition)

        return self.path.get_obj(compres.root)

    def construct(self, **kwargs):
        assert self.loader, "DeferredNode must have a loader to be constructed"
        compres = self.compose(**kwargs)
        return self.loader.load_from_node(compres)

    # def compose(self, **kwargs):
    # if not self.loader:
    # raise ValueError('DeferredNode must have a loader to be composed')

    # print(f'composing deferred node with loader: {self.loader}')
    # print(f'loader saved_reference: {self.loader.referenced_nodes}')

    # if not isinstance(self.value, Node):
    # raise ValueError('DeferredNode must have a Node as value')

    # walk_node(
    # node=self.value,
    # callback=partial(add_to_context, self.context),
    # )

    # compres = CompositionResult(root=self.value)
    # compres = self.loader.post_process_composed(compres)
    # return compres


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                     --     process deferred     --


@ftrace(watch=[])
def process_deferred(comp: CompositionResult, force_deferred_at: List[KeyPath | str] | None = None):
    from dracon.nodes import reset_tag

    force_deferred_at = force_deferred_at or []
    force_deferred_at = [KeyPath(p) if isinstance(p, str) else p for p in force_deferred_at]
    deferred_nodes = []

    def find_deferred_nodes(node: Node, path: KeyPath):
        if node.tag.startswith('!deferred') or path in force_deferred_at:
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
        else:
            assert path in force_deferred_at

        if node.tag == "":
            reset_tag(node)

        new_node = DeferredNode(tag='', value=deepcopy(node), path=path)

        comp.replace_node_at(path, new_node)

    return comp


##────────────────────────────────────────────────────────────────────────────}}}
