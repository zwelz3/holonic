"""holonic — Graph-native holonic RDF systems.

A lightweight Python client for building holonic knowledge graphs
backed by rdflib, Apache Jena Fuseki, or any SPARQL-compliant store.
"""

__version__ = "0.2.1"

from holonic.backends import GraphBackend, RdflibBackend
from holonic.client import HolonicDataset
from holonic.model import (
    AuditTrail,
    HolonInfo,
    MembraneBreachError,
    MembraneHealth,
    MembraneResult,
    PortalInfo,
    SurfaceReport,
    TraversalRecord,
    ValidationRecord,
)
from holonic.projections import (
    CONSTRUCT_COLLAPSE_REIFICATION,
    CONSTRUCT_DATA_PROPERTIES_ONLY,
    CONSTRUCT_LABELS_ONLY,
    CONSTRUCT_OBJECT_PROPERTIES_ONLY,
    CONSTRUCT_STRIP_TYPES,
    CONSTRUCT_SUBCLASS_TREE,
    ProjectedEdge,
    ProjectedGraph,
    ProjectedNode,
    ProjectionPipeline,
    ProjectionStep,
    build_construct,
    collapse_reification,
    extract_types,
    filter_by_class,
    localize_predicates,
    project_to_lpg,
    strip_blank_nodes,
)

__all__ = [
    # Client
    "HolonicDataset",
    # Models
    "HolonInfo",
    "MembraneBreachError",
    "MembraneHealth",
    "MembraneResult",
    "PortalInfo",
    # Backends
    "GraphBackend",
    "RdflibBackend",
    # Projections
    "ProjectedEdge",
    "ProjectedGraph",
    "ProjectedNode",
    "ProjectionPipeline",
    "ProjectionStep",
    "build_construct",
    "collapse_reification",
    "extract_types",
    "filter_by_class",
    "localize_predicates",
    "project_to_lpg",
    "strip_blank_nodes",
    "CONSTRUCT_COLLAPSE_REIFICATION",
    "CONSTRUCT_DATA_PROPERTIES_ONLY",
    "CONSTRUCT_LABELS_ONLY",
    "CONSTRUCT_OBJECT_PROPERTIES_ONLY",
    "CONSTRUCT_STRIP_TYPES",
    "CONSTRUCT_SUBCLASS_TREE",
]
