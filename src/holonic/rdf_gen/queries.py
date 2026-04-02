"""queries.py — Execute SPARQL queries and format results for templates.

Result types
------------
scalar    First row, first column as a Python value.
list      List of dicts, one per row, keys are variable names.
graph     rdflib Graph (from CONSTRUCT queries).
grouped   Dict of lists, grouped by first column value.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from rdflib import Graph, Literal, URIRef
from rdflib.term import Node as RDFNode


def _to_python(term: RDFNode) -> Any:
    """Convert an rdflib term to a plain Python value."""
    if isinstance(term, Literal):
        try:
            return term.toPython()
        except Exception:
            return str(term)
    if isinstance(term, URIRef):
        return str(term)
    return str(term) if term is not None else None


def _shorten(uri: str) -> str:
    """Produce a short local name from a URI."""
    for sep in ("#", "/", ":"):
        if sep in uri:
            local = uri.rsplit(sep, 1)[-1]
            if local:
                return local
    return uri


def execute_select(
    graph: Graph,
    query: str,
    result_type: str = "list",
    shorten_uris: bool = False,
) -> Any:
    """Execute a SPARQL SELECT query and return formatted results.

    Parameters
    ----------
    graph : Graph
        The RDF graph to query.
    query : str
        SPARQL SELECT query string.
    result_type : str
        How to format the results: 'scalar', 'list', 'grouped'.
    shorten_uris : bool
        If True, apply local-name shortening to URI values.

    Returns:
    -------
    Depending on result_type:
        'scalar'  — single Python value
        'list'    — list[dict[str, Any]]
        'grouped' — dict[str, list[dict]]
    """
    results = graph.query(query)

    if result_type == "scalar":
        for row in results:
            val = _to_python(row[0])
            return _shorten(val) if shorten_uris and isinstance(val, str) else val
        return None

    rows = []
    for row in results:
        d = {}
        for var in results.vars:
            val = getattr(row, str(var), None)
            pval = _to_python(val)
            if shorten_uris and isinstance(pval, str) and pval.startswith(("urn:", "http")):
                pval = _shorten(pval)
            d[str(var)] = pval
        rows.append(d)

    if result_type == "grouped":
        if not rows:
            return {}
        first_key = list(rows[0].keys())[0]
        grouped = defaultdict(list)
        for row in rows:
            key = row[first_key]
            grouped[key].append(row)
        return dict(grouped)

    return rows  # "list" is the default


def execute_construct(graph: Graph, query: str) -> Graph:
    """Execute a SPARQL CONSTRUCT query and return the result graph."""
    result = Graph()
    for triple in graph.query(query):
        result.add(triple)
    return result
