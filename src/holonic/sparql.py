"""SPARQL query templates for holonic operations.

All holonic operations -- holon discovery, portal lookup, path finding,
membrane inspection -- are expressed as SPARQL queries.  The client
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

# All four layer bindings for every holon in one query (P3: collapses the
# per-holon 4-query fan-out in iter_holons into a single scan; callers group
# ?graph by ?holon + ?pred in Python). Constant template — no store-derived
# IRIs, P1 cache-friendly.
LIST_HOLON_LAYERS = """
PREFIX cga: <urn:holonic:ontology:>

SELECT ?holon ?pred ?graph
WHERE {
    graph ?g {
        ?holon a cga:Holon .
        ?holon ?pred ?graph .
        FILTER(?pred IN (
            cga:hasInterior, cga:hasBoundary, cga:hasProjection, cga:hasContext
        ))
    }
}
"""

# Latest traversal timestamp per holon in one aggregate query (P7: replaces
# the ~5N stale_holons fan-out). Never-traversed holons still appear (via the
# OPTIONAL) with an unbound ?latest, so the caller can mark them stale.
LATEST_TRAVERSALS = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX prov: <http://www.w3.org/ns/prov#>

SELECT ?holon (MAX(?timestamp) AS ?latest)
WHERE {
    GRAPH ?hg { ?holon a cga:Holon . }
    OPTIONAL {
        GRAPH ?ag {
            ?activity a prov:Activity ;
                prov:generated ?holon ;
                prov:startedAtTime ?timestamp .
        }
    }
}
GROUP BY ?holon
"""

# Latest persisted membrane health per holon in one query (P4: replaces the
# per-holon ``validate_membrane`` fan-out inside ``holarchy_summary``). The
# inner subquery finds each holon's most-recent validation timestamp; the outer
# pattern reads the ``cga:membraneHealth`` recorded at that instant. Holons that
# have never been validated produce no row (caller leaves them out of the
# distribution). ``?health`` is a ``urn:holonic:ontology:{Intact,Weakened,
# Compromised}`` IRI mirroring ``record_validation``.
LATEST_HEALTH = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX prov: <http://www.w3.org/ns/prov#>

SELECT ?holon ?health
WHERE {
    GRAPH ?g {
        ?activity prov:used           ?holon ;
                  cga:membraneHealth  ?health ;
                  prov:endedAtTime    ?timestamp .
    }
    {
        SELECT ?holon (MAX(?t) AS ?latest)
        WHERE {
            GRAPH ?g2 {
                ?a2 prov:used          ?holon ;
                    cga:membraneHealth ?h2 ;
                    prov:endedAtTime   ?t .
            }
        }
        GROUP BY ?holon
    }
    FILTER(?timestamp = ?latest)
}
"""

# Count portals in one aggregate (P4: ``holarchy_summary`` needs the count, not
# every portal row).
COUNT_PORTALS = """
PREFIX cga: <urn:holonic:ontology:>
SELECT (COUNT(DISTINCT ?portal) AS ?n)
WHERE {
    GRAPH ?g {
        ?portal cga:sourceHolon ?source ;
                cga:targetHolon ?target .
    }
}
"""

# ──────────────────────────────────────────────────────────────
# Portal discovery
# ──────────────────────────────────────────────────────────────

FIND_PORTALS_FROM = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?portal ?target ?label ?query ?portalType
WHERE {
    graph ?g {
        ?portal cga:sourceHolon ?source ;
            cga:targetHolon ?target .
        OPTIONAL { ?portal rdfs:label ?label }
        OPTIONAL { ?portal cga:constructQuery ?query }
        OPTIONAL { ?portal a ?portalType . FILTER(?portalType != cga:Portal) }
    }
}
"""

FIND_PORTALS_TO = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?portal ?source ?label ?query ?portalType
WHERE {
    graph ?g {
        ?portal cga:sourceHolon ?source ;
            cga:targetHolon ?target .
        OPTIONAL { ?portal rdfs:label ?label }
        OPTIONAL { ?portal cga:constructQuery ?query }
        OPTIONAL { ?portal a ?portalType . FILTER(?portalType != cga:Portal) }
    }
}
"""

FIND_PORTAL_DIRECT = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?portal ?label ?query ?portalType
WHERE {
    graph ?g {
        ?portal cga:sourceHolon ?source ;
            cga:targetHolon ?target .
        OPTIONAL { ?portal rdfs:label ?label }
        OPTIONAL { ?portal cga:constructQuery ?query }
        OPTIONAL { ?portal a ?portalType . FILTER(?portalType != cga:Portal) }
    }
}
LIMIT 1
"""

