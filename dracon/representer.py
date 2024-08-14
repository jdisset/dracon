from ruamel.yaml.representer import RoundTripRepresenter
from ruamel.yaml.nodes import MappingNode, ScalarNode
from ruamel.yaml.scalarstring import PlainScalarString
from pydantic import BaseModel
from dracon.utils import list_like, dict_like

import numpy as np


class DraconRepresenter(RoundTripRepresenter):
    def __init__(self, *args, full_module_path=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.full_module_path = full_module_path


def represent_pydantic_model(self, data):
    assert isinstance(data, BaseModel)

    tag = f"!{data.__class__.__name__}"
    if self.full_module_path:
        tag = f"!{data.__class__.__module__}.{data.__class__.__name__}"

    model_dump = data.model_dump()

    # we dump the object using the model_dump method
    # (which uses the preffered aliases and serializations)
    # EXCEPT for the fields that are BaseModel instances
    # where we recursively call this method instead

    for name, attr in dict(data).items():
        if isinstance(attr, BaseModel):
            model_dump[name] = attr
        elif list_like(attr):
            for i, x in enumerate(attr):
                if isinstance(x, BaseModel):
                    model_dump[name][i] = x
        elif dict_like(attr):
            for k, v in attr.items():
                if isinstance(v, BaseModel):
                    model_dump[name][k] = v

    node = self.represent_mapping(tag, model_dump)
    return node


# # check if pandas is installed
# PANDAS_INSTALLED = False
# try:
    # import pandas as pd

    # PANDAS_INSTALLED = True
# except ImportError:
    # pass
# if PANDAS_INSTALLED:

    # def represent_pandas_dataframe(self, data):
        # assert isinstance(data, pd.DataFrame)
        # return self.represent_scalar(f"!pandas.DataFrame", PlainScalarString(data.to_json()))

    # DraconRepresenter.add_representer(pd.DataFrame, represent_pandas_dataframe)


# NUMPY_INSTALLED = False
# try:
    # import numpy as np

    # NUMPY_INSTALLED = True
# except ImportError:
    # pass
# if NUMPY_INSTALLED:

    # def represent_numpy_array(self, data):
        # assert isinstance(data, np.ndarray)
        # aslist = data.tolist()
        # return self.represent_sequence(f"!numpy.ndarray", aslist)

    # DraconRepresenter.add_representer(np.ndarray, represent_numpy_array)


DraconRepresenter.add_multi_representer(BaseModel, represent_pydantic_model)
