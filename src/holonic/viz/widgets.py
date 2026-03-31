"""
widgets.py — yFiles Jupyter graph widgets for holonic visualisation.

Classes
-------
HolonViz
    Visualise a single holon's four named graphs with layer grouping,
    colour coding, and selectable layer visibility.

HolarchyViz
    Visualise a full holarchy with nested holon groups, portal edges,
    and optional interior expansion.

SPARQLExplorer
    Interactive SPARQL query widget linked to a graph visualisation.
    Includes a namespace manager, built-in projection presets, and
    live CONSTRUCT execution against a local rdflib graph.
"""

from __future__ import annotations

from typing import Optional, Union

from rdflib import Graph

from ..holon import Holon
from ..holarchy import Holarchy
from . import styles
from .graph_builder import (
    holon_to_graph_data,
    holarchy_to_graph_data,
    sparql_construct_to_graph_data,
)
from .projections import PROJECTIONS, get_projection_names


# ------------------------------------------------------------------
# Mapping functions for yFiles GraphWidget
# ------------------------------------------------------------------

def _color_mapping(node: dict) -> str:
    """Map node to colour based on its layer property."""
    props = node.get("properties", {})
    layer = props.get("layer", "default")
    if props.get("is_group"):
        return styles.color_for_layer_light(layer)
    return styles.color_for_layer(layer)


def _shape_mapping(node: dict) -> str:
    """Map node to shape based on its layer property."""
    props = node.get("properties", {})
    if props.get("is_group"):
        return "round-rectangle"
    return styles.shape_for_layer(props.get("type", "default"))


def _scale_mapping(node: dict) -> float:
    """Map node to scale based on its layer property."""
    props = node.get("properties", {})
    if props.get("is_group"):
        return 1.0
    return styles.scale_for_layer(props.get("type", "default"))


def _label_mapping(node: dict) -> str:
    """Map node to its label string."""
    return node.get("properties", {}).get("label", node.get("id", "?"))


def _parent_mapping(node: dict) -> Optional[str]:
    """Map node to its parent group node ID."""
    return node.get("properties", {}).get("parent", None)


def _edge_color_mapping(edge: dict) -> str:
    """Map edge to colour based on predicate."""
    props = edge.get("properties", {})
    layer = props.get("layer", "default")
    if layer == "portal":
        return styles.EDGE_COLORS.get("cga:hasPortal", "#ef4444")
    pred = props.get("predicate", "")
    for key, color in styles.EDGE_COLORS.items():
        if key in pred:
            return color
    return styles.EDGE_COLORS["default"]


def _edge_label_mapping(edge: dict) -> str:
    """Map edge to its label."""
    return edge.get("properties", {}).get("label", "")


# ------------------------------------------------------------------
# Widget factory
# ------------------------------------------------------------------

def _make_widget(nodes, edges, layout="hierarchic", title=""):
    """
    Create and configure a yFiles GraphWidget.

    Returns the widget instance.  The caller should call ``.show()``
    or display it in a notebook cell.
    """
    from yfiles_jupyter_graphs import GraphWidget

    w = GraphWidget()
    w.nodes = nodes
    w.edges = edges

    # Apply holonic styling
    w.set_node_color_mapping(_color_mapping)
    w.set_node_type_mapping(_shape_mapping)
    w.set_node_scale_factor_mapping(_scale_mapping)
    w.set_node_label_mapping(_label_mapping)
    w.set_node_parent_mapping(_parent_mapping)
    w.set_edge_color_mapping(_edge_color_mapping)
    w.set_edge_label_mapping(_edge_label_mapping)

    # Layout
    if layout == "hierarchic":
        w.hierarchic_layout()
    elif layout == "organic":
        w.organic_layout()
    elif layout == "circular":
        w.circular_layout()
    elif layout == "tree":
        w.tree_layout()

    return w


# ==================================================================
# HolonViz — single holon visualisation
# ==================================================================

