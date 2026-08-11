"""Security regression tests: SPARQL / Turtle injection via provenance writes.

Covers the audit's S1 (critical) — ``record_traversal`` / ``record_validation``
interpolated caller-supplied IRIs and a portal IRI straight into a SPARQL
UPDATE template with no validation or escaping — and S4 — ``_escape_construct``
was backslash-blind, so a trailing backslash could escape the closing
long-string delimiter.

Each test drives a genuine injection payload and asserts it is rejected
(``ValueError``) rather than silently executed, plus round-trips through
rdflib's own parser to prove the escapes both *neutralise* breakouts and
*preserve* the original content.
"""

from __future__ import annotations

import pytest
from rdflib import Graph

from holonic import MembraneHealth
from holonic.client import (
    _escape_construct,
    _escape_ttl,
    _type_term,
    _xsd_datetime_literal,
)

# A payload that, unescaped/unvalidated, closes the <...> IRI slot and
# appends attacker-controlled triples to the UPDATE.
IRI_BREAKOUT = "urn:x> <urn:evil> <urn:evil2> . <urn:pwned"
# Payloads that break a quoted Turtle literal or smuggle structure.
QUOTE_BREAKOUT = 'urn:x" ; <urn:evil> "y'
NEWLINE_BREAKOUT = "urn:x\n<urn:evil> <urn:p> <urn:o> ."
CR_BREAKOUT = "urn:x\r<urn:evil> <urn:p> <urn:o> ."


class TestRecordTraversalInjection:
    @pytest.mark.parametrize(
        "payload", [IRI_BREAKOUT, QUOTE_BREAKOUT, NEWLINE_BREAKOUT, CR_BREAKOUT]
    )
    def test_agent_iri_injection_rejected(self, ds_with_holons, payload):
        with pytest.raises(ValueError, match="agent_iri"):
            ds_with_holons.record_traversal(
                portal_iri="urn:portal:src-to-tgt",
                source_iri="urn:holon:source",
                target_iri="urn:holon:target",
                agent_iri=payload,
            )

    @pytest.mark.parametrize("payload", [IRI_BREAKOUT, QUOTE_BREAKOUT])
    def test_portal_iri_injection_rejected(self, ds_with_holons, payload):
        # portal_iri is embedded in the activity's rdfs:label; a quote or
        # angle bracket there must be rejected before templating.
        with pytest.raises(ValueError, match="portal_iri"):
            ds_with_holons.record_traversal(
                portal_iri=payload,
                source_iri="urn:holon:source",
                target_iri="urn:holon:target",
                agent_iri="urn:agent:test",
            )

    def test_context_graph_injection_rejected(self, ds_with_holons):
        with pytest.raises(ValueError, match="context_graph"):
            ds_with_holons.record_traversal(
                portal_iri="urn:portal:src-to-tgt",
                source_iri="urn:holon:source",
                target_iri="urn:holon:target",
                agent_iri="urn:agent:test",
                context_graph=IRI_BREAKOUT,
            )

    def test_injection_does_not_insert_extra_triples(self, ds_with_holons):
        # The PoC: without the fix, the breakout payload would add an
        # <urn:evil> triple to the store. Confirm it raises AND leaves the
        # backend with no such triple.
        with pytest.raises(ValueError):
            ds_with_holons.record_traversal(
                portal_iri="urn:portal:src-to-tgt",
                source_iri="urn:holon:source",
                target_iri="urn:holon:target",
                agent_iri=IRI_BREAKOUT,
            )
        rows = ds_with_holons.backend.query(
            "SELECT ?s ?p ?o WHERE { GRAPH ?g { <urn:evil> ?p ?o } }"
        )
        assert rows == []

    def test_benign_iris_still_work(self, ds_with_holons):
        # No false positives: a clean call records normally.
        activity = ds_with_holons.record_traversal(
            portal_iri="urn:portal:src-to-tgt",
            source_iri="urn:holon:source",
            target_iri="urn:holon:target",
            agent_iri="urn:agent:test",
        )
        assert activity.startswith("urn:prov:traversal:")


