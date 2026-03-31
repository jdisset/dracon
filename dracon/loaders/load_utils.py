import time
from pathlib import Path


def with_possible_ext(path: str):
    # return: the original, with .yaml, with .yml, without extension. in that order
    p = Path(path)
    return [p, p.with_suffix('.yaml'), p.with_suffix('.yml'), p.with_suffix('')]


def make_file_context(p: Path) -> dict:
    """Build the standard file-metadata context dict from a resolved Path."""
    now = time.time()
    return {
        'DIR': p.parent.as_posix(),
        'FILE': p.as_posix(),
        'FILE_PATH': p.as_posix(),
        'FILE_STEM': p.stem,
        'FILE_EXT': p.suffix,
        'FILE_LOAD_TIME': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now)),
        'FILE_LOAD_TIME_UNIX': int(now),
        'FILE_LOAD_TIME_UNIX_MS': int(now * 1000),
        'FILE_SIZE': p.stat().st_size,
    }

