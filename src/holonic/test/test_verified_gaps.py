"""Tests for desired behavior that holonic v0.5.0 does not yet provide.

Every test in this file FAILS under v0.5.0. Each describes the correct
behavior that a fix should produce. Once the fix lands, the test becomes
a regression guard.

Each test class corresponds to a numbered finding in the companion
report ``holonic_feature_recommendations_verified.md``.

Run:  pytest test_verified_gaps.py -v --tb=short
Expected:  ALL tests FAIL
"""

import pytest

from holonic import (
    HolonicDataset,
    MembraneBreachError,
    MembraneHealth,
    MembraneResult,
    RdflibBackend,
)

# ══════════════════════════════════════════════════════════
# Local fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def ds():
    return HolonicDataset(RdflibBackend())


@pytest.fixture
def ds_with_holons(ds):
    ds.add_holon("urn:holon:source", "Source Holon")
    ds.add_interior(
        "urn:holon:source",
        """
        @prefix src: <urn:src:> .
        <urn:data:001> a src:Record ; src:name "Alpha" ; src:value 42 .
        <urn:data:002> a src:Record ; src:name "Beta"  ; src:value 99 .
    """,
    )
    ds.add_holon("urn:holon:target", "Target Holon")
    ds.add_boundary(
        "urn:holon:target",
        """
        @prefix tgt: <urn:tgt:> .
        <urn:shapes:ItemShape> a sh:NodeShape ;
            sh:targetClass tgt:Item ;
            sh:property [
                sh:path tgt:label ; sh:minCount 1 ;
                sh:datatype xsd:string ; sh:severity sh:Violation
            ] ;
            sh:property [
                sh:path tgt:amount ; sh:minCount 1 ;
                sh:datatype xsd:integer ; sh:severity sh:Violation
            ] .
    """,
    )
    ds.add_portal(
        "urn:portal:src-to-tgt",
        "urn:holon:source",
        "urn:holon:target",
        """
        PREFIX src: <urn:src:> PREFIX tgt: <urn:tgt:>
        CONSTRUCT { ?s a tgt:Item ; tgt:label ?name ; tgt:amount ?val . }
        WHERE     { ?s a src:Record ; src:name ?name ; src:value ?val . }
        """,
        label="Source -> Target",
    )
    return ds


@pytest.fixture
def ds_three_hop(ds):
    ds.add_holon("urn:holon:a", "Holon A")
    ds.add_interior(
        "urn:holon:a",
        """
        @prefix va: <urn:vocab-a:> .
        <urn:entity:1> a va:Widget ; va:label "One" ; va:score 10 .
        <urn:entity:2> a va:Widget ; va:label "Two" ; va:score 20 .
    """,
    )
    ds.add_holon("urn:holon:b", "Holon B")
    ds.add_boundary(
        "urn:holon:b",
        """
        @prefix vb: <urn:vocab-b:> .
        <urn:shapes:GadgetShape> a sh:NodeShape ;
            sh:targetClass vb:Gadget ;
            sh:property [ sh:path vb:name ; sh:minCount 1 ; sh:severity sh:Violation ] .
    """,
    )
    ds.add_holon("urn:holon:c", "Holon C")
    ds.add_boundary(
        "urn:holon:c",
        """
        @prefix vc: <urn:vocab-c:> .
        <urn:shapes:ThingShape> a sh:NodeShape ;
            sh:targetClass vc:Thing ;
            sh:property [ sh:path vc:title ; sh:minCount 1 ; sh:severity sh:Violation ] .
    """,
    )
    ds.add_portal(
        "urn:portal:a-to-b",
        "urn:holon:a",
        "urn:holon:b",
        (
            "PREFIX va: <urn:vocab-a:> PREFIX vb: <urn:vocab-b:> "
            "CONSTRUCT { ?s a vb:Gadget ; vb:name ?l ; vb:rating ?sc . } "
            "WHERE { ?s a va:Widget ; va:label ?l ; va:score ?sc . }"
        ),
        label="A -> B",
    )
    ds.add_portal(
        "urn:portal:b-to-c",
        "urn:holon:b",
        "urn:holon:c",
        (
            "PREFIX vb: <urn:vocab-b:> PREFIX vc: <urn:vocab-c:> "
            "CONSTRUCT { ?s a vc:Thing ; vc:title ?nm . } "
            "WHERE { ?s a vb:Gadget ; vb:name ?nm . }"
        ),
        label="B -> C",
    )
    return ds


