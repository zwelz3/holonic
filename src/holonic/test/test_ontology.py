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

    def test_label_missing_fails_cga_shapes(self, loaded_ds):
        import pyshacl
        from rdflib import URIRef
        from rdflib.namespace import RDF

        # Bypass add_holon (which always writes a label) — stamp a bare
        # cga:Holon directly into the registry so HolonShape can bite.
        registry = loaded_ds.backend.get_graph(loaded_ds.registry_graph)
        registry.add(
            (
                URIRef("urn:holon:bare"),
                RDF.type,
                URIRef("urn:holonic:ontology:Holon"),
            )
        )
        shapes = loaded_ds.backend.get_graph(CGA_SHAPES_GRAPH)

        conforms, _, report_text = pyshacl.validate(
            registry,
            shacl_graph=shapes,
        )
        assert not conforms
        assert "label" in report_text.lower()
