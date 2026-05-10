"""Tests for 0.6.0 audit remediation.

Covers:
- C1: Turtle injection via labels is neutralized
- C2: RdflibBackend.get_graph() returns a copy, not a live reference
- S3: Dead code removal (no test needed; absence verified by import)
- S4: IRI validation at API boundaries
- M1: SHACL report graph parsing (tested via validate_membrane behavior)
- M3: batch() context manager defers metadata refresh
"""

import pytest
from rdflib import URIRef

from holonic import HolonicDataset, MembraneHealth

# ══════════════════════════════════════════════════════════════
# C1 — Turtle injection neutralized
# ══════════════════════════════════════════════════════════════


class TestTurtleInjection:
    """Labels containing Turtle-significant characters must be stored
    literally, not interpreted as RDF structure."""

    def test_add_holon_label_injection_neutralized(self):
        ds = HolonicDataset()
        ds.add_holon("urn:test:h1", 'Evil" ; rdfs:comment "INJECTED')
        g = ds.backend.get_graph(ds.registry_iri)
        # No rdfs:comment triple should exist for this holon
        comments = [str(o) for s, p, o in g if "comment" in str(p) and "test:h1" in str(s)]
        assert not comments, f"Injection succeeded: {comments}"

    def test_add_holon_label_preserves_content(self):
        ds = HolonicDataset()
        ds.add_holon("urn:test:h1", 'Has "quotes" inside')
        g = ds.backend.get_graph(ds.registry_iri)
        labels = [str(o) for s, p, o in g if "label" in str(p) and "test:h1" in str(s)]
        assert len(labels) == 1
        assert labels[0] == 'Has "quotes" inside'

    def test_add_portal_label_injection_neutralized(self):
        ds = HolonicDataset()
        ds.add_holon("urn:holon:a", "A")
        ds.add_holon("urn:holon:b", "B")
        ds.add_portal(
            "urn:portal:p1",
            source_iri="urn:holon:a",
            target_iri="urn:holon:b",
            label='Evil" ; rdfs:comment "INJECTED',
            construct_query="CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
        )
        g = ds.backend.get_graph("urn:holon:a/boundary")
        comments = [str(o) for s, p, o in g if "comment" in str(p) and "portal:p1" in str(s)]
        assert not comments, f"Portal label injection succeeded: {comments}"

    def test_add_holon_label_with_newline(self):
        ds = HolonicDataset()
        ds.add_holon("urn:test:h2", "Line1\nLine2")
        g = ds.backend.get_graph(ds.registry_iri)
        labels = [str(o) for s, p, o in g if "label" in str(p) and "test:h2" in str(s)]
        assert len(labels) == 1
        assert labels[0] == "Line1\nLine2"

    def test_add_holon_label_with_backslash(self):
        ds = HolonicDataset()
        ds.add_holon("urn:test:h3", r"path\to\file")
        g = ds.backend.get_graph(ds.registry_iri)
        labels = [str(o) for s, p, o in g if "label" in str(p) and "test:h3" in str(s)]
        assert len(labels) == 1
        assert labels[0] == r"path\to\file"


# ══════════════════════════════════════════════════════════════
# C2 — get_graph returns a copy
# ══════════════════════════════════════════════════════════════


