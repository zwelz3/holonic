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

``holonic.backends.protocol`` re-exports
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

    Choosing between Protocol and ABC
    ---------------------------------

    Use the Protocol (``HolonicStore``) for type annotations on
    library-public functions and APIs. It captures the structural
    contract without requiring inheritance from users::

        def do_something(store: HolonicStore) -> None: ...

    Use the ABC (``AbstractHolonicStore``) as the base class for
    new backend implementations. It adds ``@abstractmethod``
    enforcement (so Python refuses to instantiate a subclass that
    forgets a method) plus hook points for optional-method defaults::

        class MyBackend(AbstractHolonicStore):
            def graph_exists(self, graph_iri): ...
            # ... all the other abstract methods

    Examples:
    --------
    The two first-party backends (``RdflibBackend``, ``FusekiBackend``)
    both inherit the ABC. Duck-typed protocol satisfaction works too,
    as verified by ``isinstance(backend, HolonicStore)``.

    See Also:
    --------
    AbstractHolonicStore : Recommended base class for new backends.
    holonic.backends.rdflib_backend.RdflibBackend : First-party default.
    holonic.backends.fuseki_backend.FusekiBackend : First-party HTTP.
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

    Mandatory surface
    -----------------

    Eleven methods marked ``@abstractmethod``: named-graph CRUD
    (``graph_exists``, ``get_graph``, ``put_graph``, ``post_graph``,
    ``delete_graph``, ``parse_into``), SPARQL dispatch (``query``,
    ``construct``, ``ask``, ``update``), and one utility
    (``list_named_graphs``). Python refuses to instantiate a
    subclass that doesn't implement all eleven.

    Optional surface
    ----------------

    Additional methods that backends MAY override to replace the
    library's generic Python fallbacks with native, typically
    faster implementations. Discovery is duck-typed via
    ``hasattr(store, method_name)``; no registration is required.

    As of 0.4.0, one optional method is recognized:

    - ``refresh_graph_metadata(graph_iri, registry_iri) -> GraphMetadata | None``
      recompute per-graph metadata (triple count, class inventory,
      last-modified timestamp) natively. The library's
      ``MetadataRefresher.refresh_graph`` dispatches to this if
      the method exists on the store; otherwise it runs the
      generic Python implementation.

    Future 0.4.x releases will add more optional methods for
    scope walking, bulk load, and pipeline execution (see SPEC
    R9.17).

    Example:
    -------
    A minimal backend implementing only the mandatory surface::

        from holonic.backends.store import AbstractHolonicStore

        class MyBackend(AbstractHolonicStore):
            def __init__(self):
                self._store = {}  # graph_iri -> set[(s, p, o)]

            def graph_exists(self, graph_iri):
                return bool(self._store.get(graph_iri))

            def get_graph(self, graph_iri):
                from rdflib import Graph
                g = Graph()
                for triple in self._store.get(graph_iri, ()):
                    g.add(triple)
                return g

            # ... other mandatory methods ...

    A backend with a native metadata fast path::

        class FusekiBackend(AbstractHolonicStore):
            # ... mandatory methods ...

            def refresh_graph_metadata(self, graph_iri, registry_iri):
                # Use Fuseki's native statistics endpoint
                stats = self._fetch_stats(graph_iri)
                return GraphMetadata(
                    iri=graph_iri,
                    triple_count=stats["count"],
                    last_modified=stats["modified"],
                    ...
                )

    See Also:
    --------
    HolonicStore : The Protocol view of the mandatory surface;
        use this for type annotations on library APIs.
    holonic._metadata.MetadataRefresher : Dispatcher that
        chooses native vs generic metadata paths.
    """

    # ── Mandatory (abstract) ──────────────────────────────────

    @abstractmethod
    def graph_exists(self, graph_iri: str) -> bool:
        """Return True if the named graph contains at least one triple.

        Implementations SHOULD treat "does not exist" and "exists
        but empty" as equivalent — both return False. Callers use
        this as a cheap presence check before committing to a full
        read.
        """
        ...

    @abstractmethod
    def get_graph(self, graph_iri: str) -> Graph:
        """Return the named graph as an ``rdflib.Graph``.

        The returned graph is a **copy** for local processing;
        mutations do not flow back to the store. Callers wanting
        to mutate the backing state use ``put_graph`` /
        ``post_graph`` / ``parse_into`` / ``update``.

        If the named graph does not exist, implementations SHOULD
        return an empty ``rdflib.Graph`` rather than raise.
        """
        ...

    @abstractmethod
    def put_graph(self, graph_iri: str, g: Graph) -> None:
        """Replace the named graph with the contents of ``g``.

        Existing triples in the named graph are removed; the new
        triples are then added. Atomic with respect to other
        callers where the backing store supports it; non-atomic
        implementations SHOULD document the window.
        """
        ...

    @abstractmethod
    def post_graph(self, graph_iri: str, g: Graph) -> None:
        """Append the triples in ``g`` to the named graph.

        Existing triples are preserved. Duplicate triples are
        coalesced at the RDF level (a quad store stores each
        ``(s, p, o, g)`` at most once).
        """
        ...

    @abstractmethod
    def delete_graph(self, graph_iri: str) -> None:
        """Delete the named graph entirely.

        SHOULD be idempotent: deleting a non-existent graph is a
        no-op, not an error.
        """
        ...

    @abstractmethod
    def parse_into(self, graph_iri: str, data: str, format: str = "turtle") -> None:
        """Parse serialized RDF and append into the named graph.

        ``format`` is an rdflib parser name; common values are
        ``"turtle"``, ``"xml"``, ``"n3"``, ``"json-ld"``,
        ``"nquads"``. Semantic equivalent to
        ``post_graph(graph_iri, rdflib.Graph().parse(data=data, format=format))``
        but implementations MAY optimize (e.g. stream-parse into
        the backing store directly).
        """
        ...

    @abstractmethod
    def query(self, sparql: str, **bindings: Any) -> list[dict[str, Any]]:
        """Execute a SPARQL SELECT query.

        Returns a list of binding dictionaries, one per result row.
        Each dict maps variable names (without the leading ``?``)
        to their bound values. Values are Python scalars for
        literals (strings, ints, floats, booleans, ``datetime``
        objects for ``xsd:dateTime``) and strings for IRIs.

        ``bindings`` is reserved for future parameterized-query
        support; implementations MAY raise ``NotImplementedError``
        on non-empty bindings in 0.4.x.
        """
        ...

    @abstractmethod
    def construct(self, sparql: str, **bindings: Any) -> Graph:
        """Execute a SPARQL CONSTRUCT query.

        Returns the constructed triples as an ``rdflib.Graph``.
        The return value is a fresh graph, not bound to any named
        graph in the store; callers wanting to persist it use
        ``put_graph`` or ``post_graph``.

        ``bindings``: see ``query``.
        """
        ...

    @abstractmethod
    def ask(self, sparql: str, **bindings: Any) -> bool:
        """Execute a SPARQL ASK query.

        Returns True if the query has at least one solution,
        False otherwise. ``bindings``: see ``query``.
        """
        ...

    @abstractmethod
    def update(self, sparql: str) -> None:
        """Execute a SPARQL UPDATE (INSERT / DELETE / DROP / CREATE).

        Mutates the backing store according to the update request.
        Callers using this path bypass the library's
        metadata-refresh machinery; if ``metadata_updates="eager"``
        is the dataset policy, call
        ``HolonicDataset.refresh_metadata`` after out-of-band
        updates to reconcile.
        """
        ...

    @abstractmethod
    def list_named_graphs(self) -> list[str]:
        """Return the IRIs of all named graphs in the store.

        Implementations SHOULD exclude graphs that exist as
        identifiers but contain no triples. The default graph
        (if the backing store has one) is NOT included; the
        library does not use the default graph and expects every
        triple to live in a named graph per R1.4.
        """
        ...

    # ── Optional (with library-side Python fallback) ──────────────
    #
    # These methods are NOT declared here. Backends that want a
    # native fast path add them as regular methods; library helpers
    # discover them via ``hasattr`` and dispatch accordingly. See
    # D-0.4.0-5 in docs/DECISIONS.md for the rationale.
    #
    # Why not declared? Two reasons:
    #
    #   1. A declaration here would force every backend that inherits
    #      the ABC to either implement the method or explicitly
    #      override with a no-op. The ``hasattr`` approach lets
    #      backends opt in without being forced to opt out.
    #
    #   2. Default implementations for metadata and scope would
    #      require importing from ``holonic._metadata`` and
    #      ``holonic.scope``, creating a circular-import risk. The
    #      dispatching helpers live in those modules and call back
    #      here structurally.
    #
    # Recognized optional methods (0.4.0):
    #
    #   refresh_graph_metadata(
    #       self,
    #       graph_iri: str,
    #       registry_iri: str,
    #   ) -> GraphMetadata | None
    #
    #     Compute and persist per-graph metadata. Return a fresh
    #     GraphMetadata or None (the library will re-read via the
    #     standard path). Called by MetadataRefresher.refresh_graph.
    #
    # Planned additions during 0.4.x (SPEC R9.17):
    #
    #   walk_neighbors_native(holon_iri, order) -> list[str]
    #   bulk_load_graphs(graphs: dict[str, Graph]) -> None
    #   execute_pipeline_native(holon_iri, spec_iri) -> Graph


__all__ = ["AbstractHolonicStore", "HolonicStore"]