class HolonViz:
    """
    Visualise a single holon's four named graphs.

    Parameters
    ----------
    holon : Holon
        The holon to visualise.
    layers : list[str], optional
        Which layers to show.  Default: all four.
    layout : str
        yFiles layout algorithm.  "hierarchic", "organic", "circular", "tree".
    show_groups : bool
        If True, group nodes by layer (nested rectangles).

    Usage::

        viz = HolonViz(my_holon, layers=["interior", "boundary"])
        viz.show()

        # Or with ipywidgets controls:
        viz.show_with_controls()
    """

    def __init__(
        self,
        holon: Holon,
        layers: Optional[list[str]] = None,
        layout: str = "hierarchic",
        show_groups: bool = True,
    ):
        self.holon = holon
        self.layers = layers or ["interior", "boundary", "projection", "context"]
        self.layout = layout
        self.show_groups = show_groups

    def _build(self, layers=None):
        layers = layers or self.layers
        nodes, edges = holon_to_graph_data(
            self.holon,
            layers=layers,
            show_group_nodes=self.show_groups,
        )
        return _make_widget(nodes, edges, layout=self.layout)

    def show(self, layers=None):
        """Display the holon graph in the notebook."""
        w = self._build(layers)
        return w

    def show_with_controls(self):
        """Display the holon graph with ipywidgets layer toggle controls."""
        import ipywidgets as widgets
        from IPython.display import display

        layer_checks = widgets.SelectMultiple(
            options=["interior", "boundary", "projection", "context"],
            value=self.layers,
            description="Layers:",
            rows=4,
        )

        layout_dropdown = widgets.Dropdown(
            options=["hierarchic", "organic", "circular", "tree"],
            value=self.layout,
            description="Layout:",
        )

        output = widgets.Output()

        def on_change(_):
            with output:
                output.clear_output(wait=True)
                self.layout = layout_dropdown.value
                w = self._build(layers=list(layer_checks.value))
                display(w)

        layer_checks.observe(on_change, names="value")
        layout_dropdown.observe(on_change, names="value")

        controls = widgets.HBox([layer_checks, layout_dropdown])
        display(controls)

        with output:
            w = self._build()
            display(w)
        display(output)


# ==================================================================
# HolarchyViz — full holarchy visualisation
# ==================================================================

class HolarchyViz:
    """
    Visualise a holarchy: nested holons with portals as edges.

    Parameters
    ----------
    holarchy : Holarchy
        The holarchy to visualise.
    show_internals : bool
        If True, expand each holon to show its interior triples.
        If False, show holons as single nodes connected by portals.
    layers : list[str], optional
        When ``show_internals=True``, which layers to display per holon.
    layout : str
        yFiles layout algorithm.

    Usage::

        viz = HolarchyViz(my_holarchy, show_internals=False)
        viz.show()
    """

    def __init__(
        self,
        holarchy: Holarchy,
        show_internals: bool = False,
        layers: Optional[list[str]] = None,
        layout: str = "hierarchic",
    ):
        self.holarchy = holarchy
        self.show_internals = show_internals
        self.layers = layers
        self.layout = layout

    def _build(self, show_internals=None, layers=None, layout=None):
        show_int = show_internals if show_internals is not None else self.show_internals
        nodes, edges = holarchy_to_graph_data(
            self.holarchy,
            layers=layers or self.layers,
            show_internals=show_int,
            show_portals=True,
        )
        return _make_widget(nodes, edges, layout=layout or self.layout)

    def show(self, **kwargs):
        """Display the holarchy graph in the notebook."""
        return self._build(**kwargs)

    def show_with_controls(self):
        """Display with interactive controls for layers and expansion."""
        import ipywidgets as widgets
        from IPython.display import display

        internals_toggle = widgets.ToggleButton(
            value=self.show_internals,
            description="Show Internals",
        )

        layer_checks = widgets.SelectMultiple(
            options=["interior", "boundary", "projection", "context"],
            value=["interior", "boundary"],
            description="Layers:",
            rows=4,
        )

        layout_dropdown = widgets.Dropdown(
            options=["hierarchic", "organic", "circular", "tree"],
            value=self.layout,
            description="Layout:",
        )

        output = widgets.Output()

        def on_change(_):
            with output:
                output.clear_output(wait=True)
                w = self._build(
                    show_internals=internals_toggle.value,
                    layers=list(layer_checks.value),
                    layout=layout_dropdown.value,
                )
                display(w)

        internals_toggle.observe(on_change, names="value")
        layer_checks.observe(on_change, names="value")
        layout_dropdown.observe(on_change, names="value")

        controls = widgets.HBox([internals_toggle, layer_checks, layout_dropdown])
        display(controls)

        with output:
            w = self._build()
            display(w)
        display(output)


# ==================================================================
# SPARQLExplorer — SPARQL query widget linked to graph viz
# ==================================================================

