import xxhash
import base64
from typing import Any, Optional, Set, Sequence

def dict_like(obj) -> bool:
    return (
        hasattr(obj, 'keys')
        and hasattr(obj, 'get')
        and hasattr(obj, '__getitem__')
        and hasattr(obj, '__contains__')
        and hasattr(obj, '__iter__')
        and hasattr(obj, 'items')
    )


def simplify_path(path: str):
    # a path is a string starting with '/'
    # then each part is separated by '.'
    # 2 consecutive '.' means go up one level, 3 means go up 2 levels, etc.
    # this function simplifies a path by removing the '..' and checks if it is in available_paths

    if not path.startswith('/'):
        path = '/' + path

    # cut at last /
    path = path[path.rfind('/') :]

    path = path[1:]  # remove leading '/'

    # remove one trailing '.' if present
    if path.endswith('.'):
        path = path[:-1]
    # if path is not in available_paths, try to simplify it
    parts = path.split('.')
    simplified = []
    for part in parts:
        if part == '':
            if simplified:
                simplified.pop()
        else:
            simplified.append(part)

    simplified_path = '/' + '.'.join(simplified)

    return simplified_path


def combine_paths(paths: Sequence[str]):
    sp = simplify_path('/' + '.'.join(paths))
    assert sp is not None
    return sp



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


