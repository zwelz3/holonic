# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3
#     name: python3
# ---

# %% [markdown]
# # Schema.org Holarchy — A Digital Organization
#
# A complete organizational knowledge graph modeled as a holarchy
# of Schema.org entities.  Designed to produce rich, layered
# visualizations showing:
#
# - Nested holons (organization → departments → teams → people)
# - Portal traversal between departments
# - SHACL membranes governing data contracts
# - Provenance trails across the holarchy
# - Projection pipelines for cross-department reporting
#
# The holarchy represents **Athena Labs**, a fictional R&D company
# with engineering, product, research, and operations departments.

# %%
from holonic import HolonicDataset

ds = HolonicDataset()

# ══════════════════════════════════════════════════════════════
# TIER 0 — The Organization
# ══════════════════════════════════════════════════════════════

ds.add_holon("urn:holon:athena", "Athena Labs")

ds.add_interior("urn:holon:athena", """
    @prefix schema: <https://schema.org/> .

    <urn:org:athena> a schema:Organization ;
        schema:name          "Athena Labs" ;
        schema:url           "https://athena-labs.example.com" ;
        schema:foundingDate  "2019-03-15"^^xsd:date ;
        schema:description   "Applied AI and knowledge engineering R&D." ;
        schema:location      <urn:place:sf-hq> ;
        schema:numberOfEmployees 86 ;
        .

    <urn:place:sf-hq> a schema:Place ;
        schema:name       "San Francisco HQ" ;
        schema:address    "450 Mission St, San Francisco, CA 94105" ;
        schema:latitude   37.7898 ;
        schema:longitude  -122.3942 ;
        .

    <urn:place:london> a schema:Place ;
        schema:name       "London Office" ;
        schema:address    "1 Canada Square, Canary Wharf, London E14 5AB" ;
        schema:latitude   51.5049 ;
        schema:longitude  -0.0187 ;
        .

    <urn:place:tokyo> a schema:Place ;
        schema:name       "Tokyo Lab" ;
        schema:address    "Roppongi Hills Mori Tower, Minato, Tokyo 106-6108" ;
        schema:latitude   35.6604 ;
        schema:longitude  139.7292 ;
        .
""")

ds.add_boundary("urn:holon:athena", """
    @prefix schema: <https://schema.org/> .

    <urn:shapes:OrgShape> a sh:NodeShape ;
        sh:targetClass schema:Organization ;
        sh:property [
            sh:path     schema:name ;
            sh:minCount 1 ;
            sh:maxCount 1 ;
            sh:datatype xsd:string ;
            sh:severity sh:Violation
        ] ;
        sh:property [
            sh:path     schema:url ;
            sh:maxCount 1 ;
            sh:severity sh:Warning
        ] ;
        .
""")

# ══════════════════════════════════════════════════════════════
# TIER 1 — Departments
# ══════════════════════════════════════════════════════════════

for dept_iri, dept_label, dept_desc in [
    ("urn:holon:engineering",  "Engineering",  "Platform and infrastructure engineering."),
    ("urn:holon:product",      "Product",      "Product management and design."),
    ("urn:holon:research",     "Research",     "Applied AI and knowledge graph research."),
    ("urn:holon:operations",   "Operations",   "Finance, HR, and business operations."),
]:
    ds.add_holon(dept_iri, dept_label, member_of="urn:holon:athena")
    ds.add_interior(dept_iri, f"""
        @prefix schema: <https://schema.org/> .
        <{dept_iri.replace('holon:', 'dept:')}> a schema:Organization ;
            schema:name        "{dept_label}" ;
            schema:description "{dept_desc}" ;
            schema:parentOrganization <urn:org:athena> ;
            .
    """)

# ══════════════════════════════════════════════════════════════
# TIER 2 — Teams within Engineering
# ══════════════════════════════════════════════════════════════

ds.add_holon("urn:holon:eng:platform", "Platform Team",
             member_of="urn:holon:engineering")

