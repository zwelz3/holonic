"""Deprecated: legacy import path for the store protocol.

This module exists for backward compatibility with 0.3.x code. New
code should import from ``holonic.backends.store``. This shim will
be removed in 0.5.0.

Importing ``GraphBackend`` from here emits a ``DeprecationWarning``
the first time it happens per Python session. Set the environment
variable ``HOLONIC_SILENCE_DEPRECATION=1`` to suppress the warning
(useful in CI until migration is complete).
"""

from __future__ import annotations

import os
import warnings

from holonic.backends.store import AbstractHolonicStore, HolonicStore

_WARNED = False


def _warn_once() -> None:
    global _WARNED
    if _WARNED or os.environ.get("HOLONIC_SILENCE_DEPRECATION"):
        return
    _WARNED = True
    warnings.warn(
        "holonic.backends.protocol.GraphBackend is deprecated; "
        "import HolonicStore from holonic.backends.store instead. "
        "The GraphBackend alias will be removed in 0.5.0. "
        "Set HOLONIC_SILENCE_DEPRECATION=1 to suppress this warning.",
        DeprecationWarning,
        stacklevel=3,
    )


def __getattr__(name: str):
    if name == "GraphBackend":
        _warn_once()
        return HolonicStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Re-exported for direct use; these are not deprecated.
__all__ = ["AbstractHolonicStore", "HolonicStore"]
