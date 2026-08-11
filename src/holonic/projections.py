"""Projection utilities for holonic RDF graphs.

Projections transform RDF graph structures into simplified forms useful
for visualization, LPG-style analysis, or downstream consumption.

Two modes of projection:

**Graph-to-Graph (CONSTRUCT-based):**
    Stays in RDF.  Expressed as SPARQL CONSTRUCT queries.  Composable.
    Results can be stored as named graphs in the holarchy.

**Graph-to-Structure (Pythonic):**
    Exits RDF into Python dicts, NetworkX graphs, or other structures.
    Used for the "last mile" to visualization/analysis.  Expressed as
    Python functions operating on rdflib.Graph.

Both modes share a common pattern: they take a source graph (or set of
named graphs from the dataset) and produce a simplified output.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import RDF, RDFS, SKOS

if TYPE_CHECKING:
    from holonic.console_model import ProjectionPipelineSpec

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# Graph-to-Graph projections (SPARQL CONSTRUCT templates)
# ══════════════════════════════════════════════════════════════

# These are parameterized CONSTRUCT queries that produce simplified
# RDF from source RDF.  They can be registered as portal CONSTRUCT
# queries, stored in boundary graphs, or composed in pipelines.


CONSTRUCT_STRIP_TYPES = """
# Strip rdf:type triples -- useful when type is encoded as a node
# attribute in the downstream representation.
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
CONSTRUCT {{
    ?s ?p ?o .
}}
WHERE {{
    {graph_clause}
    {{ ?s ?p ?o . FILTER(?p != rdf:type) }}
}}
"""

CONSTRUCT_OBJECT_PROPERTIES_ONLY = """
# Retain only object properties (IRI objects) -- data properties
# become node attributes in the downstream representation.
CONSTRUCT {{
    ?s ?p ?o .
}}
WHERE {{
    {graph_clause}
    {{ ?s ?p ?o . FILTER(isIRI(?o)) }}
}}
"""

CONSTRUCT_DATA_PROPERTIES_ONLY = """
# Extract only data properties (literal objects) for a given subject.
CONSTRUCT {{
    ?s ?p ?o .
}}
WHERE {{
    {graph_clause}
    {{ ?s ?p ?o . FILTER(isLiteral(?o)) }}
}}
"""

CONSTRUCT_COLLAPSE_REIFICATION = """
# Collapse RDF reification into direct triples.
# rdf:Statement instances become the triple they describe.
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
CONSTRUCT {{
    ?subj ?pred ?obj .
}}
WHERE {{
    {graph_clause}
    {{
        ?stmt a rdf:Statement ;
            rdf:subject ?subj ;
            rdf:predicate ?pred ;
            rdf:object ?obj .
    }}
}}
"""

CONSTRUCT_LABELS_ONLY = """
# Project a label graph: only rdfs:label, skos:prefLabel, skos:altLabel.
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
CONSTRUCT {{
    ?s rdfs:label ?label .
}}
WHERE {{
    {graph_clause}
    {{
        {{ ?s rdfs:label ?label }}
        UNION
        {{ ?s skos:prefLabel ?label }}
        UNION
        {{ ?s skos:altLabel ?label }}
    }}
}}
"""

CONSTRUCT_SUBCLASS_TREE = """
# Extract the rdfs:subClassOf hierarchy as a tree.
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
CONSTRUCT {{
    ?sub rdfs:subClassOf ?super .
    ?sub rdfs:label ?subLabel .
    ?super rdfs:label ?superLabel .
}}
WHERE {{
    {graph_clause}
    {{
        ?sub rdfs:subClassOf ?super .
        OPTIONAL {{ ?sub rdfs:label ?subLabel }}
        OPTIONAL {{ ?super rdfs:label ?superLabel }}
    }}
}}
"""


def _wrap_graph_clause(graph_iri: str | None) -> str:
    """Generate a GRAPH clause wrapper or empty string."""
    if graph_iri:
        return f"GRAPH <{graph_iri}>"
    return ""


def build_construct(
    template: str,
    graph_iri: str | None = None,
) -> str:
    """Instantiate a CONSTRUCT template with optional GRAPH scoping.

    If ``template`` contains the ``{graph_clause}`` placeholder, it is
    treated as a format string (escaped braces ``{{`` / ``}}`` get
    un-escaped) and the placeholder is substituted with either a
    ``GRAPH <iri>`` clause or an empty string.

    If the placeholder is absent, the template is returned as-is --
    letting callers pass raw CONSTRUCT queries through ``add_construct``
    without having to escape every brace for ``str.format``.
    """
    if "{graph_clause}" not in template:
        return template
    clause = _wrap_graph_clause(graph_iri)
    return template.format(graph_clause=clause)


# ══════════════════════════════════════════════════════════════
# Graph-to-Structure projections (Pythonic)
# ══════════════════════════════════════════════════════════════


@dataclass
class ProjectedNode:
    """A node in a projected graph with collapsed attributes."""

    iri: str
    types: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    label: str | None = None

    def __repr__(self):
        lbl = self.label or self.iri.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        return f"Node({lbl}, {len(self.attributes)} attrs)"


@dataclass
class ProjectedEdge:
    """An edge in a projected graph with collapsed attributes."""

    source: str
    predicate: str
    target: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def __repr__(self):
        p = self.predicate.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        return f"Edge({self.source.rsplit(':', 1)[-1]} --{p}-> {self.target.rsplit(':', 1)[-1]})"


@dataclass
class ProjectedGraph:
    """An LPG-style projection of an RDF graph.

    Nodes have types and literal attributes collapsed onto them.
    Edges carry only object-property relationships.  Blank nodes
    are resolved into inline structures where possible.
    """

    nodes: dict[str, ProjectedNode] = field(default_factory=dict)
    edges: list[ProjectedEdge] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a plain dict (JSON-serializable)."""
        return {
            "nodes": {
                iri: {
                    "iri": n.iri,
                    "types": n.types,
                    "label": n.label,
                    "attributes": n.attributes,
                }
                for iri, n in self.nodes.items()
            },
            "edges": [
                {
                    "source": e.source,
                    "predicate": e.predicate,
                    "target": e.target,
                    "attributes": e.attributes,
                }
                for e in self.edges
            ],
        }

    def __repr__(self):
        return f"ProjectedGraph({len(self.nodes)} nodes, {len(self.edges)} edges)"


