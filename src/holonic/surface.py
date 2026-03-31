"""
surface.py — Self-describing portal surface.

The key idea: a target holon's SHACL shapes are a machine-readable
specification of what data it accepts.  By querying those shapes, a
source holon can *discover* the target's expected structure and
auto-generate a SPARQL CONSTRUCT query skeleton for the portal.

This is what makes the holonic membrane self-describing: the shapes
are not just validators, they are the API contract.

Functions
---------
discover_target_shape(target)
    Query a target holon's boundary to extract the properties and
    constraints it declares.  Returns a list of ``ShapeProperty``
    descriptors.

generate_construct_query(source_class, target_class, property_map, prefixes)
    Generate a SPARQL CONSTRUCT query that translates triples typed
    as ``source_class`` into triples typed as ``target_class``, mapping
    properties according to ``property_map``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rdflib import Graph, URIRef, Literal
from rdflib.namespace import SH, RDF, RDFS, XSD

from .holon import Holon


@dataclass
class ShapeProperty:
    """A property constraint extracted from a SHACL NodeShape."""
    path: str                      # The sh:path IRI
    datatype: Optional[str] = None # sh:datatype, if declared
    node_kind: Optional[str] = None # sh:nodeKind, if declared
    min_count: Optional[int] = None
    max_count: Optional[int] = None
    severity: str = "Violation"
    message: str = ""
    class_constraint: Optional[str] = None  # sh:class
    in_values: list[str] = None  # sh:in

    def __post_init__(self):
        if self.in_values is None:
            self.in_values = []

    @property
    def is_required(self) -> bool:
        return self.min_count is not None and self.min_count > 0

    @property
    def path_local(self) -> str:
        """Extract the local name from the path IRI."""
        for sep in ("#", "/", ":"):
            if sep in self.path:
                return self.path.rsplit(sep, 1)[-1]
        return self.path


def discover_target_shape(
    target: Holon,
    target_class: Optional[str] = None,
) -> dict[str, list[ShapeProperty]]:
    """
    Inspect a target holon's boundary shapes to discover its expected
    data structure.

    Parameters
    ----------
    target : Holon
        The target holon whose boundary shapes to inspect.
    target_class : str, optional
        If given, only return shapes targeting this class.
        Otherwise, return all shapes found.

    Returns
    -------
    dict[str, list[ShapeProperty]]
        Mapping from target class IRI to list of ShapeProperty descriptors.
    """
    query = """
    PREFIX sh:   <http://www.w3.org/ns/shacl#>
    PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

    SELECT ?shape ?targetClass ?path ?datatype ?nodeKind
           ?minCount ?maxCount ?severity ?message ?classConstraint
    WHERE {
        ?shape a sh:NodeShape .

        # Get target class
        {
            ?shape sh:targetClass ?targetClass .
        } UNION {
            ?shape sh:targetSubjectsOf ?targetPred .
            BIND(?targetPred AS ?targetClass)
        }

        # Get property constraints
        ?shape sh:property ?propNode .
        ?propNode sh:path ?path .

        OPTIONAL { ?propNode sh:datatype ?datatype }
        OPTIONAL { ?propNode sh:nodeKind ?nodeKind }
        OPTIONAL { ?propNode sh:minCount ?minCount }
        OPTIONAL { ?propNode sh:maxCount ?maxCount }
        OPTIONAL { ?propNode sh:severity ?severity }
        OPTIONAL { ?propNode sh:message  ?message }
        OPTIONAL { ?propNode sh:class    ?classConstraint }
    }
    ORDER BY ?targetClass ?path
    """

    results: dict[str, list[ShapeProperty]] = {}

    for row in target.boundary.query(query):
        cls = str(row.targetClass)

        if target_class and cls != target_class:
            continue

        sp = ShapeProperty(
            path=str(row.path),
            datatype=str(row.datatype) if row.datatype else None,
            node_kind=str(row.nodeKind) if row.nodeKind else None,
            min_count=int(row.minCount) if row.minCount is not None else None,
            max_count=int(row.maxCount) if row.maxCount is not None else None,
            severity=str(row.severity).rsplit("#", 1)[-1] if row.severity else "Violation",
            message=str(row.message) if row.message else "",
            class_constraint=str(row.classConstraint) if row.classConstraint else None,
        )

        results.setdefault(cls, []).append(sp)

    return results


def generate_construct_query(
    source_class: str,
    target_class: str,
    property_map: dict[str, str],
    prefixes: str = "",
) -> str:
    """
    Generate a SPARQL CONSTRUCT query that translates data between
    two representations.

    Parameters
    ----------
    source_class : str
        The rdf:type of the source data (e.g. "msg:UCIPlatformStatus").
    target_class : str
        The rdf:type to assign in the output (e.g. "mil:AirPositionReport").
    property_map : dict[str, str]
        Mapping from source property to target property.
        Keys are source predicates, values are target predicates.
        If key == value, the property passes through unchanged.
    prefixes : str
        SPARQL PREFIX declarations to prepend.

    Returns
    -------
    str
        A complete SPARQL CONSTRUCT query.

    Example
    -------
    >>> q = generate_construct_query(
    ...     source_class="ex:CityData",
    ...     target_class="geo:City",
    ...     property_map={
    ...         "ex:cityName": "rdfs:label",
    ...         "ex:pop": "geo:population",
    ...         "ex:lat": "geo:latitude",
    ...     },
    ...     prefixes="PREFIX ex: <urn:ex:>\\nPREFIX geo: <urn:geo:>",
    ... )
    """
    # Build variable names from target local names
    var_map = {}
    for src, tgt in property_map.items():
        local = tgt.rsplit(":", 1)[-1] if ":" in tgt else tgt.rsplit("/", 1)[-1]
        var_map[src] = (tgt, f"?{local}")

    # CONSTRUCT clause
    construct_lines = [f"    ?s a {target_class} ."]
    for src, (tgt, var) in var_map.items():
        construct_lines.append(f"    ?s {tgt} {var} .")

    # WHERE clause
    where_required = [f"    ?s a {source_class} ."]
    where_optional = []

    for src, (tgt, var) in var_map.items():
        # First property is required (anchors the pattern); rest are optional
        if not where_required or len(where_required) <= 1:
            where_required.append(f"    ?s {src} {var} .")
        else:
            where_optional.append(f"    OPTIONAL {{ ?s {src} {var} }}")

    construct_block = "\n".join(construct_lines)
    where_block = "\n".join(where_required + where_optional)

    return f"""{prefixes}
        CONSTRUCT {{
        {construct_block}
        }}
        WHERE {{
        {where_block}
        }}
    """


def describe_surface(target: Holon, target_class: Optional[str] = None) -> str:
    """
    Human-readable description of a target holon's expected data surface.

    Useful for understanding what a portal needs to produce.
    """
    shapes = discover_target_shape(target, target_class)
    lines = [f"Surface of {target.label!r}:"]

    for cls, props in shapes.items():
        cls_short = cls.rsplit("/", 1)[-1] if "/" in cls else cls.rsplit(":", 1)[-1]
        lines.append(f"\n  Target class: {cls_short} ({cls})")

        for p in sorted(props, key=lambda x: (not x.is_required, x.path)):
            req = "REQUIRED" if p.is_required else "optional"
            dt = f" [{p.datatype.rsplit('#', 1)[-1]}]" if p.datatype else ""
            sev = f" ({p.severity})" if p.severity != "Violation" else ""
            lines.append(f"    {p.path_local:<25s} {req:<10s}{dt}{sev}")
            if p.message:
                lines.append(f"      └─ {p.message}")

    return "\n".join(lines)
