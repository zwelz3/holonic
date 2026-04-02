"""Backend protocol for holonic graph operations.

Any graph store — rdflib.Dataset, Fuseki, Oxigraph, GraphDB — can back
a HolonicDataset by implementing this protocol.  All methods operate on
named graphs via IRIs and SPARQL strings; no rdflib types leak through
the interface.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from rdflib import Graph


@runtime_checkable
class GraphBackend(Protocol):
    """Minimal interface for a quad-aware graph store.

    Implementations must support named-graph CRUD and SPARQL query/update.
    Both sync (rdflib) and async (Fuseki) implementations are expected;
    async backends should provide sync wrappers or be used via an
    adapter that handles the event loop.
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
        """Execute a SELECT query.  Return list of binding dicts.

        Each dict maps variable names (without ?) to their values.
        Values are strings (IRIs/literals) — callers convert as needed.
        """
        ...

    def construct(self, sparql: str, **bindings: Any) -> Graph:
        """Execute a CONSTRUCT query.  Return results as an rdflib.Graph."""
        ...

    def ask(self, sparql: str, **bindings: Any) -> bool:
        """Execute an ASK query.  Return boolean."""
        ...

    def update(self, sparql: str) -> None:
        """Execute a SPARQL UPDATE (INSERT/DELETE/DROP/CREATE)."""
        ...

    # ── Utility ───────────────────────────────────────────────

    def list_named_graphs(self) -> list[str]:
        """Return IRIs of all named graphs containing triples."""
        ...
