"""Provenance visualization for holonic audit trails.

Renders the flow of information through holons as a directed graph
with membrane health badges, surface reports, agent attribution,
and temporal ordering.  Designed for automated traversal auditing.

The visualization shows:
  - Holon nodes with membrane health status (color-coded)
  - Portal edges with agent, timestamp, and portal label
  - Surface reports (boundary contract summaries) on hover
  - Derivation chains connecting the full pipeline

Classes
-------
ProvenanceViz
    yFiles widget for interactive provenance exploration.
"""

from __future__ import annotations

from holonic.model import AuditTrail

# ── Health → color mapping ──

HEALTH_COLORS = {
    "INTACT": "#22c55e",  # green
    "WEAKENED": "#f59e0b",  # amber
    "COMPROMISED": "#ef4444",  # red
}

HEALTH_ICONS = {
    "INTACT": "✓",
    "WEAKENED": "⚠",
    "COMPROMISED": "✗",
}

HEALTH_COLORS_LIGHT = {
    "INTACT": "#dcfce7",
    "WEAKENED": "#fef3c7",
    "COMPROMISED": "#fee2e2",
}


# ══════════════════════════════════════════════════════════════
# Graph builder
# ══════════════════════════════════════════════════════════════


def audit_trail_to_yfiles(
    audit: AuditTrail,
    *,
    show_surface: bool = True,
    show_agents: bool = True,
) -> tuple[list[dict], list[dict]]:
    """Convert an AuditTrail into yFiles node/edge lists.

    Nodes represent holons that participated in traversals.
    Edges represent portal traversal hops.

    Each node is annotated with:
      - Membrane health status (color + icon)
      - Surface report (boundary contract summary)
      - Triple count (if available)

    Each edge is annotated with:
      - Portal label
      - Agent
      - Timestamp
    """
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    # ── Build nodes for all participating holons ──
    for holon_iri in audit.participating_holons:
        label_parts = []
        holon_label = holon_iri.rsplit(":", 1)[-1]

        # Membrane health
        validation = audit.validation_for(holon_iri)
        if validation:
            health = validation.health_label
            icon = HEALTH_ICONS.get(health, "?")
            label_parts.append(f"{icon} {health}")
        else:
            health = "UNKNOWN"
            label_parts.append("· no validation")

        label_parts.insert(0, holon_label)

        # Surface report
        surface = audit.surfaces.get(holon_iri)
        if surface and show_surface:
            label_parts.append("─" * max(len(holon_label), 14))
            if surface.target_classes:
                classes = ", ".join(
                    c.rsplit(":", 1)[-1].rsplit("/", 1)[-1] for c in surface.target_classes[:3]
                )
                label_parts.append(f"accepts: {classes}")
            if surface.required_fields:
                req = ", ".join(surface.required_fields[:6])
                more = (
                    f" +{len(surface.required_fields) - 6}"
                    if len(surface.required_fields) > 6
                    else ""
                )
                label_parts.append(f"required: {req}{more}")
            if surface.optional_fields:
                opt = ", ".join(surface.optional_fields[:4])
                more = (
                    f" +{len(surface.optional_fields) - 4}"
                    if len(surface.optional_fields) > 4
                    else ""
                )
                label_parts.append(f"optional: {opt}{more}")

        node_label = "\n".join(label_parts)

        nodes[holon_iri] = {
            "id": holon_iri,
            "properties": {
                "label": node_label,
                "holon_iri": holon_iri,
                "layer": "provenance",
                "health": health,
                "type": "audit_node",
                "is_group": False,
                "has_surface": surface is not None,
                "has_validation": validation is not None,
            },
        }

    # ── Build edges for traversals ──
    for i, traversal in enumerate(audit.traversals):
        edge_label_parts = []

        if traversal.portal_label:
            portal_short = traversal.portal_label
            if "Portal traversal via " in portal_short:
                portal_short = portal_short.replace("Portal traversal via ", "").rsplit(":", 1)[-1]
            edge_label_parts.append(portal_short)

        if show_agents and traversal.agent_iri:
            agent_short = traversal.agent_iri.rsplit(":", 1)[-1]
            edge_label_parts.append(f"agent: {agent_short}")

        if traversal.timestamp:
            ts_short = str(traversal.timestamp)[:19].replace("T", " ")
            edge_label_parts.append(ts_short)

        edges.append(
            {
                "id": f"traversal_{i}",
                "start": traversal.source_iri,
                "end": traversal.target_iri,
                "properties": {
                    "label": "\n".join(edge_label_parts),
                    "activity_iri": traversal.activity_iri,
                    "portal_label": traversal.portal_label or "",
                    "agent": traversal.agent_iri or "",
                    "timestamp": traversal.timestamp or "",
                    "layer": "provenance",
                    "hop_number": i + 1,
                },
            }
        )

    return list(nodes.values()), edges


