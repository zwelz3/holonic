"""Graph-native holonic dataset client.

HolonicDataset is a thin Python wrapper around a HolonicStore.
All state lives in the store as named graphs.  All discovery,
traversal, and validation use SPARQL against the store.
Python methods are convenience, not architecture.
"""

from __future__ import annotations

import logging
import uuid
import warnings
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from rdflib import Graph, Namespace
from rdflib.namespace import RDF, RDFS, XSD

from holonic import sparql as Q
from holonic.backends.rdflib_backend import RdflibBackend
from holonic.backends.store import HolonicStore
from holonic.console_model import (
    ClassInstanceCount,
    GraphMetadata,
    HolonDetail,
    HolonSummary,
    NeighborhoodEdge,
    NeighborhoodGraph,
    NeighborhoodNode,
    PortalDetail,
    PortalSummary,
    ProjectionPipelineSpec,
    ProjectionPipelineStep,
    ProjectionPipelineSummary,
)
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


# ══════════════════════════════════════════════════════════════
# Module-level helpers for 0.3.5
# ══════════════════════════════════════════════════════════════


def _escape_ttl(s: str) -> str:
    """Escape a string for use inside a Turtle "..." literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _escape_construct(s: str) -> str:
    """Escape a CONSTRUCT for use inside Turtle triple-quoted literal.

    Triple-quoted literals allow most content, but backslash-escape
    triple quotes if they appear in the query body.
    """
    return s.replace('"""', '\\"\\"\\"')


def _run_construct_on_graph(graph: Graph, construct_query: str) -> Graph:
    """Run a SPARQL CONSTRUCT against an in-memory Graph.

    Used by run_projection when a step carries an inline CONSTRUCT.
    Isolated from the dataset backend so intermediate results stay
    ephemeral and don't pollute named-graph state.
    """
    return graph.query(construct_query).graph