ds.add_interior("urn:holon:eng:platform", """
    @prefix schema: <https://schema.org/> .

    <urn:person:chen-wei> a schema:Person ;
        schema:name          "Chen Wei" ;
        schema:email         "cwei@athena-labs.com" ;
        schema:jobTitle      "Staff Platform Engineer" ;
        schema:workLocation  <urn:place:sf-hq> ;
        schema:knowsAbout    "Kubernetes", "Terraform", "ArgoCD" ;
        .

    <urn:person:priya-sharma> a schema:Person ;
        schema:name          "Priya Sharma" ;
        schema:email         "psharma@athena-labs.com" ;
        schema:jobTitle      "Senior SRE" ;
        schema:workLocation  <urn:place:london> ;
        schema:knowsAbout    "Prometheus", "Grafana", "incident response" ;
        .

    <urn:person:james-okafor> a schema:Person ;
        schema:name          "James Okafor" ;
        schema:email         "jokafor@athena-labs.com" ;
        schema:jobTitle      "DevOps Engineer" ;
        schema:workLocation  <urn:place:sf-hq> ;
        schema:knowsAbout    "CI/CD", "GitHub Actions", "Docker" ;
        .

    <urn:project:infra-v3> a schema:SoftwareApplication ;
        schema:name          "Infrastructure v3 Migration" ;
        schema:description   "Migrate from EKS to self-managed k8s clusters." ;
        schema:dateCreated   "2025-09-01"^^xsd:date ;
        schema:applicationCategory "Infrastructure" ;
        .
""")

ds.add_holon("urn:holon:eng:data", "Data Engineering",
             member_of="urn:holon:engineering")

ds.add_interior("urn:holon:eng:data", """
    @prefix schema: <https://schema.org/> .

    <urn:person:maria-santos> a schema:Person ;
        schema:name          "Maria Santos" ;
        schema:email         "msantos@athena-labs.com" ;
        schema:jobTitle      "Principal Data Engineer" ;
        schema:workLocation  <urn:place:sf-hq> ;
        schema:knowsAbout    "Apache Spark", "dbt", "Iceberg" ;
        .

    <urn:person:yuki-tanaka> a schema:Person ;
        schema:name          "Yuki Tanaka" ;
        schema:email         "ytanaka@athena-labs.com" ;
        schema:jobTitle      "Data Engineer" ;
        schema:workLocation  <urn:place:tokyo> ;
        schema:knowsAbout    "Kafka", "Flink", "data quality" ;
        .

    <urn:project:lakehouse> a schema:SoftwareApplication ;
        schema:name          "Lakehouse Platform" ;
        schema:description   "Unified analytics lakehouse on Iceberg." ;
        schema:dateCreated   "2025-06-15"^^xsd:date ;
        schema:applicationCategory "Data Platform" ;
        .

    <urn:dataset:customer-360> a schema:Dataset ;
        schema:name          "Customer 360" ;
        schema:description   "Unified customer profile dataset." ;
        schema:dateModified  "2026-03-28"^^xsd:date ;
        schema:encodingFormat "parquet" ;
        schema:size          "2.4 TB" ;
        .
""")

ds.add_holon("urn:holon:eng:frontend", "Frontend Team",
             member_of="urn:holon:engineering")

ds.add_interior("urn:holon:eng:frontend", """
    @prefix schema: <https://schema.org/> .

    <urn:person:alex-kim> a schema:Person ;
        schema:name          "Alex Kim" ;
        schema:email         "akim@athena-labs.com" ;
        schema:jobTitle      "Senior Frontend Engineer" ;
        schema:workLocation  <urn:place:sf-hq> ;
        schema:knowsAbout    "React", "TypeScript", "WebGL" ;
        .

    <urn:person:nina-volkov> a schema:Person ;
        schema:name          "Nina Volkov" ;
        schema:email         "nvolkov@athena-labs.com" ;
        schema:jobTitle      "UX Engineer" ;
        schema:workLocation  <urn:place:london> ;
        schema:knowsAbout    "Design systems", "accessibility", "Figma" ;
        .

    <urn:project:atlas-ui> a schema:SoftwareApplication ;
        schema:name          "Atlas UI" ;
        schema:description   "Graph exploration and visualization interface." ;
        schema:dateCreated   "2025-11-01"^^xsd:date ;
        schema:applicationCategory "Visualization" ;
        .
""")

