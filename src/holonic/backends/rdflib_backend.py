"""rdflib.Dataset backend for holonic.

This is the default backend -- zero infrastructure, pure Python.
Uses rdflib.Dataset (a ConjunctiveGraph with explicit named-graph support)
as the quad store.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, cast

from rdflib import Dataset, Graph, Literal, URIRef
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.sparql import Query
from rdflib.term import Node

from holonic.backends._bindings import as_init_bindings
from holonic.backends.store import AbstractHolonicStore

log = logging.getLogger(__name__)


def _node_to_value(node: Node) -> Any:
    """Convert an rdflib term to a Python value for query results."""
    if isinstance(node, URIRef):
        return str(node)
    if isinstance(node, Literal):
        return node.toPython()
    return str(node)


@lru_cache(maxsize=256)
def _prepare(sparql: str) -> Query:
    """Parse a SPARQL SELECT/ASK/CONSTRUCT once and cache the algebra.

    Callers that reuse a constant template string (the parameterized
    ``**bindings`` path) reparse it exactly once; before parameterization
    every string-spliced query was unique and reparsed on each call. This
    cache is the P1 reparse win the audit measured.
    """
    return prepareQuery(sparql)


class RdflibBackend(AbstractHolonicStore):
    """HolonicStore implementation backed by an rdflib.Dataset.

    Parameters
    ----------
    dataset :
        An existing rdflib.Dataset instance.  If None, a fresh
        in-memory dataset is created.
    """

    def __init__(self, dataset: Dataset | None = None):
        # default_union=True so CONSTRUCT/SELECT queries without an explicit
        # GRAPH clause operate over the union of all named graphs. Portal
        # traversal stores user-supplied CONSTRUCTs that don't scope to a
        # graph, and pyshacl-style reports expect whole-dataset semantics.
        self.ds: Dataset = dataset if dataset is not None else Dataset(default_union=True)

    # ── Named-graph CRUD ──────────────────────────────────────

    def graph_exists(self, graph_iri: str) -> bool:
        """Check if graph exists in the dataset."""
        g = self.ds.graph(URIRef(graph_iri))
        return len(g) > 0

    def get_graph(self, graph_iri: str) -> Graph:
        """Return a *copy* of the named graph for local processing.

        Mutations to the returned graph do NOT affect the backing
        dataset.  Use ``put_graph`` / ``post_graph`` to persist
        changes.
        """
        source = self.ds.graph(URIRef(graph_iri))
        copy = Graph()
        for prefix, ns in source.namespaces():
            copy.bind(prefix, ns, override=False)
        for triple in source:
            copy.add(triple)
        return copy

    def put_graph(self, graph_iri: str, g: Graph) -> None:
        """Replace graph data in the dataset named graph."""
        target = self.ds.graph(URIRef(graph_iri))
        target.remove((None, None, None))
        for triple in g:
            target.add(triple)

    def post_graph(self, graph_iri: str, g: Graph) -> None:
        """Add graph data to the dataset named graph."""
        target = self.ds.graph(URIRef(graph_iri))
        for triple in g:
            target.add(triple)

    def delete_graph(self, graph_iri: str) -> None:
        """Remove named graph from the dataset."""
        g = self.ds.graph(URIRef(graph_iri))
        g.remove((None, None, None))
        self.ds.remove_graph(g)

    def parse_into(self, graph_iri: str, data: str, format: str = "turtle") -> None:
        """Parse data into dataset named graph."""
        g = self.ds.graph(URIRef(graph_iri))
        g.parse(data=data, format=format)

    # ── SPARQL ────────────────────────────────────────────────

    def _run(self, sparql: str, bindings: dict[str, Any]) -> Any:
        """Prepare (cached) and execute a read query with rdflib bindings.

        Binding values follow the shared explicit-wrapper contract
        (``_bindings.as_init_bindings``): rdflib terms pass through, bare
        Python values become literals, so IRIs must arrive as ``URIRef``.
        """
        return self.ds.query(_prepare(sparql), initBindings=as_init_bindings(bindings))

    def query(self, sparql: str, **bindings: Any) -> list[dict[str, Any]]:
        """Execute query against the dataset."""
        result = self._run(sparql, bindings)
        if result.vars is None:
            raise ValueError(
                "query() expects a SELECT query (result has no bindings); "
                "use construct() for CONSTRUCT/DESCRIBE or ask() for ASK"
            )
        rows = []
        for row in result:
            d = {}
            for var in result.vars:
                val = getattr(row, str(var), None)
                if val is not None:
                    d[str(var)] = _node_to_value(val)
            rows.append(d)
        return rows

    def construct(self, sparql: str, **bindings: Any) -> Graph:
        """Execute CONSTRUCT query on the dataset."""
        result = self._run(sparql, bindings)
        if result.graph is None:
            raise ValueError(
                "construct() expects a CONSTRUCT or DESCRIBE query "
                "(result has no graph); use query() for SELECT or ask() for ASK"
            )
        return cast(Graph, result.graph)

    def ask(self, sparql: str, **bindings: Any) -> bool:
        """Execute ASK query on the dataset."""
        result = self._run(sparql, bindings)
        if result.askAnswer is None:
            raise ValueError(
                "ask() expects an ASK query (result has no boolean answer); "
                "use query() for SELECT or construct() for CONSTRUCT/DESCRIBE"
            )
        return bool(result.askAnswer)

    def update(self, sparql: str) -> None:
        """Update the dataset using SPARQL string."""
        self.ds.update(sparql)

    # ── Utility ───────────────────────────────────────────────

    def list_named_graphs(self) -> list[str]:
        """Return each graph idendifier in the dataset."""
        q = "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }"
        return [row["g"] for row in self.query(q)]

    # ── Dataset access (rdflib-specific, not in protocol) ─────

    # TODO __getattr__ to avoid superfluous docstring?
    @property
    def dataset(self) -> Dataset:
        """Returns dataset."""
        return self.ds
