"""Tests for graph-level metadata (0.3.3)."""

import time

import pytest

from holonic import HolonicDataset, RdflibBackend
from holonic._metadata import MetadataRefresher, _inventory_iri, _utc_now_iso

# ══════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════


def test_utc_now_iso_format():
    """Timestamps are UTC with microseconds and Z suffix."""
    ts = _utc_now_iso()
    assert ts.endswith("Z")
    assert "T" in ts
    # Microsecond precision — a fractional second component with 6 digits
    assert "." in ts
    frac = ts.split(".")[1].rstrip("Z")
    assert len(frac) == 6


def test_inventory_iri_is_stable():
    """Same (graph, class) pair yields the same inventory IRI."""
    a = _inventory_iri("urn:holon:x/interior", "urn:vocab:TrackMessage")
    b = _inventory_iri("urn:holon:x/interior", "urn:vocab:TrackMessage")
    assert a == b


def test_inventory_iri_disambiguates_same_local_name():
    """Two class IRIs with the same local name get different inventory IRIs."""
    a = _inventory_iri("urn:holon:x/interior", "urn:vocab:a/Record")
    b = _inventory_iri("urn:holon:x/interior", "urn:vocab:b/Record")
    assert a != b
    assert "Record" in a and "Record" in b


def test_inventory_iri_contains_graph_and_slug():
    iri = _inventory_iri("urn:holon:x/interior", "urn:vocab:TrackMessage")
    assert iri.startswith("urn:holon:x/interior/inventory/")
    assert "TrackMessage" in iri


# ══════════════════════════════════════════════════════════════
# Default mode is eager
# ══════════════════════════════════════════════════════════════


def test_default_mode_is_eager():
    ds = HolonicDataset(RdflibBackend())
    assert ds._metadata_updates == "eager"


def test_invalid_mode_raises():
    with pytest.raises(ValueError, match="metadata_updates"):
        HolonicDataset(RdflibBackend(), metadata_updates="sometimes")


# ══════════════════════════════════════════════════════════════
# Eager mode — metadata materializes on add_interior
# ══════════════════════════════════════════════════════════════


def test_eager_mode_refreshes_on_add_interior():
    ds = HolonicDataset(RdflibBackend(), metadata_updates="eager")
    ds.add_holon("urn:holon:h1", "H1")
    gi = ds.add_interior(
        "urn:holon:h1",
        """
        @prefix ex: <urn:ex:> .
        <urn:ex:a> a ex:Thing ; ex:label "A" .
        <urn:ex:b> a ex:Thing ; ex:label "B" .
        """,
    )
    md = ds.get_graph_metadata(gi)
    assert md is not None
    assert md.iri == gi
    assert md.triple_count == 4  # 2 rdf:type + 2 ex:label
    assert md.last_modified is not None
    # class inventory contains ex:Thing with count 2
    inv = {c.class_iri: c.count for c in md.class_inventory}
    assert inv.get("urn:ex:Thing") == 2


def test_eager_mode_refreshes_on_add_boundary():
    ds = HolonicDataset(RdflibBackend(), metadata_updates="eager")
    ds.add_holon("urn:holon:h1", "H1")
    gb = ds.add_boundary(
        "urn:holon:h1",
        """
        <urn:shapes:S1> a sh:NodeShape ;
            sh:targetClass <urn:ex:Thing> .
        """,
    )
    md = ds.get_graph_metadata(gb)
    assert md is not None
    # Boundary has shapes in it, so triple_count is > 0
    assert md.triple_count >= 2


# ══════════════════════════════════════════════════════════════
# Off mode — no automatic metadata
# ══════════════════════════════════════════════════════════════


def test_off_mode_suppresses_automatic_refresh():
    ds = HolonicDataset(RdflibBackend(), metadata_updates="off")
    ds.add_holon("urn:holon:h1", "H1")
    gi = ds.add_interior(
        "urn:holon:h1",
        """
        @prefix ex: <urn:ex:> .
        <urn:ex:a> a ex:Thing .
        """,
    )
    # Nothing written yet
    assert ds.get_graph_metadata(gi) is None