# ══════════════════════════════════════════════════════════════
# TIER 2 — Teams within Product
# ══════════════════════════════════════════════════════════════

ds.add_holon("urn:holon:prod:growth", "Growth",
             member_of="urn:holon:product")

ds.add_interior("urn:holon:prod:growth", """
    @prefix schema: <https://schema.org/> .

    <urn:person:sarah-chen> a schema:Person ;
        schema:name          "Sarah Chen" ;
        schema:email         "schen@athena-labs.com" ;
        schema:jobTitle      "Head of Growth" ;
        schema:workLocation  <urn:place:sf-hq> ;
        schema:knowsAbout    "PLG", "funnel optimization", "pricing" ;
        .

    <urn:person:tom-baker> a schema:Person ;
        schema:name          "Tom Baker" ;
        schema:email         "tbaker@athena-labs.com" ;
        schema:jobTitle      "Growth PM" ;
        schema:workLocation  <urn:place:london> ;
        schema:knowsAbout    "A/B testing", "analytics", "onboarding" ;
        .
""")

ds.add_holon("urn:holon:prod:design", "Design",
             member_of="urn:holon:product")

ds.add_interior("urn:holon:prod:design", """
    @prefix schema: <https://schema.org/> .

    <urn:person:emma-larsson> a schema:Person ;
        schema:name          "Emma Larsson" ;
        schema:email         "elarsson@athena-labs.com" ;
        schema:jobTitle      "Design Lead" ;
        schema:workLocation  <urn:place:sf-hq> ;
        schema:knowsAbout    "product design", "user research", "prototyping" ;
        .
""")

# ══════════════════════════════════════════════════════════════
# TIER 2 — Teams within Research
# ══════════════════════════════════════════════════════════════

ds.add_holon("urn:holon:research:kg", "Knowledge Graphs",
             member_of="urn:holon:research")

ds.add_interior("urn:holon:research:kg", """
    @prefix schema: <https://schema.org/> .

    <urn:person:zach-welz> a schema:Person ;
        schema:name          "Zach Welz" ;
        schema:email         "zwelz@athena-labs.com" ;
        schema:jobTitle      "Principal Ontologist" ;
        schema:workLocation  <urn:place:sf-hq> ;
        schema:knowsAbout    "RDF", "SHACL", "holonic systems", "OWL" ;
        .

    <urn:person:aisha-mohammed> a schema:Person ;
        schema:name          "Aisha Mohammed" ;
        schema:email         "amohammed@athena-labs.com" ;
        schema:jobTitle      "Knowledge Engineer" ;
        schema:workLocation  <urn:place:london> ;
        schema:knowsAbout    "SPARQL", "ontology alignment", "CCO" ;
        .

    <urn:project:holonic> a schema:SoftwareApplication ;
        schema:name          "holonic" ;
        schema:description   "Graph-native holonic RDF systems." ;
        schema:url           "https://github.com/zwelz3/holonic" ;
        schema:dateCreated   "2026-01-15"^^xsd:date ;
        schema:applicationCategory "Knowledge Engineering" ;
        .

    <urn:pub:hypergraph-paper> a schema:ScholarlyArticle ;
        schema:name          "RDF Named Graphs as Hypergraphs" ;
        schema:author        <urn:person:zach-welz> ;
        schema:datePublished "2026-02-20"^^xsd:date ;
        .
""")

ds.add_holon("urn:holon:research:ml", "Machine Learning",
             member_of="urn:holon:research")

