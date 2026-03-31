"""
holonic.viz — Visualisation for holonic RDF graphs.

Requires: yfiles-jupyter-graphs, ipywidgets

    pip install yfiles-jupyter-graphs ipywidgets
"""

from .widgets import HolonViz, HolarchyViz, SPARQLExplorer
from .projections import PROJECTIONS, get_projection_names, get_projection
from .graph_builder import (
    holon_to_graph_data,
    holarchy_to_graph_data,
    sparql_construct_to_graph_data,
)
