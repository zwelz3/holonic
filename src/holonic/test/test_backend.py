"""Tests for HolonicStore protocol and rdflib implementation."""

import pytest
from rdflib import Graph, URIRef

from holonic.backends import AbstractHolonicStore, HolonicStore, RdflibBackend


class TestProtocolConformance:
    def test_rdflib_backend_implements_protocol(self):
        backend = RdflibBackend()
        assert isinstance(backend, HolonicStore)

    def test_rdflib_backend_inherits_abc(self):
        """First-party backends dogfood AbstractHolonicStore."""
        backend = RdflibBackend()
        assert isinstance(backend, AbstractHolonicStore)


class TestRdflibBackend:
    @pytest.fixture
    def backend(self):
        return RdflibBackend()

    def test_parse_and_retrieve(self, backend):
        backend.parse_into(
            "urn:g:1",
            """
            <urn:s> <urn:p> "hello" .
        """,
            "turtle",
        )
        g = backend.get_graph("urn:g:1")
        assert len(g) == 1

    def test_graph_exists(self, backend):
        assert not backend.graph_exists("urn:g:empty")
        backend.parse_into("urn:g:full", "<urn:a> <urn:b> <urn:c> .")
        assert backend.graph_exists("urn:g:full")

    def test_put_replaces(self, backend):
        backend.parse_into("urn:g:1", "<urn:a> <urn:b> <urn:c> .")
        g2 = Graph()
        g2.add((URIRef("urn:x"), URIRef("urn:y"), URIRef("urn:z")))
        backend.put_graph("urn:g:1", g2)
        g = backend.get_graph("urn:g:1")
        assert (URIRef("urn:x"), URIRef("urn:y"), URIRef("urn:z")) in g
        assert (URIRef("urn:a"), URIRef("urn:b"), URIRef("urn:c")) not in g

    def test_post_appends(self, backend):
        backend.parse_into("urn:g:1", "<urn:a> <urn:b> <urn:c> .")
        g2 = Graph()
        g2.add((URIRef("urn:x"), URIRef("urn:y"), URIRef("urn:z")))
        backend.post_graph("urn:g:1", g2)
        g = backend.get_graph("urn:g:1")
        assert len(g) == 2

    def test_delete_graph(self, backend):
        backend.parse_into("urn:g:1", "<urn:a> <urn:b> <urn:c> .")
        backend.delete_graph("urn:g:1")
        assert not backend.graph_exists("urn:g:1")

    def test_query_select(self, backend):
        backend.parse_into(
            "urn:g:1",
            """
            @prefix ex: <urn:ex:> .
            ex:a ex:val 42 .
            ex:b ex:val 99 .
        """,
        )
        rows = backend.query("""
            SELECT ?s ?v WHERE {
                GRAPH <urn:g:1> { ?s <urn:ex:val> ?v }
            }
            ORDER BY ?v
        """)
        assert len(rows) == 2
        assert rows[0]["v"] == 42
        assert rows[1]["v"] == 99

    def test_construct(self, backend):
        backend.parse_into(
            "urn:g:1",
            """
            <urn:s> a <urn:T> ; <urn:name> "test" .
        """,
        )
        g = backend.construct("""
            CONSTRUCT { ?s <urn:label> ?n }
            WHERE {
                GRAPH <urn:g:1> { ?s <urn:name> ?n }
            }
        """)
        assert len(g) == 1

    def test_ask(self, backend):
        backend.parse_into("urn:g:1", "<urn:a> <urn:b> <urn:c> .")
        assert backend.ask("ASK { GRAPH <urn:g:1> { <urn:a> <urn:b> <urn:c> } }")
        assert not backend.ask("ASK { GRAPH <urn:g:1> { <urn:x> <urn:y> <urn:z> } }")

    def test_list_named_graphs(self, backend):
        backend.parse_into("urn:g:alpha", "<urn:a> <urn:b> <urn:c> .")
        backend.parse_into("urn:g:beta", "<urn:x> <urn:y> <urn:z> .")
        graphs = backend.list_named_graphs()
        assert "urn:g:alpha" in graphs
        assert "urn:g:beta" in graphs

    def test_update(self, backend):
        backend.update("""
            INSERT DATA {
                GRAPH <urn:g:new> { <urn:a> <urn:b> "inserted" }
            }
        """)
        assert backend.graph_exists("urn:g:new")
        rows = backend.query("""
            SELECT ?o WHERE {
                GRAPH <urn:g:new> { <urn:a> <urn:b> ?o }
            }
        """)
        assert len(rows) == 1