class TestRecordValidationInjection:
    @pytest.mark.parametrize("payload", [IRI_BREAKOUT, QUOTE_BREAKOUT, NEWLINE_BREAKOUT])
    def test_holon_iri_injection_rejected(self, ds_with_holons, payload):
        with pytest.raises(ValueError, match="holon_iri"):
            ds_with_holons.record_validation(
                holon_iri=payload,
                health=MembraneHealth.INTACT,
                agent_iri="urn:agent:test",
            )

    def test_agent_iri_injection_rejected(self, ds_with_holons):
        with pytest.raises(ValueError, match="agent_iri"):
            ds_with_holons.record_validation(
                holon_iri="urn:holon:target",
                health=MembraneHealth.INTACT,
                agent_iri=IRI_BREAKOUT,
            )

    def test_benign_still_works(self, ds_with_holons):
        activity = ds_with_holons.record_validation(
            holon_iri="urn:holon:target",
            health=MembraneHealth.INTACT,
            agent_iri="urn:agent:test",
        )
        assert activity.startswith("urn:prov:validation:")


# S2: holon_type / portal_type were spliced raw into the Turtle body when
# they contained a ':' (the old ``":" in holon_type`` discriminator), and
# merely wrapped in <...> without validation otherwise. Both let a crafted
# type term inject triples or break out of the <...> slot.
TYPE_PNAME_BREAKOUT = "cga:Holon . <urn:evil> a cga:Evil"  # old ':' raw path
TYPE_ANGLE_BREAKOUT = "foo> a cga:X . <urn:evil"  # old no-colon <...> path
TYPE_QUOTE_BREAKOUT = 'cga:X" . <urn:evil'


class TestTypeTermHelper:
    def test_bare_pname_emitted_verbatim(self):
        assert _type_term("cga:TransformPortal") == "cga:TransformPortal"
        assert _type_term("ext:NeuralPortal") == "ext:NeuralPortal"

    def test_full_iri_wrapped_in_angle_brackets(self):
        assert _type_term("http://example.org/Foo") == "<http://example.org/Foo>"
        # A multi-colon URN is not a single-colon PNAME -> treated as an IRI.
        assert _type_term("urn:holonic:ontology:Data") == "<urn:holonic:ontology:Data>"

    @pytest.mark.parametrize(
        "payload", [TYPE_PNAME_BREAKOUT, TYPE_ANGLE_BREAKOUT, TYPE_QUOTE_BREAKOUT]
    )
    def test_injection_payloads_rejected(self, payload):
        with pytest.raises(ValueError):
            _type_term(payload, "holon_type")


class TestHolonTypeInjection:
    @pytest.mark.parametrize(
        "payload", [TYPE_PNAME_BREAKOUT, TYPE_ANGLE_BREAKOUT, TYPE_QUOTE_BREAKOUT]
    )
    def test_add_holon_type_injection_rejected(self, ds, payload):
        with pytest.raises(ValueError, match="holon_type"):
            ds.add_holon("urn:holon:x", "X", holon_type=payload)

    def test_injection_inserts_no_extra_triples(self, ds):
        with pytest.raises(ValueError):
            ds.add_holon("urn:holon:x", "X", holon_type=TYPE_PNAME_BREAKOUT)
        rows = ds.backend.query("SELECT ?p ?o WHERE { GRAPH ?g { <urn:evil> ?p ?o } }")
        assert rows == []

    def test_benign_pname_and_iri_still_work(self, ds):
        ds.add_holon("urn:holon:a", "A", holon_type="cga:DataHolon")
        ds.add_holon("urn:holon:b", "B", holon_type="http://example.org/Custom")
        # Both types land as rdf:type triples in the registry.
        rows = ds.backend.query(
            "SELECT ?h ?t WHERE { GRAPH ?g { ?h a ?t } FILTER(?h IN "
            "(<urn:holon:a>, <urn:holon:b>)) }"
        )
        types = {(r["h"], r["t"]) for r in rows}
        assert ("urn:holon:a", "urn:holonic:ontology:DataHolon") in types
        assert ("urn:holon:b", "http://example.org/Custom") in types


class TestPortalTypeInjection:
    @pytest.mark.parametrize(
        "payload", [TYPE_PNAME_BREAKOUT, TYPE_ANGLE_BREAKOUT, TYPE_QUOTE_BREAKOUT]
    )
    def test_add_portal_type_injection_rejected(self, ds, payload):
        with pytest.raises(ValueError, match="portal_type"):
            ds.add_portal(
                "urn:portal:p",
                "urn:holon:source",
                "urn:holon:target",
                portal_type=payload,
            )


