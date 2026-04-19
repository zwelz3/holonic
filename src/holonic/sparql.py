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

GET_HOLON_PROJECTIONS = """
PREFIX cga: <urn:holonic:ontology:>

SELECT ?graph
WHERE {
    graph ?g {
        ?holon cga:hasProjection ?graph .
    }
}
"""

GET_HOLON_CONTEXTS = """
PREFIX cga: <urn:holonic:ontology:>

SELECT ?graph
WHERE {
    graph ?g {
        ?holon cga:hasContext ?graph .
    }
}
"""

# ──────────────────────────────────────────────────────────────
# Portal discovery
# ──────────────────────────────────────────────────────────────

FIND_PORTALS_FROM = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?portal ?target ?label ?query
WHERE {
    graph ?g {
        ?portal cga:sourceHolon ?source ;
            cga:targetHolon ?target .
        OPTIONAL { ?portal rdfs:label ?label }
        OPTIONAL { ?portal cga:constructQuery ?query }
    }
}
"""

FIND_PORTALS_TO = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?portal ?source ?label ?query
WHERE {
    graph ?g {
        ?portal cga:sourceHolon ?source ;
            cga:targetHolon ?target .
        OPTIONAL { ?portal rdfs:label ?label }
        OPTIONAL { ?portal cga:constructQuery ?query }
    }
}
"""