class TestRdflibBackendBindings:
    """The **bindings kwarg follows the explicit term-wrapper contract.

    0.8.0 (audit A1): an rdflib ``Node`` binds verbatim; a bare Python
    value binds as a typed ``Literal``. IRIs -- of *any* scheme, not just
    ``urn:`` -- must be passed as ``URIRef``. This replaced the 0.7.x
    heuristic that promoted only ``urn:``-prefixed strings and silently
    mis-bound ``http://`` strings as literals.
    """

    @pytest.fixture
    def backend(self):
        b = RdflibBackend()
        b.parse_into(
            "urn:g:bind",
            """
            @prefix ex: <urn:ex:> .
            ex:alice ex:knows ex:bob .
            ex:bob ex:knows ex:carol .
        """,
        )
        return b

    def test_query_with_uriref_binding(self, backend):
        rows = backend.query(
            """
            SELECT ?o WHERE {
                GRAPH <urn:g:bind> { ?s <urn:ex:knows> ?o }
            }
            """,
            s=URIRef("urn:ex:alice"),
        )
        assert len(rows) == 1
        assert rows[0]["o"] == "urn:ex:bob"

    def test_http_iri_binds_correctly(self, backend):
        # The 0.7.x urn:-only heuristic left an http:// string as a
        # Literal, so this query matched nothing. Now URIRef binds it.
        backend.parse_into(
            "urn:g:bind",
            "<http://example.org/x> <urn:ex:knows> <urn:ex:bob> .",
        )
        rows = backend.query(
            """
            SELECT ?o WHERE {
                GRAPH <urn:g:bind> { ?s <urn:ex:knows> ?o }
            }
            """,
            s=URIRef("http://example.org/x"),
        )
        assert len(rows) == 1
        assert rows[0]["o"] == "urn:ex:bob"

    def test_bare_string_binds_as_literal(self, backend):
        # A bare Python string is a Literal, never an IRI. Bound into the
        # subject slot it matches no IRI-subject triple -> zero rows.
        rows = backend.query(
            """
            SELECT ?o WHERE {
                GRAPH <urn:g:bind> { ?s <urn:ex:knows> ?o }
            }
            """,
            s="urn:ex:alice",
        )
        assert rows == []

    def test_construct_with_binding(self, backend):
        g = backend.construct(
            """
            CONSTRUCT { ?s <urn:label> "found" }
            WHERE {
                GRAPH <urn:g:bind> { ?s <urn:ex:knows> ?o }
            }
            """,
            s=URIRef("urn:ex:alice"),
        )
        assert len(g) == 1

    def test_ask_with_binding(self, backend):
        assert backend.ask(
            """
            ASK { GRAPH <urn:g:bind> { ?s <urn:ex:knows> <urn:ex:bob> } }
            """,
            s=URIRef("urn:ex:alice"),
        )
        assert not backend.ask(
            """
            ASK { GRAPH <urn:g:bind> { ?s <urn:ex:knows> <urn:ex:bob> } }
            """,
            s=URIRef("urn:ex:carol"),
        )


class TestPreparedQueryCache:
    """P1: identical template strings parse once (cached algebra)."""

    def test_repeated_template_hits_cache(self):
        from holonic.backends.rdflib_backend import _prepare

        _prepare.cache_clear()
        backend = RdflibBackend()
        backend.parse_into("urn:g:c", "<urn:a> <urn:ex:knows> <urn:b> .")
        template = "SELECT ?o WHERE { GRAPH <urn:g:c> { ?s <urn:ex:knows> ?o } }"
        for _ in range(5):
            backend.query(template, s=URIRef("urn:a"))
        info = _prepare.cache_info()
        # One miss (first parse) then four hits -- not five parses.
        assert info.misses == 1
        assert info.hits == 4


class TestBindingCoercion:
    """Unit tests for the shared _bindings helpers (both backends)."""

    def test_to_term_passes_nodes_through(self):
        from holonic.backends._bindings import to_term

        u = URIRef("http://example.org/x")
        assert to_term(u) is u

    def test_to_term_wraps_scalars_as_literal(self):
        from rdflib import Literal

        from holonic.backends._bindings import to_term

        assert to_term(42) == Literal(42)
        assert isinstance(to_term("plain"), Literal)

    def test_substitute_uses_n3_and_word_boundary(self):
        from holonic.backends._bindings import substitute_bindings

        sparql = "SELECT * WHERE { ?holon ?p ?holonType }"
        out = substitute_bindings(sparql, {"holon": URIRef("urn:h:1")})
        # ?holon replaced, ?holonType left intact.
        assert "<urn:h:1>" in out
        assert "?holonType" in out
        assert "?holon " not in out

    def test_substitute_escapes_literals(self):
        from rdflib import Literal

        from holonic.backends._bindings import substitute_bindings

        # A literal carrying SPARQL metacharacters must come back as a
        # single valid, self-delimiting literal -- the whole payload binds
        # as data, never breaking out to inject a clause. Prove it by
        # running the substituted ASK: it must parse and match the exact
        # literal (True), which is only possible if no breakout occurred.
        hostile = Literal('a" . } DROP ALL {')
        backend = RdflibBackend()
        g = Graph()
        g.add((URIRef("urn:s"), URIRef("urn:p"), hostile))
        backend.put_graph("urn:g:h", g)
        out = substitute_bindings("ASK { GRAPH <urn:g:h> { <urn:s> <urn:p> ?v } }", {"v": hostile})
        assert backend.ask(out) is True


