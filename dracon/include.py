# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

from dataclasses import dataclass
from typing import Any, Optional, Dict, Tuple, Callable
import dracon.utils as utils
from functools import partial
import re
from dracon.keypath import KeyPath, ROOTPATH
from dracon.composer import (
    IncludeNode,
    CompositionResult,
)
from dracon.interpolation_utils import resolve_interpolable_variables
from dracon.interpolation import evaluate_expression
from dracon.merge import merged, MergeKey
from dracon.utils import deepcopy, ftrace
from dracon.deferred import DeferredNode

from dracon.merge import add_to_context
from dracon.loaders.file import read_from_file
from dracon.loaders.pkg import read_from_pkg
from dracon.loaders.env import read_from_env

DEFAULT_LOADERS: Dict[str, Callable] = {
    'file': read_from_file,
    'pkg': read_from_pkg,
    'env': read_from_env,
}


@dataclass
class IncludeComponents:
    """Represents the parsed components of an include string."""

    main_path: str
    key_path: str

    @property
    def path(self) -> str:
        return KeyPath(self.main_path) + KeyPath(self.key_path)


@dataclass
class LoaderResult:
    """Represents the result of a loader operation."""

    result: Any
    context: dict


def parse_include_str(include_str: str) -> IncludeComponents:
    """Parse an include string into its main path and key path components."""
    if '@' in include_str:
        main_path, key_path = re.split(r'(?<!\\)@', include_str, maxsplit=1)
    else:
        main_path, key_path = include_str, ''
    return IncludeComponents(main_path, key_path)


def handle_in_memory_include(
    name: str, node: 'IncludeNode', key_path: str, dump_to_node_fn: Callable
) -> CompositionResult:
    """Handle an in-memory include (starting with $)."""
    if name not in node.context:
        raise ValueError(f'Invalid in-memory include: {name} not found')

    incl_node = node.context[name]
    incl_node = dump_to_node_fn(incl_node)
    if key_path:
        incl_node = KeyPath(key_path).get_obj(incl_node)

    return CompositionResult(root=incl_node)


def handle_absolute_path(
    main_path: str, composition_result: CompositionResult
) -> CompositionResult:
    return composition_result.rerooted(KeyPath(main_path))


def handle_relative_path(
    main_path: str, include_node_path: KeyPath, composition_result: CompositionResult
) -> CompositionResult:
    comb_path = include_node_path.parent.down(KeyPath(main_path))
    return composition_result.rerooted(comb_path)


def handle_anchor_path(
    components: IncludeComponents,
    anchors: Dict[str, KeyPath],
    composition_result: CompositionResult,
) -> CompositionResult:
    return composition_result.rerooted(
        composition_result.anchor_paths[components.main_path] + components.key_path
    )


@ftrace(watch=[])
def compose_from_include_str(
    draconloader,
    include_str: str,
    include_node_path: KeyPath = ROOTPATH,
    composition_result: Optional[CompositionResult] = None,
    custom_loaders: dict = DEFAULT_LOADERS,
    node: Optional[IncludeNode] = None,  #
) -> Any:
    context = draconloader.context if not node else node.context

    # there are 2 syntaxes for include string interpolations:
    # first is any variable that starts with $, like $DIR (which is set by the file loader)
    # second is the usual interpolation syntax, like ${some_expression}.
    # we resolve both of them here.
    include_str = evaluate_expression(
        include_str,
        current_path=include_node_path,
        root_obj=composition_result.root if composition_result else None,
        engine=draconloader.interpolation_engine,
        context=context,
    )
    include_str = resolve_interpolable_variables(include_str, context)  # type: ignore

    components = parse_include_str(include_str)
    result = None
    file_context = {}

    try:
        if composition_result is not None:
            assert isinstance(composition_result.anchor_paths, dict)

            if components.main_path.startswith('$'):
                assert node is not None
                result = handle_in_memory_include(
                    components.main_path[1:], node, components.key_path, draconloader.dump_to_node
                )

            elif components.main_path.startswith('/'):
                assert not components.key_path, 'Invalid key path for relative path include'
                result = handle_absolute_path(components.main_path, composition_result)

            elif components.main_path.startswith('@') or components.main_path.startswith('.'):
                assert not components.key_path, 'Invalid key path for relative path include'
                result = handle_relative_path(
                    components.main_path, include_node_path, composition_result
                )
            elif components.main_path in composition_result.anchor_paths:
                result = handle_anchor_path(
                    components, composition_result.anchor_paths, composition_result
                )

            if result is not None:
                result.root = deepcopy(result.root)
                return result

            assert (
                ':' in components.main_path
            ), f'Invalid include path: anchor {components.main_path} not found in document'

        assert (
            ':' in components.main_path
        ), f'Invalid include path: {components.main_path}. No loader specified.'

        loader_name, path = components.main_path.split(':', 1)
        if loader_name not in custom_loaders:
            raise ValueError(f'Unknown loader: {loader_name}')

        result, new_context = custom_loaders[loader_name](path)
        file_context = new_context
        draconloader.update_context(new_context)

        if not isinstance(result, CompositionResult):
            if not isinstance(result, str):
                raise ValueError(f"Invalid result type from loader '{loader_name}': {type(result)}")
            new_loader = draconloader.copy()
            if node is not None:
                merged_context = merged(node.context, new_context, MergeKey(raw="{<~}[<~]"))
                add_to_context(merged_context, new_loader)

            result = new_loader.compose_config_from_str(result)
        if components.key_path:
            result = result.rerooted(KeyPath(components.key_path))
        return result

    finally:
        if isinstance(result, CompositionResult) and node is not None:
            result.make_map()
            merged_context = merged(
                node.context, file_context, MergeKey(raw="{<~}[~<]")
            )  # Changed to +>
            result.walk_no_path(
                callback=partial(add_to_context, merged_context, merge_key=MergeKey(raw='{>~}[~>]'))
            )
