"""Tests for the projection plugin system (0.3.5)."""

import pytest
from rdflib import Graph

from holonic import (
    HolonicDataset,
    ProjectionPipelineSpec,
    ProjectionPipelineStep,
    RdflibBackend,
    TransformNotFoundError,
    get_registered_transforms,
    projection_transform,
    resolve_transform,
)
from holonic.plugins import host_metadata

# ══════════════════════════════════════════════════════════════
# Transform registration and discovery
# ══════════════════════════════════════════════════════════════


def test_first_party_transforms_registered():
    registry = get_registered_transforms()
    assert "strip_blank_nodes" in registry
    assert "localize_predicates" in registry
    assert "collapse_reification" in registry


def test_resolve_transform_returns_callable():
    fn = resolve_transform("strip_blank_nodes")
    assert callable(fn)
    g = Graph()
    g.parse(data="@prefix ex: <urn:ex:> . <urn:a> a ex:Thing .", format="turtle")
    result = fn(g)
    assert isinstance(result, Graph)


def test_resolve_transform_raises_for_unknown():
    with pytest.raises(TransformNotFoundError, match="No transform registered"):
        resolve_transform("not_a_real_transform_xyz")


def test_projection_transform_decorator_registers():
    @projection_transform("_test_decorated_transform")
    def my_transform(g: Graph) -> Graph:
        return g

    assert "_test_decorated_transform" in get_registered_transforms()
    assert resolve_transform("_test_decorated_transform") is my_transform


def test_host_metadata_has_expected_keys():
    meta = host_metadata()
    assert "host" in meta
    assert "platform" in meta
    assert "python_version" in meta
    assert "holonic_version" in meta
    # Values are strings, not None
    for v in meta.values():
        assert isinstance(v, str)


# ══════════════════════════════════════════════════════════════
# Pipeline spec registration
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def ds_with_holon():
    ds = HolonicDataset(RdflibBackend())
    ds.add_holon("urn:holon:h1", "H1")
    ds.add_interior(
        "urn:holon:h1",
        """
        @prefix ex: <urn:ex:> .
        <urn:ex:a> a ex:Thing ; ex:label "A" .
        <urn:ex:b> a ex:Thing ; ex:label "B" .
        _:hidden a ex:Hidden .
        """,
    )
    return ds


def test_register_pipeline_returns_iri(ds_with_holon):
    ds = ds_with_holon
    spec = ProjectionPipelineSpec(
        iri="urn:pipeline:test",
        name="Test",
        steps=[ProjectionPipelineStep(name="s1", transform_name="strip_blank_nodes")],
    )
    iri = ds.register_pipeline(spec)
    assert iri == "urn:pipeline:test"


def test_register_pipeline_validates_transform_names(ds_with_holon):
    ds = ds_with_holon
    bad = ProjectionPipelineSpec(
        iri="urn:pipeline:broken",
        name="Broken",
        steps=[ProjectionPipelineStep(name="s1", transform_name="not_a_transform")],
    )
    with pytest.raises(TransformNotFoundError):
        ds.register_pipeline(bad)


def test_register_pipeline_empty_steps_is_fine(ds_with_holon):
    """An empty pipeline is a valid (degenerate) pipeline."""
    ds = ds_with_holon
    spec = ProjectionPipelineSpec(iri="urn:pipeline:empty", name="Empty", steps=[])
    ds.register_pipeline(spec)
    got = ds.get_pipeline("urn:pipeline:empty")
    assert got is not None
    assert got.steps == []


def test_attach_pipeline_and_list(ds_with_holon):
    ds = ds_with_holon
    spec = ProjectionPipelineSpec(
        iri="urn:pipeline:viz",
        name="Viz Pipeline",
        description="Strip and localize",
        steps=[
            ProjectionPipelineStep(name="strip", transform_name="strip_blank_nodes"),
            ProjectionPipelineStep(name="local", transform_name="localize_predicates"),
        ],
    )
    ds.register_pipeline(spec)
    ds.attach_pipeline("urn:holon:h1", "urn:pipeline:viz")

    summaries = ds.list_pipelines("urn:holon:h1")
    assert len(summaries) == 1
    assert summaries[0].iri == "urn:pipeline:viz"
    assert summaries[0].name == "Viz Pipeline"
    assert summaries[0].step_count == 2
    assert summaries[0].description == "Strip and localize"


