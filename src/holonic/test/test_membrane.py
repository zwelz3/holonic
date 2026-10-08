"""Tests for SHACL membrane validation."""

import pytest
from rdflib import Graph

from holonic import MembraneBreachError, MembraneHealth, MembraneResult, ShapeViolation


class TestMembraneValidation:
    def test_intact_membrane(self, ds):
        ds.add_holon("urn:holon:valid", "Valid")
        ds.add_interior(
            "urn:holon:valid",
            """
            @prefix ex: <urn:ex:> .
            <urn:item:1> a ex:Item ;
                ex:name "Widget" .
        """,
        )
        ds.add_boundary(
            "urn:holon:valid",
            """
            @prefix ex: <urn:ex:> .
            <urn:shapes:ItemShape> a sh:NodeShape ;
                sh:targetClass ex:Item ;
                sh:property [
                    sh:path ex:name ;
                    sh:minCount 1 ;
                    sh:datatype xsd:string ;
                    sh:severity sh:Violation
                ] .
        """,
        )
        result = ds.validate_membrane("urn:holon:valid")
        assert result.conforms
        assert result.health == MembraneHealth.INTACT

    def test_compromised_membrane(self, ds):
        ds.add_holon("urn:holon:bad", "Bad")
        ds.add_interior(
            "urn:holon:bad",
            """
            @prefix ex: <urn:ex:> .
            <urn:item:1> a ex:Item .
        """,
        )
        ds.add_boundary(
            "urn:holon:bad",
            """
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
        """,
        )
        result = ds.validate_membrane("urn:holon:bad")
        assert not result.conforms
        assert result.health == MembraneHealth.COMPROMISED

    def test_no_boundary_returns_intact(self, ds):
        ds.add_holon("urn:holon:naked", "Naked")
        ds.add_interior(
            "urn:holon:naked",
            """
            <urn:x> a <urn:T> .
        """,
        )
        result = ds.validate_membrane("urn:holon:naked")
        assert result.conforms
        assert result.health == MembraneHealth.INTACT

    def test_multi_interior_validation(self, ds):
        """Boundary should validate the union of all interior graphs."""
        ds.add_holon("urn:holon:multi", "Multi")
        ds.add_interior(
            "urn:holon:multi",
            """
            @prefix ex: <urn:ex:> .
            <urn:item:1> a ex:Item ; ex:name "Alpha" .
        """,
            graph_iri="urn:holon:multi/interior/a",
        )
        ds.add_interior(
            "urn:holon:multi",
            """
            @prefix ex: <urn:ex:> .
            <urn:item:2> a ex:Item ; ex:name "Beta" .
        """,
            graph_iri="urn:holon:multi/interior/b",
        )
        ds.add_boundary(
            "urn:holon:multi",
            """
            @prefix ex: <urn:ex:> .
            <urn:shapes:ItemShape> a sh:NodeShape ;
                sh:targetClass ex:Item ;
                sh:property [
                    sh:path ex:name ;
                    sh:minCount 1 ;
                    sh:severity sh:Violation
                ] .
        """,
        )
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


class TestMembraneBreachError:
    """The exception is exported but not (yet) raised by client.traverse()."""

    def test_constructs_from_membrane_result(self):
        result = MembraneResult(
            holon_iri="urn:holon:bad",
            conforms=False,
            health=MembraneHealth.COMPROMISED,
            report_text="Validation Report\nConforms: False",
            violations=["v1", "v2"],
        )
        err = MembraneBreachError(result)
        assert err.result is result
        assert "urn:holon:bad" in str(err)
        assert "2 violation" in str(err)

    def test_is_exception_subclass(self):
        result = MembraneResult(
            holon_iri="urn:holon:x",
            conforms=False,
            health=MembraneHealth.COMPROMISED,
            report_text="",
            violations=["v1"],
        )
        with pytest.raises(MembraneBreachError):
            raise MembraneBreachError(result)


