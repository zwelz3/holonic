"""
portal.py — Portals for governed traversal between holons.

A Portal is a boundary membrane object that belongs to a source holon
but resolves to a target holon.  Portals carry optional SPARQL CONSTRUCT
queries that *translate* data during traversal — reshaping the source
interior into the target's expected form.

Portal types
------------
Portal              Base class; passthrough traversal.
TransformPortal     Carries a SPARQL CONSTRUCT query and validates the
                    projected output against the target's boundary shapes
                    before delivering it.

Self-describing surface
-----------------------
A TransformPortal can be constructed *from* the target holon's SHACL
shapes: the ``surface`` module inspects the shapes to discover what
properties the target expects, and generates a CONSTRUCT skeleton.
See ``holonic.surface``.

Registration
------------
Creating a portal automatically writes its definition (as TTL) into
the source holon's boundary graph.  The portal itself is a first-class
RDF entity with an IRI that can be referenced in queries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from rdflib import Graph, URIRef, Literal, RDF, RDFS, XSD
from rdflib.namespace import SH

from .holon import Holon
from .namespaces import CGA, TTL_PREFIXES


@dataclass
class Portal:
    """
    Governed traversal between two holons.

    Parameters
    ----------
    iri : str
        The portal's own IRI.
    source : Holon
        The holon whose boundary membrane contains this portal.
    target : Holon
        The holon this portal resolves to.
    label : str
        Human-readable name.
    traversable : bool
        Whether the portal is currently open (False = sealed).
    bidirectional : bool
        If True, the target holon gets a ``cga:exposesPortal`` reference.
    """

    iri: str
    source: Holon
    target: Holon
    label: str = ""
    traversable: bool = True
    bidirectional: bool = False

    def __post_init__(self):
        self._uri = URIRef(self.iri)
        self._register()

    def _register(self):
        """Write the portal definition into the source boundary as TTL."""
        portal_type = "cga:SealedPortal" if not self.traversable else "cga:Portal"
        label_triple = f'    rdfs:label "{self.label}" ;' if self.label else ""

        ttl = f"""
            <{self.iri}> a {portal_type} ;
            {label_triple}
                cga:sourceHolon  <{self.source.iri}> ;
                cga:targetHolon  <{self.target.iri}> ;
                cga:isTraversable {str(self.traversable).lower()} .

            <{self.source.iri}> cga:hasPortal <{self.iri}> .
        """
        self.source.load_boundary(ttl)

        if self.bidirectional:
            expose_ttl = f"""
                <{self.target.iri}> cga:exposesPortal <{self.iri}> .
            """
            self.target.load_boundary(expose_ttl)

    @property
    def uri(self) -> URIRef:
        return self._uri

    def traverse(self, data: Graph) -> Optional[Graph]:
        """
        Cross the portal.  Base implementation is a passthrough.

        Parameters
        ----------
        data : Graph
            RDF graph to pass through the portal (typically the source interior).

        Returns
        -------
        Graph or None
            The (possibly transformed) graph, or None if sealed.
        """
        if not self.traversable:
            return None
        result = Graph()
        for t in data:
            result.add(t)
        return result

    def __repr__(self):
        state = "sealed" if not self.traversable else "open"
        return f"Portal({self.label!r}, {self.source.label!r} → {self.target.label!r}, {state})"


@dataclass
class TransformPortal(Portal):
    """
    A portal that carries a SPARQL CONSTRUCT query for data translation.

    The CONSTRUCT reshapes triples from the source's vocabulary into the
    target's expected vocabulary.  After projection, the result can be
    validated against the target's boundary shapes.

    Parameters
    ----------
    construct_query : str
        A SPARQL CONSTRUCT query.  It is executed against the incoming
        data graph during traversal.
    validate_output : bool
        If True, validate the projected output against the target's
        boundary SHACL shapes before returning.  A validation failure
        raises ``MembraneBreachError``.
    """

    construct_query: str = ""
    validate_output: bool = False

    def __post_init__(self):
        super().__post_init__()
        # additionally register the transform spec in the boundary
        if self.construct_query:
            # Escape the query for embedding in TTL
            escaped = self.construct_query.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            ttl = f"""
                <{self.iri}> a cga:TransformPortal ;
                    cga:transformSpec \"\"\"{escaped}\"\"\" .
            """
            self.source.load_boundary(ttl)

    def traverse(self, data: Graph) -> Optional[Graph]:
        """
        Cross the portal, applying the SPARQL CONSTRUCT to translate data.

        The query is executed against ``data``.  If ``validate_output``
        is True, the projected graph is validated against the target
        holon's boundary shapes.

        Returns
        -------
        Graph or None
            Projected graph, or None if sealed.

        Raises
        ------
        MembraneBreachError
            If validation is enabled and the output violates the target shapes.
        """
        if not self.traversable:
            return None

        if not self.construct_query:
            return super().traverse(data)

        result = Graph()
        Holon._bind_prefixes(result)

        # Execute the CONSTRUCT
        qres = data.query(self.construct_query)
        for triple in qres:
            result.add(triple)

        # Optionally validate against target boundary
        if self.validate_output and len(self.target.boundary) > 0:
            from .membrane import validate_membrane_raw, MembraneHealth
            mr = validate_membrane_raw(result, self.target.boundary)
            if mr.health == MembraneHealth.COMPROMISED:
                raise MembraneBreachError(
                    f"Portal {self.label!r} output violates target membrane:\n"
                    + "\n".join(f"  ✗ {v}" for v in mr.violations)
                )

        return result

    def __repr__(self):
        state = "sealed" if not self.traversable else "open"
        has_q = "CONSTRUCT" if self.construct_query else "passthrough"
        return (
            f"TransformPortal({self.label!r}, "
            f"{self.source.label!r} → {self.target.label!r}, {state}, {has_q})"
        )


class MembraneBreachError(Exception):
    """Raised when a portal's projected output violates the target membrane."""