@pytest.fixture
def ds_with_projection(ds):
    ds.add_holon("urn:holon:hr", "HR Records")
    ds.add_interior(
        "urn:holon:hr",
        """
        @prefix ex: <urn:ex:> .
        <urn:person:alice> a ex:Employee ;
            ex:name "Alice" ; ex:email "alice@example.com" ;
            ex:ssn "123-45-6789" ; ex:salary 120000 .
    """,
    )
    ds.add_projection(
        "urn:holon:hr",
        """
        @prefix ex: <urn:ex:> .
        <urn:person:alice> a ex:Employee ;
            ex:name "Alice" ; ex:email "alice@example.com" .
    """,
        graph_iri="urn:holon:hr/projection/public",
    )
    ds.add_holon("urn:holon:directory", "Directory")
    ds.add_portal(
        "urn:portal:hr-to-dir",
        "urn:holon:hr",
        "urn:holon:directory",
        "PREFIX ex: <urn:ex:> "
        "CONSTRUCT { ?s a ex:Employee ; ?p ?o . } "
        "WHERE { ?s a ex:Employee ; ?p ?o . }",
        label="HR -> Directory",
    )
    return ds


# ══════════════════════════════════════════════════════════
# [1.1] traverse() should register injected interior
# ══════════════════════════════════════════════════════════


class TestTraverseInteriorRegistration:
    def test_injected_graph_is_registered_as_interior(self, ds_with_holons):
        ds_with_holons.traverse("urn:holon:source", "urn:holon:target", validate=False)
        from holonic import sparql as Q

        rows = ds_with_holons.backend.query(
            Q.GET_HOLON_INTERIORS.replace("?holon", "<urn:holon:target>")
        )
        assert len(rows) > 0, (
            "traverse() injected triples but did not register the graph "
            "as cga:hasInterior. validate_membrane() cannot see the data."
        )

    def test_validation_after_traversal_sees_injected_data(self, ds_with_holons):
        ds_with_holons.traverse("urn:holon:source", "urn:holon:target", validate=False)
        from holonic import sparql as Q

        rows = ds_with_holons.backend.query(
            Q.GET_HOLON_INTERIORS.replace("?holon", "<urn:holon:target>")
        )
        validated_count = sum(len(ds_with_holons.backend.get_graph(r["graph"])) for r in rows)
        injected_count = len(ds_with_holons.backend.get_graph("urn:holon:target/interior"))
        assert validated_count > 0, (
            f"Validator sees {validated_count} triples but {injected_count} "
            f"were injected. Interior not registered => vacuous INTACT false positive."
        )

    def test_traverse_validate_true_validates_injected_state(self, ds_with_holons):
        _, membrane = ds_with_holons.traverse("urn:holon:source", "urn:holon:target", validate=True)
        from holonic import sparql as Q

        rows = ds_with_holons.backend.query(
            Q.GET_HOLON_INTERIORS.replace("?holon", "<urn:holon:target>")
        )
        validated_count = sum(len(ds_with_holons.backend.get_graph(r["graph"])) for r in rows)
        assert validated_count > 0, (
            f"Membrane reports {membrane.health.value} but validated "
            f"{validated_count} triples (0 = vacuous false positive)."
        )

    def test_traverse_injects_into_registered_interior(self, ds):
        ds.add_holon("urn:holon:src", "Src")
        ds.add_interior("urn:holon:src", "<urn:x> a <urn:T> ; <urn:p> 1 .")
        ds.add_holon("urn:holon:tgt", "Tgt")
        ds.add_interior("urn:holon:tgt", "", graph_iri="urn:holon:tgt/interior/custom")
        ds.add_portal(
            "urn:portal:test",
            "urn:holon:src",
            "urn:holon:tgt",
            (
                "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o . "
                "FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>) }"
            ),
        )
        ds.traverse("urn:holon:src", "urn:holon:tgt", validate=False)
        registered = ds.backend.get_graph("urn:holon:tgt/interior/custom")
        assert len(registered) > 0, (
            "Triples should land in the registered interior "
            "'urn:holon:tgt/interior/custom', not the convention-named graph."
        )


# ══════════════════════════════════════════════════════════
# [1.2] traverse_path() -- multi-hop traversal
# ══════════════════════════════════════════════════════════


