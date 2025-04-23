# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

import re
from ruamel.yaml import YAML
from typing import Any, Optional, Union, Dict
import copyreg


class PicklableYAML(YAML):
    """A picklable version of ruamel.yaml.YAML"""

    def __init__(self, *args, typ='rt', **kwargs):
        super().__init__(*args, typ=typ, **kwargs)
        self._registered_types = {}  # Store registered types
        self.allow_unicode = True
        self.escape_char = None

    def register_class(self, cls):
        """Override register_class to keep track of registered types"""
        self._registered_types[cls.yaml_tag] = cls
        return super().register_class(cls)

    def __getstate__(self) -> Dict[str, Any]:
        """Get the object's state for pickling."""
        state = self.__dict__.copy()

        # Remove unpicklable attributes that are recreated on demand
        unpicklable_attrs = {
            '_reader',
            '_scanner',
            '_parser',
            '_composer',
            '_constructor',
            '_resolver',
            '_emitter',
            '_serializer',
            '_representer',
            '_stream',
            '_context_manager',
        }

        for attr in unpicklable_attrs:
            state.pop(attr, None)

        # Convert compiled regexes to patterns
        for key, value in state.items():
            if isinstance(value, re.Pattern):
                state[key] = value.pattern

        # Store essential configuration
        state['_config'] = {
            'typ': self.typ,
            'pure': getattr(self, 'pure', False),
            'plug_ins': getattr(self, 'plug_ins', []),
            'version': self.version,
            'old_indent': self.old_indent,
            'width': self.width,
            'preserve_quotes': self.preserve_quotes,
            'default_flow_style': self.default_flow_style,
            'encoding': self.encoding,
            'allow_unicode': self.allow_unicode,
            'line_break': self.line_break,
            'allow_duplicate_keys': self.allow_duplicate_keys,
        }

        return state

    def __setstate__(self, state: Dict[str, Any]) -> None:
        """Restore the object's state after unpickling."""
        # Extract configuration
        config = state.pop('_config', {})
        registered_types = state.get('_registered_types', {})

        # Reinitialize the base YAML object with saved configuration
        super().__init__(
            typ=config.get('typ', ['rt']),
            pure=config.get('pure', False),
            plug_ins=config.get('plug_ins', []),
        )

        # Restore compiled regexes
        for key, value in state.items():
            if isinstance(value, str) and key.endswith('_pattern'):
                state[key] = re.compile(value)

        # Update instance with saved state
        self.__dict__.update(state)

        # Restore configuration attributes
        for key, value in config.items():
            if hasattr(self, key):
                setattr(self, key, value)

        # Re-register types
        for cls in registered_types.values():
            self.register_class(cls)

    def __deepcopy__(self, memo):
        """Implement deep copy support."""
        state = self.__getstate__()
        new_instance = self.__class__()
        new_instance.__setstate__(state)
        return new_instance


# Register with copyreg to handle pickling
def _pickle_yaml(yaml):
    state = yaml.__getstate__()
    return PicklableYAML, (), state


copyreg.pickle(YAML, _pickle_yaml)
