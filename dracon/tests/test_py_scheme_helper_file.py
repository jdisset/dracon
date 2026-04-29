"""File-path helper for py: loader tests — NOT imported by pytest directly.

This file is referenced by absolute path in test_py_scheme.py to exercise
the file-path form of py: includes (importlib.util.spec_from_file_location).
Its module is not registered on sys.path under a package name.
"""
from pydantic import BaseModel


def double(x):
    return x * 2


class FileHelper(BaseModel):
    tag: str = 'file'


FILE_CONST = 99
