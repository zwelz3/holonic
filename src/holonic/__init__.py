"""
holonic — A Python library for Cagel's four-graph holonic RDF model.

Each holon has four named graphs:
  - Interior:   what the holon knows about itself (A-Box)
  - Boundary:   SHACL shapes + portal definitions (membrane)
  - Projection:  curated outward face for external consumers
  - Context:    holarchy membership + temporal annotations
"""

__version__ = "0.1.0"

from .holon import Holon
from .portal import Portal, TransformPortal
from .membrane import validate_membrane, MembraneHealth, MembraneResult
from .holarchy import Holarchy
from .provenance import ProvenanceTracker
from .surface import discover_target_shape, generate_construct_query, describe_surface