class TestEscapeHelpers:
    def test_escape_ttl_round_trips_control_chars(self):
        # A string with every character _escape_ttl must neutralise. After
        # escaping and embedding in a Turtle literal, rdflib must parse it
        # back to exactly the original value — proving no breakout and no
        # data loss.
        raw = 'quote " backslash \\ newline \n cr \r tab \t end'
        ttl = f'<urn:s> <urn:p> "{_escape_ttl(raw)}" .'
        g = Graph()
        g.parse(data=ttl, format="turtle")
        (value,) = [str(o) for _, _, o in g]
        assert value == raw

    def test_escape_ttl_escapes_carriage_return(self):
        # Regression: the old helper escaped \n but not \r, leaving a bare
        # CR inside the serialized literal.
        assert "\r" not in _escape_ttl("a\rb")
        assert _escape_ttl("a\rb") == "a\\rb"

    def test_escape_construct_round_trips_backslash(self):
        # S4: a backslash in a CONSTRUCT body stored as a triple-quoted
        # literal must survive; the old helper left backslashes untouched,
        # so a trailing one could escape the closing delimiter.
        raw = 'FILTER(regex(?x, "a\\\\b")) # trailing backslash \\'
        ttl = f'<urn:s> <urn:p> """{_escape_construct(raw)}""" .'
        g = Graph()
        g.parse(data=ttl, format="turtle")
        (value,) = [str(o) for _, _, o in g]
        assert value == raw

    def test_escape_construct_neutralises_triple_quote(self):
        raw = 'a """ b'
        ttl = f'<urn:s> <urn:p> """{_escape_construct(raw)}""" .'
        g = Graph()
        g.parse(data=ttl, format="turtle")
        (value,) = [str(o) for _, _, o in g]
        assert value == raw


class TestSecondOrderInjection:
    """S3: store-derived IRIs re-interpolated into fresh queries.

    The read path used to splice result-row IRIs straight back into new
    query text (``f"<{iri}>"``), so an IRI that reached the store via raw
    ingestion (bypassing the validating ``add_*`` methods, e.g. a ``\\u003E``
    UCHAR escape yielding a stored URIRef holding a literal ``>``) became a
    delayed injection primitive. Those sites now bind the IRI as a validated
    ``rdflib`` term at a single chokepoint (``_bind_iri``); the write-only
    metadata path, which cannot use ``initBindings``, validates at entry.
    """

    @pytest.mark.parametrize(
        "payload", [IRI_BREAKOUT, QUOTE_BREAKOUT, NEWLINE_BREAKOUT, CR_BREAKOUT]
    )
    def test_bind_iri_rejects_breakout(self, payload):
        from holonic.client import _bind_iri

        with pytest.raises(ValueError):
            _bind_iri(payload, "iri")

    def test_bind_iri_wraps_valid_iri_as_uriref(self):
        from rdflib import URIRef

        from holonic.client import _bind_iri

        # An ordinary http:// IRI binds as a URIRef -- not a Literal, which
        # was the 0.7.x urn:-only heuristic's mistake (A1).
        assert _bind_iri("http://example.org/x") == URIRef("http://example.org/x")

    @pytest.mark.parametrize("payload", [IRI_BREAKOUT, QUOTE_BREAKOUT])
    def test_scope_neighbors_rejects_hostile_frontier(self, ds, payload):
        # In a real BFS the frontier IRI is a store-derived result row from
        # the previous hop. Binding it means a hostile value raises here
        # instead of re-interpolating into the neighbour walk query.
        from holonic.scope import ScopeResolver

        resolver = ScopeResolver(backend=ds.backend, registry_iri=ds.registry_iri)
        with pytest.raises(ValueError):
            resolver._neighbors(payload, "network")

    @pytest.mark.parametrize("payload", [IRI_BREAKOUT, QUOTE_BREAKOUT])
    def test_metadata_read_rejects_hostile_graph_iri(self, ds, payload):
        # The metadata clear/insert writes are SPARQL UPDATE (no
        # initBindings), so graph IRIs are validated at the single
        # read+write chokepoint before any splice.
        with pytest.raises(ValueError):
            ds.get_graph_metadata(payload)


