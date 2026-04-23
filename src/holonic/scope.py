"""Scoped discovery across the holarchy (0.3.4).

Given a starting holon and a predicate, walk the holarchy in
decreasing priority order and return holons that match. The walk is a
strict BFS through one of three topologies: outbound+inbound portals
(``"network"``, default), inbound portals only
(``"reverse-network"``), or `cga:memberOf` containment
(``"containment"``).

Public API:

    resolve(predicate, from_holon, *, max_depth=3, order="network",
            limit=50) -> list[ResolveMatch]

Predicate classes:

    HasClassInInterior(class_iri)
        Match holons whose interior contains at least one instance of
        the given rdf:type. Uses the 0.3.3 class inventory when
        present; falls back to a direct GRAPH query otherwise.

    CustomSPARQL(ask_template)
        Escape hatch. Caller supplies a SPARQL ASK template using the
        placeholder ``{holon_iri}``. Returns the ASK result.

``ResolveMatch`` is a lightweight dataclass carrying the match IRI,
its distance from ``from_holon`` in the walk topology, and evidence
(the class IRI or ASK template that satisfied the predicate).

See ``docs/DECISIONS.md`` § 0.3.4 for the design rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from holonic import sparql as Q

if TYPE_CHECKING:
    from holonic.backends.store import HolonicStore


ResolveOrder = Literal["network", "reverse-network", "containment"]
"""BFS topology choice for ``ScopeResolver.resolve()``.

- ``"network"`` — outbound portals followed by inbound portals.
  The default; matches how data actually flows through the holarchy.
- ``"reverse-network"`` — inbound portals only. Useful for
  "who depends on me?" queries and for debugging a holon's upstream
  reach.
- ``"containment"`` — ``cga:memberOf`` chain in both directions
  (parent + descendants). Matches governance hierarchies rather than
  data-flow topologies.
