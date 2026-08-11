"""Console-oriented read projections over the holarchy (0.8.0).

Extracted from :class:`holonic.client.HolonicDataset` as part of the
0.8.0 god-class decomposition (AR1/CQ1). This module owns the
read-only, presentation-shaped queries that back operator tooling:
lightweight holon summaries, full holon detail, interior class
inventories, portal-bounded neighborhoods, and portal browsing.

These are *console* concerns -- cheaper listing queries and
graph-shaped payloads for browsers -- that had accreted onto the core
dataset. Moving them onto a :class:`ConsoleReads` delegate keeps the
presentation-shaped reads out of the core write/traversal surface
(the "core -> console layering" the audit flagged) while leaving the
public API untouched: ``HolonicDataset`` retains thin delegating
wrappers for every method here.

The delegate holds a back-reference to its owning ``HolonicDataset``
(``self._ds``) because some reads consult the metadata refresher
(``ds._metadata``) alongside the backend.

.. versionadded:: 0.8.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from holonic import sparql as Q
from holonic.console_model import (
    ClassInstanceCount,
    HolonDetail,
    HolonSummary,
    NeighborhoodEdge,
    NeighborhoodGraph,
    NeighborhoodNode,
    PortalDetail,
    PortalSummary,
)

if TYPE_CHECKING:
    from holonic.client import HolonicDataset


class ConsoleReads:
    """Read-only, console-shaped projections over the holarchy.

    Constructed once per :class:`~holonic.client.HolonicDataset` and
    reached via ``ds._console``. Public dataset methods delegate here.
    """

    def __init__(self, ds: HolonicDataset):
        self._ds = ds

    def list_holons_summary(self) -> list[HolonSummary]:
        """Return lightweight holon summaries for browser/list views.

        Single SPARQL query -- no per-holon layer fan-out. Use
        ``get_holon_detail()`` for the full picture of one holon.
        """
        rows = self._ds.backend.query(Q.COLLECT_HOLONS)
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

    def get_holon_detail(self, holon_iri: str) -> HolonDetail | None:
        """Return the full holon descriptor including layer graph IRIs.

        Returns None if the holon is not registered.
        """
        from holonic.client import _bind_iri

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
        # Layer graphs -- same per-predicate queries used by list_holons
        for predicate, attr in (
            (Q.GET_HOLON_INTERIORS, "interior_graphs"),
            (Q.GET_HOLON_BOUNDARIES, "boundary_graphs"),
            (Q.GET_HOLON_PROJECTIONS, "projection_graphs"),
            (Q.GET_HOLON_CONTEXTS, "context_graphs"),
        ):
            rows = self._ds.backend.query(predicate, holon=_bind_iri(holon_iri))
            setattr(detail, attr, [r["graph"] for r in rows])

        # Optional: triple count over interior graphs
        if detail.interior_graphs:
            # Store-derived graph IRIs into a VALUES list -- a variable-length
            # slot that can't ride initBindings, so validate + n3()-serialize
            # each one (closes the second-order injection path, S3).
            graph_values = " ".join(
                _bind_iri(g, "interior_graph").n3() for g in detail.interior_graphs
            )
            count_rows = self._ds.backend.query(
                Q.COUNT_INTERIOR_TRIPLES_TEMPLATE.format(graph_values=graph_values)
            )
            if count_rows:
                try:
                    detail.interior_triple_count = int(count_rows[0].get("cnt", 0))
                except (TypeError, ValueError):
                    detail.interior_triple_count = None

        # Per-layer metadata from the registry. Added 0.3.3. Any layer
        # graph with no materialized metadata is simply absent from the
        # dict -- callers should not assume full coverage.
        all_layer_graphs = (
            detail.interior_graphs
            + detail.boundary_graphs
            + detail.projection_graphs
            + detail.context_graphs
        )
        last_modified_seen: list[str] = []
        for g in all_layer_graphs:
            md = self._ds._metadata.read(g)
            if md is not None:
                detail.layer_metadata[g] = md
                if md.last_modified:
                    last_modified_seen.append(md.last_modified)
        if last_modified_seen:
            detail.holon_last_modified = max(last_modified_seen)

        return detail

    def holon_interior_classes(self, holon_iri: str) -> list[ClassInstanceCount]:
        """Return (rdf:type, instance count) pairs across a holon's interior.

        Empty list if the holon has no interior graphs or no typed
        instances. Counts are DISTINCT subject counts per class.
        """
        from holonic.client import _bind_iri

        interior_rows = self._ds.backend.query(Q.GET_HOLON_INTERIORS, holon=_bind_iri(holon_iri))
        if not interior_rows:
            return []

        # Store-derived graph IRIs into a VALUES list (see COUNT_INTERIOR
        # note above): validate + n3()-serialize each rather than splice raw.
        graph_values = " ".join(_bind_iri(r["graph"], "interior_graph").n3() for r in interior_rows)
        rows = self._ds.backend.query(
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
    ) -> NeighborhoodGraph:
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
        if depth < 0:
            raise ValueError("depth must be >= 0")

        # Pre-fetch all portals once (cheap, single query) and build
        # an undirected adjacency map for BFS.
        all_portal_rows = self._ds.backend.query(Q.ALL_PORTALS)
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

    def list_portals(self) -> list[PortalSummary]:
        """Return a flat list of all portals across the dataset."""
        rows = self._ds.backend.query(Q.ALL_PORTALS)
        return [
            PortalSummary(
                iri=r["portal"],
                source_iri=r["source"],
                target_iri=r["target"],
                label=r.get("label"),
                portal_type=r.get("portalType"),
            )
            for r in rows
        ]

    def get_portal(self, portal_iri: str) -> PortalDetail | None:
        """Return the full portal descriptor including the CONSTRUCT body.

        Returns None if no portal with that IRI is registered.
        """
        rows = self._ds.backend.query(f"""
            PREFIX cga:  <urn:holonic:ontology:>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

            SELECT ?source ?target ?label ?query ?portalType
            WHERE {{
                GRAPH ?g {{
                    <{portal_iri}> cga:sourceHolon ?source ;
                        cga:targetHolon ?target .
                    OPTIONAL {{ <{portal_iri}> rdfs:label        ?label }}
                    OPTIONAL {{ <{portal_iri}> cga:constructQuery ?query }}
                    OPTIONAL {{ <{portal_iri}> a ?portalType . FILTER(?portalType != cga:Portal) }}
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
            portal_type=r.get("portalType"),
            construct_query=r.get("query"),
        )
