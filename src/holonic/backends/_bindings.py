"""Shared SPARQL binding coercion (0.8.0).

Every backend accepts ``**bindings`` on ``query`` / ``construct`` /
``ask``. The value contract is uniform and explicit:

* a value that is already an rdflib ``Node`` (``URIRef`` / ``Literal``
  / ``BNode``) is used verbatim, and
* any other Python value is wrapped as a typed ``Literal``.

That means **IRIs must be passed as ``rdflib.URIRef``**. This replaced
the 0.7.x heuristic that promoted only ``urn:``-prefixed *strings* to
IRIs and silently left ``http://`` strings as literals -- a guess that
bound the wrong term type for the majority of real IRIs (audit A1).

Two coercion paths share this contract:

* ``as_init_bindings`` feeds rdflib's native ``initBindings`` (the
  ``RdflibBackend`` fast path), and
* ``substitute_bindings`` textually splices ``?var`` -> ``term.n3()``
  for backends that speak SPARQL-over-HTTP and cannot pre-bind
  (``FusekiBackend``). It is injection-safe because every term is
  serialized through rdflib's own ``n3()`` (a ``URIRef`` becomes
  ``<iri>``; a ``Literal`` becomes a fully escaped quoted form), and the
  variable match is word-boundaried so ``?holon`` never clobbers
  ``?holonType``.
"""

from __future__ import annotations

import re
from typing import Any

from rdflib import Literal
from rdflib.term import Identifier


def to_term(value: Any) -> Identifier:
    """Coerce a binding value to an rdflib term.

    rdflib term values (``URIRef`` / ``Literal`` / ``BNode``) pass
    through untouched; every other Python value becomes a typed
    ``Literal``. To bind an IRI, pass ``rdflib.URIRef(...)`` -- a bare
    string is always a literal.
    """
    if isinstance(value, Identifier):
        return value
    return Literal(value)


def as_init_bindings(bindings: dict[str, Any]) -> dict[str, Identifier]:
    """Coerce a ``**bindings`` dict into rdflib ``initBindings`` form."""
    return {key: to_term(value) for key, value in bindings.items()}


def substitute_bindings(sparql: str, bindings: dict[str, Any]) -> str:
    """Textually bind ``?var`` -> ``term.n3()`` for non-rdflib backends.

    Safe substitution for stores that dispatch SPARQL as text and cannot
    use rdflib ``initBindings``. Each term is serialized via rdflib's own
    ``n3()`` so IRIs and literals are correctly delimited and escaped;
    ``?holon`` is matched with a trailing non-identifier guard so it does
    not partially rewrite ``?holonType``.
    """
    for key, value in bindings.items():
        replacement = to_term(value).n3()
        pattern = re.compile(rf"\?{re.escape(key)}(?![A-Za-z0-9_])")
        # Escape backslashes so re.sub treats the n3() output (which may
        # contain \" etc.) as a literal replacement, not a group reference.
        sparql = pattern.sub(replacement.replace("\\", "\\\\"), sparql)
    return sparql


__all__ = ["as_init_bindings", "substitute_bindings", "to_term"]
