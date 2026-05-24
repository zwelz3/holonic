"""Graph-native holonic dataset client.

HolonicDataset is a thin Python wrapper around a HolonicStore.
All state lives in the store as named graphs.  All discovery,
traversal, and validation use SPARQL against the store.
Python methods are convenience, not architecture.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from rdflib import Graph, Namespace, URIRef
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
    MembraneBreachError,
    MembraneHealth,
    MembraneResult,
    PortalInfo,
    ShapeViolation,
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

# Sentinel for distinguishing "not passed" from "passed as None"
_SENTINEL = object()


# ══════════════════════════════════════════════════════════════
# Module-level helpers for 0.3.5
# ══════════════════════════════════════════════════════════════


def classify_sparql(
    query: str,
) -> str:
    """Classify a SPARQL query by its form.

    Returns one of ``'select'``, ``'ask'``, ``'construct'``,
    ``'describe'``, or ``'update'``.

    Strips comments and string literals before matching the first
    keyword. Raises ``ValueError`` if the form cannot be determined.

    .. versionadded:: 0.7.0
    """
    import re

    # Strip comments and string literals
    cleaned = re.sub(r"#[^\n]*", "", query)
    cleaned = re.sub(r'""".*?"""', "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"'''.*?'''", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'"[^"]*"', "", cleaned)
    cleaned = re.sub(r"'[^']*'", "", cleaned)
    cleaned = cleaned.strip()

    upper = cleaned.upper()
    for form in ("SELECT", "ASK", "CONSTRUCT", "DESCRIBE"):
        if form in upper.split():
            return form.lower()
    for kw in ("INSERT", "DELETE", "LOAD", "CLEAR", "DROP", "CREATE", "COPY", "MOVE", "ADD"):
        if kw in upper.split():
            return "update"
    raise ValueError(f"Cannot classify SPARQL query: {query[:80]!r}")


# Characters that are unsafe when an IRI is interpolated into a
# Turtle ``<…>`` or SPARQL ``<…>`` context.  This is a pragmatic
# subset of RFC 3987 § 2.2; a full IRI parser would be heavier
# than the value it adds at this layer.
_IRI_UNSAFE = set(' <>"{}\x00\n\r\t\\')


def _validate_iri(iri: str, param_name: str = "iri") -> None:
    """Raise ``ValueError`` if *iri* contains characters that would
    break Turtle/SPARQL interpolation or is empty.
    """
    if not iri:
        raise ValueError(f"{param_name} must be a non-empty string")
    bad = _IRI_UNSAFE.intersection(iri)
    if bad:
        escaped = ", ".join(repr(c) for c in sorted(bad))
        raise ValueError(
            f"{param_name} contains characters unsafe for RDF serialization: {escaped}"
        )


def validate_iri(iri: str) -> None:
    """Validate an IRI for safe use in SPARQL/Turtle interpolation.

    Raises ``ValueError`` if the IRI is empty or contains characters
    that are unsafe in Turtle/SPARQL contexts (angle brackets,
    quotes, backticks, braces, whitespace except space).

    This is the public interface to the library's IRI validation.
    All ``add_*`` methods call this internally.

    .. versionadded:: 0.7.0
    """
    _validate_iri(iri, "iri")
    """Escape a string for use inside a Turtle "..." literal."""


def _escape_ttl(s: str) -> str:
    """Escape a string for use inside a Turtle literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

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


