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

        loaded_ds.add_holon("urn:holon:ok", "OK")
        loaded_ds.add_interior("urn:holon:ok", "<urn:x> a <urn:T> .")
        registry = loaded_ds.backend.get_graph(loaded_ds.registry_iri)
        shapes = loaded_ds.backend.get_graph(CGA_SHAPES_GRAPH)

        # allow_infos=True so advisory shapes (HolonStewardshipShape)
        # don't cause conforms=False.  Info severity is intentionally
        # non-blocking -- it nudges, it doesn't constrain.
        conforms, _, _ = pyshacl.validate(
            registry,
            shacl_graph=shapes,
            allow_infos=True,
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

        registry = ds.backend.get_graph(ds.registry_iri)
        shapes = ds.backend.get_graph(CGA_SHAPES_GRAPH)
        conforms, _report_graph, report_text = pyshacl.validate(
            registry,
            shacl_graph=shapes,
            allow_infos=True,
        )
        return conforms, report_text

    def test_transform_portal_without_query_fails_validation(self, loaded_ds):
        """TransformPortal without cga:constructQuery triggers a violation."""
        loaded_ds.add_holon("urn:holon:a", "A")
        loaded_ds.add_interior("urn:holon:a", "<urn:x> a <urn:T> .")
        loaded_ds.add_holon("urn:holon:b", "B")
        loaded_ds.add_interior("urn:holon:b", "<urn:y> a <urn:T> .")
        # Transform portal with no query -- violates TransformPortalShape
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


class TestDerivationVocabulary:
    """R5.3 -- ``cga:derivedFrom`` is reserved, and distinct from PROV.

    The requirement is a reservation: ``cga:derivedFrom`` carries persistent
    holon-to-holon structural dependency, ``prov:wasDerivedFrom`` carries
    activity-produced graph-to-graph derivation, and neither replaces the
    other. What is asserted here is that the vocabulary says so -- that the
    term exists, is typed, is scoped Holon-to-Holon, and is not conflated
    with the PROV property by a subproperty axiom or an equivalence.
    """

    CGA_DERIVED = "urn:holonic:ontology:derivedFrom"
    PROV_DERIVED = "http://www.w3.org/ns/prov#wasDerivedFrom"

    def test_cga_derived_from_is_declared_holon_to_holon(self, loaded_ds):
        assert loaded_ds.backend.ask(f"""
            ASK {{
                GRAPH <{CGA_GRAPH}> {{
                    <{self.CGA_DERIVED}>
                        a <http://www.w3.org/2002/07/owl#ObjectProperty> ;
                        <http://www.w3.org/2000/01/rdf-schema#domain>
                            <urn:holonic:ontology:Holon> ;
                        <http://www.w3.org/2000/01/rdf-schema#range>
                            <urn:holonic:ontology:Holon> .
                }}
            }}
        """), "cga:derivedFrom must be an ObjectProperty scoped Holon -> Holon"

    def test_cga_derived_from_is_not_conflated_with_prov(self, loaded_ds):
        """The two properties coexist; neither is defined in terms of the other.

        A ``rdfs:subPropertyOf`` or ``owl:equivalentProperty`` axiom between
        them would collapse the distinction the requirement exists to draw --
        a reasoner would then infer structural dependency from every
        traversal, which is precisely the claim R5.2 and R5.3 keep apart.
        """
        assert not loaded_ds.backend.ask(f"""
            ASK {{
                GRAPH <{CGA_GRAPH}> {{
                    {{ <{self.CGA_DERIVED}>
                        <http://www.w3.org/2000/01/rdf-schema#subPropertyOf>
                        <{self.PROV_DERIVED}> }}
                    UNION
                    {{ <{self.CGA_DERIVED}>
                        <http://www.w3.org/2002/07/owl#equivalentProperty>
                        <{self.PROV_DERIVED}> }}
                    UNION
                    {{ <{self.PROV_DERIVED}>
                        <http://www.w3.org/2000/01/rdf-schema#subPropertyOf>
                        <{self.CGA_DERIVED}> }}
                }}
            }}
        """), "cga:derivedFrom and prov:wasDerivedFrom must stay distinct"


class TestSplitMergeActivities:
    """R5.4 -- ``HolonSplit`` and ``HolonMerge`` are PROV activities."""

    PROV_ACTIVITY = "http://www.w3.org/ns/prov#Activity"
    SUBCLASS_OF = "http://www.w3.org/2000/01/rdf-schema#subClassOf"

    @pytest.mark.parametrize("cls", ["HolonSplit", "HolonMerge"])
    def test_subclasses_prov_activity(self, loaded_ds, cls):
        assert loaded_ds.backend.ask(f"""
            ASK {{
                GRAPH <{CGA_GRAPH}> {{
                    <urn:holonic:ontology:{cls}>
                        a <http://www.w3.org/2002/07/owl#Class> ;
                        <{self.SUBCLASS_OF}>+ <{self.PROV_ACTIVITY}> .
                }}
            }}
        """), f"cga:{cls} must reach prov:Activity through rdfs:subClassOf"

    @pytest.mark.parametrize("cls", ["HolonSplit", "HolonMerge"])
    def test_instance_carries_used_and_generated(self, loaded_ds, cls):
        """An instance's type chain reaches prov:Activity and it declares both
        ``prov:used`` and ``prov:generated``.

        Asserted against a real instance rather than the class declaration:
        the requirement is about what a split or merge record looks like, and
        a class that subclasses Activity while nothing ever carries the two
        properties would satisfy the schema and none of the intent.
        """
        loaded_ds.add_holon("urn:holon:src", "Source")
        loaded_ds.add_holon("urn:holon:dst", "Result")
        activity = f"urn:activity:{cls.lower()}-1"
        loaded_ds.backend.parse_into(
            CGA_GRAPH,
            f"""
            @prefix prov: <http://www.w3.org/ns/prov#> .
            <{activity}> a <urn:holonic:ontology:{cls}> ;
                prov:used <urn:holon:src> ;
                prov:generated <urn:holon:dst> .
            """,
        )
        assert loaded_ds.backend.ask(f"""
            ASK {{
                GRAPH <{CGA_GRAPH}> {{
                    <{activity}> a ?cls ;
                        <http://www.w3.org/ns/prov#used> ?used ;
                        <http://www.w3.org/ns/prov#generated> ?generated .
                    ?cls <{self.SUBCLASS_OF}>+ <{self.PROV_ACTIVITY}> .
                }}
            }}
        """), f"a cga:{cls} instance must resolve to prov:Activity and declare used/generated"


class TestGraphMetadataVocabulary:
    """R9.2 -- the graph-level metadata vocabulary is declared.

    ``cga:refreshedAt`` is checked for range only. It deliberately declares no
    ``rdfs:domain`` because it applies to both LayerGraph and
    ClassInstanceCount, and ``rdfs:domain`` is an inference rule rather than a
    constraint -- naming one would make a reasoner conclude every refreshed
    inventory record is a layer graph. R9.2's acceptance criterion asks for
    "appropriate" domain and range, and for this term the appropriate domain
    is none.
    """

    OWL = "http://www.w3.org/2002/07/owl#"
    RDFS = "http://www.w3.org/2000/01/rdf-schema#"
    XSD = "http://www.w3.org/2001/XMLSchema#"

    def test_class_instance_count_is_declared(self, loaded_ds):
        assert loaded_ds.backend.ask(f"""
            ASK {{
                GRAPH <{CGA_GRAPH}> {{
                    <urn:holonic:ontology:ClassInstanceCount> a <{self.OWL}Class> .
                }}
            }}
        """), "cga:ClassInstanceCount must be declared"

    @pytest.mark.parametrize(
        "term,kind,domain,rng",
        [
            ("tripleCount", "DatatypeProperty", "LayerGraph", f"{XSD}integer"),
            ("lastModified", "DatatypeProperty", "LayerGraph", f"{XSD}dateTime"),
            ("refreshedAt", "DatatypeProperty", None, f"{XSD}dateTime"),
            ("inGraph", "ObjectProperty", "ClassInstanceCount", "urn:holonic:ontology:LayerGraph"),
            ("class", "ObjectProperty", "ClassInstanceCount", f"{RDFS}Class"),
            ("count", "DatatypeProperty", "ClassInstanceCount", f"{XSD}integer"),
            ("holonLastModified", "DatatypeProperty", "Holon", f"{XSD}dateTime"),
        ],
    )
    def test_metadata_property_declared_with_range(self, loaded_ds, term, kind, domain, rng):
        assert loaded_ds.backend.ask(f"""
            ASK {{
                GRAPH <{CGA_GRAPH}> {{
                    <urn:holonic:ontology:{term}>
                        a <{self.OWL}{kind}> ;
                        <{self.RDFS}range> <{rng}> .
                }}
            }}
        """), f"cga:{term} must be an owl:{kind} with rdfs:range <{rng}>"

        if domain is None:
            return
        assert loaded_ds.backend.ask(f"""
            ASK {{
                GRAPH <{CGA_GRAPH}> {{
                    <urn:holonic:ontology:{term}>
                        <{self.RDFS}domain> <urn:holonic:ontology:{domain}> .
                }}
            }}
        """), f"cga:{term} must declare rdfs:domain cga:{domain}"
