## {{{                          --     imports     --
from typing import Optional, Any, List, Dict, TypeVar, Generic, Type
from dracon.utils import ftrace, deepcopy
from dracon.composer import (
    CompositionResult,
    walk_node,
)
from ruamel.yaml.nodes import Node
from dracon.nodes import (
    DraconScalarNode,
    ContextNode,
    context_node_hash,
)


from dracon.keypath import KeyPath, ROOTPATH
from dracon.merge import add_to_context

from functools import partial
from dracon.nodes import make_node


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                         --     DeferredNode     --


T = TypeVar('T')


class DeferredNode(ContextNode, Generic[T]):
    """
    Allows to "pause" the composition of the contained node until construct is called
    All of dracons tree walking functions see this node as a leaf, i.e. it will not
    be traversed further.
    """

    def __init__(
        self,
        value: Node,
        path: Optional[KeyPath] = None,
        obj_type: Optional[Type[T]] = None,
        **kwargs,
    ):
        super().__init__(tag='', value=value, **kwargs)

        self.path = path
        self.obj_type = obj_type

        from dracon.loader import DraconLoader

        self._loader: Optional[DraconLoader] = None
        self._full_composition: Optional[CompositionResult] = None

    def __getstate__(self):
        state = DraconScalarNode.__getstate__(self)
        state['path'] = self.path
        state['context'] = self.context
        state['obj_type'] = self.obj_type
        state['_loader'] = self._loader
        state['_full_composition'] = self._full_composition
        return state

    def __setstate__(self, state):
        DraconScalarNode.__setstate__(self, state)
        self.path = state['path']
        self.context = state['context']
        self.obj_type = state['obj_type']
        self._loader = state['_loader']
        self._full_composition = state['_full_composition']

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

        print(
            f"Composing DeferredNode with context: {self.context}, value context: {getattr(self.value, 'context', None)}"
        )
        assert self._loader
        assert self._full_composition
        assert isinstance(self.path, KeyPath)
        assert isinstance(self.value, Node)

        self._loader.update_context(context or {})
        self._loader.deferred_paths = deferred_paths or []

        composition = self._full_composition

        composition.set_at(self.path, self.value)
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

    def __hash__(self):
        return context_node_hash(self)

    def __deepcopy__(self, memo):
        new_obj = DeferredNode(
            value=deepcopy(self.value, memo),
            path=deepcopy(self.path, memo),
            obj_type=self.obj_type,
            start_mark=self.start_mark,
            end_mark=self.end_mark,
            anchor=self.anchor,
            comment=self.comment,
            context=self.context.copy(),
        )
        return new_obj


def make_deferred(value: Any, loader=None, **kwargs) -> DeferredNode:
    from dracon.loader import DraconLoader

    if loader is None:
        loader = DraconLoader()

    n = DeferredNode(value=make_node(value, **kwargs))
    comp = CompositionResult(root=n)

    n.path = ROOTPATH
    n._loader = loader
    n._full_composition = comp

    return n


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                     --     process deferred     --


@ftrace(watch=[])
def process_deferred(comp: CompositionResult, force_deferred_at: List[KeyPath | str] | None = None):
    """Wraps any node with a tag starting with '!deferred' in a DeferredNode"""

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

    for node, path in deferred_nodes:
        if isinstance(node, DeferredNode):
            continue

        # Get any existing context from the node
        node_context = {}
        if hasattr(node, 'context'):
            node_context = node.context

        # Also capture surrounding context from composition
        comp.walk_no_path(partial(add_to_context, node_context))

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

        print(f"Wrapping node at {path} in DeferredNode. Context: {node_context}")
        new_node = DeferredNode(value=node, context=node_context)
        comp.set_at(path, new_node)

    return comp


##────────────────────────────────────────────────────────────────────────────}}}