def test_off_mode_explicit_refresh_works():
    ds = HolonicDataset(RdflibBackend(), metadata_updates="off")
    ds.add_holon("urn:holon:h1", "H1")
    gi = ds.add_interior(
        "urn:holon:h1",
        """
        @prefix ex: <urn:ex:> .
        <urn:ex:a> a ex:Thing .
        """,
    )
    assert ds.get_graph_metadata(gi) is None
    ds.refresh_metadata("urn:holon:h1")
    md = ds.get_graph_metadata(gi)
    assert md is not None
    assert md.triple_count == 1


# ══════════════════════════════════════════════════════════════
# Refresh is idempotent
# ══════════════════════════════════════════════════════════════


def test_refresh_is_idempotent_in_counts():
    """Refreshing the same graph twice produces the same counts."""
    ds = HolonicDataset(RdflibBackend(), metadata_updates="eager")
    ds.add_holon("urn:holon:h1", "H1")
    gi = ds.add_interior(
        "urn:holon:h1",
        """
        @prefix ex: <urn:ex:> .
        <urn:ex:a> a ex:Thing .
        <urn:ex:b> a ex:Thing .
        """,
    )
    first = ds.get_graph_metadata(gi)
    # force a second refresh
    time.sleep(0.001)  # ensure a different timestamp
    ds.refresh_metadata("urn:holon:h1")
    second = ds.get_graph_metadata(gi)
    assert second is not None
    assert first is not None
    assert first.triple_count == second.triple_count
    # inventory identical modulo order
    first_inv = sorted([(c.class_iri, c.count) for c in first.class_inventory])
    second_inv = sorted([(c.class_iri, c.count) for c in second.class_inventory])
    assert first_inv == second_inv


def test_refresh_after_external_mutation_reconciles():
    """refresh_metadata picks up direct backend writes."""
    ds = HolonicDataset(RdflibBackend(), metadata_updates="eager")
    ds.add_holon("urn:holon:h1", "H1")
    gi = ds.add_interior(
        "urn:holon:h1",
        """
        @prefix ex: <urn:ex:> .
        <urn:ex:a> a ex:Thing .
        """,
    )
    assert ds.get_graph_metadata(gi).triple_count == 1

    # Direct backend write — bypasses _maybe_refresh
    ds.backend.parse_into(
        gi,
        """
        @prefix ex: <urn:ex:> .
        <urn:ex:b> a ex:Thing .
        """,
        "turtle",
    )
    # Stale — still reports 1
    assert ds.get_graph_metadata(gi).triple_count == 1

    # Explicit refresh reconciles
    ds.refresh_metadata("urn:holon:h1")
    assert ds.get_graph_metadata(gi).triple_count == 2


# ══════════════════════════════════════════════════════════════
# Class inventory correctness
# ══════════════════════════════════════════════════════════════


def test_multiple_types_in_inventory():
    ds = HolonicDataset(RdflibBackend(), metadata_updates="eager")
    ds.add_holon("urn:holon:h1", "H1")
    gi = ds.add_interior(
        "urn:holon:h1",
        """
        @prefix ex: <urn:ex:> .
        <urn:ex:1> a ex:A .
        <urn:ex:2> a ex:A .
        <urn:ex:3> a ex:A .
        <urn:ex:4> a ex:B .
        <urn:ex:5> a ex:B .
        <urn:ex:6> a ex:C .
        """,
    )
    md = ds.get_graph_metadata(gi)
    inv = {c.class_iri: c.count for c in md.class_inventory}
    assert inv == {"urn:ex:A": 3, "urn:ex:B": 2, "urn:ex:C": 1}


def test_inventory_is_replaced_not_appended():
    """Refreshing after shape change replaces inventory, not appends."""
    ds = HolonicDataset(RdflibBackend(), metadata_updates="eager")
    ds.add_holon("urn:holon:h1", "H1")
    gi = ds.add_interior(
        "urn:holon:h1",
        """
        @prefix ex: <urn:ex:> .
        <urn:ex:1> a ex:A .
        """,
    )
    first_inv = {c.class_iri for c in ds.get_graph_metadata(gi).class_inventory}
    assert first_inv == {"urn:ex:A"}

    # Replace interior entirely, re-register, then refresh
    ds.backend.delete_graph(gi)
    ds.backend.parse_into(
        gi,
        """
        @prefix ex: <urn:ex:> .
        <urn:ex:2> a ex:B .
        """,
        "turtle",
    )
    ds.refresh_metadata("urn:holon:h1")
    second_inv = {c.class_iri for c in ds.get_graph_metadata(gi).class_inventory}
    assert second_inv == {"urn:ex:B"}
    assert "urn:ex:A" not in second_inv


