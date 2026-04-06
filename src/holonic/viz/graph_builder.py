"""Projection-driven graph builder for yFiles visualization.

Converts holonic structures to yFiles node/edge lists by FIRST projecting
RDF through the projections module (type collapse, literal collapse,
blank-node resolution, SHACL flattening) and THEN building yFiles data
from the simplified ProjectedGraph.

This eliminates the edge clutter and flat-label problems of the old
graph_builder by ensuring that:
  - rdf:type triples become node type annotations, not edges
  - Literal-valued triples become node attributes, not edges to literal nodes
  - Blank nodes are inlined as nested attributes, not separate nodes
  - SHACL shapes are rendered as compartmented tables, not blank-node trees
"""

from __future__ import annotations

from collections.abc import Callable

from rdflib import Graph

from holonic.projections import (
    ProjectedGraph,
    ProjectedNode,
    project_to_lpg,
)
from holonic.viz import styles
from holonic.viz.formatters import (
    format_compartmented,
    format_shacl_shape,
    format_typed,
)

# ── Label formatter type ──

LabelFormatter = Callable[[ProjectedNode], str]


def _infer_layer(node: ProjectedNode, default: str) -> str:
    """Infer the visual layer from the node's types."""
    for t in node.types:
        t_lower = t.lower()
        if "nodeshape" in t_lower or "shape" in t_lower:
            return "boundary"
        if "holon" in t_lower:
            return "holon"
        if "portal" in t_lower:
            return "portal"
        if "activity" in t_lower:
            return "context"
    return default


def _primary_type(node: ProjectedNode) -> str:
    """Return a short primary type name for shape mapping."""
    if node.types:
        return styles.shorten_uri(node.types[0])
    return "default"


# ══════════════════════════════════════════════════════════════
# ProjectedGraph → yFiles data
# ══════════════════════════════════════════════════════════════


