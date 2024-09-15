from .utils import *
from .merge import *
from .loader import *
from .composer import *
from .keypath import *
from .resolvable import Resolvable
from .draconstructor import Draconstructor
from .composer import DraconMappingNode, DraconSequenceNode
import typing


def resolvable_maker(inner_type, ctor=None):
    if ctor is None:
        ctor = Draconstructor()

    empty_node = DraconMappingNode(
        value=[],
        tag='',
    )

    def resolvable_constructor():
        return Resolvable(node=empty_node, ctor=ctor, inner_type=inner_type)

    return resolvable_constructor