class TestTraversePath:
    def test_traverse_path_exists(self, ds_three_hop):
        assert hasattr(ds_three_hop, "traverse_path"), (
            "traverse_path() not implemented. find_path() discovers routes "
            "but nothing executes them."
        )

    def test_traverse_path_executes_chain(self, ds_three_hop):
        results = ds_three_hop.traverse_path("urn:holon:a", "urn:holon:c", validate=False)
        assert len(results) == 2
        assert len(results[0][0]) > 0
        assert len(results[1][0]) > 0

    def test_traverse_path_records_provenance_per_hop(self, ds_three_hop):
        ds_three_hop.traverse_path(
            "urn:holon:a", "urn:holon:c", validate=False, agent_iri="urn:agent:test"
        )
        trail = ds_three_hop.collect_audit_trail()
        assert len(trail.traversals) >= 2

    def test_traverse_path_raises_on_no_route(self, ds_three_hop):
        with pytest.raises(ValueError, match="[Nn]o path"):
            ds_three_hop.traverse_path("urn:holon:c", "urn:holon:a")


# ══════════════════════════════════════════════════════════
# [1.3] Portal CONSTRUCT scope
# ══════════════════════════════════════════════════════════


class TestPortalConstructScope:
    def test_portal_construct_does_not_leak_pii(self, ds_with_projection):
        projected = ds_with_projection.traverse_portal("urn:portal:hr-to-dir")
        ttl = projected.serialize(format="ntriples")
        assert "123-45-6789" not in ttl, "SSN leaked through unscoped CONSTRUCT."
        assert "120000" not in ttl, "Salary leaked through unscoped CONSTRUCT."

    def test_portal_supports_source_layer_scoping(self, ds_with_projection):
        ds_with_projection.add_portal(
            "urn:portal:scoped",
            "urn:holon:hr",
            "urn:holon:directory",
            "PREFIX ex: <urn:ex:> "
            "CONSTRUCT { ?s a ex:Employee ; ?p ?o . } "
            "WHERE { ?s a ex:Employee ; ?p ?o . }",
            extra_ttl=(
                "<urn:portal:scoped> "
                "<urn:holonic:ontology:sourceLayer> "
                "<urn:holonic:ontology:ProjectionRole> ."
            ),
        )
        rows = ds_with_projection.backend.query("""
            PREFIX cga: <urn:holonic:ontology:>
            SELECT ?layer WHERE { GRAPH ?g { <urn:portal:scoped> cga:sourceLayer ?layer . } }
        """)
        assert len(rows) > 0, "cga:sourceLayer should be stored on the portal."
        projected = ds_with_projection.traverse_portal("urn:portal:scoped")
        ttl = projected.serialize(format="ntriples")
        assert "123-45-6789" not in ttl, "Scoped portal should not see SSN."


# ══════════════════════════════════════════════════════════
# [1.4] Fail-closed traversal
# ══════════════════════════════════════════════════════════