# ══════════════════════════════════════════════════════════════
# yFiles mapping functions (provenance-specific)
# ══════════════════════════════════════════════════════════════


def _prov_color_mapping(node: dict) -> str:
    """Color node by membrane health status."""
    props = node.get("properties", {})
    health = props.get("health", "UNKNOWN")
    return HEALTH_COLORS.get(health, "#94a3b8")


def _prov_shape_mapping(node: dict) -> str:
    props = node.get("properties", {})
    health = props.get("health", "UNKNOWN")
    if health == "COMPROMISED":
        return "octagon"
    if health == "WEAKENED":
        return "hexagon"
    return "round-rectangle"


def _prov_scale_mapping(node: dict) -> float:
    props = node.get("properties", {})
    if props.get("has_surface"):
        return 1.3
    return 1.0


def _prov_label_mapping(node: dict) -> str:
    return node.get("properties", {}).get("label", "?")


def _prov_edge_color_mapping(edge: dict) -> str:
    return "#6366f1"  # indigo-500 for all traversal edges


def _prov_edge_label_mapping(edge: dict) -> str:
    return edge.get("properties", {}).get("label", "")


def _prov_edge_thickness_mapping(edge: dict) -> float:
    """Thicker edges for earlier hops (pipeline entry point)."""
    hop = edge.get("properties", {}).get("hop_number", 1)
    return max(1.0, 3.0 - (hop - 1) * 0.5)


def _make_provenance_widget(nodes, edges, layout="hierarchic"):
    """Create a yFiles widget with provenance-specific styling."""
    from yfiles_jupyter_graphs import GraphWidget

    w = GraphWidget()
    w.nodes = nodes
    w.edges = edges

    w.set_node_color_mapping(_prov_color_mapping)
    w.set_node_type_mapping(_prov_shape_mapping)
    w.set_node_scale_factor_mapping(_prov_scale_mapping)
    w.set_node_label_mapping(_prov_label_mapping)
    w.set_edge_color_mapping(_prov_edge_color_mapping)
    w.set_edge_label_mapping(_prov_edge_label_mapping)

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
# ProvenanceViz widget
# ══════════════════════════════════════════════════════════════