class TestRdflibBackendDatasetAccess:
    """The .dataset property exposes the underlying rdflib.Dataset."""

    def test_dataset_property_is_rdflib_dataset(self):
        from rdflib import Dataset

        b = RdflibBackend()
        assert isinstance(b.dataset, Dataset)

    def test_constructor_accepts_existing_dataset(self):
        from rdflib import Dataset

        ds = Dataset()
        ds.graph(URIRef("urn:g:pre")).add((URIRef("urn:a"), URIRef("urn:b"), URIRef("urn:c")))
        b = RdflibBackend(dataset=ds)
        assert b.graph_exists("urn:g:pre")
        assert b.dataset is ds


class TestRdflibBackendQueryFormGuards:
    """Wrong query form must raise a clear error, not crash on None or lie.

    Regression for the audit 'typing/rdflib-backend-returns-none-as-graph'
    finding: rdflib's Result.vars / .graph / .askAnswer are None for the
    wrong query form and were dereferenced unguarded.
    """

    @pytest.fixture
    def backend(self):
        b = RdflibBackend()
        b.parse_into("urn:g:1", "<urn:s> <urn:p> <urn:o> .")
        return b

    def test_query_rejects_construct(self, backend):
        with pytest.raises(ValueError, match="SELECT"):
            backend.query("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")

    def test_query_rejects_ask(self, backend):
        with pytest.raises(ValueError, match="SELECT"):
            backend.query("ASK { ?s ?p ?o }")

    def test_construct_rejects_select(self, backend):
        with pytest.raises(ValueError, match="CONSTRUCT"):
            backend.construct("SELECT ?s WHERE { ?s ?p ?o }")

    def test_ask_rejects_select(self, backend):
        # Previously bool(None) -> silently False; now a clear error.
        with pytest.raises(ValueError, match="ASK"):
            backend.ask("SELECT ?s WHERE { ?s ?p ?o }")


class TestNoDefaultGraphFlattening:
    """R1.4 -- every triple the library writes belongs to a named graph.

    The four-graph model rests on layer membership being discoverable by
    SPARQL from the holon IRI. A triple in the default graph belongs to no
    layer, so it is outside the model entirely: it cannot be scoped, governed
    by a membrane, or attributed to a holon. One such write is enough to make
    ``GRAPH ?g`` traversal incomplete without anything reporting it.

    ``Dataset(default_union=True)`` makes this easy to miss -- an unscoped
    SELECT still returns the triple, because the union includes the default
    graph, so a leak looks exactly like a correct write until someone asks
    which graph it came from. This inspects the default context directly.
    """

    @staticmethod
    def _default_graph_triples(ds):
        """Triples sitting in the dataset's default context."""
        return list(ds.backend.ds.default_context)

    def test_fresh_dataset_has_empty_default_graph(self, ds):
        assert self._default_graph_triples(ds) == []

    def test_full_lifecycle_writes_nothing_to_the_default_graph(self, ds):
        """Exercise every write path, then assert the default graph is untouched."""
        ds.add_holon("urn:holon:a", "A")
        ds.add_holon("urn:holon:b", "B", member_of="urn:holon:a")
        ds.add_interior("urn:holon:a", "<urn:item:1> a <urn:ex:Item> .")
        ds.add_boundary(
            "urn:holon:a",
            """
            <urn:shapes:ItemShape> a sh:NodeShape ;
                sh:targetClass <urn:ex:Item> .
            """,
        )
        ds.add_portal(
            "urn:portal:a-b",
            source_iri="urn:holon:a",
            target_iri="urn:holon:b",
            construct_query=(
                "CONSTRUCT { ?s a <urn:ex:Copied> } "
                "WHERE { GRAPH <urn:holon:a/interior> { ?s a <urn:ex:Item> } }"
            ),
        )
        ds.validate_membrane("urn:holon:a")
        ds.traverse("urn:holon:a", "urn:holon:b", validate=False)

        leaked = self._default_graph_triples(ds)
        assert leaked == [], (
            f"{len(leaked)} triple(s) reached the default graph, which belongs "
            f"to no layer and is invisible to GRAPH ?g traversal: {leaked[:3]}"
        )

    def test_every_triple_is_reachable_through_a_named_graph(self, ds):
        """The positive half: what was written is findable via GRAPH ?g.

        Asserting the default graph is empty is not sufficient on its own --
        an empty dataset passes that too. This confirms the writes landed
        somewhere addressable.
        """
        ds.add_holon("urn:holon:a", "A")
        ds.add_interior("urn:holon:a", "<urn:item:1> a <urn:ex:Item> .")

        named_total = sum(
            len(ds.backend.get_graph(g)) for g in ds.backend.list_named_graphs()
        )
        assert named_total > 0, "nothing was written to any named graph"
        assert self._default_graph_triples(ds) == []
