"""End-to-end integration tests for the Fuseki backend against a live server.

These exercise :class:`holonic.backends.FusekiBackend` (and, through it, the
async ``FusekiClient``) against a **real Apache Jena Fuseki** — the coverage
the audit found entirely missing (the backend shipped at 0% because every
prior Fuseki test hit ``importorskip`` and skipped).

They are marked ``integration`` and thus deselected unless ``--integration``
is passed (see ``conftest.py``). Even with ``--integration``, the module
skips itself if aiohttp is absent or the server is unreachable, so a
developer without Docker running never sees a hard failure.

Bring a server up the easy way::

    pixi run test-integration      # docker compose up + pytest --integration + down

or point at your own::

    HOLONIC_FUSEKI_URL=http://localhost:3030 pytest --integration \
        src/holonic/test/test_fuseki_integration.py
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

# aiohttp is only needed for the Fuseki backend; skip cleanly if it is not
# installed (mirrors the backend's own lazy import).
pytest.importorskip("aiohttp")

from holonic.backends import HolonicStore  # noqa: E402
from holonic.backends.fuseki_backend import FusekiBackend  # noqa: E402

FUSEKI_URL = os.environ.get("HOLONIC_FUSEKI_URL", "http://localhost:3030")
# The docker-compose harness pre-creates this in-memory dataset via the
# container command (`--mem /holonic_itest`), so the suite needs no admin
# credentials — only anonymous data/query/update endpoints. Point at your
# own server by exporting HOLONIC_FUSEKI_URL / HOLONIC_FUSEKI_DATASET, but
# then you must have created the dataset yourself.
FUSEKI_DATASET = os.environ.get("HOLONIC_FUSEKI_DATASET", "holonic_itest")


def _server_reachable(base_url: str) -> bool:
    """Return True if a Fuseki server answers at ``base_url`` quickly.

    Hits the root UI (always anonymous) rather than an admin endpoint, so
    reachability never depends on admin credentials.
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(base_url, timeout=3) as resp:  # noqa: S310
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


@pytest.fixture(scope="module")
def _live_dataset():
    """Skip the module unless the server AND the test dataset are live.

    Deliberately avoids the admin API (which requires credentials on the
    official image); the dataset is expected to already exist. Verifies it
    by issuing an anonymous ASK against the data endpoint.
    """
    if not _server_reachable(FUSEKI_URL):
        pytest.skip(f"no Fuseki server reachable at {FUSEKI_URL}")

    probe = FusekiBackend(FUSEKI_URL, dataset=FUSEKI_DATASET)
    try:
        probe.ask("ASK { ?s ?p ?o }")
    except Exception as exc:  # noqa: BLE001 - any failure ⇒ dataset unusable
        pytest.skip(f"dataset {FUSEKI_DATASET!r} not reachable on {FUSEKI_URL}: {exc}")
    return FUSEKI_DATASET


@pytest.fixture
def backend(_live_dataset):
    """A FusekiBackend on a wiped test dataset (clean before each test)."""
    be = FusekiBackend(FUSEKI_URL, dataset=_live_dataset)
    be.update("DROP ALL")
    yield be
    be.update("DROP ALL")


class TestFusekiProtocolConformance:
    def test_backend_implements_store_protocol(self, backend):
        assert isinstance(backend, HolonicStore)


class TestFusekiRoundTrip:
    def test_parse_query_roundtrip(self, backend):
        backend.parse_into(
            "urn:g:1",
            """
            @prefix ex: <urn:ex:> .
            ex:a ex:val 42 .
            ex:b ex:val 99 .
            """,
        )
        rows = backend.query(
            """
            SELECT ?s ?v WHERE {
                GRAPH <urn:g:1> { ?s <urn:ex:val> ?v }
            }
            ORDER BY ?v
            """
        )
        assert len(rows) == 2
        assert rows[0]["v"] == "42"
        assert rows[1]["v"] == "99"

    def test_graph_exists_true_and_false(self, backend):
        assert not backend.graph_exists("urn:g:missing")
        backend.parse_into("urn:g:present", "<urn:a> <urn:b> <urn:c> .")
        assert backend.graph_exists("urn:g:present")

    def test_query_with_binding(self, backend):
        # A2 end-to-end: a URIRef binding must filter server-side, proving
        # FusekiBackend honors **bindings against a real Jena (0.7.x
        # silently dropped them and returned every row).
        from rdflib import URIRef

        backend.parse_into(
            "urn:g:bind",
            """
            @prefix ex: <urn:ex:> .
            ex:alice ex:knows ex:bob .
            ex:carol ex:knows ex:dave .
            """,
        )
        rows = backend.query(
            "SELECT ?o WHERE { GRAPH <urn:g:bind> { ?s <urn:ex:knows> ?o } }",
            s=URIRef("urn:ex:alice"),
        )
        assert len(rows) == 1
        assert rows[0]["o"] == "urn:ex:bob"

    def test_construct(self, backend):
        backend.parse_into(
            "urn:g:1",
            '<urn:s> a <urn:T> ; <urn:name> "test" .',
        )
        g = backend.construct(
            """
            CONSTRUCT { ?s <urn:label> ?n }
            WHERE { GRAPH <urn:g:1> { ?s <urn:name> ?n } }
            """
        )
        assert len(g) == 1

    def test_ask_true_and_false(self, backend):
        backend.parse_into("urn:g:1", "<urn:a> <urn:b> <urn:c> .")
        assert backend.ask("ASK { GRAPH <urn:g:1> { <urn:a> <urn:b> <urn:c> } }")
        assert not backend.ask("ASK { GRAPH <urn:g:1> { <urn:x> <urn:y> <urn:z> } }")

    def test_update_then_query(self, backend):
        backend.update('INSERT DATA { GRAPH <urn:g:new> { <urn:a> <urn:b> "inserted" } }')
        assert backend.graph_exists("urn:g:new")
        rows = backend.query("SELECT ?o WHERE { GRAPH <urn:g:new> { <urn:a> <urn:b> ?o } }")
        assert len(rows) == 1
        assert rows[0]["o"] == "inserted"

    def test_put_replaces_and_delete(self, backend):
        from rdflib import Graph, URIRef

        backend.parse_into("urn:g:1", "<urn:a> <urn:b> <urn:c> .")
        g2 = Graph()
        g2.add((URIRef("urn:x"), URIRef("urn:y"), URIRef("urn:z")))
        backend.put_graph("urn:g:1", g2)
        got = backend.get_graph("urn:g:1")
        assert (URIRef("urn:x"), URIRef("urn:y"), URIRef("urn:z")) in got
        assert (URIRef("urn:a"), URIRef("urn:b"), URIRef("urn:c")) not in got

        backend.delete_graph("urn:g:1")
        assert not backend.graph_exists("urn:g:1")

    def test_list_named_graphs(self, backend):
        backend.parse_into("urn:g:alpha", "<urn:a> <urn:b> <urn:c> .")
        backend.parse_into("urn:g:beta", "<urn:x> <urn:y> <urn:z> .")
        graphs = backend.list_named_graphs()
        assert "urn:g:alpha" in graphs
        assert "urn:g:beta" in graphs
