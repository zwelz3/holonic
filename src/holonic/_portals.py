"""Portal registry: declaration, mutation, and discovery (0.8.0).

Extracted from :class:`holonic.client.HolonicDataset` as part of the
0.8.0 god-class decomposition (AR1/CQ1). This module owns the portal
lifecycle -- declaring a portal (with its CONSTRUCT body, source/target
endpoints, and type terms), updating and removing it, and the discovery
surface over the registry: portals leaving or entering a holon, lookup
by IRI, and shortest-path search across the portal graph.

Traversal is deliberately *not* here. This module answers "which
portals exist and where do they point"; :mod:`holonic._traversal`
answers "what happens when one is crossed".

The registry holds a back-reference to its owning ``HolonicDataset``
(``self._ds``) rather than a bare backend, because portal writes reach
into the facade's metadata-refresh machinery (``_maybe_refresh``).
This mirrors :class:`holonic._pipelines.PipelineManager` and
:class:`holonic._console.ConsoleReads`.

``HolonicDataset`` keeps thin delegating wrappers for every public
method here, so the public API is unchanged.

.. versionadded:: 0.8.0
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

from holonic import sparql as Q

# Module-level rather than deferred like the other client helpers: this is a
# default argument value in update_portal, so it is evaluated when the class
# body executes. It must also be the *same* object the facade's wrapper
# forwards, because "was this argument passed?" is an identity check.
from holonic.client import _SENTINEL  # noqa: E402
from holonic.model import PortalInfo

if TYPE_CHECKING:
    from holonic.client import HolonicDataset

log = logging.getLogger(__name__)


class PortalRegistry:
    """See module docstring. Reached via ``ds._portals``."""

    def __init__(self, ds: HolonicDataset):
        self._ds = ds

    def add_portal(
        self,
        portal_iri: str,
        source_iri: str,
        target_iri: str,
        construct_query: str | None = None,
        *,
        portal_type: str = "cga:TransformPortal",
        extra_ttl: str | None = None,
        label: str | None = None,
        graph_iri: str | None = None,
    ) -> str:
        """Register a portal in the source holon's boundary graph.

        The portal definition IS RDF in the boundary named graph.
        Discovery uses SPARQL, not Python lookups.

        Parameters
        ----------
        portal_iri :
            IRI for the portal resource.
        source_iri :
            IRI of the source holon.
        target_iri :
            IRI of the target holon.
        construct_query :
            Optional SPARQL CONSTRUCT query that produces the target
            interior from the source. Omit for portal subtypes that do
            not carry a SPARQL transformation (e.g. ``cga:IconPortal``,
            ``cga:SealedPortal``, or downstream subclasses whose
            transformation is specified by a different predicate).
        portal_type :
            RDF type for the portal. Defaults to ``"cga:TransformPortal"``.
            Accepts a prefixed name (``"cga:SealedPortal"``,
            ``"ext:NeuralPortal"``) or a full IRI. The caller is
            responsible for ensuring the type resolves to a declared
            class.
        extra_ttl :
            Additional Turtle triples appended verbatim to the portal
            block before parsing. Useful for portal subclasses that
            carry extra predicates. Applied to both the boundary graph
            and the registry mirror. The string should NOT include
            ``@prefix`` declarations -- the method prepends the
            standard prefix block.
        label :
            Human-readable label. Defaults to "<source> -> <target>".
        graph_iri :
            Explicit boundary graph IRI. Defaults to
            ``"<source_iri>/boundary"``.

        Returns:
        -------
        str
            The portal's IRI (same as the input, returned for chaining).

        Examples:
        --------
        Minimal TransformPortal with CONSTRUCT (the 0.3.x/0.4.0 form,
        unchanged)::

            ds.add_portal(
                "urn:portal:a-to-b",
                source_iri="urn:holon:a",
                target_iri="urn:holon:b",
                construct_query="CONSTRUCT { ?s ?p ?o } WHERE { GRAPH ?g { ?s ?p ?o } }",
            )

        SealedPortal with no CONSTRUCT query::

            ds.add_portal(
                "urn:portal:sealed",
                source_iri="urn:holon:a",
                target_iri="urn:holon:b",
                portal_type="cga:SealedPortal",
            )

        Downstream portal subclass carrying extra predicates::

            ds.add_portal(
                "urn:portal:neural",
                source_iri="urn:holon:a",
                target_iri="urn:holon:b",
                portal_type="ext:NeuralPortal",
                extra_ttl='''
                    @prefix ext: <urn:ext:> .
                    <urn:portal:neural> ext:transformRef <urn:model:v1> ;
                        ext:portalWeight 0.87 .
                ''',
            )
        """
        from holonic.client import _escape_ttl, _type_term, _validate_iri

        _validate_iri(portal_iri, "portal_iri")
        _validate_iri(source_iri, "source_iri")
        _validate_iri(target_iri, "target_iri")
        if graph_iri:
            _validate_iri(graph_iri, "graph_iri")
        graph_iri = graph_iri or f"{source_iri}/boundary"
        # TODO to_pithy_id
        lbl = label or f"{source_iri} -> {target_iri}"

        # Extract any @prefix lines from extra_ttl so they can be placed
        # at the top of the combined Turtle block (prefix declarations
        # must precede any triples in Turtle syntax).
        extra_prefixes = ""
        extra_body = ""
        if extra_ttl:
            for line in extra_ttl.splitlines():
                stripped = line.strip()
                if stripped.lower().startswith("@prefix") and stripped.endswith("."):
                    extra_prefixes += line + "\n"
                else:
                    extra_body += line + "\n"

        ttl = f"""
            @prefix cga:  <urn:holonic:ontology:> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            {extra_prefixes}
            <{portal_iri}> a {_type_term(portal_type, "portal_type")} ;
                cga:sourceHolon <{source_iri}> ;
                cga:targetHolon <{target_iri}> ;
                rdfs:label "{_escape_ttl(lbl)}\""""
        if construct_query is not None:
            escaped_query = construct_query.replace("\\", "\\\\").replace('"', '\\"')
            ttl += f' ;\n                cga:constructQuery """{escaped_query}"""'
        ttl += " .\n"

        if extra_body.strip():
            ttl += extra_body + "\n"

        self._ds.backend.parse_into(graph_iri, ttl, "turtle")
        # Also ensure portal is visible from registry
        self._ds.backend.parse_into(self._ds.registry_iri, ttl, "turtle")
        self._ds._maybe_refresh(graph_iri)
        return portal_iri

    def remove_portal(self, portal_iri: str) -> bool:
        """Remove a portal from the dataset.

        Cleans up all triples with ``portal_iri`` as subject across every
        named graph that contains them (typically the source holon's
        boundary graph and the registry mirror). The boundary graph
        itself is preserved; only the triples about this specific
        portal are deleted.

        Parameters
        ----------
        portal_iri :
            The portal's IRI.

        Returns:
        -------
        bool
            ``True`` if the portal existed and was removed. ``False`` if
            the IRI was not found in any graph (idempotent -- not an
            error).

        Notes:
        -----
        Does NOT remove:

        - The source or target holons
        - The boundary graph itself (other portals or SHACL shapes may
          live there)
        - Provenance activities referencing this portal

        When ``metadata_updates="eager"``, metadata for each affected
        graph is refreshed after the removal.
        """
        # Find every graph containing triples about this portal
        rows = list(
            self._ds.backend.query(
                f"""
            SELECT DISTINCT ?g WHERE {{
                GRAPH ?g {{ <{portal_iri}> ?p ?o }}
            }}
            """
            )
        )
        if not rows:
            return False

        affected_graphs = [str(r["g"]) for r in rows]

        # Delete all triples with the portal as subject in each graph
        for g in affected_graphs:
            self._ds.backend.update(
                f"""
                DELETE WHERE {{
                    GRAPH <{g}> {{ <{portal_iri}> ?p ?o }}
                }}
                """
            )

        # Belt-and-suspenders: also delete from the registry in case the
        # portal was added without the registry mirror being picked up
        # by the graph search (e.g. if the portal's only subject-position
        # triples were in blank-node contexts that elided the discovery).
        if self._ds.registry_iri not in affected_graphs:
            self._ds.backend.update(
                f"""
                DELETE WHERE {{
                    GRAPH <{self._ds.registry_iri}> {{ <{portal_iri}> ?p ?o }}
                }}
                """
            )

        # Refresh metadata for affected graphs if eager
        for g in affected_graphs:
            self._ds._maybe_refresh(g)

        return True

    def update_portal(
        self,
        portal_iri: str,
        *,
        construct_query: str | None = _SENTINEL,
        label: str | None = _SENTINEL,
        portal_type: str | None = _SENTINEL,
    ) -> None:
        """Update a portal's properties in-place.

        Only the provided keyword arguments are changed; unspecified
        properties are preserved. The portal IRI and source/target
        holons are immutable (use remove + add to change those).

        Parameters
        ----------
        portal_iri :
            IRI of the portal to update.
        construct_query :
            New CONSTRUCT query string, or None to remove it.
        label :
            New label, or None to remove it.
        portal_type :
            New RDF type (e.g. ``"cga:SealedPortal"``).

        Raises:
        ------
        ValueError
            If the portal does not exist.

        .. versionadded:: 0.6.0
        """
        from holonic.client import _SENTINEL, _escape_ttl, _type_term

        # Verify portal exists
        detail = self._ds.get_portal(portal_iri)
        if detail is None:
            raise ValueError(f"Portal {portal_iri} not found")

        # Build targeted updates for each changed property.
        # rdflib's get_graph returns a reference (not copy), so we use
        # per-graph SPARQL DELETE WHERE with explicit graph names.
        if construct_query is not _SENTINEL:
            # Find which graphs contain the old constructQuery
            cq_graphs = self._ds.backend.query(f"""
                PREFIX cga: <urn:holonic:ontology:>
                SELECT DISTINCT ?g WHERE {{
                    GRAPH ?g {{ <{portal_iri}> cga:constructQuery ?q }}
                }}
            """)
            # Delete old value from each graph individually
            for row in cq_graphs:
                g_iri = row["g"]
                self._ds.backend.update(f"""
                    PREFIX cga: <urn:holonic:ontology:>
                    DELETE WHERE {{
                        GRAPH <{g_iri}> {{ <{portal_iri}> cga:constructQuery ?old }}
                    }}
                """)
            # Insert new query via Turtle parse (avoids SPARQL escaping)
            if construct_query is not None:
                escaped = construct_query.replace("\\", "\\\\").replace('"', '\\"')
                ttl = (
                    f"@prefix cga: <urn:holonic:ontology:> .\n"
                    f'<{portal_iri}> cga:constructQuery """{escaped}""" .\n'
                )
                self._ds.backend.parse_into(self._ds.registry_iri, ttl, "turtle")

        if label is not _SENTINEL:
            lbl_graphs = self._ds.backend.query(f"""
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT DISTINCT ?g WHERE {{
                    GRAPH ?g {{ <{portal_iri}> rdfs:label ?l }}
                }}
            """)
            for row in lbl_graphs:
                g_iri = row["g"]
                self._ds.backend.update(f"""
                    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                    DELETE WHERE {{
                        GRAPH <{g_iri}> {{ <{portal_iri}> rdfs:label ?old }}
                    }}
                """)
            if label is not None:
                ttl = (
                    f"@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
                    f'<{portal_iri}> rdfs:label "{_escape_ttl(label)}" .\n'
                )
                self._ds.backend.parse_into(self._ds.registry_iri, ttl, "turtle")

        if portal_type is not _SENTINEL and portal_type is not None:
            # Find and remove old subtypes per-graph
            type_graphs = self._ds.backend.query(f"""
                PREFIX cga: <urn:holonic:ontology:>
                SELECT DISTINCT ?g ?type WHERE {{
                    GRAPH ?g {{
                        <{portal_iri}> a ?type .
                        FILTER(?type != cga:Portal)
                    }}
                }}
            """)
            for row in type_graphs:
                g_iri = row["g"]
                old_type = row["type"]
                self._ds.backend.update(f"""
                    DELETE DATA {{
                        GRAPH <{g_iri}> {{
                            <{portal_iri}> a <{old_type}> .
                        }}
                    }}
                """)
            # Insert new type into registry AND the boundary graph
            # (boundary is where structural triples live; queries
            # look for type in the same graph as sourceHolon)
            ttl = (
                "@prefix cga: <urn:holonic:ontology:> .\n"
                f"<{portal_iri}> a {_type_term(portal_type, 'portal_type')} .\n"
            )
            self._ds.backend.parse_into(self._ds.registry_iri, ttl, "turtle")
            # Find the boundary graph
            bnd_rows = self._ds.backend.query(f"""
                PREFIX cga: <urn:holonic:ontology:>
                SELECT ?g WHERE {{
                    GRAPH ?g {{
                        <{portal_iri}> cga:sourceHolon ?s .
                    }}
                    FILTER(?g != <{self._ds.registry_iri}>)
                }} LIMIT 1
            """)
            if bnd_rows:
                self._ds.backend.parse_into(
                    bnd_rows[0]["g"],
                    ttl,
                    "turtle",
                )

        if self._ds._metadata_updates == "eager":
            self._ds._metadata.refresh_graph(self._ds.registry_iri)

    def iter_portals_from(
        self,
        source_iri: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ):
        """Yield portals originating from a holon.

        Parameters
        ----------
        limit :
            Maximum number of portals to yield.
        offset :
            Number of portals to skip.

        Yields:
        ------
        PortalInfo

        .. versionadded:: 0.5.0
        """
        from holonic.client import _bind_iri

        q = Q.FIND_PORTALS_FROM
        if limit is not None:
            q += f"\nLIMIT {int(limit)}"
        if offset is not None:
            q += f"\nOFFSET {int(offset)}"
        for r in self._ds.backend.query(q, source=_bind_iri(source_iri, "source_iri")):
            yield PortalInfo(
                iri=r["portal"],
                source_iri=source_iri,
                target_iri=r["target"],
                label=r.get("label"),
                construct_query=r.get("query"),
                portal_type=r.get("portalType"),
            )

    def find_portals_from(
        self,
        source_iri: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[PortalInfo]:
        """Discover portals originating from a holon.  Pure SPARQL.

        Returns a materialized list. For lazy iteration, use
        :meth:`iter_portals_from`.
        """
        return list(self.iter_portals_from(source_iri, limit=limit, offset=offset))

    def iter_portals_to(
        self,
        target_iri: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ):
        """Yield portals targeting a holon.

        Parameters
        ----------
        limit :
            Maximum number of portals to yield.
        offset :
            Number of portals to skip.

        Yields:
        ------
        PortalInfo

        .. versionadded:: 0.5.0
        """
        from holonic.client import _bind_iri

        q = Q.FIND_PORTALS_TO
        if limit is not None:
            q += f"\nLIMIT {int(limit)}"
        if offset is not None:
            q += f"\nOFFSET {int(offset)}"
        for r in self._ds.backend.query(q, target=_bind_iri(target_iri, "target_iri")):
            yield PortalInfo(
                iri=r["portal"],
                source_iri=r["source"],
                target_iri=target_iri,
                label=r.get("label"),
                construct_query=r.get("query"),
                portal_type=r.get("portalType"),
            )

    def find_portals_to(
        self,
        target_iri: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[PortalInfo]:
        """Discover portals targeting a holon.  Pure SPARQL.

        Returns a materialized list. For lazy iteration, use
        :meth:`iter_portals_to`.
        """
        return list(self.iter_portals_to(target_iri, limit=limit, offset=offset))

    def find_portal(self, source_iri: str, target_iri: str) -> PortalInfo | None:
        """Find a direct portal between two holons.  Returns None if none exists."""
        from holonic.client import _bind_iri

        rows = self._ds.backend.query(
            Q.FIND_PORTAL_DIRECT,
            source=_bind_iri(source_iri, "source_iri"),
            target=_bind_iri(target_iri, "target_iri"),
        )
        if not rows:
            return None
        r = rows[0]
        return PortalInfo(
            iri=r["portal"],
            source_iri=source_iri,
            target_iri=target_iri,
            label=r.get("label"),
            construct_query=r.get("query"),
            portal_type=r.get("portalType"),
        )

    def find_path(
        self,
        source_iri: str,
        target_iri: str,
    ) -> list[PortalInfo] | None:
        """Find a portal chain via BFS over the SPARQL-discovered portal graph.

        Returns a list of PortalInfo forming a path, or None if unreachable.
        """
        # Fetch all portals in one query
        rows = self._ds.backend.query(Q.ALL_PORTALS)
        adj: dict[str, list[PortalInfo]] = {}
        for r in rows:
            p = PortalInfo(
                iri=r["portal"],
                source_iri=r["source"],
                target_iri=r["target"],
                label=r.get("label"),
                portal_type=r.get("portalType"),
            )
            adj.setdefault(p.source_iri, []).append(p)

        # BFS
        queue: deque[tuple[str, list[PortalInfo]]] = deque([(source_iri, [])])
        visited = {source_iri}
        while queue:
            current, path = queue.popleft()
            for portal in adj.get(current, []):
                new_path = path + [portal]
                if portal.target_iri == target_iri:
                    return new_path
                if portal.target_iri not in visited:
                    visited.add(portal.target_iri)
                    queue.append((portal.target_iri, new_path))
        return None


__all__ = ["PortalRegistry"]