def _resolve_blank_node(
    graph: Graph,
    bnode: BNode,
    resolve_lists: bool = True,
) -> dict[str, Any]:
    """Recursively resolve a blank node into a nested dict."""
    result: dict[str, Any] = {}
    for p, o in graph.predicate_objects(bnode):
        p_str = str(p)
        if isinstance(o, Literal):
            result[p_str] = o.toPython()
        elif isinstance(o, BNode):
            # Check for list
            if resolve_lists and (o, RDF.first, None) in graph:
                try:
                    items = list(Collection(graph, o))
                    result[p_str] = [
                        i.toPython() if isinstance(i, Literal) else str(i) for i in items
                    ]
                except Exception:
                    result[p_str] = _resolve_blank_node(graph, o, resolve_lists)
            else:
                result[p_str] = _resolve_blank_node(graph, o, resolve_lists)
        elif isinstance(o, URIRef):
            result[p_str] = str(o)
    return result


@dataclass
class ProjectionOptions:
    """Options controlling :func:`project_to_lpg`.

    Bundles the projection knobs so the pass helpers take one argument
    instead of six. Constructed internally by :func:`project_to_lpg` from its
    keyword arguments; callers keep using those keywords.
    """

    collapse_types: bool = True
    collapse_literals: bool = True
    resolve_blanks: bool = True
    resolve_lists: bool = True
    include_predicates: set[str] | None = None
    exclude_predicates: set[str] | None = None

    @property
    def excluded(self) -> set[str]:
        """Predicate blacklist as a set (empty when none configured)."""
        return self.exclude_predicates or set()


def _find_list_heads(graph: Graph) -> set[BNode]:
    """Pass 1: blank nodes that are the head of an ``rdf:first``/``rdf:rest`` list."""
    heads: set[BNode] = set()
    for s in graph.subjects(RDF.first, None):
        head = s
        for parent_s in graph.subjects(RDF.rest, head):
            head = parent_s
        if isinstance(head, BNode):
            heads.add(head)
    return heads


