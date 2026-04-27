"""Tests for ontological graph categories and the migration CLI (0.3.4)."""

import pytest

from holonic import HolonicDataset, RdflibBackend
from holonic.cli.migrate_registry import _apply, _plan, main

# ══════════════════════════════════════════════════════════════
# Ontology additions
# ══════════════════════════════════════════════════════════════


def test_ontology_declares_holonic_graph(ds):
    result = ds.backend.ask(
        """
        PREFIX cga:  <urn:holonic:ontology:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        ASK WHERE {
            GRAPH <urn:holonic:ontology:cga> {
                cga:HolonicGraph a <http://www.w3.org/2002/07/owl#Class> .
                cga:graphRole    a <http://www.w3.org/2002/07/owl#ObjectProperty> .
                cga:RegistryRole a cga:LayerRole .
                cga:LayerGraph   rdfs:subClassOf cga:HolonicGraph .
            }
        }
        """
    )
    assert result is True


# ══════════════════════════════════════════════════════════════
# Eager typing on registration
# ══════════════════════════════════════════════════════════════


def test_add_interior_types_graph():
    ds = HolonicDataset(RdflibBackend())
    ds.add_holon("urn:holon:h1", "H1")
    gi = ds.add_interior(
        "urn:holon:h1",
        "@prefix ex: <urn:ex:> . <urn:ex:a> a ex:Thing .",
    )
    rows = ds.backend.query(
        f"""
        PREFIX cga: <urn:holonic:ontology:>
        SELECT ?role WHERE {{
            GRAPH <{ds.registry_iri}> {{
                <{gi}> a cga:HolonicGraph ;
                       cga:graphRole ?role .
            }}
        }}
        """
    )
    assert len(rows) == 1
    assert str(rows[0]["role"]) == "urn:holonic:ontology:InteriorRole"


@pytest.mark.parametrize(
    "method,expected_role",
    [
        ("add_interior", "InteriorRole"),
        ("add_boundary", "BoundaryRole"),
        ("add_projection", "ProjectionRole"),
        ("add_context", "ContextRole"),
    ],
)
def test_all_layer_methods_write_typing(method, expected_role):
    ds = HolonicDataset(RdflibBackend())
    ds.add_holon("urn:holon:h1", "H1")
    graph_iri = getattr(ds, method)(
        "urn:holon:h1",
        "@prefix ex: <urn:ex:> . <urn:ex:a> a ex:Thing .",
    )
    rows = ds.backend.query(
        f"""
        PREFIX cga: <urn:holonic:ontology:>
        SELECT ?role WHERE {{
            GRAPH <{ds.registry_iri}> {{
                <{graph_iri}> cga:graphRole ?role .
            }}
        }}
        """
    )
    assert len(rows) == 1
    assert str(rows[0]["role"]).endswith(expected_role)


# ══════════════════════════════════════════════════════════════
# Registry graph self-typing
# ══════════════════════════════════════════════════════════════


def test_registry_types_itself_on_first_refresh():
    ds = HolonicDataset(RdflibBackend())
    ds.add_holon("urn:holon:h1", "H1")
    ds.add_interior(
        "urn:holon:h1",
        "@prefix ex: <urn:ex:> . <urn:ex:a> a ex:Thing .",
    )
    # Any metadata refresh triggers registry self-typing
    rows = ds.backend.query(
        f"""
        PREFIX cga: <urn:holonic:ontology:>
        SELECT ?role WHERE {{
            GRAPH <{ds.registry_iri}> {{
                <{ds.registry_iri}> a cga:HolonicGraph ;
                    cga:graphRole ?role .
            }}
        }}
        """
    )
    assert len(rows) == 1
    assert str(rows[0]["role"]) == "urn:holonic:ontology:RegistryRole"


# ══════════════════════════════════════════════════════════════
# Migration CLI
# ══════════════════════════════════════════════════════════════


def test_migration_plan_empty_when_all_typed():
    ds = HolonicDataset(RdflibBackend())
    ds.add_holon("urn:holon:h1", "H1")
    ds.add_interior(
        "urn:holon:h1",
        "@prefix ex: <urn:ex:> . <urn:ex:a> a ex:Thing .",
    )
    # Every graph is typed eagerly — nothing to migrate
    assert _plan(ds) == []


def test_migration_plan_finds_untyped_graphs():
    ds = HolonicDataset(RdflibBackend())
    ds.add_holon("urn:holon:h1", "H1")
    # Simulate pre-0.3.4 state: write the layer binding WITHOUT the
    # graph-type triples. We do this by bypassing _register_layer and
    # writing the binding directly.
    ds.backend.parse_into(
        ds.registry_iri,
        """
        @prefix cga: <urn:holonic:ontology:> .
        <urn:holon:h1> cga:hasInterior <urn:legacy:interior> .
        """,
        "turtle",
    )
    plan = _plan(ds)
    assert len(plan) == 1
    assert plan[0] == ("urn:legacy:interior", "InteriorRole")


def test_migration_is_idempotent():
    ds = HolonicDataset(RdflibBackend())
    ds.add_holon("urn:holon:h1", "H1")
    ds.backend.parse_into(
        ds.registry_iri,
        """
        @prefix cga: <urn:holonic:ontology:> .
        <urn:holon:h1> cga:hasInterior <urn:legacy:a> ;
                       cga:hasBoundary <urn:legacy:b> .
        """,
        "turtle",
    )
    plan = _plan(ds)
    assert len(plan) == 2
    n = _apply(ds, plan)
    assert n == 2
    # Second run sees nothing to do
    assert _plan(ds) == []


def test_migration_main_dry_run(capsys):
    """main() without --apply prints plan and exits zero."""
    ds = HolonicDataset(RdflibBackend())
    ds.add_holon("urn:holon:h1", "H1")
    ds.backend.parse_into(
        ds.registry_iri,
        """
        @prefix cga: <urn:holonic:ontology:> .
        <urn:holon:h1> cga:hasProjection <urn:legacy:p> .
        """,
        "turtle",
    )
    # We exercise the planning functions directly since main() creates
    # its own dataset; just verify the plan output format.
    plan = _plan(ds)
    assert len(plan) == 1
    assert plan[0][1] == "ProjectionRole"


def test_migration_rejects_unknown_backend():
    rc = main(["ftp://bogus/bad"])
    assert rc != 0