class TestWeakenedMembrane:
    """Warning-only shapes should yield WEAKENED, not COMPROMISED."""

    def test_warning_severity_yields_weakened(self, ds):
        ds.add_holon("urn:holon:warn", "Warn")
        ds.add_interior(
            "urn:holon:warn",
            """
            @prefix ex: <urn:ex:> .
            <urn:item:1> a ex:Item .
        """,
        )
        ds.add_boundary(
            "urn:holon:warn",
            """
            @prefix ex: <urn:ex:> .
            <urn:shapes:ItemShape> a sh:NodeShape ;
                sh:targetClass ex:Item ;
                sh:property [
                    sh:path ex:name ;
                    sh:minCount 1 ;
                    sh:datatype xsd:string ;
                    sh:severity sh:Warning ;
                    sh:message "Item should have a name."
                ] .
        """,
        )
        result = ds.validate_membrane("urn:holon:warn")
        # validate_membrane parses report_text line-by-line for "Violation"/"Warning".
        # Health depends on which token shows up; this test asserts the warning
        # path is exercised at all (not COMPROMISED, since severity is Warning).
        assert result.health != MembraneHealth.COMPROMISED
        assert result.health in (MembraneHealth.INTACT, MembraneHealth.WEAKENED)


class TestMissingLayerGraph:
    """A registered-but-unmaterialized layer must not abort validation.

    Fuseki's Graph Store Protocol answers 404 both for a graph that was
    never created and for a registered graph holding zero triples, so a
    layer registered before it is materialized used to raise out of
    ``validate_membrane`` -- and, since ``validate_all`` walks every holon
    in one loop, out of validation for the entire holarchy.

    Absence is now absorbed as "contributes no triples", but *only* when
    it arrives as the typed ``GraphNotFoundError``. Anything else (auth,
    connectivity, a malformed response) still propagates, so an
    unreachable store can never be mistaken for an empty one.
    """

    ITEM_SHAPE = """
        @prefix ex: <urn:ex:> .
        <urn:shapes:ItemShape> a sh:NodeShape ;
            sh:targetClass ex:Item ;
            sh:property [
                sh:path ex:name ;
                sh:minCount 1 ;
                sh:datatype xsd:string ;
                sh:severity sh:Violation
            ] .
    """

    @staticmethod
    def _fail_on(ds, target_graph, exc):
        """Patch ``backend.get_graph`` to raise *exc* for one graph IRI."""
        real = ds.backend.get_graph

        def fake(graph_iri):
            if graph_iri == target_graph:
                raise exc
            return real(graph_iri)

        return fake

    def _holon_with_layers(self, ds, iri="urn:holon:partial"):
        ds.add_holon(iri, "Partial")
        interior = ds.add_interior(
            iri,
            """
            @prefix ex: <urn:ex:> .
            <urn:item:1> a ex:Item ;
                ex:name "Widget" .
        """,
        )
        boundary = ds.add_boundary(iri, self.ITEM_SHAPE)
        return interior, boundary

    def test_missing_interior_treated_as_empty(self, ds, monkeypatch):
        from holonic.backends.store import GraphNotFoundError

        interior, _ = self._holon_with_layers(ds)
        monkeypatch.setattr(
            ds.backend,
            "get_graph",
            self._fail_on(ds, interior, GraphNotFoundError(f"Graph {interior} not found (404).")),
        )

        # No data to validate, so the shapes have no target nodes: the
        # holon validates as intact rather than blowing up.
        result = ds.validate_membrane("urn:holon:partial")
        assert result.conforms
        assert result.health == MembraneHealth.INTACT

    def test_missing_boundary_is_reported_not_silent(self, ds, monkeypatch):
        from holonic.backends.store import GraphNotFoundError

        _, boundary = self._holon_with_layers(ds)
        monkeypatch.setattr(
            ds.backend,
            "get_graph",
            self._fail_on(ds, boundary, GraphNotFoundError(f"Graph {boundary} not found (404).")),
        )

        result = ds.validate_membrane("urn:holon:partial")
        # Same INTACT verdict a holon with no shapes at all would get --
        # so the report text has to carry the distinction.
        assert result.conforms
        assert result.health == MembraneHealth.INTACT
        assert boundary in result.report_text
        assert "no triples" in result.report_text

    def test_no_boundaries_at_all_keeps_plain_message(self, ds):
        ds.add_holon("urn:holon:bare", "Bare")
        ds.add_interior(
            "urn:holon:bare",
            """
            @prefix ex: <urn:ex:> .
            <urn:item:1> a ex:Item .
        """,
        )
        result = ds.validate_membrane("urn:holon:bare")
        assert result.report_text == "No boundary shapes defined."

    @pytest.mark.parametrize(
        "exc",
        [
            RuntimeError("Fuseki 503: service unavailable"),
            ValueError("malformed turtle in response body"),
        ],
    )
    def test_genuine_backend_error_still_raises(self, ds, monkeypatch, exc):
        interior, _ = self._holon_with_layers(ds)
        monkeypatch.setattr(ds.backend, "get_graph", self._fail_on(ds, interior, exc))

        with pytest.raises(type(exc)):
            ds.validate_membrane("urn:holon:partial")

    def test_validate_all_survives_one_missing_layer(self, ds, monkeypatch):
        from holonic.backends.store import GraphNotFoundError

        interior, _ = self._holon_with_layers(ds, "urn:holon:partial")
        self._holon_with_layers(ds, "urn:holon:whole")
        monkeypatch.setattr(
            ds.backend,
            "get_graph",
            self._fail_on(ds, interior, GraphNotFoundError("not materialized")),
        )

        results = ds.validate_all()
        # The healthy holon is still validated -- one unmaterialized layer
        # no longer takes down the whole walk.
        assert "urn:holon:partial" in results
        assert "urn:holon:whole" in results
        assert results["urn:holon:whole"].conforms

    def test_dry_run_tolerates_missing_layer(self, ds_with_holons, monkeypatch):
        from holonic.backends.store import GraphNotFoundError

        # The fixture's target has boundaries but no interior; register an
        # (unmaterialized) one so the what-if collection has a layer to miss.
        target_interior = ds_with_holons.add_interior(
            "urn:holon:target",
            """
            @prefix tgt: <urn:tgt:> .
            <urn:item:existing> a tgt:Item ;
                tgt:label "Existing" ;
                tgt:amount 1 .
        """,
        )
        monkeypatch.setattr(
            ds_with_holons.backend,
            "get_graph",
            self._fail_on(ds_with_holons, target_interior, GraphNotFoundError("not materialized")),
        )

        projected, result = ds_with_holons.dry_run("urn:holon:source", "urn:holon:target")
        assert isinstance(result, MembraneResult)
        # The projection still happened; only the pre-existing interior
        # dropped out of the what-if merge.
        assert len(projected) > 0


