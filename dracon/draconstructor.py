from ruamel.yaml.constructor import Constructor, ConstructorError
from ruamel.yaml.nodes import MappingNode, SequenceNode, ScalarNode
from typing import Any, Dict

from ruamel.yaml.constructor import Constructor, SafeConstructor
from pydantic import BaseModel, create_model, ValidationError, TypeAdapter

from dracon.dracontainer import Dracontainer

from typing import Hashable, ForwardRef, Union, List, Tuple, _eval_type


class Draconstructor(Constructor):
    def __init__(self, preserve_quotes=None, loader=None, localns=None):
        Constructor.__init__(self, preserve_quotes=preserve_quotes, loader=loader)
        self.yaml_base_dict_type = Dracontainer
        self.localns = localns or {}

    def construct_object(self, node, deep=True):
        # force deep construction so that obj is always fully constructed
        tag = node.tag
        if tag.startswith('!'):
            self.reset_tag(node)
        obj = super().construct_object(node, deep=True)
        return self.pydantic_validate(tag, obj)

    def pydantic_validate(self, tag, value):
        if tag.startswith('!'):
            tag = tag[1:]
        else:
            return value

        localns = self.localns


        if '.' in tag:
            print(f'Found a dot in tag: {tag}')
            module_name, cname = tag.rsplit('.', 1)
            try:
                import importlib
                module = importlib.import_module(module_name)
                localns[module_name] = module
                localns[tag] = getattr(module, cname)  # Add the class directly with the full tag
                print(f'Added {tag} to localns')
            except ImportError:
                print(f'Failed to import {module_name}')
            except AttributeError:
                print(f'Failed to get {cname} from {module_name}')



        return TypeAdapter(_eval_type(ForwardRef(tag), globals(), localns)).validate_python(
            value
        )

    def reset_tag(self, node):
        if isinstance(node, SequenceNode):
            node.tag = self.resolver.DEFAULT_SEQUENCE_TAG
        elif isinstance(node, MappingNode):
            node.tag = self.resolver.DEFAULT_MAPPING_TAG
        else:
            node.tag = self.resolver.DEFAULT_SCALAR_TAG


