"""Shared pytest fixtures for holonic tests."""

import pytest

from holonic import HolonicDataset, RdflibBackend


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
        label="Source → Target",
    )
    return ds
