"""Shared pytest fixtures for holonic tests.

Also defines the ``integration`` marker and the ``--integration`` opt-in
flag. Integration tests talk to real external services (an Apache Jena
Fuseki server) and are therefore *deselected by default*: they run only
when ``--integration`` is passed AND the target server is reachable (the
fixtures skip themselves otherwise). This keeps the default ``pytest`` /
``pixi run test`` invocation hermetic while still giving the Fuseki
backend real end-to-end coverage on demand::

    pixi run test-integration              # boots dockerized Jena, runs them
    pytest --integration -m integration    # against an already-running server
"""

import pytest

from holonic import HolonicDataset, RdflibBackend


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--integration`` opt-in flag."""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="run integration tests that require external services (e.g. Fuseki)",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``integration`` marker so ``--strict-markers`` is happy."""
    config.addinivalue_line(
        "markers",
        "integration: test requires a live external service (deselected "
        "unless --integration is passed).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip integration-marked tests unless ``--integration`` was given."""
    if config.getoption("--integration"):
        return
    skip_integration = pytest.mark.skip(reason="need --integration option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


@pytest.fixture
def ds():
    """A fresh HolonicDataset with rdflib backend."""
    return HolonicDataset(RdflibBackend())


@pytest.fixture
def ds_with_holons(ds):
    """A dataset pre-populated with source/target holons and a portal."""
    ds.add_holon("urn:holon:source", "Source Holon")
    ds.add_interior(
        "urn:holon:source",
        """
        @prefix src: <urn:src:> .
        <urn:data:001> a src:Record ;
            src:name "Alpha" ;
            src:value 42 .
        <urn:data:002> a src:Record ;
            src:name "Beta" ;
            src:value 99 .
    """,
    )
    ds.add_boundary(
        "urn:holon:source",
        """
        @prefix src: <urn:src:> .
        <urn:shapes:RecordShape> a sh:NodeShape ;
            sh:targetClass src:Record ;
            sh:property [
                sh:path src:name ;
                sh:minCount 1 ;
                sh:datatype xsd:string ;
                sh:severity sh:Violation
            ] .
    """,
    )

    ds.add_holon("urn:holon:target", "Target Holon")
    ds.add_boundary(
        "urn:holon:target",
        """
        @prefix tgt: <urn:tgt:> .
        <urn:shapes:ItemShape> a sh:NodeShape ;
            sh:targetClass tgt:Item ;
            sh:property [
                sh:path tgt:label ;
                sh:minCount 1 ;
                sh:datatype xsd:string ;
                sh:severity sh:Violation
            ] ;
            sh:property [
                sh:path tgt:amount ;
                sh:minCount 1 ;
                sh:datatype xsd:integer ;
                sh:severity sh:Violation
            ] .
    """,
    )

    construct = """
        PREFIX src: <urn:src:>
        PREFIX tgt: <urn:tgt:>
        CONSTRUCT {
            ?s a tgt:Item ;
                tgt:label ?name ;
                tgt:amount ?val .
        }
        WHERE {
            ?s a src:Record ;
                src:name ?name ;
                src:value ?val .
        }
    """
    ds.add_portal(
        "urn:portal:src-to-tgt",
        "urn:holon:source",
        "urn:holon:target",
        construct,
        label="Source -> Target",
    )
    return ds
