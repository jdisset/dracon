from pathlib import Path
from .load_utils import with_possible_ext, make_file_context


def read_from_file(path: str, extra_paths=None, **_) -> tuple[str, dict]:
    """
    Reads the content of a file, searching in the specified path and additional paths if provided.

    Args:
        path (str): The primary path to the file.
        extra_paths (list, optional): Additional paths to search for the file. Defaults to None.

    Returns:
        tuple[str, dict]: The file content and file context metadata.

    Raises:
        FileNotFoundError: If the file is not found in any of the specified paths.
    """
    all_paths = with_possible_ext(path)
    if not extra_paths:
        extra_paths = []

    extra_path = [Path('./')] + [Path(p) for p in extra_paths]

    for ep in extra_path:
        for p in all_paths:
            p = (ep / p).expanduser().resolve()
            if Path(p).exists():
                path = p.as_posix()
                break

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f'File not found: {path}')

    with open(p, 'r') as f:
        raw = f.read()

    return raw, make_file_context(p)
