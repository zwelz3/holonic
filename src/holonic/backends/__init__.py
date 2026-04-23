"""Graph store backends for holonic.

Canonical protocol: ``HolonicStore`` from ``holonic.backends.store``.
Recommended base class for new backends: ``AbstractHolonicStore``.

The ``GraphBackend`` alias was removed in 0.5.0. Use ``HolonicStore``.
"""

from holonic.backends.rdflib_backend import RdflibBackend
from holonic.backends.store import AbstractHolonicStore, HolonicStore

__all__ = ["AbstractHolonicStore", "HolonicStore", "RdflibBackend"]

# FusekiBackend is imported on demand to avoid requiring aiohttp
