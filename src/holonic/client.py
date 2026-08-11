"""Graph-native holonic dataset client.

HolonicDataset is a thin Python wrapper around a HolonicStore.
All state lives in the store as named graphs.  All discovery,
traversal, and validation use SPARQL against the store.
Python methods are convenience, not architecture.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import deque
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from functools import lru_cache
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
    NeighborhoodGraph,
    PortalDetail,
    PortalSummary,
    ProjectionPipelineSpec,
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


def _bind_iri(iri: str, param_name: str = "iri") -> URIRef:
    """Validate *iri* and return it as an ``rdflib.URIRef`` binding value.

    The backends' ``**bindings`` contract binds any ``rdflib`` term
    verbatim and wraps every other value as a literal, so an IRI must
    arrive as a ``URIRef`` -- a bare string would bind as a string literal
    and match nothing. Passing the term routes the value through
    ``initBindings`` (rdflib) / ``n3()`` substitution (Fuseki) instead of
    string-splicing ``?var`` -> ``<iri>`` into the template; that is the
    parameterized path the prepared-query cache (P1) and the
    injection-safe contract depend on.

    Validation is retained as defense-in-depth: it rejects empty or
    structurally unsafe IRIs -- including second-order, store-derived ones
    on the read path -- with a clear ``ValueError`` before they reach the
    store (closes S3).
    """
    _validate_iri(iri, param_name)
    return URIRef(iri)


def _escape_ttl(s: str) -> str:
    r"""Escape a string for use inside a Turtle ``"..."`` literal.

    Backslash is escaped first so the subsequent replacements are not
    themselves doubled. A bare carriage return or tab inside a quoted
    literal is both a Turtle parse error and an injection vector, so
    ``\r`` and ``\t`` are escaped alongside ``\n`` -- escaping only
    newline (the previous behaviour) left CR/TAB as a way to smuggle
    structure into a serialized literal.
    """
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _escape_construct(s: str) -> str:
    """Escape a string for use inside a Turtle triple-quoted literal.

    Backslash must be escaped FIRST -- otherwise the triple-quote escape
    below is silently corrupted, and a lone trailing backslash in the
    body could escape the closing long-string delimiter and let the
    remainder of the string break out of the literal. After that, any
    run of three double-quotes that would close the long-string literal
    early is neutralised.
    """
    return s.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


# A prefixed name (PNAME): a prefix label, a single colon, and a local name,
# each restricted to word characters plus '.'/'-'. This shape CANNOT contain
# the whitespace, angle brackets, quotes, or statement terminators an
# injection needs, so a matching value is safe to emit verbatim into an
# ``rdf:type`` slot where the document's ``@prefix`` declarations resolve it.
_PNAME_RE = re.compile(r"^[A-Za-z_][\w.-]*:[A-Za-z_][\w.-]*$")


def _type_term(type_str: str, param_name: str = "holon_type") -> str:
    """Return a safe Turtle term for an ``rdf:type`` object.

    Accepts either a prefixed name (``prefix:Local`` -- emitted verbatim so
    the document's ``@prefix`` declarations resolve it) or a full IRI
    (validated with :func:`_validate_iri` and wrapped in ``<...>``). Any
    other value raises ``ValueError``.

    This closes the injection vector where a ``':'``-containing ``type_str``
    was previously spliced raw into the Turtle body: a payload such as
    ``cga:Holon . <urn:evil> a cga:Holon`` no longer matches the strict
    PNAME shape, and a would-be full IRI carrying angle brackets or quotes
    is rejected by :func:`_validate_iri` before it can reach the serializer.
    """
    if _PNAME_RE.match(type_str):
        return type_str
    _validate_iri(type_str, param_name)
    return f"<{type_str}>"


def _run_construct_on_graph(graph: Graph, construct_query: str) -> Graph:
    """Run a SPARQL CONSTRUCT against an in-memory Graph.

    Used by run_projection when a step carries an inline CONSTRUCT.
    Isolated from the dataset backend so intermediate results stay
    ephemeral and don't pollute named-graph state.

    Raises :class:`ValueError` if ``construct_query`` is not a CONSTRUCT or
    DESCRIBE query (rdflib returns ``None`` for ``.graph`` on a SELECT/ASK,
    which would otherwise surface downstream as an opaque ``TypeError``).
    """
    result = graph.query(construct_query)
    if result.graph is None:
        raise ValueError(
            "expected a CONSTRUCT or DESCRIBE query (result has no graph); "
            "portal / pipeline steps must carry a CONSTRUCT query"
        )
    return result.graph


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


@lru_cache(maxsize=1)
def _ontology_graphs() -> tuple[tuple[str, Graph], ...]:
    """Parse the bundled CGA ontology + shapes once, process-wide.

    The Turtle sources never change at runtime, so parsing them on every
    :class:`HolonicDataset` construction re-does identical work (audit P6).
    This caches the parsed :class:`rdflib.Graph` objects keyed by their
    target graph IRI; callers only copy triples into their backend. The
    returned graphs are treated as read-only and must not be mutated.
    """
    ontology_dir = Path(__file__).parent / "ontology"
    sources = (
        ("urn:holonic:ontology:cga", ontology_dir / "cga.ttl"),
        ("urn:holonic:ontology:cga-shapes", ontology_dir / "cga-shapes.ttl"),
    )
    graphs: list[tuple[str, Graph]] = []
    for graph_iri, path in sources:
        if not path.exists():
            continue
        g = Graph()
        g.parse(source=str(path), format="turtle")
        graphs.append((graph_iri, g))
    return tuple(graphs)


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
        """Load the CGA ontology and shapes into the dataset.

        The Turtle sources are parsed once per process (see
        :func:`_ontology_graphs`) and their triples copied into the
        backend. For a persistent backend (e.g. Fuseki) that already holds
        the ontology graph, the upload is skipped -- ``graph_exists``
        guards against re-sending identical data on every reconnect (P6).
        """
        for graph_iri, graph in _ontology_graphs():
            if self.backend.graph_exists(graph_iri):
                continue
            self.backend.put_graph(graph_iri, graph)

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

        # Pipeline manager (0.8.0, AR1/CQ1 decomposition). Owns the
        # projection-pipeline registry + execution; delegated to by the
        # public register_pipeline/run_projection/... facade methods.
        from holonic._pipelines import PipelineManager

        self._pipelines = PipelineManager(self)

        # Console-read projections (0.8.0, AR1/CQ1 decomposition). Owns
        # the presentation-shaped read queries (summaries, detail,
        # neighborhood, portal browsing) that back operator tooling.
        from holonic._console import ConsoleReads

        self._console = ConsoleReads(self)

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
            ttl += f"    <{iri}> a {_type_term(holon_type, 'holon_type')} .\n"

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
            ttl = (
                "@prefix cga: <urn:holonic:ontology:> .\n"
                f"<{portal_iri}> a {_type_term(portal_type, 'portal_type')} .\n"
            )
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

        # P3: resolve every holon's layer graphs in ONE query (grouped in
        # Python) instead of four queries per holon. Turns the historical
        # 1+4N fan-out into 2 queries regardless of holarchy size.
        page_iris = {row["holon"] for row in rows}
        layers = self._layers_by_holon(page_iris)

        for row in rows:
            iri = row["holon"]
            info = HolonInfo(iri=iri, label=row.get("label"))
            holon_layers = layers.get(iri, {})
            info.interior_graphs = holon_layers.get("hasInterior", [])
            info.boundary_graphs = holon_layers.get("hasBoundary", [])
            info.projection_graphs = holon_layers.get("hasProjection", [])
            info.context_graphs = holon_layers.get("hasContext", [])
            yield info

    _LAYER_PRED_SUFFIXES = (
        "hasInterior",
        "hasBoundary",
        "hasProjection",
        "hasContext",
    )

    def _layers_by_holon(
        self, holon_iris: set[str] | None = None
    ) -> dict[str, dict[str, list[str]]]:
        """Return ``{holon_iri: {predicate_suffix: [graph_iri, ...]}}``.

        Single scan of the registry for all four ``cga:has*`` layer
        predicates (P3). When ``holon_iris`` is given, rows for other holons
        are dropped so a paged ``iter_holons`` doesn't materialize the whole
        holarchy's layers.
        """
        cga = "urn:holonic:ontology:"
        out: dict[str, dict[str, list[str]]] = {}
        for row in self.backend.query(Q.LIST_HOLON_LAYERS):
            holon = row["holon"]
            if holon_iris is not None and holon not in holon_iris:
                continue
            pred = row["pred"]
            suffix = pred[len(cga):] if pred.startswith(cga) else pred
            if suffix not in self._LAYER_PRED_SUFFIXES:
                continue
            out.setdefault(holon, {}).setdefault(suffix, []).append(row["graph"])
        return out

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
            for r in self.backend.query(Q.GET_HOLON_INTERIORS, holon=_bind_iri(holon_iri))
        ]
        info.boundary_graphs = [
            r["graph"]
            for r in self.backend.query(Q.GET_HOLON_BOUNDARIES, holon=_bind_iri(holon_iri))
        ]
        info.projection_graphs = [
            r["graph"]
            for r in self.backend.query(Q.GET_HOLON_PROJECTIONS, holon=_bind_iri(holon_iri))
        ]
        info.context_graphs = [
            r["graph"]
            for r in self.backend.query(Q.GET_HOLON_CONTEXTS, holon=_bind_iri(holon_iri))
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
            <{portal_iri}> a {_type_term(portal_type, 'portal_type')} ;
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
        q = Q.FIND_PORTALS_FROM
        if limit is not None:
            q += f"\nLIMIT {int(limit)}"
        if offset is not None:
            q += f"\nOFFSET {int(offset)}"
        for r in self.backend.query(q, source=_bind_iri(source_iri, "source_iri")):
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
        q = Q.FIND_PORTALS_TO
        if limit is not None:
            q += f"\nLIMIT {int(limit)}"
        if offset is not None:
            q += f"\nOFFSET {int(offset)}"
        for r in self.backend.query(q, target=_bind_iri(target_iri, "target_iri")):
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
        rows = self.backend.query(
            Q.FIND_PORTAL_DIRECT,
            source=_bind_iri(source_iri, "source_iri"),
            target=_bind_iri(target_iri, "target_iri"),
        )
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
        is_sealed = self.backend.ask(f"""
            PREFIX cga: <urn:holonic:ontology:>
            ASK {{ GRAPH ?g {{ <{portal_iri}> a cga:SealedPortal }} }}
        """)
        if is_sealed:
            raise SealedPortalError(portal_iri)

        log.debug("traverse_portal(%s)", portal_iri)
        # Fetch the CONSTRUCT query from the portal definition
        rows = self.backend.query(Q.GET_PORTAL_QUERY, portal=_bind_iri(portal_iri, "portal_iri"))
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

        def _graphs_for(holon: str, template: str) -> list[str]:
            return [
                r["graph"]
                for r in self.backend.query(template, holon=_bind_iri(holon))
            ]

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
            projected = self.backend.construct(construct_query)
        elif scope_graphs:
            scoped = Graph()
            for g in scope_graphs:
                scoped += self.backend.get_graph(g)
            projected = _run_construct_on_graph(scoped, construct_query)
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
            Implies ``validate=True``.
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

        portal = self.find_portal(source_iri, target_iri)
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
            self._register_layer(target_iri, target_interior, "hasInterior")

        membrane_result = None
        if validate:
            membrane_result = self.validate_membrane(target_iri)

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
        for hook in self._on_traversal:
            hook(source_iri, target_iri, projected, membrane_result)

        return projected, membrane_result

    # ── traverse() helpers (CQ2 decomposition) ───────────────────

    def _resolve_target_interior(self, target_iri: str) -> str:
        """Return the target's registered interior graph, or the convention name.

        Uses the first ``cga:hasInterior`` graph if one is registered,
        otherwise falls back to ``<target>/interior`` (registered by the
        caller once injection succeeds).
        """
        interior_rows = self.backend.query(
            Q.GET_HOLON_INTERIORS, holon=_bind_iri(target_iri)
        )
        if interior_rows:
            return interior_rows[0]["graph"]
        return f"{target_iri}/interior"

    @staticmethod
    def _projection_hash(projected: Graph | None) -> str:
        """Stable content hash of a projected graph (empty string if falsy)."""
        import hashlib

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
                self.backend.get_graph(interior_iri)
                if self.backend.graph_exists(interior_iri)
                else Graph()
            )
            delta = projected - pre
        self.backend.post_graph(interior_iri, projected)
        self._maybe_refresh(interior_iri)
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

        ground = Graph()
        for triple in delta:
            if any(isinstance(term, BNode) for term in triple):
                continue
            ground.add(triple)
        if len(ground) == 0:
            return
        nt = ground.serialize(format="nt")
        graph_ref = _bind_iri(interior_iri, "interior_iri").n3()
        self.backend.update(f"DELETE DATA {{ GRAPH {graph_ref} {{\n{nt}\n}} }}")

    def _stored_projection_hash(self, target_iri: str) -> str | None:
        """Read the persisted ``cga:lastProjectionHash`` for *target_iri*."""
        rows = self.backend.query(
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
        context_graph = f"{target_iri}/context"
        _validate_iri(context_graph, "context_graph")
        _validate_iri(target_iri, "target_iri")
        self.backend.update(
            Q.SET_PROJECTION_HASH.format(
                context_graph=context_graph,
                target_iri=target_iri,
                proj_hash=proj_hash,
            )
        )
        self._register_layer(target_iri, context_graph, "hasContext")

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
            Q.GET_HOLON_INTERIORS, holon=_bind_iri(target_iri)
        )
        for r in interior_rows:
            data_graph += self.backend.get_graph(r["graph"])
        data_graph += projected

        # Build shapes graph from boundaries
        shapes_graph = Graph()
        boundary_rows = self.backend.query(
            Q.GET_HOLON_BOUNDARIES, holon=_bind_iri(target_iri)
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
            Q.GET_HOLON_INTERIORS, holon=_bind_iri(holon_iri)
        )
        data_graph = Graph()
        for row in interior_rows:
            g = self.backend.get_graph(row["graph"])
            for triple in g:
                data_graph.add(triple)

        # Collect boundary graphs (union)
        boundary_rows = self.backend.query(
            Q.GET_HOLON_BOUNDARIES, holon=_bind_iri(holon_iri)
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
        self.backend.update(update)
        self._register_layer(holon_iri, context_graph, "hasContext")
        return activity_iri

    def _build_surface_report(self, holon_iri: str) -> SurfaceReport | None:
        """Build a surface report from a holon's boundary shapes."""
        boundary_rows = self.backend.query(
            Q.GET_HOLON_BOUNDARIES, holon=_bind_iri(holon_iri)
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
            Q.GET_HOLON_INTERIORS, holon=_bind_iri(holon_iri)
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
                Q.GET_HOLON_INTERIORS, holon=_bind_iri(align_iri)
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
            Q.GET_HOLON_INTERIORS, holon=_bind_iri(holon_iri)
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
            Q.GET_HOLON_INTERIORS, holon=_bind_iri(holon_iri)
        )
        graphs = [self.backend.get_graph(r["graph"]) for r in interior_rows]
        merged = sum(graphs, Graph()) if graphs else Graph()

        result = pipeline.apply(merged)

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
                rows = self.backend.query(query, holon=_bind_iri(holon_iri))
                for r in rows:
                    g = self.backend.get_graph(r["graph"])
                    merged += g

        return merged

    def holarchy_summary(
        self,
        *,
        max_age: timedelta | None = None,
        recent_limit: int = 10,
        live_health: bool = False,
    ):
        """Return an aggregated health snapshot of the holarchy.

        Collects holon/portal counts, root count, membrane health
        distribution, staleness count, and recent activities for
        dashboards that need a consolidated overview.

        Parameters
        ----------
        max_age :
            Staleness threshold. Defaults to 1 hour.
        recent_limit :
            Number of recent activities to include.
        live_health :
            When ``False`` (the default) the health distribution is read
            from the most recent persisted :class:`ValidationRecord` per
            holon in a single aggregate query. Holons that have never been
            validated do not contribute to the distribution. When ``True``
            every holon's membrane is re-validated with pyshacl on the
            spot -- accurate but O(N) round-trips; use only for small
            holarchies or when freshness matters more than latency.

        Returns:
        -------
        HolarchySummary

        .. versionadded:: 0.7.0
        .. versionchanged:: 0.8.0
            Reduced from ~4+N round-trips to a handful of aggregate
            queries. Health is now read from persisted validation records
            by default; pass ``live_health=True`` for the old
            re-validate-every-holon behaviour (audit P4).
        """
        from holonic.console_model import HolarchySummary

        if max_age is None:
            max_age = timedelta(hours=1)

        summaries = self.list_holons_summary()
        holon_count = len(summaries)
        root_count = sum(1 for s in summaries if not s.member_of)

        portal_rows = self.backend.query(Q.COUNT_PORTALS)
        portal_count = int(portal_rows[0]["n"]) if portal_rows else 0

        if live_health:
            health_dist = self._live_health_distribution(
                s.iri for s in summaries
            )
        else:
            health_dist = self._persisted_health_distribution()

        stale_count = len(self._stale_holon_iris(max_age))

        trail = self.collect_audit_trail(limit=recent_limit)

        return HolarchySummary(
            holon_count=holon_count,
            portal_count=portal_count,
            root_count=root_count,
            health_distribution=health_dist,
            stale_count=stale_count,
            recent_activities=(trail.traversals[:recent_limit]),
        )

    @staticmethod
    def _empty_health_distribution() -> dict[str, int]:
        return {"intact": 0, "weakened": 0, "compromised": 0}

    def _persisted_health_distribution(self) -> dict[str, int]:
        """Health distribution from the latest persisted record per holon.

        Reads ``cga:membraneHealth`` at each holon's most-recent validation
        timestamp in one aggregate query (P4). Holons never validated are
        absent from the result and so do not contribute to any bucket.
        """
        dist = self._empty_health_distribution()
        seen: set[str] = set()
        for row in self.backend.query(Q.LATEST_HEALTH):
            holon = row.get("holon")
            if holon is None or holon in seen:
                # A tie on the max timestamp can yield two rows for one
                # holon; count the first deterministically.
                continue
            seen.add(holon)
            # ?health is a urn:holonic:ontology:{Intact,...} IRI.
            key = str(row["health"]).rsplit(":", 1)[-1].lower()
            if key in dist:
                dist[key] += 1
        return dist

    def _live_health_distribution(
        self, holon_iris: Iterable[str]
    ) -> dict[str, int]:
        """Health distribution by re-validating every membrane (opt-in)."""
        dist = self._empty_health_distribution()
        for iri in holon_iris:
            result = self.validate_membrane(iri)
            dist[result.health.value] += 1
        return dist

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
        return self._console.list_holons_summary()

    def get_holon_detail(self, holon_iri: str) -> HolonDetail | None:
        """Return the full holon descriptor including layer graph IRIs.

        Returns None if the holon is not registered.
        """
        return self._console.get_holon_detail(holon_iri)

    def holon_interior_classes(self, holon_iri: str) -> list[ClassInstanceCount]:
        """Return (rdf:type, instance count) pairs across a holon's interior.

        Empty list if the holon has no interior graphs or no typed
        instances. Counts are DISTINCT subject counts per class.
        """
        return self._console.holon_interior_classes(holon_iri)

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
        return self._console.holon_neighborhood(holon_iri, depth)

    # ══════════════════════════════════════════════════════════
    # Portal browsing (0.3.1)
    # ══════════════════════════════════════════════════════════

    def list_portals(self) -> list[PortalSummary]:
        """Return a flat list of all portals across the dataset."""
        return self._console.list_portals()

    def get_portal(self, portal_iri: str) -> PortalDetail | None:
        """Return the full portal descriptor including the CONSTRUCT body.

        Returns None if no portal with that IRI is registered.
        """
        return self._console.get_portal(portal_iri)

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

    def _stale_holon_iris(self, max_age: timedelta) -> set[str]:
        """IRIs of holons stale beyond ``max_age`` in a single aggregate query.

        A holon is stale if it has never been traversed or its most recent
        traversal is older than the cutoff (P7: one ``MAX(?timestamp)``
        aggregate instead of a per-holon freshness query).
        """
        from datetime import datetime as dt

        cutoff = datetime.now(UTC) - max_age
        stale: set[str] = set()
        for row in self.backend.query(Q.LATEST_TRAVERSALS):
            latest = row.get("latest")
            if not latest:
                stale.add(row["holon"])
                continue
            try:
                last_time = dt.fromisoformat(str(latest))
                if last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                # Unparseable timestamp -> treat as stale (conservative).
                stale.add(row["holon"])
                continue
            if last_time < cutoff:
                stale.add(row["holon"])
        return stale

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
        .. versionchanged:: 0.8.0
            Staleness is now computed with a single aggregate query plus the
            2-query :meth:`iter_holons` (was ~5N queries). See audit P7.
        """
        if max_age is None:
            max_age = timedelta(hours=1)
        stale_iris = self._stale_holon_iris(max_age)
        return [h for h in self.iter_holons() if h.iri in stale_iris]

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
            Q.GET_HOLON_INTERIORS, holon=_bind_iri(target_iri)
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

    # ══════════════════════════════════════════════════════════
    # Projection pipelines (0.3.5) — delegated to PipelineManager (0.8.0)
    # ══════════════════════════════════════════════════════════

    def register_pipeline(self, spec: ProjectionPipelineSpec) -> str:
        """Register a projection pipeline in the registry.

        Validates that every step's ``transform_name`` (if any) is
        known to the plugin registry. Raises ``TransformNotFoundError``
        at registration time rather than later at run time.

        Returns the pipeline's IRI.
        """
        return self._pipelines.register_pipeline(spec)

    def register_pipeline_ttl(self, ttl: str) -> None:
        """Escape hatch: register a pipeline from caller-supplied Turtle.

        Parses the Turtle into the registry graph without validation.
        Caller is responsible for conforming to the
        ``cga:ProjectionPipelineSpec`` + ``cga:ProjectionPipelineStep``
        vocabulary and for valid rdf:List ordering.
        """
        self._pipelines.register_pipeline_ttl(ttl)

    def attach_pipeline(self, holon_iri: str, spec_iri: str) -> None:
        """Declare that a holon has access to a registered pipeline.

        Writes ``<holon_iri> cga:hasPipeline <spec_iri>`` into the
        registry graph. Idempotent at the RDF level (duplicate
        triples in the same graph are coalesced).
        """
        self._pipelines.attach_pipeline(holon_iri, spec_iri)

    def list_pipelines(self, holon_iri: str) -> list[ProjectionPipelineSummary]:
        """Return projection pipelines attached to a holon.

        Each summary carries just iri, name, description, and step
        count -- use ``get_pipeline(iri)`` for full step content.
        """
        return self._pipelines.list_pipelines(holon_iri)

    def get_pipeline(self, spec_iri: str) -> ProjectionPipelineSpec | None:
        """Return the full pipeline spec as a ``ProjectionPipelineSpec``.

        Returns ``None`` if no pipeline with the given IRI is registered.
        Steps are returned in their declared rdf:List order.
        """
        return self._pipelines.get_pipeline(spec_iri)

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
        return self._pipelines.run_projection(
            holon_iri,
            spec_iri,
            store_as=store_as,
            agent_iri=agent_iri,
        )

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