def _find_blank_parents(
    graph: Graph, list_heads: set[BNode]
) -> dict[BNode, tuple[URIRef | BNode, URIRef]]:
    """Pass 2: map each structured-value blank node to its (subject, predicate)."""
    blank_parents: dict[BNode, tuple[URIRef | BNode, URIRef]] = {}
    for s, p, o in graph:
        if isinstance(o, BNode) and o not in list_heads:
            blank_parents[o] = (s, p)
    return blank_parents


def _accumulate_attr(node: ProjectedNode, key: str, val: Any) -> None:
    """Set ``node.attributes[key] = val``, promoting to a list on repeat keys."""
    existing = node.attributes.get(key)
    if existing is None:
        node.attributes[key] = val
    elif isinstance(existing, list):
        existing.append(val)
    else:
        node.attributes[key] = [existing, val]


def _project_blank_object(
    graph: Graph,
    projected: ProjectedGraph,
    s_str: str,
    p_str: str,
    o: BNode,
    opts: ProjectionOptions,
    list_heads: set[BNode],
) -> None:
    """Resolve a blank-node object into a list (if it heads an RDF list) or a
    nested dict, attaching the result to the subject node's attributes.
    """
    if o in list_heads and opts.resolve_lists:
        try:
            items = list(Collection(graph, o))
            if s_str in projected.nodes:
                projected.nodes[s_str].attributes[p_str] = [
                    i.toPython() if isinstance(i, Literal) else str(i) for i in items
                ]
        except Exception:
            pass
        return
    nested = _resolve_blank_node(graph, o, opts.resolve_lists)
    if s_str in projected.nodes:
        _accumulate_attr(projected.nodes[s_str], p_str, nested)


def _project_triple(
    graph: Graph,
    projected: ProjectedGraph,
    s: URIRef | BNode,
    p: URIRef,
    o: Any,
    opts: ProjectionOptions,
    list_heads: set[BNode],
    blank_parents: dict[BNode, tuple[URIRef | BNode, URIRef]],
) -> None:
    """Classify a single triple and fold it into *projected* (Pass 3 body)."""
    s_str = str(s)

    # Skip blank-node internals when we're inlining them.
    if opts.resolve_blanks and isinstance(s, BNode) and (s in blank_parents or s in list_heads):
        return

    # Ensure the source node exists (blank subjects are never their own node).
    if s_str not in projected.nodes and not isinstance(s, BNode):
        projected.nodes[s_str] = ProjectedNode(iri=s, attributes={"iri": s})

    p_str = str(p)

    # ── Type collapse ──
    if opts.collapse_types and p == RDF.type:
        if s_str in projected.nodes:
            projected.nodes[s_str].types.append(str(o))
        return

    # ── Predicate filtering ──
    if opts.include_predicates and p_str not in opts.include_predicates:
        return
    if p_str in opts.excluded:
        return

    # ── Label capture ──
    if p in (RDFS.label, SKOS.prefLabel):
        if s_str in projected.nodes:
            projected.nodes[s_str].label = str(o)
            if opts.collapse_literals and isinstance(o, Literal):
                projected.nodes[s_str].attributes[p_str] = o.toPython()
        return

    # ── Literal collapse ──
    if opts.collapse_literals and isinstance(o, Literal):
        if s_str in projected.nodes:
            _accumulate_attr(projected.nodes[s_str], p_str, o.toPython())
        return

    # ── Blank node resolution ──
    if opts.resolve_blanks and isinstance(o, BNode):
        _project_blank_object(graph, projected, s_str, p_str, o, opts, list_heads)
        return

    # ── Object property -> edge ──
    if isinstance(o, URIRef):
        o_str = str(o)
        if o_str not in projected.nodes:
            projected.nodes[o_str] = ProjectedNode(iri=o_str)
        projected.edges.append(ProjectedEdge(source=s_str, predicate=p_str, target=o_str))


def _build_nodes_and_edges(
    graph: Graph,
    projected: ProjectedGraph,
    opts: ProjectionOptions,
    list_heads: set[BNode],
    blank_parents: dict[BNode, tuple[URIRef | BNode, URIRef]],
) -> None:
    """Pass 3: fold every triple into *projected*."""
    for s, p, o in graph:
        _project_triple(graph, projected, s, p, o, opts, list_heads, blank_parents)


