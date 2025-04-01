## {{{                          --     imports     --
from typing import Optional, Any, List, Dict, TypeVar, Generic, Type
import dracon.utils as utils
from dracon.utils import ftrace, deepcopy, ser_debug, node_repr
from dracon.utils import ShallowDict
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
from dracon.merge import add_to_context, merged, MergeKey, reset_context

from functools import partial
from dracon.nodes import make_node
import logging

logger = logging.getLogger(__name__)

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
        value: Node | T,
        path=ROOTPATH,
        obj_type: Optional[Type[T]] = None,
        clear_ctx: Optional[List[str] | bool] = None,
        loader=None,
        context=None,
        comp=None,
        **kwargs,
    ):
        from dracon.loader import DraconLoader

        if not isinstance(value, Node):
            value = make_node(value, **kwargs)

        self._clear_ctx = []

        if isinstance(clear_ctx, str):
            clear_ctx = [clear_ctx]

        if context is None or clear_ctx is True:
            context = ShallowDict()

        if isinstance(clear_ctx, list):
            self._clear_ctx = clear_ctx

        super().__init__(tag='', value=value, context=context, **kwargs)

        self.obj_type = obj_type

        for key in self._clear_ctx:
            if key in self.context:
                del self.context[key]

        if loader is None:
            self._loader = DraconLoader()
        else:
            self._loader = loader

        self.path = path

    def __getstate__(self):
        state = DraconScalarNode.__getstate__(self)
        state['path'] = self.path
        state['context'] = self.context
        state['obj_type'] = self.obj_type
        state['_loader'] = self._loader
        state['_full_composition'] = self._full_composition
        state['_clear_ctx'] = self._clear_ctx
        return state

    def __setstate__(self, state):
        DraconScalarNode.__setstate__(self, state)
        self.path = state['path']
        self.context = state['context']
        self.obj_type = state['obj_type']
        self._loader = state['_loader']
        self._clear_ctx = state['_clear_ctx']
        self._full_composition = state['_full_composition']

    @ftrace(watch=[])
    def update_context(self, context):
        add_to_context(context, self)

    @ftrace(watch=[])
    def compose(
        self,
        context: Optional[Dict[str, Any]] = None,
        deferred_paths: Optional[list[KeyPath | str]] = None,
        use_original_root: bool = False,
    ) -> Node:
        from dracon.loader import DraconLoader

        if self._loader is None:
            self._loader = DraconLoader()

        assert self._loader
        assert self._full_composition

        assert isinstance(self.path, KeyPath)
        assert isinstance(self.value, Node)

        deferred_paths = [KeyPath(p) if isinstance(p, str) else p for p in deferred_paths or []]

        logger.debug(f"Composing deferred node at {self.path}. deferred_paths={deferred_paths}")
        if not use_original_root:
            deferred_paths = [self.path + p[1:] for p in deferred_paths]

        self._loader.deferred_paths = deferred_paths

        composition = self._full_composition
        value = self.value

        ser_debug(context, operation='deepcopy')
        ser_debug(self.context, operation='deepcopy')

        merged_context = merged(self.context, context or {}, MergeKey(raw="{<~}[<~]"))
        merged_context = ShallowDict(merged_context)

        composition.set_at(self.path, value)

        composition.walk_no_path(
            callback=partial(
                add_to_context, self._loader.context, merge_key=MergeKey(raw='{>~}[>~]')
            )
        )

        walk_node(
            node=self.path.get_obj(composition.root),
            callback=partial(reset_context),
        )

        walk_node(
            node=self.path.get_obj(composition.root),
            callback=partial(add_to_context, merged_context, merge_key=MergeKey(raw='{<~}[<~]')),
        )

        compres = self._loader.post_process_composed(composition)

        return self.path.get_obj(compres.root)

    @ftrace(watch=[])
    def construct(self, **kwargs) -> T:  # type: ignore
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

    def copy(self, clear_context=False, reroot=False, deepcopy_composition=True):
        """Create a copy with optional context clearing."""

        value_copy = deepcopy(self.value)
        context = {} if clear_context else self.context.copy()

        new_obj = DeferredNode(
            value=value_copy,
            path=deepcopy(self.path),
            obj_type=self.obj_type,
            start_mark=self.start_mark,
            end_mark=self.end_mark,
            anchor=self.anchor,
            comment=self.comment,
            context=context,
        )
        new_obj._loader = self._loader.copy() if self._loader else None
        if not reroot:
            new_obj._full_composition = self._full_composition
            if deepcopy_composition:
                new_obj._full_composition = deepcopy(new_obj._full_composition)
        else:
            # new_comp = self._full_composition.rerooted(self.path)
            # new_obj._full_composition = new_comp
            # new_obj.path = ROOTPATH
            new_comp = CompositionResult(root=new_obj)
            new_obj._full_composition = new_comp
            new_obj.path = ROOTPATH


        return new_obj


