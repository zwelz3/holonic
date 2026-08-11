"""Graph-level metadata refresher (0.3.3).

Computes per-graph triple counts, last-modified timestamps, and
class inventories, and materializes them in the registry graph
(``urn:holarchy:registry`` by default, configurable via
``HolonicDataset(registry_iri=...)``).

This is an internal module. The public API is exposed through
``HolonicDataset.refresh_metadata()``, ``refresh_all_metadata()``,
and ``get_graph_metadata()``. See ``docs/DECISIONS.md`` § 0.3.3 for
the design rationale.

Design notes
~~~~~~~~~~~~
- Idempotent. Refreshing a graph twice produces the same output
  (modulo ``refreshedAt`` timestamps).
- All writes go through ``clear + insert`` SPARQL updates against
  the registry graph. No read-modify-write races from inside the
  library; direct backend writes by other processes will create
  drift, and ``refresh_metadata()`` exists to reconcile.
- Class-inventory records have stable IRIs derived from the graph
  IRI and a URL-safe slug of the class IRI. The slug includes a
  short hash suffix so two classes with identical local names do
  not collide.
- Backend-agnostic. Uses only the ``HolonicStore`` protocol
  (``query``, ``update``, ``list_named_graphs``, ``graph_exists``).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import quote

from holonic import sparql
from holonic.console_model import ClassInstanceCount, GraphMetadata

if TYPE_CHECKING:
    from holonic.backends.store import HolonicStore


DEFAULT_REGISTRY_IRI = "urn:holarchy:registry"


# ══════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════


def _utc_now_iso() -> str:
    """UTC timestamp, microsecond precision, ISO 8601 with trailing ``Z``."""
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


_SLUG_RE = re.compile(r"[^A-Za-z0-9_\-]+")


def _inventory_iri(graph_iri: str, class_iri: str) -> str:
    """Build a stable IRI for a ClassInstanceCount record.

    Pattern: ``<graph-iri>/inventory/<slug>-<hash>`` where ``slug``
    is the URL-safe local name of the class IRI and ``hash`` is a
    short truncated SHA-1 of the full class IRI for disambiguation.
    """
    if "#" in class_iri:
        local = class_iri.rsplit("#", 1)[-1]
    elif "/" in class_iri:
        local = class_iri.rsplit("/", 1)[-1]
    elif ":" in class_iri:
        local = class_iri.rsplit(":", 1)[-1]
    else:
        local = class_iri
    slug = _SLUG_RE.sub("-", local).strip("-") or "cls"
    digest = hashlib.sha1(class_iri.encode("utf-8")).hexdigest()[:8]
    base = graph_iri.rstrip("/")
    return f"{base}/inventory/{quote(slug, safe='-_')}-{digest}"


def _escape_literal(s: str) -> str:
    """Escape a string for use as a Turtle/SPARQL string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ══════════════════════════════════════════════════════════════
# Refresher
# ══════════════════════════════════════════════════════════════


@dataclass
class _GraphStats:
    """Internal computation result for one graph."""

    graph_iri: str
    triple_count: int
    classes: list[ClassInstanceCount]


