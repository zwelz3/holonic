"""Holonic store protocol and ABC (0.4.0).

Any graph store — rdflib.Dataset, Fuseki, Oxigraph, GraphDB — can back
a HolonicDataset by satisfying the ``HolonicStore`` protocol. All
methods operate on named graphs via IRIs and SPARQL strings; no
rdflib types leak through the interface beyond ``rdflib.Graph`` for
query results.

Design
------

``HolonicStore`` is a ``typing.Protocol`` that declares the MANDATORY
surface. Any object with these methods can be used with
``HolonicDataset``.

``AbstractHolonicStore`` is an ABC that inherits the protocol and
provides default implementations of OPTIONAL methods in terms of the
mandatory ones. Backends that want native optimizations inherit the
ABC and override; backends that implement only the protocol get the
generic Python fallbacks from the library's helpers (``MetadataRefresher``,
``ScopeResolver``).

Optional surface (0.4.0)
------------------------

Minimal to start — see ``docs/DECISIONS.md`` § 0.4.0:

- ``refresh_graph_metadata(graph_iri)`` — recompute per-graph metadata
  natively. Library dispatches to this if present; otherwise falls
  back to the Python ``MetadataRefresher``.

Future 0.4.x extensions (scope walking, bulk load, pipeline
execution) will be additive — a backend that implements none of them
continues to work; a backend that implements some gets native speed
for those operations.

Backward compatibility
----------------------

``holonic.backends.protocol.GraphBackend`` is a deprecated alias for
``HolonicStore`` kept through all of 0.4.x. Removal scheduled for
0.5.0. See ``docs/MIGRATION.md``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from rdflib import Graph


# ══════════════════════════════════════════════════════════════
# Mandatory protocol
# ══════════════════════════════════════════════════════════════


@runtime_checkable
class HolonicStore(Protocol):
    """Mandatory interface for a quad-aware graph store.

    Every backend must satisfy this protocol. The methods cover
    named-graph CRUD and SPARQL dispatch — enough for all holonic
    operations when combined with the library's Python-side helpers
    (``MetadataRefresher``, ``ScopeResolver``, ``run_projection``).

    Any object matching this protocol shape can be used with
    ``HolonicDataset``, regardless of whether it inherits
    ``AbstractHolonicStore``. Inheritance is recommended for the
    defaults-for-optional-methods it provides, but not required.
    """

    # ── Named-graph CRUD ──────────────────────────────────────

    def graph_exists(self, graph_iri: str) -> bool:
        """Return True if the named graph contains at least one triple."""
        ...

    def get_graph(self, graph_iri: str) -> Graph:
        """Return the named graph as an rdflib.Graph (for local processing)."""
        ...

    def put_graph(self, graph_iri: str, g: Graph) -> None:
        """Replace the named graph with the contents of g."""
        ...

    def post_graph(self, graph_iri: str, g: Graph) -> None:
        """Append triples from g into the named graph."""
        ...

    def delete_graph(self, graph_iri: str) -> None:
        """Delete the named graph entirely."""
        ...

    def parse_into(self, graph_iri: str, data: str, format: str = "turtle") -> None:
        """Parse serialized RDF into the named graph (append)."""
        ...

    # ── SPARQL ────────────────────────────────────────────────

    def query(self, sparql: str, **bindings: Any) -> list[dict[str, Any]]:
        """Execute a SELECT query. Return list of binding dicts.

        Each dict maps variable names (without ``?``) to their values.
        Values are strings (IRIs/literals) — callers convert as needed.
        """
        ...

    def construct(self, sparql: str, **bindings: Any) -> Graph:
        """Execute a CONSTRUCT query. Return results as an rdflib.Graph."""
        ...

    def ask(self, sparql: str, **bindings: Any) -> bool:
        """Execute an ASK query. Return boolean."""
        ...

    def update(self, sparql: str) -> None:
        """Execute a SPARQL UPDATE (INSERT/DELETE/DROP/CREATE)."""
        ...

    # ── Utility ───────────────────────────────────────────────

    def list_named_graphs(self) -> list[str]:
        """Return IRIs of all named graphs containing triples."""
        ...


# ══════════════════════════════════════════════════════════════
# ABC with default implementations of optional methods
# ══════════════════════════════════════════════════════════════


class AbstractHolonicStore(ABC):
    """Abstract base class for holonic stores with optional-method defaults.

    Inheriting this is the recommended way to implement a backend.
    Subclasses define the mandatory methods (abstract here); the ABC
    provides Python fallback implementations of optional methods so
    backend authors don't have to ship them.

    Optional methods are prefixed ``_`` by convention — they are
    discovered via ``hasattr(store, method_name)`` by library helpers
    (see D-0.4.0-5). Subclasses override the public optional methods
    without underscore; the default implementations live under the
    underscore name to avoid accidental override.

    As of 0.4.0 the optional surface is minimal: just native
    metadata refresh. Future 0.4.x will add more.
    """

    # ── Mandatory (abstract) ──────────────────────────────────

    @abstractmethod
    def graph_exists(self, graph_iri: str) -> bool: ...

    @abstractmethod
    def get_graph(self, graph_iri: str) -> Graph: ...

    @abstractmethod
    def put_graph(self, graph_iri: str, g: Graph) -> None: ...

    @abstractmethod
    def post_graph(self, graph_iri: str, g: Graph) -> None: ...

    @abstractmethod
    def delete_graph(self, graph_iri: str) -> None: ...

    @abstractmethod
    def parse_into(self, graph_iri: str, data: str, format: str = "turtle") -> None: ...

    @abstractmethod
    def query(self, sparql: str, **bindings: Any) -> list[dict[str, Any]]: ...

    @abstractmethod
    def construct(self, sparql: str, **bindings: Any) -> Graph: ...

    @abstractmethod
    def ask(self, sparql: str, **bindings: Any) -> bool: ...

    @abstractmethod
    def update(self, sparql: str) -> None: ...

    @abstractmethod
    def list_named_graphs(self) -> list[str]: ...

    # ── Optional (with default implementations) ────────────────
    #
    # Backends that can compute these natively (e.g. Fuseki with a
    # native count query, GraphDB with graph-statistics extensions)
    # override the public method name. The library dispatches via
    # hasattr checks in the helpers that need them.
    #
    # Default implementations are intentionally absent here because
    # the Python fallback lives in holonic._metadata — co-locating it
    # would create a cycle. Instead, the library's MetadataRefresher
    # checks hasattr(store, 'refresh_graph_metadata') and dispatches
    # accordingly.

    # (No method bodies here in 0.4.0. Placeholder for when the
    # optional surface grows beyond a single method — see R9.x items
    # for scope walking, bulk load, pipeline execution, and health
    # aggregation.)


__all__ = ["AbstractHolonicStore", "HolonicStore"]
