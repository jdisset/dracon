## {{{                          --     imports     --
from ruamel.yaml import YAML, Node
from typing import Type, Callable
import os
import re
from pathlib import Path
from typing import Optional, Dict, Any, Annotated, TypeVar
from pydantic import BeforeValidator, Field, PlainSerializer
from dracon.composer import (
    IncludeNode,
    CompositionResult,
    DraconComposer,
    delete_unset_nodes,
    walk_node,
)
from dracon.draconstructor import Draconstructor
from dracon.keypath import KeyPath, ROOTPATH
from dracon.utils import (
    DictLike,
    MetadataDictLike,
    ListLike,
    ShallowDict,
    ftrace,
    deepcopy,
)
from dracon.interpolation_utils import resolve_interpolable_variables
from dracon.interpolation import InterpolableNode
from dracon.merge import process_merges, add_to_context, merged, MergeKey
from dracon.instructions import process_instructions
from dracon.loaders.file import read_from_file
from dracon.loaders.pkg import read_from_pkg
from dracon.deferred import DeferredNode, process_deferred
from dracon.loaders.env import read_from_env
from dracon.representer import DraconRepresenter
from dracon import dracontainer
from functools import partial


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                       --     DraconLoader     --

DEFAULT_LOADERS: Dict[str, Callable] = {
    'file': read_from_file,
    'pkg': read_from_pkg,
    'env': read_from_env,
}


DEFAULT_CONTEXT = {
    # some SAFE os functions (not all of them are safe)
    # need no side effects, and no access to the filesystem
    'getenv': os.getenv,
    'getcwd': os.getcwd,
}


def dillcopy(obj):
    import dill

    return dill.loads(dill.dumps(obj))


@ftrace()
def construct(node_or_val, **kwargs):
    try:
        if isinstance(node_or_val, Node):
            loader = DraconLoader(**kwargs)
            compres = CompositionResult(root=deepcopy(node_or_val))
            return loader.load_composition_result(compres, post_process=True)
    except Exception as e:
        # give much more context to the error, since this usually happens inside an asteval eval
        import traceback

        msg = f'Error while constructing node: {e}\n{traceback.format_exc()}'
        raise ValueError(msg)

    return node_or_val