# ══════════════════════════════════════════════════════════════
# Per-holon rollup
# ══════════════════════════════════════════════════════════════


def test_holon_rollup_sums_multiple_interior_graphs():
    ds = HolonicDataset(RdflibBackend(), metadata_updates="eager")
    ds.add_holon("urn:holon:h1", "H1")
    g_radar = ds.add_interior(
        "urn:holon:h1",
        """
        @prefix ex: <urn:ex:> .
        <urn:ex:r1> a ex:Track .
        <urn:ex:r2> a ex:Track .
        """,
        graph_iri="urn:holon:h1/interior/radar",
    )
    g_fusion = ds.add_interior(
        "urn:holon:h1",
        """
        @prefix ex: <urn:ex:> .
        <urn:ex:f1> a ex:FusedTrack .
        """,
        graph_iri="urn:holon:h1/interior/fusion",
    )
    ds.refresh_metadata("urn:holon:h1")

    detail = ds.get_holon_detail("urn:holon:h1")
    assert detail is not None
    # 2 + 1 = 3 typed instances; each has one triple (rdf:type)
    assert detail.interior_triple_count == 3
    assert g_radar in detail.layer_metadata
    assert g_fusion in detail.layer_metadata
    assert detail.layer_metadata[g_radar].triple_count == 2
    assert detail.layer_metadata[g_fusion].triple_count == 1
    assert detail.holon_last_modified is not None


def test_refresh_all_metadata_returns_holon_count():
    ds = HolonicDataset(RdflibBackend(), metadata_updates="off")
    for i in range(3):
        iri = f"urn:holon:h{i}"
        ds.add_holon(iri, f"H{i}")
        ds.add_interior(
            iri,
            f"""
            @prefix ex: <urn:ex:> .
            <urn:ex:{i}> a ex:Thing .
            """,
        )
    count = ds.refresh_all_metadata()
    assert count == 3
    # All three should have materialized metadata
    for i in range(3):
        gi = f"urn:holon:h{i}/interior"
        assert ds.get_graph_metadata(gi) is not None


# ══════════════════════════════════════════════════════════════
# Traversal hook
# ══════════════════════════════════════════════════════════════


def test_traverse_portal_refreshes_target_metadata(ds_with_holons):
    """Traversal that injects into a graph refreshes that graph's metadata."""
    ds = ds_with_holons
    target_graph = "urn:holon:target/interior"
    ds.traverse_portal("urn:portal:src-to-tgt", inject_into=target_graph)
    md = ds.get_graph_metadata(target_graph)
    assert md is not None
    assert md.triple_count > 0


# ══════════════════════════════════════════════════════════════
# read() before any write returns None
# ══════════════════════════════════════════════════════════════


def test_read_returns_none_before_refresh():
    refresher = MetadataRefresher(RdflibBackend())
    assert refresher.read("urn:does:not:exist") is None


# ══════════════════════════════════════════════════════════════
# Refresher uses configured registry graph
# ══════════════════════════════════════════════════════════════


def test_refresher_respects_custom_registry():
    custom_registry = "urn:custom:registry"
    ds = HolonicDataset(
        RdflibBackend(),
        registry_iri=custom_registry,
        metadata_updates="eager",
    )
    ds.add_holon("urn:holon:h1", "H1")
    gi = ds.add_interior(
        "urn:holon:h1",
        """
        @prefix ex: <urn:ex:> .
        <urn:ex:a> a ex:Thing .
        """,
    )
    # The metadata should live in the custom registry graph
    rows = ds.backend.query(
        f"""
        PREFIX cga: <urn:holonic:ontology:>
        SELECT ?cnt WHERE {{
            GRAPH <{custom_registry}> {{
                <{gi}> cga:tripleCount ?cnt .
            }}
        }}
        """
    )
    assert len(rows) == 1
    assert int(rows[0]["cnt"]) == 1
