from dracon import *
from io import StringIO
from rich import print as rprint

def dump(res):
    stream = StringIO()
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.dump(res, stream)
    rprint(stream.getvalue())

content = read_from_pkg('dracon:tests/configs/extra.yaml')


compres = compose_config_from_str(content)


res = load_from_composition_result(compres)
dump(res)
compres.node_map