def test_list_pipelines_empty_for_unattached_holon(ds_with_holon):
    ds = ds_with_holon
    ds.add_holon("urn:holon:h2", "H2")
    assert ds.list_pipelines("urn:holon:h2") == []


def test_get_pipeline_none_if_missing(ds_with_holon):
    ds = ds_with_holon
    assert ds.get_pipeline("urn:pipeline:phantom") is None


def test_get_pipeline_preserves_step_order(ds_with_holon):
    ds = ds_with_holon
    spec = ProjectionPipelineSpec(
        iri="urn:pipeline:ordered",
        name="Ordered",
        steps=[
            ProjectionPipelineStep(name="first", transform_name="strip_blank_nodes"),
            ProjectionPipelineStep(name="second", transform_name="localize_predicates"),
            ProjectionPipelineStep(name="third", transform_name="collapse_reification"),
        ],
    )
    ds.register_pipeline(spec)
    got = ds.get_pipeline("urn:pipeline:ordered")
    assert [s.name for s in got.steps] == ["first", "second", "third"]


# ══════════════════════════════════════════════════════════════
# Pipeline execution
# ══════════════════════════════════════════════════════════════


def test_run_projection_applies_transforms(ds_with_holon):
    """Running strip_blank_nodes should remove blank-node triples."""
    ds = ds_with_holon
    before_rows = ds.backend.query(
        """
        PREFIX ex: <urn:ex:>
        SELECT ?s WHERE { GRAPH ?g { ?s a ex:Hidden } }
        """
    )
    # There IS a _:hidden triple in the fixture
    assert len(before_rows) == 1

    ds.register_pipeline(
        ProjectionPipelineSpec(
            iri="urn:pipeline:strip",
            name="Strip",
            steps=[ProjectionPipelineStep(name="s", transform_name="strip_blank_nodes")],
        )
    )
    ds.attach_pipeline("urn:holon:h1", "urn:pipeline:strip")

    result = ds.run_projection(
        "urn:holon:h1", "urn:pipeline:strip", store_as="urn:holon:h1/projection/viz"
    )
    # Result should contain the two ex:Thing subjects but not the blank
    subjects = {str(s) for s in result.subjects()}
    assert "urn:ex:a" in subjects
    assert "urn:ex:b" in subjects
    assert not any(s.startswith("_:") or "bnode" in s.lower() for s in subjects)


def test_run_projection_records_provenance(ds_with_holon):
    ds = ds_with_holon
    ds.register_pipeline(
        ProjectionPipelineSpec(
            iri="urn:pipeline:prov",
            name="Prov",
            steps=[ProjectionPipelineStep(name="s", transform_name="strip_blank_nodes")],
        )
    )
    ds.attach_pipeline("urn:holon:h1", "urn:pipeline:prov")
    ds.run_projection(
        "urn:holon:h1",
        "urn:pipeline:prov",
        store_as="urn:holon:h1/projection/viz",
        agent_iri="urn:agent:tester",
    )

    rows = ds.backend.query(
        """
        PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX cga:  <urn:holonic:ontology:>
        SELECT ?a ?spec ?agent ?host ?platform ?pyver ?hver
        WHERE {
            GRAPH ?g {
                ?a a prov:Activity ;
                   prov:used ?spec ;
                   prov:wasAssociatedWith ?agent ;
                   cga:runHost ?host ;
                   cga:runPlatform ?platform ;
                   cga:runPythonVersion ?pyver ;
                   cga:runHolonicVersion ?hver .
            }
        }
        """
    )
    assert len(rows) == 1
    assert str(rows[0]["spec"]) == "urn:pipeline:prov"
    assert str(rows[0]["agent"]) == "urn:agent:tester"
    # Host metadata values are non-empty strings
    for key in ("host", "platform", "pyver", "hver"):
        assert str(rows[0][key])


def test_run_projection_raises_for_missing_spec(ds_with_holon):
    ds = ds_with_holon
    with pytest.raises(ValueError, match="No pipeline registered"):
        ds.run_projection("urn:holon:h1", "urn:pipeline:phantom")