class TestGetGraphCopySemantics:
    """RdflibBackend.get_graph() must return a detached copy."""

    def test_mutation_does_not_affect_store(self):
        ds = HolonicDataset()
        ds.add_holon("urn:h:1", "Test")
        ds.add_interior(
            "urn:h:1",
            "<urn:x> <urn:y> <urn:z> .",
            graph_iri="urn:h:1/interior",
        )
        g = ds.backend.get_graph("urn:h:1/interior")
        original_len = len(g)
        assert original_len > 0

        # Mutate the copy
        g.remove((URIRef("urn:x"), URIRef("urn:y"), URIRef("urn:z")))

        # Store should be unchanged
        g2 = ds.backend.get_graph("urn:h:1/interior")
        assert len(g2) == original_len

    def test_copy_preserves_namespace_bindings(self):
        ds = HolonicDataset()
        ds.add_holon("urn:h:1", "Test")
        ds.add_interior(
            "urn:h:1",
            "@prefix ex: <http://example.org/> . ex:a ex:b ex:c .",
            graph_iri="urn:h:1/interior",
        )
        g = ds.backend.get_graph("urn:h:1/interior")
        prefixes = dict(g.namespaces())
        # The graph should carry namespace bindings (at minimum the
        # ones parsed from the Turtle input)
        assert len(prefixes) > 0

    def test_two_copies_are_independent(self):
        ds = HolonicDataset()
        ds.add_holon("urn:h:1", "Test")
        ds.add_interior(
            "urn:h:1",
            "<urn:x> <urn:y> <urn:z> .",
            graph_iri="urn:h:1/interior",
        )
        g1 = ds.backend.get_graph("urn:h:1/interior")
        g2 = ds.backend.get_graph("urn:h:1/interior")
        g1.remove((URIRef("urn:x"), URIRef("urn:y"), URIRef("urn:z")))
        assert len(g1) == 0
        assert len(g2) > 0, "Second copy should be independent of first"


# ══════════════════════════════════════════════════════════════
# S4 — IRI validation
# ══════════════════════════════════════════════════════════════


class TestIRIValidation:
    """Public API methods reject malformed IRIs early with ValueError."""

    @pytest.mark.parametrize(
        "bad_iri",
        [
            "",
            "urn:has space",
            'urn:has"quote',
            "urn:has>bracket",
            "urn:has<bracket",
            "urn:has{brace}",
        ],
    )
    def test_add_holon_rejects_bad_iri(self, bad_iri):
        ds = HolonicDataset()
        with pytest.raises(ValueError):
            ds.add_holon(bad_iri, "Label")

    def test_add_holon_rejects_bad_member_of(self):
        ds = HolonicDataset()
        with pytest.raises(ValueError):
            ds.add_holon("urn:ok", "Label", member_of="urn:has space")

    @pytest.mark.parametrize(
        "method",
        [
            "add_interior",
            "add_boundary",
            "add_projection",
            "add_context",
        ],
    )
    def test_add_layer_rejects_bad_holon_iri(self, method):
        ds = HolonicDataset()
        fn = getattr(ds, method)
        with pytest.raises(ValueError):
            fn("urn:has space", "<urn:x> <urn:y> <urn:z> .")

    @pytest.mark.parametrize(
        "method",
        [
            "add_interior",
            "add_boundary",
            "add_projection",
            "add_context",
        ],
    )
    def test_add_layer_rejects_bad_graph_iri(self, method):
        ds = HolonicDataset()
        fn = getattr(ds, method)
        with pytest.raises(ValueError):
            fn("urn:ok", "<urn:x> <urn:y> <urn:z> .", graph_iri="urn:has space")

    def test_add_portal_rejects_bad_portal_iri(self):
        ds = HolonicDataset()
        with pytest.raises(ValueError):
            ds.add_portal(
                "urn:has space",
                source_iri="urn:a",
                target_iri="urn:b",
            )

    def test_add_portal_rejects_bad_source_iri(self):
        ds = HolonicDataset()
        with pytest.raises(ValueError):
            ds.add_portal(
                "urn:ok",
                source_iri="urn:has space",
                target_iri="urn:b",
            )

    def test_valid_iris_are_accepted(self):
        """Sanity check: well-formed IRIs should not be rejected."""
        ds = HolonicDataset()
        ds.add_holon("urn:holon:test-1", "Test")
        ds.add_holon("http://example.org/holon/2", "Test HTTP")
        ds.add_holon("urn:uuid:550e8400-e29b-41d4-a716-446655440000", "UUID")
        assert True  # If we got here, no ValueError was raised


# ══════════════════════════════════════════════════════════════
# M1 — SHACL report graph parsing
# ══════════════════════════════════════════════════════════════


