from ruamel.yaml.constructor import Constructor
import sys
import importlib
from ruamel.yaml.nodes import MappingNode, SequenceNode
from ruamel.yaml.constructor import ConstructorError
from typing import Dict, Any, Mapping, List
from dracon.merge import merged, MergeKey
import pydantic
import types
import pickle
from dracon.keypath import KeyPath, ROOTPATH

from pydantic import (
    TypeAdapter,
    PydanticSchemaGenerationError,
)

import typing
import inspect
from dracon.utils import ShallowDict, ftrace
from dracon import dracontainer
from dracon.dracontainer import Dracontainer
from dracon.interpolation import outermost_interpolation_exprs, InterpolableNode
from dracon.lazy import LazyInterpolable, resolve_all_lazy, is_lazy_compatible
from dracon.resolvable import Resolvable, get_inner_type
from dracon.deferred import DeferredNode
from dracon.nodes import reset_tag

from typing import (
    Optional,
    Hashable,
    Type,
    Any,
    ForwardRef,
    List,
    get_origin,
)
from functools import partial
import logging

logger = logging.getLogger("dracon")

## {{{                        --     type utils     --


def pydantic_validate(tag, value, localns=None, root_obj=None, current_path=None):
    tag_type = resolve_type(tag, localns=localns or {})

    if not is_lazy_compatible(tag_type) and isinstance(value, Dracontainer) and tag_type is not Any:
        resolve_all_lazy(value)

    try:
        return TypeAdapter(tag_type).validate_python(value)
    except PydanticSchemaGenerationError as e:
        # we try a simple construction:
        try:
            instance = tag_type(value)
            return instance
        except Exception as e2:
            raise ValueError(
                f"Failed to validate {tag}, i.e {tag_type=} with {value=}. When trying as a simple construction, got {e2}. When trying as a Pydantic schema, got {e}"
            ) from e


def resolve_type(
    type_str: str,
    localns: Optional[dict] = None,
    available_module_names: Optional[List[str]] = None,
) -> Type:
    if not type_str.startswith('!'):
        return Any

    type_str = type_str[1:]

    if available_module_names is None:
        available_module_names = ["__main__"]
    localns = localns or {}

    # Attempt regular import
    module_name, type_name = type_str.rsplit(".", 1) if "." in type_str else ("", type_str)
    if module_name:
        available_module_names = [module_name] + available_module_names

    for module_name in available_module_names:
        try:
            module = sys.modules.get(module_name) or importlib.import_module(module_name)
            if hasattr(module, type_name):
                return getattr(module, type_name)
        except ImportError:
            continue

    # Fall back to _eval_type
    if '.' in type_str:
        module_name, cname = type_str.rsplit('.', 1)
        try:
            module = importlib.import_module(module_name)
            localns[module_name] = module
            localns[type_str] = getattr(module, cname)
        except (ImportError, AttributeError):
            pass

    try:
        from typing import _eval_type

        return _eval_type(ForwardRef(type_str), globals(), localns)
    except NameError as e:
        raise ValueError(f"Failed to resolve type {type_str}") from e
    except Exception:
        return Resolvable if type_str.startswith('Resolvable[') else Any


def get_origin_type(t):
    orig = get_origin(t)
    if orig is None:
        return t
    return orig


def get_all_types(items):
    return {
        name: obj
        for name, obj in items.items()
        if isinstance(
            obj,
            (
                type,
                typing._GenericAlias,
                typing._SpecialForm,
                typing._SpecialGenericAlias,
            ),
        )
    }


def get_all_types_from_module(module):
    if isinstance(module, str):
        try:
            module = importlib.import_module(module)
        except ImportError:
            print(f"WARNING: Could not import module {module}")
            return {}
    return get_all_types(module.__dict__)


def get_globals_up_to_frame(frame_n):
    frames = inspect.stack()
    globalns = {}

    for frame_id in range(min(frame_n, len(frames) - 1), 0, -1):
        frame = frames[frame_id]
        globalns.update(frame.frame.f_globals)

    return globalns


def parse_resolvable_tag(tag):
    if tag.startswith('!'):
        tag = tag[1:]
    if tag.startswith('Resolvable['):
        inner = tag[11:-1]
        return inner
    return Any


def collect_all_types(modules, capture_globals=True, globals_at_frame=15):
    types = {}
    for module in modules:
        types.update(get_all_types_from_module(module))
    if capture_globals:
        globalns = get_globals_up_to_frame(globals_at_frame)
        types.update(get_all_types(globalns))
    return types


DEFAULT_TYPES = {
    'Any': Any,
    'Resolvable': Resolvable,
    'DraconResolvable': Resolvable,
}

DEFAULT_MODULES_FOR_TYPES = [
    'pydantic',
    'typing',
    'dracon',
    'numpy',
]

##────────────────────────────────────────────────────────────────────────────}}}


