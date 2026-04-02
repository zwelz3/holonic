"""Tests for SHACL membrane validation."""

import pytest
from holonic import HolonicDataset, MembraneHealth


class TestMembraneValidation:
    def test_intact_membrane(self, ds):
        ds.add_holon("urn:holon:valid", "Valid")
        ds.add_interior("urn:holon:valid", """
            @prefix ex: <urn:ex:> .
            <urn:item:1> a ex:Item ;
                ex:name "Widget" .
        """)
        ds.add_boundary("urn:holon:valid", """
            @prefix ex: <urn:ex:> .
            <urn:shapes:ItemShape> a sh:NodeShape ;
                sh:targetClass ex:Item ;
                sh:property [
                    sh:path ex:name ;
                    sh:minCount 1 ;
                    sh:datatype xsd:string ;
                    sh:severity sh:Violation
                ] .
        """)
        result = ds.validate_membrane("urn:holon:valid")
        assert result.conforms
        assert result.health == MembraneHealth.INTACT

    def test_compromised_membrane(self, ds):
        ds.add_holon("urn:holon:bad", "Bad")
        ds.add_interior("urn:holon:bad", """
            @prefix ex: <urn:ex:> .
            <urn:item:1> a ex:Item .
        """)
        ds.add_boundary("urn:holon:bad", """
            @prefix ex: <urn:ex:> .
            <urn:shapes:ItemShape> a sh:NodeShape ;
                sh:targetClass ex:Item ;
                sh:property [
                    sh:path ex:name ;
                    sh:minCount 1 ;
                    sh:datatype xsd:string ;
                    sh:severity sh:Violation ;
                    sh:message "Item must have a name."
                ] .
        """)
        result = ds.validate_membrane("urn:holon:bad")
        assert not result.conforms
        assert result.health == MembraneHealth.COMPROMISED

    def test_no_boundary_returns_intact(self, ds):
        ds.add_holon("urn:holon:naked", "Naked")
        ds.add_interior("urn:holon:naked", """
            <urn:x> a <urn:T> .
        """)
        result = ds.validate_membrane("urn:holon:naked")
        assert result.conforms
        assert result.health == MembraneHealth.INTACT

    def test_multi_interior_validation(self, ds):
        """Boundary should validate the union of all interior graphs."""
        ds.add_holon("urn:holon:multi", "Multi")
        ds.add_interior("urn:holon:multi", """
            @prefix ex: <urn:ex:> .
            <urn:item:1> a ex:Item ; ex:name "Alpha" .
        """, graph_iri="urn:holon:multi/interior/a")
        ds.add_interior("urn:holon:multi", """
            @prefix ex: <urn:ex:> .
            <urn:item:2> a ex:Item ; ex:name "Beta" .
        """, graph_iri="urn:holon:multi/interior/b")
        ds.add_boundary("urn:holon:multi", """
            @prefix ex: <urn:ex:> .
            <urn:shapes:ItemShape> a sh:NodeShape ;
                sh:targetClass ex:Item ;
                sh:property [
                    sh:path ex:name ;
                    sh:minCount 1 ;
                    sh:severity sh:Violation
                ] .
        """)
        result = ds.validate_membrane("urn:holon:multi")
        assert result.conforms
        assert result.health == MembraneHealth.INTACT

    def test_summary_output(self, ds):
        ds.add_holon("urn:holon:test", "Test")
        ds.add_interior("urn:holon:test", "<urn:x> a <urn:T> .")
        result = ds.validate_membrane("urn:holon:test")
        s = result.summary()
        assert "INTACT" in s


class TestProvenance:
    def test_record_traversal(self, ds_with_holons):
        activity = ds_with_holons.record_traversal(
            portal_iri="urn:portal:src-to-tgt",
            source_iri="urn:holon:source",
            target_iri="urn:holon:target",
            agent_iri="urn:agent:test",
        )
        assert activity.startswith("urn:prov:traversal:")

        # Check the context graph has triples
        g = ds_with_holons.backend.get_graph("urn:holon:target/context")
        assert len(g) > 0

    def test_record_validation(self, ds_with_holons):
        activity = ds_with_holons.record_validation(
            holon_iri="urn:holon:target",
            health=MembraneHealth.INTACT,
            agent_iri="urn:agent:test",
        )
        assert activity.startswith("urn:prov:validation:")

    def test_traverse_with_provenance(self, ds_with_holons):
        _, result = ds_with_holons.traverse(
            "urn:holon:source",
            "urn:holon:target",
            validate=False,
            agent_iri="urn:agent:pipeline",
        )
        # Check context was created
        g = ds_with_holons.backend.get_graph("urn:holon:target/context")
        assert len(g) > 0
