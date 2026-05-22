# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

import re
from ruamel.yaml import YAML
from ruamel.yaml.scanner import RoundTripScanner, ScannerError, _THE_END_SPACE_TAB
from ruamel.yaml.tokens import ScalarToken, CommentToken
from typing import Any, Optional, Union, Dict
import copyreg

from dracon.interpolation_utils import scan_balanced, INTERPOLATION_OPENERS

_FLOW_COLON_TERMINATORS = _THE_END_SPACE_TAB + ',[]{}'


class DraconRoundTripScanner(RoundTripScanner):
    """Treats `${...}` and `$(...)` as atomic plain-scalar spans so flow indicators
    (`,`, `}`, `]`) inside them don't terminate the scalar."""

    def scan_plain(self) -> Any:
        srp = self.reader.peek
        srf = self.reader.forward
        chunks: list = []
        start_mark = self.reader.get_mark()
        end_mark = start_mark
        indent = self.indent + 1
        spaces: list = []
        while True:
            length = 0
            if srp() == '#':
                break
            while True:
                ch = srp(length)
                if ch == '$' and srp(length + 1) in INTERPOLATION_OPENERS:
                    opener = srp(length + 1)
                    end = scan_balanced(
                        srp, length + 2, opener, INTERPOLATION_OPENERS[opener], stop_at='\0\n\r'
                    )
                    if end > 0:
                        length = end
                        continue
                if ch == ':' and srp(length + 1) not in _THE_END_SPACE_TAB:
                    pass
                elif ch == '?' and self.scanner_processing_version != (1, 1):
                    pass
                elif (
                    ch in _THE_END_SPACE_TAB
                    or (
                        not self.flow_level
                        and ch == ':'
                        and srp(length + 1) in _THE_END_SPACE_TAB
                    )
                    or (self.flow_level and ch in ',:?[]{}')
                ):
                    break
                length += 1
            if (
                self.flow_level
                and ch == ':'
                and srp(length + 1) not in _FLOW_COLON_TERMINATORS
            ):
                srf(length)
                raise ScannerError(
                    'while scanning a plain scalar',
                    start_mark,
                    "found unexpected ':'",
                    self.reader.get_mark(),
                    'Please check http://pyyaml.org/wiki/YAMLColonInFlowContext for details.',
                )
            if length == 0:
                break
            self.allow_simple_key = False
            chunks.extend(spaces)
            chunks.append(self.reader.prefix(length))
            srf(length)
            end_mark = self.reader.get_mark()
            spaces = self.scan_plain_spaces(indent, start_mark)
            if (
                not spaces
                or srp() == '#'
                or (not self.flow_level and self.reader.column < indent)
            ):
                break

        token = ScalarToken("".join(chunks), True, start_mark, end_mark)
        if self.loader is not None:
            comment_handler = getattr(self.loader, 'comment_handling', False)
            if comment_handler is None:
                if spaces and spaces[0] == '\n':
                    comment = CommentToken("".join(spaces) + '\n', start_mark, end_mark)
                    token.add_post_comment(comment)
            elif comment_handler is not False:
                line = start_mark.line + 1
                for ch in spaces:
                    if ch == '\n':
                        self.comments.add_blank_line('\n', 0, line)
                        line += 1
        return token


class PicklableYAML(YAML):
    """A picklable version of ruamel.yaml.YAML"""

    def __init__(self, *args, typ='rt', **kwargs):
        super().__init__(*args, typ=typ, **kwargs)
        self._registered_types = {}  # Store registered types
        self.allow_unicode = True
        self.escape_char = None
        self.Scanner = DraconRoundTripScanner

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
