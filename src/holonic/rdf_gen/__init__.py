"""rdf_gen — Generate documents and code from RDF data.

Provides a template-driven generation engine where the entire pipeline
(templates, data bindings, render specs) is described in RDF and
executed via SPARQL + Jinja2.
"""

__version__ = "0.1.0"

from .engine import RenderEngine, load_ttl
from .loaders import (
    json_to_ttl,
    requirements_to_ttl,
    simulation_results_to_ttl,
    sysml_to_ttl,
)
from .namespaces import ENG, GEN, SIM, SPARQL_PREFIXES, TTL_PREFIXES
from .queries import execute_construct, execute_select
