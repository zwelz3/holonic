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

from rdflib import Graph

from holonic import sparql as Q
from holonic.model import MembraneHealth, MembraneResult

if TYPE_CHECKING:
    from holonic.client import HolonicDataset

log = logging.getLogger(__name__)


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


class MembraneValidator:
    """SHACL validation of holon interiors against their boundaries.

    Constructed once per :class:`~holonic.client.HolonicDataset` and
    reached via ``ds._membrane``. Public dataset methods delegate here.
    """

    def __init__(self, ds: HolonicDataset):
        self._ds = ds

    def validate_membrane(self, holon_iri: str) -> MembraneResult:
        """Validate a holon's interior(s) against its boundary shape(s).

        Collects all cga:hasInterior graphs as data and all cga:hasBoundary
        graphs as shapes, then runs pyshacl.
        """
        import pyshacl

        from holonic.client import _bind_iri, _parse_shacl_report

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

        conforms, report_graph, report_text = pyshacl.validate(
            data_graph,
            shacl_graph=shapes_graph,
        )

        # Parse violations and warnings from the structured report graph
        violations, warnings, shape_violations = _parse_shacl_report(
            report_graph,
        )

        if violations:
            health = MembraneHealth.COMPROMISED
        elif warnings:
            health = MembraneHealth.WEAKENED
        else:
            health = MembraneHealth.INTACT

        result = MembraneResult(
            holon_iri=holon_iri,
            conforms=conforms,
            health=health,
            report_text=report_text,
            violations=violations,
            warnings=warnings,
            shape_violations=shape_violations,
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


__all__ = ["MembraneValidator", "no_shapes_report"]