class TestFailClosedTraversal:
    def test_traverse_accepts_fail_on_breach(self, ds_with_holons):
        import inspect

        sig = inspect.signature(ds_with_holons.traverse)
        assert "fail_on_breach" in sig.parameters, "traverse() has no fail_on_breach parameter."

    @pytest.mark.xfail(
        reason="SHACL sh:targetClass validates only instances of the target class. "
        "When no instances exist, validation reports conformant. Detecting "
        "'wrong type injected' requires non-standard validation semantics. "
        "Tracked as SPEC OQ11.",
        strict=True,
    )
    def test_fail_on_breach_raises_on_compromised(self, ds):
        ds.add_holon("urn:holon:src", "Src")
        ds.add_interior("urn:holon:src", '<urn:x> a <urn:bad:Wrong> ; <urn:bad:junk> "y" .')
        ds.add_holon("urn:holon:tgt", "Tgt")
        ds.add_boundary(
            "urn:holon:tgt",
            """
            @prefix good: <urn:good:> .
            <urn:shapes:S> a sh:NodeShape ; sh:targetClass good:Required ;
                sh:property [ sh:path good:mandatory ; sh:minCount 1 ; sh:severity sh:Violation ] .
        """,
        )
        ds.add_portal(
            "urn:portal:bad",
            "urn:holon:src",
            "urn:holon:tgt",
            "PREFIX bad: <urn:bad:> "
            "CONSTRUCT { ?s a bad:Wrong ; bad:junk ?o . } "
            "WHERE { ?s a bad:Wrong ; bad:junk ?o . }",
        )
        with pytest.raises(MembraneBreachError):
            ds.traverse("urn:holon:src", "urn:holon:tgt", validate=True, fail_on_breach=True)

    @pytest.mark.xfail(
        reason="Same root cause as test_fail_on_breach_raises_on_compromised: "
        "SHACL reports conformant when no target-class instances exist. "
        "Tracked as SPEC OQ11.",
        strict=True,
    )
    def test_fail_on_breach_rolls_back(self, ds):
        ds.add_holon("urn:holon:src", "Src")
        ds.add_interior("urn:holon:src", "<urn:x> a <urn:T> ; <urn:p> 1 .")
        ds.add_holon("urn:holon:tgt", "Tgt")
        ds.add_interior("urn:holon:tgt", "", graph_iri="urn:holon:tgt/interior")
        ds.add_boundary(
            "urn:holon:tgt",
            """
            @prefix req: <urn:req:> .
            <urn:shapes:S> a sh:NodeShape ; sh:targetClass req:Must ;
                sh:property [ sh:path req:field ; sh:minCount 1 ; sh:severity sh:Violation ] .
        """,
        )
        ds.add_portal(
            "urn:portal:bad",
            "urn:holon:src",
            "urn:holon:tgt",
            "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
        )
        before = len(ds.backend.get_graph("urn:holon:tgt/interior"))
        try:
            ds.traverse("urn:holon:src", "urn:holon:tgt", validate=True, fail_on_breach=True)
        except MembraneBreachError:
            pass
        after = len(ds.backend.get_graph("urn:holon:tgt/interior"))
        assert after == before, f"Rollback failed. Before: {before}, After: {after}."


# ══════════════════════════════════════════════════════════
# [2.1] Incremental / delta traversal
# ══════════════════════════════════════════════════════════


class TestIncrementalTraversal:
    def test_traversal_stores_projection_hash(self, ds_with_holons):
        ds_with_holons.traverse(
            "urn:holon:source", "urn:holon:target", validate=False, agent_iri="urn:agent:test"
        )
        rows = ds_with_holons.backend.query("""
            PREFIX cga: <urn:holonic:ontology:>
            SELECT ?hash WHERE { GRAPH ?g { ?s cga:lastProjectionHash ?hash . } }
        """)
        assert len(rows) > 0, "No projection hash stored after traversal."

    def test_noop_traversal_when_source_unchanged(self, ds_with_holons):
        ds_with_holons.traverse(
            "urn:holon:source", "urn:holon:target", validate=False, agent_iri="urn:agent:test"
        )
        ds_with_holons.traverse(
            "urn:holon:source", "urn:holon:target", validate=False, agent_iri="urn:agent:test"
        )
        trail = ds_with_holons.collect_audit_trail()
        labels = [t.portal_label or "" for t in trail.traversals]
        assert any("no-op" in lbl.lower() or "skip" in lbl.lower() for lbl in labels), (
            "No traversal marked as no-op despite identical source data."
        )


# ══════════════════════════════════════════════════════════
# [2.2] Staleness tracking
# ══════════════════════════════════════════════════════════


class TestStalenessTracking:
    def test_freshness_returns_timedelta(self, ds_with_holons):
        ds_with_holons.traverse(
            "urn:holon:source", "urn:holon:target", validate=False, agent_iri="urn:agent:test"
        )
        from datetime import timedelta

        result = ds_with_holons.freshness("urn:holon:target")
        assert isinstance(result, timedelta), f"Expected timedelta, got {type(result)}"

    def test_is_stale_exists(self, ds):
        assert hasattr(ds, "is_stale"), "is_stale() not implemented."

    def test_stale_holons_exists(self, ds):
        assert hasattr(ds, "stale_holons"), "stale_holons() not implemented."


# ══════════════════════════════════════════════════════════
# [2.3] SealedPortal enforcement
# ══════════════════════════════════════════════════════════


