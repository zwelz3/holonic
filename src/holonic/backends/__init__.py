"""Graph store backends for holonic.

Canonical protocol: ``HolonicStore`` from ``holonic.backends.store``.
Recommended base class for new backends: ``AbstractHolonicStore``.

``GraphBackend`` is preserved as a deprecated alias through the
entire 0.4.x series. New code should use ``HolonicStore``.
"""

import os
import warnings

from holonic.backends.rdflib_backend import RdflibBackend
from holonic.backends.store import AbstractHolonicStore, HolonicStore

_WARNED = False


def _warn_graphbackend_once() -> None:
    """Emit the deprecation warning once per Python session."""
    global _WARNED
    if _WARNED or os.environ.get("HOLONIC_SILENCE_DEPRECATION"):
        return
    _WARNED = True
    warnings.warn(
        "holonic.GraphBackend is deprecated; use HolonicStore instead. "
        "The alias will be removed in 0.5.0. "
        "Set HOLONIC_SILENCE_DEPRECATION=1 to suppress this warning.",
        DeprecationWarning,
        stacklevel=3,
    )


def __getattr__(name: str):
    if name == "GraphBackend":
        _warn_graphbackend_once()
        return HolonicStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["AbstractHolonicStore", "HolonicStore", "RdflibBackend"]

# FusekiBackend is imported on demand to avoid requiring aiohttp