class TestAuditTrailSinceInjection:
    """The ``since`` filter on ``collect_audit_trail``.

    ``collect_audit_trail`` assembles its query textually (strip
    ``ORDER BY``, splice a ``FILTER``, append ``LIMIT``/``OFFSET``), and
    ``limit``/``offset`` were already ``int()``-cast. ``since`` was not:
    it went into the ``FILTER`` raw, so a value carrying a quote closed
    the literal and appended attacker-chosen patterns to a query the
    caller believed was a timestamp filter.
    """

    # Closes the typed literal, drops the intended comparison, and
    # re-opens a literal so the remaining template text still parses.
    SINCE_BREAKOUT = (
        '2026-01-01T00:00:00"^^<http://www.w3.org/2001/XMLSchema#dateTime>)'
        ' UNION { ?activity ?p ?o } FILTER("x'
    )

    @pytest.mark.parametrize(
        "payload",
        [
            SINCE_BREAKOUT,
            '2026-01-01T00:00:00" ',
            "not-a-timestamp",
            "2026-01-01",  # date only: no time component
            "",
            "2026-01-01T00:00:00Z\n} INSERT DATA { <urn:evil> <urn:p> <urn:o> } #",
            # A trailing newline only: '$'-anchored patterns accept this,
            # so the validator is anchored with \A/\Z instead.
            "2026-01-01T00:00:00Z\n",
        ],
    )
    def test_malformed_since_rejected(self, ds, payload):
        with pytest.raises(ValueError):
            ds.collect_audit_trail(since=payload)

    def test_rejected_before_any_query(self, ds, monkeypatch):
        # Validation happens once, up front -- a bad value must not reach
        # the store even for the first of the two collected activity kinds.
        def explode(*args, **kwargs):
            raise AssertionError("backend.query called with an invalid `since`")

        monkeypatch.setattr(ds.backend, "query", explode)
        with pytest.raises(ValueError):
            ds.collect_audit_trail(since='2026-01-01T00:00:00" ) (')

    def test_canonical_since_emits_typed_literal(self):
        assert _xsd_datetime_literal("2026-01-31T12:00:00") == (
            '"2026-01-31T12:00:00"^^<http://www.w3.org/2001/XMLSchema#dateTime>'
        )

    def test_timezone_is_normalized_by_rdflib(self):
        # rdflib canonicalizes the lexical form on the way out, so the
        # emitted literal is not always byte-identical to the caller's
        # string. 'Z' and '+00:00' denote the same instant, so this is a
        # serialization detail -- pinned here so a future rdflib change
        # that alters it shows up as a test failure rather than a silently
        # different query.
        assert _xsd_datetime_literal("2026-01-31T12:00:00Z") == (
            '"2026-01-31T12:00:00+00:00"^^<http://www.w3.org/2001/XMLSchema#dateTime>'
        )

    @pytest.mark.parametrize(
        "value",
        [
            "2026-01-31T12:00:00",
            "2026-01-31T12:00:00Z",
            "2026-01-31T12:00:00.123456",
            "2026-01-31T12:00:00+05:30",
            "2026-01-31T12:00:00-08:00",
            "-0044-03-15T12:00:00Z",  # negative year: legal xsd:dateTime
        ],
    )
    def test_well_formed_since_accepted(self, value):
        # Asserted on shape rather than exact text: rdflib owns the
        # lexical form, and the security property is that the result is
        # a single closed, typed literal with no bare quote inside it.
        n3 = _xsd_datetime_literal(value)
        assert n3.startswith('"')
        assert n3.endswith('"^^<http://www.w3.org/2001/XMLSchema#dateTime>')
        assert '"' not in n3[1 : n3.index('"^^')]

    def test_since_filters_the_real_trail(self, ds_with_holons):
        # End-to-end: the emitted FILTER is valid SPARQL and actually
        # filters, so the escaping did not merely make the query inert.
        ds_with_holons.traverse(
            "urn:holon:source",
            "urn:holon:target",
            validate=False,
            agent_iri="urn:agent:test",
        )
        assert len(ds_with_holons.collect_audit_trail().traversals) >= 1

        past = ds_with_holons.collect_audit_trail(since="2000-01-01T00:00:00Z")
        future = ds_with_holons.collect_audit_trail(since="2999-01-01T00:00:00Z")
        assert len(past.traversals) >= 1
        assert future.traversals == []
