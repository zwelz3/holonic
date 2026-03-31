"""
holon.py — Core Holon with four named graphs.

A Holon is constructed by providing TTL content for each layer.
Graphs are built by parsing Turtle, never by manual add() calls.
This keeps the graph content readable, auditable, and close to
how the data would appear in a triple store or file.

Construction patterns
---------------------

Minimal holon (identity only)::

    h = Holon("urn:holon:example", label="Example")

Holon with interior data::

    h = Holon(
        "urn:holon:city:vancouver",
        label="Vancouver",
        depth=2,
        interior_ttl='''
            <urn:holon:city:vancouver> a cga:Holon ;
                rdfs:label "Vancouver" ;
                <urn:geo:population> 675218 ;
                <urn:geo:latitude>  49.2827 ;
                <urn:geo:longitude> -123.1207 .
        ''',
    )

Holon with boundary shapes::

    h = Holon(
        "urn:holon:city:vancouver",
        label="Vancouver",
        boundary_ttl='''
            <urn:shapes:CityShape> a sh:NodeShape ;
                sh:targetClass <urn:geo:City> ;
                sh:closed true ;
                sh:property [
                    sh:path rdfs:label ;
                    sh:minCount 1 ; sh:maxCount 1 ;
                    sh:severity sh:Violation
                ] .
        ''',
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
from typing import Optional

from rdflib import Graph, URIRef, Literal, RDF, RDFS, XSD
from rdflib.namespace import SH

from .namespaces import CGA, TTL_PREFIXES


@dataclass
class Holon:
    """
    A holonic RDF entity with four named graphs.

    Parameters
    ----------
    iri : str
        The holon's IRI — threads through all four layers.
    label : str
        Human-readable label.
    depth : int
        Nesting depth in the holarchy (root = 0).
    interior_ttl : str, optional
        Turtle content for the interior graph.
    boundary_ttl : str, optional
        Turtle content for the boundary graph (SHACL shapes + portals).
    projection_ttl : str, optional
        Turtle content for the projection graph.
    context_ttl : str, optional
        Turtle content for the context graph.
    """

    iri: str
    label: str
    depth: int = 0
    interior_ttl: Optional[str] = None
    boundary_ttl: Optional[str] = None
    projection_ttl: Optional[str] = None
    context_ttl: Optional[str] = None

    # The four graphs — set in __post_init__
    interior: Graph = field(init=False, repr=False)
    boundary: Graph = field(init=False, repr=False)
    projection: Graph = field(init=False, repr=False)
    context: Graph = field(init=False, repr=False)

    def __post_init__(self):
        self._uri = URIRef(self.iri)

        # Create the four named graphs with conventional IRI suffixes
        self.interior = self._make_graph("interior", self.interior_ttl)
        self.boundary = self._make_graph("boundary", self.boundary_ttl)
        self.projection = self._make_graph("projection", self.projection_ttl)
        self.context = self._make_graph("context", self.context_ttl)

        # Always seed holon identity into the interior
        identity_ttl = f"""
            <{self.iri}> a cga:Holon ;
                rdfs:label "{self.label}"^^xsd:string ;
                cga:holonDepth {self.depth} ;
                cga:interiorGraph   <{self.iri}/interior> ;
                cga:boundaryGraph   <{self.iri}/boundary> ;
                cga:projectionGraph <{self.iri}/projection> ;
                cga:contextGraph    <{self.iri}/context> .
        """
        self._parse_into(self.interior, identity_ttl)

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _make_graph(self, suffix: str, ttl: Optional[str]) -> Graph:
        """Create a named graph and optionally parse TTL into it."""
        g = Graph(identifier=URIRef(f"{self.iri}/{suffix}"))
        self._bind_prefixes(g)
        if ttl:
            self._parse_into(g, ttl)
        return g

    @staticmethod
    def _bind_prefixes(g: Graph):
        """Bind the standard prefixes so serialisation is readable."""
        g.bind("cga", CGA)
        g.bind("sh", SH)
        g.bind("rdfs", RDFS)
        g.bind("xsd", XSD)

    @staticmethod
    def _parse_into(g: Graph, ttl: str):
        """Parse a TTL snippet (with auto-prefixed header) into a graph."""
        full = TTL_PREFIXES + "\n" + ttl
        g.parse(StringIO(full), format="turtle")

    # ------------------------------------------------------------------
    # Layer manipulation
    # ------------------------------------------------------------------

    def load_interior(self, ttl: str):
        """Parse additional TTL into the interior graph."""
        self._parse_into(self.interior, ttl)

    def load_boundary(self, ttl: str):
        """Parse additional TTL into the boundary graph."""
        self._parse_into(self.boundary, ttl)

    def load_projection(self, ttl: str):
        """Parse additional TTL into the projection graph."""
        self._parse_into(self.projection, ttl)

    def load_context(self, ttl: str):
        """Parse additional TTL into the context graph."""
        self._parse_into(self.context, ttl)

    def load_boundary_file(self, path: str):
        """Load SHACL shapes from a .ttl file into the boundary."""
        self.boundary.parse(path, format="turtle")

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def uri(self) -> URIRef:
        return self._uri

    def all_graphs(self) -> list[Graph]:
        return [self.interior, self.boundary, self.projection, self.context]

    def merged_graph(self) -> Graph:
        """Merge all four layers into a single graph."""
        merged = Graph()
        self._bind_prefixes(merged)
        for g in self.all_graphs():
            for t in g:
                merged.add(t)
        return merged

    def serialize_layer(self, layer: str, fmt: str = "turtle") -> str:
        """Serialize one of the four layers to a string."""
        g = getattr(self, layer)
        return g.serialize(format=fmt)

    def __repr__(self):
        counts = ", ".join(
            f"{name}={len(getattr(self, name))}t"
            for name in ("interior", "boundary", "projection", "context")
        )
        return f"Holon({self.label!r}, depth={self.depth}, {counts})"
