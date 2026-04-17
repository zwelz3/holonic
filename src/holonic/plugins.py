"""Projection transform plugin system (0.3.5).

Transforms are Python callables with signature
``(graph: rdflib.Graph, **kwargs) -> rdflib.Graph``. They are
discovered via the ``holonic.projections`` entry-point group.
Pipelines (RDF-declared, see ``cga:ProjectionPipelineSpec``)
reference transforms by registered name.

This module exposes:

- ``projection_transform(name)`` — decorator for first-party
  transforms in ``holonic.projections``. Register a function
  under a name that pipelines can reference.
- ``get_registered_transforms()`` — returns ``dict[str, Callable]``
  of all discovered transforms (first-party + third-party).
- ``resolve_transform(name)`` — return the callable for a given
  registered name, or raise ``TransformNotFoundError``.
- ``transform_version(name)`` — return ``pkg-name==version`` for
  a registered transform, for provenance recording.
- ``host_metadata()`` — return a dict of host/platform/runtime
  metadata to include in projection-run activities.

See ``docs/DECISIONS.md`` § 0.3.5 for rationale.
"""

from __future__ import annotations

import platform
import socket
import sys
from collections.abc import Callable
from importlib import metadata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rdflib import Graph


# Entry-point group that third-party packages use to register
# transforms with holonic.
ENTRY_POINT_GROUP = "holonic.projections"

# First-party transform registry, populated at import time by the
# @projection_transform decorator.
_REGISTERED: dict[str, Callable[[Graph], Graph]] = {}

# Reverse index: callable id -> registered name. Used so that
# transform_version() can identify a registered callable in logs.
_NAMES_FOR_ID: dict[int, str] = {}


class TransformNotFoundError(KeyError):
    """Raised when a pipeline references an unknown transform name."""


def projection_transform(
    name: str,
) -> Callable[[Callable[[Graph], Graph]], Callable[[Graph], Graph]]:
    """Register a Python function as a projection transform.

    Intended for first-party transforms shipped in ``holonic.projections``.
    Third-party transforms declare themselves via the
    ``holonic.projections`` entry-point group in their ``pyproject.toml``.

    The decorator does not modify the function; it just records
    the name -> callable mapping in a module-level dict.

    Example::

        @projection_transform("strip_blank_nodes")
        def strip_blank_nodes(graph: Graph) -> Graph:
            ...

    Pipelines reference the transform by the registered name::

        ProjectionPipelineStep(name="strip", transform_name="strip_blank_nodes")
    """

    def _decorator(func: Callable[[Graph], Graph]) -> Callable[[Graph], Graph]:
        _REGISTERED[name] = func
        _NAMES_FOR_ID[id(func)] = name
        return func

    return _decorator


def _discover_entry_points() -> dict[str, Callable[[Graph], Graph]]:
    """Discover all transforms advertised via entry points.

    Called lazily on the first ``get_registered_transforms()`` call
    so entry-point metadata is not scanned during package import.
    """
    discovered: dict[str, Callable[[Graph], Graph]] = {}
    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        # Older importlib.metadata API fallback (Python 3.9); holonic
        # requires 3.11+, but this protects against environment quirks.
        all_eps = metadata.entry_points()
        eps = getattr(all_eps, "select", lambda **_: [])(group=ENTRY_POINT_GROUP)
    for ep in eps:
        try:
            obj = ep.load()
        except Exception:  # noqa: BLE001
            # A broken third-party transform should not prevent the
            # rest of the registry from loading. Log but continue.
            continue
        discovered[ep.name] = obj
    return discovered


def get_registered_transforms() -> dict[str, Callable[[Graph], Graph]]:
    """Return all registered transforms: first-party + entry-points.

    The first-party registry (populated by ``@projection_transform``)
    wins when names collide. This keeps the library's own transforms
    stable even if a third-party package registers under the same
    name.
    """
    combined = dict(_discover_entry_points())
    combined.update(_REGISTERED)  # first-party wins
    return combined


def resolve_transform(name: str) -> Callable[[Graph], Graph]:
    """Return the callable for a registered transform name.

    Raises ``TransformNotFoundError`` if no transform with that name
    is registered.
    """
    registry = get_registered_transforms()
    if name not in registry:
        known = ", ".join(sorted(registry.keys())) or "<none>"
        raise TransformNotFoundError(
            f"No transform registered under name {name!r}. Known transforms: {known}"
        )
    return registry[name]


def transform_version(name: str) -> str | None:
    """Return a 'package-name==version' string for a transform.

    Used by ``run_projection()`` for provenance recording. Returns
    ``None`` if the package providing the transform cannot be
    identified (rare; typically means the transform was registered
    in-process without a distribution, e.g. in a test).
    """
    registry = get_registered_transforms()
    func = registry.get(name)
    if func is None:
        return None
    module_name = getattr(func, "__module__", None)
    if not module_name:
        return None
    # Walk up module path to find the distribution that provides it.
    parts = module_name.split(".")
    while parts:
        try:
            dist = metadata.distribution(parts[0])
            return f"{dist.metadata['Name']}=={dist.version}"
        except metadata.PackageNotFoundError:
            # Try a shorter module path
            parts = parts[:-1]
    return None


def host_metadata() -> dict[str, str]:
    """Return host/platform/runtime metadata for provenance recording.

    Keys match the cga:run* predicates in the 0.3.5 ontology:

    - ``host`` -> ``cga:runHost``
    - ``platform`` -> ``cga:runPlatform``
    - ``python_version`` -> ``cga:runPythonVersion``
    - ``holonic_version`` -> ``cga:runHolonicVersion``

    None of these are guaranteed to be unique across a cluster; they
    are deployment-context hints, not strong identifiers.
    """
    from holonic import __version__ as holonic_version

    try:
        hostname = socket.gethostname()
    except Exception:  # noqa: BLE001
        hostname = "unknown"
    return {
        "host": hostname,
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "holonic_version": holonic_version,
    }


__all__ = [
    "ENTRY_POINT_GROUP",
    "TransformNotFoundError",
    "get_registered_transforms",
    "host_metadata",
    "projection_transform",
    "resolve_transform",
    "transform_version",
]
