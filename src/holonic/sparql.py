"""SPARQL query templates for holonic operations.

All holonic operations — holon discovery, portal lookup, path finding,
membrane inspection — are expressed as SPARQL queries.  The client
submits these to the backend; no Python data-structure iteration.
"""

# ──────────────────────────────────────────────────────────────
# Holon discovery
# ──────────────────────────────────────────────────────────────

LIST_HOLONS = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?holon ?label
WHERE {
    graph ?g {
        ?holon a cga:Holon .
        OPTIONAL { ?holon rdfs:label ?label }
    }
}
ORDER BY ?label
"""

GET_HOLON_LAYERS = """
PREFIX cga: <urn:holonic:ontology:>

SELECT ?graph ?role
WHERE {
    graph ?g {
        ?holon cga:hasLayer ?graph .
        OPTIONAL { ?graph cga:layerRole ?role }
    }
}
"""

GET_HOLON_INTERIORS = """
PREFIX cga: <urn:holonic:ontology:>

SELECT ?graph
WHERE {
    graph ?g {
        ?holon cga:hasInterior ?graph .
    }
}
"""

GET_HOLON_BOUNDARIES = """
PREFIX cga: <urn:holonic:ontology:>

SELECT ?graph
WHERE {
    graph ?g {
        ?holon cga:hasBoundary ?graph .
    }
}
"""

# ──────────────────────────────────────────────────────────────
# Portal discovery
# ──────────────────────────────────────────────────────────────

FIND_PORTALS_FROM = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?portal ?target ?label ?query
WHERE {
    graph ?g {
        ?portal a cga:TransformPortal ;
            cga:sourceHolon ?source ;
            cga:targetHolon ?target .
        OPTIONAL { ?portal rdfs:label ?label }
        OPTIONAL { ?portal cga:constructQuery ?query }
    }
}
"""

FIND_PORTALS_TO = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?portal ?source ?label ?query
WHERE {
    graph ?g {
        ?portal a cga:TransformPortal ;
            cga:sourceHolon ?source ;
            cga:targetHolon ?target .
        OPTIONAL { ?portal rdfs:label ?label }
        OPTIONAL { ?portal cga:constructQuery ?query }
    }
}
"""

FIND_PORTAL_DIRECT = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?portal ?label ?query
WHERE {
    graph ?g {
        ?portal a cga:TransformPortal ;
            cga:sourceHolon ?source ;
            cga:targetHolon ?target .
        OPTIONAL { ?portal rdfs:label ?label }
        OPTIONAL { ?portal cga:constructQuery ?query }
    }
}
LIMIT 1
"""

ALL_PORTALS = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?portal ?source ?target ?label
WHERE {
    graph ?g {
        ?portal a cga:TransformPortal ;
        cga:sourceHolon ?source ;
        cga:targetHolon ?target .
        OPTIONAL { ?portal rdfs:label ?label }
    }
}
"""

# ──────────────────────────────────────────────────────────────
# Portal traversal
# ──────────────────────────────────────────────────────────────

GET_PORTAL_QUERY = """
PREFIX cga: <urn:holonic:ontology:>

SELECT ?query
WHERE {
    graph ?g {
        ?portal cga:constructQuery ?query .
    }
}
LIMIT 1
"""

# ──────────────────────────────────────────────────────────────
# Holarchy structure
# ──────────────────────────────────────────────────────────────

HOLARCHY_TREE = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?holon ?label ?parent
WHERE {
    ?holon a cga:Holon .
    OPTIONAL { ?holon rdfs:label ?label }
    OPTIONAL { ?holon cga:memberOf ?parent }
}
ORDER BY ?label
"""

COMPUTE_DEPTH = """
PREFIX cga: <urn:holonic:ontology:>

SELECT ?holon (COUNT(?ancestor) AS ?depth)
WHERE {
    ?holon a cga:Holon .
    OPTIONAL { ?holon cga:memberOf+ ?ancestor }
}
GROUP BY ?holon
"""

# ──────────────────────────────────────────────────────────────
# Provenance recording (SPARQL UPDATE templates)
# ──────────────────────────────────────────────────────────────

RECORD_TRAVERSAL = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

INSERT DATA {{
    GRAPH <{context_graph}> {{
        <{activity_iri}> a prov:Activity ;
            rdfs:label "{label}" ;
            prov:wasAssociatedWith <{agent_iri}> ;
            prov:used <{source_iri}> ;
            prov:generated <{target_iri}> ;
            prov:startedAtTime "{timestamp}"^^xsd:dateTime .

        <{target_iri}> prov:wasDerivedFrom <{source_iri}> .
    }}
}}
"""

RECORD_VALIDATION = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

INSERT DATA {{
    GRAPH <{context_graph}> {{
        <{activity_iri}> a prov:Activity ;
            rdfs:label "Membrane validation" ;
            prov:wasAssociatedWith <{agent_iri}> ;
            prov:used <{holon_iri}> ;
            cga:membraneHealth <{health_iri}> ;
            prov:endedAtTime "{timestamp}"^^xsd:dateTime .
    }}
}}
"""

# ──────────────────────────────────────────────────────────────
# Provenance collection (SPARQL SELECT)
# ──────────────────────────────────────────────────────────────

COLLECT_TRAVERSALS = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?activity ?label ?agent ?source ?target ?timestamp
WHERE {
    GRAPH ?g {
        ?activity a prov:Activity ;
            prov:used      ?source ;
            prov:generated ?target .
        OPTIONAL { ?activity rdfs:label             ?label }
        OPTIONAL { ?activity prov:wasAssociatedWith ?agent }
        OPTIONAL { ?activity prov:startedAtTime     ?timestamp }
    }
    FILTER EXISTS {
        GRAPH ?g { ?target prov:wasDerivedFrom ?source }
    }
}
ORDER BY ?timestamp
"""

COLLECT_VALIDATIONS = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?activity ?holon ?health ?agent ?timestamp
WHERE {
    GRAPH ?g {
        ?activity a prov:Activity ;
            prov:used          ?holon ;
            cga:membraneHealth ?health .
        OPTIONAL { ?activity prov:wasAssociatedWith ?agent }
        OPTIONAL { ?activity prov:endedAtTime       ?timestamp }
    }
}
ORDER BY ?timestamp
"""

COLLECT_DERIVATION_CHAIN = """
PREFIX prov: <http://www.w3.org/ns/prov#>

SELECT ?derived ?source
WHERE {
    GRAPH ?g {
        ?derived prov:wasDerivedFrom ?source .
    }
}
"""