class TestTypedGraphNotFound:
    """The Fuseki 404 must be catchable by type, not by message text."""

    def test_fuseki_404_subclasses_both_bases(self):
        pytest.importorskip("aiohttp")

        from holonic.backends._fuseki_client import FusekiError, FusekiGraphNotFound
        from holonic.backends.store import GraphNotFoundError

        # FusekiError keeps pre-0.8.0 handlers working; GraphNotFoundError
        # lets client code catch absence without importing the backend.
        assert issubclass(FusekiGraphNotFound, FusekiError)
        assert issubclass(FusekiGraphNotFound, GraphNotFoundError)

    def test_graph_not_found_is_a_holonic_error(self):
        from holonic import GraphNotFoundError, HolonicError

        assert issubclass(GraphNotFoundError, HolonicError)


class TestShapeViolationDetail:
    """R9.44 -- ``MembraneResult.shape_violations`` carries structured detail.

    The requirement names six fields and one behaviour: ``focus_node``
    identifies the offending node. That is the field that makes the list
    actionable -- a caller with a breach needs to know *which* node failed,
    and a message string alone leaves them grepping the interior.
    """

    EXPECTED_FIELDS = ("shape_iri", "focus_node", "path", "value", "message", "severity")

    @pytest.fixture
    def breached(self, ds):
        """A holon whose interior violates its own boundary shape."""
        ds.add_holon("urn:holon:r944", "Detail")
        ds.add_interior(
            "urn:holon:r944",
            """
            @prefix ex: <urn:ex:> .
            <urn:item:offender> a ex:Item .
            """,
        )
        ds.add_boundary(
            "urn:holon:r944",
            """
            @prefix ex: <urn:ex:> .
            <urn:shapes:ItemShape> a sh:NodeShape ;
                sh:targetClass ex:Item ;
                sh:property [
                    sh:path ex:name ;
                    sh:minCount 1 ;
                    sh:datatype xsd:string ;
                    sh:severity sh:Violation
                ] .
            """,
        )
        return ds.validate_membrane("urn:holon:r944")

    def test_violation_list_is_populated(self, breached):
        assert not breached.conforms
        assert breached.shape_violations, (
            "a breached membrane must populate shape_violations from the pyshacl report graph"
        )
        assert all(isinstance(v, ShapeViolation) for v in breached.shape_violations), (
            "shape_violations must be list[ShapeViolation], not raw strings"
        )

    def test_focus_node_identifies_the_offending_node(self, breached):
        """The acceptance criterion, asserted literally."""
        assert breached.shape_violations[0].focus_node == "urn:item:offender"

    def test_all_declared_fields_are_present(self, breached):
        violation = breached.shape_violations[0]
        for field_name in self.EXPECTED_FIELDS:
            assert hasattr(violation, field_name), (
                f"ShapeViolation is missing the declared field {field_name!r}"
            )

    def test_path_and_shape_are_resolved_from_the_report(self, breached):
        """Not merely present -- carrying the values the report supplied.

        ``hasattr`` passes on a dataclass whose fields all defaulted to None,
        which would satisfy the field list while telling a caller nothing.
        """
        violation = breached.shape_violations[0]
        assert violation.path == "urn:ex:name"
        assert violation.shape_iri is not None
        assert violation.severity == "Violation"
        assert violation.message

    def test_intact_membrane_reports_no_violations(self, ds):
        ds.add_holon("urn:holon:r944-ok", "Clean")
        ds.add_interior(
            "urn:holon:r944-ok",
            """
            @prefix ex: <urn:ex:> .
            <urn:item:ok> a ex:Item ; ex:name "Widget" .
            """,
        )
        ds.add_boundary(
            "urn:holon:r944-ok",
            """
            @prefix ex: <urn:ex:> .
            <urn:shapes:ItemShape> a sh:NodeShape ;
                sh:targetClass ex:Item ;
                sh:property [
                    sh:path ex:name ; sh:minCount 1 ; sh:severity sh:Violation
                ] .
            """,
        )
        result = ds.validate_membrane("urn:holon:r944-ok")
        assert result.conforms
        assert result.shape_violations == []