def make_deferred(
    value: Any,
    loader=None,
    context=None,
    comp=None,
    path=ROOTPATH,
    clear_ctx=None,
    reroot=False,
    **kwargs,
) -> DeferredNode:
    from dracon.utils import ShallowDict

    if context is None or clear_ctx is True:
        context = ShallowDict()

    n = DeferredNode(
        value=make_node(value, **kwargs),
        context=context,
        path=path,
        clear_ctx=clear_ctx,
    )

    if comp is None:
        comp = CompositionResult(root=n)
    n._full_composition = comp

    n._loader = loader


    if reroot:
        n.path = ROOTPATH
        n._full_composition = comp.rerooted(n.path)
    else:
        n._full_composition = comp

    return n


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                     --     process deferred     --


def parse_query_params(query_string: str) -> Dict[str, Any]:
    """
    Parse URI-style query parameters into a dictionary with type conversion and list support
    For list values, the key should be repeated with the same name.
    For nested values, the key should be separated by a dot.
    """

    from urllib.parse import parse_qsl

    params = {}
    if not query_string:
        return params

    for key, value in parse_qsl(query_string, keep_blank_values=True):
        if value.lower() == "true":
            value = True
        elif value.lower() == "false":
            value = False
        elif value.lower() == "null" or value.lower() == "none":
            value = None
        else:
            try:
                if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
                    value = int(value)
                else:
                    value = float(value)
            except (ValueError, TypeError):
                pass

        if "." in key:
            parts = key.split(".")
            current = params
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                elif not isinstance(current[part], dict):
                    current[part] = {"_value": current[part]}
                current = current[part]

            last_part = parts[-1]
            if last_part in current:
                if isinstance(current[last_part], list):
                    current[last_part].append(value)
                else:
                    current[last_part] = [current[last_part], value]
            else:
                current[last_part] = value
        elif key in params:
            if isinstance(params[key], list):
                params[key].append(value)
            else:
                params[key] = [params[key], value]
        else:
            params[key] = value

    return params


@ftrace(watch=[])
def process_deferred(comp: CompositionResult, force_deferred_at: List[KeyPath | str] | None = None):
    """
    Wraps in a DeferredNode any node with a tag starting with '!deferred', or in a path that matches any in force_deferred_at
    """

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
        qparams = {}
        if isinstance(node, DeferredNode):
            continue

        node_context = {}
        if hasattr(node, 'context'):
            node_context = node.context

        if node.tag.startswith('!deferred'):
            node.tag = node.tag[len('!deferred') :]
            if node.tag.startswith('::'):
                end = node.tag[2:].find(':')
                if end == -1:
                    query_string = node.tag[2:]
                else:
                    query_string = node.tag[2:end]
                qparams = parse_query_params(query_string)
                node.tag = node.tag[end + 1 :]

            if node.tag.startswith(':'):
                node.tag = '!' + node.tag[1:]
        else:
            assert any(
                p.match(path) for p in force_deferred_at
            ), f"node at path {path} is not deferred"

        if node.tag == "":
            reset_tag(node)

        new_node = make_deferred(
            value=node,
            path=path,
            context=node_context,
            comp=comp,
            **qparams,
        )
        comp.set_at(path, new_node)

    return comp


##────────────────────────────────────────────────────────────────────────────}}}
