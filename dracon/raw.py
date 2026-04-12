# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""!raw tag -- opaque values that survive all dracon phases untouched."""

from typing import Any
from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema
from dracon.nodes import make_scalar_node

RAW_TAG = '!raw'


class RawExpression(str):
    """A string value opaque to dracon's interpolation and resolution.

    Dracon carries it through composition, construction, and lazy resolution
    without ever interpreting the contents. Downstream systems (runtimes,
    template engines, shells) evaluate it however they like.
    """

    def dracon_dump_to_node(self, representer):
        return make_scalar_node(str(self), tag=RAW_TAG)

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: GetCoreSchemaHandler):
        return core_schema.no_info_after_validator_function(
            lambda v: v if isinstance(v, cls) else cls(v),
            core_schema.str_schema(),
        )