class HolonicDataset:
    """A holonic system backed by an RDF quad store.

    Parameters
    ----------
    backend :
        A HolonicStore implementation. Defaults to RdflibBackend
        (in-memory rdflib.Dataset). Any duck-typed object satisfying
        the protocol works; ``AbstractHolonicStore`` is the
        recommended base class for custom implementations.
    registry_iri :
        IRI of the named graph holding holon/portal declarations and
        graph-level metadata. Default: ``urn:holarchy:registry``.
        ``registry_graph`` is accepted as a deprecated alias.
    load_ontology :
        If True (default), load the CGA ontology and shapes into
        the dataset on construction.
    metadata_updates :
        One of ``"eager"`` (default) or ``"off"``. See § D-0.3.3-2.
    """

    # Map the _register_layer predicate shortcut to the cga:LayerRole
    # individual for graph typing. Added 0.3.4.
    _PREDICATE_ROLE_MAP: dict[str, str] = {
        "hasInterior": "InteriorRole",
        "hasBoundary": "BoundaryRole",
        "hasProjection": "ProjectionRole",
        "hasContext": "ContextRole",
    }

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
        backend: HolonicStore | None = None,
        *,
        registry_iri: str = REGISTRY_GRAPH,
        registry_graph: str | None = None,
        load_ontology: bool = True,
        metadata_updates: str = "eager",
    ):
        """Construct a HolonicDataset.

        Parameters
        ----------
        backend :
            A HolonicStore instance. Defaults to RdflibBackend().
        registry_iri :
            IRI of the registry graph (holon/portal declarations
            and graph-level metadata). Default: urn:holarchy:registry.
            In 0.3.x this parameter was ``registry_graph``; the old
            name is still accepted with a DeprecationWarning and will
            be removed in 0.5.0.
        registry_graph :
            Deprecated alias for ``registry_iri``. Do not use both.
        load_ontology :
            Whether to auto-load the CGA ontology into the store.
        metadata_updates :
            One of ``"eager"`` or ``"off"``. When ``"eager"`` (default),
            graph-level metadata is refreshed on every library-mediated
            write to a layer graph. When ``"off"``, callers refresh
            explicitly via ``refresh_metadata()``. See
            docs/DECISIONS.md § D-0.3.3-2.
        """
        if metadata_updates not in ("eager", "off"):
            raise ValueError(f"metadata_updates must be 'eager' or 'off', got {metadata_updates!r}")

        # Handle the 0.3.x -> 0.4.0 registry_graph -> registry_iri rename.
        if registry_graph is not None:
            import os

            if registry_iri != REGISTRY_GRAPH:
                raise ValueError(
                    "Cannot pass both registry_iri and registry_graph; "
                    "the latter is a deprecated alias for the former."
                )
            if not os.environ.get("HOLONIC_SILENCE_DEPRECATION"):
                warnings.warn(
                    "registry_graph is deprecated; use registry_iri instead. "
                    "The registry_graph parameter will be removed in 0.5.0.",
                    DeprecationWarning,
                    stacklevel=2,
                )
            registry_iri = registry_graph

        self.backend: HolonicStore = backend or RdflibBackend()
        self.registry_iri = registry_iri
        self._metadata_updates = metadata_updates

        if load_ontology:
            self._load_ontology()

        # Metadata refresher is always constructed; `metadata_updates`
        # controls whether it runs automatically, not whether it exists.
        from holonic._metadata import MetadataRefresher

        self._metadata = MetadataRefresher(backend=self.backend, registry_iri=self.registry_iri)

        # Scope resolver (0.3.4). Delegated to by HolonicDataset.resolve().
        from holonic.scope import ScopeResolver

        self._scope = ScopeResolver(backend=self.backend, registry_iri=self.registry_iri)

    @property
    def registry_graph(self) -> str:
        """Deprecated alias for ``registry_iri``. Read-only.

        Kept for 0.3.x compatibility; access does NOT emit a warning
        (too noisy for existing code). The constructor parameter by
        the same name DOES warn. Scheduled for removal in 0.5.0.
        """
        return self.registry_iri

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
        self.backend.parse_into(self.registry_iri, ttl, "turtle")
        return iri

    # TODO move predicate to arg[1] position
    def _register_layer(self, holon_iri: str, graph_iri: str, predicate: str) -> None:
        """Register a layer graph with the holon and type it in the registry.

        Writes three triples into the registry graph:
        - ``<holon_iri> cga:<predicate> <graph_iri>`` (the layer binding)
        - ``<graph_iri> a cga:HolonicGraph`` (the graph-type declaration, 0.3.4)
        - ``<graph_iri> cga:graphRole <role>`` (the role individual, 0.3.4)

        ``predicate`` is the bare suffix like ``"hasInterior"``; the
        corresponding role is derived (``hasInterior -> InteriorRole``,
        etc.) per the 0.3.4 graph-type vocabulary. See D-0.3.4-1 and
        D-0.3.4-2 in docs/DECISIONS.md.
        """
        role = self._PREDICATE_ROLE_MAP.get(predicate)
        ttl = f"""
            @prefix cga: <urn:holonic:ontology:> .
            <{holon_iri}> cga:{predicate} <{graph_iri}> .
        """
        if role:
            ttl += f"""
            <{graph_iri}> a cga:HolonicGraph ;
                cga:graphRole cga:{role} .
            """
        self.backend.parse_into(self.registry_iri, ttl, "turtle")

    def _maybe_refresh(self, graph_iri: str) -> None:
        """Trigger automatic metadata refresh if eager mode is active.

        Called after every library-mediated write to a layer graph.
        No-op when ``metadata_updates="off"``. See D-0.3.3-5 in
        docs/DECISIONS.md for the trigger list.
        """
        if self._metadata_updates == "eager":
            self._metadata.refresh_graph(graph_iri)

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
        self._maybe_refresh(graph_iri)
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
        self._maybe_refresh(graph_iri)
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
        self._maybe_refresh(graph_iri)
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
        self._maybe_refresh(graph_iri)
        return graph_iri

    def remove_holon(self, iri: str) -> bool:
        """Remove a holon and all its associated state from the dataset.

        Completes the CRUD lifecycle started by :meth:`add_holon`. Cleans
        up the holon's registry entry, all layer graphs, graph-level
        metadata records, and any portals incident to the holon.

        Parameters
        ----------
        iri :
            The holon's IRI.

        Returns:
        -------
        bool
            ``True`` if the holon existed and was removed. ``False`` if
            the IRI was not found in the registry (idempotent — not an
            error).

        Notes:
        -----
        What is removed:

        - The holon's registry entry (``cga:Holon`` type triple,
          ``rdfs:label``, ``cga:memberOf``)
        - All ``cga:hasInterior`` / ``hasBoundary`` / ``hasProjection``
          / ``hasContext`` bindings in the registry
        - The layer graphs themselves (via ``backend.delete_graph``)
        - Graph-typing triples for the layer graphs (``cga:HolonicGraph``,
          ``cga:graphRole`` — added by 0.3.4 eager typing)
        - Graph-level metadata records (``cga:tripleCount``,
          ``cga:lastModified``, ``cga:ClassInstanceCount`` inventory
          records — added by 0.3.3)
        - The per-holon rollup (``cga:holonLastModified``)
        - ``cga:memberOf`` triples where OTHER holons reference this
          holon as parent (those children become root-level; they are
          NOT themselves deleted)
        - Any portals where this holon is the source or target
          (delegated to :meth:`remove_portal`)

        What is preserved:

        - Child holons (they become parentless, not deleted — matches
          the semantic that the containment relationship is dissolved,
          not the child)
        - Provenance activities referencing this holon (provenance is
          immutable history)

        When ``metadata_updates="eager"``, metadata refresh fires once
        after the full removal rather than per-layer, to avoid
        redundant work during cascading cleanup.
        """
        # Existence check. Using SELECT COUNT for backend portability
        # (ASK result handling varies across backends; COUNT is uniform).
        count_rows = list(
            self.backend.query(
                f"""
            PREFIX cga: <urn:holonic:ontology:>
            SELECT (COUNT(*) AS ?n) WHERE {{
                GRAPH <{self.registry_iri}> {{
                    <{iri}> a cga:Holon .
                }}
            }}
            """
            )
        )
        exists = bool(count_rows) and int(count_rows[0]["n"]) > 0
        if not exists:
            return False

        # 1. Collect layer graph IRIs for this holon
        layer_rows = list(
            self.backend.query(
                f"""
            PREFIX cga: <urn:holonic:ontology:>
            SELECT ?graph WHERE {{
                GRAPH <{self.registry_iri}> {{
                    <{iri}> ?pred ?graph .
                    FILTER(?pred IN (cga:hasInterior, cga:hasBoundary,
                                     cga:hasProjection, cga:hasContext))
                }}
            }}
            """
            )
        )
        layer_graphs = [str(r["graph"]) for r in layer_rows]

        # 2. Collect portals where this holon is source or target
        portal_rows = list(
            self.backend.query(
                f"""
            PREFIX cga: <urn:holonic:ontology:>
            SELECT DISTINCT ?portal WHERE {{
                GRAPH ?g {{
                    ?portal ?pred <{iri}> .
                    FILTER(?pred IN (cga:sourceHolon, cga:targetHolon))
                }}
            }}
            """
            )
        )
        portal_iris = [str(r["portal"]) for r in portal_rows]

        # Suppress per-step metadata refresh during cascading cleanup —
        # we'll fire one consolidated refresh at the end.
        original_mode = self._metadata_updates
        self._metadata_updates = "off"
        try:
            # 3. Remove each portal incident to the holon
            for portal_iri in portal_iris:
                self.remove_portal(portal_iri)

            # 4. Delete each layer graph and its registry bindings
            for graph_iri in layer_graphs:
                # Delete the graph's contents
                if self.backend.graph_exists(graph_iri):
                    self.backend.delete_graph(graph_iri)
                # Delete the registry binding + graph-typing triples
                self.backend.update(
                    f"""
                    PREFIX cga: <urn:holonic:ontology:>
                    DELETE WHERE {{
                        GRAPH <{self.registry_iri}> {{
                            <{iri}> ?pred <{graph_iri}> .
                        }}
                    }}
                    """
                )
                self.backend.update(
                    f"""
                    PREFIX cga: <urn:holonic:ontology:>
                    DELETE WHERE {{
                        GRAPH <{self.registry_iri}> {{
                            <{graph_iri}> ?p ?o .
                        }}
                    }}
                    """
                )

            # 5. Remove cga:memberOf triples where OTHER holons reference
            # this holon as parent. Children become root-level; they are
            # not themselves deleted.
            self.backend.update(
                f"""
                PREFIX cga: <urn:holonic:ontology:>
                DELETE WHERE {{
                    GRAPH <{self.registry_iri}> {{
                        ?child cga:memberOf <{iri}> .
                    }}
                }}
                """
            )

            # 6. Remove the holon's own registry entry (type, label,
            # memberOf outgoing, per-holon rollup metadata, any other
            # registry-level triples about the holon).
            self.backend.update(
                f"""
                DELETE WHERE {{
                    GRAPH <{self.registry_iri}> {{
                        <{iri}> ?p ?o .
                    }}
                }}
                """
            )
        finally:
            self._metadata_updates = original_mode

        # 7. One consolidated metadata refresh after the cascade
        if self._metadata_updates == "eager":
            self._metadata.refresh_graph(self.registry_iri)

        return True

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
        construct_query: str | None = None,
        *,
        portal_type: str = "cga:TransformPortal",
        extra_ttl: str | None = None,
        label: str | None = None,
        graph_iri: str | None = None,
    ) -> str:
        """Register a portal in the source holon's boundary graph.

        The portal definition IS RDF in the boundary named graph.
        Discovery uses SPARQL, not Python lookups.

        Parameters
        ----------
        portal_iri :
            IRI for the portal resource.
        source_iri :
            IRI of the source holon.
        target_iri :
            IRI of the target holon.
        construct_query :
            Optional SPARQL CONSTRUCT query that produces the target
            interior from the source. Omit for portal subtypes that do
            not carry a SPARQL transformation (e.g. ``cga:IconPortal``,
            ``cga:SealedPortal``, or downstream subclasses whose
            transformation is specified by a different predicate).
        portal_type :
            RDF type for the portal. Defaults to ``"cga:TransformPortal"``.
            Accepts a prefixed name (``"cga:SealedPortal"``,
            ``"ext:NeuralPortal"``) or a full IRI. The caller is
            responsible for ensuring the type resolves to a declared
            class.
        extra_ttl :
            Additional Turtle triples appended verbatim to the portal
            block before parsing. Useful for portal subclasses that
            carry extra predicates. Applied to both the boundary graph
            and the registry mirror. The string should NOT include
            ``@prefix`` declarations — the method prepends the
            standard prefix block.
        label :
            Human-readable label. Defaults to "<source> → <target>".
        graph_iri :
            Explicit boundary graph IRI. Defaults to
            ``"<source_iri>/boundary"``.

        Returns:
        -------
        str
            The portal's IRI (same as the input, returned for chaining).

        Examples:
        --------
        Minimal TransformPortal with CONSTRUCT (the 0.3.x/0.4.0 form,
        unchanged)::

            ds.add_portal(
                "urn:portal:a-to-b",
                source_iri="urn:holon:a",
                target_iri="urn:holon:b",
                construct_query="CONSTRUCT { ?s ?p ?o } WHERE { GRAPH ?g { ?s ?p ?o } }",
            )

        SealedPortal with no CONSTRUCT query::

            ds.add_portal(
                "urn:portal:sealed",
                source_iri="urn:holon:a",
                target_iri="urn:holon:b",
                portal_type="cga:SealedPortal",
            )

        Downstream portal subclass carrying extra predicates::

            ds.add_portal(
                "urn:portal:neural",
                source_iri="urn:holon:a",
                target_iri="urn:holon:b",
                portal_type="ext:NeuralPortal",
                extra_ttl='''
                    @prefix ext: <urn:ext:> .
                    <urn:portal:neural> ext:transformRef <urn:model:v1> ;
                        ext:portalWeight 0.87 .
                ''',
            )
        """
        graph_iri = graph_iri or f"{source_iri}/boundary"
        # TODO to_pithy_id
        lbl = label or f"{source_iri} → {target_iri}"

        # Extract any @prefix lines from extra_ttl so they can be placed
        # at the top of the combined Turtle block (prefix declarations
        # must precede any triples in Turtle syntax).
        extra_prefixes = ""
        extra_body = ""
        if extra_ttl:
            for line in extra_ttl.splitlines():
                stripped = line.strip()
                if stripped.lower().startswith("@prefix") and stripped.endswith("."):
                    extra_prefixes += line + "\n"
                else:
                    extra_body += line + "\n"

        ttl = f"""
            @prefix cga:  <urn:holonic:ontology:> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            {extra_prefixes}
            <{portal_iri}> a {portal_type} ;
                cga:sourceHolon <{source_iri}> ;
                cga:targetHolon <{target_iri}> ;
                rdfs:label "{lbl}\""""
        if construct_query is not None:
            escaped_query = construct_query.replace("\\", "\\\\").replace('"', '\\"')
            ttl += f' ;\n                cga:constructQuery """{escaped_query}"""'
        ttl += " .\n"

        if extra_body.strip():
            ttl += extra_body + "\n"

        self.backend.parse_into(graph_iri, ttl, "turtle")
        # Also ensure portal is visible from registry
        self.backend.parse_into(self.registry_iri, ttl, "turtle")
        self._maybe_refresh(graph_iri)
        return portal_iri

    def remove_portal(self, portal_iri: str) -> bool:
        """Remove a portal from the dataset.

        Cleans up all triples with ``portal_iri`` as subject across every
        named graph that contains them (typically the source holon's
        boundary graph and the registry mirror). The boundary graph
        itself is preserved; only the triples about this specific
        portal are deleted.

        Parameters
        ----------
        portal_iri :
            The portal's IRI.

        Returns:
        -------
        bool
            ``True`` if the portal existed and was removed. ``False`` if
            the IRI was not found in any graph (idempotent — not an
            error).

        Notes:
        -----
        Does NOT remove:

        - The source or target holons
        - The boundary graph itself (other portals or SHACL shapes may
          live there)
        - Provenance activities referencing this portal

        When ``metadata_updates="eager"``, metadata for each affected
        graph is refreshed after the removal.
        """
        # Find every graph containing triples about this portal
        rows = list(
            self.backend.query(
                f"""
            SELECT DISTINCT ?g WHERE {{
                GRAPH ?g {{ <{portal_iri}> ?p ?o }}
            }}
            """
            )
        )
        if not rows:
            return False

        affected_graphs = [str(r["g"]) for r in rows]

        # Delete all triples with the portal as subject in each graph
        for g in affected_graphs:
            self.backend.update(
                f"""
                DELETE WHERE {{
                    GRAPH <{g}> {{ <{portal_iri}> ?p ?o }}
                }}
                """
            )

        # Belt-and-suspenders: also delete from the registry in case the
        # portal was added without the registry mirror being picked up
        # by the graph search (e.g. if the portal's only subject-position
        # triples were in blank-node contexts that elided the discovery).
        if self.registry_iri not in affected_graphs:
            self.backend.update(
                f"""
                DELETE WHERE {{
                    GRAPH <{self.registry_iri}> {{ <{portal_iri}> ?p ?o }}
                }}
                """
            )

        # Refresh metadata for affected graphs if eager
        for g in affected_graphs:
            self._maybe_refresh(g)

        return True

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
            self._maybe_refresh(inject_into)

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
            self._maybe_refresh(store_as)

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
                ?portal cga:sourceHolon ?src ;
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
                        ?portal cga:sourceHolon ?src ;
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
            self._maybe_refresh(store_as)

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
                GRAPH <{self.registry_iri}> {{
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

    def list_holons_summary(self) -> list[HolonSummary]:
        """Return lightweight holon summaries for browser/list views.

        Single SPARQL query — no per-holon layer fan-out. Use
        ``get_holon_detail()`` for the full picture of one holon.
        """
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

    def get_holon_detail(self, holon_iri: str) -> HolonDetail | None:
        """Return the full holon descriptor including layer graph IRIs.

        Returns None if the holon is not registered.
        """
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

        # Per-layer metadata from the registry. Added 0.3.3. Any layer
        # graph with no materialized metadata is simply absent from the
        # dict — callers should not assume full coverage.
        all_layer_graphs = (
            detail.interior_graphs
            + detail.boundary_graphs
            + detail.projection_graphs
            + detail.context_graphs
        )
        last_modified_seen: list[str] = []
        for g in all_layer_graphs:
            md = self._metadata.read(g)
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

    def list_portals(self) -> list[PortalSummary]:
        """Return a flat list of all portals across the dataset."""
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

    def get_portal(self, portal_iri: str) -> PortalDetail | None:
        """Return the full portal descriptor including the CONSTRUCT body.

        Returns None if no portal with that IRI is registered.
        """
        # Single query to pull all portal triples
        rows = self.backend.query(f"""
            PREFIX cga:  <urn:holonic:ontology:>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

            SELECT ?source ?target ?label ?query
            WHERE {{
                GRAPH ?g {{
                    <{portal_iri}> cga:sourceHolon ?source ;
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

    # ══════════════════════════════════════════════════════════
    # Graph-level metadata (0.3.3)
    # ══════════════════════════════════════════════════════════

    def refresh_metadata(self, holon_iri: str) -> list[GraphMetadata]:
        """Recompute and persist metadata for all of a holon's layer graphs.

        Writes per-graph metadata (triple count, last-modified, class
        inventory) and the per-holon rollup to the registry graph.
        Use after out-of-band writes via ``backend.put_graph()`` or
        ``backend.update()``.

        Returns the refreshed per-graph metadata in the order
        returned by the registry's ``cga:hasLayer`` enumeration.
        """
        return self._metadata.refresh_holon(holon_iri)

    def refresh_all_metadata(self) -> int:
        """Refresh metadata for every holon in the registry.

        Returns the number of holons refreshed. Use after bulk data
        loads that bypass the library's mutation API.
        """
        n = 0
        for h in self.list_holons_summary():
            self._metadata.refresh_holon(h.iri)
            n += 1
        return n

    def get_graph_metadata(self, graph_iri: str) -> GraphMetadata | None:
        """Return currently-materialized metadata for a graph.

        Returns ``None`` if no metadata has been written. Use
        ``refresh_metadata()`` to materialize it.
        """
        return self._metadata.read(graph_iri)

    # ══════════════════════════════════════════════════════════
    # Scoped discovery (0.3.4)
    # ══════════════════════════════════════════════════════════

    def resolve(
        self,
        predicate,
        from_holon: str,
        *,
        max_depth: int = 3,
        order: str = "network",
        limit: int = 50,
    ):
        """Walk the holarchy in BFS order and return predicate matches.

        Parameters
        ----------
        predicate :
            A ``ResolvePredicate`` instance (``HasClassInInterior``,
            ``CustomSPARQL``, or any object with the predicate
            protocol from ``holonic.scope``).
        from_holon :
            IRI of the starting holon.
        max_depth :
            BFS depth limit. Clamped to ``[0, 100]``.
        order :
            ``"network"`` (outbound+inbound portals, default),
            ``"reverse-network"`` (inbound only), or
            ``"containment"`` (``cga:memberOf`` walk).
        limit :
            Maximum number of matches. Clamped to ``[1, 10_000]``.

        Returns:
        -------
        list[ResolveMatch]
            Matches in BFS depth order. See ``holonic.scope`` for
            the dataclass and predicate types.
        """
        return self._scope.resolve(
            predicate=predicate,
            from_holon=from_holon,
            max_depth=max_depth,
            order=order,
            limit=limit,
        )

    def _pipeline_to_ttl(self, spec: ProjectionPipelineSpec) -> str:
        """Convert a ProjectionPipelineSpec to Turtle for the registry."""
        lines = [
            "@prefix cga:  <urn:holonic:ontology:> .",
            "@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
            "",
            f"<{spec.iri}> a cga:ProjectionPipelineSpec ;",
            f'    rdfs:label "{_escape_ttl(spec.name)}" ;',
        ]
        if spec.description:
            lines[-1] += ""
            lines.append(f'    rdfs:comment "{_escape_ttl(spec.description)}" ;')

        if not spec.steps:
            # Empty pipeline — no steps, close the spec
            lines[-1] = lines[-1].rstrip(" ;") + " ."
            return "\n".join(lines)

        # Build an rdf:List of blank-node step resources
        step_iris = [f"<{spec.iri}/step/{i}>" for i in range(len(spec.steps))]
        lines[-1] += ""  # keep trailing ;
        lines.append(f"    cga:hasStep ({' '.join(step_iris)}) .")
        lines.append("")

        # Emit each step resource
        for iri, step in zip(step_iris, spec.steps):
            lines.append(f"{iri} a cga:ProjectionPipelineStep ;")
            lines.append(f'    cga:stepName "{_escape_ttl(step.name)}"')
            extras = []
            if step.transform_name:
                extras.append(f'    cga:transformName "{_escape_ttl(step.transform_name)}"')
            if step.construct_query:
                extras.append(
                    f'    cga:constructQuery """{_escape_construct(step.construct_query)}"""'
                )
            if extras:
                lines[-1] += " ;"
                for i, extra in enumerate(extras):
                    suffix = " ;" if i < len(extras) - 1 else " ."
                    lines.append(extra + suffix)
            else:
                lines[-1] += " ."
            lines.append("")
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════
    # Projection pipelines (0.3.5)
    # ══════════════════════════════════════════════════════════

    def register_pipeline(self, spec: ProjectionPipelineSpec) -> str:
        """Register a projection pipeline in the registry.

        Validates that every step's ``transform_name`` (if any) is
        known to the plugin registry. Raises ``TransformNotFoundError``
        at registration time rather than later at run time.

        Returns the pipeline's IRI.
        """
        from holonic.plugins import resolve_transform

        # Validate named transforms up front
        for step in spec.steps:
            if step.transform_name:
                resolve_transform(step.transform_name)

        # Serialize to Turtle and write to registry
        ttl = self._pipeline_to_ttl(spec)
        self.backend.parse_into(self.registry_iri, ttl, "turtle")
        return spec.iri

    def register_pipeline_ttl(self, ttl: str) -> None:
        """Escape hatch: register a pipeline from caller-supplied Turtle.

        Parses the Turtle into the registry graph without validation.
        Caller is responsible for conforming to the
        ``cga:ProjectionPipelineSpec`` + ``cga:ProjectionPipelineStep``
        vocabulary and for valid rdf:List ordering.
        """
        self.backend.parse_into(self.registry_iri, ttl, "turtle")

    def attach_pipeline(self, holon_iri: str, spec_iri: str) -> None:
        """Declare that a holon has access to a registered pipeline.

        Writes ``<holon_iri> cga:hasPipeline <spec_iri>`` into the
        registry graph. Idempotent at the RDF level (duplicate
        triples in the same graph are coalesced).
        """
        self.backend.parse_into(
            self.registry_iri,
            f"""
            @prefix cga: <urn:holonic:ontology:> .
            <{holon_iri}> cga:hasPipeline <{spec_iri}> .
            """,
            "turtle",
        )

    def list_pipelines(self, holon_iri: str) -> list[ProjectionPipelineSummary]:
        """Return projection pipelines attached to a holon.

        Each summary carries just iri, name, description, and step
        count — use ``get_pipeline(iri)`` for full step content.
        """
        from holonic.console_model import ProjectionPipelineSummary

        rows = self.backend.query(
            Q.LIST_PIPELINES_FOR_HOLON_TEMPLATE.format(
                registry_iri=self.registry_iri,
                holon_iri=holon_iri,
            )
        )
        return [
            ProjectionPipelineSummary(
                iri=str(r["spec"]),
                name=str(r["name"]),
                description=str(r["description"]) if r.get("description") else None,
                step_count=int(r.get("step_count") or 0),
            )
            for r in rows
        ]

    def _step_from_node(self, reg_graph, step_node):
        """Materialize a ProjectionPipelineStep from its graph node."""
        from rdflib import URIRef

        from holonic.console_model import ProjectionPipelineStep

        cga_stepName = URIRef("urn:holonic:ontology:stepName")
        cga_transformName = URIRef("urn:holonic:ontology:transformName")
        cga_constructQuery = URIRef("urn:holonic:ontology:constructQuery")
        name = reg_graph.value(step_node, cga_stepName)
        transform = reg_graph.value(step_node, cga_transformName)
        construct = reg_graph.value(step_node, cga_constructQuery)
        return ProjectionPipelineStep(
            name=str(name) if name else "",
            transform_name=str(transform) if transform else None,
            construct_query=str(construct) if construct else None,
        )

    def _read_pipeline_steps_ordered(self, spec_iri: str) -> list[ProjectionPipelineStep]:
        """Read pipeline steps preserving rdf:List order."""
        from rdflib import RDF, URIRef

        reg = self.backend.get_graph(self.registry_iri)
        spec = URIRef(spec_iri)
        cga_hasStep = URIRef("urn:holonic:ontology:hasStep")
        head = reg.value(spec, cga_hasStep)
        if head is None:
            return []
        # Walk rdf:first / rdf:rest
        steps: list[ProjectionPipelineStep] = []
        current = head
        while current and current != RDF.nil:
            step_node = reg.value(current, RDF.first)
            if step_node is None:
                break
            step = self._step_from_node(reg, step_node)
            steps.append(step)
            current = reg.value(current, RDF.rest)
        return steps

    def get_pipeline(self, spec_iri: str) -> ProjectionPipelineSpec | None:
        """Return the full pipeline spec as a ``ProjectionPipelineSpec``.

        Returns ``None`` if no pipeline with the given IRI is registered.
        Steps are returned in their declared rdf:List order.
        """
        from holonic.console_model import (
            ProjectionPipelineSpec,
        )

        detail_rows = self.backend.query(
            Q.READ_PIPELINE_DETAIL_TEMPLATE.format(
                registry_iri=self.registry_iri,
                spec_iri=spec_iri,
            )
        )
        if not detail_rows:
            return None
        name = str(detail_rows[0]["name"])
        description = (
            str(detail_rows[0]["description"]) if detail_rows[0].get("description") else None
        )
        # Walk the rdf:List in registered order. We pull it from the
        # registry graph directly so ordering is canonical.
        steps = self._read_pipeline_steps_ordered(spec_iri)
        return ProjectionPipelineSpec(
            iri=spec_iri,
            name=name,
            description=description,
            steps=steps,
        )

    def _record_projection_activity(
        self,
        *,
        holon_iri: str,
        spec_iri: str,
        output_graph_iri: str | None,
        started: datetime,
        ended: datetime,
        agent_iri: str | None,
        transform_versions: list[str],
        host_meta: dict[str, str],
    ) -> str:
        """Write a prov:Activity for a projection run. Returns activity IRI."""
        activity_iri = f"urn:activity:projection:{uuid4()}"
        # Find or default the holon's context graph
        context_rows = self.backend.query(Q.GET_HOLON_CONTEXTS.replace("?holon", f"<{holon_iri}>"))
        if context_rows:
            ctx_graph_iri = str(context_rows[0]["graph"])
        else:
            ctx_graph_iri = f"{holon_iri}/context"
            self._register_layer(holon_iri, ctx_graph_iri, "hasContext")

        ttl_lines = [
            "@prefix cga:  <urn:holonic:ontology:> .",
            "@prefix prov: <http://www.w3.org/ns/prov#> .",
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
            "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .",
            "",
            f"<{activity_iri}> a prov:Activity ;",
            f'    rdfs:label "Projection run: {_escape_ttl(spec_iri)}" ;',
            f"    prov:used <{spec_iri}> ;",
            f'    prov:startedAtTime "{started.isoformat()}"^^xsd:dateTime ;',
            f'    prov:endedAtTime "{ended.isoformat()}"^^xsd:dateTime ;',
        ]
        if output_graph_iri:
            ttl_lines.append(f"    prov:generated <{output_graph_iri}> ;")
        if agent_iri:
            ttl_lines.append(f"    prov:wasAssociatedWith <{agent_iri}> ;")
        for v in transform_versions:
            ttl_lines.append(f'    cga:transformVersion "{_escape_ttl(v)}" ;')
        ttl_lines.append(f'    cga:runHost "{_escape_ttl(host_meta["host"])}" ;')
        ttl_lines.append(f'    cga:runPlatform "{_escape_ttl(host_meta["platform"])}" ;')
        ttl_lines.append(f'    cga:runPythonVersion "{_escape_ttl(host_meta["python_version"])}" ;')
        ttl_lines.append(
            f'    cga:runHolonicVersion "{_escape_ttl(host_meta["holonic_version"])}" .'
        )

        self.backend.parse_into(ctx_graph_iri, "\n".join(ttl_lines), "turtle")
        return activity_iri

    def run_projection(
        self,
        holon_iri: str,
        spec_iri: str,
        *,
        store_as: str | None = None,
        agent_iri: str | None = None,
    ) -> Graph:
        """Execute a registered pipeline against a holon's interiors.

        Merges the holon's interior graphs, runs each step in
        declared order (transform first, then inline CONSTRUCT if
        present), and optionally stores the result as a named graph
        registered as a projection layer.

        Records a ``prov:Activity`` in the holon's context graph
        with:

        - ``prov:used <spec_iri>``
        - ``prov:generated <output_graph_iri>`` (if ``store_as``)
        - ``prov:startedAtTime`` / ``prov:endedAtTime``
        - ``prov:wasAssociatedWith <agent_iri>`` (if provided)
        - ``cga:transformVersion`` for each transform used
        - ``cga:runHost``, ``cga:runPlatform``, ``cga:runPythonVersion``,
          ``cga:runHolonicVersion``

        Raises ``ValueError`` if the spec is not registered, or
        ``TransformNotFoundError`` if a step references an unknown
        transform.
        """
        from holonic.plugins import (
            host_metadata,
            resolve_transform,
            transform_version,
        )

        spec = self.get_pipeline(spec_iri)
        if spec is None:
            raise ValueError(f"No pipeline registered with IRI {spec_iri!r}")

        started = datetime.now(UTC)

        # Merge interiors
        interior_rows = self.backend.query(
            Q.GET_HOLON_INTERIORS.replace("?holon", f"<{holon_iri}>")
        )
        merged = Graph()
        for row in interior_rows:
            g = self.backend.get_graph(row["graph"])
            for triple in g:
                merged.add(triple)

        # Execute steps
        current = merged
        transform_versions: list[str] = []
        for step in spec.steps:
            if step.transform_name:
                fn = resolve_transform(step.transform_name)
                current = fn(current)
                ver = transform_version(step.transform_name)
                if ver:
                    transform_versions.append(ver)
            if step.construct_query:
                # Run the CONSTRUCT against the current intermediate graph
                current = _run_construct_on_graph(current, step.construct_query)

        ended = datetime.now(UTC)

        # Optionally store result and register as a projection
        if store_as:
            self.backend.put_graph(store_as, current)
            self._register_layer(holon_iri, store_as, "hasProjection")
            self._maybe_refresh(store_as)

        # Record provenance in the holon's context graph
        self._record_projection_activity(
            holon_iri=holon_iri,
            spec_iri=spec_iri,
            output_graph_iri=store_as,
            started=started,
            ended=ended,
            agent_iri=agent_iri,
            transform_versions=transform_versions,
            host_meta=host_metadata(),
        )

        return current
