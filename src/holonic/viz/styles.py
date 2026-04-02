"""Visual constants for holonic graph visualization.

Colour palette follows the cell-membrane metaphor:
  Interior   = blue   (the cytoplasm)
  Boundary   = purple (the membrane)
  Projection = green  (the surface proteins)
  Context    = amber  (the tissue/environment)
  Portal     = red    (traversal channel)
  Holon      = grey   (group container)
"""

# ── Layer colours ──

LAYER_COLORS = {
    "interior": "#3b82f6",
    "boundary": "#a855f7",
    "projection": "#22c55e",
    "context": "#f59e0b",
    "portal": "#ef4444",
    "holon": "#6b7280",
    "alignment": "#06b6d4",
    "literal": "#94a3b8",
    "default": "#64748b",
}

LAYER_COLORS_LIGHT = {
    "interior": "#dbeafe",
    "boundary": "#f3e8ff",
    "projection": "#dcfce7",
    "context": "#fef3c7",
    "portal": "#fee2e2",
    "holon": "#f3f4f6",
    "alignment": "#cffafe",
}

# ── Node shapes ──

LAYER_SHAPES = {
    "interior": "round-rectangle",
    "boundary": "hexagon",
    "projection": "pill",
    "context": "octagon",
    "portal": "diamond",
    "holon": "round-rectangle",
    "shape": "hexagon",
    "literal": "ellipse",
    "default": "rectangle",
}

# ── Edge colours by semantic role ──

EDGE_COLORS = {
    "portal": "#ef4444",
    "membership": "#f59e0b",
    "type_hierarchy": "#7c3aed",
    "provenance": "#06b6d4",
    "realization": "#22c55e",
    "default": "#94a3b8",
}


def color_for_layer(layer: str) -> str:
    return LAYER_COLORS.get(layer, LAYER_COLORS["default"])


def color_for_layer_light(layer: str) -> str:
    return LAYER_COLORS_LIGHT.get(layer, "#f8fafc")


def shape_for_layer(layer: str) -> str:
    return LAYER_SHAPES.get(layer, LAYER_SHAPES["default"])


def shorten_uri(uri: str, max_len: int = 40) -> str:
    """Produce a readable short form of a URI."""
    for sep in ("#", "/", ":"):
        idx = uri.rfind(sep)
        if idx >= 0:
            local = uri[idx + 1 :]
            if local:
                return local[:max_len]
    return uri[:max_len]


def classify_edge(predicate: str) -> str:
    """Classify an edge predicate into a semantic role for styling."""
    p = predicate.lower()
    if "portal" in p or "sourceholon" in p or "targetholon" in p:
        return "portal"
    if "memberof" in p or "adjacentto" in p:
        return "membership"
    if "subclassof" in p or "subpropertyof" in p:
        return "type_hierarchy"
    if "prov" in p or "derived" in p or "generated" in p:
        return "provenance"
    if "realizes" in p:
        return "realization"
    return "default"


def edge_color(predicate: str) -> str:
    """Return colour for an edge based on its predicate."""
    role = classify_edge(predicate)
    return EDGE_COLORS.get(role, EDGE_COLORS["default"])
