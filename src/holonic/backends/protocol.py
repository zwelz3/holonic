"""Legacy import path for the store protocol.

The ``GraphBackend`` alias was removed in 0.5.0. Import from
``holonic.backends.store`` or the top-level ``holonic`` package.
"""

from __future__ import annotations

from holonic.backends.store import AbstractHolonicStore, HolonicStore

__all__ = ["AbstractHolonicStore", "HolonicStore"]
