from dracon.nodes import Node


def read_from_var(var_name: str, node=None, **_) -> tuple[Node, dict]:
    from dracon.loader import dump_to_node

    if node is None or var_name not in node.context:
        raise ValueError(f'Variable "{var_name}" not found in context for var: include')

    # dump the context variable to a node representation
    value_node = dump_to_node(node.context[var_name])

    return value_node, {}
