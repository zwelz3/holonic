"""Tests for projection utilities."""

from rdflib import Graph, Literal, Namespace, URIRef, BNode
from rdflib.namespace import RDF, RDFS, XSD, SKOS
from rdflib.collection import Collection

from holonic.projections import (
    ProjectedGraph,
    ProjectionPipeline,
    build_construct,
    collapse_reification,
    extract_types,
    filter_by_class,
    localize_predicates,
    merge_graphs,
    project_to_lpg,
    strip_blank_nodes,
    CONSTRUCT_STRIP_TYPES,
    CONSTRUCT_OBJECT_PROPERTIES_ONLY,
    CONSTRUCT_LABELS_ONLY,
)


EX = Namespace("urn:ex:")


def _make_typed_graph() -> Graph:
    """Graph with typed nodes, literals, and object properties."""
    g = Graph()
    g.add((EX.alice, RDF.type, EX.Person))
    g.add((EX.alice, RDFS.label, Literal("Alice")))
    g.add((EX.alice, EX.age, Literal(30, datatype=XSD.integer)))
    g.add((EX.alice, EX.knows, EX.bob))
    g.add((EX.bob, RDF.type, EX.Person))
    g.add((EX.bob, RDFS.label, Literal("Bob")))
    g.add((EX.bob, EX.age, Literal(25, datatype=XSD.integer)))
    return g


def _make_blank_node_graph() -> Graph:
    """Graph with blank nodes for structured values."""
    g = Graph()
    addr = BNode()
    g.add((EX.alice, RDF.type, EX.Person))
    g.add((EX.alice, EX.address, addr))
    g.add((addr, EX.street, Literal("123 Main St")))
    g.add((addr, EX.city, Literal("Vancouver")))
    g.add((addr, EX.zip, Literal("V6B 1A1")))
    return g


def _make_list_graph() -> Graph:
    """Graph with an RDF collection (linked list)."""
    g = Graph()
    g.add((EX.alice, RDF.type, EX.Person))
    items = [Literal("Python"), Literal("SPARQL"), Literal("Turtle")]
    list_node = Collection(g, BNode(), items).uri
    g.add((EX.alice, EX.skills, list_node))
    return g


def _make_reified_graph() -> Graph:
    """Graph with RDF reification."""
    g = Graph()
    stmt = EX.stmt1
    g.add((stmt, RDF.type, RDF.Statement))
    g.add((stmt, RDF.subject, EX.alice))
    g.add((stmt, RDF.predicate, EX.knows))
    g.add((stmt, RDF.object, EX.bob))
    g.add((stmt, EX.confidence, Literal(0.95)))
    g.add((stmt, EX.source, Literal("survey-2026")))
    return g


# ══════════════════════════════════════════════════════════════
# project_to_lpg tests
# ══════════════════════════════════════════════════════════════


