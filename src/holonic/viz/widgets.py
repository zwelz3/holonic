"""yFiles Jupyter graph widgets for holonic visualization.

All widgets query the HolonicDataset via SPARQL and project through
the projections module before rendering.  No direct Python object
traversal — the dataset is the source of truth.

Classes
-------
HolonViz
    Visualize a single holon's layers with compartmented node labels,
    SHACL shape tables, and edge-reduced topology.

HolarchyViz
    Visualize the holarchy topology — collapsed (holons as nodes) or
    expanded (layers visible per holon).

SPARQLExplorer
    Interactive SPARQL CONSTRUCT explorer with projection presets,
    namespace management, and live graph rendering.
"""

from __future__ import annotations

from typing import Optional

from rdflib import Graph

from holonic.viz import styles
from holonic.viz.formatters import (
    format_compartmented,
    format_shacl_shape,
    format_simple,
    format_typed,
)
from holonic.viz.graph_builder import (
    LabelFormatter,
    holon_to_yfiles,
    holarchy_to_yfiles,
    sparql_result_to_yfiles,
)


# ── Built-in SPARQL projections for the explorer ──

PROJECTIONS: dict[str, dict] = {
    "Holarchy Structure": {
        "description": "Holons and their nesting/portal relationships.",
        "query": """
            PREFIX cga:  <urn:holonic:ontology:>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            CONSTRUCT {
                ?holon a cga:Holon ;
                    rdfs:label ?label ;
                    cga:memberOf ?parent .
                ?portal a cga:TransformPortal ;
                    cga:sourceHolon ?src ;
                    cga:targetHolon ?tgt ;
                    rdfs:label ?plabel .
            }
            WHERE {
                { ?holon a cga:Holon .
                  OPTIONAL { ?holon rdfs:label ?label }
                  OPTIONAL { ?holon cga:memberOf ?parent } }
                UNION
                { ?portal a cga:TransformPortal ;
                      cga:sourceHolon ?src ; cga:targetHolon ?tgt .
                  OPTIONAL { ?portal rdfs:label ?plabel } }
            }
        """,
    },
    "SHACL Shapes": {
        "description": "Boundary membrane: all SHACL shapes with property constraints.",
        "query": """
            PREFIX sh: <http://www.w3.org/ns/shacl#>
            CONSTRUCT {
                ?shape a sh:NodeShape ;
                    sh:targetClass ?cls ;
                    sh:property ?prop .
                ?prop sh:path ?path ;
                    sh:datatype ?dt ;
                    sh:minCount ?min ;
                    sh:maxCount ?max ;
                    sh:severity ?sev ;
                    sh:message ?msg .
            }
            WHERE {
                ?shape a sh:NodeShape .
                OPTIONAL { ?shape sh:targetClass ?cls }
                OPTIONAL {
                    ?shape sh:property ?prop .
                    ?prop sh:path ?path .
                    OPTIONAL { ?prop sh:datatype ?dt }
                    OPTIONAL { ?prop sh:minCount ?min }
                    OPTIONAL { ?prop sh:maxCount ?max }
                    OPTIONAL { ?prop sh:severity ?sev }
                    OPTIONAL { ?prop sh:message ?msg }
                }
            }
        """,
    },
    "Portal Network": {
        "description": "All portals with source and target holons.",
        "query": """
            PREFIX cga:  <urn:holonic:ontology:>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            CONSTRUCT {
                ?portal a cga:TransformPortal ;
                    rdfs:label ?label ;
                    cga:sourceHolon ?src ;
                    cga:targetHolon ?tgt .
            }
            WHERE {
                ?portal a cga:TransformPortal ;
                    cga:sourceHolon ?src ;
                    cga:targetHolon ?tgt .
                OPTIONAL { ?portal rdfs:label ?label }
            }
        """,
    },
    "Provenance Trail": {
        "description": "PROV-O activities: traversals, validations, agents.",
        "query": """
            PREFIX prov: <http://www.w3.org/ns/prov#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            CONSTRUCT {
                ?activity a prov:Activity ;
                    rdfs:label ?label ;
                    prov:wasAssociatedWith ?agent ;
                    prov:used ?input ;
                    prov:generated ?output .
                ?output prov:wasDerivedFrom ?source .
            }
            WHERE {
                ?activity a prov:Activity .
                OPTIONAL { ?activity rdfs:label ?label }
                OPTIONAL { ?activity prov:wasAssociatedWith ?agent }
                OPTIONAL { ?activity prov:used ?input }
                OPTIONAL { ?activity prov:generated ?output .
                           OPTIONAL { ?output prov:wasDerivedFrom ?source } }
            }
        """,
    },
    "Object Properties Only": {
        "description": "Topology: only IRI-to-IRI edges, no literals or types.",
        "query": """
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            CONSTRUCT { ?s ?p ?o }
            WHERE {
                ?s ?p ?o .
                FILTER(isIRI(?o))
                FILTER(?p != rdf:type)
            }
        """,
    },
    "External Bindings": {
        "description": "Projection layer: bindsTo and exactMatch links.",
        "query": """
            PREFIX cga:  <urn:holonic:ontology:>
            PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
            CONSTRUCT {
                ?holon cga:bindsTo ?ext .
                ?holon skos:exactMatch ?match .
            }
            WHERE {
                { ?holon cga:bindsTo ?ext }
                UNION
                { ?holon skos:exactMatch ?match }
            }
        """,
    },
}


