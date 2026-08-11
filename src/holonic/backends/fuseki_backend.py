"""Apache Jena Fuseki backend for holonic.

Wraps a FusekiClient (async) with synchronous methods matching the
HolonicStore protocol.

Every operation is dispatched onto a single, long-lived background event
loop running on a dedicated daemon thread (created lazily on first use).
This has two consequences the audit flagged the old ``asyncio.new_event_loop``
+ ``run_until_complete`` shape for:

* **Works inside a running event loop (C1).** ``run_until_complete`` (like
  ``asyncio.run``) refuses to start while another loop is running in the same
  thread, so every Fuseki call previously raised ``RuntimeError`` inside a
  Jupyter kernel or an async web handler. Dispatching to a separate worker
  thread via ``run_coroutine_threadsafe`` sidesteps that entirely — the
  caller's loop (if any) is never touched.
* **Reuses one client/session (P5).** The ``FusekiClient`` — and therefore its
  ``aiohttp.ClientSession`` and TCP/TLS connection pool — is opened once on
  the worker loop and reused for the backend's lifetime, instead of building
  and tearing down a session per call.

Call :meth:`close` (or use the backend as a context manager) to shut the
session and worker loop down deterministically; a ``weakref.finalize`` handler
does the same best-effort at garbage-collection time.

Requires: aiohttp
"""

from __future__ import annotations

import asyncio
import logging
import threading
import weakref
from typing import Any

from rdflib import Graph

from holonic.backends._bindings import substitute_bindings
from holonic.backends.store import AbstractHolonicStore

log = logging.getLogger(__name__)


def _shutdown_worker(loop, thread, client_box):
    """Close the pooled client (if any) and stop the worker loop/thread.

    Kept module-level (not a bound method) so :class:`weakref.finalize` can
    hold it without keeping the backend instance alive.
    """
    if loop.is_closed():
        return
    try:
        client = client_box[0]
        if client is not None:
            fut = asyncio.run_coroutine_threadsafe(client.close(), loop)
            fut.result(timeout=5)
    except Exception:  # noqa: BLE001 - shutdown is best-effort
        log.debug("Fuseki client close failed during shutdown", exc_info=True)
    finally:
        client_box[0] = None
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)


class FusekiBackend(AbstractHolonicStore):
    """HolonicStore implementation backed by an Apache Jena Fuseki server.

    Parameters
    ----------
    base_url :
        Fuseki server URL, e.g. "http://localhost:3030". Positional.
    dataset :
        Dataset name on the server. Keyword-only since 0.4.0.
    extra_headers :
        Optional HTTP headers merged into every outbound request.
    **client_kwargs :
        Extra kwargs forwarded to FusekiClient.

    .. versionchanged:: 0.4.0
       ``dataset`` is now keyword-only. Callers using the legacy
       positional form (``FusekiBackend(base_url, dataset)``)
       receive a ``TypeError``; migrate to
       ``FusekiBackend(base_url, dataset=name)``.

    .. versionchanged:: 0.8.0
       Operations now run on a long-lived worker-thread event loop with a
       pooled client/session, so the backend works inside a running event
       loop (Jupyter, async web handlers) and no longer opens a fresh
       session per call. Added :meth:`close` and context-manager support.
    """

    def __init__(
        self,
        base_url: str,
        *,
        dataset: str,
        extra_headers: dict[str, str] | None = None,
        **client_kwargs: Any,
    ):
        # Lazy import -- don't require aiohttp unless this backend is used
        from holonic.backends._fuseki_client import FusekiClient

        self.base_url = base_url
        self.dataset = dataset
        self._client_kwargs = client_kwargs
        if extra_headers:
            # Forward to FusekiClient, which merges them into every request.
            self._client_kwargs["extra_headers"] = dict(extra_headers)
        self._client_cls = FusekiClient

        # Worker loop + pooled client, all created lazily on first call.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client_box: list[Any] = [None]
        self._finalizer: weakref.finalize | None = None
        self._start_lock = threading.Lock()
        self._closed = False

    # ── Worker-loop plumbing ──────────────────────────────────
    @staticmethod
    def _loop_main(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop
        with self._start_lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                thread = threading.Thread(
                    target=self._loop_main,
                    args=(loop,),
                    name=f"fuseki-backend-{id(self):x}",
                    daemon=True,
                )
                thread.start()
                self._loop = loop
                self._thread = thread
                self._finalizer = weakref.finalize(
                    self, _shutdown_worker, loop, thread, self._client_box
                )
        return self._loop

    async def _get_client(self):
        """Return the pooled client, opening its session on first use."""
        if self._client_box[0] is None:
            client = self._client_cls(
                self.base_url,
                dataset=self.dataset,
                **self._client_kwargs,
            )
            await client.open()
            self._client_box[0] = client
        return self._client_box[0]

    def _call(self, fn):
        if self._closed:
            raise RuntimeError("FusekiBackend is closed")
        loop = self._ensure_loop()

        async def _job():
            client = await self._get_client()
            return await fn(client)

        return asyncio.run_coroutine_threadsafe(_job(), loop).result()

    # ── Lifecycle ─────────────────────────────────────────────
    def close(self) -> None:
        """Close the pooled session and stop the worker loop (idempotent)."""
        if self._finalizer is not None:
            self._finalizer()  # runs _shutdown_worker exactly once
        self._closed = True

    def __enter__(self) -> FusekiBackend:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

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
        # Fuseki speaks SPARQL-over-HTTP and cannot pre-bind, so honor
        # **bindings by safe textual substitution (n3()-escaped terms).
        # 0.7.x silently dropped bindings here (audit A2) -- corrupting
        # every parameterized call into an unfiltered scan.
        if bindings:
            sparql = substitute_bindings(sparql, bindings)

        async def _q(c):
            result = await c.query_sparql(sparql)
            rows = []
            for b in result.get("results", {}).get("bindings", []):
                rows.append({k: v["value"] for k, v in b.items()})
            return rows

        return self._call(_q)

    def construct(self, sparql: str, **bindings: Any) -> Graph:
        """Execute a CONSTRUCT query against the dataset."""
        if bindings:
            sparql = substitute_bindings(sparql, bindings)

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
        if bindings:
            sparql = substitute_bindings(sparql, bindings)

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