def project_to_lpg(
    graph: Graph,
    *,
    collapse_types: bool = True,
    collapse_literals: bool = True,
    resolve_blanks: bool = True,
    resolve_lists: bool = True,
    include_predicates: set[str] | None = None,
    exclude_predicates: set[str] | None = None,
) -> ProjectedGraph:
    """Project an RDF graph into an LPG-style structure.

    This is the primary "exit ramp" from RDF into a property-graph
    representation suitable for visualization, NetworkX, or LPG tools.

    Parameters
    ----------
    graph :
        Source rdflib.Graph.
    collapse_types :
        If True, rdf:type becomes a node attribute, not an edge.
    collapse_literals :
        If True, literal-valued triples become node attributes.
    resolve_blanks :
        If True, blank nodes are inlined as nested dicts on their
        parent node's attributes.
    resolve_lists :
        If True, RDF collections (rdf:first/rdf:rest chains) are
        resolved into Python lists.
    include_predicates :
        If set, only these predicates appear as edges (whitelist).
    exclude_predicates :
        If set, these predicates are excluded from edges (blacklist).
    """
    opts = ProjectionOptions(
        collapse_types=collapse_types,
        collapse_literals=collapse_literals,
        resolve_blanks=resolve_blanks,
        resolve_lists=resolve_lists,
        include_predicates=include_predicates,
        exclude_predicates=exclude_predicates,
    )

    projected = ProjectedGraph()
    # Pass 1/2 are prerequisites for Pass 3, and each is a no-op when its
    # feature is disabled (preserving the original short-circuits).
    list_heads = _find_list_heads(graph) if opts.resolve_lists else set()
    blank_parents = (
        _find_blank_parents(graph, list_heads) if opts.resolve_blanks else {}
    )
    _build_nodes_and_edges(graph, projected, opts, list_heads, blank_parents)
    return projected


def collapse_reification(
    graph: Graph,
    *,
    preserve_metadata: bool = True,
) -> ProjectedGraph:
    """Collapse RDF reification into direct edges with metadata.

    rdf:Statement instances become edges.  Non-structural properties
    on the statement (e.g., prov:wasAttributedTo, dct:created) become
    edge attributes.

    Parameters
    ----------
    graph :
        Source graph containing reified statements.
    preserve_metadata :
        If True, non-structural properties on the rdf:Statement
        become attributes on the projected edge.
    """
    projected = ProjectedGraph()
    structural = {RDF.type, RDF.subject, RDF.predicate, RDF.object}

    for stmt in graph.subjects(RDF.type, RDF.Statement):
        subj = graph.value(stmt, RDF.subject)
        pred = graph.value(stmt, RDF.predicate)
        obj = graph.value(stmt, RDF.object)
        if not all([subj, pred, obj]):
            continue

        s_str, o_str = str(subj), str(obj)

        # Ensure nodes
        if s_str not in projected.nodes:
            projected.nodes[s_str] = ProjectedNode(iri=s_str)
        if isinstance(obj, URIRef) and o_str not in projected.nodes:
            projected.nodes[o_str] = ProjectedNode(iri=o_str)

        # Build edge
        edge = ProjectedEdge(source=s_str, predicate=str(pred), target=o_str)

        if preserve_metadata:
            for p2, o2 in graph.predicate_objects(stmt):
                if p2 not in structural:
                    key = str(p2)
                    val = o2.toPython() if isinstance(o2, Literal) else str(o2)
                    edge.attributes[key] = val

        projected.edges.append(edge)

    return projected


# ══════════════════════════════════════════════════════════════
# Projection pipeline (composable)
# ══════════════════════════════════════════════════════════════


@dataclass
class ProjectionStep:
    """A single step in a projection pipeline."""

    name: str
    construct: str | None = None  # SPARQL CONSTRUCT (graph->graph)
    transform: Callable[[Graph], Graph] | None = None  # Python (graph->graph)

    def apply(self, source: Graph) -> Graph:
        """Apply this step to *source*, returning the resulting graph.

        A CONSTRUCT step runs **against ``source``** -- the output of the
        previous step -- so steps chain correctly and a pipeline never widens
        to more than the graph it was handed.

        .. versionchanged:: 0.8.0
           Dropped the ``backend`` parameter. Previously, passing a backend
           made the CONSTRUCT run against the *entire* backend dataset instead
           of ``source``, which broke chaining (step *n* ignored step *n-1*'s
           output) and leaked triples from other holons into the projection
           (audit A3). Materialize the source graph before calling ``apply``.
        """
        if self.construct:
            result = source.query(self.construct)
            constructed = result.graph
            if constructed is None:  # not a CONSTRUCT/DESCRIBE query
                raise ValueError(
                    f"pipeline step {self.name!r} CONSTRUCT did not yield a graph; "
                    "steps must use CONSTRUCT (or DESCRIBE), not SELECT/ASK"
                )
            return constructed
        elif self.transform:
            return self.transform(source)
        return source


