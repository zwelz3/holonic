"""Graph-native holonic dataset client.

HolonicDataset is a thin Python wrapper around a GraphBackend.
All state lives in the backend as named graphs.  All discovery,
traversal, and validation use SPARQL against the backend.
Python methods are convenience, not architecture.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from rdflib import Graph, Namespace
from rdflib.namespace import RDF, RDFS, XSD

from holonic import sparql as Q
from holonic.backends.protocol import GraphBackend
from holonic.backends.rdflib_backend import RdflibBackend
from holonic.model import (
    AuditTrail,
    HolonInfo,
    MembraneHealth,
    MembraneResult,
    PortalInfo,
    SurfaceReport,
    TraversalRecord,
    ValidationRecord,
)

log = logging.getLogger(__name__)

CGA = Namespace("urn:holonic:ontology:")
PROJ = Namespace("urn:holonic:projection:")
REGISTRY_GRAPH = "urn:holarchy:registry"
SH = Namespace("http://www.w3.org/ns/shacl#")

# TODO replace with namespace manager?
_KNOWN_PREFIX_STR = f"""@prefix rdf: <{RDF}> .
@prefix sh: <{SH}> .
@prefix rdfs: <{RDFS}> .
@prefix xsd: <{XSD}> .
"""


class HolonicDataset:
    """A holonic system backed by an RDF quad store.

    Parameters
    ----------
    backend :
        A GraphBackend implementation.  Defaults to RdflibBackend
        (in-memory rdflib.Dataset).
    registry_graph :
        IRI of the named graph holding holon/portal declarations.
    load_ontology :
        If True (default), load the CGA ontology and shapes into
        the dataset on construction.
    """

    # ══════════════════════════════════════════════════════════
    # Ontology loading
    # ══════════════════════════════════════════════════════════

    def _load_ontology(self) -> None:
        """Load the CGA ontology and shapes into the dataset."""
        ontology_dir = Path(__file__).parent / "ontology"

        cga_path = ontology_dir / "cga.ttl"
        if cga_path.exists():
            with open(cga_path, encoding="utf-8") as f:
                self.backend.parse_into("urn:holonic:ontology:cga", f.read(), "turtle")

        shapes_path = ontology_dir / "cga-shapes.ttl"
        if shapes_path.exists():
            with open(shapes_path, encoding="utf-8") as f:
                self.backend.parse_into("urn:holonic:ontology:cga-shapes", f.read(), "turtle")

    def __init__(
        self,
        backend: GraphBackend | None = None,
        *,
        registry_graph: str = REGISTRY_GRAPH,
        load_ontology: bool = True,
    ):
        self.backend: GraphBackend = backend or RdflibBackend()
        self.registry_graph = registry_graph

        if load_ontology:
            self._load_ontology()

    # ══════════════════════════════════════════════════════════
    # Holon management
    # ══════════════════════════════════════════════════════════

    def add_holon(
        self,
        iri: str,
        label: str,
        *,
        member_of: str | None = None,
    ) -> str:
        """Declare a holon in the registry.  Returns the holon IRI.

        Parameters
        ----------
        iri :
            The holon's IRI.
        label :
            Human-readable label.
        member_of :
            IRI of the parent holon (holarchy containment).

        Note:
        ----
        Depth is not stored — it is derivable from the cga:memberOf
        chain via ``compute_depth()``.
        """
        ttl = f"""
            @prefix cga:  <urn:holonic:ontology:> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

            <{iri}> a cga:Holon ;
                rdfs:label "{label}" .
        """
        if member_of:
            ttl += f"    <{iri}> cga:memberOf <{member_of}> .\n"

        ttl = _KNOWN_PREFIX_STR + ttl
        self.backend.parse_into(self.registry_graph, ttl, "turtle")
        return iri

    # TODO move predicate to arg[1] position
    def _register_layer(self, holon_iri: str, graph_iri: str, predicate: str) -> None:
        ttl = f"""
            @prefix cga: <urn:holonic:ontology:> .
            <{holon_iri}> cga:{predicate} <{graph_iri}> .
        """
        self.backend.parse_into(self.registry_graph, ttl, "turtle")

    def add_interior(
        self,
        holon_iri: str,
        ttl: str,
        *,
        graph_iri: str | None = None,
    ) -> str:
        """Parse TTL into a named graph and register it as a holon's interior."""
        graph_iri = graph_iri or f"{holon_iri}/interior"
        ttl = _KNOWN_PREFIX_STR + ttl
        self.backend.parse_into(graph_iri, ttl, "turtle")
        self._register_layer(holon_iri, graph_iri, "hasInterior")
        return graph_iri

    def add_boundary(
        self,
        holon_iri: str,
        ttl: str,
        *,
        graph_iri: str | None = None,
    ) -> str:
        """Parse TTL into a named graph and register it as a holon's boundary."""
        graph_iri = graph_iri or f"{holon_iri}/boundary"
        ttl = _KNOWN_PREFIX_STR + ttl
        self.backend.parse_into(graph_iri, ttl, "turtle")
        self._register_layer(holon_iri, graph_iri, "hasBoundary")
        return graph_iri

    def add_projection(
        self,
        holon_iri: str,
        ttl: str,
        *,
        graph_iri: str | None = None,
    ) -> str:
        """Parse TTL into a named graph and register it as a holon's projection."""
        graph_iri = graph_iri or f"{holon_iri}/projection"
        ttl = _KNOWN_PREFIX_STR + ttl
        self.backend.parse_into(graph_iri, ttl, "turtle")
        self._register_layer(holon_iri, graph_iri, "hasProjection")
        return graph_iri

    def add_context(
        self,
        holon_iri: str,
        ttl: str,
        *,
        graph_iri: str | None = None,
    ) -> str:
        """Parse TTL into a named graph and register it as a holon's context."""
        graph_iri = graph_iri or f"{holon_iri}/context"
        ttl = _KNOWN_PREFIX_STR + ttl
        self.backend.parse_into(graph_iri, ttl, "turtle")
        self._register_layer(holon_iri, graph_iri, "hasContext")
        return graph_iri

    # ══════════════════════════════════════════════════════════
    # Holon discovery (SPARQL-driven)
    # ══════════════════════════════════════════════════════════

    def list_holons(self) -> list[HolonInfo]:
        """Discover all holons via SPARQL against the registry."""
        rows = self.backend.query(Q.LIST_HOLONS)
        holons = []
        for row in rows:
            info = HolonInfo(
                iri=row["holon"],
                label=row.get("label"),
            )
            # Fetch layers
            layer_rows = self.backend.query(
                Q.GET_HOLON_INTERIORS.replace("?holon", f"<{info.iri}>")
            )
            info.interior_graphs = [r["graph"] for r in layer_rows]

            boundary_rows = self.backend.query(
                Q.GET_HOLON_BOUNDARIES.replace("?holon", f"<{info.iri}>")
            )
            info.boundary_graphs = [r["graph"] for r in boundary_rows]

            projection_rows = self.backend.query(
                Q.GET_HOLON_PROJECTIONS.replace("?holon", f"<{info.iri}>")
            )
            info.projection_graphs = [r["graph"] for r in projection_rows]

            context_rows = self.backend.query(
                Q.GET_HOLON_CONTEXTS.replace("?holon", f"<{info.iri}>")
            )
            info.context_graphs = [r["graph"] for r in context_rows]
            holons.append(info)
        return holons

    def get_holon(self, holon_iri: str) -> HolonInfo | None:
        """Get info for a single holon, or None if not found."""
        for h in self.list_holons():
            if h.iri == holon_iri:
                return h
        return None

    # ══════════════════════════════════════════════════════════
    # Portal management
    # ══════════════════════════════════════════════════════════

    def add_portal(
        self,
        portal_iri: str,
        source_iri: str,
        target_iri: str,
        construct_query: str,
        *,
        label: str | None = None,
        graph_iri: str | None = None,
    ) -> str:
        """Register a TransformPortal in the source holon's boundary graph.

        The portal definition IS RDF in the boundary named graph.
        Discovery uses SPARQL, not Python lookups.
        """
        graph_iri = graph_iri or f"{source_iri}/boundary"
        escaped_query = construct_query.replace("\\", "\\\\").replace('"', '\\"')
        # TODO to_pithy_id
        lbl = label or f"{source_iri} → {target_iri}"
        ttl = f"""
            @prefix cga:  <urn:holonic:ontology:> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

            <{portal_iri}> a cga:TransformPortal ;
                cga:sourceHolon <{source_iri}> ;
                cga:targetHolon <{target_iri}> ;
                rdfs:label "{lbl}" ;
                cga:constructQuery \"\"\"{escaped_query}\"\"\" .
        """
        self.backend.parse_into(graph_iri, ttl, "turtle")
        # Also ensure portal is visible from registry
        self.backend.parse_into(self.registry_graph, ttl, "turtle")
        return portal_iri

    # ══════════════════════════════════════════════════════════
    # Portal discovery (SPARQL-driven)
    # ══════════════════════════════════════════════════════════

    def find_portals_from(self, source_iri: str) -> list[PortalInfo]:
        """Discover all portals originating from a holon.  Pure SPARQL."""
        # TODO investigate templates instead of string replace
        q = Q.FIND_PORTALS_FROM.replace("?source", f"<{source_iri}>")
        rows = self.backend.query(q)
        return [
            PortalInfo(
                iri=r["portal"],
                source_iri=source_iri,
                target_iri=r["target"],
                label=r.get("label"),
                construct_query=r.get("query"),
            )
            for r in rows
        ]

    def find_portals_to(self, target_iri: str) -> list[PortalInfo]:
        """Discover all portals targeting a holon.  Pure SPARQL."""
        q = Q.FIND_PORTALS_TO.replace("?target", f"<{target_iri}>")
        rows = self.backend.query(q)
        return [
            PortalInfo(
                iri=r["portal"],
                source_iri=r["source"],
                target_iri=target_iri,
                label=r.get("label"),
                construct_query=r.get("query"),
            )
            for r in rows
        ]

    def find_portal(self, source_iri: str, target_iri: str) -> PortalInfo | None:
        """Find a direct portal between two holons.  Returns None if none exists."""
        q = Q.FIND_PORTAL_DIRECT.replace("?source", f"<{source_iri}>").replace(
            "?target", f"<{target_iri}>"
        )
        rows = self.backend.query(q)
        if not rows:
            return None
        r = rows[0]
        return PortalInfo(
            iri=r["portal"],
            source_iri=source_iri,
            target_iri=target_iri,
            label=r.get("label"),
            construct_query=r.get("query"),
        )

    def find_path(
        self,
        source_iri: str,
        target_iri: str,
    ) -> list[PortalInfo] | None:
        """Find a portal chain via BFS over the SPARQL-discovered portal graph.

        Returns a list of PortalInfo forming a path, or None if unreachable.
        """
        # Fetch all portals in one query
        rows = self.backend.query(Q.ALL_PORTALS)
        adj: dict[str, list[PortalInfo]] = {}
        for r in rows:
            p = PortalInfo(
                iri=r["portal"],
                source_iri=r["source"],
                target_iri=r["target"],
                label=r.get("label"),
            )
            adj.setdefault(p.source_iri, []).append(p)

        # BFS
        queue: deque[tuple[str, list[PortalInfo]]] = deque([(source_iri, [])])
        visited = {source_iri}
        while queue:
            current, path = queue.popleft()
            for portal in adj.get(current, []):
                new_path = path + [portal]
                if portal.target_iri == target_iri:
                    return new_path
                if portal.target_iri not in visited:
                    visited.add(portal.target_iri)
                    queue.append((portal.target_iri, new_path))
        return None

    # ══════════════════════════════════════════════════════════
    # Portal traversal
    # ══════════════════════════════════════════════════════════

    def traverse_portal(
        self,
        portal_iri: str,
        *,
        inject_into: str | None = None,
    ) -> Graph:
        """Execute a portal's CONSTRUCT query against the dataset.

        The CONSTRUCT query is read FROM the dataset (not passed as arg).
        This is the graph-native pattern: the portal definition IS the
        traversal specification.

        Parameters
        ----------
        portal_iri :
            IRI of the portal to traverse.
        inject_into :
            If provided, the resulting triples are also appended into
            this named graph in the dataset.

        Returns:
        -------
        rdflib.Graph
            The projected triples.
        """
        # Fetch the CONSTRUCT query from the portal definition
        q = Q.GET_PORTAL_QUERY.replace("?portal", f"<{portal_iri}>")
        rows = self.backend.query(q)
        if not rows:
            raise ValueError(f"Portal {portal_iri} not found or has no CONSTRUCT query")

        construct_query = rows[0]["query"]
        projected = self.backend.construct(construct_query)

        if inject_into and projected:
            self.backend.post_graph(inject_into, projected)

        return projected

    def traverse(
        self,
        source_iri: str,
        target_iri: str,
        *,
        inject: bool = True,
        validate: bool = True,
        agent_iri: str | None = None,
    ) -> tuple[Graph, MembraneResult | None]:
        """High-level: find a portal, traverse it, optionally validate and record.

        Parameters
        ----------
        source_iri, target_iri :
            Source and target holon IRIs.
        inject :
            If True, inject projected triples into the target's first interior.
        validate :
            If True, validate the target membrane after injection.
        agent_iri :
            If provided, record PROV-O provenance.

        Returns:
        -------
        (projected_graph, membrane_result_or_none)
        """
        portal = self.find_portal(source_iri, target_iri)
        if portal is None:
            raise ValueError(f"No direct portal from {source_iri} to {target_iri}")

        target_interior = f"{target_iri}/interior"
        projected = self.traverse_portal(
            portal.iri,
            inject_into=target_interior if inject else None,
        )

        membrane_result = None
        if validate:
            membrane_result = self.validate_membrane(target_iri)

        if agent_iri:
            self.record_traversal(
                portal_iri=portal.iri,
                source_iri=source_iri,
                target_iri=target_iri,
                agent_iri=agent_iri,
            )
            if membrane_result:
                self.record_validation(
                    holon_iri=target_iri,
                    health=membrane_result.health,
                    agent_iri=agent_iri,
                )

        return projected, membrane_result

    # ══════════════════════════════════════════════════════════
    # Membrane validation
    # ══════════════════════════════════════════════════════════

    def validate_membrane(self, holon_iri: str) -> MembraneResult:
        """Validate a holon's interior(s) against its boundary shape(s).

        Collects all cga:hasInterior graphs as data and all cga:hasBoundary
        graphs as shapes, then runs pyshacl.
        """
        import pyshacl

        # Collect interior graphs (union)
        interior_rows = self.backend.query(
            Q.GET_HOLON_INTERIORS.replace("?holon", f"<{holon_iri}>")
        )
        data_graph = Graph()
        for row in interior_rows:
            g = self.backend.get_graph(row["graph"])
            for triple in g:
                data_graph.add(triple)

        # Collect boundary graphs (union)
        boundary_rows = self.backend.query(
            Q.GET_HOLON_BOUNDARIES.replace("?holon", f"<{holon_iri}>")
        )
        shapes_graph = Graph()
        for row in boundary_rows:
            g = self.backend.get_graph(row["graph"])
            for triple in g:
                shapes_graph.add(triple)

        if len(shapes_graph) == 0:
            return MembraneResult(
                holon_iri=holon_iri,
                conforms=True,
                health=MembraneHealth.INTACT,
                report_text="No boundary shapes defined.",
            )

        conforms, report_graph, report_text = pyshacl.validate(
            data_graph,
            shacl_graph=shapes_graph,
        )

        # Parse violations and warnings from report
        violations = []
        warnings = []
        for line in report_text.split("\n"):
            line_stripped = line.strip()
            if "Violation" in line_stripped:
                violations.append(line_stripped)
            elif "Warning" in line_stripped:
                warnings.append(line_stripped)

        if violations:
            health = MembraneHealth.COMPROMISED
        elif warnings:
            health = MembraneHealth.WEAKENED
        else:
            health = MembraneHealth.INTACT

        return MembraneResult(
            holon_iri=holon_iri,
            conforms=conforms,
            health=health,
            report_text=report_text,
            violations=violations,
            warnings=warnings,
        )

    # ══════════════════════════════════════════════════════════
    # Provenance (SPARQL UPDATE)
    # ══════════════════════════════════════════════════════════

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
        activity_iri = f"urn:prov:traversal:{uuid.uuid4().hex[:12]}"
        context_graph = context_graph or f"{target_iri}/context"
        ts = datetime.now(UTC).isoformat()

        update = Q.RECORD_TRAVERSAL.format(
            context_graph=context_graph,
            activity_iri=activity_iri,
            label=f"Portal traversal via {portal_iri}",
            agent_iri=agent_iri,
            source_iri=source_iri,
            target_iri=target_iri,
            timestamp=ts,
        )
        self.backend.update(update)

        # Register context graph if not already
        self._register_layer(target_iri, context_graph, "hasContext")
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
        activity_iri = f"urn:prov:validation:{uuid.uuid4().hex[:12]}"
        context_graph = context_graph or f"{holon_iri}/context"
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
        self.backend.update(update)
        self._register_layer(holon_iri, context_graph, "hasContext")
        return activity_iri

    def _build_surface_report(self, holon_iri: str) -> SurfaceReport | None:
        """Build a surface report from a holon's boundary shapes."""
        boundary_rows = self.backend.query(
            Q.GET_HOLON_BOUNDARIES.replace("?holon", f"<{holon_iri}>")
        )
        if not boundary_rows:
            return None

        # Query the shapes for required/optional fields
        report = SurfaceReport(holon_iri=holon_iri)
        for row in boundary_rows:
            shape_rows = self.backend.query(f"""
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

    def collect_audit_trail(self) -> AuditTrail:
        """Collect the full provenance audit trail from context graphs.

        Queries all PROV-O activities across every context graph in the
        dataset, correlates traversals with validations, and builds
        surface reports from boundary shapes.

        Returns:
        -------
        AuditTrail
            Complete structured audit of traversals, validations,
            derivation chains, and surface reports.
        """
        # Collect traversals
        traversal_rows = self.backend.query(Q.COLLECT_TRAVERSALS)
        traversals = [
            TraversalRecord(
                activity_iri=r["activity"],
                source_iri=r["source"],
                target_iri=r["target"],
                agent_iri=r.get("agent"),
                portal_label=r.get("label"),
                timestamp=r.get("timestamp"),
            )
            for r in traversal_rows
        ]

        # Collect validations
        validation_rows = self.backend.query(Q.COLLECT_VALIDATIONS)
        validations = [
            ValidationRecord(
                activity_iri=r["activity"],
                holon_iri=r["holon"],
                health=r["health"],
                agent_iri=r.get("agent"),
                timestamp=r.get("timestamp"),
            )
            for r in validation_rows
        ]

        # Collect derivation chain
        derivation_rows = self.backend.query(Q.COLLECT_DERIVATION_CHAIN)
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

    # ══════════════════════════════════════════════════════════
    # RDFS entailment (proposed extension)
    # ══════════════════════════════════════════════════════════

    def materialize_rdfs(
        self,
        holon_iri: str,
        alignment_iris: list[str] | None = None,
    ) -> str:
        """Materialize RDFS entailment for a holon using alignment axioms.

        Creates an /interior/inferred named graph containing the delta
        (new triples from RDFS closure not in the original interiors).

        Returns the IRI of the inferred graph.
        """
        try:
            import owlrl
        except ImportError:
            raise ImportError("owlrl is required for RDFS materialization: pip install owlrl")

        # Collect original interior triples
        interior_rows = self.backend.query(
            Q.GET_HOLON_INTERIORS.replace("?holon", f"<{holon_iri}>")
        )
        originals = Graph()
        for row in interior_rows:
            g = self.backend.get_graph(row["graph"])
            for triple in g:
                originals.add(triple)

        # Merge with alignment axioms
        temp = Graph()
        for triple in originals:
            temp.add(triple)
        for align_iri in alignment_iris or []:
            align_rows = self.backend.query(
                Q.GET_HOLON_INTERIORS.replace("?holon", f"<{align_iri}>")
            )
            for row in align_rows:
                g = self.backend.get_graph(row["graph"])
                for triple in g:
                    temp.add(triple)

        # Apply RDFS closure
        owlrl.DeductiveClosure(owlrl.RDFS_Semantics).expand(temp)

        # Compute delta
        inferred = Graph()
        original_set = set(originals)
        for triple in temp:
            if triple not in original_set:
                inferred.add(triple)

        # Store in named graph
        inferred_iri = f"{holon_iri}/interior/inferred"
        self.backend.put_graph(inferred_iri, inferred)
        self._register_layer(holon_iri, inferred_iri, "hasInterior")

        return inferred_iri

    # ══════════════════════════════════════════════════════════
    # Raw SPARQL access
    # ══════════════════════════════════════════════════════════

    def query(self, sparql: str, **bindings) -> list[dict[str, Any]]:
        """Run a SELECT query against the full dataset."""
        return self.backend.query(sparql, **bindings)

    def construct(self, sparql: str, **bindings) -> Graph:
        """Run a CONSTRUCT query against the full dataset."""
        return self.backend.construct(sparql, **bindings)

    def update(self, sparql: str) -> None:
        """Run a SPARQL UPDATE against the dataset."""
        self.backend.update(sparql)

    # ══════════════════════════════════════════════════════════
    # Projections
    # ══════════════════════════════════════════════════════════

    def project_holon(
        self,
        holon_iri: str,
        *,
        store_as: str | None = None,
        **lpg_kwargs,
    ):
        """Project a holon's interior(s) into an LPG-style structure.

        Collects all cga:hasInterior graphs, merges them, and runs
        project_to_lpg().  Optionally stores the projection result
        as a named graph in the dataset.

        Parameters
        ----------
        holon_iri :
            The holon to project.
        store_as :
            If provided, serialize the LPG back to triples and store
            in this named graph (registered as a projection layer).
        **lpg_kwargs :
            Forwarded to project_to_lpg() — collapse_types, resolve_blanks, etc.

        Returns:
        -------
        ProjectedGraph
        """
        from holonic.projections import project_to_lpg

        interior_rows = self.backend.query(
            Q.GET_HOLON_INTERIORS.replace("?holon", f"<{holon_iri}>")
        )
        graphs = [self.backend.get_graph(r["graph"]) for r in interior_rows]

        if not graphs:
            from holonic.projections import ProjectedGraph

            return ProjectedGraph()

        lpg = project_to_lpg(sum(graphs, Graph()), **lpg_kwargs)

        if store_as:
            # Serialize back to triples for storage
            result_graph = Graph(identifier=PROJ + str(uuid4()))
            from rdflib import Literal as Lit
            from rdflib import URIRef as URef
            from rdflib.namespace import RDF as _RDF
            from rdflib.namespace import RDFS as _RDFS

            for iri, node in lpg.nodes.items():
                subj = URef(iri)
                for t in node.types:
                    result_graph.add((subj, _RDF.type, URef(t)))
                if node.label:
                    result_graph.add((subj, _RDFS.label, Lit(node.label)))
            for edge in lpg.edges:
                result_graph.add(
                    (
                        URef(edge.source),
                        URef(edge.predicate),
                        URef(edge.target),
                    )
                )
            self.backend.put_graph(store_as, result_graph)
            self._register_layer(holon_iri, store_as, "hasProjection")

        return lpg

    def project_holarchy(self, **lpg_kwargs):
        """Project the entire holarchy structure into an LPG.

        Nodes are holons; edges are cga:memberOf and portal connections.
        Useful for visualizing the holarchy topology.

        Returns:
        -------
        ProjectedGraph
        """
        from holonic.projections import project_to_lpg

        # Build a graph of holarchy structure from the registry
        structure = self.backend.construct("""
            PREFIX cga:  <urn:holonic:ontology:>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

            CONSTRUCT {
                ?holon a cga:Holon ;
                    rdfs:label ?label ;
                    cga:memberOf ?parent .
                ?portal a cga:TransformPortal ;
                    cga:sourceHolon ?src ;
                    cga:targetHolon ?tgt ;
                    rdfs:label ?plabel .
            }
            WHERE {
                {
                    graph ?g {
                        ?holon a cga:Holon .
                        OPTIONAL { ?holon rdfs:label ?label }
                        OPTIONAL { ?holon cga:memberOf ?parent }
                    }
                }
                UNION
                {
                    graph ?g {
                        ?portal a cga:TransformPortal ;
                            cga:sourceHolon ?src ;
                            cga:targetHolon ?tgt .
                        OPTIONAL { ?portal rdfs:label ?plabel }
                    }
                }
            }
        """)

        return project_to_lpg(structure, **lpg_kwargs)

    def apply_pipeline(
        self,
        holon_iri: str,
        pipeline,
        *,
        store_as: str | None = None,
    ) -> Graph:
        """Apply a ProjectionPipeline to a holon's merged interior(s).

        Parameters
        ----------
        holon_iri :
            The holon whose interiors to project.
        pipeline :
            A ProjectionPipeline instance.
        store_as :
            If provided, store the result as a named graph.

        Returns:
        -------
        rdflib.Graph
        """
        interior_rows = self.backend.query(
            Q.GET_HOLON_INTERIORS.replace("?holon", f"<{holon_iri}>")
        )
        graphs = [self.backend.get_graph(r["graph"]) for r in interior_rows]
        merged = sum(graphs, Graph()) if graphs else Graph()

        result = pipeline.apply(merged, backend=self.backend)

        if store_as:
            self.backend.put_graph(store_as, result)
            self._register_layer(holon_iri, store_as, "hasProjection")

        return result

    # ══════════════════════════════════════════════════════════
    # Summary / inspection
    # ══════════════════════════════════════════════════════════

    def summary(self) -> str:
        """Human-readable summary of the holarchy state."""
        holons = self.list_holons()
        portals_rows = self.backend.query(Q.ALL_PORTALS)
        graphs = self.backend.list_named_graphs()

        lines = [
            "HolonicDataset",
            f"  Backend: {type(self.backend).__name__}",
            f"  Named graphs: {len(graphs)}",
            f"  Holons: {len(holons)}",
        ]
        for h in holons:
            lines.append(f"    {h.label or h.iri}")
            lines.append(
                f"      interiors: {len(h.interior_graphs)}, boundaries: {len(h.boundary_graphs)}"
            )

        lines.append(f"  Portals: {len(portals_rows)}")
        for r in portals_rows:
            lbl = r.get("label", r["portal"].rsplit(":", 1)[-1])
            lines.append(f"    {lbl}: {r['source']} → {r['target']}")

        return "\n".join(lines)

    def compute_depth(self, holon_iri: str | None = None):
        """Compute nesting depth from the cga:memberOf chain.

        Depth is not stored — it is derived from structure.  A root
        holon (no memberOf) has depth 0.  Each memberOf hop adds 1.

        Uses a simple SPARQL query to fetch direct memberOf pairs from
        the registry graph, then walks the parent chain in Python.
        This avoids SPARQL property path limitations in named-graph
        contexts across different engines.

        Parameters
        ----------
        holon_iri :
            If provided, compute depth for a single holon.
            If None, compute for all holons.

        Returns:
        -------
        HolarchyTree
            Dict-like object (``tree[iri]`` → depth) that also carries
            parent/child relationships and labels.  ``print(tree)``
            renders the holarchy as an indented tree.
        """
        from collections import defaultdict

        from holonic.model import HolarchyTree

        # Fetch all holons with labels and direct parents from the registry
        rows = self.backend.query(f"""
            PREFIX cga:  <urn:holonic:ontology:>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?holon ?label ?parent
            WHERE {{
                GRAPH <{self.registry_graph}> {{
                    ?holon a cga:Holon .
                    OPTIONAL {{ ?holon rdfs:label ?label }}
                    OPTIONAL {{ ?holon cga:memberOf ?parent }}
                }}
            }}
        """)

        # Build parent map and labels
        parents: dict[str, str] = {}
        labels: dict[str, str] = {}
        all_holons: set[str] = set()
        for r in rows:
            iri = r["holon"]
            all_holons.add(iri)
            if r.get("label"):
                labels[iri] = r["label"]
            if r.get("parent"):
                parents[iri] = r["parent"]

        # Build children map (inverse of parents)
        children: dict[str, list[str]] = defaultdict(list)
        for child, parent in parents.items():
            children[parent].append(child)

        # Walk parent chains to compute depth
        def _depth_of(iri: str) -> int:
            depth = 0
            current = iri
            visited: set[str] = set()
            while current in parents and current not in visited:
                visited.add(current)
                current = parents[current]
                depth += 1
            return depth

        depths = {h: _depth_of(h) for h in all_holons}

        tree = HolarchyTree(
            depths=depths,
            parents=parents,
            children=dict(children),
            labels=labels,
        )

        if holon_iri:
            # Still return the full tree, but ensure the requested holon is present
            if holon_iri not in tree.depths:
                tree.depths[holon_iri] = 0
            return tree

        return tree

    # ══════════════════════════════════════════════════════════
    # Console-friendly summary / detail / neighborhood (0.3.1)
    #
    # These methods support operator-tool browsers that need cheaper
    # listing queries and graph-shaped neighborhood payloads. They
    # are additive — the existing list_holons/get_holon return the
    # richer HolonInfo type and remain unchanged.
    # ══════════════════════════════════════════════════════════

    def list_holons_summary(self) -> "list[HolonSummary]":
        """Return lightweight holon summaries for browser/list views.

        Single SPARQL query — no per-holon layer fan-out. Use
        ``get_holon_detail()`` for the full picture of one holon.
        """
        from holonic.console_model import HolonSummary

        rows = self.backend.query(Q.COLLECT_HOLONS)
        # COLLECT_HOLONS may emit multiple rows per holon (one per
        # rdf:type that isn't cga:Holon). Collapse server-side here.
        merged: dict[str, HolonSummary] = {}
        for row in rows:
            iri = row["holon"]
            existing = merged.get(iri)
            if existing is None:
                merged[iri] = HolonSummary(
                    iri=iri,
                    label=row.get("label"),
                    kind=row.get("kind"),
                    classification=row.get("classification"),
                    member_of=row.get("member_of"),
                )
            else:
                # Prefer the most-specific kind; first non-None wins
                # otherwise. Operators relying on multi-typed holons
                # should use get_holon_detail to see all types.
                if not existing.kind and row.get("kind"):
                    existing.kind = row["kind"]
        return list(merged.values())

    def get_holon_detail(self, holon_iri: str) -> "HolonDetail | None":
        """Return the full holon descriptor including layer graph IRIs.

        Returns None if the holon is not registered.
        """
        from holonic.console_model import HolonDetail

        # Reuse list_holons_summary for the registry triples
        summaries = self.list_holons_summary()
        match = next((s for s in summaries if s.iri == holon_iri), None)
        if match is None:
            return None

        detail = HolonDetail(
            iri=match.iri,
            label=match.label,
            kind=match.kind,
            classification=match.classification,
            member_of=match.member_of,
        )
        # Layer graphs — same per-predicate queries used by list_holons
        for predicate, attr in (
            (Q.GET_HOLON_INTERIORS, "interior_graphs"),
            (Q.GET_HOLON_BOUNDARIES, "boundary_graphs"),
            (Q.GET_HOLON_PROJECTIONS, "projection_graphs"),
            (Q.GET_HOLON_CONTEXTS, "context_graphs"),
        ):
            q = predicate.replace("?holon", f"<{holon_iri}>")
            setattr(detail, attr, [r["graph"] for r in self.backend.query(q)])

        # Optional: triple count over interior graphs
        if detail.interior_graphs:
            graph_values = " ".join(f"<{g}>" for g in detail.interior_graphs)
            count_rows = self.backend.query(
                Q.COUNT_INTERIOR_TRIPLES_TEMPLATE.format(graph_values=graph_values)
            )
            if count_rows:
                try:
                    detail.interior_triple_count = int(count_rows[0].get("cnt", 0))
                except (TypeError, ValueError):
                    detail.interior_triple_count = None

        return detail

    def holon_interior_classes(self, holon_iri: str) -> "list[ClassInstanceCount]":
        """Return (rdf:type, instance count) pairs across a holon's interior.

        Empty list if the holon has no interior graphs or no typed
        instances. Counts are DISTINCT subject counts per class.
        """
        from holonic.console_model import ClassInstanceCount

        interior_rows = self.backend.query(
            Q.GET_HOLON_INTERIORS.replace("?holon", f"<{holon_iri}>")
        )
        if not interior_rows:
            return []

        graph_values = " ".join(f"<{r['graph']}>" for r in interior_rows)
        rows = self.backend.query(
            Q.COUNT_INTERIOR_CLASSES_TEMPLATE.format(graph_values=graph_values)
        )
        out: list[ClassInstanceCount] = []
        for r in rows:
            try:
                count = int(r.get("cnt", 0))
            except (TypeError, ValueError):
                continue
            out.append(ClassInstanceCount(class_iri=r["class"], count=count))
        return out

    def holon_neighborhood(
        self,
        holon_iri: str,
        depth: int = 1,
    ) -> "NeighborhoodGraph":
        """Return a portal-bounded subgraph around a holon, depth-limited.

        BFS over portals from the source holon; each hop adds the
        portal's other endpoint to the node set and the portal itself
        to the edge set. Depth is the maximum number of portal hops
        from the source.

        The result is shaped for direct serialization to graphology
        JSON via ``NeighborhoodGraph.to_graphology()``. Edge keys are
        deterministic (``edge-NNNN``) so re-fetches with the same
        backing data produce stable IDs for diffing.
        """
        from holonic.console_model import (
            NeighborhoodEdge,
            NeighborhoodGraph,
            NeighborhoodNode,
        )

        if depth < 0:
            raise ValueError("depth must be >= 0")

        # Pre-fetch all portals once (cheap, single query) and build
        # an undirected adjacency map for BFS.
        all_portal_rows = self.backend.query(Q.ALL_PORTALS)
        outgoing: dict[str, list[dict]] = {}
        incoming: dict[str, list[dict]] = {}
        for r in all_portal_rows:
            outgoing.setdefault(r["source"], []).append(r)
            incoming.setdefault(r["target"], []).append(r)

        # BFS over holons up to depth
        visited_nodes: set[str] = {holon_iri}
        visited_edges: set[str] = set()
        frontier: list[str] = [holon_iri]
        edges: list[NeighborhoodEdge] = []
        edge_seq = 0

        for _ in range(depth):
            next_frontier: list[str] = []
            for node in frontier:
                for r in outgoing.get(node, []) + incoming.get(node, []):
                    portal_iri = r["portal"]
                    if portal_iri in visited_edges:
                        continue
                    visited_edges.add(portal_iri)
                    edge_seq += 1
                    edges.append(
                        NeighborhoodEdge(
                            key=f"edge-{edge_seq:04d}",
                            source=r["source"],
                            target=r["target"],
                            edge_type="portal",
                            label=r.get("label"),
                        )
                    )
                    for endpoint in (r["source"], r["target"]):
                        if endpoint not in visited_nodes:
                            visited_nodes.add(endpoint)
                            next_frontier.append(endpoint)
            frontier = next_frontier
            if not frontier:
                break

        # Hydrate node attributes from the holon registry. Holons
        # discovered via portal traversal that aren't registered
        # still appear in the graph (with kind=None) so the operator
        # sees the dangling reference.
        summaries = {s.iri: s for s in self.list_holons_summary()}
        nodes: list[NeighborhoodNode] = []
        for iri in sorted(visited_nodes):
            summary = summaries.get(iri)
            nodes.append(
                NeighborhoodNode(
                    key=iri,
                    label=summary.label if summary else None,
                    kind=summary.kind if summary else None,
                    health=summary.health if summary else None,
                    triples=summary.interior_triple_count or 0 if summary else 0,
                    size=10.0,
                    node_type="holon",
                )
            )

        return NeighborhoodGraph(
            source_holon=holon_iri,
            depth=depth,
            nodes=nodes,
            edges=edges,
        )

    # ══════════════════════════════════════════════════════════
    # Portal browsing (0.3.1)
    # ══════════════════════════════════════════════════════════

    def list_portals(self) -> "list[PortalSummary]":
        """Return a flat list of all portals across the dataset."""
        from holonic.console_model import PortalSummary

        rows = self.backend.query(Q.ALL_PORTALS)
        return [
            PortalSummary(
                iri=r["portal"],
                source_iri=r["source"],
                target_iri=r["target"],
                label=r.get("label"),
            )
            for r in rows
        ]

    def get_portal(self, portal_iri: str) -> "PortalDetail | None":
        """Return the full portal descriptor including the CONSTRUCT body.

        Returns None if no portal with that IRI is registered.
        """
        from holonic.console_model import PortalDetail

        # Single query to pull all portal triples
        rows = self.backend.query(f"""
            PREFIX cga:  <urn:holonic:ontology:>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

            SELECT ?source ?target ?label ?query
            WHERE {{
                GRAPH ?g {{
                    <{portal_iri}> a cga:TransformPortal ;
                        cga:sourceHolon ?source ;
                        cga:targetHolon ?target .
                    OPTIONAL {{ <{portal_iri}> rdfs:label        ?label }}
                    OPTIONAL {{ <{portal_iri}> cga:constructQuery ?query }}
                }}
            }}
            LIMIT 1
        """)
        if not rows:
            return None
        r = rows[0]
        return PortalDetail(
            iri=portal_iri,
            source_iri=r["source"],
            target_iri=r["target"],
            label=r.get("label"),
            construct_query=r.get("query"),
        )

    def portal_traversal_history(
        self,
        portal_iri: str,
        limit: int = 50,
    ) -> list[TraversalRecord]:
        """Return recorded traversals attributable to a single portal.

        See note in ``sparql.py`` PORTAL_TRAVERSAL_HISTORY_TEMPLATE —
        scoped by (source, target) pair, since the current provenance
        schema does not store the portal IRI as a structured triple.
        Returns an empty list if the portal is not registered.
        """
        portal = self.get_portal(portal_iri)
        if portal is None:
            return []

        # Clamp limit defensively — runaway value would let a caller
        # pull the full audit history.
        safe_limit = max(1, min(int(limit), 10_000))

        q = Q.PORTAL_TRAVERSAL_HISTORY_TEMPLATE.format(
            source_iri=portal.source_iri,
            target_iri=portal.target_iri,
            limit=safe_limit,
        )
        rows = self.backend.query(q)
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
