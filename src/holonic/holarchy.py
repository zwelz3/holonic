"""
holarchy.py — A managed collection of holons forming a nested hierarchy.

The holarchy tracks holons by IRI, manages parent-child relationships,
indexes portals, and provides cross-holon query facilities.
"""

from __future__ import annotations

from typing import Optional

from rdflib import Graph, URIRef, RDF

from .holon import Holon
from .portal import Portal
from .namespaces import CGA


class Holarchy:

    def __init__(self, label: str = "Holarchy"):
        self.label = label
        self._holons: dict[str, Holon] = {}
        self._portals: list[Portal] = []

    def register(self, holon: Holon) -> None:
        self._holons[holon.iri] = holon

    def get(self, iri: str) -> Optional[Holon]:
        return self._holons.get(iri)

    def add_portal(self, portal: Portal) -> None:
        self._portals.append(portal)

    def find_portal(self, source: Holon, target: Holon) -> Optional[Portal]:
        for p in self._portals:
            if p.source.iri == source.iri and p.target.iri == target.iri:
                return p
        return None

    @property
    def holons(self) -> list[Holon]:
        return list(self._holons.values())

    @property
    def portals(self) -> list[Portal]:
        return list(self._portals)

    def merged_interiors(self) -> Graph:
        merged = Graph()
        Holon._bind_prefixes(merged)
        for h in self._holons.values():
            for t in h.interior:
                merged.add(t)
        return merged

    def merged_all(self) -> Graph:
        merged = Graph()
        Holon._bind_prefixes(merged)
        for h in self._holons.values():
            for g in h.all_graphs():
                for t in g:
                    merged.add(t)
        return merged

    def summary(self) -> str:
        lines = [f"Holarchy: {self.label}"]
        for h in self._holons.values():
            lines.append(f"  {h}")
        if self._portals:
            lines.append("  Portals:")
            for p in self._portals:
                lines.append(f"    {p}")
        return "\n".join(lines)

    def __repr__(self):
        return f"Holarchy({self.label!r}, holons={len(self._holons)}, portals={len(self._portals)})"