class ProjectionPipeline:
    """A composable pipeline of projection steps.

    Steps are applied sequentially.  Each step takes the output of
    the previous step as input.  Steps can be SPARQL CONSTRUCTs
    (staying in RDF) or Python functions (Graph->Graph).

    The final output can optionally be converted to a ProjectedGraph
    via project_to_lpg().

    > TODO: write metadata about the Pipeline (self-describing)
    w/n holon boundary (new opaque portal type?)

    Example:
    -------
    ```python
    pipeline = ProjectionPipeline("visualization")
    pipeline.add_construct("strip_types", CONSTRUCT_STRIP_TYPES, graph_iri=...)
    pipeline.add_construct("labels", CONSTRUCT_LABELS_ONLY, graph_iri=...)
    pipeline.add_transform("custom", my_transform_fn)

    result_graph = pipeline.apply(source_graph)
    lpg = pipeline.apply_to_lpg(source_graph)
    ```
    """

    def __init__(self, name: str = "projection"):
        self.name = name
        self.steps: list[ProjectionStep] = []

    def add_construct(
        self,
        name: str,
        template: str,
        graph_iri: str | None = None,
    ) -> ProjectionPipeline:
        """Add a CONSTRUCT-based step."""
        query = build_construct(template, graph_iri)
        self.steps.append(ProjectionStep(name=name, construct=query))
        return self

    def add_transform(
        self,
        name: str,
        fn: Callable[[Graph], Graph],
    ) -> ProjectionPipeline:
        """Add a Python transform step (Graph->Graph)."""
        self.steps.append(ProjectionStep(name=name, transform=fn))
        return self

    def apply(self, source: Graph) -> Graph:
        """Apply all steps sequentially, returning the final Graph.

        Each step receives the previous step's output, starting from
        *source*. The pipeline never reads beyond the graph it is handed.

        .. versionchanged:: 0.8.0
           Dropped the ``backend`` parameter (see
           :meth:`ProjectionStep.apply`). Fetch the source graph from the
           backend before calling -- e.g. :meth:`HolonicDataset.apply_pipeline`
           merges the holon's interiors and passes them here.
        """
        current = source
        for step in self.steps:
            current = step.apply(current)
        return current

    def apply_to_graph(self, source: Graph) -> Graph:
        """Apply all steps sequentially, returning the final Graph.

        Alias for :meth:`apply` that matches the terminal-method naming
        used in SPEC R7.3 alongside :meth:`apply_to_lpg`.
        """
        return self.apply(source)

    def apply_to_lpg(self, source: Graph, **lpg_kwargs) -> ProjectedGraph:
        """Apply all steps, then convert the result to an LPG projection."""
        result = self.apply(source)
        return project_to_lpg(result, **lpg_kwargs)

    def to_spec(self, iri: str, *, description: str | None = None) -> ProjectionPipelineSpec:
        """Convert this builder into a declarative :class:`ProjectionPipelineSpec`.

        The ``ProjectionPipelineSpec`` (RDF-serializable, registry-backed) is
        the canonical, persistable pipeline model as of 0.8.0;
        ``ProjectionPipeline`` is the fluent builder for it. ``to_spec`` bridges
        the two so a pipeline assembled in code can be registered via
        :meth:`HolonicDataset.register_pipeline` and later executed through
        :meth:`HolonicDataset.run_projection`.

        Each CONSTRUCT step maps to ``construct_query``; each transform step
        maps to ``transform_name`` -- the registered name of the callable.

        Raises :class:`ValueError` if a step carries a transform callable that
        is not registered (via ``@projection_transform`` or the
        ``holonic.projections`` entry-point group), since a declarative spec can
        only reference transforms by name -- register the transform first, or
        express the step as a CONSTRUCT.

        .. versionadded:: 0.8.0
        """
        # Local import: console_model + plugins are heavier peers, and this
        # keeps ProjectionPipeline usable without importing the registry stack.
        from holonic.console_model import ProjectionPipelineSpec, ProjectionPipelineStep
        from holonic.plugins import name_for_transform

        spec_steps: list[ProjectionPipelineStep] = []
        for step in self.steps:
            transform_name: str | None = None
            if step.transform is not None:
                transform_name = name_for_transform(step.transform)
                if transform_name is None:
                    raise ValueError(
                        f"pipeline step {step.name!r} uses an unregistered transform "
                        "callable; a ProjectionPipelineSpec references transforms by "
                        "name. Register it with @projection_transform (or via the "
                        "'holonic.projections' entry-point group) before calling "
                        "to_spec(), or express the step as a CONSTRUCT."
                    )
            spec_steps.append(
                ProjectionPipelineStep(
                    name=step.name,
                    transform_name=transform_name,
                    construct_query=step.construct,
                )
            )
        return ProjectionPipelineSpec(
            iri=iri,
            name=self.name,
            steps=spec_steps,
            description=description,
        )

    def __repr__(self):
        return f"ProjectionPipeline({self.name}, {len(self.steps)} steps)"