class DraconLoader:
    def __init__(
        self,
        custom_loaders: Optional[Dict[str, Callable]] = None,
        capture_globals: bool = True,
        base_dict_type: Type[DictLike] = dracontainer.Mapping,
        base_list_type: Type[ListLike] = dracontainer.Sequence,
        enable_interpolation: bool = False,
        context: Optional[Dict[str, Any]] = None,
        deferred_paths: Optional[
            list[KeyPath | str]
        ] = None,  # list of paths to nodes that we need to force-defer
    ):
        self.custom_loaders = DEFAULT_LOADERS
        self.custom_loaders.update(custom_loaders or {})
        self._context_arg = context
        self._enable_interpolation = enable_interpolation
        self.referenced_nodes = {}
        self.deferred_paths = deferred_paths or []
        self.deferred_paths = [KeyPath(p) for p in self.deferred_paths]

        self.yaml = YAML()
        self.yaml.Composer = DraconComposer
        self.yaml.Constructor = Draconstructor
        self.yaml.Representer = DraconRepresenter

        self.yaml.composer.interpolation_enabled = enable_interpolation
        self.yaml.constructor.yaml_base_dict_type = base_dict_type
        self.context = ShallowDict(self._context_arg) if self._context_arg else ShallowDict()
        self.reset_context()

    def reset_context(self):
        self.update_context(DEFAULT_CONTEXT)
        self.update_context(
            {
                'construct': partial(  # from node to obj
                    construct,
                    custom_loaders=self.custom_loaders,
                    capture_globals=True,
                    enable_interpolation=self._enable_interpolation,
                    context=self.context,
                )
            }
        )

    def update_context(self, kwargs):
        add_to_context(kwargs, self)

    def copy(self):
        new_loader = DraconLoader(
            custom_loaders=self.custom_loaders,
            capture_globals=False,
            base_dict_type=self.yaml.constructor.yaml_base_dict_type,
            base_list_type=self.yaml.constructor.yaml_base_list_type,
            enable_interpolation=self.yaml.composer.interpolation_enabled,
            context=self.context.copy() if self.context else None,
        )
        new_loader.referenced_nodes = self.referenced_nodes
        new_loader.yaml.constructor.yaml_constructors = self.yaml.constructor.yaml_constructors

        return new_loader

    def __deepcopy__(self, memo):
        return self.copy()

    @ftrace(inputs=False, watch=[])
    def compose_from_include_str(
        self,
        include_str: str,
        include_node_path: KeyPath = ROOTPATH,
        composition_result: Optional[CompositionResult] = None,
        custom_loaders: dict = DEFAULT_LOADERS,
        node: Optional[IncludeNode] = None,
    ) -> Any:
        # TODO [medium priority]:
        # this resolve_interpolable_variables business is hacky and ugly.
        # It's just a find + replace of $VAR with the value of VAR
        # from the loader context (i.e. "./$FILE_STEM.png").
        # It's weirdly independent from the rest of the interpolation system,
        # and not even using the node.context.
        # It's conflicting with the node include syntax (!include $var)
        # which does use the node.context ...
        # Need to clean this up, merge both (probably use comptime interpolation)
        # and make it consistent.

        include_str = resolve_interpolable_variables(include_str, self.context)

        res = None

        try:
            if '@' in include_str:
                # split at the first unescaped @
                mainpath, keypath = re.split(r'(?<!\\)@', include_str, maxsplit=1)
            else:
                mainpath, keypath = include_str, ''

            if composition_result is not None:
                if mainpath.startswith('$'):  # it's an in-memory node
                    if not node:
                        raise ValueError('Node not provided for in-memory include')
                    name = mainpath[1:]
                    if name in node.context:
                        incl_node = node.context[name]
                        incl_node = self.dump_to_node(incl_node)
                        if keypath:
                            incl_node = KeyPath(keypath).get_obj(incl_node)
                        res = CompositionResult(root=incl_node)
                        res.root = deepcopy(res.root)
                        return res

                    raise ValueError(f'Invalid in-memory include: {name} not found')

                # it's a path starting with the root of the document
                if include_str.startswith('/'):
                    res = composition_result.rerooted(KeyPath(mainpath))
                    res.root = deepcopy(res.root)
                    return res

                # it's a path relative to the current node
                if include_str.startswith('@') or include_str.startswith(
                    '.'
                ):  # means relative to parent
                    comb_path = include_node_path.parent.down(KeyPath(mainpath))
                    res = composition_result.rerooted(comb_path)
                    res.root = deepcopy(res.root)
                    return res

                anchors = composition_result.anchor_paths
                if mainpath in anchors:
                    res = composition_result.rerooted(anchors[mainpath] + keypath)
                    res.root = deepcopy(res.root)
                    return res

                assert (
                    ':' in mainpath
                ), f'Invalid include path: anchor {mainpath} not found in document'

            assert ':' in mainpath, f'Invalid include path: {mainpath}. No loader specified.'

            loader, path = mainpath.split(':', 1)
            if loader not in custom_loaders:
                raise ValueError(f'Unknown loader: {loader}')

            res = custom_loaders[loader](path, loader=self)
            if not isinstance(res, CompositionResult):
                if not isinstance(res, str):
                    raise ValueError(f"Invalid result type from loader '{loader}': {type(res)}")
                new_loader = self.copy()
                if node is not None:
                    add_to_context(node.context, new_loader)
                res = new_loader.compose_config_from_str(res)
            if keypath:
                res = res.rerooted(KeyPath(keypath))
            return res
        finally:
            if isinstance(res, CompositionResult) and node is not None:
                walk_node(
                    node=res.root,
                    callback=partial(add_to_context, node.context),
                )

    @ftrace(watch=[])
    def compose_config_from_str(self, content: str) -> CompositionResult:
        self.yaml.compose(content)
        assert isinstance(self.yaml.composer, DraconComposer)
        res = self.yaml.composer.get_result()
        return self.post_process_composed(res)

    @ftrace(watch=[])
    def load_node(self, node):
        self.yaml.constructor.referenced_nodes = self.referenced_nodes
        self.yaml.constructor.context = deepcopy(self.context or {})
        return self.yaml.constructor.construct_document(node)

    def load_composition_result(self, compres: CompositionResult, post_process=True):
        if post_process:
            compres = self.post_process_composed(compres)
        return self.load_node(compres.root)

    @ftrace(watch=[])
    def load(self, config_path: str | Path):
        self.reset_context()
        if isinstance(config_path, Path):
            config_path = config_path.resolve().as_posix()
        if ":" not in config_path:
            config_path = f"file:{config_path}"
        comp = self.compose_from_include_str(config_path)
        return self.load_composition_result(comp)

    @ftrace(watch=[])
    def loads(self, content: str):
        comp = self.compose_config_from_str(content)
        return self.load_composition_result(comp)

    @ftrace(watch=[])
    def post_process_composed(self, comp: CompositionResult):
        # first we update the context of all context-containing nodes
        walk_node(
            node=comp.root,
            callback=partial(add_to_context, self.context),
        )

        comp = self.preprocess_references(comp)
        comp = process_deferred(comp, force_deferred_at=self.deferred_paths)
        comp = process_instructions(comp, self)
        comp = self.process_includes(comp)
        comp = process_merges(comp)
        comp = delete_unset_nodes(comp)
        comp = self.save_references(comp)
        comp = self.update_deferred_nodes(comp)

        return comp

    @ftrace(watch=[])
    def preprocess_references(self, comp_res: CompositionResult):
        comp_res.find_special_nodes('interpolable', lambda n: isinstance(n, InterpolableNode))
        comp_res.sort_special_nodes('interpolable')

        for path in comp_res.pop_all_special('interpolable'):
            node = path.get_obj(comp_res.root)
            assert isinstance(node, InterpolableNode), f"Invalid node type: {type(node)}  => {node}"
            node.preprocess_references(comp_res, path)

        return comp_res

    def update_deferred_nodes(self, comp_res: CompositionResult):
        # copies the loader into deferred nodes so they can resume their composition by themselves

        deferred_nodes = []

        def find_deferred_nodes(node: Node, path: KeyPath):
            if isinstance(node, DeferredNode):
                deferred_nodes.append((node, path))

        comp_res.walk(find_deferred_nodes)
        deferred_nodes = sorted(deferred_nodes, key=lambda x: len(x[1]), reverse=True)

        for node, _ in deferred_nodes:
            node._loader = self.copy()
            node._full_composition = deepcopy(comp_res)
        return comp_res

    @ftrace(watch=[])
    def save_references(self, comp_res: CompositionResult):
        # the preprocessed refernces are stored as paths that point to refered nodes
        # however, after all the merging and including is done, we need to save
        # the nodes themselves so that they can't be affected by further changes (e.g. construction)
        comp_res.find_special_nodes('interpolable', lambda n: isinstance(n, InterpolableNode))

        referenced_nodes = {}

        for path in comp_res.pop_all_special('interpolable'):
            node = path.get_obj(comp_res.root)
            assert isinstance(node, InterpolableNode), f"Invalid node type: {type(node)}"
            node.flush_references()
            for i, n in node.referenced_nodes.items():
                if i not in referenced_nodes:
                    referenced_nodes[i] = deepcopy(n)

        self.referenced_nodes = ShallowDict(
            merged(self.referenced_nodes, referenced_nodes, MergeKey(raw='{<+}'))
        )
        return comp_res

    @ftrace(watch=[])
    def process_includes(self, comp_res: CompositionResult):
        while True:  # we need to loop until there are no more includes (since some includes may bring other ones )
            comp_res.find_special_nodes('include', lambda n: isinstance(n, IncludeNode))

            if not comp_res.special_nodes['include']:
                break

            comp_res.sort_special_nodes('include')
            for inode_path in comp_res.pop_all_special('include'):
                inode = inode_path.get_obj(comp_res.root)
                assert isinstance(inode, IncludeNode), f"Invalid node type: {type(inode)}"
                new_loader = self.copy()
                include_composed = new_loader.compose_from_include_str(
                    inode.value, inode_path, comp_res, node=inode
                )
                comp_res.replace_node_at(inode_path, include_composed.root)

        return comp_res

    def dump(self, data, stream=None):
        if stream is None:
            from io import StringIO

            string_stream = StringIO()
            self.yaml.dump(data, string_stream)
            return string_stream.getvalue()
        else:
            return self.yaml.dump(data, stream)

    def dump_to_node(self, data):
        if isinstance(data, Node):
            return data
        return self.yaml.representer.represent_data(data)