class TestSHACLReportGraphParsing:
    """validate_membrane uses structured graph parsing, producing
    violation/warning lists with detail strings."""

    def test_violation_includes_focus_and_path(self):
        ds = HolonicDataset()
        ds.add_holon("urn:h:1", "Test")
        ds.add_interior(
            "urn:h:1",
            """
            @prefix schema: <https://schema.org/> .
            <urn:person:alice> a schema:Person .
            """,
            graph_iri="urn:h:1/interior",
        )
        ds.add_boundary(
            "urn:h:1",
            """
            @prefix sh: <http://www.w3.org/ns/shacl#> .
            @prefix schema: <https://schema.org/> .
            <urn:shape:person> a sh:NodeShape ;
                sh:targetClass schema:Person ;
                sh:property [
                    sh:path schema:name ;
                    sh:minCount 1 ;
                    sh:severity sh:Violation ;
                ] .
            """,
            graph_iri="urn:h:1/boundary",
        )
        result = ds.validate_membrane("urn:h:1")
        assert result.health == MembraneHealth.COMPROMISED
        assert len(result.violations) > 0
        # The violation string should contain structured detail
        v = result.violations[0]
        assert "Violation:" in v
        assert "focus=" in v or "path=" in v

    def test_intact_membrane_has_no_violations(self):
        ds = HolonicDataset()
        ds.add_holon("urn:h:1", "Test")
        ds.add_interior(
            "urn:h:1",
            """
            @prefix schema: <https://schema.org/> .
            <urn:person:alice> a schema:Person ;
                schema:name "Alice" .
            """,
            graph_iri="urn:h:1/interior",
        )
        ds.add_boundary(
            "urn:h:1",
            """
            @prefix sh: <http://www.w3.org/ns/shacl#> .
            @prefix schema: <https://schema.org/> .
            <urn:shape:person> a sh:NodeShape ;
                sh:targetClass schema:Person ;
                sh:property [
                    sh:path schema:name ;
                    sh:minCount 1 ;
                ] .
            """,
            graph_iri="urn:h:1/boundary",
        )
        result = ds.validate_membrane("urn:h:1")
        assert result.health == MembraneHealth.INTACT
        assert result.violations == []
        assert result.warnings == []


# ══════════════════════════════════════════════════════════════
# M3 — batch() context manager
# ══════════════════════════════════════════════════════════════


class TestBatchContextManager:
    """ds.batch() suppresses per-write metadata refresh."""

    def test_batch_suppresses_refresh(self):
        ds = HolonicDataset()
        refresh_count = 0
        orig = ds._metadata.refresh_graph

        def counting_refresh(g):
            nonlocal refresh_count
            refresh_count += 1
            return orig(g)

        ds._metadata.refresh_graph = counting_refresh

        with ds.batch():
            ds.add_holon("urn:h:1", "One")
            ds.add_interior("urn:h:1", "<urn:a> <urn:b> <urn:c> .", graph_iri="urn:h:1/interior")
            ds.add_interior("urn:h:1", "<urn:d> <urn:e> <urn:f> .", graph_iri="urn:h:1/interior2")
            assert refresh_count == 0, "No refresh inside batch"

        # One consolidated refresh on exit
        assert refresh_count == 1

    def test_batch_restores_mode_on_exception(self):
        ds = HolonicDataset()
        assert ds._metadata_updates == "eager"
        with pytest.raises(RuntimeError):
            with ds.batch():
                assert ds._metadata_updates == "off"
                raise RuntimeError("boom")
        assert ds._metadata_updates == "eager"

    def test_batch_nests_safely(self):
        ds = HolonicDataset()
        with ds.batch():
            assert ds._metadata_updates == "off"
            with ds.batch():
                assert ds._metadata_updates == "off"
                ds.add_holon("urn:h:inner", "Inner")
            # Inner batch restores to "off" (the outer batch's setting)
            assert ds._metadata_updates == "off"
        # Outer batch restores to "eager"
        assert ds._metadata_updates == "eager"

    def test_batch_returns_dataset(self):
        ds = HolonicDataset()
        with ds.batch() as ctx:
            assert ctx is ds
