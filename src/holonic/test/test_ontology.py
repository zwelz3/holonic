"""Smoke tests for the shipped CGA ontology and SHACL shapes.

Ensures the TTL files parse cleanly, the expected vocabulary is present,
and the shapes graph validates a minimal conformant holon registry.
"""

from pathlib import Path

import pytest
from rdflib import Graph

from holonic import HolonicDataset, RdflibBackend

CGA_GRAPH = "urn:holonic:ontology:cga"
CGA_SHAPES_GRAPH = "urn:holonic:ontology:cga-shapes"


@pytest.fixture
def loaded_ds():
    """A fresh dataset with the CGA ontology auto-loaded."""
    return HolonicDataset(RdflibBackend(), load_ontology=True)


class TestOntologyFilesExist:
    def test_cga_ttl_is_shipped(self):
        p = Path(__file__).parent.parent / "ontology" / "cga.ttl"
        assert p.exists(), f"Missing ontology file: {p}"

    def test_cga_shapes_ttl_is_shipped(self):
        p = Path(__file__).parent.parent / "ontology" / "cga-shapes.ttl"
        assert p.exists(), f"Missing shapes file: {p}"

    def test_cga_ttl_parses_standalone(self):
        p = Path(__file__).parent.parent / "ontology" / "cga.ttl"
        g = Graph()
        g.parse(str(p), format="turtle")
        assert len(g) > 0

    def test_cga_shapes_ttl_parses_standalone(self):
        p = Path(__file__).parent.parent / "ontology" / "cga-shapes.ttl"
        g = Graph()
        g.parse(str(p), format="turtle")
        assert len(g) > 0


class TestOntologyAutoLoaded:
    """HolonicDataset(load_ontology=True) should put the CGA in a known graph."""

    def test_cga_graph_created(self, loaded_ds):
        assert loaded_ds.backend.graph_exists(CGA_GRAPH)

    def test_cga_shapes_graph_created(self, loaded_ds):
        assert loaded_ds.backend.graph_exists(CGA_SHAPES_GRAPH)

    def test_holon_class_defined(self, loaded_ds):
        assert loaded_ds.backend.ask(f"""
            ASK {{
                GRAPH <{CGA_GRAPH}> {{
                    <urn:holonic:ontology:Holon>
                        a <http://www.w3.org/2002/07/owl#Class> .
                }}
            }}
        """)

    def test_portal_class_defined(self, loaded_ds):
        assert loaded_ds.backend.ask(f"""
            ASK {{
                GRAPH <{CGA_GRAPH}> {{
                    <urn:holonic:ontology:Portal>
                        a <http://www.w3.org/2002/07/owl#Class> .
                }}
            }}
        """)

    def test_transform_portal_class_defined(self, loaded_ds):
        assert loaded_ds.backend.ask(f"""
            ASK {{
                GRAPH <{CGA_GRAPH}> {{
                    <urn:holonic:ontology:TransformPortal>
                        a <http://www.w3.org/2002/07/owl#Class> .
                }}
            }}
        """)

    def test_icon_portal_class_defined(self, loaded_ds):
        assert loaded_ds.backend.ask(f"""
            ASK {{
                GRAPH <{CGA_GRAPH}> {{
                    <urn:holonic:ontology:IconPortal>
                        a <http://www.w3.org/2002/07/owl#Class> ;
                        <http://www.w3.org/2000/01/rdf-schema#subClassOf>
                            <urn:holonic:ontology:Portal> .
                }}
            }}
        """)

    def test_sealed_portal_class_defined(self, loaded_ds):
        assert loaded_ds.backend.ask(f"""
            ASK {{
                GRAPH <{CGA_GRAPH}> {{
                    <urn:holonic:ontology:SealedPortal>
                        a <http://www.w3.org/2002/07/owl#Class> ;
                        <http://www.w3.org/2000/01/rdf-schema#subClassOf>
                            <urn:holonic:ontology:Portal> .
                }}
            }}
        """)

    def test_holon_shape_defined(self, loaded_ds):
        assert loaded_ds.backend.ask(f"""
            ASK {{
                GRAPH <{CGA_SHAPES_GRAPH}> {{
                    <urn:holonic:ontology:HolonShape>
                        a <http://www.w3.org/ns/shacl#NodeShape> .
                }}
            }}
        """)

    def test_load_ontology_false_skips_load(self):
        ds = HolonicDataset(RdflibBackend(), load_ontology=False)
        assert not ds.backend.graph_exists(CGA_GRAPH)
        assert not ds.backend.graph_exists(CGA_SHAPES_GRAPH)


class TestShapesValidateRegistry:
    """The shapes graph should validate a minimal conformant holon registry."""

    def test_conformant_holon_passes_cga_shapes(self, loaded_ds):
        import pyshacl

        # HolonShape has two property rules:
        #   - exactly one rdfs:label (Violation severity)
        #   - at least one cga:hasInterior (Warning severity)
        # pyshacl's `conforms` flips False on *any* reported result,
        # warning or violation, so a fully-conformant holon needs both.
        loaded_ds.add_holon("urn:holon:ok", "OK")
        loaded_ds.add_interior("urn:holon:ok", "<urn:x> a <urn:T> .")
        registry = loaded_ds.backend.get_graph(loaded_ds.registry_graph)
        shapes = loaded_ds.backend.get_graph(CGA_SHAPES_GRAPH)

        conforms, _, _ = pyshacl.validate(
            registry,
            shacl_graph=shapes,
        )
        assert conforms


