from ruamel.yaml.representer import RoundTripRepresenter
from ruamel.yaml.nodes import MappingNode, ScalarNode
from ruamel.yaml.scalarstring import PlainScalarString
from pydantic import BaseModel


class DraconRepresenter(RoundTripRepresenter):
    pass


def represent_pydantic_model(self, data):
    tag = f"!{data.__class__.__name__}"
    return self.represent_mapping(tag, data.dict())

DraconRepresenter.add_multi_representer(BaseModel, represent_pydantic_model)
