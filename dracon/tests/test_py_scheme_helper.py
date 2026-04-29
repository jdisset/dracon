"""Helper module imported by test_py_scheme.py via the py: loader."""
from pydantic import BaseModel


def add(a, b):
    return a + b


def greet(name, greeting='hello'):
    return f"{greeting} {name}"


class Helper(BaseModel):
    """Pydantic model used for tag-syntax construction (!Helper { ... })."""

    n: int = 10
    label: str = 'x'

    def describe(self):
        return f"{self.label}={self.n}"


PI_APPROX = 3.14

_private_thing = "should not be exported"


__all__ = ['add', 'greet', 'Helper', 'PI_APPROX']
