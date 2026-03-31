"""
provenance.py — PROV-O provenance for holonic operations.

Every operation on a holon (portal traversal, membrane validation,
projection generation) can be recorded as a PROV-O Activity with
associated Entity and Agent triples.

The provenance graph is written into the target holon's context layer
(temporal stratum), keeping the audit trail inside the hypergraph.

PROV-O mapping
--------------
Portal traversal    →  prov:Activity (used source interior, generated projection)
Membrane validation →  prov:Activity (used interior + boundary)
Agent               →  the tool or human that triggered the operation
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from rdflib import Graph, URIRef

from .holon import Holon
from .namespaces import TTL_PREFIXES


class ProvenanceTracker:
    """
    Records PROV-O activities into holon context graphs.

    Usage::

        prov = ProvenanceTracker(agent_iri="urn:agent:translator-v1")

        # Record a portal traversal
        prov.record_traversal(
            portal_iri="urn:portal:uci-to-canonical",
            source=uci_holon,
            target=canonical_holon,
            target_context=canonical_holon,  # where to write the prov
        )

        # Record a membrane validation
        prov.record_validation(
            holon=uci_holon,
            conforms=True,
        )
    """

    def __init__(self, agent_iri: str, agent_label: str = ""):
        self.agent_iri = agent_iri
        self.agent_label = agent_label or agent_iri.split(":")[-1]

    def record_traversal(
        self,
        portal_iri: str,
        source: Holon,
        target: Holon,
        target_context: Optional[Holon] = None,
        notes: str = "",
    ) -> str:
        """
        Record a portal traversal as a PROV-O Activity.

        Returns the activity IRI.
        """
        ctx = target_context or target
        activity_id = f"urn:prov:traversal:{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        ttl = f"""
            <{activity_id}> a prov:Activity ;
                rdfs:label "Portal traversal: {source.label} → {target.label}" ;
                prov:startedAtTime "{now}"^^xsd:dateTime ;
                prov:endedAtTime   "{now}"^^xsd:dateTime ;
                prov:wasAssociatedWith <{self.agent_iri}> ;
                prov:used <{source.iri}/interior> ;
                prov:generated <{target.iri}/interior> ;
                cga:viaPortal <{portal_iri}> .

            <{self.agent_iri}> a prov:Agent ;
                rdfs:label "{self.agent_label}" .

            <{target.iri}/interior> prov:wasGeneratedBy <{activity_id}> ;
                prov:wasDerivedFrom <{source.iri}/interior> .
        """
        if notes:
            ttl += f'\n    <{activity_id}> rdfs:comment """{notes}""" .'

        ctx.load_context(ttl)
        return activity_id

    def record_validation(
        self,
        holon: Holon,
        conforms: bool,
        health: str = "",
        notes: str = "",
    ) -> str:
        """
        Record a membrane validation as a PROV-O Activity.

        Returns the activity IRI.
        """
        activity_id = f"urn:prov:validation:{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        ttl = f"""
            <{activity_id}> a prov:Activity ;
                rdfs:label "Membrane validation: {holon.label}" ;
                prov:startedAtTime "{now}"^^xsd:dateTime ;
                prov:wasAssociatedWith <{self.agent_iri}> ;
                prov:used <{holon.iri}/interior> ;
                prov:used <{holon.iri}/boundary> ;
                cga:validationConforms {str(conforms).lower()} .
        """
        if health:
            ttl += f'\n    <{activity_id}> cga:membraneHealth "{health}" .'
        if notes:
            ttl += f'\n    <{activity_id}> rdfs:comment """{notes}""" .'

        holon.load_context(ttl)
        return activity_id

    def record_projection(
        self,
        source: Holon,
        target: Holon,
        construct_query: str = "",
    ) -> str:
        """Record the generation of a projection graph."""
        activity_id = f"urn:prov:projection:{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        ttl = f"""
            <{activity_id}> a prov:Activity ;
                rdfs:label "Projection: {source.label} → {target.label}" ;
                prov:startedAtTime "{now}"^^xsd:dateTime ;
                prov:wasAssociatedWith <{self.agent_iri}> ;
                prov:used <{source.iri}/interior> .

            <{target.iri}/projection> prov:wasGeneratedBy <{activity_id}> ;
                prov:wasDerivedFrom <{source.iri}/interior> .
        """
        target.load_context(ttl)
        return activity_id
