"""
projections.py — Built-in SPARQL projections for holonic subgraph views.

Each projection is a named SPARQL CONSTRUCT query that extracts a
specific view of the holonic hypergraph.  These can be selected from
the SPARQLExplorer dropdown or used programmatically.
"""

PROJECTIONS: dict[str, dict] = {
    "All Triples": {
        "description": "Every triple across all layers (caution: may be large).",
        "query": """
            CONSTRUCT { ?s ?p ?o }
            WHERE { ?s ?p ?o }
        """,
    },

    "Interior Only": {
        "description": "Only the holon's self-knowledge (A-Box data).",
        "query": """
            PREFIX cga: <urn:cga:>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

            CONSTRUCT { ?s ?p ?o }
            WHERE {
                ?s ?p ?o .
                FILTER(?p != cga:interiorGraph &&
                       ?p != cga:boundaryGraph &&
                       ?p != cga:projectionGraph &&
                       ?p != cga:contextGraph)
                FILTER NOT EXISTS { ?s rdf:type <http://www.w3.org/ns/shacl#NodeShape> }
            }
        """,
    },

    "SHACL Shapes": {
        "description": "Boundary membrane: all SHACL node shapes and their properties.",
        "query": """
            PREFIX sh: <http://www.w3.org/ns/shacl#>

            CONSTRUCT {
                ?shape a sh:NodeShape .
                ?shape sh:targetClass ?cls .
                ?shape sh:property ?prop .
                ?prop sh:path ?path .
                ?prop sh:datatype ?dt .
                ?prop sh:minCount ?min .
                ?prop sh:severity ?sev .
                ?prop sh:message ?msg .
            }
            WHERE {
                ?shape a sh:NodeShape .
                OPTIONAL { ?shape sh:targetClass ?cls }
                OPTIONAL {
                    ?shape sh:property ?prop .
                    ?prop sh:path ?path .
                    OPTIONAL { ?prop sh:datatype ?dt }
                    OPTIONAL { ?prop sh:minCount ?min }
                    OPTIONAL { ?prop sh:severity ?sev }
                    OPTIONAL { ?prop sh:message ?msg }
                }
            }
        """,
    },

    "Portal Network": {
        "description": "All portals with their source and target holons.",
        "query": """
            PREFIX cga: <urn:cga:>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

            CONSTRUCT {
                ?portal a cga:Portal .
                ?portal rdfs:label ?label .
                ?portal cga:sourceHolon ?src .
                ?portal cga:targetHolon ?tgt .
                ?portal cga:isTraversable ?open .
            }
            WHERE {
                ?portal a ?ptype .
                FILTER(?ptype IN (cga:Portal, cga:TransformPortal,
                                  cga:SealedPortal, cga:BidirectionalPortal))
                OPTIONAL { ?portal rdfs:label ?label }
                OPTIONAL { ?portal cga:sourceHolon ?src }
                OPTIONAL { ?portal cga:targetHolon ?tgt }
                OPTIONAL { ?portal cga:isTraversable ?open }
            }
        """,
    },

    "Holarchy Structure": {
        "description": "Holons and their nesting relationships.",
        "query": """
            PREFIX cga: <urn:cga:>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

            CONSTRUCT {
                ?holon a cga:Holon .
                ?holon rdfs:label ?label .
                ?holon cga:holonDepth ?depth .
                ?holon cga:memberOf ?parent .
                ?holon cga:hasPortal ?portal .
            }
            WHERE {
                ?holon a cga:Holon .
                OPTIONAL { ?holon rdfs:label ?label }
                OPTIONAL { ?holon cga:holonDepth ?depth }
                OPTIONAL { ?holon cga:memberOf ?parent }
                OPTIONAL { ?holon cga:hasPortal ?portal }
            }
        """,
    },

    "Provenance Trail": {
        "description": "PROV-O activities: who did what, when, using what.",
        "query": """
            PREFIX prov: <http://www.w3.org/ns/prov#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

            CONSTRUCT {
                ?activity a prov:Activity .
                ?activity rdfs:label ?label .
                ?activity prov:startedAtTime ?time .
                ?activity prov:wasAssociatedWith ?agent .
                ?activity prov:used ?input .
                ?activity prov:generated ?output .
                ?agent a prov:Agent .
                ?agent rdfs:label ?agentLabel .
                ?output prov:wasDerivedFrom ?source .
            }
            WHERE {
                ?activity a prov:Activity .
                OPTIONAL { ?activity rdfs:label ?label }
                OPTIONAL { ?activity prov:startedAtTime ?time }
                OPTIONAL { ?activity prov:wasAssociatedWith ?agent .
                           OPTIONAL { ?agent rdfs:label ?agentLabel } }
                OPTIONAL { ?activity prov:used ?input }
                OPTIONAL { ?activity prov:generated ?output .
                           OPTIONAL { ?output prov:wasDerivedFrom ?source } }
            }
        """,
    },

    "External Bindings": {
        "description": "Projection layer: cga:bindsTo and skos:exactMatch links.",
        "query": """
            PREFIX cga:  <urn:cga:>
            PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

            CONSTRUCT {
                ?holon cga:bindsTo ?ext .
                ?holon skos:exactMatch ?match .
            }
            WHERE {
                { ?holon cga:bindsTo ?ext }
                UNION
                { ?holon skos:exactMatch ?match }
            }
        """,
    },

    "Type Hierarchy": {
        "description": "All rdf:type and rdfs:subClassOf relationships.",
        "query": """
            PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

            CONSTRUCT {
                ?s rdf:type ?class .
                ?sub rdfs:subClassOf ?super .
            }
            WHERE {
                { ?s rdf:type ?class }
                UNION
                { ?sub rdfs:subClassOf ?super }
            }
        """,
    },
}


def get_projection_names() -> list[str]:
    """Return the names of all built-in projections."""
    return list(PROJECTIONS.keys())


def get_projection(name: str) -> str:
    """Return the SPARQL query for a named projection."""
    return PROJECTIONS[name]["query"]


def get_projection_description(name: str) -> str:
    """Return the description for a named projection."""
    return PROJECTIONS[name]["description"]
