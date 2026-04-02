"""Visualization module for holonic RDF systems.

Provides yFiles Jupyter Graphs widgets for visualizing holons,
holarchies, and SPARQL query results.  All rendering is projection-
driven: RDF is simplified via project_to_lpg() before building
yFiles node/edge data.

Requires: yfiles-jupyter-graphs, ipywidgets
"""

from holonic.viz.formatters import (
    format_compartmented,
    format_shacl_shape,
    format_simple,
    format_typed,
)
from holonic.viz.graph_builder import (
    holarchy_to_yfiles,
    holon_to_yfiles,
    projected_to_yfiles,
    sparql_result_to_yfiles,
)
from holonic.viz.widgets import (
    HolarchyViz,
    HolonViz,
    SPARQLExplorer,
)

__all__ = [
    # Widgets
    "HolonViz",
    "HolarchyViz",
    "SPARQLExplorer",
    # Graph builders
    "holon_to_yfiles",
    "holarchy_to_yfiles",
    "projected_to_yfiles",
    "sparql_result_to_yfiles",
    # Formatters
    "format_compartmented",
    "format_shacl_shape",
    "format_simple",
    "format_typed",
]