ds.add_interior("urn:holon:research:ml", """
    @prefix schema: <https://schema.org/> .

    <urn:person:li-zhang> a schema:Person ;
        schema:name          "Li Zhang" ;
        schema:email         "lzhang@athena-labs.com" ;
        schema:jobTitle      "ML Research Lead" ;
        schema:workLocation  <urn:place:tokyo> ;
        schema:knowsAbout    "transformers", "graph neural networks", "RLHF" ;
        .

    <urn:person:omar-hassan> a schema:Person ;
        schema:name          "Omar Hassan" ;
        schema:email         "ohassan@athena-labs.com" ;
        schema:jobTitle      "Research Scientist" ;
        schema:workLocation  <urn:place:sf-hq> ;
        schema:knowsAbout    "NLP", "knowledge distillation", "RAG" ;
        .

    <urn:project:graphrag> a schema:SoftwareApplication ;
        schema:name          "GraphRAG Pipeline" ;
        schema:description   "Retrieval-augmented generation over knowledge graphs." ;
        schema:dateCreated   "2025-10-01"^^xsd:date ;
        schema:applicationCategory "AI/ML" ;
        .

    <urn:pub:gnn-alignment> a schema:ScholarlyArticle ;
        schema:name          "GNN-Based Ontology Alignment at Scale" ;
        schema:author        <urn:person:li-zhang> ;
        schema:datePublished "2026-01-10"^^xsd:date ;
        .
""")

ds.add_holon("urn:holon:research:acq", "Acquisition Analytics",
             member_of="urn:holon:research")

ds.add_interior("urn:holon:research:acq", """
    @prefix schema: <https://schema.org/> .

    <urn:person:rachel-green> a schema:Person ;
        schema:name          "Rachel Green" ;
        schema:email         "rgreen@athena-labs.com" ;
        schema:jobTitle      "Applied Scientist" ;
        schema:workLocation  <urn:place:sf-hq> ;
        schema:knowsAbout    "NLP", "document intelligence", "proposal analytics" ;
        .

    <urn:project:proposal-ai> a schema:SoftwareApplication ;
        schema:name          "Proposal Intelligence" ;
        schema:description   "AI-assisted proposal analysis and competitive intelligence." ;
        schema:dateCreated   "2025-08-01"^^xsd:date ;
        schema:applicationCategory "AI/ML" ;
        .
""")

# ══════════════════════════════════════════════════════════════
# TIER 2 — Operations teams
# ══════════════════════════════════════════════════════════════

ds.add_holon("urn:holon:ops:finance", "Finance",
             member_of="urn:holon:operations")

ds.add_interior("urn:holon:ops:finance", """
    @prefix schema: <https://schema.org/> .

    <urn:person:david-park> a schema:Person ;
        schema:name          "David Park" ;
        schema:email         "dpark@athena-labs.com" ;
        schema:jobTitle      "CFO" ;
        schema:workLocation  <urn:place:sf-hq> ;
        .

    <urn:budget:2026> a schema:MonetaryAmount ;
        schema:name    "2026 Operating Budget" ;
        schema:value   12500000 ;
        schema:currency "USD" ;
        .
""")

ds.add_holon("urn:holon:ops:hr", "People & Culture",
             member_of="urn:holon:operations")

ds.add_interior("urn:holon:ops:hr", """
    @prefix schema: <https://schema.org/> .

    <urn:person:lisa-nguyen> a schema:Person ;
        schema:name          "Lisa Nguyen" ;
        schema:email         "lnguyen@athena-labs.com" ;
        schema:jobTitle      "Head of People" ;
        schema:workLocation  <urn:place:sf-hq> ;
        .
""")

# ══════════════════════════════════════════════════════════════
# Events
# ══════════════════════════════════════════════════════════════

ds.add_holon("urn:holon:events", "Events & Conferences",
             member_of="urn:holon:athena")