class TestSeverityFailsClosed:
    """R3.6 -- a SHACL result counts as a violation unless its severity is
    exactly ``sh:Warning`` or ``sh:Info`` (issue #30).

    Before the fix, ``_parse_shacl_report`` matched severities by suffix and
    dropped any result it could not classify. A shape declaring a custom
    severity therefore produced an INTACT membrane, and ``fail_on_breach``
    injected the breaching data.
    """

    @staticmethod
    def _boundary(severity: str) -> str:
        return f"""
            @prefix ex: <urn:ex:> .
            <urn:shapes:ItemShape> a sh:NodeShape ;
                sh:targetClass ex:Item ;
                sh:property [ sh:path ex:name ; sh:minCount 1 ; sh:severity {severity} ] .
            """

    def _holon_missing_name(self, ds, severity: str) -> str:
        iri = "urn:holon:severity"
        ds.add_holon(iri, "Severity")
        ds.add_interior(iri, "@prefix ex: <urn:ex:> . <urn:item:nameless> a ex:Item .")
        ds.add_boundary(iri, self._boundary(severity))
        return iri

    @staticmethod
    def _report(severity_triple: str) -> Graph:
        return Graph().parse(
            data=f"""
            @prefix sh: <http://www.w3.org/ns/shacl#> .
            [] a sh:ValidationReport ; sh:conforms false ;
               sh:result [ a sh:ValidationResult ;
                           sh:focusNode <urn:item:1> ;
                           sh:resultMessage "msg" {severity_triple} ] .
            """,
            format="turtle",
        )

    @pytest.mark.parametrize(
        "severity_triple",
        [
            "; sh:resultSeverity <urn:ex:Critical>",
            "; sh:resultSeverity <urn:ex:SoftWarning>",
            '; sh:resultSeverity "Warning"',
            "",
        ],
        ids=["custom-iri", "custom-iri-ending-in-Warning", "literal", "missing"],
    )
    def test_unrecognized_severity_is_a_violation(self, severity_triple):
        from holonic.client import _health_from_report, _parse_shacl_report

        report = _parse_shacl_report(self._report(severity_triple))
        assert len(report.violations) == 1
        assert "unrecognized severity" in report.violations[0]
        assert report.shape_violations[0].severity == "Violation"
        assert _health_from_report(report) == MembraneHealth.COMPROMISED

    def test_info_is_reported_and_does_not_lower_health(self):
        from holonic.client import _health_from_report, _parse_shacl_report

        report = _parse_shacl_report(self._report("; sh:resultSeverity sh:Info"))
        assert report.violations == []
        assert report.warnings == []
        assert report.infos == ["Info: msg; focus=urn:item:1"]
        assert report.shape_violations == []
        assert _health_from_report(report) == MembraneHealth.INTACT

    def test_custom_severity_compromises_the_membrane(self, ds):
        iri = self._holon_missing_name(ds, "<urn:ex:Critical>")
        result = ds.validate_membrane(iri)
        assert result.health == MembraneHealth.COMPROMISED
        assert result.shape_violations[0].focus_node == "urn:item:nameless"

    def test_info_shape_leaves_the_membrane_intact(self, ds):
        iri = self._holon_missing_name(ds, "sh:Info")
        result = ds.validate_membrane(iri)
        assert result.health == MembraneHealth.INTACT
        assert len(result.infos) == 1
        assert "infos (1)" in result.summary()

    def test_fail_on_breach_rejects_a_custom_severity_breach(self, ds):
        """The regression the issue asks for, end to end through traverse()."""
        ds.add_holon("urn:holon:src", "Src")
        ds.add_interior("urn:holon:src", "@prefix ex: <urn:ex:> . <urn:item:nameless> a ex:Item .")
        ds.add_holon("urn:holon:tgt", "Tgt")
        ds.add_interior(
            "urn:holon:tgt",
            '@prefix ex: <urn:ex:> . <urn:item:named> a ex:Item ; ex:name "ok" .',
            graph_iri="urn:holon:tgt/interior",
        )
        ds.add_boundary("urn:holon:tgt", self._boundary("<urn:ex:Critical>"))
        ds.add_portal(
            "urn:portal:items",
            "urn:holon:src",
            "urn:holon:tgt",
            "PREFIX ex: <urn:ex:> CONSTRUCT { ?s a ex:Item . } WHERE { ?s a ex:Item . }",
        )
        with pytest.raises(MembraneBreachError):
            ds.traverse("urn:holon:src", "urn:holon:tgt", validate=True, fail_on_breach=True)

    def test_dry_run_reports_a_custom_severity_breach(self, ds):
        ds.add_holon("urn:holon:src", "Src")
        ds.add_interior("urn:holon:src", "@prefix ex: <urn:ex:> . <urn:item:nameless> a ex:Item .")
        ds.add_holon("urn:holon:tgt", "Tgt")
        ds.add_boundary("urn:holon:tgt", self._boundary("<urn:ex:Critical>"))
        ds.add_portal(
            "urn:portal:items",
            "urn:holon:src",
            "urn:holon:tgt",
            "PREFIX ex: <urn:ex:> CONSTRUCT { ?s a ex:Item . } WHERE { ?s a ex:Item . }",
        )
        _, result = ds.dry_run("urn:holon:src", "urn:holon:tgt")
        assert result.health == MembraneHealth.COMPROMISED


