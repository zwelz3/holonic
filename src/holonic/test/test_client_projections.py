"""Tests for client-level projection and raw-SPARQL methods.

Covers:
    - HolonicDataset.project_holon (with and without store_as)
    - HolonicDataset.project_holarchy
    - HolonicDataset.apply_pipeline
    - HolonicDataset.construct / .update
    - HolonicDataset.materialize_rdfs (gated on owlrl)
"""

import pytest
from rdflib import Graph

from holonic import (
    CONSTRUCT_STRIP_TYPES,
    ProjectedGraph,
    ProjectionPipeline,
    localize_predicates,
    strip_blank_nodes,
)

# ══════════════════════════════════════════════════════════════
# project_holon
# ══════════════════════════════════════════════════════════════


class TestProjectHolon:
    def test_empty_holon_returns_empty_lpg(self, ds):
        ds.add_holon("urn:holon:empty", "Empty")
        lpg = ds.project_holon("urn:holon:empty")
        assert isinstance(lpg, ProjectedGraph)
        assert len(lpg.nodes) == 0

    def test_single_interior_projects(self, ds):
        ds.add_holon("urn:holon:p", "P")
        ds.add_interior(
            "urn:holon:p",
            """
            @prefix ex: <urn:ex:> .
            <urn:n:1> a ex:Thing ;
                <http://www.w3.org/2000/01/rdf-schema#label> "One" ;
                ex:value 42 .
            <urn:n:2> a ex:Thing ;
                <http://www.w3.org/2000/01/rdf-schema#label> "Two" .
            <urn:n:1> ex:linksTo <urn:n:2> .
        """,
        )
        lpg = ds.project_holon("urn:holon:p")
        assert isinstance(lpg, ProjectedGraph)
        assert "urn:n:1" in lpg.nodes
        assert "urn:n:2" in lpg.nodes
        assert any(e.predicate == "urn:ex:linksTo" for e in lpg.edges)

    def test_multiple_interiors_are_merged(self, ds):
        ds.add_holon("urn:holon:m", "Multi")
        ds.add_interior(
            "urn:holon:m",
            "<urn:a> a <urn:T> .",
            graph_iri="urn:holon:m/interior/x",
        )
        ds.add_interior(
            "urn:holon:m",
            "<urn:b> a <urn:T> .",
            graph_iri="urn:holon:m/interior/y",
        )
        lpg = ds.project_holon("urn:holon:m")
        assert "urn:a" in lpg.nodes
        assert "urn:b" in lpg.nodes

    def test_lpg_kwargs_forwarded(self, ds):
        ds.add_holon("urn:holon:t", "T")
        ds.add_interior(
            "urn:holon:t",
            """
            @prefix ex: <urn:ex:> .
            <urn:n:1> a ex:Thing ;
                ex:value 42 .
        """,
        )
        lpg = ds.project_holon(
            "urn:holon:t",
            collapse_types=True,
            collapse_literals=True,
        )
        node = lpg.nodes.get("urn:n:1")
        assert node is not None
        assert "urn:ex:Thing" in node.types
        assert node.attributes.get("urn:ex:value") == 42

    def test_store_as_writes_named_graph_and_registers_layer(self, ds):
        ds.add_holon("urn:holon:s", "S")
        ds.add_interior(
            "urn:holon:s",
            """
            @prefix ex: <urn:ex:> .
            <urn:n:1> a ex:Thing ;
                <http://www.w3.org/2000/01/rdf-schema#label> "One" .
            <urn:n:1> ex:linksTo <urn:n:2> .
            <urn:n:2> a ex:Thing .
        """,
        )
        ds.project_holon(
            "urn:holon:s",
            store_as="urn:holon:s/projection/viz",
        )
        # Stored graph exists and has triples
        assert ds.backend.graph_exists("urn:holon:s/projection/viz")
        g = ds.backend.get_graph("urn:holon:s/projection/viz")
        assert len(g) > 0
        # Registered as a projection layer on the holon
        info = ds.get_holon("urn:holon:s")
        assert "urn:holon:s/projection/viz" in info.projection_graphs


# ══════════════════════════════════════════════════════════════
# project_holarchy
# ══════════════════════════════════════════════════════════════


class TestProjectHolarchy:
    def test_holarchy_topology_includes_holons(self, ds):
        ds.add_holon("urn:holon:org", "Org")
        ds.add_holon("urn:holon:eng", "Eng", member_of="urn:holon:org")
        lpg = ds.project_holarchy()
        assert isinstance(lpg, ProjectedGraph)
        assert "urn:holon:org" in lpg.nodes
        assert "urn:holon:eng" in lpg.nodes

    def test_holarchy_includes_portals(self, ds_with_holons):
        lpg = ds_with_holons.project_holarchy()
        # Portal should appear as a node (it's typed cga:TransformPortal)
        assert "urn:portal:src-to-tgt" in lpg.nodes

    def test_holarchy_member_of_edges_present(self, ds):
        ds.add_holon("urn:holon:org", "Org")
        ds.add_holon("urn:holon:eng", "Eng", member_of="urn:holon:org")
        lpg = ds.project_holarchy()
        member_edges = [e for e in lpg.edges if e.predicate == "urn:holonic:ontology:memberOf"]
        assert len(member_edges) >= 1
        assert any(
            e.source == "urn:holon:eng" and e.target == "urn:holon:org" for e in member_edges
        )


