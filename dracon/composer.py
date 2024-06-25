from ruamel.yaml import YAML
from ruamel.yaml.composer import Composer
from ruamel.yaml.nodes import ScalarNode
from ruamel.yaml.events import (
    AliasEvent,
    ScalarEvent,
)
from .merge import MergeKey, merged
from .utils import dict_like
from .loader import load_raw_conf_str

class DraconComposer(Composer):
    def compose_node(self, parent, index):
        event = self.parser.peek_event()

        if self.parser.check_event(ScalarEvent):
            if event.style is None and MergeKey.is_merge_key(event.value):
                event.tag = 'dracon_merge'
            return super().compose_node(parent, index)

        if self.parser.check_event(AliasEvent):
            event = self.parser.get_event()
            alias = event.anchor
            if alias in self.anchors:
                return self.return_alias(self.anchors[alias])
            else:
                return ScalarNode(
                    tag='dracon_include',
                    value=event.anchor,
                    start_mark=event.start_mark,
                    end_mark=event.end_mark,
                )

        return super().compose_node(parent, index)

def perform_merges(conf_obj):
    if isinstance(conf_obj, list):
        return [perform_merges(v) for v in conf_obj]

    if dict_like(conf_obj):
        res = {}
        merges = []
        for key, value in conf_obj.items():
            if hasattr(key, 'tag') and key.tag == 'dracon_merge':
                merges.append((MergeKey(raw=key.value), value))
            else:
                res[key] = perform_merges(value)
        for merge_key, merge_value in merges:
            res = merged(res, merge_value, merge_key)
        return res

    return conf_obj


def resolve_includes(conf_obj, base_path=None):
    if dict_like(conf_obj):
        return {k: resolve_includes(v, base_path) for k, v in conf_obj.items()}
    if isinstance(conf_obj, list):
        return [resolve_includes(v, base_path) for v in conf_obj]
    if hasattr(conf_obj, 'tag') and conf_obj.tag == 'dracon_include':
        return load_yaml(load_raw_conf_str(conf_obj.value))
    return conf_obj


def dracon_post_process(loaded):
    loaded = resolve_includes(loaded)
    loaded = perform_merges(loaded)
    return loaded

def load_yaml(content: str):
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.Composer = DraconComposer
    loaded_raw = yaml.load(content)
    return dracon_post_process(loaded_raw)