def projected_to_yfiles(
    lpg: ProjectedGraph,
    *,
    layer: str = "default",
    label_fn: LabelFormatter = format_compartmented,
    parent_id: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """Convert a ProjectedGraph into yFiles node/edge lists.

    Parameters
    ----------
    lpg :
        The projected graph (output of project_to_lpg or similar).
    layer :
        Layer name for styling (interior, boundary, etc.).
    label_fn :
        Function to format node labels.  Default: compartmented.
    parent_id :
        If set, all nodes are parented to this group node.
    """
    nodes: list[dict] = []
    edges: list[dict] = []

    for iri, node in lpg.nodes.items():
        # Detect SHACL shapes for special formatting
        is_shape = any("NodeShape" in t for t in node.types)
        fn = format_shacl_shape if is_shape else label_fn

        node_layer = _infer_layer(node, layer)

        n = {
            "id": iri,
            "properties": {
                "label": fn(node),
                "layer": node_layer,
                "type": _primary_type(node),
                "types": node.types,
                "attr_count": len(node.attributes),
                "is_group": False,
            },
        }
        if parent_id:
            n["properties"]["parent"] = parent_id
        nodes.append(n)

    for i, edge in enumerate(lpg.edges):
        e = {
            "id": f"e_{i}",
            "start": edge.source,
            "end": edge.target,
            "properties": {
                "label": styles.shorten_uri(edge.predicate),
                "predicate": edge.predicate,
                "layer": layer,
            },
        }
        if edge.attributes:
            e["properties"]["edge_attrs"] = edge.attributes
        edges.append(e)

    return nodes, edges


# ══════════════════════════════════════════════════════════════
# Holon → yFiles (via HolonicDataset)
# ══════════════════════════════════════════════════════════════


def holon_to_yfiles(
    ds,
    holon_iri: str,
    *,
    layers: list[str] | None = None,
    show_group: bool = True,
    label_fn: LabelFormatter = format_compartmented,
) -> tuple[list[dict], list[dict]]:
    """Build yFiles data for a single holon from a HolonicDataset.

    Queries the dataset for the holon's layer graphs, projects each
    through project_to_lpg(), and builds the yFiles representation.

    Parameters
    ----------
    ds :
        A HolonicDataset instance.
    holon_iri :
        The holon to visualize.
    layers :
        Which layer roles to include.  Default: all registered.
    show_group :
        If True, create a group node for the holon and layer groups.
    label_fn :
        Node label formatter.  Default: compartmented.
    """
    from holonic.sparql import (
        GET_HOLON_BOUNDARIES,
        GET_HOLON_INTERIORS,
    )

    all_nodes: list[dict] = []
    all_edges: list[dict] = []

    # Get holon metadata
    info = ds.get_holon(holon_iri)
    holon_label = info.label if info else styles.shorten_uri(holon_iri)

    # Create holon group node
    if show_group:
        all_nodes.append(
            {
                "id": holon_iri,
                "properties": {
                    "label": holon_label,
                    "layer": "holon",
                    "type": "holon",
                    "is_group": True,
                },
            }
        )

    # Map layer role → (query_template, layer_name)
    layer_specs = {
        "interior": (GET_HOLON_INTERIORS, "interior"),
        "boundary": (GET_HOLON_BOUNDARIES, "boundary"),
    }

    # Also check projection and context
    PROJ_Q = """PREFIX cga: <urn:holonic:ontology:> 
    SELECT ?graph WHERE { <HOLON> cga:hasProjection ?graph }"""
    CTX_Q = (
        "PREFIX cga: <urn:holonic:ontology:> SELECT ?graph WHERE { <HOLON> cga:hasContext ?graph }"
    )
    layer_specs["projection"] = (PROJ_Q, "projection")
    layer_specs["context"] = (CTX_Q, "context")

    include = set(layers or layer_specs.keys())

    for role, (query_tmpl, layer_name) in layer_specs.items():
        if role not in include:
            continue

        q = query_tmpl.replace("?holon", f"<{holon_iri}>").replace("<HOLON>", f"<{holon_iri}>")
        rows = ds.backend.query(q)
        if not rows:
            continue

        # Create layer group
        layer_group_id = f"{holon_iri}/{role}"
        if show_group:
            all_nodes.append(
                {
                    "id": layer_group_id,
                    "properties": {
                        "label": f"{holon_label} / {role}",
                        "layer": layer_name,
                        "type": "layer_group",
                        "is_group": True,
                        "parent": holon_iri,
                    },
                }
            )

        # Merge all graphs for this layer role
        merged = Graph()
        for row in rows:
            g = ds.backend.get_graph(row["graph"])
            for t in g:
                merged.add(t)

        # Project through LPG
        lpg = project_to_lpg(
            merged,
            collapse_types=True,
            collapse_literals=True,
            resolve_blanks=True,
            resolve_lists=True,
        )

        # Convert to yFiles
        parent = layer_group_id if show_group else None
        nodes, edges = projected_to_yfiles(
            lpg,
            layer=layer_name,
            label_fn=label_fn,
            parent_id=parent,
        )
        all_nodes.extend(nodes)
        all_edges.extend(edges)

    return all_nodes, all_edges


def _holarchy_collapsed(
    ds,
    label_fn: LabelFormatter = format_typed,
) -> tuple[list[dict], list[dict]]:
    """Holarchy as single holon nodes connected by portals/membership."""
    # Use project_holarchy which does a CONSTRUCT against the dataset
    lpg = ds.project_holarchy(collapse_types=True, collapse_literals=True)

    nodes, edges = projected_to_yfiles(
        lpg,
        layer="holon",
        label_fn=label_fn,
    )
    return nodes, edges


def _holarchy_expanded(
    ds,
    layers: list[str] | None = None,
    label_fn: LabelFormatter = format_compartmented,
) -> tuple[list[dict], list[dict]]:
    """Holarchy with each holon expanded to show its layers."""
    all_nodes: list[dict] = []
    all_edges: list[dict] = []

    holons = ds.list_holons()
    for holon_info in holons:
        h_nodes, h_edges = holon_to_yfiles(
            ds,
            holon_info.iri,
            layers=layers,
            show_group=True,
            label_fn=label_fn,
        )
        all_nodes.extend(h_nodes)
        all_edges.extend(h_edges)

    # Add portal edges between holon groups
    from holonic.sparql import ALL_PORTALS

    portal_rows = ds.backend.query(ALL_PORTALS)
    for i, r in enumerate(portal_rows):
        all_edges.append(
            {
                "id": f"portal_e_{i}",
                "start": r["source"],
                "end": r["target"],
                "properties": {
                    "label": r.get("label", "portal"),
                    "predicate": "cga:portal",
                    "layer": "portal",
                },
            }
        )

    return all_nodes, all_edges


# ══════════════════════════════════════════════════════════════
# Holarchy topology → yFiles
# ══════════════════════════════════════════════════════════════


def holarchy_to_yfiles(
    ds,
    *,
    show_internals: bool = False,
    layers: list[str] | None = None,
    label_fn: LabelFormatter = format_typed,
) -> tuple[list[dict], list[dict]]:
    """Build yFiles data for the holarchy topology.

    Parameters
    ----------
    ds :
        A HolonicDataset instance.
    show_internals :
        If True, expand each holon to show its layer contents.
        If False, show holons as single nodes with portal edges.
    layers :
        When show_internals=True, which layers to display.
    label_fn :
        Node label formatter for topology mode.
    """
    if show_internals:
        return _holarchy_expanded(ds, layers=layers, label_fn=label_fn)
    else:
        return _holarchy_collapsed(ds, label_fn=label_fn)


# ══════════════════════════════════════════════════════════════
# SPARQL result → yFiles (for SPARQLExplorer)
# ══════════════════════════════════════════════════════════════


def sparql_result_to_yfiles(
    result_graph: Graph,
    *,
    layer: str = "default",
    label_fn: LabelFormatter = format_compartmented,
) -> tuple[list[dict], list[dict]]:
    """Convert a SPARQL CONSTRUCT result graph to yFiles data.

    Projects the result through project_to_lpg first, eliminating
    type edges, literal nodes, and blank-node clutter.
    """
    lpg = project_to_lpg(
        result_graph,
        collapse_types=True,
        collapse_literals=True,
        resolve_blanks=True,
        resolve_lists=True,
    )
    return projected_to_yfiles(lpg, layer=layer, label_fn=label_fn)