class TestProjectToLPG:
    def test_basic_projection(self):
        g = _make_typed_graph()
        lpg = project_to_lpg(g)
        assert len(lpg.nodes) >= 2
        assert len(lpg.edges) >= 1  # alice knows bob

    def test_type_collapse(self):
        g = _make_typed_graph()
        lpg = project_to_lpg(g, collapse_types=True)
        alice = lpg.nodes.get(str(EX.alice))
        assert alice is not None
        assert str(EX.Person) in alice.types
        # No edge for rdf:type
        type_edges = [e for e in lpg.edges if e.predicate == str(RDF.type)]
        assert len(type_edges) == 0

    def test_type_no_collapse(self):
        g = _make_typed_graph()
        lpg = project_to_lpg(g, collapse_types=False)
        type_edges = [e for e in lpg.edges if e.predicate == str(RDF.type)]
        assert len(type_edges) >= 2  # alice, bob

    def test_literal_collapse(self):
        g = _make_typed_graph()
        lpg = project_to_lpg(g, collapse_literals=True)
        alice = lpg.nodes.get(str(EX.alice))
        assert alice is not None
        assert alice.attributes.get(str(EX.age)) == 30

    def test_label_capture(self):
        g = _make_typed_graph()
        lpg = project_to_lpg(g)
        alice = lpg.nodes.get(str(EX.alice))
        assert alice is not None
        assert alice.label == "Alice"

    def test_object_property_edge(self):
        g = _make_typed_graph()
        lpg = project_to_lpg(g)
        knows_edges = [e for e in lpg.edges if e.predicate == str(EX.knows)]
        assert len(knows_edges) == 1
        assert knows_edges[0].source == str(EX.alice)
        assert knows_edges[0].target == str(EX.bob)

    def test_blank_node_resolution(self):
        g = _make_blank_node_graph()
        lpg = project_to_lpg(g, resolve_blanks=True)
        alice = lpg.nodes.get(str(EX.alice))
        assert alice is not None
        addr = alice.attributes.get(str(EX.address))
        assert isinstance(addr, dict)
        assert addr.get(str(EX.city)) == "Vancouver"
        assert addr.get(str(EX.street)) == "123 Main St"

    def test_list_resolution(self):
        g = _make_list_graph()
        lpg = project_to_lpg(g, resolve_blanks=True, resolve_lists=True)
        alice = lpg.nodes.get(str(EX.alice))
        assert alice is not None
        skills = alice.attributes.get(str(EX.skills))
        assert isinstance(skills, list)
        assert "Python" in skills
        assert "SPARQL" in skills

    def test_predicate_whitelist(self):
        g = _make_typed_graph()
        lpg = project_to_lpg(g, include_predicates={str(EX.knows)})
        assert len(lpg.edges) == 1
        assert lpg.edges[0].predicate == str(EX.knows)

    def test_predicate_blacklist(self):
        g = _make_typed_graph()
        lpg = project_to_lpg(g, exclude_predicates={str(EX.knows)})
        knows_edges = [e for e in lpg.edges if e.predicate == str(EX.knows)]
        assert len(knows_edges) == 0

    def test_to_dict_serializable(self):
        g = _make_typed_graph()
        lpg = project_to_lpg(g)
        d = lpg.to_dict()
        assert "nodes" in d
        assert "edges" in d
        assert isinstance(d["nodes"], dict)
        assert isinstance(d["edges"], list)
        # Should be JSON-serializable
        import json
        json.dumps(d)  # should not raise


# ══════════════════════════════════════════════════════════════
# collapse_reification tests
# ══════════════════════════════════════════════════════════════


class TestCollapseReification:
    def test_basic_collapse(self):
        g = _make_reified_graph()
        lpg = collapse_reification(g)
        assert len(lpg.edges) == 1
        e = lpg.edges[0]
        assert e.source == str(EX.alice)
        assert e.predicate == str(EX.knows)
        assert e.target == str(EX.bob)

    def test_metadata_preserved(self):
        g = _make_reified_graph()
        lpg = collapse_reification(g, preserve_metadata=True)
        e = lpg.edges[0]
        assert e.attributes.get(str(EX.confidence)) == 0.95
        assert e.attributes.get(str(EX.source)) == "survey-2026"

    def test_metadata_stripped(self):
        g = _make_reified_graph()
        lpg = collapse_reification(g, preserve_metadata=False)
        e = lpg.edges[0]
        assert len(e.attributes) == 0


# ══════════════════════════════════════════════════════════════
# Utility function tests
# ══════════════════════════════════════════════════════════════


class TestUtilityFunctions:
    def test_strip_blank_nodes(self):
        g = _make_blank_node_graph()
        result = strip_blank_nodes(g)
        for s, p, o in result:
            assert not isinstance(s, BNode)
            assert not isinstance(o, BNode)

    def test_extract_types(self):
        g = _make_typed_graph()
        types = extract_types(g)
        assert str(EX.Person) in types[str(EX.alice)]
        assert str(EX.Person) in types[str(EX.bob)]

    def test_merge_graphs(self):
        g1 = Graph()
        g1.add((EX.a, EX.p, Literal("x")))
        g2 = Graph()
        g2.add((EX.b, EX.q, Literal("y")))
        merged = merge_graphs(g1, g2)
        assert len(merged) == 2

    def test_filter_by_class(self):
        g = _make_typed_graph()
        g.add((EX.car, RDF.type, EX.Vehicle))
        g.add((EX.car, EX.color, Literal("red")))
        filtered = filter_by_class(g, str(EX.Person))
        # Should have alice and bob triples, not car
        subjects = set(str(s) for s in filtered.subjects())
        assert str(EX.alice) in subjects
        assert str(EX.bob) in subjects
        assert str(EX.car) not in subjects

    def test_localize_predicates(self):
        g = Graph()
        g.add((EX.a, URIRef("http://example.org/ontology#hasName"), Literal("test")))
        result = localize_predicates(g)
        preds = [str(p) for _, p, _ in result]
        assert any("hasName" in p for p in preds)


