"""Tests for 0.5.0 removal of deprecated names and new deprecations."""

import warnings

import pytest

from holonic import HolonicDataset, RdflibBackend
from holonic._metadata import MetadataRefresher

# ══════════════════════════════════════════════════════════════
# GraphBackend alias — REMOVED in 0.5.0
# ══════════════════════════════════════════════════════════════


def test_graphbackend_removed_from_holonic():
    """``holonic.GraphBackend`` was removed in 0.5.0."""
    import holonic

    with pytest.raises(AttributeError, match="GraphBackend"):
        _ = holonic.GraphBackend


def test_graphbackend_removed_from_backends_protocol():
    """``holonic.backends.protocol.GraphBackend`` was removed in 0.5.0."""
    import holonic.backends.protocol as legacy

    with pytest.raises(AttributeError, match="GraphBackend"):
        _ = legacy.GraphBackend


def test_unknown_attribute_raises_attribute_error():
    """Module __getattr__ doesn't swallow real AttributeErrors."""
    import holonic

    with pytest.raises(AttributeError, match="NoSuchThing"):
        _ = holonic.NoSuchThing


# ══════════════════════════════════════════════════════════════
# registry_graph — REMOVED in 0.5.0
# ══════════════════════════════════════════════════════════════


def test_registry_graph_kwarg_removed():
    """``registry_graph=`` kwarg was removed in 0.5.0."""
    with pytest.raises(TypeError):
        HolonicDataset(registry_graph="urn:custom:reg")


def test_registry_graph_property_removed():
    """``ds.registry_graph`` property was removed in 0.5.0."""
    ds = HolonicDataset()
    with pytest.raises(AttributeError):
        _ = ds.registry_graph


