from dracon import *
from dracon.utils import with_indent
from io import StringIO
from rich import print as rprint
from dracon.utils import node_print, list_like, dict_like
from dracon.keypath import KeyPath
from ruamel.yaml.nodes import Node,SequenceNode,ScalarNode,MappingNode


def dump(res):
    stream = StringIO()
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.dump(res, stream)
    rprint(stream.getvalue())

content = read_from_pkg('dracon:tests/configs/params.yaml')
# content = read_from_pkg('dracon:tests/configs/main.yaml')


##

compres = compose_config_from_str(content)
res = load_from_composition_result(compres)
dump(res)



