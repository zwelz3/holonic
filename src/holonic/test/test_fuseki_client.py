"""Unit tests for the async FusekiClient wiring (no live server).

These check construction-time behaviour only -- the request timeout the
audit found missing (cli-config/no-request-timeout). End-to-end behaviour
against a real server lives in test_fuseki_integration.py.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("aiohttp")

import aiohttp  # noqa: E402

from holonic.backends._fuseki_client import FusekiClient  # noqa: E402


class TestFusekiBindingsOnTheWire:
    """A2: FusekiBackend must honor **bindings, not silently drop them.

    0.7.x sent the template verbatim, turning a parameterized lookup into
    an unfiltered scan. We capture the SPARQL the backend hands to the
    async client by patching ``query_sparql`` -- no live server, and no
    dependency on aioresponses (which is currently incompatible with the
    installed aiohttp). End-to-end wire behaviour is covered separately by
    the dockerized-Jena integration suite.
    """

    def _run_capture(self, method, sparql, **bindings):
        from unittest.mock import patch

        from holonic.backends._fuseki_client import FusekiClient
        from holonic.backends.fuseki_backend import FusekiBackend

        captured = {}

        async def fake_query(self, query, *, accept="application/sparql-results+json"):
            captured["query"] = query
            return {"boolean": False, "results": {"bindings": []}, "raw": ""}

        with patch.object(FusekiClient, "query_sparql", fake_query):
            be = FusekiBackend("http://localhost:3030", dataset="ds")
            try:
                getattr(be, method)(sparql, **bindings)
            finally:
                be.close()  # release the pooled worker loop + session
        return captured["query"]

    def test_query_binding_substituted_into_wire_sparql(self):
        from rdflib import URIRef

        sent = self._run_capture(
            "query",
            "SELECT ?o WHERE { GRAPH <urn:g> { ?s <urn:p> ?o } }",
            s=URIRef("urn:subject:x"),
        )
        assert "<urn:subject:x>" in sent
        # The variable is gone -- it was bound, not left to scan freely.
        assert "?s " not in sent

    def test_ask_binding_substituted(self):
        from rdflib import URIRef

        sent = self._run_capture(
            "ask",
            "ASK { GRAPH <urn:g> { ?s <urn:p> <urn:o> } }",
            s=URIRef("urn:subject:y"),
        )
        assert "<urn:subject:y>" in sent
        assert "?s " not in sent

    def test_no_bindings_leaves_query_untouched(self):
        template = "SELECT ?s WHERE { GRAPH <urn:g> { ?s <urn:p> <urn:o> } }"
        sent = self._run_capture("query", template)
        assert sent == template


class TestTimeoutWiring:
    def test_default_timeout_installed(self):
        # A default session-level timeout must be present so every request
        # is bounded and the 5xx/timeout retry loop is actually reachable.
        client = FusekiClient("http://localhost:3030", dataset="ds")
        timeout = client._session_kwargs.get("timeout")
        assert isinstance(timeout, aiohttp.ClientTimeout)
        assert timeout.total == 30.0

    def test_custom_timeout(self):
        client = FusekiClient("http://localhost:3030", dataset="ds", timeout=5)
        assert client._session_kwargs["timeout"].total == 5.0

    def test_timeout_none_disables_default(self):
        client = FusekiClient("http://localhost:3030", dataset="ds", timeout=None)
        assert "timeout" not in client._session_kwargs

    def test_explicit_session_kwarg_timeout_wins(self):
        explicit = aiohttp.ClientTimeout(total=99)
        client = FusekiClient(
            "http://localhost:3030",
            dataset="ds",
            session_kwargs={"timeout": explicit},
            timeout=5,
        )
        assert client._session_kwargs["timeout"] is explicit


class TestRunsInsideRunningLoop:
    """C1: FusekiBackend must not raise inside an already-running event loop.

    The old ``asyncio.new_event_loop().run_until_complete`` shape raised
    ``RuntimeError: Cannot run the event loop while another loop is running``
    from any Jupyter kernel or async web handler. The worker-thread dispatch
    fixes it; this reproduces the exact failure mode with a stubbed client.
    """

    def _make_backend(self):
        from unittest.mock import patch

        from holonic.backends._fuseki_client import FusekiClient
        from holonic.backends.fuseki_backend import FusekiBackend

        async def fake_query(self, query, *, accept="application/sparql-results+json"):
            return {"boolean": True, "results": {"bindings": []}, "raw": ""}

        return patch.object(FusekiClient, "query_sparql", fake_query), FusekiBackend

    def test_ask_inside_asyncio_run(self):
        patcher, FusekiBackend = self._make_backend()
        with patcher:
            be = FusekiBackend("http://localhost:3030", dataset="ds")

            async def main():
                # Blocking sync call from inside a running loop -- this is the
                # Jupyter / FastAPI scenario that used to raise RuntimeError.
                return be.ask("ASK { ?s ?p ?o }")

            try:
                result = asyncio.run(main())
            finally:
                be.close()
        assert result is True

    def test_close_is_idempotent(self):
        patcher, FusekiBackend = self._make_backend()
        with patcher:
            be = FusekiBackend("http://localhost:3030", dataset="ds")
            be.ask("ASK { ?s ?p ?o }")
            be.close()
            be.close()  # second close must not raise
        with pytest.raises(RuntimeError, match="closed"):
            be.ask("ASK { ?s ?p ?o }")