ds.add_interior("urn:holon:events", """
    @prefix schema: <https://schema.org/> .

    <urn:event:kgc-2026> a schema:Event ;
        schema:name      "Knowledge Graph Conference 2026" ;
        schema:startDate "2026-05-04"^^xsd:date ;
        schema:endDate   "2026-05-07"^^xsd:date ;
        schema:location  <urn:place:nyc> ;
        schema:attendee  <urn:person:zach-welz> ,
                         <urn:person:aisha-mohammed> ;
        .

    <urn:event:iswc-2026> a schema:Event ;
        schema:name      "ISWC 2026" ;
        schema:startDate "2026-10-20"^^xsd:date ;
        schema:endDate   "2026-10-23"^^xsd:date ;
        schema:location  <urn:place:seoul> ;
        schema:attendee  <urn:person:li-zhang> ,
                         <urn:person:zach-welz> ;
        .

    <urn:event:all-hands-q2> a schema:Event ;
        schema:name      "Q2 All-Hands" ;
        schema:startDate "2026-04-15"^^xsd:date ;
        schema:location  <urn:place:sf-hq> ;
        schema:description "Quarterly company-wide meeting." ;
        .

    <urn:place:nyc> a schema:Place ;
        schema:name "New York, NY" ;
        .

    <urn:place:seoul> a schema:Place ;
        schema:name "Seoul, South Korea" ;
        .
""")

# ══════════════════════════════════════════════════════════════
# Boundaries on key holons
# ══════════════════════════════════════════════════════════════

PERSON_BOUNDARY = """
    @prefix schema: <https://schema.org/> .

    <urn:shapes:PersonShape> a sh:NodeShape ;
        sh:targetClass schema:Person ;
        sh:property [
            sh:path     schema:name ;
            sh:minCount 1 ;
            sh:maxCount 1 ;
            sh:datatype xsd:string ;
            sh:severity sh:Violation ;
            sh:message  "Person must have exactly one name."
        ] ;
        sh:property [
            sh:path     schema:email ;
            sh:minCount 1 ;
            sh:severity sh:Violation ;
            sh:message  "Person must have an email."
        ] ;
        sh:property [
            sh:path     schema:jobTitle ;
            sh:maxCount 1 ;
            sh:severity sh:Warning
        ] ;
        .
"""

for holon_iri in [
    "urn:holon:eng:platform", "urn:holon:eng:data", "urn:holon:eng:frontend",
    "urn:holon:research:kg", "urn:holon:research:ml", "urn:holon:research:acq",
    "urn:holon:prod:growth", "urn:holon:prod:design",
]:
    ds.add_boundary(holon_iri, PERSON_BOUNDARY)

EVENT_BOUNDARY = """
    @prefix schema: <https://schema.org/> .

    <urn:shapes:EventShape> a sh:NodeShape ;
        sh:targetClass schema:Event ;
        sh:property [
            sh:path     schema:name ;
            sh:minCount 1 ;
            sh:severity sh:Violation
        ] ;
        sh:property [
            sh:path     schema:startDate ;
            sh:minCount 1 ;
            sh:datatype xsd:date ;
            sh:severity sh:Violation
        ] ;
        .
"""

ds.add_boundary("urn:holon:events", EVENT_BOUNDARY)

# ══════════════════════════════════════════════════════════════
# Portals — cross-department views
# ══════════════════════════════════════════════════════════════

# KG team → ML team: shared person expertise for collaboration
ds.add_portal(
    "urn:portal:kg-to-ml",
    "urn:holon:research:kg",
    "urn:holon:research:ml",
    label="KG → ML Expertise",
    construct_query="""
        PREFIX schema: <https://schema.org/>
        CONSTRUCT {
            ?person a schema:Person ;
                schema:name      ?name ;
                schema:knowsAbout ?expertise ;
                .
        }
        WHERE {
            GRAPH <urn:holon:research:kg/interior> {
                ?person a schema:Person ;
                    schema:name      ?name ;
                    schema:knowsAbout ?expertise ;
                    .
            }
        }
    """,
)