class Draconstructor(Constructor):
    def __init__(
        self,
        preserve_quotes=None,
        loader=None,
        reference_nodes=None,
        resolve_interpolations=False,
        capture_globals=False,
    ):
        Constructor.__init__(self, preserve_quotes=preserve_quotes, loader=loader)
        self.preserve_quotes = preserve_quotes
        self.yaml_base_dict_type = dracontainer.Mapping
        self.yaml_base_sequence_type = dracontainer.Sequence

        self.localns = collect_all_types(
            DEFAULT_MODULES_FOR_TYPES,
            capture_globals=capture_globals,
        )
        self.localns.update(get_all_types_from_module('__main__'))

        self.referenced_nodes = reference_nodes or {}
        self._depth = 0
        self._root_node = None
        self._current_path = ROOTPATH
        self.resolve_interpolations = resolve_interpolations
        self.context = None

    def base_construct_object(self, node: Any, deep: bool = False) -> Any:
        """deep is True when creating an object/mapping recursively,
        in that case want the underlying elements available during construction
        """
        if node in self.constructed_objects:
            return self.constructed_objects[node]
        if deep:
            old_deep = self.deep_construct
            self.deep_construct = True
        if node in self.recursive_objects:
            return self.recursive_objects[node]
        self.recursive_objects[node] = None
        data = self.construct_non_recursive_object(node)

        self.constructed_objects[node] = data
        try:
            del self.recursive_objects[node]
        except KeyError as e:
            msg = f"Failed to delete {node} from recursive objects: {e}"
            msg += f"\navailable = \n{self.recursive_objects}"
            logger.error(msg)

        if deep:
            self.deep_construct = old_deep
        return data

    @ftrace()
    def construct_object(self, node, deep=True):
        assert self.context is not None, "Context must be set before constructing objects"

        self.localns.update(DEFAULT_TYPES)
        self.localns.update(get_all_types(self.context))

        is_root = False
        if self._depth == 0:
            self._root_node = node
            is_root = True
            self._current_path = ROOTPATH
        self._depth += 1
        tag = node.tag
        try:
            tag_type = resolve_type(tag, localns=self.localns)

            if issubclass(get_origin_type(tag_type), Resolvable):
                return self.construct_resolvable(node, tag_type)

            if isinstance(node, DeferredNode):
                return node

            if isinstance(node, InterpolableNode):
                return self.construct_interpolable(node)

            if tag.startswith('!'):
                reset_tag(node)
            obj = self.base_construct_object(node, deep=True)

            node.tag = tag  # we don't want to permanently change the tag of the node because it might be referenced elsewhere

        except pydantic.ValidationError as e:
            raise ConstructorError(
                None, None, f"Error while constructing {tag}: {e.errors()}", node.start_mark
            ) from e
        except Exception as e:
            raise ConstructorError(
                None, None, f"Error while constructing {tag}: {e}", node.start_mark
            ) from e
        finally:
            self._depth -= 1
            # self._current_path.up()

        obj = pydantic_validate(
            tag, obj, self.localns, root_obj=self._root_node, current_path=self._current_path
        )

        if self.resolve_interpolations and is_root:
            resolve_all_lazy(obj)

        return obj

    @ftrace(watch=[])
    def construct_resolvable(self, node, tag_type):
        inner_type = get_inner_type(tag_type)
        if inner_type is Any:
            inner_type = parse_resolvable_tag(node.tag)
        if inner_type is Any:
            reset_tag(node)
        else:
            # check if it's a string or a type:
            if isinstance(inner_type, str):
                node.tag = f"!{inner_type}"
            else:
                node.tag = f"!{inner_type.__name__}"
        res = Resolvable(node=node, ctor=self, inner_type=inner_type)
        return res

    @ftrace(watch=[])
    def construct_interpolable(self, node):
        node_value = node.value
        init_outermost_interpolations = node.init_outermost_interpolations
        validator = partial(pydantic_validate, node.tag, localns=self.localns)
        tag_iexpr = outermost_interpolation_exprs(node.tag)
        if tag_iexpr:  # tag is an interpolation itself
            # we can make a combo interpolation that evaluates
            # to a tuple of the resolved tag and value
            node_value = "${('" + str(node.tag) + "', " + str(node.value) + ")}"
            init_outermost_interpolations = outermost_interpolation_exprs(node_value)

            def validator_f(value, localns=self.localns):
                tag, value = value
                return pydantic_validate(tag, value, localns=localns)

            validator = partial(validator_f)

        context = ShallowDict(merged(self.context, node.context, MergeKey(raw='{<+}')))
        context['__DR_NODES'] = {
            i: Resolvable(node=n, ctor=self.copy()) for i, n in self.referenced_nodes.items()
        }

        lzy = LazyInterpolable(
            value=node_value,
            init_outermost_interpolations=init_outermost_interpolations,
            validator=validator,
            current_path=self._current_path,
            root_obj=self._root_node,
            context=context,
        )

        return lzy

    def copy(self):
        ctor = Draconstructor(
            preserve_quotes=self.preserve_quotes,
            loader=self.loader,
            reference_nodes=self.referenced_nodes,
        )
        ctor.context = self.context.copy()

        return ctor

    def __deepcopy__(self, memo):
        return self.copy()

    def construct_mapping(self, node: Any, deep: bool = False) -> Any:
        if not isinstance(node, MappingNode):
            raise ConstructorError(
                None,
                None,
                f"expected a mapping node, but found {node.id!s}",
                node.start_mark,
            )
        mapping = self.yaml_base_dict_type()
        for key_node, value_node in node.value:
            if key_node.tag == '!noconstruct' or value_node.tag == '!noconstruct':
                continue
            key = self.construct_object(key_node, deep=True)
            if not isinstance(key, Hashable):
                if isinstance(key, list):
                    key = tuple(key)
            if not isinstance(key, Hashable):
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found unhashable key",
                    key_node.start_mark,
                )
            if self._depth == 1:  # This is the root mapping node
                if isinstance(key, str) and key.startswith('__dracon__'):
                    continue

            value = self.construct_object(value_node, deep=deep)
            mapping[key] = value

        return mapping
