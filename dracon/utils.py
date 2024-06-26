import xxhash
import base64
from typing import Any

def dict_like(obj) -> bool:
    return (
        hasattr(obj, 'keys')
        and hasattr(obj, 'get')
        and hasattr(obj, '__getitem__')
        and hasattr(obj, '__contains__')
        and hasattr(obj, '__iter__')
        and hasattr(obj, 'items')
    )


def with_indent(content: str, indent: int) -> str:
    return '\n'.join([f'{" " * indent}{line}' for line in content.split('\n')])

def get_hash(data: str) -> str:
    hash_value = xxhash.xxh128(data).digest()
    return base64.b32encode(hash_value).decode('utf-8').rstrip('=')



def obj_get(obj: Any, attr: str):
    """
    Get an attribute from an object, handling various types of objects.
    """
    if isinstance(obj, list):
        return obj[int(attr)]
    if hasattr(obj, attr):
        return getattr(obj, attr)
    else:
        try:  # check if we can access it with __getitem__
            return obj[attr]
        except (TypeError, KeyError):
            raise AttributeError(f'Could not find attribute {attr} in {obj}')

# TODO: allow backtracking with consecutive dots
def get_obj_at_keypath(obj: Any, attr_path: str):

    if attr_path.startswith('/'):
        return get_obj_at_keypath(obj, attr_path[1:])

    if attr_path == '':
        return obj

    res = obj
    for attr in attr_path.split('.'):
        try:
            res = obj_get(res, attr)
        except (AttributeError, KeyError, IndexError) as e:
            raise AttributeError(f'Could not find path {attr_path} in {type(obj)} instance: {e}')
    return res


