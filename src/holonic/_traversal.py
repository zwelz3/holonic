"""Portal traversal and projection injection (0.8.0).

Extracted from :class:`holonic.client.HolonicDataset` as part of the
0.8.0 god-class decomposition (AR1/CQ1). This module owns what happens
when a portal is crossed: resolving and scoping the source layers a
CONSTRUCT may see, running it, injecting the result into the target's
projection or interior, hashing the injection so a re-traversal is
idempotent, rolling the injection back when validation fails closed,
and recording the outcome.

The boundary against neighbouring delegates:

- :mod:`holonic._portals` owns which portals exist and where they point;
  this module owns crossing them.
- :mod:`holonic._membrane` owns the SHACL run; this module calls it and
  decides what a failure means for the injection.
- :mod:`holonic._provenance` owns the activity records; this module
  hands it outcomes to write.

Layer scoping (``_scoped_dataset``) lives here because it exists solely
to bound portal CONSTRUCT visibility -- the S5 fix. The shared
``_safe_layer_graph`` helper deliberately stays on the facade: holon
writes, validation, and projections all use it too.

The engine holds a back-reference to its owning ``HolonicDataset``
(``self._ds``) rather than a bare backend, because traversal reaches
across most of the facade -- layer registration, metadata refresh,
membrane validation, provenance recording, and the traversal
notification hooks.

``HolonicDataset`` keeps thin delegating wrappers for the public
methods (``traverse_portal``, ``traverse``, ``traverse_path``,
``dry_run``), so the public API is unchanged.

.. versionadded:: 0.8.0
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from rdflib import RDF, Dataset, Graph, URIRef

from holonic import sparql as Q
from holonic.model import (
    MembraneBreachError,
    MembraneHealth,
    MembraneResult,
    PortalInfo,
    UntargetedNode,
)

if TYPE_CHECKING:
    from holonic.client import HolonicDataset

log = logging.getLogger(__name__)


class TraversalEngine:
    """See module docstring. Reached via ``ds._traversal``."""

    def __init__(self, ds: HolonicDataset):
        self._ds = ds

    def _scoped_dataset(self, graph_iris: Iterable[str]) -> Dataset:
        """Materialize the given named graphs as a standalone queryable dataset.

        Portal traversal is scoped to a subset of the store's graphs (S5).
        Scoping must narrow *which graphs are visible* without changing the
        *query model*: a portal CONSTRUCT written as
        ``WHERE { GRAPH ?g { ... } }`` -- the idiom every portal used before
        0.8.0, when CONSTRUCTs ran against the whole dataset -- has to keep
        working. Merging the scope into a single ``Graph`` silently broke
        that, since rdflib raises "requires a dataset (i.e. ConjunctiveGraph)"
        for a ``GRAPH`` clause evaluated against one graph.

        So the scope is rebuilt as a ``Dataset`` holding each in-scope graph
        under its own IRI. ``default_union=True`` mirrors
        :class:`~holonic.backends.rdflib_backend.RdflibBackend`: patterns
        outside a ``GRAPH`` clause see the union of the in-scope graphs, and
        ``GRAPH ?g { ... }`` binds ``?g`` to in-scope graph IRIs *only* --
        never to a graph the portal was not scoped to.

        Layers are fetched through :meth:`_safe_layer_graph`, so a layer that
        is registered but not yet materialized contributes nothing instead of
        aborting the traversal (this is reachable on Fuseki, where an empty
        graph answers 404).

        .. versionadded:: 0.8.0
        """
        scoped = Dataset(default_union=True)
        for graph_iri in graph_iris:
            target = scoped.graph(URIRef(graph_iri))
            for triple in self._ds._safe_layer_graph(graph_iri):
                target.add(triple)
        return scoped

    def traverse_portal(
        self,
        portal_iri: str,
        *,
        inject_into: str | None = None,
        unscoped_portals_allowed: bool = False,
    ) -> Graph:
        """Execute a portal's CONSTRUCT query against the dataset.

        The CONSTRUCT query is read FROM the dataset (not passed as arg).
        This is the graph-native pattern: the portal definition IS the
        traversal specification.

        Raises :class:`SealedPortalError` if the portal is a
        ``cga:SealedPortal`` -- traversal is explicitly blocked regardless
        of whether the portal carries a CONSTRUCT query.

        The CONSTRUCT is **scoped to the source holon** (its projections if
        any, else its raw interior). Running against the whole dataset --
        which can expose other holons' interiors and leak PII -- is
        fail-closed: it requires an explicit opt-in (see
        ``unscoped_portals_allowed``). A portal whose source has neither
        projections nor interiors raises :class:`ValueError` rather than
        silently widening to the whole dataset.

        Parameters
        ----------
        portal_iri :
            IRI of the portal to traverse.
        inject_into :
            If provided, the resulting triples are also appended into
            this named graph in the dataset.
        unscoped_portals_allowed :
            Opt in to the legacy behaviour of running the CONSTRUCT against
            the entire dataset. Equivalent to declaring
            ``cga:sourceLayer cga:DatasetRole`` on the portal. Off by
            default (fail-closed).

        Returns:
        -------
        rdflib.Graph
            The projected triples.
        """
        from holonic.client import _bind_iri, _run_construct_on_graph, _validate_iri
        from holonic.model import SealedPortalError

        _validate_iri(portal_iri, "portal_iri")

        # Check portal type -- SealedPortal blocks traversal.
        #
        # Fail-closed: an ASK is true if *any* graph types the portal as
        # cga:SealedPortal, so a dual-typed portal (sealed AND, say,
        # cga:TransformPortal) can no longer slip through. The previous
        # ``SELECT ?type ... LIMIT 1`` returned one arbitrary type row and a
        # substring test on it, so whichever type the store happened to
        # return first decided the seal -- a nondeterministic bypass. Match
        # the class IRI exactly rather than by substring.
        is_sealed = self._ds.backend.ask(f"""
            PREFIX cga: <urn:holonic:ontology:>
            ASK {{ GRAPH ?g {{ <{portal_iri}> a cga:SealedPortal }} }}
        """)
        if is_sealed:
            raise SealedPortalError(portal_iri)

        log.debug("traverse_portal(%s)", portal_iri)
        # Fetch the CONSTRUCT query from the portal definition
        rows = self._ds.backend.query(
            Q.GET_PORTAL_QUERY, portal=_bind_iri(portal_iri, "portal_iri")
        )
        if not rows:
            raise ValueError(f"Portal {portal_iri} not found or has no CONSTRUCT query")

        construct_query = rows[0]["query"]

        # Source layer scoping: determine what the CONSTRUCT runs against.
        #
        # Priority:
        #   1. Explicit cga:sourceLayer on the portal -> honor it
        #      (DatasetRole -> whole dataset; ProjectionRole/InteriorRole
        #      -> that layer of the source holon)
        #   2. No explicit layer, source has projection graphs -> scope to
        #      projections (the governed view; raw interiors may carry PII)
        #   3. No explicit layer, no projections -> scope to the source's
        #      own interior graphs
        #   4. Nothing to scope to AND no opt-in -> raise (fail-closed)
        #
        # BREAKING in 0.8.0 (S5): a portal is NEVER silently widened to the
        # whole dataset. Previously a source with no projections ran its
        # CONSTRUCT against every graph, leaking other holons' interiors.
        # Whole-dataset traversal now requires cga:sourceLayer cga:DatasetRole
        # or unscoped_portals_allowed=True. See MIGRATION.md.

        # Get source holon IRI for projection lookup
        source_rows = self._ds.backend.query(f"""
            PREFIX cga: <urn:holonic:ontology:>
            SELECT ?source WHERE {{
                GRAPH ?g {{ <{portal_iri}> cga:sourceHolon ?source }}
            }} LIMIT 1
        """)
        source_iri_for_scope = source_rows[0]["source"] if source_rows else None

        # Check explicit sourceLayer
        scope_rows = self._ds.backend.query(f"""
            PREFIX cga: <urn:holonic:ontology:>
            SELECT ?layer WHERE {{
                GRAPH ?g {{ <{portal_iri}> cga:sourceLayer ?layer }}
            }} LIMIT 1
        """)
        explicit_layer = str(scope_rows[0]["layer"]) if scope_rows else None

        def _graphs_for(holon: str, template: str) -> list[str]:
            return [r["graph"] for r in self._ds.backend.query(template, holon=_bind_iri(holon))]

        scope_graphs: list[str] = []
        run_whole_dataset = unscoped_portals_allowed

        if explicit_layer and "DatasetRole" in explicit_layer:
            run_whole_dataset = True
        elif source_iri_for_scope and explicit_layer and "InteriorRole" in explicit_layer:
            scope_graphs = _graphs_for(source_iri_for_scope, Q.GET_HOLON_INTERIORS)
        elif source_iri_for_scope and explicit_layer and "ProjectionRole" in explicit_layer:
            scope_graphs = _graphs_for(source_iri_for_scope, Q.GET_HOLON_PROJECTIONS)
        elif source_iri_for_scope:
            # No explicit layer: prefer projections (the governed view),
            # else fall back to the source's own interior. Never the whole
            # dataset by default.
            scope_graphs = _graphs_for(source_iri_for_scope, Q.GET_HOLON_PROJECTIONS)
            if not scope_graphs:
                scope_graphs = _graphs_for(source_iri_for_scope, Q.GET_HOLON_INTERIORS)

        if run_whole_dataset:
            projected = self._ds.backend.construct(construct_query)
        elif scope_graphs:
            # Named graphs are preserved (not merged into one Graph) so a
            # CONSTRUCT carrying `GRAPH ?g { ... }` still resolves -- scoping
            # narrows visibility, not the query model. See _scoped_dataset.
            projected = _run_construct_on_graph(self._scoped_dataset(scope_graphs), construct_query)
        else:
            raise ValueError(
                f"Portal {portal_iri} cannot be scoped: its source holon "
                f"{source_iri_for_scope!r} has no projection or interior graphs, "
                "and whole-dataset traversal was not explicitly permitted. "
                "Declare `cga:sourceLayer cga:DatasetRole` on the portal, or "
                "call with unscoped_portals_allowed=True, to opt into the legacy "
                "whole-dataset behaviour."
            )

        if inject_into and projected:
            self._ds.backend.post_graph(inject_into, projected)
            self._ds._maybe_refresh(inject_into)

        return projected

    def _resolve_target_interior(self, target_iri: str) -> str:
        """Return the target's registered interior graph, or the convention name.

        Uses the first ``cga:hasInterior`` graph if one is registered,
        otherwise falls back to ``<target>/interior`` (registered by the
        caller once injection succeeds).
        """
        from holonic.client import _bind_iri

        interior_rows = self._ds.backend.query(Q.GET_HOLON_INTERIORS, holon=_bind_iri(target_iri))
        if interior_rows:
            return interior_rows[0]["graph"]
        return f"{target_iri}/interior"

    @staticmethod
    def _projection_hash(projected: Graph | None) -> str:
        """Stable content hash of a projected graph (empty string if falsy)."""
        if not projected:
            return ""
        return hashlib.sha256(projected.serialize(format="nt").encode()).hexdigest()

    def _inject_projection(
        self, interior_iri: str, projected: Graph, *, snapshot: bool
    ) -> Graph | None:
        """POST *projected* into *interior_iri*; return the added-triple delta.

        When ``snapshot`` is True the interior is read first so the returned
        delta is exactly the set of triples this call adds (projected minus
        pre-existing). That delta is what :meth:`_rollback_injection` removes on
        breach, so a rollback never touches triples written concurrently by
        another writer to the same interior. When ``snapshot`` is False no
        rollback will be needed and ``None`` is returned to skip the read.
        """
        delta: Graph | None = None
        if snapshot:
            pre = (
                self._ds.backend.get_graph(interior_iri)
                if self._ds.backend.graph_exists(interior_iri)
                else Graph()
            )
            delta = projected - pre
        self._ds.backend.post_graph(interior_iri, projected)
        self._ds._maybe_refresh(interior_iri)
        return delta

    def _rollback_injection(self, interior_iri: str, delta: Graph) -> None:
        """Remove exactly the triples in *delta* from *interior_iri*.

        Uses a targeted ``DELETE DATA`` so concurrently-written triples in the
        same interior survive the rollback (C2). ``DELETE DATA`` cannot name
        blank nodes; a delta carrying them falls back to nothing removed for
        those triples — ``fail_on_breach`` therefore still assumes exclusive
        access to the target interior for blank-node-bearing projections.
        """
        from rdflib import BNode

        from holonic.client import _bind_iri

        ground = Graph()
        for triple in delta:
            if any(isinstance(term, BNode) for term in triple):
                continue
            ground.add(triple)
        if len(ground) == 0:
            return
        nt = ground.serialize(format="nt")
        graph_ref = _bind_iri(interior_iri, "interior_iri").n3()
        self._ds.backend.update(f"DELETE DATA {{ GRAPH {graph_ref} {{\n{nt}\n}} }}")

    def _stored_projection_hash(self, target_iri: str) -> str | None:
        """Read the persisted ``cga:lastProjectionHash`` for *target_iri*."""
        from holonic.client import _bind_iri

        rows = self._ds.backend.query(
            Q.GET_PROJECTION_HASH,
            context=_bind_iri(f"{target_iri}/context", "context_graph"),
            target=_bind_iri(target_iri, "target_iri"),
        )
        return rows[0]["hash"] if rows else None

    def _store_projection_hash(self, target_iri: str, proj_hash: str) -> None:
        """Persist *proj_hash* as the target's ``cga:lastProjectionHash``.

        Single ``DELETE/INSERT WHERE`` (replaces the prior read + DELETE +
        parse_into three-op sequence). ``proj_hash`` is a sha256 hex digest —
        no injection surface — and the IRIs are validated before templating.
        """
        from holonic.client import _validate_iri

        context_graph = f"{target_iri}/context"
        _validate_iri(context_graph, "context_graph")
        _validate_iri(target_iri, "target_iri")
        self._ds.backend.update(
            Q.SET_PROJECTION_HASH.format(
                context_graph=context_graph,
                target_iri=target_iri,
                proj_hash=proj_hash,
            )
        )
        self._ds._register_layer(target_iri, context_graph, "hasContext")

    def _record_traversal_outcome(
        self,
        *,
        portal: PortalInfo,
        source_iri: str,
        target_iri: str,
        agent_iri: str,
        is_noop: bool,
        membrane_result: MembraneResult | None,
    ) -> None:
        """Record PROV-O provenance for a completed traversal."""
        from holonic.client import _escape_ttl, _validate_iri

        if is_noop:
            # Record a no-op traversal with explicit label. Same injection
            # surface as record_traversal() -- validate the interpolated IRIs
            # and escape the portal IRI embedded in the label before it
            # reaches the UPDATE template.
            _validate_iri(agent_iri, "agent_iri")
            _validate_iri(source_iri, "source_iri")
            _validate_iri(target_iri, "target_iri")
            activity_iri = f"urn:prov:traversal:{uuid.uuid4().hex[:12]}"
            context_graph = f"{target_iri}/context"
            _validate_iri(context_graph, "context_graph")
            ts = datetime.now(UTC).isoformat()
            noop_label = _escape_ttl(f"no-op: source unchanged (portal {portal.iri})")
            update = Q.RECORD_TRAVERSAL.format(
                context_graph=context_graph,
                activity_iri=activity_iri,
                label=noop_label,
                agent_iri=agent_iri,
                source_iri=source_iri,
                target_iri=target_iri,
                timestamp=ts,
            )
            self._ds.backend.update(update)
            self._ds._register_layer(target_iri, context_graph, "hasContext")
        else:
            self._ds.record_traversal(
                portal_iri=portal.iri,
                source_iri=source_iri,
                target_iri=target_iri,
                agent_iri=agent_iri,
            )
        if membrane_result:
            self._ds.record_validation(
                holon_iri=target_iri,
                health=membrane_result.health,
                agent_iri=agent_iri,
            )

    def traverse(
        self,
        source_iri: str,
        target_iri: str,
        *,
        inject: bool = True,
        validate: bool = True,
        fail_on_breach: bool = False,
        agent_iri: str | None = None,
        unscoped_portals_allowed: bool = False,
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
        fail_on_breach :
            If True and validation returns COMPROMISED, roll back the
            injected triples and raise :class:`MembraneBreachError`.
            Implies ``validate=True``. Injected nodes whose types no
            boundary shape targets also compromise the membrane, at the
            target's declared ``cga:untargetedTypeSeverity`` or
            ``sh:Violation`` by default (``cga:permitsType`` exempts a
            class).
        agent_iri :
            If provided, record PROV-O provenance.
        unscoped_portals_allowed :
            Forwarded to :meth:`traverse_portal`; opt in to running the
            portal CONSTRUCT against the whole dataset (fail-closed off by
            default).

        Returns:
        -------
        (projected_graph, membrane_result_or_none)
        """
        if fail_on_breach:
            validate = True

        portal = self._ds.find_portal(source_iri, target_iri)
        if portal is None:
            raise ValueError(f"No direct portal from {source_iri} to {target_iri}")
        log.debug("traverse(%s -> %s) via %s", source_iri, target_iri, portal.iri)

        target_interior = self._resolve_target_interior(target_iri) if inject else None

        # Run the CONSTRUCT without injecting first (for hash comparison).
        projected = self.traverse_portal(
            portal.iri,
            inject_into=None,
            unscoped_portals_allowed=unscoped_portals_allowed,
        )
        proj_hash = self._projection_hash(projected)

        # Hash-compare: skip injection when the projection is unchanged.
        # Only tracked when agent_iri is provided (hash is a provenance concern).
        is_noop = False
        if inject and target_interior and proj_hash and agent_iri:
            if self._stored_projection_hash(target_iri) == proj_hash:
                is_noop = True

        # Inject, capturing exactly the triples we add so a breach rollback
        # can remove only those (C2: never a whole-graph put_graph that would
        # clobber a concurrent writer's triples in the same interior).
        injected_delta: Graph | None = None
        if inject and target_interior and projected and not is_noop:
            injected_delta = self._inject_projection(
                target_interior, projected, snapshot=fail_on_breach
            )

        # Ensure the target interior graph is registered as cga:hasInterior.
        if target_interior:
            self._ds._register_layer(target_iri, target_interior, "hasInterior")

        membrane_result = None
        if validate:
            if fail_on_breach:
                # Check the injected nodes for untargeted types at Violation
                # severity by default (holonic#50): SHACL passes a node no
                # shape targets, so a portal injecting the wrong type would
                # otherwise leave the membrane INTACT.
                membrane_result = self._ds._membrane.validate_membrane(
                    target_iri, injected=injected_delta if injected_delta is not None else Graph()
                )
            else:
                membrane_result = self._ds.validate_membrane(target_iri)

            # Fail-closed: remove exactly what this call injected and raise.
            # The projection hash is written *after* this check (below), so a
            # rolled-back breach never poisons the no-op cache (E2): a retry
            # after fixing the boundary re-injects instead of reporting a
            # phantom no-op.
            if fail_on_breach and membrane_result.health == MembraneHealth.COMPROMISED:
                if target_interior and injected_delta is not None:
                    self._rollback_injection(target_interior, injected_delta)
                raise MembraneBreachError(membrane_result)

        # Persist the projection hash only once validation has passed (E2).
        if inject and target_interior and proj_hash and agent_iri and not is_noop:
            self._store_projection_hash(target_iri, proj_hash)

        if agent_iri:
            self._record_traversal_outcome(
                portal=portal,
                source_iri=source_iri,
                target_iri=target_iri,
                agent_iri=agent_iri,
                is_noop=is_noop,
                membrane_result=membrane_result,
            )

        # Fire notification hooks
        for hook in self._ds._on_traversal:
            hook(source_iri, target_iri, projected, membrane_result)

        return projected, membrane_result

    def traverse_path(
        self,
        source_iri: str,
        target_iri: str,
        *,
        validate: bool = True,
        fail_on_breach: bool = False,
        agent_iri: str | None = None,
    ) -> list[tuple[Graph, MembraneResult | None]]:
        """Execute a multi-hop traversal along the shortest portal path.

        Calls :meth:`find_path` to discover the route, then executes
        :meth:`traverse` for each hop in sequence. Each hop's projected
        graph and membrane result are collected and returned.

        Parameters
        ----------
        source_iri, target_iri :
            Source and ultimate target holon IRIs.
        validate :
            If True, validate the membrane at each hop.
        fail_on_breach :
            If True and any hop produces COMPROMISED, raise
            :class:`MembraneBreachError` immediately (remaining
            hops are not executed).
        agent_iri :
            If provided, record PROV-O provenance per hop.

        Returns:
        -------
        list[tuple[Graph, MembraneResult | None]]
            One entry per hop in the path.

        Raises:
        ------
        ValueError
            If no path exists between source and target.
        MembraneBreachError
            If ``fail_on_breach=True`` and a hop produces COMPROMISED.

        .. versionadded:: 0.6.0
        """
        path = self._ds.find_path(source_iri, target_iri)
        if path is None:
            raise ValueError(f"No path from {source_iri} to {target_iri}")

        results = []
        for portal in path:
            projected, membrane = self.traverse(
                portal.source_iri,
                portal.target_iri,
                validate=validate,
                fail_on_breach=fail_on_breach,
                agent_iri=agent_iri,
            )
            results.append((projected, membrane))

        return results

    def dry_run(
        self,
        source_iri: str,
        target_iri: str,
    ) -> tuple[Graph, MembraneResult]:
        """Simulate a traversal without mutating any state.

        Runs the portal's CONSTRUCT query, merges the result with the
        target's existing interior(s) in a temporary graph, and validates
        against the target's boundary shapes. Nothing is written to the
        dataset.

        Projected nodes whose types no boundary shape targets are reported in
        ``result.untargeted`` at the target's declared
        ``cga:untargetedTypeSeverity``, ``sh:Info`` by default. A
        ``traverse(..., fail_on_breach=True)`` defaults to ``sh:Violation``
        for the same nodes, so a dry run that lists untargeted nodes at Info
        predicts a breach for a fail-closed traversal.

        Useful for CI/CD validation of CONSTRUCT query changes, mapping
        updates, and interactive development.

        Parameters
        ----------
        source_iri, target_iri :
            Source and target holon IRIs.

        Returns:
        -------
        (projected_graph, membrane_result)
            The projected triples and what-if membrane validation.

        Raises:
        ------
        ValueError
            If no direct portal exists.

        .. versionadded:: 0.6.0
        """
        import pyshacl

        from holonic._membrane import find_untargeted, untargeted_policy, untargeted_severity_label
        from holonic.client import _bind_iri, _health_from_report, _parse_shacl_report

        portal = self._ds.find_portal(source_iri, target_iri)
        if portal is None:
            raise ValueError(f"No direct portal from {source_iri} to {target_iri}")

        # Run the CONSTRUCT without injecting
        projected = self.traverse_portal(portal.iri, inject_into=None)

        # Build what-if data graph: existing interiors + projected
        data_graph = Graph()
        interior_rows = self._ds.backend.query(Q.GET_HOLON_INTERIORS, holon=_bind_iri(target_iri))
        for r in interior_rows:
            data_graph += self._ds._safe_layer_graph(r["graph"])
        data_graph += projected

        # Build shapes graph from boundaries
        shapes_graph = Graph()
        missing_boundaries: list[str] = []
        boundary_rows = self._ds.backend.query(Q.GET_HOLON_BOUNDARIES, holon=_bind_iri(target_iri))
        for r in boundary_rows:
            shapes_graph += self._ds._safe_layer_graph(r["graph"], missing=missing_boundaries)

        # Validate the merged state
        if len(shapes_graph) == 0:
            return projected, MembraneResult(
                holon_iri=target_iri,
                conforms=True,
                health=MembraneHealth.INTACT,
                report_text=self._ds._no_shapes_report(missing_boundaries),
            )

        conforms, report_graph, report_text = pyshacl.validate(
            data_graph,
            shacl_graph=shapes_graph,
            allow_infos=True,
        )

        report = _parse_shacl_report(report_graph)

        # Untargeted projected nodes are reported at the holon's declared
        # severity, Info by default; traverse(fail_on_breach=True) defaults
        # to Violation for the same nodes (holonic#50).
        permitted, declared = untargeted_policy(shapes_graph, _bind_iri(target_iri))
        severity = untargeted_severity_label(declared, "Info")
        candidates = set(projected.subjects(RDF.type, None))
        found = find_untargeted(data_graph, shapes_graph, permitted, candidates) or []
        untargeted = [UntargetedNode(str(n), types, severity) for n, types in found]
        health = _health_from_report(report, untargeted)

        return projected, MembraneResult(
            holon_iri=target_iri,
            conforms=conforms,
            health=health,
            report_text=report_text,
            violations=report.violations,
            warnings=report.warnings,
            infos=report.infos,
            shape_violations=report.shape_violations,
            untargeted=untargeted,
        )


__all__ = ["TraversalEngine"]
