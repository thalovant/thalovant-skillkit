"""Cached inventories of immutable files shipped in a skill package."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=128)
def bundled_files(directory: Path | str, pattern: str) -> tuple[Path, ...]:
    """List matching bundled files once, in stable filename order.

    The directory and pattern are author-supplied, not utterance text. This
    caches paths, never audio bytes, so a large sound library stays cheap.
    For development or an in-place resource reload, call
    ``bundled_files.cache_clear()`` before the next turn. Live user directories
    should be read directly instead of using this package-asset cache.
    """
    return tuple(sorted(path for path in Path(directory).glob(pattern) if path.is_file()))
