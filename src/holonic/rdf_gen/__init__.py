"""
rdf_gen — Generate documents and code from RDF data.

Provides a template-driven generation engine where the entire pipeline
(templates, data bindings, render specs) is described in RDF and
executed via SPARQL + Jinja2.
"""

__version__ = "0.1.0"

from .engine import RenderEngine, load_ttl
from .queries import execute_select, execute_construct
from .loaders import (
    sysml_to_ttl,
    requirements_to_ttl,
    simulation_results_to_ttl,
    json_to_ttl,
)
from .namespaces import GEN, ENG, SIM, TTL_PREFIXES, SPARQL_PREFIXES
