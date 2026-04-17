"""Tests for 0.4.0 deprecation behavior and native-dispatch hooks."""

import os
import warnings

import pytest

from holonic import HolonicDataset, HolonicStore, RdflibBackend
from holonic._metadata import MetadataRefresher

# ══════════════════════════════════════════════════════════════
# GraphBackend deprecation alias
# ══════════════════════════════════════════════════════════════


def test_graphbackend_importable_from_holonic():
    """Top-level ``from holonic import GraphBackend`` still works."""
    import holonic

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        # Force cache reset so we see the warning
        holonic._GRAPHBACKEND_WARNED = False
        old_env = os.environ.pop("HOLONIC_SILENCE_DEPRECATION", None)
        try:
            alias = holonic.GraphBackend
        finally:
            if old_env is not None:
                os.environ["HOLONIC_SILENCE_DEPRECATION"] = old_env

    assert alias is HolonicStore
    assert any(issubclass(warning.category, DeprecationWarning) for warning in w)


def test_graphbackend_importable_from_backends_protocol():
    """Legacy ``from holonic.backends.protocol import GraphBackend`` works."""
    import holonic.backends.protocol as legacy

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        legacy._WARNED = False
        old_env = os.environ.pop("HOLONIC_SILENCE_DEPRECATION", None)
        try:
            alias = legacy.GraphBackend
        finally:
            if old_env is not None:
                os.environ["HOLONIC_SILENCE_DEPRECATION"] = old_env

    assert alias is HolonicStore
    assert any(issubclass(warning.category, DeprecationWarning) for warning in w)


def test_graphbackend_suppression_env_var():
    """HOLONIC_SILENCE_DEPRECATION=1 suppresses the warning."""
    import holonic

    holonic._GRAPHBACKEND_WARNED = False
    os.environ["HOLONIC_SILENCE_DEPRECATION"] = "1"
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _ = holonic.GraphBackend
        dep_warnings = [
            warning for warning in w if issubclass(warning.category, DeprecationWarning)
        ]
        assert dep_warnings == []
    finally:
        os.environ.pop("HOLONIC_SILENCE_DEPRECATION", None)


def test_graphbackend_still_usable_for_isinstance():
    """``isinstance(backend, GraphBackend)`` still works as an alias."""
    import holonic

    holonic._GRAPHBACKEND_WARNED = False
    os.environ["HOLONIC_SILENCE_DEPRECATION"] = "1"
    try:
        GraphBackend = holonic.GraphBackend
        backend = RdflibBackend()
        assert isinstance(backend, GraphBackend)
    finally:
        os.environ.pop("HOLONIC_SILENCE_DEPRECATION", None)


def test_unknown_attribute_raises_attribute_error():
    """The __getattr__ shim doesn't swallow real AttributeErrors."""
    import holonic

    with pytest.raises(AttributeError, match="NoSuchThing"):
        _ = holonic.NoSuchThing


# ══════════════════════════════════════════════════════════════
# registry_graph -> registry_iri deprecation
# ══════════════════════════════════════════════════════════════


def test_registry_graph_kwarg_still_works():
    """Old ``registry_graph=`` parameter still works with a warning."""
    os.environ.pop("HOLONIC_SILENCE_DEPRECATION", None)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        ds = HolonicDataset(registry_graph="urn:custom:reg")
    assert ds.registry_iri == "urn:custom:reg"
    assert any(
        issubclass(warning.category, DeprecationWarning)
        and "registry_graph" in str(warning.message)
        for warning in w
    )


def test_registry_iri_is_canonical_name():
    """The new ``registry_iri=`` parameter does not warn."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        ds = HolonicDataset(registry_iri="urn:custom:reg")
    assert ds.registry_iri == "urn:custom:reg"
    assert not any(
        issubclass(warning.category, DeprecationWarning)
        and "registry" in str(warning.message).lower()
        for warning in w
    )


def test_registry_graph_property_alias_no_warning():
    """Reading ``ds.registry_graph`` is silent (attribute access, not kwarg)."""
    ds = HolonicDataset(registry_iri="urn:custom:reg")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        value = ds.registry_graph
    assert value == "urn:custom:reg"
    assert not any(issubclass(warning.category, DeprecationWarning) for warning in w)


def test_registry_conflict_raises():
    """Passing both names is an error."""
    with pytest.raises(ValueError, match="Cannot pass both"):
        HolonicDataset(
            registry_iri="urn:a",
            registry_graph="urn:b",
        )


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
