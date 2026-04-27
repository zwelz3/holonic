"""Tests for scoped discovery (0.3.4)."""

import pytest

from holonic import (
    CustomSPARQL,
    HasClassInInterior,
    HolonicDataset,
    RdflibBackend,
    ResolveMatch,
    ScopeResolver,
)

# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════


def _portal_from(ds, source, target, label=None):
    """Register a minimal passthrough portal between two holons."""
    construct = """
        CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }
    """
    portal_iri = f"urn:portal:{source.rsplit(':', 1)[-1]}-to-{target.rsplit(':', 1)[-1]}"
    ds.add_portal(portal_iri, source, target, construct, label=label or portal_iri)


@pytest.fixture
def linear_chain():
    """A → B → C → D. Each holon has an interior with one rdf:type."""
    ds = HolonicDataset(RdflibBackend())
    for name, cls in [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma"), ("d", "Delta")]:
        ds.add_holon(f"urn:holon:{name}", name.upper())
        ds.add_interior(
            f"urn:holon:{name}",
            f"""
            @prefix ex: <urn:ex:> .
            <urn:entity:{name}> a ex:{cls} .
            """,
        )
    _portal_from(ds, "urn:holon:a", "urn:holon:b")
    _portal_from(ds, "urn:holon:b", "urn:holon:c")
    _portal_from(ds, "urn:holon:c", "urn:holon:d")
    return ds


@pytest.fixture
def star_topology():
    """One hub with 3 spokes; no inter-spoke portals."""
    ds = HolonicDataset(RdflibBackend())
    ds.add_holon("urn:holon:hub", "Hub")
    ds.add_interior(
        "urn:holon:hub",
        "@prefix ex: <urn:ex:> . <urn:entity:h> a ex:Hub .",
    )
    for spoke in ("one", "two", "three"):
        ds.add_holon(f"urn:holon:{spoke}", spoke.title())
        ds.add_interior(
            f"urn:holon:{spoke}",
            f"""
            @prefix ex: <urn:ex:> .
            <urn:entity:{spoke}> a ex:Spoke .
            """,
        )
        _portal_from(ds, "urn:holon:hub", f"urn:holon:{spoke}")
    return ds


# ══════════════════════════════════════════════════════════════
# HasClassInInterior predicate
# ══════════════════════════════════════════════════════════════


def test_resolve_finds_starting_holon(linear_chain):
    ds = linear_chain
    matches = ds.resolve(
        HasClassInInterior("urn:ex:Alpha"),
        from_holon="urn:holon:a",
    )
    assert len(matches) == 1
    assert matches[0].iri == "urn:holon:a"
    assert matches[0].distance == 0


def test_resolve_walks_outbound_portals(linear_chain):
    ds = linear_chain
    # Starting from A, looking for something in C's interior (2 hops away)
    matches = ds.resolve(
        HasClassInInterior("urn:ex:Gamma"),
        from_holon="urn:holon:a",
        max_depth=3,
    )
    assert len(matches) == 1
    assert matches[0].iri == "urn:holon:c"
    assert matches[0].distance == 2


def test_resolve_respects_max_depth(linear_chain):
    ds = linear_chain
    # D is 3 hops from A; max_depth=2 should miss it
    matches = ds.resolve(
        HasClassInInterior("urn:ex:Delta"),
        from_holon="urn:holon:a",
        max_depth=2,
    )
    assert matches == []


def test_resolve_returns_matches_in_bfs_order(star_topology):
    ds = star_topology

    # Match anything typed ex:Spoke; from hub, all three are 1 hop away
    matches = ds.resolve(
        HasClassInInterior("urn:ex:Spoke"),
        from_holon="urn:holon:hub",
        max_depth=2,
    )
    assert len(matches) == 3
    # All should be at distance 1 — before hub matches itself (0) if hub
    # had been Spoke-typed, which it isn't
    for m in matches:
        assert m.distance == 1
    # Within the hop, sorted alphabetically by IRI per the walk query's ORDER BY
    iris = [m.iri for m in matches]
    assert iris == sorted(iris)


def test_resolve_limit_truncates(star_topology):
    ds = star_topology
    matches = ds.resolve(
        HasClassInInterior("urn:ex:Spoke"),
        from_holon="urn:holon:hub",
        limit=2,
    )
    assert len(matches) == 2


def test_resolve_no_matches_returns_empty(linear_chain):
    ds = linear_chain
    matches = ds.resolve(
        HasClassInInterior("urn:ex:Nonexistent"),
        from_holon="urn:holon:a",
    )
    assert matches == []


def test_resolve_starting_holon_unknown_still_works(linear_chain):
    """Calling resolve from a non-existent holon yields no matches, no error."""
    ds = linear_chain
    matches = ds.resolve(
        HasClassInInterior("urn:ex:Alpha"),
        from_holon="urn:holon:phantom",
    )
    assert matches == []


# ══════════════════════════════════════════════════════════════
# Order modes
# ══════════════════════════════════════════════════════════════


def test_reverse_network_only_follows_inbound(linear_chain):
    """From D, reverse-network walk reaches C, B, A via inbound portals."""
    ds = linear_chain
    matches = ds.resolve(
        HasClassInInterior("urn:ex:Alpha"),
        from_holon="urn:holon:d",
        order="reverse-network",
        max_depth=5,
    )
    assert len(matches) == 1
    assert matches[0].iri == "urn:holon:a"
    assert matches[0].distance == 3


def test_network_order_default(linear_chain):
    ds = linear_chain
    matches = ds.resolve(
        HasClassInInterior("urn:ex:Alpha"),
        from_holon="urn:holon:a",
    )
    assert matches[0].distance == 0


def test_containment_walks_member_of():
    ds = HolonicDataset(RdflibBackend())
    ds.add_holon("urn:holon:parent", "Parent")
    ds.add_holon("urn:holon:child", "Child", member_of="urn:holon:parent")
    ds.add_interior(
        "urn:holon:parent",
        "@prefix ex: <urn:ex:> . <urn:entity:p> a ex:ParentClass .",
    )
    ds.add_interior(
        "urn:holon:child",
        "@prefix ex: <urn:ex:> . <urn:entity:c> a ex:ChildClass .",
    )

    matches = ds.resolve(
        HasClassInInterior("urn:ex:ParentClass"),
        from_holon="urn:holon:child",
        order="containment",
    )
    assert len(matches) == 1
    assert matches[0].iri == "urn:holon:parent"
    assert matches[0].distance == 1


def test_invalid_order_raises(linear_chain):
    ds = linear_chain
    with pytest.raises(ValueError, match="unknown order"):
        ds.resolve(
            HasClassInInterior("urn:ex:Alpha"),
            from_holon="urn:holon:a",
            order="sideways",
        )


# ══════════════════════════════════════════════════════════════
# CustomSPARQL escape hatch
# ══════════════════════════════════════════════════════════════


def test_custom_sparql_predicate(linear_chain):
    """CustomSPARQL can inspect arbitrary holon properties via ASK."""
    ds = linear_chain
    template = """
        PREFIX cga:  <urn:holonic:ontology:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        ASK WHERE {
            GRAPH ?g {
                <{holon_iri}> rdfs:label "B" .
            }
        }
    """
    matches = ds.resolve(
        CustomSPARQL(template),
        from_holon="urn:holon:a",
        max_depth=3,
    )
    assert len(matches) == 1
    assert matches[0].iri == "urn:holon:b"


# ══════════════════════════════════════════════════════════════
# Clamps
# ══════════════════════════════════════════════════════════════


def test_max_depth_clamped_to_zero_floor(linear_chain):
    ds = linear_chain
    # Negative max_depth clamps to 0 — starting holon only
    matches = ds.resolve(
        HasClassInInterior("urn:ex:Alpha"),
        from_holon="urn:holon:a",
        max_depth=-5,
    )
    assert len(matches) == 1
    assert matches[0].distance == 0


def test_limit_clamped_to_one_floor(star_topology):
    ds = star_topology
    matches = ds.resolve(
        HasClassInInterior("urn:ex:Spoke"),
        from_holon="urn:holon:hub",
        limit=0,
    )
    # Clamped to 1
    assert len(matches) == 1


# ══════════════════════════════════════════════════════════════
# ScopeResolver used standalone
# ══════════════════════════════════════════════════════════════


def test_scope_resolver_standalone(linear_chain):
    ds = linear_chain
    resolver = ScopeResolver(backend=ds.backend, registry_iri=ds.registry_iri)
    matches = resolver.resolve(
        HasClassInInterior("urn:ex:Beta"),
        from_holon="urn:holon:a",
    )
    assert len(matches) == 1
    assert isinstance(matches[0], ResolveMatch)
