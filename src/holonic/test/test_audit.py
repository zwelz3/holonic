"""Tests for provenance audit trail collection and the AuditTrail model."""

import pytest

from holonic import MembraneHealth
from holonic.model import (
    AuditTrail,
    SurfaceReport,
    TraversalRecord,
    ValidationRecord,
)


# ══════════════════════════════════════════════════════════════
# AuditTrail dataclass — pure unit tests, no client
# ══════════════════════════════════════════════════════════════


class TestAuditTrailModel:
    def test_empty_audit_trail(self):
        a = AuditTrail()
        assert a.traversals == []
        assert a.validations == []
        assert a.participating_holons == set()

    def test_participating_holons_unions_sources_and_targets(self):
        a = AuditTrail(
            traversals=[
                TraversalRecord(
                    activity_iri="urn:prov:traversal:1",
                    source_iri="urn:holon:a",
                    target_iri="urn:holon:b",
                ),
                TraversalRecord(
                    activity_iri="urn:prov:traversal:2",
                    source_iri="urn:holon:b",
                    target_iri="urn:holon:c",
                ),
            ],
            validations=[
                ValidationRecord(
                    activity_iri="urn:prov:validation:1",
                    holon_iri="urn:holon:d",
                    health="intact",
                ),
            ],
        )
        assert a.participating_holons == {
            "urn:holon:a",
            "urn:holon:b",
            "urn:holon:c",
            "urn:holon:d",
        }

    def test_validation_for_returns_most_recent(self):
        a = AuditTrail(
            validations=[
                ValidationRecord(
                    activity_iri="urn:prov:validation:1",
                    holon_iri="urn:holon:x",
                    health="weakened",
                ),
                ValidationRecord(
                    activity_iri="urn:prov:validation:2",
                    holon_iri="urn:holon:x",
                    health="intact",
                ),
            ]
        )
        latest = a.validation_for("urn:holon:x")
        assert latest is not None
        assert latest.activity_iri == "urn:prov:validation:2"
        assert latest.health == "intact"

    def test_validation_for_returns_none_when_missing(self):
        a = AuditTrail()
        assert a.validation_for("urn:holon:nonexistent") is None

    def test_summary_includes_counts(self):
        a = AuditTrail(
            traversals=[
                TraversalRecord(
                    activity_iri="urn:prov:traversal:1",
                    source_iri="urn:holon:a",
                    target_iri="urn:holon:b",
                    portal_label="A→B",
                    timestamp="2026-04-05T12:00:00",
                ),
            ],
            validations=[
                ValidationRecord(
                    activity_iri="urn:prov:validation:1",
                    holon_iri="urn:holon:b",
                    health="intact",
                ),
            ],
        )
        s = a.summary()
        assert "Traversals:  1" in s
        assert "Validations: 1" in s
        assert "Holons:" in s
        assert "A→B" in s or "a → b" in s

    def test_summary_includes_surfaces(self):
        a = AuditTrail(
            surfaces={
                "urn:holon:x": SurfaceReport(
                    holon_iri="urn:holon:x",
                    target_classes=["urn:T"],
                    required_fields=["urn:p1", "urn:p2"],
                    optional_fields=["urn:p3"],
                ),
            },
        )
        s = a.summary()
        assert "Surfaces" in s
        assert "2 required" in s
        assert "1 optional" in s


class TestRecordLabels:
    def test_traversal_record_labels(self):
        t = TraversalRecord(
            activity_iri="urn:prov:traversal:1",
            source_iri="urn:holon:source",
            target_iri="urn:holon:target",
        )
        assert t.source_label == "source"
        assert t.target_label == "target"

    def test_validation_record_health_label(self):
        v = ValidationRecord(
            activity_iri="urn:prov:validation:1",
            holon_iri="urn:holon:x",
            health="urn:cga:health:intact",
        )
        assert v.health_label == "INTACT"
        assert v.holon_label == "x"

    def test_validation_record_plain_health(self):
        v = ValidationRecord(
            activity_iri="urn:prov:validation:1",
            holon_iri="urn:holon:x",
            health="weakened",
        )
        assert v.health_label == "WEAKENED"


# ══════════════════════════════════════════════════════════════
# collect_audit_trail — integration with the client
# ══════════════════════════════════════════════════════════════


class TestCollectAuditTrail:
    def test_empty_dataset_yields_empty_trail(self, ds):
        trail = ds.collect_audit_trail()
        assert isinstance(trail, AuditTrail)
        assert trail.traversals == []
        assert trail.validations == []

    def test_traverse_then_collect(self, ds_with_holons):
        ds_with_holons.traverse(
            "urn:holon:source",
            "urn:holon:target",
            validate=True,
            agent_iri="urn:agent:test",
        )
        trail = ds_with_holons.collect_audit_trail()
        assert len(trail.traversals) >= 1
        t = trail.traversals[0]
        assert t.source_iri == "urn:holon:source"
        assert t.target_iri == "urn:holon:target"
        assert t.agent_iri == "urn:agent:test"

    def test_validation_recorded_in_trail(self, ds_with_holons):
        ds_with_holons.record_validation(
            holon_iri="urn:holon:target",
            health=MembraneHealth.INTACT,
            agent_iri="urn:agent:test",
        )
        trail = ds_with_holons.collect_audit_trail()
        assert len(trail.validations) >= 1
        v = trail.validations[0]
        assert v.holon_iri == "urn:holon:target"

    def test_multiple_traversals_accumulate(self, ds_with_holons):
        for _ in range(3):
            ds_with_holons.traverse(
                "urn:holon:source",
                "urn:holon:target",
                validate=False,
                agent_iri="urn:agent:test",
            )
        trail = ds_with_holons.collect_audit_trail()
        assert len(trail.traversals) >= 3

    def test_summary_runs_on_real_trail(self, ds_with_holons):
        ds_with_holons.traverse(
            "urn:holon:source",
            "urn:holon:target",
            validate=True,
            agent_iri="urn:agent:test",
        )
        trail = ds_with_holons.collect_audit_trail()
        s = trail.summary()
        assert "Traversals" in s
        assert "Validations" in s