def test_run_projection_triggers_metadata_refresh(ds_with_holon):
    """store_as with eager mode should refresh metadata on the output graph."""
    ds = ds_with_holon
    ds.register_pipeline(
        ProjectionPipelineSpec(
            iri="urn:pipeline:m",
            name="M",
            steps=[ProjectionPipelineStep(name="s", transform_name="strip_blank_nodes")],
        )
    )
    ds.attach_pipeline("urn:holon:h1", "urn:pipeline:m")
    ds.run_projection("urn:holon:h1", "urn:pipeline:m", store_as="urn:holon:h1/projection/out")
    md = ds.get_graph_metadata("urn:holon:h1/projection/out")
    assert md is not None
    assert md.triple_count > 0


def test_run_projection_no_store_as_returns_graph(ds_with_holon):
    """Without store_as, the result graph comes back without being persisted."""
    ds = ds_with_holon
    ds.register_pipeline(
        ProjectionPipelineSpec(
            iri="urn:pipeline:ephemeral",
            name="Ephemeral",
            steps=[ProjectionPipelineStep(name="s", transform_name="strip_blank_nodes")],
        )
    )
    ds.attach_pipeline("urn:holon:h1", "urn:pipeline:ephemeral")
    result = ds.run_projection("urn:holon:h1", "urn:pipeline:ephemeral")
    assert isinstance(result, Graph)
    # Output graph should not be registered as a projection
    detail = ds.get_holon_detail("urn:holon:h1")
    assert not any("ephemeral" in g for g in detail.projection_graphs)


# ══════════════════════════════════════════════════════════════
# CONSTRUCT-only steps
# ══════════════════════════════════════════════════════════════


def test_pipeline_with_construct_query(ds_with_holon):
    """A step with only a CONSTRUCT (no transform_name) still runs."""
    ds = ds_with_holon
    spec = ProjectionPipelineSpec(
        iri="urn:pipeline:construct",
        name="Construct-only",
        steps=[
            ProjectionPipelineStep(
                name="things-only",
                construct_query="""
                    PREFIX ex: <urn:ex:>
                    CONSTRUCT { ?s ?p ?o }
                    WHERE { ?s a ex:Thing . ?s ?p ?o }
                """,
            )
        ],
    )
    ds.register_pipeline(spec)
    ds.attach_pipeline("urn:holon:h1", "urn:pipeline:construct")
    result = ds.run_projection("urn:holon:h1", "urn:pipeline:construct")
    # Result should contain only triples where subjects are ex:Thing
    subjects = {str(s) for s in result.subjects()}
    assert subjects == {"urn:ex:a", "urn:ex:b"}


# ══════════════════════════════════════════════════════════════
# Turtle escape hatch
# ══════════════════════════════════════════════════════════════


def test_register_pipeline_ttl_accepts_raw_turtle(ds_with_holon):
    """The ttl path allows callers to write pipelines directly."""
    ds = ds_with_holon
    ttl = """
        @prefix cga:  <urn:holonic:ontology:> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

        <urn:pipeline:raw> a cga:ProjectionPipelineSpec ;
            rdfs:label "Raw TTL Pipeline" ;
            cga:hasStep ( <urn:pipeline:raw/step/0> ) .

        <urn:pipeline:raw/step/0> a cga:ProjectionPipelineStep ;
            cga:stepName "raw step" ;
            cga:transformName "strip_blank_nodes" .
    """
    ds.register_pipeline_ttl(ttl)
    spec = ds.get_pipeline("urn:pipeline:raw")
    assert spec is not None
    assert spec.name == "Raw TTL Pipeline"
    assert len(spec.steps) == 1
    assert spec.steps[0].transform_name == "strip_blank_nodes"


# ══════════════════════════════════════════════════════════════
# Multi-pipeline: one holon, several attached
# ══════════════════════════════════════════════════════════════


def test_multiple_pipelines_per_holon(ds_with_holon):
    ds = ds_with_holon
    for n in ("p1", "p2", "p3"):
        ds.register_pipeline(
            ProjectionPipelineSpec(
                iri=f"urn:pipeline:{n}",
                name=n.upper(),
                steps=[ProjectionPipelineStep(name="s", transform_name="strip_blank_nodes")],
            )
        )
        ds.attach_pipeline("urn:holon:h1", f"urn:pipeline:{n}")
    summaries = ds.list_pipelines("urn:holon:h1")
    assert len(summaries) == 3
    assert {s.name for s in summaries} == {"P1", "P2", "P3"}
