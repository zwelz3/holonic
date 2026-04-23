"""holonic — Graph-native holonic RDF systems.

A lightweight Python client for building holonic knowledge graphs
backed by rdflib, Apache Jena Fuseki, or any SPARQL-compliant store.
"""

__version__ = "0.5.0"

from holonic.backends import AbstractHolonicStore, HolonicStore, RdflibBackend
from holonic.client import HolonicDataset
from holonic.console_model import (
    ClassInstanceCount,
    GraphMetadata,
    HolonDetail,
    HolonSummary,
    NeighborhoodEdge,
    NeighborhoodGraph,
    NeighborhoodNode,
    PortalDetail,
    PortalSummary,
    ProjectionPipelineSpec,
    ProjectionPipelineStep,
    ProjectionPipelineSummary,
)
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
from holonic.plugins import (
    TransformNotFoundError,
    get_registered_transforms,
    projection_transform,
    resolve_transform,
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
from holonic.scope import (
    CustomSPARQL,
    HasClassInInterior,
    ResolveMatch,
    ResolveOrder,
    ResolvePredicate,
    ScopeResolver,
)

__all__ = [
    # Client
    "HolonicDataset",
    # Models
    "AuditTrail",
    "SurfaceReport",
    "TraversalRecord",
    "ValidationRecord",
    "HolonInfo",
    "MembraneBreachError",
    "MembraneHealth",
    "MembraneResult",
    "PortalInfo",
    # Console model (0.3.1 + 0.3.3 + 0.3.5)
    "ClassInstanceCount",
    "GraphMetadata",
    "HolonDetail",
    "HolonSummary",
    "NeighborhoodEdge",
    "NeighborhoodGraph",
    "NeighborhoodNode",
    "PortalDetail",
    "PortalSummary",
    "ProjectionPipelineSpec",
    "ProjectionPipelineStep",
    "ProjectionPipelineSummary",
    # Backends
    "AbstractHolonicStore",
    "HolonicStore",
    "RdflibBackend",
    # Scope resolution (0.3.4)
    "CustomSPARQL",
    "HasClassInInterior",
    "ResolveMatch",
    "ResolveOrder",
    "ResolvePredicate",
    "ScopeResolver",
    # Plugins (0.3.5)
    "TransformNotFoundError",
    "get_registered_transforms",
    "projection_transform",
    "resolve_transform",
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


# ══════════════════════════════════════════════════════════════
# 0.4.0 deprecation shims
# ══════════════════════════════════════════════════════════════
