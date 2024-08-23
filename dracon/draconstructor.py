from ruamel.yaml.constructor import Constructor, ConstructorError
from ruamel.yaml.nodes import MappingNode, SequenceNode, ScalarNode
from typing import Any, Dict
from copy import deepcopy

from ruamel.yaml.constructor import Constructor, SafeConstructor
from pydantic import BaseModel, create_model, ValidationError, TypeAdapter

from dracon import dracontainer
from dracon.composer import LazyInterpolableNode
from dracon.interpolation import LazyInterpolable, Lazy, outermost_interpolation_exprs

from typing import Hashable, ForwardRef, Union, List, Tuple, _eval_type  # type: ignore
from functools import partial


def pydantic_validate(tag, value, localns=None):
    if tag.startswith('!'):
        tag = tag[1:]
    else:
        return value

    localns = localns or {}

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

    return TypeAdapter(_eval_type(ForwardRef(tag), globals(), localns)).validate_python(value)


# for delayed instanciation, maybe allow ${...} expression in tags
# which will mark the whole branch as delayed, and allow the type to actually be resolved later
# maybe a special Resolvable type
# And of course I need to write the equivalent serialiazer that turns Resolvable[T] into !${T}

class Draconstructor(Constructor):
    def __init__(self, preserve_quotes=None, loader=None, localns=None, context=None):
        Constructor.__init__(self, preserve_quotes=preserve_quotes, loader=loader)
        self.yaml_base_dict_type = dracontainer.Mapping
        self.yaml_base_sequence_type = dracontainer.Sequence
        self.localns = localns or {}
        self.context = context or {}

    def construct_object(self, node, deep=True):
        # force deep construction so that obj is always fully constructed
        tag = node.tag
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
            return LazyInterpolable(
                value=node_value,
                init_outermost_interpolations=init_outermost_interpolations,
                validator=validator,
                extra_symbols=deepcopy(self.context),
            )

        if tag.startswith('!'):
            self.reset_tag(node)
        obj = super().construct_object(node, deep=True)
        return pydantic_validate(tag, obj, self.localns)

    def reset_tag(self, node):
        if isinstance(node, SequenceNode):
            node.tag = self.resolver.DEFAULT_SEQUENCE_TAG
        elif isinstance(node, MappingNode):
            node.tag = self.resolver.DEFAULT_MAPPING_TAG
        else:
            node.tag = self.resolver.DEFAULT_SCALAR_TAG