# ══════════════════════════════════════════════════════════════
# apply_pipeline
# ══════════════════════════════════════════════════════════════


class TestApplyPipeline:
    def test_pipeline_returns_graph(self, ds):
        ds.add_holon("urn:holon:p", "P")
        ds.add_interior(
            "urn:holon:p",
            """
            @prefix ex: <urn:ex:> .
            <urn:n:1> a ex:Thing ;
                ex:value 42 .
        """,
        )
        pipeline = ProjectionPipeline("strip")
        pipeline.add_construct("strip_types", CONSTRUCT_STRIP_TYPES)
        result = ds.apply_pipeline("urn:holon:p", pipeline)
        assert isinstance(result, Graph)
        # rdf:type stripped
        from rdflib import RDF

        assert len(list(result.triples((None, RDF.type, None)))) == 0

    def test_pipeline_with_python_transform(self, ds):
        ds.add_holon("urn:holon:p", "P")
        ds.add_interior(
            "urn:holon:p",
            """
            @prefix ex: <urn:ex:> .
            <urn:n:1> ex:foo "bar" .
        """,
        )
        pipeline = ProjectionPipeline("localize")
        pipeline.add_transform("localize", localize_predicates)
        result = ds.apply_pipeline("urn:holon:p", pipeline)
        for _, p, _ in result:
            assert "urn:local:" in str(p)

    def test_apply_pipeline_store_as(self, ds):
        ds.add_holon("urn:holon:p", "P")
        ds.add_interior("urn:holon:p", "<urn:a> <urn:b> <urn:c> .")
        pipeline = ProjectionPipeline("noop")
        pipeline.add_transform("strip", strip_blank_nodes)
        ds.apply_pipeline(
            "urn:holon:p",
            pipeline,
            store_as="urn:holon:p/projection/clean",
        )
        assert ds.backend.graph_exists("urn:holon:p/projection/clean")
        info = ds.get_holon("urn:holon:p")
        assert "urn:holon:p/projection/clean" in info.projection_graphs

    def test_empty_holon_returns_empty_graph(self, ds):
        ds.add_holon("urn:holon:e", "E")
        pipeline = ProjectionPipeline("noop")
        result = ds.apply_pipeline("urn:holon:e", pipeline)
        assert isinstance(result, Graph)
        assert len(result) == 0


# ══════════════════════════════════════════════════════════════
# Raw SPARQL pass-throughs
# ══════════════════════════════════════════════════════════════


class TestRawSparqlPassthrough:
    def test_construct_returns_graph(self, ds):
        ds.add_holon("urn:holon:c", "C")
        ds.add_interior(
            "urn:holon:c",
            "<urn:s> <urn:p> <urn:o> .",
        )
        g = ds.construct("""
            CONSTRUCT { ?s <urn:label> ?o }
            WHERE {
                GRAPH <urn:holon:c/interior> { ?s <urn:p> ?o }
            }
        """)
        assert isinstance(g, Graph)
        assert len(g) == 1

    def test_update_writes_named_graph(self, ds):
        ds.update("""
            INSERT DATA {
                GRAPH <urn:g:client-update> {
                    <urn:a> <urn:b> "client" .
                }
            }
        """)
        rows = ds.query("""
            SELECT ?o WHERE {
                GRAPH <urn:g:client-update> { <urn:a> <urn:b> ?o }
            }
        """)
        assert len(rows) == 1
        assert rows[0]["o"] == "client"


# ══════════════════════════════════════════════════════════════
# materialize_rdfs (gated on owlrl)
# ══════════════════════════════════════════════════════════════


class TestMaterializeRdfs:
    def test_rdfs_subclass_inference(self, ds):
        pytest.importorskip("owlrl")

        ds.add_holon("urn:holon:r", "R")
        ds.add_interior(
            "urn:holon:r",
            """
            @prefix ex:   <urn:ex:> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            ex:Dog rdfs:subClassOf ex:Animal .
            <urn:rex> a ex:Dog .
        """,
        )
        inferred_iri = ds.materialize_rdfs("urn:holon:r")
        assert inferred_iri == "urn:holon:r/interior/inferred"
        g = ds.backend.get_graph(inferred_iri)
        # Should contain the entailed triple <urn:rex> a ex:Animal
        from rdflib import RDF, URIRef

        assert (
            URIRef("urn:rex"),
            RDF.type,
            URIRef("urn:ex:Animal"),
        ) in g

    def test_inferred_graph_is_registered_as_interior(self, ds):
        pytest.importorskip("owlrl")

        ds.add_holon("urn:holon:r", "R")
        ds.add_interior(
            "urn:holon:r",
            """
            @prefix ex:   <urn:ex:> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            ex:Dog rdfs:subClassOf ex:Animal .
            <urn:rex> a ex:Dog .
        """,
        )
        ds.materialize_rdfs("urn:holon:r")
        info = ds.get_holon("urn:holon:r")
        # Original interior + inferred interior
        assert "urn:holon:r/interior/inferred" in info.interior_graphs
        assert len(info.interior_graphs) == 2