# Data Eng → Frontend: dataset catalog for the UI
ds.add_portal(
    "urn:portal:data-to-frontend",
    "urn:holon:eng:data",
    "urn:holon:eng:frontend",
    label="Data → UI Catalog",
    construct_query="""
        PREFIX schema: <https://schema.org/>
        CONSTRUCT {
            ?ds a schema:Dataset ;
                schema:name          ?name ;
                schema:description   ?desc ;
                schema:encodingFormat ?fmt ;
                .
        }
        WHERE {
            GRAPH <urn:holon:eng:data/interior> {
                ?ds a schema:Dataset ;
                    schema:name          ?name ;
                    .
                OPTIONAL { ?ds schema:description   ?desc }
                OPTIONAL { ?ds schema:encodingFormat ?fmt }
            }
        }
    """,
)

# Research → Product: project summaries for roadmap planning
ds.add_portal(
    "urn:portal:research-to-product",
    "urn:holon:research",
    "urn:holon:product",
    label="Research → Product Roadmap",
    construct_query="""
        PREFIX schema: <https://schema.org/>
        CONSTRUCT {
            ?app a schema:SoftwareApplication ;
                schema:name        ?name ;
                schema:description ?desc ;
                schema:applicationCategory ?cat ;
                .
        }
        WHERE {
            GRAPH ?g {
                ?app a schema:SoftwareApplication ;
                    schema:name        ?name ;
                    .
                OPTIONAL { ?app schema:description ?desc }
                OPTIONAL { ?app schema:applicationCategory ?cat }
            }
            FILTER(STRSTARTS(STR(?g), "urn:holon:research:"))
        }
    """,
)

# Platform → Operations: infrastructure cost reporting
ds.add_portal(
    "urn:portal:platform-to-ops",
    "urn:holon:eng:platform",
    "urn:holon:operations",
    label="Platform → Ops Reporting",
    construct_query="""
        PREFIX schema: <https://schema.org/>
        CONSTRUCT {
            ?proj a schema:SoftwareApplication ;
                schema:name        ?name ;
                schema:description ?desc ;
                .
        }
        WHERE {
            GRAPH <urn:holon:eng:platform/interior> {
                ?proj a schema:SoftwareApplication ;
                    schema:name        ?name ;
                    .
                OPTIONAL { ?proj schema:description ?desc }
            }
        }
    """,
)

# ══════════════════════════════════════════════════════════════
# Traverse portals with provenance
# ══════════════════════════════════════════════════════════════

for source, target in [
    ("urn:holon:research:kg", "urn:holon:research:ml"),
    ("urn:holon:eng:data", "urn:holon:eng:frontend"),
    ("urn:holon:research", "urn:holon:product"),
    ("urn:holon:eng:platform", "urn:holon:operations"),
]:
    try:
        ds.traverse(source, target,
                    inject=True, validate=True,
                    agent_iri="urn:agent:holarchy-demo")
    except Exception as e:
        print(f"  Portal {source.rsplit(':',1)[-1]} → {target.rsplit(':',1)[-1]}: {e}")

# ══════════════════════════════════════════════════════════════
# Output
# ══════════════════════════════════════════════════════════════

print(ds.summary())
print()

tree = ds.compute_depth()
print(tree)

# ══════════════════════════════════════════════════════════════
# Visualize
# ══════════════════════════════════════════════════════════════

# %% [markdown]
# ## Holarchy Topology (collapsed)

# %%
from holonic.viz import HolarchyViz
hz = HolarchyViz(ds, layout="hierarchic")
hz.show()

# %% [markdown]
# ## Holarchy Topology (expanded — with interiors)

# %%
hz_expanded = HolarchyViz(ds, show_internals=True,
                           layers=["interior", "boundary"],
                           layout="hierarchic")
hz_expanded.show()

# %% [markdown]
# ## Single Holon: Knowledge Graphs Team

# %%
from holonic.viz import HolonViz
hv = HolonViz(ds, "urn:holon:research:kg",
              layers=["interior", "boundary"])
hv.show()

# %% [markdown]
# ## Provenance Trail

# %%
from holonic.viz import ProvenanceViz
pv = ProvenanceViz(ds)
pv.show()

# %%
pv.print_report()