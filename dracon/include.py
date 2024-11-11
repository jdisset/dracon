from dataclasses import dataclass
from typing import Any, Optional, Dict, Tuple, Callable
from functools import partial
import re
from dracon.keypath import KeyPath, ROOTPATH
from dracon.composer import (
    IncludeNode,
    CompositionResult,
)
from dracon.interpolation_utils import resolve_interpolable_variables
from dracon.utils import (
    deepcopy,
)

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


def compose_from_include_str(
    draconloader,
    include_str: str,
    include_node_path: KeyPath = ROOTPATH,
    composition_result: Optional[CompositionResult] = None,
    custom_loaders: dict = DEFAULT_LOADERS,
    node: Optional[IncludeNode] = None,
) -> list[CompositionResult]:
    context = draconloader.context if not node else node.context
    include_str = resolve_interpolable_variables(include_str, context)  # type: ignore
    components = parse_include_str(include_str)
    results = []
    try:
        if composition_result is not None:
            assert isinstance(composition_result.anchor_paths, dict)
            if components.main_path.startswith('$'):
                assert node is not None
                result = handle_in_memory_include(
                    components.main_path[1:], node, components.key_path, draconloader.dump_to_node
                )
                results = [result] if result else []
            elif components.main_path.startswith('/'):
                assert not components.key_path, 'Invalid key path for relative path include'
                result = handle_absolute_path(components.main_path, composition_result)
                results = [result] if result else []
            elif components.main_path.startswith('@') or components.main_path.startswith('.'):
                assert not components.key_path, 'Invalid key path for relative path include'
                result = handle_relative_path(
                    components.main_path, include_node_path, composition_result
                )
                results = [result] if result else []
            elif components.main_path in composition_result.anchor_paths:
                result = handle_anchor_path(
                    components, composition_result.anchor_paths, composition_result
                )
                results = [result] if result else []
            
            if results:
                # Deep copy each result
                results = [CompositionResult(root=deepcopy(r.root)) for r in results]
                return results
                
            assert (
                ':' in components.main_path
            ), f'Invalid include path: anchor {components.main_path} not found in document'
        
        assert (
            ':' in components.main_path
        ), f'Invalid include path: {components.main_path}. No loader specified.'
        
        loader_name, path = components.main_path.split(':', 1)
        if loader_name not in custom_loaders:
            raise ValueError(f'Unknown loader: {loader_name}')
        
        loader_result, new_context = custom_loaders[loader_name](path)
        draconloader.update_context(new_context)
        
        if isinstance(loader_result, list):
            # Handle case where loader returns multiple results
            results = loader_result
        else:
            results = [loader_result]
            
        processed_results = []
        for result in results:
            if not isinstance(result, CompositionResult):
                if not isinstance(result, str):
                    raise ValueError(f"Invalid result type from loader '{loader_name}': {type(result)}")
                new_loader = draconloader.copy()
                if node is not None:
                    add_to_context(node.context, new_loader)
                result = new_loader.compose_config_from_str(result)
                
                # when compose_config_from_str returns multiple variants
                if isinstance(result, list):
                    processed_results.extend(result)
                else:
                    processed_results.append(result)
            else:
                processed_results.append(result)
        
        if components.key_path:
            processed_results = [
                result.rerooted(KeyPath(components.key_path)) 
                for result in processed_results
            ]
        
        return processed_results
        
    finally:
        # Apply context to all results
        if node is not None:
            for result in results:
                if isinstance(result, CompositionResult):
                    result.make_map()
                    result.walk_no_path(callback=partial(add_to_context, node.context))