FIND_PORTAL_DIRECT = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?portal ?label ?query
WHERE {
    graph ?g {
        ?portal cga:sourceHolon ?source ;
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

SELECT DISTINCT ?portal ?source ?target ?label
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

# ──────────────────────────────────────────────────────────────
# Holon listing for browser/list views (0.3.1)
#
# Lighter than LIST_HOLONS — returns the optional "registry" facets
# (member_of, classification) in one query so callers don't N+1
# the layer-graph queries when they only need a summary.
# ──────────────────────────────────────────────────────────────

COLLECT_HOLONS = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?holon ?label ?member_of ?classification ?kind
WHERE {
    GRAPH ?g {
        ?holon a cga:Holon .
        OPTIONAL { ?holon rdfs:label        ?label }
        OPTIONAL { ?holon cga:memberOf      ?member_of }
        OPTIONAL { ?holon cga:classification ?classification }
        OPTIONAL {
            ?holon a ?kind .
            FILTER(?kind != cga:Holon)
        }
    }
}
ORDER BY ?label
"""

# ──────────────────────────────────────────────────────────────
# Interior class instance counts (0.3.1)
#
# Bind ?g via VALUES to scope the query to a holon's interior
# graph IRIs. Using VALUES rather than concatenating keeps the
# template parsable by static SPARQL validators.
# ──────────────────────────────────────────────────────────────

COUNT_INTERIOR_CLASSES_TEMPLATE = """
SELECT ?class (COUNT(DISTINCT ?subject) AS ?cnt)
WHERE {{
    VALUES ?g {{ {graph_values} }}
    GRAPH ?g {{
        ?subject a ?class .
    }}
}}
GROUP BY ?class
ORDER BY DESC(?cnt)
"""

COUNT_INTERIOR_TRIPLES_TEMPLATE = """
SELECT (COUNT(*) AS ?cnt)
WHERE {{
    VALUES ?g {{ {graph_values} }}
    GRAPH ?g {{ ?s ?p ?o }}
}}
"""

# ──────────────────────────────────────────────────────────────
# Portal traversal history scoped to one portal (0.3.1)
#
# The current RECORD_TRAVERSAL template does not write a structured
# triple linking the activity back to the portal IRI; the portal IRI
# only appears inside the rdfs:label string. Until that changes,
# scope by (source, target) pair — correct in the common case where
# at most one portal exists per ordered pair.
# ──────────────────────────────────────────────────────────────

PORTAL_TRAVERSAL_HISTORY_TEMPLATE = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?activity ?label ?agent ?timestamp
WHERE {{
    GRAPH ?g {{
        ?activity a prov:Activity ;
            prov:used      <{source_iri}> ;
            prov:generated <{target_iri}> .
        OPTIONAL {{ ?activity rdfs:label             ?label }}
        OPTIONAL {{ ?activity prov:wasAssociatedWith ?agent }}
        OPTIONAL {{ ?activity prov:startedAtTime     ?timestamp }}
    }}
}}
ORDER BY DESC(?timestamp)
LIMIT {limit}
"""

# ══════════════════════════════════════════════════════════════
# 0.3.3 — GRAPH-LEVEL METADATA TEMPLATES
#
# All templates read from and write to the registry graph
# (urn:holarchy:registry by default; configurable via
# HolonicDataset(registry_graph_iri=...)). Substitution is done
# with str.format(registry_iri=..., graph_iri=..., ...).
# See docs/DECISIONS.md § 0.3.3 for the design rationale.
# ══════════════════════════════════════════════════════════════

COUNT_GRAPH_TRIPLES_TEMPLATE = """
SELECT (COUNT(*) AS ?n)
WHERE {{
    GRAPH <{graph_iri}> {{ ?s ?p ?o }}
}}
"""

COUNT_GRAPH_TYPES_TEMPLATE = """
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?class (COUNT(?s) AS ?n)
WHERE {{
    GRAPH <{graph_iri}> {{ ?s rdf:type ?class }}
}}
GROUP BY ?class
ORDER BY DESC(?n)
"""

CLEAR_GRAPH_METADATA_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>

DELETE {{
    GRAPH <{registry_iri}> {{
        <{graph_iri}> cga:tripleCount ?count .
        <{graph_iri}> cga:lastModified ?modified .
        ?inv a cga:ClassInstanceCount ;
             cga:inGraph <{graph_iri}> ;
             cga:class ?cls ;
             cga:count ?n ;
             cga:refreshedAt ?r .
    }}
}}
WHERE {{
    GRAPH <{registry_iri}> {{
        OPTIONAL {{ <{graph_iri}> cga:tripleCount ?count }}
        OPTIONAL {{ <{graph_iri}> cga:lastModified ?modified }}
        OPTIONAL {{
            ?inv a cga:ClassInstanceCount ;
                 cga:inGraph <{graph_iri}> ;
                 cga:class ?cls ;
                 cga:count ?n .
            OPTIONAL {{ ?inv cga:refreshedAt ?r }}
        }}
    }}
}}
"""

CLEAR_HOLON_METADATA_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>

DELETE {{
    GRAPH <{registry_iri}> {{
        <{holon_iri}> cga:interiorTripleCount ?c .
        <{holon_iri}> cga:holonLastModified ?m .
    }}
}}
WHERE {{
    GRAPH <{registry_iri}> {{
        OPTIONAL {{ <{holon_iri}> cga:interiorTripleCount ?c }}
        OPTIONAL {{ <{holon_iri}> cga:holonLastModified ?m }}
    }}
}}
"""

READ_GRAPH_METADATA_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>

SELECT ?triple_count ?last_modified
WHERE {{
    GRAPH <{registry_iri}> {{
        OPTIONAL {{ <{graph_iri}> cga:tripleCount ?triple_count }}
        OPTIONAL {{ <{graph_iri}> cga:lastModified ?last_modified }}
    }}
}}
"""

READ_GRAPH_CLASS_INVENTORY_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>

SELECT ?class ?n ?refreshed_at
WHERE {{
    GRAPH <{registry_iri}> {{
        ?inv a cga:ClassInstanceCount ;
             cga:inGraph <{graph_iri}> ;
             cga:class ?class ;
             cga:count ?n .
        OPTIONAL {{ ?inv cga:refreshedAt ?refreshed_at }}
    }}
}}
ORDER BY DESC(?n)
"""

LIST_HOLON_LAYER_GRAPHS_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>

SELECT DISTINCT ?graph
WHERE {{
    GRAPH ?g {{
        <{holon_iri}> ?pred ?graph .
        FILTER(?pred IN (cga:hasInterior, cga:hasBoundary,
                          cga:hasProjection, cga:hasContext,
                          cga:hasLayer))
    }}
}}
"""

LIST_HOLON_INTERIOR_GRAPHS_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>

SELECT ?graph
WHERE {{
    GRAPH ?g {{
        <{holon_iri}> cga:hasInterior ?graph .
    }}
}}
"""

# ══════════════════════════════════════════════════════════════
# 0.3.4 — TYPED GRAPHS AND SCOPE RESOLUTION
#
# Templates write graph-category typing into the registry and walk
# the holarchy for scoped discovery. See docs/DECISIONS.md § 0.3.4.
# ══════════════════════════════════════════════════════════════

TYPE_GRAPH_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>

INSERT DATA {{
    GRAPH <{registry_iri}> {{
        <{graph_iri}> a cga:HolonicGraph ;
            cga:graphRole cga:{role} .
    }}
}}
"""

QUERY_GRAPH_TYPE_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>

SELECT DISTINCT ?role
WHERE {{
    GRAPH <{registry_iri}> {{
        <{graph_iri}> cga:graphRole ?role .
    }}
}}
"""

LIST_UNTYPED_LAYER_GRAPHS_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>

SELECT DISTINCT ?graph ?role
WHERE {{
    GRAPH ?g1 {{
        ?holon ?pred ?graph .
        FILTER(?pred IN (cga:hasInterior, cga:hasBoundary,
                          cga:hasProjection, cga:hasContext))
        BIND(
            IF(?pred = cga:hasInterior,   cga:InteriorRole,
            IF(?pred = cga:hasBoundary,   cga:BoundaryRole,
            IF(?pred = cga:hasProjection, cga:ProjectionRole,
            IF(?pred = cga:hasContext,    cga:ContextRole, ?pred))))
            AS ?role
        )
    }}
    FILTER NOT EXISTS {{
        GRAPH <{registry_iri}> {{
            ?graph cga:graphRole ?existing_role .
        }}
    }}
}}
"""

# ── Scope resolution ──
#
# The resolver issues one BFS query per hop. At each hop, it asks
# the backend for the neighbors of the current frontier. Portal
# traversal is directional: "network" follows source→target edges
# outbound, then inbound; "reverse-network" follows only inbound;
# "containment" walks the cga:memberOf chain.

WALK_OUTBOUND_PORTAL_NEIGHBORS_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>

SELECT DISTINCT ?neighbor
WHERE {{
    GRAPH ?g {{
        ?portal cga:sourceHolon <{from_holon}> ;
                cga:targetHolon ?neighbor .
    }}
}}
ORDER BY ?neighbor
"""

WALK_INBOUND_PORTAL_NEIGHBORS_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>

SELECT DISTINCT ?neighbor
WHERE {{
    GRAPH ?g {{
        ?portal cga:targetHolon <{from_holon}> ;
                cga:sourceHolon ?neighbor .
    }}
}}
ORDER BY ?neighbor
"""

WALK_MEMBER_OF_NEIGHBORS_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>

SELECT DISTINCT ?neighbor
WHERE {{
    GRAPH ?g {{
        {{ <{from_holon}> cga:memberOf ?neighbor }}
        UNION
        {{ ?neighbor cga:memberOf <{from_holon}> }}
    }}
}}
ORDER BY ?neighbor
"""

# ── Predicate templates ──
#
# Each predicate is expressed as an ASK query with <holon> as the
# subject-under-test. Callers substitute the candidate IRI at
# walk time.

ASK_HAS_CLASS_IN_INTERIOR_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

ASK WHERE {{
    {{
        GRAPH <{registry_iri}> {{
            ?inv a cga:ClassInstanceCount ;
                 cga:inGraph ?g ;
                 cga:class <{class_iri}> ;
                 cga:count ?n .
            FILTER(?n > 0)
        }}
        GRAPH ?reg {{
            <{holon_iri}> cga:hasInterior ?g .
        }}
    }}
    UNION
    {{
        # Fallback when the registry has not materialized class
        # inventory for this graph yet: query the interior directly.
        GRAPH ?reg {{
            <{holon_iri}> cga:hasInterior ?g .
        }}
        GRAPH ?g {{
            ?s rdf:type <{class_iri}> .
        }}
    }}
}}
"""

# ══════════════════════════════════════════════════════════════
# 0.3.5 — PROJECTION PIPELINE TEMPLATES
# ══════════════════════════════════════════════════════════════

LIST_PIPELINES_FOR_HOLON_TEMPLATE = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?spec ?name ?description (COUNT(?step) AS ?step_count)
WHERE {{
    GRAPH <{registry_iri}> {{
        <{holon_iri}> cga:hasPipeline ?spec .
        ?spec rdfs:label ?name .
        OPTIONAL {{ ?spec rdfs:comment ?description }}
        OPTIONAL {{
            ?spec cga:hasStep ?list .
            ?list rdf:rest*/rdf:first ?step .
        }}
    }}
}}
GROUP BY ?spec ?name ?description
ORDER BY ?name
"""

READ_PIPELINE_DETAIL_TEMPLATE = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?name ?description
WHERE {{
    GRAPH <{registry_iri}> {{
        <{spec_iri}> a cga:ProjectionPipelineSpec ;
            rdfs:label ?name .
        OPTIONAL {{ <{spec_iri}> rdfs:comment ?description }}
    }}
}}
"""

PIPELINE_STEPS_TEMPLATE = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?step ?step_name ?transform_name ?construct_query
WHERE {{
    GRAPH <{registry_iri}> {{
        <{spec_iri}> cga:hasStep ?list .
        ?list rdf:rest*/rdf:first ?step .
        OPTIONAL {{ ?step cga:stepName        ?step_name }}
        OPTIONAL {{ ?step cga:transformName   ?transform_name }}
        OPTIONAL {{ ?step cga:constructQuery  ?construct_query }}
    }}
}}
"""

# Note: the SELECT order above intentionally relies on the rdf:List
# structure for ordering. We reconstruct the canonical order in
# Python by walking the list explicitly to avoid SPARQL ORDER BY
# ambiguity.

WALK_PIPELINE_LIST_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?head
WHERE {{
    GRAPH <{registry_iri}> {{
        <{spec_iri}> cga:hasStep ?head .
    }}
}}
"""