class TestSealedPortalEnforcement:
    def test_sealed_portal_raises_specific_error(self, ds):
        ds.add_holon("urn:holon:s", "S")
        ds.add_interior("urn:holon:s", "<urn:x> a <urn:T> .")
        ds.add_holon("urn:holon:t", "T")
        ds.add_portal(
            "urn:portal:blocked", "urn:holon:s", "urn:holon:t", portal_type="cga:SealedPortal"
        )
        with pytest.raises(Exception, match="(?i)seal"):
            ds.traverse_portal("urn:portal:blocked")

    def test_sealed_with_construct_still_blocked(self, ds):
        ds.add_holon("urn:holon:s", "S")
        ds.add_interior("urn:holon:s", "<urn:x> a <urn:T> .")
        ds.add_holon("urn:holon:t", "T")
        ds.add_portal(
            "urn:portal:sealed-q",
            "urn:holon:s",
            "urn:holon:t",
            portal_type="cga:SealedPortal",
            construct_query="CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
        )
        with pytest.raises(Exception, match="(?i)sealed"):
            ds.traverse_portal("urn:portal:sealed-q")

    def test_sealed_via_high_level_traverse(self, ds):
        ds.add_holon("urn:holon:s", "S")
        ds.add_interior("urn:holon:s", "<urn:x> a <urn:T> .")
        ds.add_holon("urn:holon:t", "T")
        ds.add_portal(
            "urn:portal:blocked", "urn:holon:s", "urn:holon:t", portal_type="cga:SealedPortal"
        )
        with pytest.raises(Exception, match="(?i)seal"):
            ds.traverse("urn:holon:s", "urn:holon:t", validate=False)


# ══════════════════════════════════════════════════════════
# [2.4] get_holon() efficiency
# ══════════════════════════════════════════════════════════


class TestGetHolonEfficiency:
    def test_get_holon_uses_direct_query(self, ds):
        for i in range(20):
            ds.add_holon(f"urn:holon:h{i}", f"Holon {i}")
        import inspect

        source = inspect.getsource(ds.get_holon)
        assert "iter_holons" not in source, (
            "get_holon() iterates iter_holons() => O(N) queries. "
            "Should use direct SPARQL FILTER instead."
        )


# ══════════════════════════════════════════════════════════
# [3.1] Multi-holon composition views
# ══════════════════════════════════════════════════════════


class TestCompositionViews:
    def test_compose_exists(self, ds_three_hop):
        assert hasattr(ds_three_hop, "compose"), "compose() not implemented."

    def test_compose_returns_union(self, ds_three_hop):
        ds_three_hop.traverse("urn:holon:a", "urn:holon:b", validate=False)
        composed = ds_three_hop.compose(["urn:holon:a", "urn:holon:b"])
        ttl = composed.serialize(format="ntriples")
        assert "vocab-a" in ttl and "vocab-b" in ttl


# ══════════════════════════════════════════════════════════
# [3.3] Portal dry-run
# ══════════════════════════════════════════════════════════


class TestPortalDryRun:
    def test_dry_run_exists(self, ds_with_holons):
        assert hasattr(ds_with_holons, "dry_run"), "dry_run() not implemented."

    def test_dry_run_does_not_mutate(self, ds_with_holons):
        projected, membrane = ds_with_holons.dry_run("urn:holon:source", "urn:holon:target")
        assert len(projected) > 0
        assert membrane is not None
        g = ds_with_holons.backend.get_graph("urn:holon:target/interior")
        assert len(g) == 0, "dry_run() must not mutate the target."


# ══════════════════════════════════════════════════════════
# [3.4] Per-holon provenance helpers
# ══════════════════════════════════════════════════════════


class TestPerHolonProvenanceHelpers:
    def test_last_traversal_for_holon(self, ds_with_holons):
        ds_with_holons.traverse(
            "urn:holon:source", "urn:holon:target", validate=False, agent_iri="urn:agent:test"
        )
        result = ds_with_holons.last_traversal("urn:holon:target")
        assert result is not None, "last_traversal() not implemented."
        assert result.target_iri == "urn:holon:target"

    def test_derivation_chain_for_holon(self, ds_three_hop):
        ds_three_hop.traverse(
            "urn:holon:a", "urn:holon:b", validate=False, agent_iri="urn:agent:test"
        )
        ds_three_hop.traverse(
            "urn:holon:b", "urn:holon:c", validate=False, agent_iri="urn:agent:test"
        )
        chain = ds_three_hop.derivation_chain("urn:holon:c")
        assert "urn:holon:b" in chain and "urn:holon:a" in chain