# ══════════════════════════════════════════════════════════════
# Convenience: common projection functions (Graph->Graph)
# ══════════════════════════════════════════════════════════════


def strip_blank_nodes(graph: Graph) -> Graph:
    """Remove all triples involving blank nodes (subjects or objects).

    Useful as a pre-visualization step when blank nodes add noise.
    Blank node content should be resolved BEFORE this step if needed.
    """
    result = Graph()
    for s, p, o in graph:
        if not isinstance(s, BNode) and not isinstance(o, BNode):
            result.add((s, p, o))
    return result


def extract_types(graph: Graph) -> dict[str, list[str]]:
    """Extract a mapping of subject IRI -> list of rdf:type IRIs.

    This is the companion to type-stripping: extract the types first,
    then strip them from the graph.
    """
    types: dict[str, list[str]] = defaultdict(list)
    for s, _, o in graph.triples((None, RDF.type, None)):
        if isinstance(s, URIRef):
            types[str(s)].append(str(o))
    return dict(types)


def filter_by_class(graph: Graph, class_iri: str) -> Graph:
    """Extract only triples whose subject is an instance of the given class."""
    result = Graph()
    instances = set(graph.subjects(RDF.type, URIRef(class_iri)))
    for s, p, o in graph:
        if s in instances:
            result.add((s, p, o))
    return result


def localize_predicates(graph: Graph) -> Graph:
    """Replace full predicate IRIs with their local names.

    `http://example.org/ontology#hasName` -> `hasName` (as a new IRI
    in a local namespace).  Useful for visualization where full IRIs
    clutter edge labels.
    """
    local_ns = Namespace("urn:local:")
    result = Graph()
    for s, p, o in graph:
        local_name = str(p).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        result.add((s, local_ns[local_name], o))
    return result


# ══════════════════════════════════════════════════════════════
# Plugin registration (0.3.5)
#
# First-party transforms with the (Graph) -> Graph signature are
# registered under stable names via the projection_transform
# decorator. Pipelines (cga:ProjectionPipelineSpec) reference them
# by registered name, not dotted path. Third-party packages register
# their own transforms via the "holonic.projections" entry-point
# group in their pyproject.toml. See holonic.plugins.
#
# extract_types is not registered (returns a dict, not a Graph).
# filter_by_class is not registered (requires a class_iri argument;
# 0.3.5 pipeline steps do not carry per-step arguments -- see
# D-0.3.5-9).
# collapse_reification is not registered (returns a ProjectedGraph --
# an LPG node/edge structure -- not an rdflib Graph, so it does not
# satisfy the (Graph) -> Graph contract that pipelines and put_graph
# rely on). It remains a public function for direct LPG projection.
# ══════════════════════════════════════════════════════════════

from holonic.plugins import (  # noqa: E402 -- deferred import: wraps transforms defined above
    projection_transform as _projection_transform,
)

# Wrap existing names via the decorator. collapse_reification is
# deliberately NOT wrapped: it returns a ProjectedGraph, not a Graph
# (see the note above), so registering it would violate the
# (Graph) -> Graph contract consumers depend on.
strip_blank_nodes = _projection_transform("strip_blank_nodes")(strip_blank_nodes)
localize_predicates = _projection_transform("localize_predicates")(localize_predicates)