# ── yFiles mapping functions ──

def _color_mapping(node: dict) -> str:
    props = node.get("properties", {})
    layer = props.get("layer", "default")
    if props.get("is_group"):
        return styles.color_for_layer_light(layer)
    return styles.color_for_layer(layer)


def _shape_mapping(node: dict) -> str:
    props = node.get("properties", {})
    if props.get("is_group"):
        return "round-rectangle"
    return styles.shape_for_layer(props.get("layer", "default"))


def _scale_mapping(node: dict) -> float:
    props = node.get("properties", {})
    if props.get("is_group"):
        return 1.0
    # Scale up nodes with many attributes
    attr_count = props.get("attr_count", 0)
    base = 0.8
    if attr_count > 5:
        base = 1.2
    elif attr_count > 2:
        base = 1.0
    return base


def _label_mapping(node: dict) -> str:
    return node.get("properties", {}).get("label", node.get("id", "?"))


def _parent_mapping(node: dict) -> Optional[str]:
    return node.get("properties", {}).get("parent", None)


def _edge_color_mapping(edge: dict) -> str:
    props = edge.get("properties", {})
    pred = props.get("predicate", "")
    return styles.edge_color(pred)


def _edge_label_mapping(edge: dict) -> str:
    return edge.get("properties", {}).get("label", "")


def _make_widget(nodes, edges, layout="hierarchic"):
    """Create and configure a yFiles GraphWidget."""
    from yfiles_jupyter_graphs import GraphWidget

    w = GraphWidget()
    w.nodes = nodes
    w.edges = edges

    w.set_node_color_mapping(_color_mapping)
    w.set_node_type_mapping(_shape_mapping)
    w.set_node_scale_factor_mapping(_scale_mapping)
    w.set_node_label_mapping(_label_mapping)
    w.set_node_parent_mapping(_parent_mapping)
    w.set_edge_color_mapping(_edge_color_mapping)
    w.set_edge_label_mapping(_edge_label_mapping)

    if layout == "hierarchic":
        w.hierarchic_layout()
    elif layout == "organic":
        w.organic_layout()
    elif layout == "circular":
        w.circular_layout()
    elif layout == "tree":
        w.tree_layout()

    return w


# ══════════════════════════════════════════════════════════════
# HolonViz
# ══════════════════════════════════════════════════════════════


class HolonViz:
    """Visualize a single holon's layers from a HolonicDataset.

    Projects each layer through project_to_lpg before rendering,
    collapsing types, literals, and blank nodes into compartmented
    node labels.  SHACL shapes get special tabular formatting.

    Parameters
    ----------
    ds :
        A HolonicDataset instance.
    holon_iri :
        IRI of the holon to visualize.
    layers :
        Which layers to show.  Default: all registered.
    layout :
        yFiles layout algorithm.
    label_fn :
        Node label formatter.  Default: compartmented.

    Usage::

        viz = HolonViz(ds, "urn:holon:my-data")
        viz.show()
    """

    def __init__(
        self,
        ds,
        holon_iri: str,
        *,
        layers: list[str] | None = None,
        layout: str = "hierarchic",
        label_fn: LabelFormatter = format_compartmented,
    ):
        self.ds = ds
        self.holon_iri = holon_iri
        self.layers = layers
        self.layout = layout
        self.label_fn = label_fn

    def _build(self, layers=None, layout=None):
        nodes, edges = holon_to_yfiles(
            self.ds,
            self.holon_iri,
            layers=layers or self.layers,
            label_fn=self.label_fn,
        )
        return _make_widget(nodes, edges, layout=layout or self.layout)

    def show(self, **kwargs):
        """Display the holon graph in the notebook."""
        return self._build(**kwargs)

    def show_with_controls(self):
        """Display with interactive layer/layout controls."""
        import ipywidgets as widgets
        from IPython.display import display

        layer_checks = widgets.SelectMultiple(
            options=["interior", "boundary", "projection", "context"],
            value=list(self.layers or ["interior", "boundary"]),
            description="Layers:",
            rows=4,
        )

        layout_dropdown = widgets.Dropdown(
            options=["hierarchic", "organic", "circular", "tree"],
            value=self.layout,
            description="Layout:",
        )

        label_dropdown = widgets.Dropdown(
            options=[
                ("Compartmented", "compartmented"),
                ("Typed", "typed"),
                ("Simple", "simple"),
            ],
            value="compartmented",
            description="Labels:",
        )

        output = widgets.Output()

        label_fns = {
            "compartmented": format_compartmented,
            "typed": format_typed,
            "simple": format_simple,
        }

        def on_change(_):
            with output:
                output.clear_output(wait=True)
                self.label_fn = label_fns[label_dropdown.value]
                w = self._build(
                    layers=list(layer_checks.value),
                    layout=layout_dropdown.value,
                )
                display(w)

        layer_checks.observe(on_change, names="value")
        layout_dropdown.observe(on_change, names="value")
        label_dropdown.observe(on_change, names="value")

        controls = widgets.HBox([layer_checks, layout_dropdown, label_dropdown])
        display(controls)

        with output:
            w = self._build()
            display(w)
        display(output)