class MetadataRefresher:
    """Computes and writes graph-level metadata to the registry graph.

    Intended to be held by a ``HolonicDataset``. Exposes two write
    entry points:

    - ``refresh_graph(graph_iri)`` -- refresh one graph only.
    - ``refresh_holon(holon_iri)`` -- refresh all layer graphs of
      one holon, then write the rolled-up per-holon metadata.

    And one read:

    - ``read(graph_iri)`` -- return the currently-materialized
      ``GraphMetadata`` for a graph.
    """

    def __init__(
        self,
        backend: HolonicStore,
        registry_iri: str = DEFAULT_REGISTRY_IRI,
    ) -> None:
        self._backend = backend
        self._registry_iri = registry_iri
        self._registry_typed = False

    def _ensure_registry_typed(self) -> None:
        """Write the registry graph's self-typing triple, once per instance.

        See D-0.3.4-7: the registry graph gets ``a cga:HolonicGraph ;
        cga:graphRole cga:RegistryRole`` on first metadata refresh so
        it is discoverable by the same type-based query pattern as
        any other graph. Idempotent at the SPARQL level; we also cache
        a flag to avoid the UPDATE round-trip on every refresh.
        """
        if self._registry_typed:
            return
        self._backend.update(
            "PREFIX cga: <urn:holonic:ontology:>\n"
            "INSERT {\n"
            f"  GRAPH <{self._registry_iri}> {{\n"
            f"    <{self._registry_iri}> a cga:HolonicGraph ;\n"
            f"        cga:graphRole cga:RegistryRole .\n"
            "  }\n"
            "}\n"
            "WHERE {\n"
            "  FILTER NOT EXISTS {\n"
            f"    GRAPH <{self._registry_iri}> {{\n"
            f"      <{self._registry_iri}> a cga:HolonicGraph .\n"
            "    }\n"
            "  }\n"
            "}\n"
        )
        self._registry_typed = True

    # ── internals ─────────────────────────────────────────────

    def _compute(self, graph_iri: str) -> _GraphStats:
        """Count triples and class instances in the target graph."""
        count_rows = self._backend.query(
            sparql.COUNT_GRAPH_TRIPLES_TEMPLATE.format(graph_iri=graph_iri)
        )
        n = int(count_rows[0]["n"]) if count_rows else 0

        type_rows = self._backend.query(
            sparql.COUNT_GRAPH_TYPES_TEMPLATE.format(graph_iri=graph_iri)
        )
        classes = [
            ClassInstanceCount(class_iri=str(r["class"]), count=int(r["n"])) for r in type_rows
        ]
        return _GraphStats(graph_iri=graph_iri, triple_count=n, classes=classes)

    def _write_graph(self, stats: _GraphStats, when_iso: str) -> None:
        """Replace the graph's metadata in one ``DELETE/INSERT/WHERE``.

        Collapses the prior clear-then-insert pair into a single UPDATE
        (audit P2): halves the round-trips on the eager per-write path and
        closes the read-then-write window between the two statements.
        """
        reg = self._registry_iri
        graph_iri = stats.graph_iri
        inventory_lines: list[str] = []
        for c in stats.classes:
            inv_iri = _inventory_iri(graph_iri, c.class_iri)
            inventory_lines.append(
                f"    <{inv_iri}> a cga:ClassInstanceCount ;\n"
                f"        cga:inGraph <{graph_iri}> ;\n"
                f"        cga:class <{c.class_iri}> ;\n"
                f"        cga:count {c.count} ;\n"
                f'        cga:refreshedAt "{when_iso}"^^xsd:dateTime .'
            )
        inventory_block = "\n".join(inventory_lines)
        # Delete the prior scalar triples + every ClassInstanceCount record
        # for this graph, then insert the freshly-computed values. DELETE is
        # evaluated before INSERT (SPARQL 1.1), so a re-inserted inventory
        # record with an unchanged IRI ends up carrying the new counts.
        update = (
            "PREFIX cga: <urn:holonic:ontology:>\n"
            "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"
            "DELETE {\n"
            f"  GRAPH <{reg}> {{\n"
            f"    <{graph_iri}> cga:tripleCount ?old_count .\n"
            f"    <{graph_iri}> cga:lastModified ?old_modified .\n"
            "    ?inv a cga:ClassInstanceCount ;\n"
            f"         cga:inGraph <{graph_iri}> ;\n"
            "         cga:class ?cls ;\n"
            "         cga:count ?n ;\n"
            "         cga:refreshedAt ?r .\n"
            "  }\n"
            "}\n"
            "INSERT {\n"
            f"  GRAPH <{reg}> {{\n"
            f"    <{graph_iri}> cga:tripleCount {stats.triple_count} ;\n"
            f'      cga:lastModified "{when_iso}"^^xsd:dateTime ;\n'
            f'      cga:refreshedAt "{when_iso}"^^xsd:dateTime .\n'
            f"{inventory_block}\n"
            "  }\n"
            "}\n"
            "WHERE {\n"
            f"  GRAPH <{reg}> {{\n"
            f"    OPTIONAL {{ <{graph_iri}> cga:tripleCount ?old_count }}\n"
            f"    OPTIONAL {{ <{graph_iri}> cga:lastModified ?old_modified }}\n"
            "    OPTIONAL {\n"
            "      ?inv a cga:ClassInstanceCount ;\n"
            f"           cga:inGraph <{graph_iri}> ;\n"
            "           cga:class ?cls ;\n"
            "           cga:count ?n .\n"
            "      OPTIONAL { ?inv cga:refreshedAt ?r }\n"
            "    }\n"
            "  }\n"
            "}\n"
        )
        self._backend.update(update)

    def _layer_graphs_of(self, holon_iri: str) -> list[str]:
        """Return all layer graph IRIs for a holon across all layers."""
        rows = self._backend.query(
            sparql.LIST_HOLON_LAYER_GRAPHS_TEMPLATE.format(holon_iri=holon_iri)
        )
        return [str(r["graph"]) for r in rows]

    def _interior_graphs_of(self, holon_iri: str) -> list[str]:
        """Return interior layer graph IRIs for a holon."""
        rows = self._backend.query(
            sparql.LIST_HOLON_INTERIOR_GRAPHS_TEMPLATE.format(holon_iri=holon_iri)
        )
        return [str(r["graph"]) for r in rows]

    def _write_holon_rollup(
        self,
        holon_iri: str,
        interior_graphs: list[str],
        layer_modified_times: list[str],
        when_iso: str,
    ) -> None:
        """Compute and persist the per-holon rollup metadata.

        - ``cga:interiorTripleCount`` -- sum across interior graphs
        - ``cga:holonLastModified`` -- max of layer lastModified
        """
        # Sum interior triples
        interior_sum = 0
        for g in interior_graphs:
            rows = self._backend.query(
                sparql.READ_GRAPH_METADATA_TEMPLATE.format(
                    registry_iri=self._registry_iri,
                    graph_iri=g,
                )
            )
            if rows and rows[0].get("triple_count") is not None:
                interior_sum += int(rows[0]["triple_count"])

        last_modified = max(layer_modified_times) if layer_modified_times else when_iso

        # Single DELETE/INSERT/WHERE replaces the prior clear-then-insert
        # pair (audit P2).
        reg = self._registry_iri
        update = (
            "PREFIX cga: <urn:holonic:ontology:>\n"
            "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"
            "DELETE {\n"
            f"  GRAPH <{reg}> {{\n"
            f"    <{holon_iri}> cga:interiorTripleCount ?old_count .\n"
            f"    <{holon_iri}> cga:holonLastModified ?old_modified .\n"
            "  }\n"
            "}\n"
            "INSERT {\n"
            f"  GRAPH <{reg}> {{\n"
            f"    <{holon_iri}> cga:interiorTripleCount {interior_sum} ;\n"
            f'      cga:holonLastModified "{last_modified}"^^xsd:dateTime .\n'
            "  }\n"
            "}\n"
            "WHERE {\n"
            f"  GRAPH <{reg}> {{\n"
            f"    OPTIONAL {{ <{holon_iri}> cga:interiorTripleCount ?old_count }}\n"
            f"    OPTIONAL {{ <{holon_iri}> cga:holonLastModified ?old_modified }}\n"
            "  }\n"
            "}\n"
        )
        self._backend.update(update)

    # ── public entry points ──────────────────────────────────

    def refresh_graph(self, graph_iri: str) -> GraphMetadata:
        """Refresh metadata for a single graph and return the new values.

        If the backing store provides a native
        ``refresh_graph_metadata(graph_iri, registry_iri)`` method,
        dispatch to it and trust its return value. Otherwise, run
        the generic Python implementation (compute + write).

        Native dispatch is duck-typed via ``hasattr`` per D-0.4.0-5
        in docs/DECISIONS.md.
        """
        # ``graph_iri`` may be store-derived (``refresh_holon`` feeds the
        # layer graphs it read back from the registry). The COUNT reads
        # bind it, but the clear/insert writes are SPARQL UPDATE and splice
        # it as text, so validate here -- the single read+write chokepoint
        # that closes second-order injection on this path (S3).
        from holonic.client import _validate_iri

        _validate_iri(graph_iri, "graph_iri")
        self._ensure_registry_typed()
        native = getattr(self._backend, "refresh_graph_metadata", None)
        if callable(native):
            # Backend handles the whole operation. Trust its return value.
            result = native(graph_iri, self._registry_iri)
            if isinstance(result, GraphMetadata):
                return result
            # Backend may return None (fire-and-forget); materialize
            # the just-written state via read() for the caller.
            return self.read(graph_iri) or GraphMetadata(iri=graph_iri)
        when = _utc_now_iso()
        stats = self._compute(graph_iri)
        self._write_graph(stats, when)
        return GraphMetadata(
            iri=graph_iri,
            triple_count=stats.triple_count,
            last_modified=when,
            refreshed_at=when,
            class_inventory=list(stats.classes),
        )

    def refresh_holon(self, holon_iri: str) -> list[GraphMetadata]:
        """Refresh all layer graphs of a holon, then the per-holon rollup."""
        from holonic.client import _validate_iri

        _validate_iri(holon_iri, "holon_iri")
        layer_graphs = self._layer_graphs_of(holon_iri)
        results: list[GraphMetadata] = []
        layer_times: list[str] = []
        for g in layer_graphs:
            md = self.refresh_graph(g)
            results.append(md)
            if md.last_modified:
                layer_times.append(md.last_modified)
        interior = self._interior_graphs_of(holon_iri)
        self._write_holon_rollup(
            holon_iri=holon_iri,
            interior_graphs=interior,
            layer_modified_times=layer_times,
            when_iso=_utc_now_iso(),
        )
        return results

    def read(self, graph_iri: str) -> GraphMetadata | None:
        """Read currently-materialized metadata for a graph.

        Returns ``None`` if no metadata has been written yet.
        """
        from holonic.client import _validate_iri

        _validate_iri(graph_iri, "graph_iri")
        scalar_rows = self._backend.query(
            sparql.READ_GRAPH_METADATA_TEMPLATE.format(
                registry_iri=self._registry_iri,
                graph_iri=graph_iri,
            )
        )
        if not scalar_rows or scalar_rows[0].get("triple_count") is None:
            return None
        count = int(scalar_rows[0]["triple_count"])
        last_modified = (
            str(scalar_rows[0]["last_modified"]) if scalar_rows[0].get("last_modified") else None
        )

        inv_rows = self._backend.query(
            sparql.READ_GRAPH_CLASS_INVENTORY_TEMPLATE.format(
                registry_iri=self._registry_iri,
                graph_iri=graph_iri,
            )
        )
        inventory = [
            ClassInstanceCount(class_iri=str(r["class"]), count=int(r["n"])) for r in inv_rows
        ]
        refreshed = None
        if inv_rows and inv_rows[0].get("refreshed_at"):
            refreshed = str(inv_rows[0]["refreshed_at"])

        return GraphMetadata(
            iri=graph_iri,
            triple_count=count,
            last_modified=last_modified,
            refreshed_at=refreshed or last_modified,
            class_inventory=inventory,
        )