##────────────────────────────────────────────────────────────────────────────}}}


def load(config_path: str | Path, raw_dict=False, **kwargs):
    loader = DraconLoader(**kwargs)
    if raw_dict:
        loader.yaml.constructor.yaml_base_dict_type = dict
    return loader.load(config_path)


def load_node(node: Node, **kwargs):
    loader = DraconLoader(**kwargs)
    return loader.load_node(node)


def load_file(config_path: str | Path, raw_dict=True, **kwargs):
    return load(f'file:{config_path}', raw_dict, **kwargs)


def loads(config_str: str, raw_dict=False, **kwargs):
    loader = DraconLoader(**kwargs)
    if raw_dict:
        loader.yaml.constructor.yaml_base_dict_type = dict
    return loader.loads(config_str)


def dump(data, stream=None, **kwargs):
    loader = DraconLoader(**kwargs)
    return loader.dump(data, stream)


def load_config_to_dict(maybe_config: str | DictLike) -> DictLike:
    if isinstance(maybe_config, str):
        loader = DraconLoader()
        conf = loader.load(maybe_config)
        conf.set_metadata({'dracon_origin': maybe_config})
        return conf
    return maybe_config


T = TypeVar('T')

LoadedConfig = Annotated[
    T | str,
    BeforeValidator(load_config_to_dict),
    PlainSerializer(lambda x: serialize_loaded_config(x)),
    Field(validate_default=True),
]


def serialize_loaded_config(c: DictLike) -> str | DictLike:
    if isinstance(c, MetadataDictLike):
        origin = c.get_metadata().get('dracon_origin')
        if origin is not None:
            return origin
    return c
