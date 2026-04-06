"""rdflib.Dataset backend for holonic.

This is the default backend — zero infrastructure, pure Python.
Uses rdflib.Dataset (a ConjunctiveGraph with explicit named-graph support)
as the quad store.
"""

from __future__ import annotations

import logging
from typing import Any

from rdflib import Dataset, Graph, Literal, URIRef
from rdflib.term import Node

log = logging.getLogger(__name__)


def _node_to_value(node: Node) -> Any:
    """Convert an rdflib term to a Python value for query results."""
    if isinstance(node, URIRef):
        return str(node)
    if isinstance(node, Literal):
        return node.toPython()
    return str(node)


class RdflibBackend:
    """GraphBackend implementation backed by an rdflib.Dataset.

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
        """Get named graph from the dataset."""
        return self.ds.graph(URIRef(graph_iri))

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

    def query(self, sparql: str, **bindings: Any) -> list[dict[str, Any]]:
        """Execute query against the dataset."""
        init = {
            k: URIRef(v) if isinstance(v, str) and v.startswith("urn:") else v
            for k, v in bindings.items()
        }
        result = self.ds.query(sparql, initBindings=init)
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
        init = {
            k: URIRef(v) if isinstance(v, str) and v.startswith("urn:") else v
            for k, v in bindings.items()
        }
        result = self.ds.query(sparql, initBindings=init)
        return result.graph

    def ask(self, sparql: str, **bindings: Any) -> bool:
        """Execute ASK query on the dataset."""
        init = {
            k: URIRef(v) if isinstance(v, str) and v.startswith("urn:") else v
            for k, v in bindings.items()
        }
        result = self.ds.query(sparql, initBindings=init)
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
