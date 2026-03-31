"""
styles.py — Visual constants for holonic graph visualization.

Colour palette follows the cell-membrane metaphor:
  Interior   = blue   (the cytoplasm)
  Boundary   = purple (the membrane)
  Projection = green  (the surface proteins, outward-facing)
  Context    = amber  (the tissue/environment)
  Portal     = red    (traversal channel)
  Holon      = grey   (group container)
"""

# ------------------------------------------------------------------
# Layer colours
# ------------------------------------------------------------------

LAYER_COLORS = {
    "interior":   "#3b82f6",  # blue-500
    "boundary":   "#a855f7",  # purple-500
    "projection": "#22c55e",  # green-500
    "context":    "#f59e0b",  # amber-500
    "portal":     "#ef4444",  # red-500
    "holon":      "#6b7280",  # grey-500 (group container)
    "literal":    "#94a3b8",  # slate-400
    "default":    "#64748b",  # slate-500
}

LAYER_COLORS_LIGHT = {
    "interior":   "#dbeafe",  # blue-100
    "boundary":   "#f3e8ff",  # purple-100
    "projection": "#dcfce7",  # green-100
    "context":    "#fef3c7",  # amber-100
    "portal":     "#fee2e2",  # red-100
    "holon":      "#f3f4f6",  # grey-100
}

# ------------------------------------------------------------------
# Node shapes (yFiles shape names)
# ------------------------------------------------------------------

LAYER_SHAPES = {
    "interior":   "round-rectangle",
    "boundary":   "hexagon",
    "projection": "pill",
    "context":    "octagon",
    "portal":     "triangle",
    "holon":      "rectangle",
    "literal":    "ellipse",
    "default":    "rectangle",
}

# ------------------------------------------------------------------
# Node scale factors
# ------------------------------------------------------------------

LAYER_SCALES = {
    "interior":   1.0,
    "boundary":   0.9,
    "projection": 0.9,
    "context":    0.9,
    "portal":     1.2,
    "holon":      1.0,
    "literal":    0.6,
    "default":    0.8,
}

# ------------------------------------------------------------------
# Edge styles per predicate category
# ------------------------------------------------------------------

EDGE_COLORS = {
    "rdf:type":        "#9333ea",
    "rdfs:subClassOf": "#7c3aed",
    "sh:property":     "#a855f7",
    "sh:path":         "#c084fc",
    "cga:memberOf":    "#f59e0b",
    "cga:hasPortal":   "#ef4444",
    "cga:sourceHolon": "#ef4444",
    "cga:targetHolon": "#ef4444",
    "prov:used":       "#06b6d4",
    "prov:generated":  "#06b6d4",
    "default":         "#94a3b8",
}

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def color_for_layer(layer: str) -> str:
    return LAYER_COLORS.get(layer, LAYER_COLORS["default"])

def color_for_layer_light(layer: str) -> str:
    return LAYER_COLORS_LIGHT.get(layer, "#f8fafc")

def shape_for_layer(layer: str) -> str:
    return LAYER_SHAPES.get(layer, LAYER_SHAPES["default"])

def scale_for_layer(layer: str) -> float:
    return LAYER_SCALES.get(layer, LAYER_SCALES["default"])

def shorten_uri(uri: str, max_len: int = 40) -> str:
    """Produce a readable short form of a URI."""
    for sep in ("#", "/", ":"):
        if sep in uri:
            local = uri.rsplit(sep, 1)[-1]
            if local:
                return local[:max_len]
    return uri[:max_len]