class SPARQLExplorer:
    """
    Interactive SPARQL CONSTRUCT explorer linked to a yFiles graph widget.

    Executes SPARQL CONSTRUCT queries against a local rdflib Graph and
    visualises the results.  Includes:
      - Namespace manager (auto-generates PREFIX declarations)
      - Built-in projection presets (dropdown)
      - Editable query textarea
      - Live graph update on execution

    Parameters
    ----------
    graph : rdflib.Graph
        The graph to query against.
    namespaces : dict[str, str], optional
        Namespace prefix → IRI mapping for auto-PREFIX generation.
    layout : str
        Default layout algorithm.

    Usage::

        explorer = SPARQLExplorer(
            graph=my_holarchy.merged_all(),
            namespaces={"cga": "urn:cga:", "eng": "urn:eng:"},
        )
        explorer.show()
    """

    DEFAULT_NAMESPACES = {
        "rdf":  "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "xsd":  "http://www.w3.org/2001/XMLSchema#",
        "owl":  "http://www.w3.org/2002/07/owl#",
        "sh":   "http://www.w3.org/ns/shacl#",
        "cga":  "urn:cga:",
        "prov": "http://www.w3.org/ns/prov#",
        "skos": "http://www.w3.org/2004/02/skos/core#",
        "dct":  "http://purl.org/dc/terms/",
    }

    def __init__(
        self,
        graph: Graph,
        namespaces: Optional[dict[str, str]] = None,
        layout: str = "hierarchic",
    ):
        self.graph = graph
        self.namespaces = {**self.DEFAULT_NAMESPACES}
        if namespaces:
            self.namespaces.update(namespaces)
        self.layout = layout
        self._last_result: Optional[Graph] = None

    def _prefix_block(self) -> str:
        """Generate PREFIX declarations from the namespace manager."""
        return "\n".join(
            f"PREFIX {pfx}: <{iri}>"
            for pfx, iri in sorted(self.namespaces.items())
        )

    def execute(self, query: str) -> Graph:
        """Execute a SPARQL CONSTRUCT and return the result graph."""
        result = Graph()
        for t in self.graph.query(query):
            result.add(t)
        self._last_result = result
        return result

    def visualise_result(self, result: Graph, layout: Optional[str] = None):
        """Convert a CONSTRUCT result to a yFiles widget."""
        nodes, edges = sparql_construct_to_graph_data(result)
        return _make_widget(nodes, edges, layout=layout or self.layout)

    def show(self):
        """Display the full interactive SPARQL explorer."""
        import ipywidgets as widgets
        from IPython.display import display

        # Namespace display
        ns_html = "<br>".join(
            f"<code>{pfx}:</code> <span style='color:#888'>&lt;{iri}&gt;</span>"
            for pfx, iri in sorted(self.namespaces.items())
        )
        ns_widget = widgets.HTML(
            value=f"<details><summary><b>Namespaces</b></summary>"
                  f"<div style='font-size:12px; padding:4px'>{ns_html}</div>"
                  f"</details>",
        )

        # Projection preset dropdown
        preset_names = ["(custom query)"] + get_projection_names()
        preset_dropdown = widgets.Dropdown(
            options=preset_names,
            value="(custom query)",
            description="Preset:",
            style={"description_width": "60px"},
            layout=widgets.Layout(width="300px"),
        )

        # Description label
        desc_label = widgets.HTML(value="<i>Write a SPARQL CONSTRUCT query below.</i>")

        # Query textarea
        default_query = self._prefix_block() + "\n\n" + PROJECTIONS["All Triples"]["query"]
        query_area = widgets.Textarea(
            value=default_query,
            description="",
            layout=widgets.Layout(width="100%", height="260px"),
            style={"font_family": "monospace"},
        )
        # Add monospace styling
        query_area.add_class("monospace-textarea")

        # Layout dropdown
        layout_dropdown = widgets.Dropdown(
            options=["hierarchic", "organic", "circular", "tree"],
            value=self.layout,
            description="Layout:",
            style={"description_width": "60px"},
            layout=widgets.Layout(width="200px"),
        )

        # Execute button
        exec_button = widgets.Button(
            description="Execute CONSTRUCT",
            button_style="primary",
            icon="play",
        )

        # Status label
        status = widgets.HTML(value="")

        # Graph output
        graph_output = widgets.Output()

        def on_preset_change(change):
            name = change["new"]
            if name != "(custom query)":
                q = PROJECTIONS[name]["query"]
                query_area.value = self._prefix_block() + "\n\n" + q
                desc_label.value = f"<i>{PROJECTIONS[name]['description']}</i>"
            else:
                desc_label.value = "<i>Write a SPARQL CONSTRUCT query below.</i>"

        def on_execute(_):
            status.value = "<i style='color:#888'>Executing...</i>"
            try:
                result = self.execute(query_area.value)
                count = len(result)
                status.value = (
                    f"<span style='color:green'>✓ {count} triples returned</span>"
                )
                with graph_output:
                    graph_output.clear_output(wait=True)
                    if count > 0:
                        w = self.visualise_result(result, layout=layout_dropdown.value)
                        display(w)
                    else:
                        display(widgets.HTML(
                            "<div style='padding:20px; color:#888'>"
                            "No results. Check your query or try a different preset."
                            "</div>"
                        ))
            except Exception as e:
                status.value = f"<span style='color:red'>✗ Error: {e}</span>"

        preset_dropdown.observe(on_preset_change, names="value")
        exec_button.on_click(on_execute)

        # Layout the UI
        header = widgets.HBox([preset_dropdown, layout_dropdown, exec_button])
        display(widgets.VBox([
            ns_widget,
            header,
            desc_label,
            query_area,
            status,
            graph_output,
        ]))

        # Inject CSS for monospace textarea
        display(widgets.HTML("""
            <style>
                .monospace-textarea textarea {
                    font-family: 'Fira Code', 'Source Code Pro', 'Consolas', monospace !important;
                    font-size: 13px !important;
                    line-height: 1.4 !important;
                    tab-size: 4;
                }
            </style>
        """))