# ══════════════════════════════════════════════════════════════
# CONSTRUCT template tests
# ══════════════════════════════════════════════════════════════


class TestConstructTemplates:
    def test_build_construct_no_graph(self):
        q = build_construct(CONSTRUCT_STRIP_TYPES)
        assert "GRAPH" not in q
        assert "rdf:type" in q

    def test_build_construct_with_graph(self):
        q = build_construct(CONSTRUCT_STRIP_TYPES, "urn:g:test")
        assert "GRAPH <urn:g:test>" in q

    def test_strip_types_construct(self):
        g = _make_typed_graph()
        q = build_construct(CONSTRUCT_STRIP_TYPES)
        result = g.query(q).graph
        # No rdf:type triples in result
        type_triples = list(result.triples((None, RDF.type, None)))
        assert len(type_triples) == 0
        # But other triples preserved
        assert len(result) > 0

    def test_object_properties_only(self):
        g = _make_typed_graph()
        q = build_construct(CONSTRUCT_OBJECT_PROPERTIES_ONLY)
        result = g.query(q).graph
        for _, _, o in result:
            assert isinstance(o, URIRef)

    def test_labels_only(self):
        g = _make_typed_graph()
        q = build_construct(CONSTRUCT_LABELS_ONLY)
        result = g.query(q).graph
        for _, p, _ in result:
            assert p == RDFS.label


# ══════════════════════════════════════════════════════════════
# Pipeline tests
# ══════════════════════════════════════════════════════════════


class TestProjectionPipeline:
    def test_empty_pipeline(self):
        g = _make_typed_graph()
        pipeline = ProjectionPipeline("noop")
        result = pipeline.apply(g)
        # Should pass through unchanged
        assert result is g

    def test_single_construct_step(self):
        g = _make_typed_graph()
        pipeline = ProjectionPipeline("strip-types")
        pipeline.add_construct("strip", CONSTRUCT_STRIP_TYPES)
        result = pipeline.apply(g)
        type_triples = list(result.triples((None, RDF.type, None)))
        assert len(type_triples) == 0

    def test_single_transform_step(self):
        g = _make_blank_node_graph()
        pipeline = ProjectionPipeline("clean")
        pipeline.add_transform("strip_blanks", strip_blank_nodes)
        result = pipeline.apply(g)
        for s, _, o in result:
            assert not isinstance(s, BNode)
            assert not isinstance(o, BNode)

    def test_chained_steps(self):
        g = _make_typed_graph()
        pipeline = ProjectionPipeline("viz-prep")
        pipeline.add_construct("strip_types", CONSTRUCT_STRIP_TYPES)
        pipeline.add_transform("localize", localize_predicates)
        result = pipeline.apply(g)
        # No rdf:type, and predicates are localized
        assert len(list(result.triples((None, RDF.type, None)))) == 0
        for _, p, _ in result:
            assert "urn:local:" in str(p)

    def test_apply_to_lpg(self):
        g = _make_typed_graph()
        pipeline = ProjectionPipeline("to-lpg")
        lpg = pipeline.apply_to_lpg(g)
        assert isinstance(lpg, ProjectedGraph)
        assert len(lpg.nodes) >= 2

    def test_fluent_api(self):
        g = _make_typed_graph()
        lpg = (
            ProjectionPipeline("fluent")
            .add_construct("strip", CONSTRUCT_STRIP_TYPES)
            .add_transform("localize", localize_predicates)
            .apply_to_lpg(g)
        )
        assert isinstance(lpg, ProjectedGraph)

    def test_repr(self):
        pipeline = ProjectionPipeline("test")
        pipeline.add_construct("a", "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
        pipeline.add_transform("b", lambda g: g)
        assert "2 steps" in repr(pipeline)
