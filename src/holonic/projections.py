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
from dataclasses import dataclass, field
from typing import Any, Callable

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import RDF, RDFS, OWL, XSD, SKOS

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# Graph-to-Graph projections (SPARQL CONSTRUCT templates)
# ══════════════════════════════════════════════════════════════

# These are parameterized CONSTRUCT queries that produce simplified
# RDF from source RDF.  They can be registered as portal CONSTRUCT
# queries, stored in boundary graphs, or composed in pipelines.


CONSTRUCT_STRIP_TYPES = """
# Strip rdf:type triples — useful when type is encoded as a node
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
# Retain only object properties (IRI objects) — data properties
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
    """Instantiate a CONSTRUCT template with optional GRAPH scoping."""
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
        return f"Edge({self.source.rsplit(':',1)[-1]} —{p}→ {self.target.rsplit(':',1)[-1]})"


@dataclass
class ProjectedGraph:
    """An LPG-style projection of an RDF graph.

    Nodes have types and literal attributes collapsed onto them.
    Edges carry only object-property relationships.  Blank nodes
    are resolved into inline structures where possible.
    """

    nodes: dict[str, ProjectedNode] = field(default_factory=dict)
    edges: list[ProjectedEdge] = field(default_factory=list)

    def __repr__(self):
        return f"ProjectedGraph({len(self.nodes)} nodes, {len(self.edges)} edges)"

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
    projected = ProjectedGraph()
    excluded = exclude_predicates or set()

    # ── Pass 1: identify blank nodes that are list heads ──
    list_heads: set[BNode] = set()
    if resolve_lists:
        for s in graph.subjects(RDF.first, None):
            # Walk back to find the list head
            head = s
            for parent_s in graph.subjects(RDF.rest, head):
                head = parent_s
            if isinstance(head, BNode):
                list_heads.add(head)

    # ── Pass 2: identify blank nodes used as structured values ──
    # (blank nodes that are objects of exactly one triple)
    blank_parents: dict[BNode, tuple[URIRef | BNode, URIRef]] = {}
    if resolve_blanks:
        for s, p, o in graph:
            if isinstance(o, BNode) and o not in list_heads:
                # Track parent → blank mapping
                blank_parents[o] = (s, p)

    # ── Pass 3: build nodes and edges ──
    for s, p, o in graph:
        s_str = str(s)

        # Skip blank node internals if we're resolving them
        if resolve_blanks and isinstance(s, BNode) and s in blank_parents:
            continue
        if resolve_blanks and isinstance(s, BNode) and s in list_heads:
            continue

        # Ensure source node exists
        if s_str not in projected.nodes and not isinstance(s, BNode):
            projected.nodes[s_str] = ProjectedNode(iri=s_str)

        p_str = str(p)

        # ── Type collapse ──
        if collapse_types and p == RDF.type:
            if s_str in projected.nodes:
                projected.nodes[s_str].types.append(str(o))
            continue

        # ── Predicate filtering ──
        if include_predicates and p_str not in include_predicates:
            continue
        if p_str in excluded:
            continue

        # ── Label capture ──
        if p in (RDFS.label, SKOS.prefLabel):
            if s_str in projected.nodes:
                projected.nodes[s_str].label = str(o)
            # Also add as attribute
            if collapse_literals and isinstance(o, Literal):
                if s_str in projected.nodes:
                    projected.nodes[s_str].attributes[p_str] = o.toPython()
            continue

        # ── Literal collapse ──
        if collapse_literals and isinstance(o, Literal):
            if s_str in projected.nodes:
                key = p_str
                val = o.toPython()
                # Handle multi-valued: accumulate into list
                existing = projected.nodes[s_str].attributes.get(key)
                if existing is not None:
                    if isinstance(existing, list):
                        existing.append(val)
                    else:
                        projected.nodes[s_str].attributes[key] = [existing, val]
                else:
                    projected.nodes[s_str].attributes[key] = val
            continue

        # ── Blank node resolution ──
        if resolve_blanks and isinstance(o, BNode):
            if o in list_heads and resolve_lists:
                # Resolve RDF list to Python list
                try:
                    items = list(Collection(graph, o))
                    if s_str in projected.nodes:
                        projected.nodes[s_str].attributes[p_str] = [
                            i.toPython() if isinstance(i, Literal) else str(i)
                            for i in items
                        ]
                except Exception:
                    pass
                continue
            else:
                # Inline blank node as nested dict
                nested = _resolve_blank_node(graph, o, resolve_lists)
                if s_str in projected.nodes:
                    existing = projected.nodes[s_str].attributes.get(p_str)
                    if existing is not None:
                        if isinstance(existing, list):
                            existing.append(nested)
                        else:
                            projected.nodes[s_str].attributes[p_str] = [existing, nested]
                    else:
                        projected.nodes[s_str].attributes[p_str] = nested
                continue

        # ── Object property → edge ──
        if isinstance(o, URIRef):
            o_str = str(o)
            # Ensure target node exists
            if o_str not in projected.nodes:
                projected.nodes[o_str] = ProjectedNode(iri=o_str)
            projected.edges.append(ProjectedEdge(
                source=s_str, predicate=p_str, target=o_str
            ))

    return projected


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
                        i.toPython() if isinstance(i, Literal) else str(i)
                        for i in items
                    ]
                except Exception:
                    result[p_str] = _resolve_blank_node(graph, o, resolve_lists)
            else:
                result[p_str] = _resolve_blank_node(graph, o, resolve_lists)
        elif isinstance(o, URIRef):
            result[p_str] = str(o)
    return result


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
    construct: str | None = None  # SPARQL CONSTRUCT (graph→graph)
    transform: Callable[[Graph], Graph] | None = None  # Python (graph→graph)

    def apply(self, source: Graph, backend=None) -> Graph:
        """Apply this step to a source graph."""
        if self.construct:
            if backend:
                return backend.construct(self.construct)
            else:
                return source.query(self.construct).graph
        elif self.transform:
            return self.transform(source)
        return source


class ProjectionPipeline:
    """A composable pipeline of projection steps.

    Steps are applied sequentially.  Each step takes the output of
    the previous step as input.  Steps can be SPARQL CONSTRUCTs
    (staying in RDF) or Python functions (Graph→Graph).

    The final output can optionally be converted to a ProjectedGraph
    via project_to_lpg().

    Example
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
        """Add a Python transform step (Graph→Graph)."""
        self.steps.append(ProjectionStep(name=name, transform=fn))
        return self

    def apply(self, source: Graph, backend=None) -> Graph:
        """Apply all steps sequentially, returning the final Graph."""
        current = source
        for step in self.steps:
            current = step.apply(current, backend)
        return current

    def apply_to_lpg(self, source: Graph, backend=None, **lpg_kwargs) -> ProjectedGraph:
        """Apply all steps, then convert the result to an LPG projection."""
        result = self.apply(source, backend)
        return project_to_lpg(result, **lpg_kwargs)

    def __repr__(self):
        return f"ProjectionPipeline({self.name}, {len(self.steps)} steps)"


# ══════════════════════════════════════════════════════════════
# Convenience: common projection functions (Graph→Graph)
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
    """Extract a mapping of subject IRI → list of rdf:type IRIs.

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

    `http://example.org/ontology#hasName` → `hasName` (as a new IRI
    in a local namespace).  Useful for visualization where full IRIs
    clutter edge labels.
    """
    local_ns = Namespace("urn:local:")
    result = Graph()
    for s, p, o in graph:
        local_name = str(p).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        result.add((s, local_ns[local_name], o))
    return result