# ══════════════════════════════════════════════════════════
# [4.2] MembraneResult.is_healthy
# ══════════════════════════════════════════════════════════


class TestMembraneResultIsHealthy:
    def test_is_healthy_true_for_intact(self):
        r = MembraneResult(
            holon_iri="urn:h", conforms=True, health=MembraneHealth.INTACT, report_text="OK"
        )
        assert hasattr(r, "is_healthy"), "is_healthy property missing."
        assert r.is_healthy is True

    def test_is_healthy_false_for_compromised(self):
        r = MembraneResult(
            holon_iri="urn:h",
            conforms=False,
            health=MembraneHealth.COMPROMISED,
            report_text="Bad",
            violations=["v1"],
        )
        assert hasattr(r, "is_healthy"), "is_healthy property missing."
        assert r.is_healthy is False


# ══════════════════════════════════════════════════════════
# [4.3] Portal update
# ══════════════════════════════════════════════════════════


class TestPortalUpdate:
    def test_update_portal_exists(self, ds_with_holons):
        assert hasattr(ds_with_holons, "update_portal"), "update_portal() not implemented."

    def test_update_portal_changes_construct(self, ds_with_holons):
        ds_with_holons.update_portal(
            "urn:portal:src-to-tgt",
            construct_query=(
                "PREFIX tgt: <urn:tgt:> CONSTRUCT { ?s a tgt:Item . } WHERE { ?s ?p ?o }"
            ),
        )
        detail = ds_with_holons.get_portal("urn:portal:src-to-tgt")
        assert "tgt:amount" not in (detail.construct_query or "")


# ══════════════════════════════════════════════════════════
# [4.4] validate_all()
# ══════════════════════════════════════════════════════════


class TestValidateAll:
    def test_validate_all_exists(self, ds_with_holons):
        assert hasattr(ds_with_holons, "validate_all"), "validate_all() not implemented."

    def test_validate_all_returns_dict(self, ds_with_holons):
        results = ds_with_holons.validate_all()
        assert isinstance(results, dict)
        assert len(results) == 2
        assert all(isinstance(v, MembraneResult) for v in results.values())


# ══════════════════════════════════════════════════════════
# [4.5] Portal type in data model
# ══════════════════════════════════════════════════════════


class TestPortalTypeInDataModel:
    def test_portal_info_has_type(self, ds_with_holons):
        portals = ds_with_holons.find_portals_from("urn:holon:source")
        assert hasattr(portals[0], "portal_type"), "PortalInfo has no portal_type."
        assert "TransformPortal" in (portals[0].portal_type or "")

    def test_portal_summary_has_type(self, ds_with_holons):
        summaries = ds_with_holons.list_portals()
        assert hasattr(summaries[0], "portal_type"), "PortalSummary has no portal_type."

    def test_portal_detail_has_type(self, ds_with_holons):
        detail = ds_with_holons.get_portal("urn:portal:src-to-tgt")
        assert hasattr(detail, "portal_type"), "PortalDetail has no portal_type."

    def test_sealed_type_visible_via_api(self, ds):
        ds.add_holon("urn:holon:x", "X")
        ds.add_holon("urn:holon:y", "Y")
        ds.add_portal(
            "urn:portal:sealed", "urn:holon:x", "urn:holon:y", portal_type="cga:SealedPortal"
        )
        detail = ds.get_portal("urn:portal:sealed")
        assert hasattr(detail, "portal_type"), "portal_type field missing"
        assert "SealedPortal" in (detail.portal_type or "")


# ══════════════════════════════════════════════════════════
# [3.5] Rollback
# ══════════════════════════════════════════════════════════


class TestRollback:
    def test_rollback_exists(self, ds):
        assert hasattr(ds, "rollback_traversal"), "rollback_traversal() not implemented."

    def test_rollback_removes_injected_triples(self, ds_with_holons):
        ds_with_holons.traverse(
            "urn:holon:source", "urn:holon:target", validate=False, agent_iri="urn:agent:test"
        )
        trail = ds_with_holons.collect_audit_trail()
        activity_iri = trail.traversals[0].activity_iri
        ds_with_holons.rollback_traversal(activity_iri)
        g = ds_with_holons.backend.get_graph("urn:holon:target/interior")
        assert len(g) == 0, "Rollback should remove all injected triples."
