"""PROV-O provenance recording and audit queries (0.8.0).

Extracted from :class:`holonic.client.HolonicDataset` as part of the
0.8.0 god-class decomposition (AR1/CQ1). This module owns the
provenance cluster: writing ``prov:Activity`` records for traversals
and validations into a holon's context graph, and reading them back as
audit trails, activity detail, derivation chains, and per-portal
history. It also owns fail-closed rollback, which is a provenance
operation in both directions -- it reads the recorded delta and writes
a compensating record.

The log holds a back-reference to its owning ``HolonicDataset``
(``self._ds``) rather than a bare backend, because recording reaches
into the facade's layer-registration and metadata-refresh machinery
(``_register_layer`` / ``_maybe_refresh``) and audit reads consult
membrane validation for surface reports. This mirrors
:class:`holonic._pipelines.PipelineManager` and
:class:`holonic._console.ConsoleReads`.

``HolonicDataset`` keeps thin delegating wrappers for every public
method here (``record_traversal``, ``record_validation``,
``collect_audit_trail``, ``portal_traversal_history``,
``get_activity``, ``last_traversal``, ``derivation_chain``,
``rollback_traversal``), so the public API is unchanged.

.. versionadded:: 0.8.0
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from holonic import sparql as Q
from holonic.model import (
    AuditTrail,
    MembraneHealth,
    SurfaceReport,
    TraversalRecord,
    ValidationRecord,
)

if TYPE_CHECKING:
    from holonic.client import HolonicDataset

log = logging.getLogger(__name__)


class ProvenanceLog:
    """See module docstring. Reached via ``ds._provenance``."""

    def __init__(self, ds: HolonicDataset):
        self._ds = ds

    def record_traversal(
        self,
        portal_iri: str,
        source_iri: str,
        target_iri: str,
        agent_iri: str,
        *,
        context_graph: str | None = None,
    ) -> str:
        """Record a portal traversal as a PROV-O Activity via SPARQL UPDATE."""
        from holonic.client import _escape_ttl, _validate_iri

        # Every value below is interpolated into a SPARQL UPDATE template:
        # the four IRIs land inside <...> slots and portal_iri is embedded
        # in a quoted label. Validate the IRIs (reject <>"{} whitespace) and
        # escape the label so neither can break out of its slot.
        _validate_iri(portal_iri, "portal_iri")
        _validate_iri(source_iri, "source_iri")
        _validate_iri(target_iri, "target_iri")
        _validate_iri(agent_iri, "agent_iri")
        activity_iri = f"urn:prov:traversal:{uuid.uuid4().hex[:12]}"
        context_graph = context_graph or f"{target_iri}/context"
        _validate_iri(context_graph, "context_graph")
        ts = datetime.now(UTC).isoformat()

        update = Q.RECORD_TRAVERSAL.format(
            context_graph=context_graph,
            activity_iri=activity_iri,
            label=_escape_ttl(f"Portal traversal via {portal_iri}"),
            agent_iri=agent_iri,
            source_iri=source_iri,
            target_iri=target_iri,
            timestamp=ts,
        )
        self._ds.backend.update(update)

        # Register context graph if not already
        self._ds._register_layer(target_iri, context_graph, "hasContext")
        return activity_iri

    def record_validation(
        self,
        holon_iri: str,
        health: MembraneHealth,
        agent_iri: str,
        *,
        context_graph: str | None = None,
    ) -> str:
        """Record a membrane validation as a PROV-O Activity."""
        from holonic.client import _validate_iri

        # holon_iri, agent_iri and context_graph are interpolated into <...>
        # slots of a SPARQL UPDATE template; validate before use. health_iri
        # and activity_iri are derived from a trusted enum / a generated UUID.
        _validate_iri(holon_iri, "holon_iri")
        _validate_iri(agent_iri, "agent_iri")
        activity_iri = f"urn:prov:validation:{uuid.uuid4().hex[:12]}"
        context_graph = context_graph or f"{holon_iri}/context"
        _validate_iri(context_graph, "context_graph")
        ts = datetime.now(UTC).isoformat()

        health_iri = f"urn:holonic:ontology:{health.value.capitalize()}"
        update = Q.RECORD_VALIDATION.format(
            context_graph=context_graph,
            activity_iri=activity_iri,
            agent_iri=agent_iri,
            holon_iri=holon_iri,
            health_iri=health_iri,
            timestamp=ts,
        )
        self._ds.backend.update(update)
        self._ds._register_layer(holon_iri, context_graph, "hasContext")
        return activity_iri

    def _build_surface_report(self, holon_iri: str) -> SurfaceReport | None:
        """Build a surface report from a holon's boundary shapes."""
        from holonic.client import _bind_iri

        boundary_rows = self._ds.backend.query(Q.GET_HOLON_BOUNDARIES, holon=_bind_iri(holon_iri))
        if not boundary_rows:
            return None

        # Query the shapes for required/optional fields
        report = SurfaceReport(holon_iri=holon_iri)
        for row in boundary_rows:
            shape_rows = self._ds.backend.query(f"""
                PREFIX sh: <http://www.w3.org/ns/shacl#>
                SELECT ?shape ?target_class ?path ?min_count ?severity
                WHERE {{
                    GRAPH <{row["graph"]}> {{
                        ?shape a sh:NodeShape .
                        OPTIONAL {{ ?shape sh:targetClass ?target_class }}
                        OPTIONAL {{
                            ?shape sh:property ?prop .
                            ?prop sh:path ?path .
                            OPTIONAL {{ ?prop sh:minCount ?min_count }}
                            OPTIONAL {{ ?prop sh:severity ?severity }}
                        }}
                    }}
                }}
            """)
            for sr in shape_rows:
                if sr.get("target_class"):
                    tc = sr["target_class"]
                    if tc not in report.target_classes:
                        report.target_classes.append(tc)
                if sr.get("path"):
                    path = sr["path"]
                    path_short = path.rsplit(":", 1)[-1] if ":" in path else path
                    min_c = sr.get("min_count")
                    sev = str(sr.get("severity", ""))
                    if min_c and int(min_c) > 0:
                        report.required_fields.append(path_short)
                    else:
                        report.optional_fields.append(path_short)
                    if "Violation" in sev:
                        report.violations += 0  # counted at validation time
        return report

    def collect_audit_trail(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
        since: str | None = None,
        kind: str | None = None,
    ) -> AuditTrail:
        """Collect the provenance audit trail from context graphs.

        Queries all PROV-O activities across every context graph in the
        dataset, correlates traversals with validations, and builds
        surface reports from boundary shapes.

        Parameters
        ----------
        limit :
            Maximum number of activities to return. None means all.
        offset :
            Number of activities to skip. None means 0.
        since :
            ISO-8601 timestamp. Only return activities started after
            this time. Pushed to the SPARQL engine via FILTER.
        kind :
            Filter by activity type: ``'traversal'`` or
            ``'validation'``. None means both.

        Returns:
        -------
        AuditTrail

        Raises:
        ------
        ValueError
            If ``since`` is not a well-formed ``xsd:dateTime``.

        .. versionchanged:: 0.7.0
            Added ``limit``, ``offset``, ``since``, ``kind``.

        .. versionchanged:: 0.8.0
            ``since`` is validated as an ``xsd:dateTime`` and emitted
            through rdflib's ``n3()`` instead of being interpolated raw
            into the ``FILTER``. A malformed value now raises
            ``ValueError`` rather than reaching the SPARQL engine.
        """
        from holonic.client import _xsd_datetime_literal

        traversals = []
        validations = []

        # Validated once, before either branch: both queries splice the
        # same literal, and a bad value should fail before any I/O.
        # Note `is not None`, not truthiness: `since=""` used to build
        # FILTER(?timestamp > ""^^xsd:dateTime), an ill-typed comparison
        # that silently matched nothing. It is now a ValueError.
        since_literal = _xsd_datetime_literal(since) if since is not None else None

        if kind in (None, "traversal"):
            tq = Q.COLLECT_TRAVERSALS
            # Strip existing ORDER BY clause for re-ordering
            if "ORDER BY" in tq:
                tq = tq[: tq.index("ORDER BY")].rstrip()
            if since_literal:
                # Insert FILTER before closing }
                tq = tq.rstrip().rstrip("}")
                tq += f"  FILTER(?timestamp > {since_literal})\n}}\n"
            tq += "\nORDER BY DESC(?timestamp)"
            if limit is not None:
                tq += f"\nLIMIT {int(limit)}"
            if offset is not None:
                tq += f"\nOFFSET {int(offset)}"

            traversals = [
                TraversalRecord(
                    activity_iri=r["activity"],
                    source_iri=r["source"],
                    target_iri=r["target"],
                    agent_iri=r.get("agent"),
                    portal_label=r.get("label"),
                    timestamp=r.get("timestamp"),
                )
                for r in self._ds.backend.query(tq)
            ]

        if kind in (None, "validation"):
            vq = Q.COLLECT_VALIDATIONS
            # Strip existing ORDER BY clause
            if "ORDER BY" in vq:
                vq = vq[: vq.index("ORDER BY")].rstrip()
            if since_literal:
                vq = vq.rstrip().rstrip("}")
                vq += f"  FILTER(?timestamp > {since_literal})\n}}\n"
            vq += "\nORDER BY DESC(?timestamp)"
            if limit is not None:
                vq += f"\nLIMIT {int(limit)}"
            if offset is not None:
                vq += f"\nOFFSET {int(offset)}"

            validations = [
                ValidationRecord(
                    activity_iri=r["activity"],
                    holon_iri=r["holon"],
                    health=r["health"],
                    agent_iri=r.get("agent"),
                    timestamp=r.get("timestamp"),
                )
                for r in self._ds.backend.query(vq)
            ]

        # Collect derivation chain
        derivation_rows = self._ds.backend.query(Q.COLLECT_DERIVATION_CHAIN)
        derivations = [(r["derived"], r["source"]) for r in derivation_rows]

        # Build surface reports for participating holons
        participating = set()
        for t in traversals:
            participating.add(t.source_iri)
            participating.add(t.target_iri)

        surfaces: dict[str, SurfaceReport] = {}
        for holon_iri in participating:
            report = self._build_surface_report(holon_iri)
            if report:
                surfaces[holon_iri] = report

        return AuditTrail(
            traversals=traversals,
            validations=validations,
            derivation_chain=derivations,
            surfaces=surfaces,
        )

    def portal_traversal_history(
        self,
        portal_iri: str,
        limit: int = 50,
    ) -> list[TraversalRecord]:
        """Return recorded traversals attributable to a single portal.

        See note in ``sparql.py`` PORTAL_TRAVERSAL_HISTORY_TEMPLATE --
        scoped by (source, target) pair, since the current provenance
        schema does not store the portal IRI as a structured triple.
        Returns an empty list if the portal is not registered.
        """
        portal = self._ds.get_portal(portal_iri)
        if portal is None:
            return []

        # Clamp limit defensively -- runaway value would let a caller
        # pull the full audit history.
        safe_limit = max(1, min(int(limit), 10_000))

        q = Q.PORTAL_TRAVERSAL_HISTORY_TEMPLATE.format(
            source_iri=portal.source_iri,
            target_iri=portal.target_iri,
            limit=safe_limit,
        )
        rows = self._ds.backend.query(q)
        return [
            TraversalRecord(
                activity_iri=r["activity"],
                source_iri=portal.source_iri,
                target_iri=portal.target_iri,
                agent_iri=r.get("agent"),
                portal_label=r.get("label"),
                timestamp=r.get("timestamp"),
            )
            for r in rows
        ]

    def get_activity(
        self,
        activity_iri: str,
    ) -> TraversalRecord | ValidationRecord | None:
        """Look up a single provenance activity by IRI.

        Returns a :class:`TraversalRecord` if the activity has
        ``prov:used`` and ``prov:generated`` predicates (indicating
        a portal traversal), a :class:`ValidationRecord` if it has
        ``cga:validatedHolon``, or None if not found.

        .. versionadded:: 0.7.0
        """
        # Try as traversal first
        rows = self._ds.backend.query(f"""
            PREFIX prov: <http://www.w3.org/ns/prov#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?source ?target ?agent ?label ?timestamp
            WHERE {{
                GRAPH ?g {{
                    <{activity_iri}> a prov:Activity ;
                        prov:used ?source ;
                        prov:generated ?target .
                    OPTIONAL {{
                        <{activity_iri}> prov:wasAssociatedWith ?agent
                    }}
                    OPTIONAL {{
                        <{activity_iri}> rdfs:label ?label
                    }}
                    OPTIONAL {{
                        <{activity_iri}> prov:startedAtTime ?timestamp
                    }}
                }}
            }} LIMIT 1
        """)
        if rows:
            r = rows[0]
            return TraversalRecord(
                activity_iri=activity_iri,
                source_iri=r["source"],
                target_iri=r["target"],
                agent_iri=r.get("agent"),
                portal_label=r.get("label"),
                timestamp=r.get("timestamp"),
            )

        # Try as validation
        rows = self._ds.backend.query(f"""
            PREFIX prov: <http://www.w3.org/ns/prov#>
            PREFIX cga:  <urn:holonic:ontology:>
            SELECT ?holon ?health ?agent ?timestamp WHERE {{
                GRAPH ?g {{
                    <{activity_iri}> a prov:Activity ;
                        cga:validatedHolon ?holon ;
                        cga:membraneHealth ?health .
                    OPTIONAL {{
                        <{activity_iri}> prov:wasAssociatedWith ?agent
                    }}
                    OPTIONAL {{
                        <{activity_iri}> prov:startedAtTime ?timestamp
                    }}
                }}
            }} LIMIT 1
        """)
        if rows:
            r = rows[0]
            return ValidationRecord(
                activity_iri=activity_iri,
                holon_iri=r["holon"],
                health=r["health"],
                agent_iri=r.get("agent"),
                timestamp=r.get("timestamp"),
            )

        return None

    def last_traversal(self, holon_iri: str) -> TraversalRecord | None:
        """Return the most recent traversal targeting a given holon.

        Unlike ``portal_traversal_history()`` (which requires knowing
        the portal IRI), this finds the latest traversal into
        ``holon_iri`` regardless of which portal was used.

        Returns None if no traversal has been recorded.

        .. versionadded:: 0.6.0
        """
        # Provenance pattern: activity prov:generated <target>,
        # prov:used <source>, stored in target's context graph.
        q = f"""
            PREFIX prov: <http://www.w3.org/ns/prov#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

            SELECT ?activity ?source ?agent ?label ?timestamp
            WHERE {{
                GRAPH ?g {{
                    ?activity a prov:Activity ;
                        prov:generated <{holon_iri}> ;
                        prov:used ?source .
                    OPTIONAL {{ ?activity prov:wasAssociatedWith ?agent }}
                    OPTIONAL {{ ?activity rdfs:label ?label }}
                    OPTIONAL {{ ?activity prov:startedAtTime ?timestamp }}
                }}
            }}
            ORDER BY DESC(?timestamp)
            LIMIT 1
        """
        rows = self._ds.backend.query(q)
        if not rows:
            return None
        r = rows[0]
        return TraversalRecord(
            activity_iri=r["activity"],
            source_iri=r.get("source", ""),
            target_iri=holon_iri,
            agent_iri=r.get("agent"),
            portal_label=r.get("label"),
            timestamp=r.get("timestamp"),
        )

    def derivation_chain(self, holon_iri: str) -> list[str]:
        """Return upstream holon IRIs in derivation order.

        Walks the ``prov:wasDerivedFrom`` chain backward from
        ``holon_iri`` to find all holons that contributed data
        (directly or transitively) via portal traversals. Returns
        a list of holon IRIs (most direct source first).

        .. versionadded:: 0.6.0
        """
        chain: list[str] = []
        visited = {holon_iri}
        frontier = [holon_iri]

        while frontier:
            current = frontier.pop(0)
            q = f"""
                PREFIX prov: <http://www.w3.org/ns/prov#>
                SELECT DISTINCT ?source WHERE {{
                    GRAPH ?g {{
                        <{current}> prov:wasDerivedFrom ?source .
                    }}
                }}
            """
            rows = self._ds.backend.query(q)
            for r in rows:
                src = r["source"]
                if src not in visited:
                    visited.add(src)
                    chain.append(src)
                    frontier.append(src)

        return chain

    def rollback_traversal(self, activity_iri: str) -> int:
        """Undo a traversal by removing the triples it injected.

        Looks up the target holon from the provenance activity,
        re-runs the portal's CONSTRUCT query to reconstruct what
        was injected, and removes those triples from the target
        interior.

        Parameters
        ----------
        activity_iri :
            IRI of the prov:Activity to roll back.

        Returns:
        -------
        int
            Number of triples removed.

        .. versionadded:: 0.6.0
        """
        from holonic.client import _bind_iri

        # Find the source (prov:used) and target (prov:generated)
        q = f"""
            PREFIX prov: <http://www.w3.org/ns/prov#>
            SELECT ?source ?target WHERE {{
                GRAPH ?g {{
                    <{activity_iri}> a prov:Activity ;
                        prov:used ?source ;
                        prov:generated ?target .
                }}
            }}
            LIMIT 1
        """
        rows = self._ds.backend.query(q)
        if not rows:
            raise ValueError(f"Activity {activity_iri} not found")

        source_iri = rows[0]["source"]
        target_iri = rows[0]["target"]

        # Find the portal and re-run its CONSTRUCT to get the projected triples
        portal = self._ds.find_portal(source_iri, target_iri)
        if portal is None:
            raise ValueError(
                f"Cannot find portal from {source_iri} to {target_iri} for activity {activity_iri}"
            )

        projected = self._ds.traverse_portal(portal.iri, inject_into=None)

        # Remove the projected triples from the target interior
        interior_rows = self._ds.backend.query(Q.GET_HOLON_INTERIORS, holon=_bind_iri(target_iri))
        removed = 0
        for ir in interior_rows:
            g_iri = ir["graph"]
            target_g = self._ds.backend.get_graph(g_iri)
            before = len(target_g)
            for s, p, o in projected:
                target_g.remove((s, p, o))
            after = len(target_g)
            if after < before:
                self._ds.backend.put_graph(g_iri, target_g)
                removed += before - after

        return removed


__all__ = ["ProvenanceLog"]
