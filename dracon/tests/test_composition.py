import pytest
from dracon.keypath import KeyPath, ROOTPATH
from dracon.composer import CompositionResult
from ruamel.yaml.nodes import ScalarNode


class UniqueNode(ScalarNode):

    def __init__(
        self,
        value=None,
        start_mark=None,
        end_mark=None,
        tag=None,
        anchor=None,
        comment=None,
    ):
        ScalarNode.__init__(self, tag, value, start_mark, end_mark, comment=comment, anchor=anchor)




