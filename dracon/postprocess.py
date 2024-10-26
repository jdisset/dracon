from dracon.utils import (
    DictLike,
    MetadataDictLike,
    ListLike,
    ShallowDict,
    ftrace,
    deepcopy,
)

from dracon.composer import (
    IncludeNode,
    CompositionResult,
    DraconComposer,
    delete_unset_nodes,
    walk_node,
)
from dracon.interpolation_utils import resolve_interpolable_variables
from dracon.interpolation import InterpolableNode
from dracon.merge import process_merges, add_to_context, merged, MergeKey
from dracon.instructions import process_instructions
from dracon.loaders.file import read_from_file
from dracon.loaders.pkg import read_from_pkg
from dracon.deferred import DeferredNode, process_deferred
from dracon.loaders.env import read_from_env
from dracon.representer import DraconRepresenter
from dracon import dracontainer
from functools import partial


@ftrace(watch=[])
def preprocess_references(comp_res: CompositionResult):
    comp_res.find_special_nodes('interpolable', lambda n: isinstance(n, InterpolableNode))
    comp_res.sort_special_nodes('interpolable')

    for path in comp_res.pop_all_special('interpolable'):
        node = path.get_obj(comp_res.root)
        assert isinstance(node, InterpolableNode), f"Invalid node type: {type(node)}  => {node}"
        node.preprocess_references(comp_res, path)

    return comp_res
