"""Membrane (SHACL boundary) validation (0.8.0).

Extracted from :class:`holonic.client.HolonicDataset` as part of the
0.8.0 god-class decomposition (AR1/CQ1). This module owns membrane
validation: collecting a holon's ``cga:hasInterior`` graphs as the data
graph and its ``cga:hasBoundary`` graphs as the shapes graph, running
pyshacl over the pair, and classifying the outcome into a
:class:`~holonic.model.MembraneHealth`.

The validator holds a back-reference to its owning ``HolonicDataset``
(``self._ds``) rather than a bare backend, because validation reaches
back into the facade for the shared layer-materialization helper
(``_safe_layer_graph``) and for the validation notification hooks
(``_on_validation``). This mirrors :class:`holonic._pipelines.PipelineManager`
and :class:`holonic._console.ConsoleReads`.

``HolonicDataset`` keeps thin delegating wrappers for the public methods
(``validate_membrane``, ``validate_all``), so the public API is unchanged.

:func:`no_shapes_report` is a module-level function rather than a method
because two clusters need it: validation itself, and the traversal
cluster's ``dry_run`` preflight. Keeping it at module scope avoids one
delegate reaching through the facade into another.

.. versionadded:: 0.8.0
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rdflib import OWL, RDF, RDFS, Graph, Namespace, URIRef
from rdflib.term import Node

from holonic import sparql as Q
from holonic.model import MembraneHealth, MembraneResult, UntargetedNode

if TYPE_CHECKING:
    from holonic.client import HolonicDataset

log = logging.getLogger(__name__)

SH = Namespace("http://www.w3.org/ns/shacl#")
CGA = Namespace("urn:holonic:ontology:")


def no_shapes_report(missing: list[str]) -> str:
    """Explain an empty shapes graph, naming unmaterialized layers.

    "No boundary shapes defined" and "every boundary graph a holon
    registered is empty" are operationally different situations that
    produce an identical INTACT result; the report text is the only
    place the difference survives.
    """
    if not missing:
        return "No boundary shapes defined."
    return (
        f"No boundary shapes defined: {len(missing)} registered boundary "
        f"graph(s) hold no triples ({', '.join(sorted(missing))})."
    )


def run_shacl(data: Graph, shapes: Graph) -> tuple[bool, Graph, str]:
    """Run pyshacl the one way membrane validation and ``dry_run`` both use.

    ``allow_infos=True`` makes ``conforms`` false only for results above
    ``sh:Info``, matching membrane health, which Info results never lower
    (R3.6). Before 0.9.0 ``dry_run`` passed the flag and ``validate_membrane``
    did not, so the two disagreed on ``conforms`` for an Info-only report.

    .. versionadded:: 0.9.0
    """
    import pyshacl

    conforms, report_graph, report_text = pyshacl.validate(
        data, shacl_graph=shapes, allow_infos=True
    )
    return bool(conforms), report_graph, str(report_text)


def _is_shape(shapes: Graph, node: Node) -> bool:
    return (node, RDF.type, SH.NodeShape) in shapes or (node, RDF.type, SH.PropertyShape) in shapes


def find_untargeted(
    data: Graph,
    shapes: Graph,
    permitted: set[URIRef],
    candidates: set[Node] | None = None,
) -> list[tuple[Node, list[str]]] | None:
    """Return the typed nodes in ``data`` that no shape in ``shapes`` targets.

    A node is targeted when it is a SHACL instance (``rdf:type`` followed by
    ``rdfs:subClassOf*`` in the data graph) of a class named by
    ``sh:targetClass`` or of a shape that is itself an ``rdfs:Class`` or
    ``owl:Class`` (an implicit class target, as pyshacl applies it), when it
    is named by ``sh:targetNode``, or when it is the subject of a predicate
    named by ``sh:targetSubjectsOf`` or the object of one named by
    ``sh:targetObjectsOf``. A node that is an instance of a class in
    ``permitted`` is treated as targeted.

    ``candidates`` restricts the check to those nodes; by default every
    subject of an ``rdf:type`` triple in ``data`` is checked.

    Returns ``None`` when a shape uses a SPARQL-based target (``sh:target``),
    whose focus nodes cannot be determined without running it; the caller
    reports nothing rather than guessing.

    .. versionadded:: 0.9.0
    """
    if next(shapes.objects(None, SH.target), None) is not None:
        log.debug("find_untargeted: SPARQL-based target present, check skipped")
        return None

    covered = set(permitted) | {c for c in shapes.objects(None, SH.targetClass)}
    for class_type in (RDFS.Class, OWL.Class):
        covered |= {s for s in shapes.subjects(RDF.type, class_type) if _is_shape(shapes, s)}
    target_nodes = set(shapes.objects(None, SH.targetNode))
    subjects_of = set(shapes.objects(None, SH.targetSubjectsOf))
    objects_of = set(shapes.objects(None, SH.targetObjectsOf))

    superclass_cache: dict[Node, set[Node]] = {}

    def superclasses(cls: Node) -> set[Node]:
        if cls not in superclass_cache:
            superclass_cache[cls] = set(data.transitive_objects(cls, RDFS.subClassOf))
        return superclass_cache[cls]

    nodes = candidates if candidates is not None else set(data.subjects(RDF.type, None))
    found: list[tuple[Node, list[str]]] = []
    for node in sorted(nodes, key=str):
        types = set(data.objects(node, RDF.type))
        if not types or node in target_nodes:
            continue
        if any((node, p, None) in data for p in subjects_of):
            continue
        if any((None, p, node) in data for p in objects_of):
            continue
        if any(superclasses(t) & covered for t in types):
            continue
        found.append((node, sorted(str(t) for t in types)))
    return found


def untargeted_policy(shapes: Graph, holon: URIRef) -> tuple[set[URIRef], Node | None]:
    """Read a holon's permitted types and untargeted-node severity.

    Both are declared in the holon's boundary graphs, with the holon as
    subject: ``cga:permitsType`` names a class whose instances need no
    targeting shape, and ``cga:untargetedTypeSeverity`` names the
    severity (``sh:Violation``, ``sh:Warning``, or ``sh:Info``) at which an
    untargeted node is reported.

    .. versionadded:: 0.9.0
    """
    permitted = {t for t in shapes.objects(holon, CGA.permitsType) if isinstance(t, URIRef)}
    return permitted, shapes.value(holon, CGA.untargetedTypeSeverity)


def untargeted_severity_label(declared: Node | None, default: str) -> str:
    """Resolve a declared severity, failing closed as R3.6 does for SHACL results."""
    from holonic.client import _SEVERITY_LABELS

    if declared is None:
        return default
    return (
        _SEVERITY_LABELS.get(declared, "Violation") if isinstance(declared, URIRef) else "Violation"
    )


class MembraneValidator:
    """SHACL validation of holon interiors against their boundaries.

    Constructed once per :class:`~holonic.client.HolonicDataset` and
    reached via ``ds._membrane``. Public dataset methods delegate here.
    """

    def __init__(self, ds: HolonicDataset):
        self._ds = ds

    def validate_membrane(self, holon_iri: str, *, injected: Graph | None = None) -> MembraneResult:
        """Validate a holon's interior(s) against its boundary shape(s).

        Collects all cga:hasInterior graphs as data and all cga:hasBoundary
        graphs as shapes, then runs pyshacl. Typed interior nodes that no
        boundary shape targets are reported in ``result.untargeted``
        (:func:`find_untargeted`), at the holon's declared
        ``cga:untargetedTypeSeverity`` or ``sh:Info`` by default.

        ``injected`` is the triples a fail-closed traversal just added. When
        given, only the typed subjects of those triples are checked for
        targeting, and the default severity is ``sh:Violation``, so a portal
        that injects a type no shape covers breaches the membrane while nodes
        already in the interior do not.
        """
        from holonic.client import _bind_iri, _health_from_report, _parse_shacl_report

        log.debug("validate_membrane(%s)", holon_iri)

        # Collect interior graphs (union)
        interior_rows = self._ds.backend.query(Q.GET_HOLON_INTERIORS, holon=_bind_iri(holon_iri))
        data_graph = Graph()
        for row in interior_rows:
            g = self._ds._safe_layer_graph(row["graph"])
            for triple in g:
                data_graph.add(triple)

        # Collect boundary graphs (union)
        boundary_rows = self._ds.backend.query(Q.GET_HOLON_BOUNDARIES, holon=_bind_iri(holon_iri))
        shapes_graph = Graph()
        missing_boundaries: list[str] = []
        for row in boundary_rows:
            g = self._ds._safe_layer_graph(row["graph"], missing=missing_boundaries)
            for triple in g:
                shapes_graph.add(triple)

        if len(shapes_graph) == 0:
            return MembraneResult(
                holon_iri=holon_iri,
                conforms=True,
                health=MembraneHealth.INTACT,
                report_text=no_shapes_report(missing_boundaries),
            )

        conforms, report_graph, report_text = run_shacl(data_graph, shapes_graph)

        # Parse violations and warnings from the structured report graph
        report = _parse_shacl_report(report_graph)

        permitted, declared = untargeted_policy(shapes_graph, _bind_iri(holon_iri))
        severity = untargeted_severity_label(
            declared, "Violation" if injected is not None else "Info"
        )
        candidates = set(injected.subjects(RDF.type, None)) if injected is not None else None
        found = find_untargeted(data_graph, shapes_graph, permitted, candidates) or []
        untargeted = [UntargetedNode(str(n), types, severity) for n, types in found]
        health = _health_from_report(report, untargeted)

        result = MembraneResult(
            holon_iri=holon_iri,
            conforms=conforms,
            health=health,
            report_text=report_text,
            violations=report.violations,
            warnings=report.warnings,
            infos=report.infos,
            shape_violations=report.shape_violations,
            untargeted=untargeted,
        )

        # Fire notification hooks
        for hook in self._ds._on_validation:
            hook(holon_iri, result)

        return result

    def validate_all(self) -> dict[str, MembraneResult]:
        """Validate membranes for all holons in the holarchy.

        Returns a dict mapping holon IRI to its
        :class:`MembraneResult`. Holons without boundary shapes
        still appear in the result (they will be INTACT with
        ``conforms=True``).

        .. versionadded:: 0.6.0
        """
        results = {}
        for holon in self._ds.iter_holons():
            results[holon.iri] = self.validate_membrane(holon.iri)
        return results


__all__ = [
    "MembraneValidator",
    "find_untargeted",
    "no_shapes_report",
    "run_shacl",
    "untargeted_policy",
    "untargeted_severity_label",
]
