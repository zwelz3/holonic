"""Every SPARQL template in ``holonic.sparql`` must be valid SPARQL (CQ4).

The audit found the query layer was a pile of hand-written strings that no
test ever handed to a parser -- a typo in any template would only surface at
runtime, on whichever backend happened to run it. This round-trips every
module-level template through rdflib's own SPARQL parser (the same grammar
both backends rely on), so template drift fails fast and backend-independently.

Templates that carry ``{placeholder}`` slots are ``str.format``-filled with
context-appropriate stand-ins first (an IRI slot gets an IRI, ``cga:{role}``
gets a local name, a quoted literal slot gets safe text), because a raw
template with unfilled slots is not yet syntactically complete.
"""

from __future__ import annotations

import re

import pytest
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.processor import prepareUpdate

import holonic.sparql as Q

# Context-appropriate fills. Every IRI placeholder appears wrapped in <...>
# in the templates, so a bare IRI string is correct; role is a bare local
# name (used as cga:{role}); graph_values is a triple-pattern body; label and
# timestamp sit inside quotes.
_FILLS = {
    "activity_iri": "urn:x:1",
    "agent_iri": "urn:x:1",
    "class_iri": "urn:x:1",
    "context_graph": "urn:x:1",
    "from_holon": "urn:x:1",
    "graph_iri": "urn:x:1",
    "health_iri": "urn:x:1",
    "holon_iri": "urn:x:1",
    "registry_iri": "urn:x:1",
    "source_iri": "urn:x:1",
    "spec_iri": "urn:x:1",
    "target_iri": "urn:x:1",
    "role": "InteriorRole",
    "graph_values": "<urn:g:1>",
    "label": "safe-label",
    "timestamp": "2020-01-01T00:00:00",
    "limit": "5",
    "proj_hash": "deadbeef",
}

_PLACEHOLDER_RE = re.compile(r"\{(" + "|".join(_FILLS) + r")\}")
_UPDATE_KEYWORDS = ("INSERT", "DELETE", "DROP", "CREATE", "CLEAR", "LOAD")


def _templates() -> list[tuple[str, str]]:
    """Collect every module-level ``UPPER_CASE`` string template."""
    out = []
    for name in dir(Q):
        if not name.isupper():
            continue
        value = getattr(Q, name)
        if isinstance(value, str) and ("SELECT" in value or "ASK" in value
                                       or "CONSTRUCT" in value or "DESCRIBE" in value
                                       or any(k in value for k in _UPDATE_KEYWORDS)):
            out.append((name, value))
    return out


def _fill(template: str) -> str:
    """Fill ``{placeholder}`` slots if the template has any; else return as-is."""
    if _PLACEHOLDER_RE.search(template):
        return template.format(**_FILLS)
    return template


def _is_update(text: str) -> bool:
    return any(k in text for k in _UPDATE_KEYWORDS)


TEMPLATES = _templates()


def test_template_inventory_nonempty():
    # Guard against the collector silently matching nothing (which would make
    # every parametrized case vacuously pass).
    assert len(TEMPLATES) >= 15


@pytest.mark.parametrize("name,template", TEMPLATES, ids=[n for n, _ in TEMPLATES])
def test_template_parses(name, template):
    text = _fill(template)
    if _is_update(text):
        prepareUpdate(text)
    else:
        prepareQuery(text)
