from ruamel.yaml.constructor import Constructor, ConstructorError
from ruamel.yaml.nodes import MappingNode, SequenceNode, ScalarNode
from typing import Any, Dict
from copy import deepcopy

from ruamel.yaml.constructor import Constructor, SafeConstructor
from pydantic import BaseModel, create_model, ValidationError, TypeAdapter, PydanticSchemaGenerationError

from dracon import dracontainer
from dracon.composer import LazyInterpolableNode
from dracon.interpolation import LazyInterpolable, Lazy, outermost_interpolation_exprs
from dracon.resolvable import Resolvable, get_inner_type

from typing import Hashable, ForwardRef, Union, List, Tuple, _eval_type, get_origin  # type: ignore
from functools import partial


def pydantic_validate(tag, value, localns=None):
    tag_type = get_type(tag, localns or {})
    return TypeAdapter(tag_type).validate_python(value)

DEFAULT_TYPES = {
    'Any': Any,
    'Resolvable': Resolvable,
    'DraconResolvable': Resolvable,
}

def get_type(tag, localns):
    if tag.startswith('!'):
        tag = tag[1:]
    else:
        return Any

    localns = {**DEFAULT_TYPES, **localns}
    if '.' in tag:
        module_name, cname = tag.rsplit('.', 1)
        try:
            import importlib

            module = importlib.import_module(module_name)
            localns[module_name] = module
            localns[tag] = getattr(module, cname)  # Add the class directly with the full tag
        except ImportError:
            print(f'Failed to import {module_name}')
        except AttributeError:
            print(f'Failed to get {cname} from {module_name}')

    try:
        return _eval_type(ForwardRef(tag), globals(), localns)
    except NameError as e:
        raise ConstructorError(None, None, f"Failed to resolve type {tag}") from e

    except Exception as e:
        if tag.startswith('Resolvable['):
            return Resolvable
        return Any

# for delayed instanciation, maybe allow ${...} expression in tags
# which will mark the whole branch as delayed, and allow the type to actually be resolved later
# maybe a special Resolvable type
# And of course I need to write the equivalent serialiazer that turns Resolvable[T] into !${T}

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
    def __init__(self, preserve_quotes=None, loader=None, localns=None, context=None, interpolate_all=False):
        Constructor.__init__(self, preserve_quotes=preserve_quotes, loader=loader)
        self.yaml_base_dict_type = dracontainer.Mapping
        self.yaml_base_sequence_type = dracontainer.Sequence
        self.localns = localns or {}
        self.context = context or {}
        self.interpolate_all = interpolate_all

    def construct_object(self, node, deep=True):
        # force deep construction so that obj is always fully constructed
        tag = node.tag

        tag_type = get_type(tag, self.localns)


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


        if isinstance(node, LazyInterpolableNode):
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

            # TODO: current_path, root_obj
            lzy = LazyInterpolable(
                value=node_value,
                init_outermost_interpolations=init_outermost_interpolations,
                validator=validator,
                extra_symbols=deepcopy(self.context),
            )
            if self.interpolate_all:
                lzy = lzy.get(self)

            return lzy


        if tag.startswith('!'):
            self.reset_tag(node)

        obj = super().construct_object(node, deep=True)

        try:
            return pydantic_validate(tag, obj, self.localns)

        except PydanticSchemaGenerationError as e:
            # rebuild the object with the original tag
            node.tag = tag
            new = super().construct_object(node)
            return new

    def reset_tag(self, node):
        if isinstance(node, SequenceNode):
            node.tag = self.resolver.DEFAULT_SEQUENCE_TAG
        elif isinstance(node, MappingNode):
            node.tag = self.resolver.DEFAULT_MAPPING_TAG
        else:
            node.tag = self.resolver.DEFAULT_SCALAR_TAG