class TestPortalSubtypeShapeSemantics:
    """SHACL shapes enforce the per-subtype constructQuery semantics:

    - TransformPortal MUST have exactly one constructQuery
    - IconPortal MUST NOT have a constructQuery (warning)
    - SealedPortal MUST NOT have a constructQuery (warning)
    """

    def _validate_registry(self, ds):
        import pyshacl

        registry = ds.backend.get_graph(ds.registry_graph)
        shapes = ds.backend.get_graph(CGA_SHAPES_GRAPH)
        conforms, _report_graph, report_text = pyshacl.validate(
            registry,
            shacl_graph=shapes,
        )
        return conforms, report_text

    def test_transform_portal_without_query_fails_validation(self, loaded_ds):
        """TransformPortal without cga:constructQuery triggers a violation."""
        loaded_ds.add_holon("urn:holon:a", "A")
        loaded_ds.add_interior("urn:holon:a", "<urn:x> a <urn:T> .")
        loaded_ds.add_holon("urn:holon:b", "B")
        loaded_ds.add_interior("urn:holon:b", "<urn:y> a <urn:T> .")
        # Transform portal with no query — violates TransformPortalShape
        loaded_ds.add_portal(
            "urn:portal:incomplete",
            source_iri="urn:holon:a",
            target_iri="urn:holon:b",
            construct_query=None,  # missing query on a TransformPortal
            portal_type="cga:TransformPortal",
        )
        conforms, report = self._validate_registry(loaded_ds)
        assert not conforms
        assert "TransformPortal must have exactly one constructQuery" in report

    def test_sealed_portal_with_query_fails_validation(self, loaded_ds):
        """SealedPortal carrying a constructQuery triggers a warning."""
        loaded_ds.add_holon("urn:holon:a", "A")
        loaded_ds.add_interior("urn:holon:a", "<urn:x> a <urn:T> .")
        loaded_ds.add_holon("urn:holon:b", "B")
        loaded_ds.add_interior("urn:holon:b", "<urn:y> a <urn:T> .")
        loaded_ds.add_portal(
            "urn:portal:sealed-with-query",
            source_iri="urn:holon:a",
            target_iri="urn:holon:b",
            construct_query="CONSTRUCT { ?s ?p ?o } WHERE { GRAPH ?g { ?s ?p ?o } }",
            portal_type="cga:SealedPortal",
        )
        conforms, report = self._validate_registry(loaded_ds)
        assert not conforms
        assert "SealedPortal should not carry a constructQuery" in report

    def test_icon_portal_with_query_fails_validation(self, loaded_ds):
        """IconPortal carrying a constructQuery triggers a warning."""
        loaded_ds.add_holon("urn:holon:a", "A")
        loaded_ds.add_interior("urn:holon:a", "<urn:x> a <urn:T> .")
        loaded_ds.add_holon("urn:holon:b", "B")
        loaded_ds.add_interior("urn:holon:b", "<urn:y> a <urn:T> .")
        loaded_ds.add_portal(
            "urn:portal:icon-with-query",
            source_iri="urn:holon:a",
            target_iri="urn:holon:b",
            construct_query="CONSTRUCT { ?s ?p ?o } WHERE { GRAPH ?g { ?s ?p ?o } }",
            portal_type="cga:IconPortal",
        )
        conforms, report = self._validate_registry(loaded_ds)
        assert not conforms
        assert "IconPortal should not carry a constructQuery" in report

    def test_sealed_portal_without_query_passes_validation(self, loaded_ds):
        """Sealed portal without a query conforms to its shape."""
        loaded_ds.add_holon("urn:holon:a", "A")
        loaded_ds.add_interior("urn:holon:a", "<urn:x> a <urn:T> .")
        loaded_ds.add_holon("urn:holon:b", "B")
        loaded_ds.add_interior("urn:holon:b", "<urn:y> a <urn:T> .")
        loaded_ds.add_portal(
            "urn:portal:sealed-ok",
            source_iri="urn:holon:a",
            target_iri="urn:holon:b",
            portal_type="cga:SealedPortal",
        )
        conforms, _ = self._validate_registry(loaded_ds)
        assert conforms

    def test_icon_portal_without_query_passes_validation(self, loaded_ds):
        """Icon portal without a query conforms to its shape."""
        loaded_ds.add_holon("urn:holon:a", "A")
        loaded_ds.add_interior("urn:holon:a", "<urn:x> a <urn:T> .")
        loaded_ds.add_holon("urn:holon:b", "B")
        loaded_ds.add_interior("urn:holon:b", "<urn:y> a <urn:T> .")
        loaded_ds.add_portal(
            "urn:portal:icon-ok",
            source_iri="urn:holon:a",
            target_iri="urn:holon:b",
            portal_type="cga:IconPortal",
        )
        conforms, _ = self._validate_registry(loaded_ds)
        assert conforms