def test_registry_iri_is_canonical_name():
    """The canonical ``registry_iri=`` parameter works without warnings."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        ds = HolonicDataset(registry_iri="urn:custom:reg")
    assert ds.registry_iri == "urn:custom:reg"
    assert not any(
        issubclass(warning.category, DeprecationWarning)
        and "registry" in str(warning.message).lower()
        for warning in w
    )


# ══════════════════════════════════════════════════════════════
# holon_type kwarg (new in 0.5.0)
# ══════════════════════════════════════════════════════════════


def test_add_holon_with_holon_type():
    """``add_holon(holon_type=...)`` asserts the subtype in the registry."""
    ds = HolonicDataset()
    ds.add_holon("urn:holon:agent", "Agent", holon_type="cga:AgentHolon")

    result = ds.backend.ask("""
        ASK {
            GRAPH ?g {
                <urn:holon:agent> a <urn:holonic:ontology:AgentHolon> .
            }
        }
    """)
    assert result


def test_add_holon_without_holon_type():
    """Without ``holon_type``, only ``cga:Holon`` is asserted."""
    ds = HolonicDataset()
    ds.add_holon("urn:holon:plain", "Plain")

    types = ds.backend.query("""
        SELECT ?type WHERE {
            GRAPH ?g {
                <urn:holon:plain> a ?type .
            }
        }
    """)
    type_iris = [r["type"] for r in types]
    assert "urn:holonic:ontology:Holon" in type_iris
    assert "urn:holonic:ontology:AgentHolon" not in type_iris


# ══════════════════════════════════════════════════════════════
# iter_* generators (new in 0.5.0)
# ══════════════════════════════════════════════════════════════


def test_iter_holons_yields_same_as_list_holons():
    """``iter_holons()`` yields the same results as ``list_holons()``."""
    ds = HolonicDataset()
    ds.add_holon("urn:holon:a", "A")
    ds.add_holon("urn:holon:b", "B")

    from_list = ds.list_holons()
    from_iter = list(ds.iter_holons())

    assert len(from_list) == len(from_iter) == 2
    assert {h.iri for h in from_list} == {h.iri for h in from_iter}


def test_iter_portals_from_yields_same_as_find():
    """``iter_portals_from()`` yields same results as ``find_portals_from()``."""
    ds = HolonicDataset()
    ds.add_holon("urn:holon:a", "A")
    ds.add_holon("urn:holon:b", "B")
    ds.add_portal(
        "urn:portal:ab",
        "urn:holon:a",
        "urn:holon:b",
        "CONSTRUCT { ?s ?p ?o } WHERE { GRAPH ?g { ?s ?p ?o } }",
    )

    from_find = ds.find_portals_from("urn:holon:a")
    from_iter = list(ds.iter_portals_from("urn:holon:a"))

    assert len(from_find) == len(from_iter) == 1
    assert from_find[0].iri == from_iter[0].iri


# ══════════════════════════════════════════════════════════════
# Fuseki keyword-only dataset
# ══════════════════════════════════════════════════════════════


def test_fuseki_positional_dataset_raises():
    """``FusekiBackend(url, name)`` without aiohttp or kwarg fails cleanly."""
    pytest.importorskip("aiohttp")
    from holonic.backends.fuseki_backend import FusekiBackend

    with pytest.raises(TypeError):
        FusekiBackend("http://fuseki.test:3030", "ds")


def test_fuseki_keyword_dataset_works():
    """The keyword form is canonical since 0.4.0."""
    pytest.importorskip("aiohttp")
    from holonic.backends.fuseki_backend import FusekiBackend

    backend = FusekiBackend("http://fuseki.test:3030", dataset="ds")
    assert backend.dataset == "ds"


# ══════════════════════════════════════════════════════════════
# Native dispatch hook
# ══════════════════════════════════════════════════════════════


class _NativeStore:
    """Test double that wraps RdflibBackend and adds a native hook.

    Tracks how many times the native method was called, so the test
    can verify dispatch actually happened.
    """

    def __init__(self):
        self._inner = RdflibBackend()
        self.native_calls: list[tuple[str, str]] = []

    def refresh_graph_metadata(self, graph_iri: str, registry_iri: str):
        """Native hook — just record the call, return None."""
        self.native_calls.append((graph_iri, registry_iri))
        # Return None to exercise the "materialize via read()" fallback
        return None

    def __getattr__(self, name):
        # Proxy everything else to the inner rdflib backend
        return getattr(self._inner, name)


def test_metadata_refresher_dispatches_to_native():
    """MetadataRefresher.refresh_graph uses native hook when available."""
    store = _NativeStore()
    ds = HolonicDataset(store)
    ds.add_holon("urn:holon:h1", "H1")
    # add_interior triggers _maybe_refresh which calls refresh_graph
    ds.add_interior(
        "urn:holon:h1",
        "@prefix ex: <urn:ex:> . <urn:ex:a> a ex:Thing .",
    )
    # Native method was called
    assert len(store.native_calls) >= 1
    graph_iri, registry_iri = store.native_calls[-1]
    assert graph_iri == "urn:holon:h1/interior"
    assert registry_iri == ds.registry_iri


def test_metadata_refresher_falls_back_without_native():
    """A store without the native method uses the generic Python path."""
    store = RdflibBackend()
    refresher = MetadataRefresher(backend=store, registry_iri="urn:holarchy:registry")
    assert not hasattr(store, "refresh_graph_metadata")
    # Seed a graph and verify the generic path produces metadata
    store.parse_into(
        "urn:test:g",
        "@prefix ex: <urn:ex:> . <urn:ex:a> a ex:Thing .",
        "turtle",
    )
    md = refresher.refresh_graph("urn:test:g")
    assert md.triple_count == 1
    assert md.last_modified is not None


# ══════════════════════════════════════════════════════════════
# Pagination (0.5.0)
# ══════════════════════════════════════════════════════════════


def test_list_holons_pagination():
    """limit and offset work on list_holons."""
    ds = HolonicDataset()
    for i in range(5):
        ds.add_holon(f"urn:holon:{i}", f"H{i}")

    all_holons = ds.list_holons()
    assert len(all_holons) == 5

    page1 = ds.list_holons(limit=2)
    assert len(page1) == 2

    page2 = ds.list_holons(limit=2, offset=2)
    assert len(page2) == 2

    page3 = ds.list_holons(limit=2, offset=4)
    assert len(page3) == 1

    # All IRIs covered across pages
    paged_iris = {h.iri for h in page1 + page2 + page3}
    all_iris = {h.iri for h in all_holons}
    assert paged_iris == all_iris


def test_iter_holons_pagination():
    """limit and offset work on iter_holons generator."""
    ds = HolonicDataset()
    for i in range(5):
        ds.add_holon(f"urn:holon:{i}", f"H{i}")

    from_iter = list(ds.iter_holons(limit=3))
    assert len(from_iter) == 3


def test_find_portals_from_pagination():
    """limit works on find_portals_from."""
    ds = HolonicDataset()
    ds.add_holon("urn:holon:src", "Source")
    for i in range(4):
        ds.add_holon(f"urn:holon:tgt{i}", f"T{i}")
        ds.add_portal(
            f"urn:portal:{i}",
            "urn:holon:src",
            f"urn:holon:tgt{i}",
            "CONSTRUCT { ?s ?p ?o } WHERE { GRAPH ?g { ?s ?p ?o } }",
        )

    all_portals = ds.find_portals_from("urn:holon:src")
    assert len(all_portals) == 4

    page = ds.find_portals_from("urn:holon:src", limit=2)
    assert len(page) == 2


# ══════════════════════════════════════════════════════════════
# Bulk load (0.5.0)
# ══════════════════════════════════════════════════════════════


def test_bulk_load_holons():
    """bulk_load creates multiple holons in one batch."""
    ds = HolonicDataset()
    n_holons, n_portals = ds.bulk_load(
        holons=[
            {"iri": "urn:holon:a", "label": "A"},
            {"iri": "urn:holon:b", "label": "B", "member_of": "urn:holon:a"},
            {"iri": "urn:holon:c", "label": "C", "holon_type": "cga:DataHolon"},
        ],
    )
    assert n_holons == 3
    assert n_portals == 0
    assert len(ds.list_holons()) == 3

    # holon_type was applied
    result = ds.backend.ask("""
        ASK {
            GRAPH ?g {
                <urn:holon:c> a <urn:holonic:ontology:DataHolon> .
            }
        }
    """)
    assert result


def test_bulk_load_holons_and_portals():
    """bulk_load creates holons and portals together."""
    ds = HolonicDataset()
    n_holons, n_portals = ds.bulk_load(
        holons=[
            {"iri": "urn:holon:x", "label": "X"},
            {"iri": "urn:holon:y", "label": "Y"},
        ],
        portals=[
            {
                "iri": "urn:portal:xy",
                "source_iri": "urn:holon:x",
                "target_iri": "urn:holon:y",
                "construct_query": "CONSTRUCT { ?s ?p ?o } WHERE { GRAPH ?g { ?s ?p ?o } }",
            },
        ],
    )
    assert n_holons == 2
    assert n_portals == 1
    assert len(ds.find_portals_from("urn:holon:x")) == 1


def test_bulk_load_empty():
    """bulk_load with no arguments is a no-op."""
    ds = HolonicDataset()
    n_holons, n_portals = ds.bulk_load()
    assert n_holons == 0
    assert n_portals == 0
