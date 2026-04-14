"""Lightweight result types for console / operator-tool consumers.

These types are introduced in 0.3.1 to support the holonic-console
project. They are intentionally separate from ``holonic.model`` so
that the existing model surface stays focused on in-process holon
mechanics; the types here are tuned for serialization to JSON over
HTTP and for graph-rendering payloads.

All types are plain dataclasses with no Pydantic dependency. Convert
to dict via ``dataclasses.asdict`` if a service layer wants JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _short(iri: str) -> str:
    """Best-effort short label from an IRI.

    Tries '#' first (RDF fragment style), then '/' (HTTP path style),
    then ':' (URN/CURIE style). Returns the input unchanged if none
    of the above are present.
    """
    if not iri:
        return ""
    if "#" in iri:
        return iri.rsplit("#", 1)[-1]
    if "/" in iri:
        return iri.rsplit("/", 1)[-1]
    if ":" in iri:
        return iri.rsplit(":", 1)[-1]
    return iri


# ══════════════════════════════════════════════════════════════
# Holon listing / detail
# ══════════════════════════════════════════════════════════════


@dataclass
class HolonSummary:
    """Lightweight holon descriptor for browser/list views.

    Excludes layer graphs to keep the list query cheap. Use
    ``HolonicDataset.get_holon_detail()`` for the full picture.
    """

    iri: str
    label: str | None = None
    kind: str | None = None
    """The most-specific rdf:type other than cga:Holon, or 'Holon' if none."""
    classification: str | None = None
    """Optional cga:classification value (governance label)."""
    member_of: str | None = None
    """Parent holon IRI, if any."""
    interior_triple_count: int | None = None
    """Sum of triples across all interior graphs. None if not computed."""
    health: str | None = None
    """Latest membrane health (intact|weakened|compromised), or None."""


@dataclass
class HolonDetail:
    """Full holon descriptor including layer graph IRIs and registry triples."""

    iri: str
    label: str | None = None
    kind: str | None = None
    classification: str | None = None
    member_of: str | None = None
    interior_graphs: list[str] = field(default_factory=list)
    boundary_graphs: list[str] = field(default_factory=list)
    projection_graphs: list[str] = field(default_factory=list)
    context_graphs: list[str] = field(default_factory=list)
    interior_triple_count: int | None = None
    health: str | None = None


@dataclass
class ClassInstanceCount:
    """Count of instances of a single rdf:type within a holon's interior."""

    class_iri: str
    count: int


# ══════════════════════════════════════════════════════════════
# Neighborhood graph (graphology-compatible)
# ══════════════════════════════════════════════════════════════


@dataclass
class NeighborhoodNode:
    key: str
    label: str | None = None
    kind: str | None = None
    health: str | None = None
    triples: int = 0
    size: float = 10.0
    node_type: str = "holon"


@dataclass
class NeighborhoodEdge:
    key: str
    source: str
    target: str
    edge_type: str  # 'portal' | 'class-ref' | 'provenance'
    label: str | None = None
    health: str | None = None
    size: float = 1.0


@dataclass
class NeighborhoodGraph:
    """A neighborhood subgraph centered on a holon, depth-bounded.

    Serializes to graphology's native JSON via ``to_graphology()``.
    The console returns this directly to sigma.js.
    """

    source_holon: str
    depth: int
    nodes: list[NeighborhoodNode] = field(default_factory=list)
    edges: list[NeighborhoodEdge] = field(default_factory=list)

    def to_graphology(self) -> dict:
        """Return a graphology-compatible JSON payload.

        Shape per https://graphology.github.io/serialization.html and
        the contract documented in ``docs/GRAPH-COMPONENTS.md`` of
        the holonic-console project.
        """
        return {
            "attributes": {
                "name": "holon-neighborhood",
                "sourceHolon": self.source_holon,
                "depth": self.depth,
            },
            "options": {
                "type": "directed",
                "multi": True,
                "allowSelfLoops": True,
            },
            "nodes": [
                {
                    "key": n.key,
                    "attributes": {
                        "label": n.label or _short(n.key),
                        "nodeType": n.node_type,
                        "kind": n.kind,
                        "health": n.health,
                        "triples": n.triples,
                        "size": n.size,
                    },
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "key": e.key,
                    "source": e.source,
                    "target": e.target,
                    "attributes": {
                        "edgeType": e.edge_type,
                        "label": e.label,
                        "health": e.health,
                        "size": e.size,
                    },
                }
                for e in self.edges
            ],
        }


# ══════════════════════════════════════════════════════════════
# Portal listing / detail
# ══════════════════════════════════════════════════════════════


@dataclass
class PortalSummary:
    """Lightweight portal descriptor for browser/list views."""

    iri: str
    source_iri: str
    target_iri: str
    label: str | None = None
    last_traversal: str | None = None
    """ISO-8601 timestamp of the most-recent recorded traversal."""
    health: str | None = None
    """Latest target-membrane health (intact|weakened|compromised) or None."""


@dataclass
class PortalDetail:
    """Full portal descriptor including the CONSTRUCT query body."""

    iri: str
    source_iri: str
    target_iri: str
    label: str | None = None
    construct_query: str | None = None
    graph_iri: str | None = None
    """Named graph in which this portal is registered (the source's boundary)."""