class ProvenanceViz:
    """Interactive provenance audit trail visualization.

    Shows the flow of information through holons as a directed graph
    with membrane health badges, surface reports, and temporal ordering.

    Parameters
    ----------
    ds :
        A HolonicDataset instance.
    layout :
        yFiles layout algorithm.  Default: hierarchic (best for
        pipelines — left-to-right flow).
    show_surface :
        If True, nodes display boundary contract summaries.
    show_agents :
        If True, edges display agent attribution.

    Usage::

        prov_viz = ProvenanceViz(ds)
        prov_viz.show()

        # Or with interactive controls:
        prov_viz.show_with_controls()

        # Access the underlying audit trail:
        audit = prov_viz.audit
        print(audit.summary())
    """

    def __init__(
        self,
        ds,
        *,
        layout: str = "hierarchic",
        show_surface: bool = True,
        show_agents: bool = True,
    ):
        self.ds = ds
        self.layout = layout
        self.show_surface = show_surface
        self.show_agents = show_agents
        self._audit: AuditTrail | None = None

    @property
    def audit(self) -> AuditTrail:
        """The collected audit trail (lazy-loaded)."""
        if self._audit is None:
            self._audit = self.ds.collect_audit_trail()
        return self._audit

    def refresh(self) -> None:
        """Re-collect the audit trail from the dataset."""
        self._audit = self.ds.collect_audit_trail()

    def _build(self, show_surface=None, show_agents=None, layout=None):
        nodes, edges = audit_trail_to_yfiles(
            self.audit,
            show_surface=show_surface if show_surface is not None else self.show_surface,
            show_agents=show_agents if show_agents is not None else self.show_agents,
        )
        return _make_provenance_widget(nodes, edges, layout=layout or self.layout)

    def show(self, **kwargs):
        """Display the provenance graph in the notebook."""
        return self._build(**kwargs)

    def show_with_controls(self):
        """Display with interactive controls."""
        import ipywidgets as widgets
        from IPython.display import display

        surface_toggle = widgets.ToggleButton(
            value=self.show_surface,
            description="Surface Reports",
            tooltip="Show boundary contract summaries on nodes",
        )

        agent_toggle = widgets.ToggleButton(
            value=self.show_agents,
            description="Show Agents",
            tooltip="Show agent attribution on edges",
        )

        layout_dropdown = widgets.Dropdown(
            options=["hierarchic", "organic", "circular", "tree"],
            value=self.layout,
            description="Layout:",
        )

        refresh_button = widgets.Button(
            description="Refresh",
            button_style="warning",
            icon="refresh",
            tooltip="Re-collect audit trail from dataset",
        )

        summary_output = widgets.Output()
        graph_output = widgets.Output()

        def on_change(_):
            with graph_output:
                graph_output.clear_output(wait=True)
                w = self._build(
                    show_surface=surface_toggle.value,
                    show_agents=agent_toggle.value,
                    layout=layout_dropdown.value,
                )
                display(w)

        def on_refresh(_):
            self.refresh()
            with summary_output:
                summary_output.clear_output(wait=True)
                print(self.audit.summary())
            on_change(None)

        surface_toggle.observe(on_change, names="value")
        agent_toggle.observe(on_change, names="value")
        layout_dropdown.observe(on_change, names="value")
        refresh_button.on_click(on_refresh)

        controls = widgets.HBox([surface_toggle, agent_toggle, layout_dropdown, refresh_button])
        display(controls)

        with summary_output:
            print(self.audit.summary())
        display(summary_output)

        with graph_output:
            w = self._build()
            display(w)
        display(graph_output)

    def print_report(self) -> None:
        """Print a text-based audit report (no yFiles required)."""
        a = self.audit
        print(a.summary())
        print()

        # Detailed traversal report
        for i, t in enumerate(a.traversals):
            print(f"  Hop {i + 1}: {t.source_label} → {t.target_label}")
            if t.portal_label:
                print(f"    Portal:    {t.portal_label}")
            if t.agent_iri:
                print(f"    Agent:     {t.agent_iri.rsplit(':', 1)[-1]}")
            if t.timestamp:
                print(f"    Timestamp: {str(t.timestamp)[:19]}")

            # Target validation
            v = a.validation_for(t.target_iri)
            if v:
                icon = HEALTH_ICONS.get(v.health_label, "?")
                print(f"    Membrane:  {icon} {v.health_label}")

            # Target surface
            s = a.surfaces.get(t.target_iri)
            if s:
                print(
                    f"    Surface:   {len(s.required_fields)} required, "
                    f"{len(s.optional_fields)} optional"
                )
                if s.target_classes:
                    classes = ", ".join(c.rsplit(":", 1)[-1] for c in s.target_classes)
                    print(f"    Accepts:   {classes}")
            print()
