"""Apache Jena Fuseki backend for holonic.

Wraps a FusekiClient (async) with synchronous methods matching the
GraphBackend protocol.  Uses asyncio.run() for sync callers; for
async usage, call the underlying client directly.

Requires: aiohttp
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rdflib import Graph

log = logging.getLogger(__name__)


def _get_or_create_loop():
    """Get the running event loop or create one."""
    try:
        _loop = asyncio.get_running_loop()
        # We're inside an async context — can't use asyncio.run()
        raise RuntimeError(
            "FusekiBackend sync methods cannot be called from within "
            "an async context.  Use FusekiBackendAsync directly."
        )
    except RuntimeError:
        pass
    return asyncio.new_event_loop()


class FusekiBackend:
    """GraphBackend implementation backed by an Apache Jena Fuseki server.

    Parameters
    ----------
    base_url :
        Fuseki server URL, e.g. "http://localhost:3030".
    dataset :
        Dataset name on the server.
    client_kwargs :
        Extra kwargs forwarded to FusekiClient.
    """

    def __init__(
        self,
        base_url: str,
        dataset: str,
        **client_kwargs: Any,
    ):
        # Lazy import — don't require aiohttp unless this backend is used
        from holonic.backends._fuseki_client import FusekiClient

        self.base_url = base_url
        self.dataset = dataset
        self._client_kwargs = client_kwargs
        self._client_cls = FusekiClient

    def _run(self, coro):
        """Run an async coroutine synchronously."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    async def _with_client(self, fn):
        """Create a client session, run fn, close."""
        client = self._client_cls(
            self.base_url,
            dataset=self.dataset,
            **self._client_kwargs,
        )
        async with client as c:
            return await fn(c)

    def _call(self, fn):
        return self._run(self._with_client(fn))

    # ── Named-graph CRUD ──────────────────────────────────────
    def graph_exists(self, graph_iri: str) -> bool:
        """Check if named graph exists in the dataset."""
        return self._call(lambda c: c.graph_exists(graph_iri))

    def get_graph(self, graph_iri: str) -> Graph:
        """Return named graph in dataset."""
        return self._call(lambda c: c.get_graph(graph_iri))

    def put_graph(self, graph_iri: str, g: Graph) -> None:
        """Replace graph data from named graph to dataset."""
        self._call(lambda c: c.put_graph(graph_iri, g))

    def post_graph(self, graph_iri: str, g: Graph) -> None:
        """Add graph data from named graph to dataset."""
        self._call(lambda c: c.post_graph(graph_iri, g))

    def delete_graph(self, graph_iri: str) -> None:
        """Remove graph from dataset."""
        self._call(lambda c: c.delete_graph(graph_iri))

    def parse_into(self, graph_iri: str, data: str, format: str = "turtle") -> None:
        """Add data to graph and post to the dataset."""
        g = Graph()
        g.parse(data=data, format=format)
        self.post_graph(graph_iri, g)

    # ── SPARQL ────────────────────────────────────────────────

    def query(self, sparql: str, **bindings: Any) -> list[dict[str, Any]]:
        """Execute a query against the dataset."""

        async def _q(c):
            result = await c.query_sparql(sparql)
            rows = []
            for b in result.get("results", {}).get("bindings", []):
                rows.append({k: v["value"] for k, v in b.items()})
            return rows

        return self._call(_q)

    def construct(self, sparql: str, **bindings: Any) -> Graph:
        """Execute a CONSTRUCT query against the dataset."""

        async def _q(c):
            result = await c.query_sparql(sparql, accept="text/turtle")
            g = Graph()
            raw = result.get("raw", "")
            if raw:
                g.parse(data=raw, format="turtle")
            return g

        return self._call(_q)

    def ask(self, sparql: str, **bindings: Any) -> bool:
        """Execute an ASK query against the dataset."""

        async def _q(c):
            result = await c.query_sparql(sparql)
            return result.get("boolean", False)

        return self._call(_q)

    def update(self, sparql: str) -> None:
        """Update dataset with SPARQL string."""
        self._call(lambda c: c.update_sparql(sparql))

    # ── Utility ───────────────────────────────────────────────

    def list_named_graphs(self) -> list[str]:
        """List all named graphs in the dataset."""

        async def _q(c):
            return await c.list_named_graphs()

        return self._call(_q)
