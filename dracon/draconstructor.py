from ruamel.yaml.constructor import Constructor
import sys
import importlib
from ruamel.yaml.nodes import MappingNode, SequenceNode
from ruamel.yaml.constructor import ConstructorError
from copy import deepcopy

from pydantic import (
    TypeAdapter,
    PydanticSchemaGenerationError,
)

from dracon import dracontainer
from dracon.nodes import InterpolableNode
from dracon.interpolation import LazyInterpolable, outermost_interpolation_exprs
from dracon.resolvable import Resolvable, get_inner_type

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


def pydantic_validate(tag, value, localns=None):
    tag_type = resolve_type(tag, localns=localns or {})
    return TypeAdapter(tag_type).validate_python(value)


DEFAULT_TYPES = {
    'Any': Any,
    'Resolvable': Resolvable,
    'DraconResolvable': Resolvable,
}


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


def parse_resolvable_tag(tag):
    if tag.startswith('!'):
        tag = tag[1:]
    if tag.startswith('Resolvable['):
        inner = tag[11:-1]
        return inner
    return Any


class Draconstructor(Constructor):
    def __init__(
        self,
        preserve_quotes=None,
        loader=None,
        drloader=None,
        localns=None,
        context=None,
        interpolate_all=False,
    ):
        Constructor.__init__(self, preserve_quotes=preserve_quotes, loader=loader)
        self.drloader = drloader  # Store the loader
        self.yaml_base_dict_type = dracontainer.Mapping
        self.yaml_base_sequence_type = dracontainer.Sequence
        self.localns = localns or {}
        self.context = context or {}
        self.interpolate_all = interpolate_all
        self._depth = 0

    def construct_object(self, node, deep=True):
        # first, we ignore any mapping node that has a name starting with __dracon__
        self._depth += 1

        try:
            # force deep construction so that obj is always fully constructed
            tag = node.tag

            tag_type = resolve_type(tag, localns=self.localns)

            if issubclass(get_origin_type(tag_type), Resolvable):
                inner_type = get_inner_type(tag_type)
                if inner_type is Any:
                    inner_type = parse_resolvable_tag(tag)
                if inner_type is Any:
                    self.reset_tag(node)
                else:
                    # check if it's a string or a type:
                    if isinstance(inner_type, str):
                        node.tag = f"!{inner_type}"
                    else:
                        node.tag = f"!{inner_type.__name__}"
                res = Resolvable(node=node, ctor=self, inner_type=inner_type)
                return res

            if isinstance(node, InterpolableNode):
                node_value = node.value
                init_outermost_interpolations = node.init_outermost_interpolations
                validator = partial(pydantic_validate, tag, localns=self.localns)
                tag_iexpr = outermost_interpolation_exprs(tag)
                if tag_iexpr:  # tag is an interpolation itself
                    # we can make a combo interpolation that evaluates
                    # to a tuple of the resolved tag and value
                    node_value = "${('" + str(tag) + "', " + str(node.value) + ")}"
                    init_outermost_interpolations = outermost_interpolation_exprs(node_value)

                    def validator_f(value, localns=self.localns):
                        tag, value = value
                        return pydantic_validate(tag, value, localns=localns)

                    validator = partial(validator_f)

                extra_symbols = deepcopy(self.context)
                extra_symbols['__DRACON_RESOLVABLES'] = {
                    i: Resolvable(node=deepcopy(n), ctor=self)
                    for i, n in node.referenced_nodes.items()
                }

                lzy = LazyInterpolable(
                    value=node_value,
                    init_outermost_interpolations=init_outermost_interpolations,
                    validator=validator,
                    extra_symbols=extra_symbols,
                )
                if self.interpolate_all:
                    lzy = lzy.get(self)

                return lzy
        finally:
            self._depth -= 1

        if tag.startswith('!'):
            self.reset_tag(node)

        obj = super().construct_object(node, deep=True)

        try:
            obj = pydantic_validate(tag, obj, self.localns)
            return obj
        except PydanticSchemaGenerationError as e:
            print(f"Error while validating {tag}: {obj}: {e}")
            # rebuild the object with the original tag
            node.tag = tag
            new = super().construct_object(node)
            return new

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
            if self._depth == 0:  # This is the root mapping node
                if isinstance(key, str) and key.startswith('__dracon__'):
                    continue

            value = self.construct_object(value_node, deep=deep)
            mapping[key] = value

        return mapping

    def reset_tag(self, node):
        if isinstance(node, SequenceNode):
            node.tag = self.resolver.DEFAULT_SEQUENCE_TAG
        elif isinstance(node, MappingNode):
            node.tag = self.resolver.DEFAULT_MAPPING_TAG
        else:
            node.tag = self.resolver.DEFAULT_SCALAR_TAG