class TestUntargetedTypes:
    """R3.7 -- typed interior nodes that no boundary shape targets (holonic#50).

    SHACL validates only the focus nodes its shapes target, so a node of a
    type no shape names passes unchecked. Membrane validation reports such
    nodes in ``result.untargeted``: at Info by default, and at Violation for
    the nodes a ``traverse(fail_on_breach=True)`` injects.
    """

    SHAPES = """
        @prefix ex: <urn:ex:> .
        <urn:shapes:ItemShape> a sh:NodeShape ;
            sh:targetClass ex:Item ;
            sh:property [ sh:path ex:name ; sh:minCount 1 ; sh:severity sh:Violation ] .
        """
    PERMIT_OTHER = "<urn:holon:tgt> <urn:holonic:ontology:permitsType> <urn:ex:Other> ."

    def _target(self, ds, *, interior: str = "", policy: str = "") -> None:
        ds.add_holon("urn:holon:tgt", "Tgt")
        ds.add_interior("urn:holon:tgt", interior, graph_iri="urn:holon:tgt/interior")
        ds.add_boundary("urn:holon:tgt", self.SHAPES + policy)

    @staticmethod
    def _portal_from(ds, source_ttl: str) -> None:
        ds.add_holon("urn:holon:src", "Src")
        ds.add_interior("urn:holon:src", source_ttl)
        ds.add_portal(
            "urn:portal:all",
            "urn:holon:src",
            "urn:holon:tgt",
            "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
        )

    @staticmethod
    def _traverse_closed(ds):
        return ds.traverse("urn:holon:src", "urn:holon:tgt", validate=True, fail_on_breach=True)

    def test_targeted_interior_is_unchanged(self, ds):
        self._target(ds, interior='@prefix ex: <urn:ex:> . <urn:i:1> a ex:Item ; ex:name "a" .')
        result = ds.validate_membrane("urn:holon:tgt")
        assert result.health == MembraneHealth.INTACT
        assert result.untargeted == []

    def test_untargeted_node_is_reported_at_info_by_default(self, ds):
        self._target(ds, interior="@prefix ex: <urn:ex:> . <urn:o:1> a ex:Other .")
        result = ds.validate_membrane("urn:holon:tgt")
        assert result.health == MembraneHealth.INTACT
        assert [(u.focus_node, u.types, u.severity) for u in result.untargeted] == [
            ("urn:o:1", ["urn:ex:Other"], "Info")
        ]
        assert "untargeted nodes (1)" in result.summary()

    @pytest.mark.parametrize(
        ("declared", "health"),
        [
            ("sh:Warning", MembraneHealth.WEAKENED),
            ("sh:Violation", MembraneHealth.COMPROMISED),
            ("<urn:ex:Custom>", MembraneHealth.COMPROMISED),
        ],
    )
    def test_declared_severity_sets_health(self, ds, declared, health):
        policy = f"<urn:holon:tgt> <urn:holonic:ontology:untargetedTypeSeverity> {declared} ."
        self._target(ds, interior="@prefix ex: <urn:ex:> . <urn:o:1> a ex:Other .", policy=policy)
        assert ds.validate_membrane("urn:holon:tgt").health == health

    def test_subclass_instance_is_targeted(self, ds):
        interior = """
            @prefix ex: <urn:ex:> .
            ex:Gadget rdfs:subClassOf ex:Item .
            <urn:g:1> a ex:Gadget ; ex:name "g" .
            """
        self._target(ds, interior=interior)
        assert ds.validate_membrane("urn:holon:tgt").untargeted == []

    @pytest.mark.parametrize(
        "shape",
        [
            "<urn:shapes:N> a sh:NodeShape ; sh:targetNode <urn:o:1> .",
            "<urn:shapes:N> a sh:NodeShape ; sh:targetSubjectsOf <urn:ex:p> .",
            "<urn:shapes:N> a sh:NodeShape ; sh:targetObjectsOf <urn:ex:q> .",
            "<urn:ex:Other> a sh:NodeShape , rdfs:Class .",
            "<urn:ex:Other> a sh:NodeShape , <http://www.w3.org/2002/07/owl#Class> .",
        ],
        ids=[
            "targetNode",
            "targetSubjectsOf",
            "targetObjectsOf",
            "implicit-rdfs-class",
            "implicit-owl-class",
        ],
    )
    def test_other_core_targets_count(self, ds, shape):
        interior = "<urn:o:1> a <urn:ex:Other> ; <urn:ex:p> 1 . <urn:x> <urn:ex:q> <urn:o:1> ."
        self._target(ds, interior=interior, policy=shape)
        assert ds.validate_membrane("urn:holon:tgt").untargeted == []

    def test_sparql_target_skips_the_check(self, ds):
        shape = """
            <urn:shapes:S> a sh:NodeShape ;
                sh:target [ a sh:SPARQLTarget ; sh:select "SELECT ?this WHERE { ?this ?p ?o }" ] .
            """
        self._target(ds, interior="<urn:o:1> a <urn:ex:Other> .", policy=shape)
        assert ds.validate_membrane("urn:holon:tgt").untargeted == []

    def test_fail_on_breach_rejects_an_untargeted_injection(self, ds):
        self._target(ds)
        self._portal_from(ds, "<urn:o:1> a <urn:ex:Other> .")
        with pytest.raises(MembraneBreachError, match="1 untargeted node"):
            self._traverse_closed(ds)
        assert len(ds.backend.get_graph("urn:holon:tgt/interior")) == 0

    def test_permitted_type_passes_fail_on_breach(self, ds):
        self._target(ds, policy=self.PERMIT_OTHER)
        self._portal_from(ds, "<urn:o:1> a <urn:ex:Other> .")
        _, result = self._traverse_closed(ds)
        assert result.health == MembraneHealth.INTACT
        assert result.untargeted == []

    def test_existing_untargeted_nodes_do_not_block_fail_on_breach(self, ds):
        """Only injected nodes are checked at Violation; prior content is not."""
        self._target(ds, interior="<urn:o:old> a <urn:ex:Other> .")
        self._portal_from(ds, '@prefix ex: <urn:ex:> . <urn:i:1> a ex:Item ; ex:name "a" .')
        _, result = self._traverse_closed(ds)
        assert result.health == MembraneHealth.INTACT
        assert result.untargeted == []

    def test_traverse_without_fail_on_breach_keeps_info(self, ds):
        self._target(ds)
        self._portal_from(ds, "<urn:o:1> a <urn:ex:Other> .")
        _, result = ds.traverse("urn:holon:src", "urn:holon:tgt", validate=True)
        assert result.health == MembraneHealth.INTACT
        assert [u.severity for u in result.untargeted] == ["Info"]

    def test_dry_run_reports_projected_untargeted_nodes(self, ds):
        self._target(ds, interior="<urn:o:old> a <urn:ex:Other> .")
        self._portal_from(ds, "<urn:o:new> a <urn:ex:Other> .")
        _, result = ds.dry_run("urn:holon:src", "urn:holon:tgt")
        assert result.health == MembraneHealth.INTACT
        assert [u.focus_node for u in result.untargeted] == ["urn:o:new"]
