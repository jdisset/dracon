from typing import List, Any, Optional
from dracon.composer import CompositionResult
from dracon.keypath import KeyPath
from dracon.nodes import DraconMappingNode, DraconSequenceNode
from dracon.interpolation import evaluate_expression
from dracon.utils import deepcopy, generate_unique_id
from dracon.nodes import ContextNode
from pydantic import BaseModel, ConfigDict, Field
from dracon.nodes import Node


def make_node_or_expr(value) -> Node:
    """
    will try to make a node from the value, if it fails, it will return an InterpolableNode
    with a unique id to reference the variable (added to its context)
    """

    from dracon.interpolation import InterpolableNode
    from dracon.loader import dump_to_node

    if isinstance(value, Node):
        return value

    try:
        return dump_to_node(value)
    except Exception:
        uid = "gen_" + str(generate_unique_id())
        return InterpolableNode(value="${" + uid + "}", context={uid: value})


def generate_nodes(generator: Node, path: KeyPath) -> List[Node]:
    """
    Generate a list of Node objects from a generator node and its value.
    """
    from dracon.interpolation import InterpolableNode

    tag = generator.tag
    if not tag.startswith('!generate'):
        raise ValueError(f"Generator node must have a tag starting with '!generate', got '{tag}'")

    tag = tag[len('!generate') :]
    if tag.startswith(':'):
        tag = '!' + tag[1:]

    value = generator.value

    # 2 acceptable cases: the value is a sequence or an InterpolationNode
    if isinstance(value, DraconSequenceNode):
        nodes = [v for v in value.value]

    elif isinstance(value, InterpolableNode):
        evaluated = value.evaluate(path=str(path))
        if isinstance(evaluated, (range, map, filter)):
            evaluated = list(evaluated)
        elif not isinstance(evaluated, (list, tuple)):
            raise ValueError(f"Generator must evaluate to an iterable, got {type(evaluated)}")
        nodes = [make_node_or_expr(v) for v in evaluated]

    else:
        raise ValueError(
            f"Generator value must be a sequence or an InterpolableNode, got {type(value)}"
        )

    if tag:
        for n in nodes:
            n.tag = tag

    return nodes


def process_generators(comp: CompositionResult):
    """
    Find and process generator nodes in the composition.
    Whenever a generator node is found, the entire composition is duplicated and the generator node is replaced with
    its evaluated value. The resulting compositions are returned in a list.
    """
    pass

    # generator_nodes = []
    #
    # def is_generator(node):
    #     return hasattr(node, 'tag') and node.tag.startswith('!generate')
    #
    # def find_generators(node, path: KeyPath):
    #     if is_generator(node):
    #         generator_nodes.append((node, path))
    #
    # comp.walk(find_generators)
    #
    # if not generator_nodes:
    #     return [GeneratedComposition(composition=comp)]
    #
    # # Process generators from deepest to shallowest
    # generator_nodes.sort(key=lambda x: len(x[1]), reverse=True)
    #
    # new_comps = []
    # # Process each generator node
    # for node, path in generator_nodes:
    #     nodes = generate_nodes(node, path)
    #     for n in nodes:
    #         new_comp = deepcopy(comp)
    #         new_comp.set_at(path, n)
    #         new_comps.append(GeneratedComposition(composition=new_comp, generator_path=path))
    #
    # return new_comps