"""


# ══════════════════════════════════════════════════════════════
# Predicate classes
# ══════════════════════════════════════════════════════════════


class ResolvePredicate(Protocol):
    """A predicate takes a candidate holon IRI and returns a bool.

    Implementations render one or more SPARQL queries against the
    backend and interpret the result. Keep per-predicate state to a
    minimum — predicates are evaluated once per candidate holon
    during resolution.
    """

    def matches(self, backend: HolonicStore, holon_iri: str, registry_iri: str) -> bool:
        """Return True if the given holon satisfies the predicate."""
        ...

    def evidence(self) -> str:
        """Return a human-readable description of what the predicate tests."""
        ...


@dataclass(frozen=True)
class HasClassInInterior:
    """Match holons whose interior graphs contain instances of ``class_iri``.

    Uses the 0.3.3 class inventory via the registry graph when the
    inventory is populated; falls back to a direct interior graph
    query otherwise. The fallback means ``metadata_updates="off"``
    deployments still get correct answers, just slower.

    Parameters
    ----------
    class_iri :
        The full IRI of the class to match against
        (e.g. ``"urn:holonic:ontology:Holon"``).

    Examples:
    --------
    Find any holon in the holarchy whose interior contains a
    ``cga:TransformPortal``::

        matches = ds.resolve(
            HasClassInInterior("urn:holonic:ontology:TransformPortal"),
            from_holon="urn:holon:root",
            max_depth=5,
        )
    """

    class_iri: str

    def matches(self, backend: HolonicStore, holon_iri: str, registry_iri: str) -> bool:
        """Return True if the holon's interior contains an instance of ``class_iri``.

        Executes an ASK query against the backend. The query first
        consults the 0.3.3 class inventory in the registry and falls
        back to a direct interior scan if the inventory is not
        populated for this holon.
        """
        ask = Q.ASK_HAS_CLASS_IN_INTERIOR_TEMPLATE.format(
            registry_iri=registry_iri,
            class_iri=self.class_iri,
            holon_iri=holon_iri,
        )
        return backend.ask(ask)

    def evidence(self) -> str:
        """Return a description naming the class being matched."""
        return f"interior contains instances of <{self.class_iri}>"


@dataclass(frozen=True)
class CustomSPARQL:
    """Match holons via a caller-supplied SPARQL ASK template.

    The template must use the literal placeholder ``{holon_iri}`` for
    the candidate holon IRI. ``{registry_iri}`` is also substituted
    if present. Substitution uses ``str.replace``, not ``str.format``,
    so normal SPARQL braces in ``GRAPH ?g { ... }`` do not need to
    be doubled.

    Parameters
    ----------
    ask_template :
        A SPARQL ASK query string with ``{holon_iri}`` (and optionally
        ``{registry_iri}``) as literal substring placeholders.

    Examples:
    --------
    Find holons with classified data::

        CustomSPARQL('''
            PREFIX cga: <urn:holonic:ontology:>
            ASK WHERE {
                GRAPH ?g {
                    <{holon_iri}> cga:dataClassification cga:CUI .
                }
            }
        ''')

    Notes:
    -----
    ``CustomSPARQL`` is intended as an escape hatch. If you find
    yourself using it repeatedly for the same pattern, consider
    proposing a first-class predicate class via SPEC R9.14.
    """

    ask_template: str

    def matches(self, backend: HolonicStore, holon_iri: str, registry_iri: str) -> bool:
        """Substitute placeholders and run the ASK query against the backend.

        Uses ``str.replace`` for substitution, not ``str.format``, so
        SPARQL braces in the template body don't need escaping.
        """
        ask = self.ask_template.replace("{holon_iri}", holon_iri).replace(
            "{registry_iri}", registry_iri
        )
        return backend.ask(ask)

    def evidence(self) -> str:
        """Return the first line of the ASK template as a terse description."""
        first_line = self.ask_template.strip().splitlines()[0]
        return f"custom SPARQL: {first_line[:80]}..."


# ══════════════════════════════════════════════════════════════
# Match record
# ══════════════════════════════════════════════════════════════


@dataclass
class ResolveMatch:
    """A holon that satisfied the resolve predicate.

    Attributes:
    ----------
    iri :
        The matching holon's IRI.
    distance :
        BFS hop count from ``from_holon``. 0 means the starting
        holon itself matched.
    evidence :
        Human-readable description of what matched (from the
        predicate's ``evidence()`` method).
    """

    iri: str
    distance: int
    evidence: str = ""


# ══════════════════════════════════════════════════════════════
# Resolver
# ══════════════════════════════════════════════════════════════


class ScopeResolver:
    """Executes a scoped BFS walk against a backend.

    Held by ``HolonicDataset`` and delegated to from ``resolve()``.
    Public construction is allowed for advanced callers who want to
    customize walking without going through the dataset.

    Parameters
    ----------
    backend :
        Any ``HolonicStore`` implementation. The resolver issues
        ASK, SELECT, and (indirectly via predicates) further ASK
        queries against the backend during resolution.
    registry_iri :
        IRI of the registry graph used for portal and
        ``cga:memberOf`` discovery. Predicates receive this IRI so
        they can query the registry if needed.
    """

    def __init__(
        self,
        backend: HolonicStore,
        registry_iri: str,
    ) -> None:
        self._backend = backend
        self._registry_iri = registry_iri

    def _neighbors(self, holon_iri: str, order: ResolveOrder) -> list[str]:
        """Return the next-hop candidates from ``holon_iri`` under ``order``.

        Parameters
        ----------
        holon_iri :
            IRI of the current BFS frontier holon.
        order :
            Walk topology. See ``ResolveOrder`` for the three choices.

        Returns:
        -------
        list[str]
            Neighbor IRIs in deterministic order. Under ``"network"``,
            outbound-portal neighbors appear before inbound-portal
            ones; duplicates (holons reachable both ways) are
            deduplicated while preserving their first-appearance
            ordering.

        Raises:
        ------
        ValueError
            If ``order`` is not one of the three ``ResolveOrder``
            values. In practice this should only happen if a caller
            bypasses the type system.
        """
        if order == "network":
            # Outbound portals first, then inbound
            outbound = self._backend.query(
                Q.WALK_OUTBOUND_PORTAL_NEIGHBORS_TEMPLATE.format(from_holon=holon_iri)
            )
            inbound = self._backend.query(
                Q.WALK_INBOUND_PORTAL_NEIGHBORS_TEMPLATE.format(from_holon=holon_iri)
            )
            # Preserve ordering: outbound before inbound, dedup within each
            seen: set[str] = set()
            out: list[str] = []
            for r in outbound:
                iri = str(r["neighbor"])
                if iri not in seen:
                    seen.add(iri)
                    out.append(iri)
            for r in inbound:
                iri = str(r["neighbor"])
                if iri not in seen:
                    seen.add(iri)
                    out.append(iri)
            return out

        if order == "reverse-network":
            rows = self._backend.query(
                Q.WALK_INBOUND_PORTAL_NEIGHBORS_TEMPLATE.format(from_holon=holon_iri)
            )
            return [str(r["neighbor"]) for r in rows]

        if order == "containment":
            rows = self._backend.query(
                Q.WALK_MEMBER_OF_NEIGHBORS_TEMPLATE.format(from_holon=holon_iri)
            )
            return [str(r["neighbor"]) for r in rows]

        raise ValueError(f"unknown order: {order!r}")

    def resolve(
        self,
        predicate: ResolvePredicate,
        from_holon: str,
        *,
        max_depth: int = 3,
        order: ResolveOrder = "network",
        limit: int = 50,
    ) -> list[ResolveMatch]:
        """Walk the holarchy in BFS order and return predicate matches.

        Parameters
        ----------
        predicate :
            A ``ResolvePredicate`` instance. The starting holon and
            every neighbor visited during the walk is tested.
        from_holon :
            IRI of the starting holon.
        max_depth :
            Maximum BFS depth (hops from ``from_holon``). Clamped to
            the range ``[0, 100]`` to prevent runaway walks.
            ``max_depth=0`` tests only the starting holon.
        order :
            Walk topology: ``"network"`` (default),
            ``"reverse-network"``, or ``"containment"``.
        limit :
            Maximum number of matches to return. Clamped to
            ``[1, 10_000]``. BFS terminates once ``limit`` is
            reached; remaining frontier holons are not visited.

        Returns:
        -------
        list[ResolveMatch]
            Matches in BFS order: all depth-0 matches first, then
            depth-1, etc. Within a single depth, order is determined
            by the backend's ``ORDER BY ?neighbor`` on the walk query
            (IRI-alphabetical for deterministic tiebreaking).

        Examples:
        --------
        Network-proximity discovery from a known holon::

            from holonic import HolonicDataset, HasClassInInterior

            ds = HolonicDataset()
            # ... populate the holarchy ...

            matches = ds.resolve(
                HasClassInInterior("urn:holonic:ontology:AgentHolon"),
                from_holon="urn:holon:op-center",
                max_depth=5,
            )
            for m in matches:
                print(f"  {m.iri}  distance={m.distance}")

        Containment walk (governance chain)::

            matches = ds.resolve(
                HasClassInInterior("urn:ex:Person"),
                from_holon="urn:holon:child",
                order="containment",
            )

        Custom predicate::

            from holonic import CustomSPARQL

            labeled = ds.resolve(
                CustomSPARQL('''
                    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                    ASK WHERE {
                        GRAPH ?g {
                            <{holon_iri}> rdfs:label ?l .
                            FILTER(STRSTARTS(?l, "B"))
                        }
                    }
                '''),
                from_holon="urn:holon:root",
            )

        Notes:
        -----
        The starting holon itself is always tested (depth 0) before
        any neighbors are visited. Its inclusion in the result set
        depends solely on whether the predicate matches it.

        Predicates are evaluated exactly once per candidate holon;
        cycles in the walk topology are handled by an internal
        ``visited`` set. This means a holon reachable by multiple
        paths contributes at most one ``ResolveMatch`` record,
        carrying the shortest-path distance.
        """
        max_depth = max(0, min(max_depth, 100))
        limit = max(1, min(limit, 10_000))

        matches: list[ResolveMatch] = []
        visited: set[str] = set()
        # BFS queue holds (holon_iri, distance)
        frontier: list[tuple[str, int]] = [(from_holon, 0)]
        evidence = predicate.evidence()

        while frontier and len(matches) < limit:
            next_frontier: list[tuple[str, int]] = []
            for iri, depth in frontier:
                if iri in visited:
                    continue
                visited.add(iri)
                if predicate.matches(self._backend, iri, self._registry_iri):
                    matches.append(ResolveMatch(iri=iri, distance=depth, evidence=evidence))
                    if len(matches) >= limit:
                        break
                if depth < max_depth:
                    for neighbor in self._neighbors(iri, order):
                        if neighbor not in visited:
                            next_frontier.append((neighbor, depth + 1))
            frontier = next_frontier

        return matches


# ══════════════════════════════════════════════════════════════
# Public re-exports
# ══════════════════════════════════════════════════════════════

__all__ = [
    "CustomSPARQL",
    "HasClassInInterior",
    "ResolveMatch",
    "ResolveOrder",
    "ResolvePredicate",
    "ScopeResolver",
]