# ══════════════════════════════════════════════════════════════
# HolarchyViz
# ══════════════════════════════════════════════════════════════


class HolarchyViz:
    """Visualize a holarchy: holons as nodes connected by portals.

    Two modes:
      - **Collapsed:** Holons are single nodes, portals are edges.
        Uses project_holarchy() for clean topology view.
      - **Expanded:** Each holon opens to show its layer groups
        with projected, edge-reduced content.

    Parameters
    ----------
    ds :
        A HolonicDataset instance.
    show_internals :
        If True, expand holons to show layers.  Default: False.
    layers :
        When expanded, which layers to show.
    layout :
        yFiles layout algorithm.

    Usage::

        viz = HolarchyViz(ds)
        viz.show()  # collapsed
        viz.show(show_internals=True)  # expanded
    """

    def __init__(
        self,
        ds,
        *,
        show_internals: bool = False,
        layers: list[str] | None = None,
        layout: str = "hierarchic",
    ):
        self.ds = ds
        self.show_internals = show_internals
        self.layers = layers
        self.layout = layout

    def _build(self, show_internals=None, layers=None, layout=None):
        si = show_internals if show_internals is not None else self.show_internals
        nodes, edges = holarchy_to_yfiles(
            self.ds,
            show_internals=si,
            layers=layers or self.layers,
        )
        return _make_widget(nodes, edges, layout=layout or self.layout)

    def show(self, **kwargs):
        return self._build(**kwargs)

    def show_with_controls(self):
        import ipywidgets as widgets
        from IPython.display import display

        internals_toggle = widgets.ToggleButton(
            value=self.show_internals,
            description="Expand Holons",
        )

        layer_checks = widgets.SelectMultiple(
            options=["interior", "boundary", "projection", "context"],
            value=list(self.layers or ["interior", "boundary"]),
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


# ══════════════════════════════════════════════════════════════
# SPARQLExplorer
# ══════════════════════════════════════════════════════════════


class SPARQLExplorer:
    """Interactive SPARQL CONSTRUCT explorer linked to graph visualization.

    Executes CONSTRUCT queries against the HolonicDataset and renders
    results through the projections module — types collapsed, literals
    inlined, blank nodes resolved — before visualization.

    Includes:
      - Namespace manager (auto-generates PREFIX declarations)
      - Built-in projection presets (dropdown)
      - Editable query textarea
      - Live graph update on execution
      - Label format selector

    Parameters
    ----------
    ds :
        A HolonicDataset instance.
    namespaces :
        Additional namespace prefix → IRI mappings.
    layout :
        Default layout algorithm.

    Usage::

        explorer = SPARQLExplorer(ds, namespaces={"eng": "urn:eng:"})
        explorer.show()
    """

    DEFAULT_NAMESPACES = {
        "rdf":  "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "xsd":  "http://www.w3.org/2001/XMLSchema#",
        "owl":  "http://www.w3.org/2002/07/owl#",
        "sh":   "http://www.w3.org/ns/shacl#",
        "cga":  "urn:holonic:ontology:",
        "prov": "http://www.w3.org/ns/prov#",
        "skos": "http://www.w3.org/2004/02/skos/core#",
        "dct":  "http://purl.org/dc/terms/",
    }

    def __init__(
        self,
        ds,
        namespaces: dict[str, str] | None = None,
        layout: str = "hierarchic",
    ):
        self.ds = ds
        self.namespaces = {**self.DEFAULT_NAMESPACES}
        if namespaces:
            self.namespaces.update(namespaces)
        self.layout = layout
        self._last_result: Graph | None = None

    def _prefix_block(self) -> str:
        return "\n".join(
            f"PREFIX {pfx}: <{iri}>"
            for pfx, iri in sorted(self.namespaces.items())
        )

    def execute(self, query: str) -> Graph:
        """Execute a SPARQL CONSTRUCT against the dataset."""
        result = self.ds.construct(query)
        self._last_result = result
        return result

    def visualize_result(
        self,
        result: Graph,
        layout: str | None = None,
        label_fn: LabelFormatter = format_compartmented,
    ):
        """Convert CONSTRUCT result to a yFiles widget via projections."""
        nodes, edges = sparql_result_to_yfiles(result, label_fn=label_fn)
        return _make_widget(nodes, edges, layout=layout or self.layout)

    def show(self):
        """Display the interactive explorer."""
        import ipywidgets as widgets
        from IPython.display import display

        # Namespace display
        ns_html = "<br>".join(
            f"<code>{pfx}:</code> "
            f"<span style='color:#888'>&lt;{iri}&gt;</span>"
            for pfx, iri in sorted(self.namespaces.items())
        )
        ns_widget = widgets.HTML(
            value=(
                f"<details><summary><b>Namespaces</b></summary>"
                f"<div style='font-size:12px; padding:4px'>{ns_html}</div>"
                f"</details>"
            ),
        )

        # Preset dropdown
        preset_names = ["(custom query)"] + list(PROJECTIONS.keys())
        preset_dropdown = widgets.Dropdown(
            options=preset_names,
            value="(custom query)",
            description="Preset:",
            style={"description_width": "60px"},
            layout=widgets.Layout(width="300px"),
        )

        desc_label = widgets.HTML(
            value="<i>Write a SPARQL CONSTRUCT query below.</i>"
        )

        # Query textarea
        default_query = (
            self._prefix_block() + "\n\n"
            + PROJECTIONS["Holarchy Structure"]["query"]
        )
        query_area = widgets.Textarea(
            value=default_query,
            layout=widgets.Layout(width="100%", height="260px"),
        )
        query_area.add_class("monospace-textarea")

        # Layout dropdown
        layout_dropdown = widgets.Dropdown(
            options=["hierarchic", "organic", "circular", "tree"],
            value=self.layout,
            description="Layout:",
            style={"description_width": "60px"},
            layout=widgets.Layout(width="200px"),
        )

        # Label format
        label_dropdown = widgets.Dropdown(
            options=[
                ("Compartmented", "compartmented"),
                ("Typed", "typed"),
                ("Simple", "simple"),
            ],
            value="compartmented",
            description="Labels:",
            style={"description_width": "60px"},
            layout=widgets.Layout(width="200px"),
        )

        exec_button = widgets.Button(
            description="Execute CONSTRUCT",
            button_style="primary",
            icon="play",
        )

        status = widgets.HTML(value="")
        graph_output = widgets.Output()

        label_fns = {
            "compartmented": format_compartmented,
            "typed": format_typed,
            "simple": format_simple,
        }

        def on_preset_change(change):
            name = change["new"]
            if name != "(custom query)":
                q = PROJECTIONS[name]["query"]
                query_area.value = self._prefix_block() + "\n\n" + q
                desc_label.value = f"<i>{PROJECTIONS[name]['description']}</i>"
            else:
                desc_label.value = (
                    "<i>Write a SPARQL CONSTRUCT query below.</i>"
                )

        def on_execute(_):
            status.value = "<i style='color:#888'>Executing...</i>"
            try:
                result = self.execute(query_area.value)
                count = len(result)
                status.value = (
                    f"<span style='color:green'>✓ {count} triples</span>"
                )
                with graph_output:
                    graph_output.clear_output(wait=True)
                    if count > 0:
                        fn = label_fns[label_dropdown.value]
                        w = self.visualize_result(
                            result,
                            layout=layout_dropdown.value,
                            label_fn=fn,
                        )
                        display(w)
                    else:
                        display(widgets.HTML(
                            "<div style='padding:20px; color:#888'>"
                            "No results.</div>"
                        ))
            except Exception as e:
                status.value = (
                    f"<span style='color:red'>✗ {e}</span>"
                )

        preset_dropdown.observe(on_preset_change, names="value")
        exec_button.on_click(on_execute)

        header = widgets.HBox([
            preset_dropdown, layout_dropdown, label_dropdown, exec_button
        ])
        display(widgets.VBox([
            ns_widget, header, desc_label, query_area, status, graph_output,
        ]))
        display(widgets.HTML("""
            <style>
                .monospace-textarea textarea {
                    font-family: 'Fira Code', 'Consolas', monospace !important;
                    font-size: 13px !important;
                    line-height: 1.4 !important;
                }
            </style>
        """))