ALL_PORTALS = """
PREFIX cga:  <urn:holonic:ontology:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?portal ?source ?target ?label ?portalType
WHERE {
    graph ?g {
        ?portal cga:sourceHolon ?source ;
            cga:targetHolon ?target .
        OPTIONAL { ?portal rdfs:label ?label }
        OPTIONAL { ?portal a ?portalType . FILTER(?portalType != cga:Portal) }
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

# Read the persisted incremental-traversal hash. Bound variables (``?context``,
# ``?target``) go through the ``**bindings`` chokepoint, so this is a constant
# template (P1 cache-hit) with no store-derived IRIs spliced into text (S3).
GET_PROJECTION_HASH = """
PREFIX cga: <urn:holonic:ontology:>
SELECT ?hash WHERE {
    GRAPH ?context {
        ?target cga:lastProjectionHash ?hash .
    }
}
"""

# Replace the persisted hash in one DELETE/INSERT WHERE (collapses the prior
# read + DELETE WHERE + parse_into three-op sequence, closing the read-then-act
# window on the hash triple). SPARQL UPDATE cannot pre-bind, so this is
# ``.format()``-templated; the caller validates both IRIs and ``proj_hash`` is a
# sha256 hex digest (no injection surface).
SET_PROJECTION_HASH = """
PREFIX cga: <urn:holonic:ontology:>
DELETE {{ GRAPH <{context_graph}> {{ <{target_iri}> cga:lastProjectionHash ?old . }} }}
INSERT {{ GRAPH <{context_graph}> {{ <{target_iri}> cga:lastProjectionHash "{proj_hash}" . }} }}
WHERE {{
    OPTIONAL {{ GRAPH <{context_graph}> {{ <{target_iri}> cga:lastProjectionHash ?old . }} }}
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
# Lighter than LIST_HOLONS -- returns the optional "registry" facets
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
        OPTIONAL { ?holon cga:dataClassification ?classification }
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
# scope by (source, target) pair -- correct in the common case where
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
# 0.3.3 -- GRAPH-LEVEL METADATA TEMPLATES
#
# All templates read from and write to the registry graph
# (urn:holarchy:registry by default; configurable via
# HolonicDataset(registry_iri=...)). Substitution is done
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

# NOTE: the former CLEAR_GRAPH_METADATA_TEMPLATE / CLEAR_HOLON_METADATA_TEMPLATE
# pair was retired in 0.8.0 (audit P2). MetadataRefresher now issues a single
# DELETE/INSERT/WHERE per refresh instead of a separate clear-then-insert, so
# the standalone clear templates no longer have a caller.

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
# 0.3.4 -- TYPED GRAPHS AND SCOPE RESOLUTION
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
# traversal is directional: "network" follows source->target edges
# outbound, then inbound; "reverse-network" follows only inbound;
# "containment" walks the cga:memberOf chain.

# These walk templates take the BFS frontier IRI as a **bound variable**
# (``?from_holon``), not a spliced ``<{from_holon}>`` -- the frontier is a
# store-derived neighbour IRI from the previous hop, so binding it (rather
# than re-interpolating result-row text) is what closes the second-order
# injection path (S3). As constant strings they also hit the prepared-query
# cache (P1). Callers pass ``from_holon=_bind_iri(iri)``.

WALK_OUTBOUND_PORTAL_NEIGHBORS_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>

SELECT DISTINCT ?neighbor
WHERE {
    GRAPH ?g {
        ?portal cga:sourceHolon ?from_holon ;
                cga:targetHolon ?neighbor .
    }
}
ORDER BY ?neighbor
"""

WALK_INBOUND_PORTAL_NEIGHBORS_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>

SELECT DISTINCT ?neighbor
WHERE {
    GRAPH ?g {
        ?portal cga:targetHolon ?from_holon ;
                cga:sourceHolon ?neighbor .
    }
}
ORDER BY ?neighbor
"""

WALK_MEMBER_OF_NEIGHBORS_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>

SELECT DISTINCT ?neighbor
WHERE {
    GRAPH ?g {
        { ?from_holon cga:memberOf ?neighbor }
        UNION
        { ?neighbor cga:memberOf ?from_holon }
    }
}
ORDER BY ?neighbor
"""

# ── Predicate templates ──
#
# The holon under test (``?holon``), its registry graph (``?registry``)
# and the wanted class (``?want_class``) are all bound variables, not
# spliced text: the holon IRI is store-derived at walk time, so binding it
# closes the second-order injection path (S3). Callers pass
# ``holon=_bind_iri(iri)``, ``registry=_bind_iri(...)``,
# ``want_class=_bind_iri(...)``.

ASK_HAS_CLASS_IN_INTERIOR_TEMPLATE = """
PREFIX cga: <urn:holonic:ontology:>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

ASK WHERE {
    {
        GRAPH ?registry {
            ?inv a cga:ClassInstanceCount ;
                 cga:inGraph ?g ;
                 cga:class ?want_class ;
                 cga:count ?n .
            FILTER(?n > 0)
        }
        GRAPH ?reg {
            ?holon cga:hasInterior ?g .
        }
    }
    UNION
    {
        # Fallback when the registry has not materialized class
        # inventory for this graph yet: query the interior directly.
        GRAPH ?reg {
            ?holon cga:hasInterior ?g .
        }
        GRAPH ?g {
            ?s rdf:type ?want_class .
        }
    }
}
"""

# ══════════════════════════════════════════════════════════════
# 0.3.5 -- PROJECTION PIPELINE TEMPLATES
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
