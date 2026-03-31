"""
graph_builder.py — Convert holonic RDF structures to yFiles node/edge lists.

Handles:
  - Single holon → nodes grouped by layer (interior/boundary/projection/context)
  - Holarchy → holons as parent groups, layers as child groups, triples as leaf nodes
  - Arbitrary SPARQL CONSTRUCT/SELECT results → flat node/edge graph
  - Portal edges between holon groups
"""

from __future__ import annotations

from typing import Optional
from rdflib import Graph, URIRef, Literal, BNode, RDF, RDFS
from rdflib.term import Node as RDFNode

from ..holon import Holon
from ..holarchy import Holarchy
from ..namespaces import CGA
from . import styles


def _node_id(term: RDFNode, layer: str = "", holon_iri: str = "") -> str:
    """Generate a unique node ID for an RDF term within a layer context."""
    if isinstance(term, Literal):
        # Literals get unique IDs scoped to their layer to avoid collisions
        val = str(term)[:30].replace(" ", "_")
        return f"lit:{layer}:{holon_iri}:{val}:{hash(term) % 10000}"
    if isinstance(term, BNode):
        return f"bnode:{layer}:{holon_iri}:{str(term)}"
    return str(term)


def _node_label(term: RDFNode) -> str:
    """Generate a human-readable label for an RDF term."""
    if isinstance(term, Literal):
        val = str(term)
        return val[:50] + ("..." if len(val) > 50 else "")
    if isinstance(term, BNode):
        return f"_:{str(term)[:8]}"
    return styles.shorten_uri(str(term))


def _classify_node(term: RDFNode, layer: str) -> str:
    """Return the node type for styling purposes."""
    if isinstance(term, Literal):
        return "literal"
    return layer or "default"


# ------------------------------------------------------------------
# Single Holon → nodes and edges
# ------------------------------------------------------------------

def holon_to_graph_data(
    holon: Holon,
    layers: Optional[list[str]] = None,
    show_group_nodes: bool = True,
) -> tuple[list[dict], list[dict]]:
    """
    Convert a single Holon's named graphs into yFiles node/edge lists.

    Parameters
    ----------
    holon : Holon
        The holon to visualise.
    layers : list[str], optional
        Which layers to include.  Default: all four.
    show_group_nodes : bool
        If True, create group nodes for each layer and parent
        resource nodes to them.

    Returns
    -------
    (nodes, edges)
        Lists of dicts suitable for ``GraphWidget.nodes`` and ``.edges``.
    """
    if layers is None:
        layers = ["interior", "boundary", "projection", "context"]

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_counter = 0

    # Create holon group node
    if show_group_nodes:
        nodes[holon.iri] = {
            "id": holon.iri,
            "properties": {
                "label": holon.label,
                "layer": "holon",
                "type": "holon",
                "is_group": True,
            },
        }

    for layer_name in layers:
        graph: Graph = getattr(holon, layer_name, None)
        if graph is None:
            continue

        # Create layer group node (child of holon group)
        layer_group_id = f"{holon.iri}/{layer_name}"
        if show_group_nodes:
            nodes[layer_group_id] = {
                "id": layer_group_id,
                "properties": {
                    "label": f"{holon.label} / {layer_name}",
                    "layer": layer_name,
                    "type": "layer_group",
                    "is_group": True,
                    "parent": holon.iri,
                },
            }

        for s, p, o in graph:
            s_id = _node_id(s, layer_name, holon.iri)
            o_id = _node_id(o, layer_name, holon.iri)

            # Subject node
            if s_id not in nodes:
                nodes[s_id] = {
                    "id": s_id,
                    "properties": {
                        "label": _node_label(s),
                        "layer": layer_name,
                        "type": _classify_node(s, layer_name),
                        "uri": str(s),
                        "is_group": False,
                        **({"parent": layer_group_id} if show_group_nodes else {}),
                    },
                }

            # Object node
            if o_id not in nodes:
                nodes[o_id] = {
                    "id": o_id,
                    "properties": {
                        "label": _node_label(o),
                        "layer": layer_name,
                        "type": _classify_node(o, layer_name),
                        "uri": str(o),
                        "is_group": False,
                        **({"parent": layer_group_id} if show_group_nodes else {}),
                    },
                }

            # Edge
            edge_counter += 1
            edges.append({
                "id": edge_counter,
                "start": s_id,
                "end": o_id,
                "properties": {
                    "label": _node_label(p),
                    "predicate": str(p),
                    "layer": layer_name,
                },
            })

    return list(nodes.values()), edges


# ------------------------------------------------------------------
# Holarchy → nodes and edges
# ------------------------------------------------------------------

def holarchy_to_graph_data(
    holarchy: Holarchy,
    layers: Optional[list[str]] = None,
    show_internals: bool = True,
    show_portals: bool = True,
) -> tuple[list[dict], list[dict]]:
    """
    Convert a full Holarchy into yFiles node/edge lists.

    Each holon becomes a group node.  If ``show_internals`` is True,
    each layer becomes a child group with its triples as leaf nodes.
    If False, holons are shown as atomic nodes connected by portals.

    Portals become edges between holon groups.
    """
    all_nodes: dict[str, dict] = {}
    all_edges: list[dict] = []
    edge_counter = 0

    for holon in holarchy.holons:
        if show_internals:
            h_nodes, h_edges = holon_to_graph_data(holon, layers=layers)
            for n in h_nodes:
                all_nodes[n["id"]] = n
            # Offset edge IDs
            for e in h_edges:
                edge_counter += 1
                e["id"] = edge_counter
                all_edges.append(e)
        else:
            # Atomic holon node
            all_nodes[holon.iri] = {
                "id": holon.iri,
                "properties": {
                    "label": holon.label,
                    "layer": "holon",
                    "type": "holon",
                    "depth": holon.depth,
                    "is_group": False,
                    "interior_count": len(holon.interior),
                    "boundary_count": len(holon.boundary),
                },
            }

    if show_portals:
        for portal in holarchy.portals:
            edge_counter += 1
            all_edges.append({
                "id": edge_counter,
                "start": portal.source.iri,
                "end": portal.target.iri,
                "properties": {
                    "label": portal.label or styles.shorten_uri(portal.iri),
                    "predicate": "cga:portal",
                    "layer": "portal",
                    "traversable": portal.traversable,
                    "type": type(portal).__name__,
                },
            })

    return list(all_nodes.values()), all_edges


# ------------------------------------------------------------------
# SPARQL results → nodes and edges
# ------------------------------------------------------------------

def sparql_construct_to_graph_data(
    result_graph: Graph,
    layer: str = "default",
) -> tuple[list[dict], list[dict]]:
    """Convert a SPARQL CONSTRUCT result graph to yfiles format."""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_counter = 0

    for s, p, o in result_graph:
        s_id = _node_id(s, layer)
        o_id = _node_id(o, layer)

        if s_id not in nodes:
            nodes[s_id] = {
                "id": s_id,
                "properties": {
                    "label": _node_label(s),
                    "layer": layer,
                    "type": _classify_node(s, layer),
                    "uri": str(s),
                },
            }

        if o_id not in nodes:
            nodes[o_id] = {
                "id": o_id,
                "properties": {
                    "label": _node_label(o),
                    "layer": layer,
                    "type": _classify_node(o, layer),
                    "uri": str(o) if not isinstance(o, Literal) else str(o),
                },
            }

        edge_counter += 1
        edges.append({
            "id": edge_counter,
            "start": s_id,
            "end": o_id,
            "properties": {
                "label": _node_label(p),
                "predicate": str(p),
                "layer": layer,
            },
        })

    return list(nodes.values()), edges