def _parse_shacl_report(
    report_graph: Graph,
) -> tuple[list[str], list[str], list[ShapeViolation]]:
    """Extract violations and warnings from a SHACL validation report graph.

    Parses the structured ``sh:ValidationResult`` entries rather than
    scanning the human-readable text, making the result independent
    of pyshacl's text-formatting choices.

    Returns ``(violations, warnings, shape_violations)`` where
    ``violations`` and ``warnings`` are human-readable summary strings,
    and ``shape_violations`` is a list of structured
    :class:`ShapeViolation` objects.
    """
    violations: list[str] = []
    warnings: list[str] = []
    structured: list[ShapeViolation] = []

    for result in report_graph.objects(predicate=SH.result):
        severity = report_graph.value(result, SH.resultSeverity)
        message = report_graph.value(result, SH.resultMessage)
        focus = report_graph.value(result, SH.focusNode)
        path = report_graph.value(result, SH.resultPath)
        source_shape = report_graph.value(result, SH.sourceShape)
        value = report_graph.value(result, SH.value)

        severity_str = str(severity) if severity else ""
        msg = str(message) if message else "No message"
        focus_str = str(focus) if focus else ""
        path_str = str(path) if path else ""

        detail_parts = [msg]
        if focus_str:
            detail_parts.append(f"focus={focus_str}")
        if path_str:
            detail_parts.append(f"path={path_str}")
        detail = "; ".join(detail_parts)

        sev_label = "Violation"
        if severity_str.endswith("Violation"):
            violations.append(f"Violation: {detail}")
            sev_label = "Violation"
        elif severity_str.endswith("Warning"):
            warnings.append(f"Warning: {detail}")
            sev_label = "Warning"
        else:
            # Info severity: skip for violation/warning lists
            continue

        structured.append(
            ShapeViolation(
                shape_iri=str(source_shape) if source_shape else None,
                focus_node=focus_str or None,
                path=path_str or None,
                value=str(value) if value else None,
                message=msg,
                severity=sev_label,
            )
        )

    return violations, warnings, structured


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
        ``registry_iri`` parameter configures the registry graph IRI.
    load_ontology :
        If True (default), load the CGA ontology and shapes into
        the dataset on construction.
    metadata_updates :
        One of ``"eager"`` (default) or ``"off"``. See § D-0.3.3-2.
    """

    class _BatchContext:
        """Internal helper returned by :meth:`HolonicDataset.batch`."""

        __slots__ = ("_ds", "_saved_mode")

        def __init__(self, ds: HolonicDataset):
            self._ds = ds
            self._saved_mode: str | None = None

        def __enter__(self) -> HolonicDataset:
            self._saved_mode = self._ds._metadata_updates
            self._ds._metadata_updates = "off"
            return self._ds

        def __exit__(
            self,
            exc_type: type | None,
            exc_val: BaseException | None,
            exc_tb: Any,
        ) -> None:
            self._ds._metadata_updates = self._saved_mode or "eager"
            if exc_type is None and self._saved_mode == "eager":
                self._ds._metadata.refresh_graph(self._ds.registry_iri)
            return None

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

        # Notification hooks (0.7.0). Callbacks fire synchronously
        # after traversal/validation within the calling thread.
        self._on_traversal: list = []
        self._on_validation: list = []

    def on_traversal(self, callback) -> None:
        """Register a callback fired after each ``traverse()``.

        The callback receives ``(source_iri, target_iri, projected,
        membrane_result)`` as arguments.

        .. versionadded:: 0.7.0
        """
        self._on_traversal.append(callback)

    def on_validation(self, callback) -> None:
        """Register a callback fired after each ``validate_membrane()``.

        The callback receives ``(holon_iri, membrane_result)``.

        .. versionadded:: 0.7.0
        """
        self._on_validation.append(callback)

    # ══════════════════════════════════════════════════════════
    # Holon management
    # ══════════════════════════════════════════════════════════

    def add_holon(
        self,
        iri: str,
        label: str,
        *,
        member_of: str | None = None,
        holon_type: str | None = None,
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
        holon_type :
            Functional subtype to assert (e.g. ``"cga:DataHolon"``,
            ``"cga:AgentHolon"``). Must be a prefixed CGA name or a
            full IRI. The holon always carries ``a cga:Holon``; this
            adds a second ``rdf:type`` assertion.

        Note:
        ----
        Depth is not stored -- it is derivable from the cga:memberOf
        chain via ``compute_depth()``.
        """
        _validate_iri(iri, "iri")
        if member_of:
            _validate_iri(member_of, "member_of")
        ttl = f"""
            @prefix cga:  <urn:holonic:ontology:> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

            <{iri}> a cga:Holon ;
                rdfs:label "{_escape_ttl(label)}" .
        """
        if member_of:
            ttl += f"    <{iri}> cga:memberOf <{member_of}> .\n"
        if holon_type:
            if holon_type.startswith("cga:") or ":" in holon_type:
                ttl += f"    <{iri}> a {holon_type} .\n"
            else:
                ttl += f"    <{iri}> a <{holon_type}> .\n"

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

    def batch(self) -> _BatchContext:
        """Context manager that suppresses per-write metadata refresh.

        Metadata refresh is deferred until the block exits, avoiding
        redundant computation during bulk writes. On normal exit, a
        single consolidated refresh runs for the registry. On
        exception, the original mode is restored without refreshing.

        Nests safely: inner ``batch()`` blocks are no-ops when an
        outer batch is already active.

        Example::

            with ds.batch():
                for row in data:
                    ds.add_holon(row["iri"], row["label"])
                    ds.add_interior(row["iri"], row["ttl"])
            # metadata refreshed once here

        .. versionadded:: 0.6.0
        """
        return self._BatchContext(self)

    def add_interior(
        self,
        holon_iri: str,
        ttl: str,
        *,
        graph_iri: str | None = None,
    ) -> str:
        """Parse TTL into a named graph and register it as a holon's interior."""
        _validate_iri(holon_iri, "holon_iri")
        if graph_iri:
            _validate_iri(graph_iri, "graph_iri")
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
        _validate_iri(holon_iri, "holon_iri")
        if graph_iri:
            _validate_iri(graph_iri, "graph_iri")
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
        _validate_iri(holon_iri, "holon_iri")
        if graph_iri:
            _validate_iri(graph_iri, "graph_iri")
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
        _validate_iri(holon_iri, "holon_iri")
        if graph_iri:
            _validate_iri(graph_iri, "graph_iri")
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
            the IRI was not found in the registry (idempotent -- not an
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
          ``cga:graphRole`` -- added by 0.3.4 eager typing)
        - Graph-level metadata records (``cga:tripleCount``,
          ``cga:lastModified``, ``cga:ClassInstanceCount`` inventory
          records -- added by 0.3.3)
        - The per-holon rollup (``cga:holonLastModified``)
        - ``cga:memberOf`` triples where OTHER holons reference this
          holon as parent (those children become root-level; they are
          NOT themselves deleted)
        - Any portals where this holon is the source or target
          (delegated to :meth:`remove_portal`)

        What is preserved:

        - Child holons (they become parentless, not deleted -- matches
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

        # Suppress per-step metadata refresh during cascading cleanup --
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

    def update_portal(
        self,
        portal_iri: str,
        *,
        construct_query: str | None = _SENTINEL,
        label: str | None = _SENTINEL,
        portal_type: str | None = _SENTINEL,
    ) -> None:
        """Update a portal's properties in-place.

        Only the provided keyword arguments are changed; unspecified
        properties are preserved. The portal IRI and source/target
        holons are immutable (use remove + add to change those).

        Parameters
        ----------
        portal_iri :
            IRI of the portal to update.
        construct_query :
            New CONSTRUCT query string, or None to remove it.
        label :
            New label, or None to remove it.
        portal_type :
            New RDF type (e.g. ``"cga:SealedPortal"``).

        Raises:
        ------
        ValueError
            If the portal does not exist.

        .. versionadded:: 0.6.0
        """
        # Verify portal exists
        detail = self.get_portal(portal_iri)
        if detail is None:
            raise ValueError(f"Portal {portal_iri} not found")

        # Build targeted updates for each changed property.
        # rdflib's get_graph returns a reference (not copy), so we use
        # per-graph SPARQL DELETE WHERE with explicit graph names.
        if construct_query is not _SENTINEL:
            # Find which graphs contain the old constructQuery
            cq_graphs = self.backend.query(f"""
                PREFIX cga: <urn:holonic:ontology:>
                SELECT DISTINCT ?g WHERE {{
                    GRAPH ?g {{ <{portal_iri}> cga:constructQuery ?q }}
                }}
            """)
            # Delete old value from each graph individually
            for row in cq_graphs:
                g_iri = row["g"]
                self.backend.update(f"""
                    PREFIX cga: <urn:holonic:ontology:>
                    DELETE WHERE {{
                        GRAPH <{g_iri}> {{ <{portal_iri}> cga:constructQuery ?old }}
                    }}
                """)
            # Insert new query via Turtle parse (avoids SPARQL escaping)
            if construct_query is not None:
                escaped = construct_query.replace("\\", "\\\\").replace('"', '\\"')
                ttl = (
                    f"@prefix cga: <urn:holonic:ontology:> .\n"
                    f'<{portal_iri}> cga:constructQuery """{escaped}""" .\n'
                )
                self.backend.parse_into(self.registry_iri, ttl, "turtle")

        if label is not _SENTINEL:
            lbl_graphs = self.backend.query(f"""
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT DISTINCT ?g WHERE {{
                    GRAPH ?g {{ <{portal_iri}> rdfs:label ?l }}
                }}
            """)
            for row in lbl_graphs:
                g_iri = row["g"]
                self.backend.update(f"""
                    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                    DELETE WHERE {{
                        GRAPH <{g_iri}> {{ <{portal_iri}> rdfs:label ?old }}
                    }}
                """)
            if label is not None:
                ttl = (
                    f"@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
                    f'<{portal_iri}> rdfs:label "{_escape_ttl(label)}" .\n'
                )
                self.backend.parse_into(self.registry_iri, ttl, "turtle")

        if portal_type is not _SENTINEL and portal_type is not None:
            # Find and remove old subtypes per-graph
            type_graphs = self.backend.query(f"""
                PREFIX cga: <urn:holonic:ontology:>
                SELECT DISTINCT ?g ?type WHERE {{
                    GRAPH ?g {{
                        <{portal_iri}> a ?type .
                        FILTER(?type != cga:Portal)
                    }}
                }}
            """)
            for row in type_graphs:
                g_iri = row["g"]
                old_type = row["type"]
                self.backend.update(f"""
                    DELETE DATA {{
                        GRAPH <{g_iri}> {{
                            <{portal_iri}> a <{old_type}> .
                        }}
                    }}
                """)
            # Insert new type into registry AND the boundary graph
            # (boundary is where structural triples live; queries
            # look for type in the same graph as sourceHolon)
            ttl = f"@prefix cga: <urn:holonic:ontology:> .\n<{portal_iri}> a {portal_type} .\n"
            self.backend.parse_into(self.registry_iri, ttl, "turtle")
            # Find the boundary graph
            bnd_rows = self.backend.query(f"""
                PREFIX cga: <urn:holonic:ontology:>
                SELECT ?g WHERE {{
                    GRAPH ?g {{
                        <{portal_iri}> cga:sourceHolon ?s .
                    }}
                    FILTER(?g != <{self.registry_iri}>)
                }} LIMIT 1
            """)
            if bnd_rows:
                self.backend.parse_into(
                    bnd_rows[0]["g"],
                    ttl,
                    "turtle",
                )

        if self._metadata_updates == "eager":
            self._metadata.refresh_graph(self.registry_iri)

    # ══════════════════════════════════════════════════════════
    # Bulk loading
    # ══════════════════════════════════════════════════════════

    def bulk_load(
        self,
        holons: list[dict] | None = None,
        portals: list[dict] | None = None,
    ) -> tuple[int, int]:
        """Create multiple holons and portals in a single batch.

        Suppresses per-write metadata refresh during the batch and
        fires one consolidated refresh at the end.  For holarchies
        with hundreds of holons, this is significantly faster than
        calling ``add_holon`` and ``add_portal`` in a loop.

        Parameters
        ----------
        holons :
            List of dicts, each with keys matching ``add_holon()``
            parameters: ``iri`` (required), ``label`` (required),
            and optionally ``member_of``, ``holon_type``.
        portals :
            List of dicts, each with keys matching ``add_portal()``
            parameters: ``iri`` (required), ``source_iri`` (required),
            ``target_iri`` (required), and optionally
            ``construct_query``, ``portal_type``, ``extra_ttl``,
            ``label``.

        Returns:
        -------
        tuple[int, int]
            (holons_added, portals_added)

        Example:
        -------
        ::

            ds.bulk_load(
                holons=[
                    {"iri": "urn:holon:a", "label": "A",
                     "holon_type": "cga:DataHolon"},
                    {"iri": "urn:holon:b", "label": "B",
                     "member_of": "urn:holon:a"},
                ],
                portals=[
                    {"iri": "urn:portal:ab",
                     "source_iri": "urn:holon:a",
                     "target_iri": "urn:holon:b",
                     "construct_query": "CONSTRUCT ..."},
                ],
            )

        .. versionadded:: 0.5.0
        """
        holons = holons or []
        portals = portals or []

        # Suppress per-write metadata refresh during the batch.
        original_mode = self._metadata_updates
        self._metadata_updates = "off"

        try:
            for h in holons:
                self.add_holon(
                    h["iri"],
                    h["label"],
                    member_of=h.get("member_of"),
                    holon_type=h.get("holon_type"),
                )

            for p in portals:
                self.add_portal(
                    p["iri"],
                    p["source_iri"],
                    p["target_iri"],
                    p.get("construct_query"),
                    portal_type=p.get("portal_type", "cga:TransformPortal"),
                    extra_ttl=p.get("extra_ttl"),
                    label=p.get("label"),
                )
        finally:
            self._metadata_updates = original_mode

        # One consolidated refresh for the entire batch.
        if self._metadata_updates == "eager":
            self._metadata.refresh_graph(self.registry_iri)

        return len(holons), len(portals)

    # ══════════════════════════════════════════════════════════
    # Holon discovery (SPARQL-driven)
    # ══════════════════════════════════════════════════════════

    def iter_holons(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ):
        """Yield holons via SPARQL against the registry.

        Each holon is a fully-populated :class:`HolonInfo` with layer
        graph IRIs resolved. Use this instead of ``list_holons()`` when
        iterating over large holarchies to avoid materializing the full
        list in memory.

        Parameters
        ----------
        limit :
            Maximum number of holons to yield. None means no limit.
        offset :
            Number of holons to skip before yielding. None means 0.

        Yields:
        ------
        HolonInfo

        .. versionadded:: 0.5.0
        """
        q = Q.LIST_HOLONS
        if limit is not None:
            q += f"\nLIMIT {int(limit)}"
        if offset is not None:
            q += f"\nOFFSET {int(offset)}"
        rows = self.backend.query(q)
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
            yield info

    def list_holons(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[HolonInfo]:
        """Discover holons via SPARQL against the registry.

        Returns a materialized list. For lazy iteration over large
        holarchies, use :meth:`iter_holons` instead.

        Parameters
        ----------
        limit :
            Maximum number of holons to return. None means all.
        offset :
            Number of holons to skip. None means 0.
        """
        return list(self.iter_holons(limit=limit, offset=offset))

    def get_holon(self, holon_iri: str) -> HolonInfo | None:
        """Get info for a single holon, or None if not found.

        Uses a direct filtered SPARQL query (5 queries total).
        O(1) in holarchy size.

        .. versionchanged:: 0.6.0
            Rewritten from linear scan to direct query.
        """
        # Check existence + get label in one query
        rows = self.backend.query(f"""
            PREFIX cga:  <urn:holonic:ontology:>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?label WHERE {{
                GRAPH ?g {{
                    <{holon_iri}> a cga:Holon .
                    OPTIONAL {{ <{holon_iri}> rdfs:label ?label }}
                }}
            }} LIMIT 1
        """)
        if not rows:
            return None

        info = HolonInfo(iri=holon_iri, label=rows[0].get("label"))

        # Fetch layers (4 targeted queries)
        info.interior_graphs = [
            r["graph"]
            for r in self.backend.query(Q.GET_HOLON_INTERIORS.replace("?holon", f"<{holon_iri}>"))
        ]
        info.boundary_graphs = [
            r["graph"]
            for r in self.backend.query(Q.GET_HOLON_BOUNDARIES.replace("?holon", f"<{holon_iri}>"))
        ]
        info.projection_graphs = [
            r["graph"]
            for r in self.backend.query(Q.GET_HOLON_PROJECTIONS.replace("?holon", f"<{holon_iri}>"))
        ]
        info.context_graphs = [
            r["graph"]
            for r in self.backend.query(Q.GET_HOLON_CONTEXTS.replace("?holon", f"<{holon_iri}>"))
        ]
        return info

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
            ``@prefix`` declarations -- the method prepends the
            standard prefix block.
        label :
            Human-readable label. Defaults to "<source> -> <target>".
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
        _validate_iri(portal_iri, "portal_iri")
        _validate_iri(source_iri, "source_iri")
        _validate_iri(target_iri, "target_iri")
        if graph_iri:
            _validate_iri(graph_iri, "graph_iri")
        graph_iri = graph_iri or f"{source_iri}/boundary"
        # TODO to_pithy_id
        lbl = label or f"{source_iri} -> {target_iri}"

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
                rdfs:label "{_escape_ttl(lbl)}\""""
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
            the IRI was not found in any graph (idempotent -- not an
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

    def iter_portals_from(
        self,
        source_iri: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ):
        """Yield portals originating from a holon.

        Parameters
        ----------
        limit :
            Maximum number of portals to yield.
        offset :
            Number of portals to skip.

        Yields:
        ------
        PortalInfo

        .. versionadded:: 0.5.0
        """
        q = Q.FIND_PORTALS_FROM.replace("?source", f"<{source_iri}>")
        if limit is not None:
            q += f"\nLIMIT {int(limit)}"
        if offset is not None:
            q += f"\nOFFSET {int(offset)}"
        for r in self.backend.query(q):
            yield PortalInfo(
                iri=r["portal"],
                source_iri=source_iri,
                target_iri=r["target"],
                label=r.get("label"),
                construct_query=r.get("query"),
                portal_type=r.get("portalType"),
            )

    def find_portals_from(
        self,
        source_iri: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[PortalInfo]:
        """Discover portals originating from a holon.  Pure SPARQL.

        Returns a materialized list. For lazy iteration, use
        :meth:`iter_portals_from`.
        """
        return list(self.iter_portals_from(source_iri, limit=limit, offset=offset))

    def iter_portals_to(
        self,
        target_iri: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ):
        """Yield portals targeting a holon.

        Parameters
        ----------
        limit :
            Maximum number of portals to yield.
        offset :
            Number of portals to skip.

        Yields:
        ------
        PortalInfo

        .. versionadded:: 0.5.0
        """
        q = Q.FIND_PORTALS_TO.replace("?target", f"<{target_iri}>")
        if limit is not None:
            q += f"\nLIMIT {int(limit)}"
        if offset is not None:
            q += f"\nOFFSET {int(offset)}"
        for r in self.backend.query(q):
            yield PortalInfo(
                iri=r["portal"],
                source_iri=r["source"],
                target_iri=target_iri,
                label=r.get("label"),
                construct_query=r.get("query"),
                portal_type=r.get("portalType"),
            )

    def find_portals_to(
        self,
        target_iri: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[PortalInfo]:
        """Discover portals targeting a holon.  Pure SPARQL.

        Returns a materialized list. For lazy iteration, use
        :meth:`iter_portals_to`.
        """
        return list(self.iter_portals_to(target_iri, limit=limit, offset=offset))

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
            portal_type=r.get("portalType"),
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
                portal_type=r.get("portalType"),
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

        Raises :class:`SealedPortalError` if the portal is a
        ``cga:SealedPortal`` -- traversal is explicitly blocked regardless
        of whether the portal carries a CONSTRUCT query.

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
        from holonic.model import SealedPortalError

        # Check portal type -- SealedPortal blocks traversal
        type_rows = self.backend.query(f"""
            PREFIX cga: <urn:holonic:ontology:>
            SELECT ?type WHERE {{
                GRAPH ?g {{ <{portal_iri}> a ?type . FILTER(?type != cga:Portal) }}
            }} LIMIT 1
        """)
        if type_rows:
            ptype = str(type_rows[0].get("type", ""))
            if "SealedPortal" in ptype:
                raise SealedPortalError(portal_iri)

        log.debug("traverse_portal(%s)", portal_iri)
        # Fetch the CONSTRUCT query from the portal definition
        q = Q.GET_PORTAL_QUERY.replace("?portal", f"<{portal_iri}>")
        rows = self.backend.query(q)
        if not rows:
            raise ValueError(f"Portal {portal_iri} not found or has no CONSTRUCT query")

        construct_query = rows[0]["query"]

        # Source layer scoping: determine what the CONSTRUCT runs against.
        #
        # Priority:
        #   1. Explicit cga:sourceLayer on the portal -> honor it
        #   2. Source holon has projection graphs -> scope to projections
        #      (projections exist to be the governed view; raw interiors
        #      may contain PII or other data the portal should not see)
        #   3. No projections -> full dataset (backward compat)
        #
        # BREAKING in 0.6.0: portals that previously accessed raw
        # interiors will now be scoped to projections if the source
        # holon has any. See MIGRATION.md.

        # Get source holon IRI for projection lookup
        source_rows = self.backend.query(f"""
            PREFIX cga: <urn:holonic:ontology:>
            SELECT ?source WHERE {{
                GRAPH ?g {{ <{portal_iri}> cga:sourceHolon ?source }}
            }} LIMIT 1
        """)
        source_iri_for_scope = source_rows[0]["source"] if source_rows else None

        # Check explicit sourceLayer
        scope_rows = self.backend.query(f"""
            PREFIX cga: <urn:holonic:ontology:>
            SELECT ?layer WHERE {{
                GRAPH ?g {{ <{portal_iri}> cga:sourceLayer ?layer }}
            }} LIMIT 1
        """)
        explicit_layer = str(scope_rows[0]["layer"]) if scope_rows else None

        use_projection_scope = False
        if explicit_layer and "ProjectionRole" in explicit_layer:
            use_projection_scope = True
        elif explicit_layer and "InteriorRole" in explicit_layer:
            use_projection_scope = False
        elif source_iri_for_scope:
            # No explicit layer: check if source has projections
            proj_rows = self.backend.query(
                Q.GET_HOLON_PROJECTIONS.replace("?holon", f"<{source_iri_for_scope}>")
            )
            if proj_rows:
                use_projection_scope = True

        if use_projection_scope and source_iri_for_scope:
            proj_rows = self.backend.query(
                Q.GET_HOLON_PROJECTIONS.replace("?holon", f"<{source_iri_for_scope}>")
            )
            scoped = Graph()
            for pr in proj_rows:
                scoped += self.backend.get_graph(pr["graph"])
            projected = _run_construct_on_graph(scoped, construct_query)
        else:
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
        fail_on_breach: bool = False,
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
        fail_on_breach :
            If True and validation returns COMPROMISED, roll back the
            injected triples and raise :class:`MembraneBreachError`.
            Implies ``validate=True``.
        agent_iri :
            If provided, record PROV-O provenance.

        Returns:
        -------
        (projected_graph, membrane_result_or_none)
        """
        if fail_on_breach:
            validate = True

        portal = self.find_portal(source_iri, target_iri)
        if portal is None:
            raise ValueError(f"No direct portal from {source_iri} to {target_iri}")
        log.debug("traverse(%s -> %s) via %s", source_iri, target_iri, portal.iri)

        # Resolve target interior: use existing registered interior if
        # available, otherwise fall back to convention name and register it.
        target_interior = None
        if inject:
            interior_rows = self.backend.query(
                Q.GET_HOLON_INTERIORS.replace("?holon", f"<{target_iri}>")
            )
            if interior_rows:
                target_interior = interior_rows[0]["graph"]
            else:
                target_interior = f"{target_iri}/interior"

        # Run the CONSTRUCT without injecting first (for hash comparison)
        projected = self.traverse_portal(portal.iri, inject_into=None)

        # Hash-compare: skip injection if projected data unchanged
        # Only tracked when agent_iri is provided (hash is a provenance concern)
        import hashlib

        proj_hash = (
            hashlib.sha256(projected.serialize(format="nt").encode()).hexdigest()
            if projected
            else ""
        )

        is_noop = False
        # Snapshot the target interior before injection for atomic rollback.
        # get_graph() returns a copy (C2 fix), so this is safe to hold.
        _pre_injection_snapshot = None
        if inject and target_interior and fail_on_breach:
            if self.backend.graph_exists(target_interior):
                _pre_injection_snapshot = self.backend.get_graph(target_interior)
            else:
                _pre_injection_snapshot = Graph()

        if inject and target_interior and proj_hash and agent_iri:
            # Check for stored hash
            context_graph = f"{target_iri}/context"
            existing_hash_rows = self.backend.query(f"""
                PREFIX cga: <urn:holonic:ontology:>
                SELECT ?hash WHERE {{
                    GRAPH <{context_graph}> {{
                        <{target_iri}> cga:lastProjectionHash ?hash .
                    }}
                }}
            """)
            old_hash = existing_hash_rows[0]["hash"] if existing_hash_rows else None
            if old_hash == proj_hash:
                is_noop = True
            else:
                # Inject and store new hash
                self.backend.post_graph(target_interior, projected)
                self._maybe_refresh(target_interior)
                # Delete old hash if present
                if existing_hash_rows:
                    self.backend.update(f"""
                        PREFIX cga: <urn:holonic:ontology:>
                        DELETE WHERE {{
                            GRAPH <{context_graph}> {{
                                <{target_iri}> cga:lastProjectionHash ?old .
                            }}
                        }}
                    """)
                # Store new hash
                self.backend.parse_into(
                    context_graph,
                    f"""
                    @prefix cga: <urn:holonic:ontology:> .
                    <{target_iri}> cga:lastProjectionHash "{proj_hash}" .
                """,
                    "turtle",
                )
                self._register_layer(target_iri, context_graph, "hasContext")
        elif inject and target_interior and projected:
            # No hash to compare (empty projection) -- just inject
            self.backend.post_graph(target_interior, projected)
            self._maybe_refresh(target_interior)

        # Ensure the target interior graph is registered as cga:hasInterior
        if target_interior:
            self._register_layer(target_iri, target_interior, "hasInterior")

        membrane_result = None
        if validate:
            membrane_result = self.validate_membrane(target_iri)

            # Fail-closed: restore pre-injection snapshot on breach
            if fail_on_breach and membrane_result.health == MembraneHealth.COMPROMISED:
                if target_interior and _pre_injection_snapshot is not None:
                    self.backend.put_graph(target_interior, _pre_injection_snapshot)
                raise MembraneBreachError(membrane_result)

        if agent_iri:
            if is_noop:
                # Record a no-op traversal with explicit label
                activity_iri = f"urn:prov:traversal:{uuid.uuid4().hex[:12]}"
                context_graph = f"{target_iri}/context"
                ts = datetime.now(UTC).isoformat()
                noop_label = f"no-op: source unchanged (portal {portal.iri})"
                update = Q.RECORD_TRAVERSAL.format(
                    context_graph=context_graph,
                    activity_iri=activity_iri,
                    label=noop_label,
                    agent_iri=agent_iri,
                    source_iri=source_iri,
                    target_iri=target_iri,
                    timestamp=ts,
                )
                self.backend.update(update)
                self._register_layer(target_iri, context_graph, "hasContext")
            else:
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

        # Fire notification hooks
        for hook in self._on_traversal:
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
        path = self.find_path(source_iri, target_iri)
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

        portal = self.find_portal(source_iri, target_iri)
        if portal is None:
            raise ValueError(f"No direct portal from {source_iri} to {target_iri}")

        # Run the CONSTRUCT without injecting
        projected = self.traverse_portal(portal.iri, inject_into=None)

        # Build what-if data graph: existing interiors + projected
        data_graph = Graph()
        interior_rows = self.backend.query(
            Q.GET_HOLON_INTERIORS.replace("?holon", f"<{target_iri}>")
        )
        for r in interior_rows:
            data_graph += self.backend.get_graph(r["graph"])
        data_graph += projected

        # Build shapes graph from boundaries
        shapes_graph = Graph()
        boundary_rows = self.backend.query(
            Q.GET_HOLON_BOUNDARIES.replace("?holon", f"<{target_iri}>")
        )
        for r in boundary_rows:
            shapes_graph += self.backend.get_graph(r["graph"])

        # Validate the merged state
        if len(shapes_graph) == 0:
            return projected, MembraneResult(
                holon_iri=target_iri,
                conforms=True,
                health=MembraneHealth.INTACT,
                report_text="No shapes to validate against.",
            )

        conforms, report_graph, report_text = pyshacl.validate(
            data_graph,
            shacl_graph=shapes_graph,
            allow_infos=True,
        )

        violations, warnings_list, shape_viols = _parse_shacl_report(
            report_graph,
        )

        if violations:
            health = MembraneHealth.COMPROMISED
        elif warnings_list:
            health = MembraneHealth.WEAKENED
        else:
            health = MembraneHealth.INTACT

        return projected, MembraneResult(
            holon_iri=target_iri,
            conforms=conforms,
            health=health,
            report_text=report_text,
            violations=violations,
            warnings=warnings_list,
            shape_violations=shape_viols,
        )

    # ══════════════════════════════════════════════════════════
    # Membrane validation
    # ══════════════════════════════════════════════════════════

    def validate_membrane(self, holon_iri: str) -> MembraneResult:
        """Validate a holon's interior(s) against its boundary shape(s).

        Collects all cga:hasInterior graphs as data and all cga:hasBoundary
        graphs as shapes, then runs pyshacl.
        """
        import pyshacl

        log.debug("validate_membrane(%s)", holon_iri)

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
        for hook in self._on_validation:
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
        for holon in self.iter_holons():
            results[holon.iri] = self.validate_membrane(holon.iri)
        return results

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

        .. versionchanged:: 0.7.0
            Added ``limit``, ``offset``, ``since``, ``kind``.
        """
        traversals = []
        validations = []

        if kind in (None, "traversal"):
            tq = Q.COLLECT_TRAVERSALS
            # Strip existing ORDER BY clause for re-ordering
            if "ORDER BY" in tq:
                tq = tq[: tq.index("ORDER BY")].rstrip()
            if since:
                # Insert FILTER before closing }
                tq = tq.rstrip().rstrip("}")
                tq += (
                    f"  FILTER(?timestamp > "
                    f'"{since}"^^<http://www.w3.org/2001/'
                    f"XMLSchema#dateTime>)\n}}\n"
                )
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
                for r in self.backend.query(tq)
            ]

        if kind in (None, "validation"):
            vq = Q.COLLECT_VALIDATIONS
            # Strip existing ORDER BY clause
            if "ORDER BY" in vq:
                vq = vq[: vq.index("ORDER BY")].rstrip()
            if since:
                vq = vq.rstrip().rstrip("}")
                vq += (
                    f"  FILTER(?timestamp > "
                    f'"{since}"^^<http://www.w3.org/2001/'
                    f"XMLSchema#dateTime>)\n}}\n"
                )
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
                for r in self.backend.query(vq)
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
    #
    # Three projection methods serve different purposes:
    #
    #   project_holon(holon_iri)
    #       Ad-hoc LPG projection of a single holon's interiors.
    #       Merges interior graphs, runs structural collapse
    #       (types, literals, blank nodes), returns a ProjectedGraph.
    #       No pipeline, no provenance, no PROV-O activity recorded.
    #       Use for interactive exploration and visualization.
    #
    #   project_holarchy()
    #       Topology projection of the entire holarchy. Nodes are
    #       holons; edges are cga:memberOf and portal connections.
    #       Returns a ProjectedGraph for NetworkX/graphology export.
    #
    #   run_projection(holon_iri, spec_iri)
    #       Execute a registered ProjectionPipelineSpec against a
    #       holon.  Runs each step in declared order (Python
    #       transforms + inline CONSTRUCT). Records a full PROV-O
    #       activity in the context graph with transform versions,
    #       host metadata, and timing. Use for governed, auditable
    #       projection workflows.
    #
    # Despite the similar names, project_holon and run_projection
    # are not aliases.  project_holon is a quick structural tool;
    # run_projection is a governed pipeline executor with provenance.
    # ══════════════════════════════════════════════════════════

    def project_holon(
        self,
        holon_iri: str,
        *,
        store_as: str | None = None,
        **lpg_kwargs,
    ):
        """Project a holon's interior(s) into an LPG-style structure.

        Ad-hoc structural projection: merges all interior graphs, runs
        ``project_to_lpg()`` for type/literal/blank-node collapse, and
        returns a :class:`ProjectedGraph`. No pipeline spec is needed
        and no PROV-O activity is recorded.

        For governed, auditable projections with provenance, use
        :meth:`run_projection` with a registered
        :class:`ProjectionPipelineSpec` instead.

        Parameters
        ----------
        holon_iri :
            The holon to project.
        store_as :
            If provided, serialize the LPG back to triples and store
            in this named graph (registered as a projection layer).
        **lpg_kwargs :
            Forwarded to project_to_lpg() -- collapse_types, resolve_blanks, etc.

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
    # Export / serialization
    # ══════════════════════════════════════════════════════════

    def compose(
        self,
        holon_iris: list[str],
        *,
        layers: list[str] | None = None,
    ) -> Graph:
        """Union interior graphs across multiple holons into one view.

        Returns a merged :class:`rdflib.Graph` containing all triples
        from the requested layers of the specified holons. Does not
        persist the result; callers can serialize or query it directly.

        Parameters
        ----------
        holon_iris :
            List of holon IRIs to compose.
        layers :
            Which layer types to include. Defaults to ``["interior"]``.
            Valid values: ``"interior"``, ``"projection"``, ``"boundary"``,
            ``"context"``.

        Returns:
        -------
        rdflib.Graph
            Merged graph.

        .. versionadded:: 0.6.0
        """
        if layers is None:
            layers = ["interior"]

        layer_query_map = {
            "interior": Q.GET_HOLON_INTERIORS,
            "boundary": Q.GET_HOLON_BOUNDARIES,
            "projection": Q.GET_HOLON_PROJECTIONS,
            "context": Q.GET_HOLON_CONTEXTS,
        }

        merged = Graph()
        for holon_iri in holon_iris:
            for layer_name in layers:
                query = layer_query_map.get(layer_name)
                if query is None:
                    continue
                rows = self.backend.query(query.replace("?holon", f"<{holon_iri}>"))
                for r in rows:
                    g = self.backend.get_graph(r["graph"])
                    merged += g

        return merged

    def holarchy_summary(
        self,
        *,
        max_age: timedelta | None = None,
        recent_limit: int = 10,
    ):
        """Return an aggregated health snapshot of the holarchy.

        Collects holon/portal counts, root count, membrane health
        distribution, staleness count, and recent activities in a
        single call. Designed for dashboards that need a consolidated
        overview without making 4+ separate SPARQL round-trips.

        Parameters
        ----------
        max_age :
            Staleness threshold. Defaults to 1 hour.
        recent_limit :
            Number of recent activities to include.

        Returns:
        -------
        HolarchySummary

        .. versionadded:: 0.7.0
        """
        from holonic.console_model import HolarchySummary

        holons = self.list_holons()
        portals = self.backend.query(Q.ALL_PORTALS)
        roots = [
            h
            for h in holons
            if not self.backend.query(
                f"PREFIX cga: <urn:holonic:ontology:> "
                f"SELECT ?p WHERE {{ GRAPH ?g {{ "
                f"<{h.iri}> cga:memberOf ?p }} }} LIMIT 1"
            )
        ]

        # Health distribution
        health_dist: dict[str, int] = {
            "intact": 0,
            "weakened": 0,
            "compromised": 0,
        }
        for h in holons:
            result = self.validate_membrane(h.iri)
            health_dist[result.health.value] += 1

        # Staleness
        stale = self.stale_holons(max_age=max_age)

        # Recent activities
        trail = self.collect_audit_trail(limit=recent_limit)

        return HolarchySummary(
            holon_count=len(holons),
            portal_count=len(portals),
            root_count=len(roots),
            health_distribution=health_dist,
            stale_count=len(stale),
            recent_activities=(trail.traversals[:recent_limit]),
        )

    def export_graph(
        self,
        graph_iri: str,
        format: str = "turtle",
    ) -> str:
        """Serialize a single named graph to a string.

        Parameters
        ----------
        graph_iri :
            IRI of the named graph to export.
        format :
            RDF serialization format. Common values: ``"turtle"``,
            ``"xml"``, ``"json-ld"``, ``"nt"`` (N-Triples).
            Passed directly to rdflib's ``Graph.serialize()``.

        Returns:
        -------
        str
            The serialized graph content.

        Raises:
        ------
        ValueError
            If the graph does not exist.

        .. versionadded:: 0.5.0
        """
        if not self.backend.graph_exists(graph_iri):
            raise ValueError(f"Graph {graph_iri!r} does not exist")
        g = self.backend.get_graph(graph_iri)
        return g.serialize(format=format)

    def export(self, format: str = "trig") -> str:
        """Serialize the entire dataset (all named graphs) to a string.

        Parameters
        ----------
        format :
            RDF serialization format that supports named graphs.
            Common values: ``"trig"`` (default), ``"nquads"``.
            Single-graph formats like ``"turtle"`` will lose graph
            boundaries.

        Returns:
        -------
        str
            The serialized dataset content.

        Example:
        -------
        ::

            # Save to file
            with open("holarchy.trig", "w") as f:
                f.write(ds.export())

            # Or export as N-Quads
            nquads = ds.export(format="nquads")

        .. versionadded:: 0.5.0
        """
        from rdflib import Dataset as RdflibDataset

        ds = RdflibDataset()
        for graph_iri in self.backend.list_named_graphs():
            g = self.backend.get_graph(graph_iri)
            ctx = ds.graph(URIRef(graph_iri))
            for s, p, o in g:
                ctx.add((s, p, o))
        return ds.serialize(format=format)

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
            src = r["source"].rsplit("/", 1)[-1].rsplit(":", 1)[-1]
            tgt = r["target"].rsplit("/", 1)[-1].rsplit(":", 1)[-1]
            lbl = r.get("label")
            if lbl:
                lines.append(f"    {lbl} ({src} -> {tgt})")
            else:
                lines.append(f"    {src} -> {tgt}")

        return "\n".join(lines)

    def compute_depth(self, holon_iri: str | None = None):
        """Compute nesting depth from the cga:memberOf chain.

        Depth is not stored -- it is derived from structure.  A root
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
            Dict-like object (``tree[iri]`` -> depth) that also carries
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
    # are additive -- the existing list_holons/get_holon return the
    # richer HolonInfo type and remain unchanged.
    # ══════════════════════════════════════════════════════════

    def list_holons_summary(self) -> list[HolonSummary]:
        """Return lightweight holon summaries for browser/list views.

        Single SPARQL query -- no per-holon layer fan-out. Use
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
        # Layer graphs -- same per-predicate queries used by list_holons
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
        # dict -- callers should not assume full coverage.
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
                portal_type=r.get("portalType"),
            )
            for r in rows
        ]

    def get_portal(self, portal_iri: str) -> PortalDetail | None:
        """Return the full portal descriptor including the CONSTRUCT body.

        Returns None if no portal with that IRI is registered.
        """
        rows = self.backend.query(f"""
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
        portal = self.get_portal(portal_iri)
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
        rows = self.backend.query(f"""
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
        rows = self.backend.query(f"""
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
        rows = self.backend.query(q)
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

    def freshness(self, holon_iri: str) -> timedelta | None:
        """Return time since the most recent traversal into this holon.

        Returns None if no traversal has been recorded.

        .. versionadded:: 0.6.0
        """
        record = self.last_traversal(holon_iri)
        if record is None or record.timestamp is None:
            return None
        from datetime import datetime as dt

        try:
            last_time = dt.fromisoformat(str(record.timestamp))
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=UTC)
            return datetime.now(UTC) - last_time
        except (ValueError, TypeError):
            return None

    def is_stale(
        self,
        holon_iri: str,
        max_age: timedelta | None = None,
    ) -> bool:
        """Check whether a holon's data is stale.

        Parameters
        ----------
        holon_iri :
            The holon to check.
        max_age :
            Maximum acceptable age. Defaults to 1 hour.

        Returns True if the holon has never been traversed or if
        ``freshness()`` exceeds ``max_age``.

        .. versionadded:: 0.6.0
        """
        if max_age is None:
            max_age = timedelta(hours=1)
        age = self.freshness(holon_iri)
        if age is None:
            return True
        return age > max_age

    def stale_holons(
        self,
        max_age: timedelta | None = None,
    ) -> list[HolonInfo]:
        """Return all holons whose data is stale.

        Parameters
        ----------
        max_age :
            Maximum acceptable age. Defaults to 1 hour.

        .. versionadded:: 0.6.0
        """
        return [h for h in self.iter_holons() if self.is_stale(h.iri, max_age=max_age)]

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
            rows = self.backend.query(q)
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
        rows = self.backend.query(q)
        if not rows:
            raise ValueError(f"Activity {activity_iri} not found")

        source_iri = rows[0]["source"]
        target_iri = rows[0]["target"]

        # Find the portal and re-run its CONSTRUCT to get the projected triples
        portal = self.find_portal(source_iri, target_iri)
        if portal is None:
            raise ValueError(
                f"Cannot find portal from {source_iri} to {target_iri} for activity {activity_iri}"
            )

        projected = self.traverse_portal(portal.iri, inject_into=None)

        # Remove the projected triples from the target interior
        interior_rows = self.backend.query(
            Q.GET_HOLON_INTERIORS.replace("?holon", f"<{target_iri}>")
        )
        removed = 0
        for ir in interior_rows:
            g_iri = ir["graph"]
            target_g = self.backend.get_graph(g_iri)
            before = len(target_g)
            for s, p, o in projected:
                target_g.remove((s, p, o))
            after = len(target_g)
            if after < before:
                self.backend.put_graph(g_iri, target_g)
                removed += before - after

        return removed

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
            # Empty pipeline -- no steps, close the spec
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
        count -- use ``get_pipeline(iri)`` for full step content.
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
        from rdflib import RDF

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

        Governed projection: merges the holon's interior graphs, runs
        each step of the referenced :class:`ProjectionPipelineSpec` in
        declared order (Python transform first, then inline CONSTRUCT
        if present), and optionally stores the result as a named graph
        registered as a projection layer. Records a full ``prov:Activity``
        in the holon's context graph with transform versions, host
        metadata, and timing.

        This is distinct from :meth:`project_holon`, which is an ad-hoc
        structural projection with no pipeline spec and no provenance.
        Use ``project_holon`` for quick interactive exploration; use
        ``run_projection`` for governed, auditable workflows.

        Parameters
        ----------
        holon_iri :
            The holon whose interiors are projected.
        spec_iri :
            IRI of a registered ``ProjectionPipelineSpec``.
        store_as :
            Named graph IRI to store the projection result in.
        agent_iri :
            Agent to associate with the provenance activity.

        Provenance recorded
        -------------------
        - ``prov:used <spec_iri>``
        - ``prov:generated <output_graph_iri>`` (if ``store_as``)
        - ``prov:startedAtTime`` / ``prov:endedAtTime``
        - ``prov:wasAssociatedWith <agent_iri>`` (if provided)
        - ``cga:transformVersion`` for each transform used
        - ``cga:runHost``, ``cga:runPlatform``, ``cga:runPythonVersion``,
          ``cga:runHolonicVersion``

        Raises:
        ------
        ValueError
            If ``spec_iri`` is not registered.
        TransformNotFoundError
            If a step references an unknown transform.
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

    def __repr__(self) -> str:
        backend_name = type(self.backend).__name__
        try:
            rows = self.backend.query(
                "SELECT (COUNT(DISTINCT ?h) AS ?n) WHERE "
                "{ GRAPH ?g { ?h a <urn:holonic:ontology:Holon> } }"
            )
            n_holons = int(rows[0]["n"]) if rows else 0
        except Exception:
            n_holons = "?"
        return (
            f"HolonicDataset(backend={backend_name}, "
            f"holons={n_holons}, "
            f"registry='{self.registry_iri}')"
        )
