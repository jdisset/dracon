import os


def read_from_env(path: str, **_):
    return str(os.getenv(path)), {}
