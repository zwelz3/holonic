"""Realistic holarchy generators for testing, benchmarking, and visualization.

Generates holarchies with:
  - Typed holons (data, alignment, agent, governance, aggregate, index)
  - Realistic Schema.org interiors (people, orgs, projects, events, datasets)
  - SHACL boundary shapes per holon type
  - Portals with CONSTRUCT queries between related holons
  - Shared entity references across holons (people on multiple teams,
    projects spanning departments)
  - Provenance trails from portal traversals
  - Holon metadata (stewardship, classification, operational stats)

Usage::

    from holonic.generators import generate_company, generate_research_lab

    ds = generate_company(departments=4, teams_per_dept=3, people_per_team=4)
    print(ds.compute_depth())

    ds = generate_research_lab(groups=5, papers_per_group=3)
"""

from __future__ import annotations

import math
import random
import uuid
from datetime import date, timedelta
from typing import Any

from holonic import HolonicDataset


# ══════════════════════════════════════════════════════════════
# Data pools — realistic names, skills, domains, etc.
# ══════════════════════════════════════════════════════════════

FIRST_NAMES = [
    "Alice", "Bob", "Chen", "Diana", "Erik", "Fatima", "Gabriel",
    "Hana", "Ivan", "Julia", "Kai", "Lena", "Marco", "Nina",
    "Omar", "Priya", "Quinn", "Rachel", "Sven", "Tanya",
    "Uri", "Vera", "Wei", "Xena", "Yusuf", "Zara",
    "Aisha", "Brian", "Camila", "David", "Elena", "Felix",
    "Grace", "Hassan", "Ingrid", "James", "Kenji", "Luna",
    "Mateo", "Nadia", "Oscar", "Petra", "Ravi", "Sofia",
    "Tomoko", "Viktor", "Wendy", "Xiaoling", "Yuki", "Zach",
]

LAST_NAMES = [
    "Smith", "Chen", "Kumar", "Müller", "Santos", "Kim", "Okafor",
    "Larsson", "Hassan", "Tanaka", "Volkov", "Park", "Nguyen",
    "Sharma", "Zhang", "Green", "Baker", "Torres", "Petrov",
    "Morales", "Ali", "Jensen", "Ito", "Weber", "Costa",
    "Singh", "Johansson", "Martinez", "Nakamura", "Dubois",
]

DEPARTMENTS = [
    ("Engineering", "Platform engineering and infrastructure."),
    ("Product", "Product management, design, and growth."),
    ("Research", "Applied AI and knowledge graph research."),
    ("Operations", "Finance, HR, and business operations."),
    ("Sales", "Enterprise sales and customer success."),
    ("Data Science", "Analytics, ML, and data platform."),
    ("Security", "Information security and compliance."),
    ("Legal", "Contracts, IP, and regulatory compliance."),
]

TEAM_NAMES = {
    "Engineering": ["Platform", "Backend", "Frontend", "DevOps", "QA", "Mobile"],
    "Product": ["Growth", "Design", "Analytics", "Partnerships", "Documentation"],
    "Research": ["Knowledge Graphs", "Machine Learning", "NLP", "Computer Vision", "Robotics"],
    "Operations": ["Finance", "People & Culture", "Facilities", "IT Support"],
    "Sales": ["Enterprise", "Mid-Market", "Solutions Engineering", "Customer Success"],
    "Data Science": ["ML Engineering", "Analytics", "Data Platform", "Experimentation"],
    "Security": ["AppSec", "Infrastructure Security", "Compliance", "Incident Response"],
    "Legal": ["Contracts", "IP & Patents", "Regulatory", "Privacy"],
}

JOB_TITLES = {
    "Engineering": ["Staff Engineer", "Senior Engineer", "Engineer", "Principal Engineer", "Tech Lead"],
    "Product": ["Product Manager", "Senior PM", "Design Lead", "UX Researcher", "Growth PM"],
    "Research": ["Research Scientist", "Senior Researcher", "Principal Scientist", "Research Engineer", "Postdoc"],
    "Operations": ["CFO", "Controller", "HR Manager", "Recruiter", "Office Manager"],
    "Sales": ["Account Executive", "Solutions Architect", "Customer Success Manager", "Sales Engineer"],
    "Data Science": ["Data Scientist", "ML Engineer", "Analytics Engineer", "Data Analyst"],
    "Security": ["Security Engineer", "CISO", "Compliance Analyst", "Pentester"],
    "Legal": ["General Counsel", "IP Attorney", "Contract Manager", "Paralegal"],
}

SKILLS_BY_DOMAIN = {
    "Engineering": ["Kubernetes", "Terraform", "Go", "Rust", "PostgreSQL", "gRPC", "Docker", "CI/CD", "React", "TypeScript"],
    "Product": ["A/B testing", "user research", "Figma", "analytics", "roadmapping", "agile", "OKRs"],
    "Research": ["RDF", "SPARQL", "SHACL", "OWL", "transformers", "PyTorch", "GNNs", "NLP", "computer vision", "reinforcement learning"],
    "Operations": ["financial modeling", "recruiting", "compensation", "HRIS", "budgeting"],
    "Sales": ["Salesforce", "enterprise sales", "solution selling", "negotiation", "customer success"],
    "Data Science": ["Python", "SQL", "Spark", "dbt", "Airflow", "statistics", "experiment design", "feature engineering"],
    "Security": ["SAST", "DAST", "SOC 2", "FedRAMP", "incident response", "threat modeling", "zero trust"],
    "Legal": ["contract negotiation", "IP law", "GDPR", "ITAR", "export controls"],
}

PROJECT_NAMES = [
    "Atlas", "Beacon", "Compass", "Dynamo", "Eclipse", "Forge",
    "Gateway", "Horizon", "Impulse", "Jetstream", "Keystone",
    "Lighthouse", "Meridian", "Nexus", "Orbit", "Pinnacle",
    "Quantum", "Radiance", "Sentinel", "Trident", "Unity",
    "Vanguard", "Wavelength", "Xenon", "Zenith",
]

PROJECT_CATEGORIES = [
    "Infrastructure", "Data Platform", "AI/ML", "Analytics",
    "Visualization", "Security", "Integration", "Automation",
    "Customer-Facing", "Internal Tools",
]

DATASET_NAMES = [
    "Customer 360", "Product Catalog", "Transaction Ledger",
    "Clickstream Events", "Sensor Telemetry", "Employee Directory",
    "Document Corpus", "Knowledge Graph", "Embedding Store",
    "Audit Trail", "Compliance Records", "Market Data",
]

EVENT_NAMES = [
    "KGC 2026", "ISWC 2026", "NeurIPS 2026", "AAAI 2026",
    "Q1 All-Hands", "Q2 All-Hands", "Q3 All-Hands", "Q4 All-Hands",
    "Annual Offsite", "Hackathon", "Tech Talks Series",
    "Customer Summit", "Board Meeting", "Product Launch",
]

CITIES = [
    ("San Francisco", 37.7749, -122.4194),
    ("New York", 40.7128, -74.0060),
    ("London", 51.5074, -0.1278),
    ("Tokyo", 35.6762, 139.6503),
    ("Berlin", 52.5200, 13.4050),
    ("Singapore", 1.3521, 103.8198),
    ("Sydney", -33.8688, 151.2093),
    ("Toronto", 43.6532, -79.3832),
    ("Seoul", 37.5665, 126.9780),
    ("Bangalore", 12.9716, 77.5946),
]

CLASSIFICATIONS = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "CUI"]


# ══════════════════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════════════════

def _slug(s: str) -> str:
    return s.lower().replace(" ", "-").replace("&", "and").replace("/", "-")


def _iri(prefix: str, name: str) -> str:
    return f"urn:{prefix}:{_slug(name)}"


def _pick(pool: list, n: int = 1) -> list:
    return random.sample(pool, min(n, len(pool)))


def _date_near(center: date, spread_days: int = 365) -> str:
    delta = random.randint(-spread_days, spread_days)
    return (center + timedelta(days=delta)).isoformat()


def _person_ttl(
    person_iri: str,
    name: str,
    email: str,
    title: str,
    location_iri: str,
    skills: list[str],
) -> str:
    skills_str = ", ".join(f'"{s}"' for s in skills)
    return f"""
    <{person_iri}> a schema:Person ;
        schema:name          "{name}" ;
        schema:email         "{email}" ;
        schema:jobTitle      "{title}" ;
        schema:workLocation  <{location_iri}> ;
        schema:knowsAbout    {skills_str} ;
        .
"""


def _project_ttl(
    project_iri: str,
    name: str,
    description: str,
    category: str,
    created: str,
) -> str:
    return f"""
    <{project_iri}> a schema:SoftwareApplication ;
        schema:name                "{name}" ;
        schema:description         "{description}" ;
        schema:applicationCategory "{category}" ;
        schema:dateCreated         "{created}"^^xsd:date ;
        .
"""


def _dataset_ttl(
    dataset_iri: str,
    name: str,
    description: str,
    size: str,
    modified: str,
) -> str:
    return f"""
    <{dataset_iri}> a schema:Dataset ;
        schema:name           "{name}" ;
        schema:description    "{description}" ;
        schema:size           "{size}" ;
        schema:dateModified   "{modified}"^^xsd:date ;
        schema:encodingFormat "parquet" ;
        .
"""


def _event_ttl(
    event_iri: str,
    name: str,
    start: str,
    end: str,
    location_iri: str,
    attendee_iris: list[str],
) -> str:
    attendees = " ,\n                         ".join(
        f"<{a}>" for a in attendee_iris
    )
    return f"""
    <{event_iri}> a schema:Event ;
        schema:name      "{name}" ;
        schema:startDate "{start}"^^xsd:date ;
        schema:endDate   "{end}"^^xsd:date ;
        schema:location  <{location_iri}> ;
        schema:attendee  {attendees} ;
        .
"""


PERSON_BOUNDARY = """
    @prefix schema: <https://schema.org/> .

    <urn:shapes:gen:PersonShape> a sh:NodeShape ;
        sh:targetClass schema:Person ;
        sh:property [
            sh:path     schema:name ;
            sh:minCount 1 ;
            sh:maxCount 1 ;
            sh:datatype xsd:string ;
            sh:severity sh:Violation
        ] ;
        sh:property [
            sh:path     schema:email ;
            sh:minCount 1 ;
            sh:severity sh:Violation
        ] ;
        sh:property [
            sh:path     schema:jobTitle ;
            sh:maxCount 1 ;
            sh:severity sh:Info
        ] ;
        .
"""

PROJECT_BOUNDARY = """
    @prefix schema: <https://schema.org/> .

    <urn:shapes:gen:ProjectShape> a sh:NodeShape ;
        sh:targetClass schema:SoftwareApplication ;
        sh:property [
            sh:path     schema:name ;
            sh:minCount 1 ;
            sh:severity sh:Violation
        ] ;
        sh:property [
            sh:path     schema:applicationCategory ;
            sh:maxCount 1 ;
            sh:severity sh:Info
        ] ;
        .
"""

EVENT_BOUNDARY = """
    @prefix schema: <https://schema.org/> .

    <urn:shapes:gen:EventShape> a sh:NodeShape ;
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

DATASET_BOUNDARY = """
    @prefix schema: <https://schema.org/> .

    <urn:shapes:gen:DatasetShape> a sh:NodeShape ;
        sh:targetClass schema:Dataset ;
        sh:property [
            sh:path     schema:name ;
            sh:minCount 1 ;
            sh:severity sh:Violation
        ] ;
        .
"""


# ══════════════════════════════════════════════════════════════
# Generator: Company holarchy
# ══════════════════════════════════════════════════════════════

def generate_company(
    name: str = "Athena Labs",
    departments: int = 4,
    teams_per_dept: int = 3,
    people_per_team: int = 4,
    projects_per_dept: int = 2,
    datasets: int = 3,
    events: int = 4,
    cross_team_people_pct: float = 0.15,
    portals_per_dept: int = 2,
    seed: int | None = None,
) -> HolonicDataset:
    """Generate a realistic company holarchy.

    Parameters
    ----------
    name :
        Company name.
    departments :
        Number of departments (sampled from the pool).
    teams_per_dept :
        Teams per department.
    people_per_team :
        People per team.
    projects_per_dept :
        Projects per department.
    datasets :
        Number of shared datasets.
    events :
        Number of company events.
    cross_team_people_pct :
        Fraction of people who appear in multiple teams
        (shared references across holons).
    portals_per_dept :
        Inter-department portals.
    seed :
        Random seed for reproducibility.

    Returns
    -------
    HolonicDataset
        A fully populated holarchy.
    """
    if seed is not None:
        random.seed(seed)

    ds = HolonicDataset()
    company_slug = _slug(name)
    company_iri = f"urn:holon:{company_slug}"

    # ── Locations ──
    locations = _pick(CITIES, min(3, len(CITIES)))
    location_iris = {}
    location_ttl_parts = []
    for city_name, lat, lon in locations:
        loc_iri = _iri("place", city_name)
        location_iris[city_name] = loc_iri
        location_ttl_parts.append(f"""
    <{loc_iri}> a schema:Place ;
        schema:name      "{city_name}" ;
        schema:latitude  {lat} ;
        schema:longitude {lon} ;
        .
""")
    location_list = list(location_iris.values())

    # ── Root holon ──
    ds.add_holon(company_iri, name)
    ds.add_interior(company_iri, f"""
        @prefix schema: <https://schema.org/> .

        <urn:org:{company_slug}> a schema:Organization ;
            schema:name          "{name}" ;
            schema:foundingDate  "{_date_near(date(2018, 1, 1), 730)}"^^xsd:date ;
            schema:numberOfEmployees {departments * teams_per_dept * people_per_team} ;
            .
        {"".join(location_ttl_parts)}
    """)

    # ── Track all generated people for cross-referencing ──
    all_people: list[dict] = []
    dept_holons: list[str] = []
    team_holons: list[str] = []

    selected_depts = _pick(DEPARTMENTS, departments)
    available_names = list(zip(
        random.sample(FIRST_NAMES, len(FIRST_NAMES)),
        random.sample(LAST_NAMES * 2, len(FIRST_NAMES)),
    ))
    name_idx = 0

    for dept_name, dept_desc in selected_depts:
        dept_iri = f"{company_iri}:{_slug(dept_name)}"
        dept_holons.append(dept_iri)

        ds.add_holon(dept_iri, dept_name, member_of=company_iri)
        ds.add_interior(dept_iri, f"""
            @prefix schema: <https://schema.org/> .
            <urn:dept:{_slug(dept_name)}> a schema:Organization ;
                schema:name         "{dept_name}" ;
                schema:description  "{dept_desc}" ;
                schema:parentOrganization <urn:org:{company_slug}> ;
                .
        """)

        # ── Teams within department ──
        available_teams = TEAM_NAMES.get(dept_name, ["Team A", "Team B", "Team C", "Team D"])
        selected_teams = _pick(available_teams, teams_per_dept)
        dept_skills = SKILLS_BY_DOMAIN.get(dept_name, ["general"])
        dept_titles = JOB_TITLES.get(dept_name, ["Employee"])

        for team_name in selected_teams:
            team_iri = f"{dept_iri}:{_slug(team_name)}"
            team_holons.append(team_iri)

            ds.add_holon(team_iri, team_name, member_of=dept_iri)

            # Generate people
            people_ttl = ["@prefix schema: <https://schema.org/> ."]
            team_people = []
            for _ in range(people_per_team):
                if name_idx >= len(available_names):
                    name_idx = 0
                first, last = available_names[name_idx]
                name_idx += 1

                full_name = f"{first} {last}"
                person_iri = _iri("person", f"{first.lower()}-{last.lower()}")
                email = f"{first[0].lower()}{last.lower()}@{company_slug}.com"
                title = random.choice(dept_titles)
                loc = random.choice(location_list)
                skills = _pick(dept_skills, random.randint(2, 4))

                person = {
                    "iri": person_iri,
                    "name": full_name,
                    "email": email,
                    "title": title,
                    "dept": dept_name,
                    "team": team_name,
                    "team_iri": team_iri,
                    "location": loc,
                    "skills": skills,
                }
                all_people.append(person)
                team_people.append(person)

                people_ttl.append(_person_ttl(
                    person_iri, full_name, email, title, loc, skills,
                ))

            ds.add_interior(team_iri, "\n".join(people_ttl))
            ds.add_boundary(team_iri, PERSON_BOUNDARY)

        # ── Projects per department ──
        proj_names = _pick(PROJECT_NAMES, projects_per_dept)
        for proj_name in proj_names:
            proj_iri = _iri("project", proj_name)
            cat = random.choice(PROJECT_CATEGORIES)
            created = _date_near(date(2025, 6, 1), 300)
            desc = f"{proj_name} — {cat.lower()} initiative for {dept_name}."

            # Add project to a random team in this department
            target_team = random.choice(
                [t for t in team_holons if t.startswith(dept_iri)]
            )
            ds.add_interior(target_team, f"""
                @prefix schema: <https://schema.org/> .
                {_project_ttl(proj_iri, proj_name, desc, cat, created)}
            """, graph_iri=f"{target_team}/interior/projects")

    # ── Cross-team people (shared references) ──
    num_shared = max(1, int(len(all_people) * cross_team_people_pct))
    shared_people = _pick(all_people, num_shared)
    for person in shared_people:
        # Add this person to a random DIFFERENT team
        other_teams = [t for t in team_holons if t != person["team_iri"]]
        if other_teams:
            target = random.choice(other_teams)
            ds.add_interior(target, f"""
                @prefix schema: <https://schema.org/> .
                {_person_ttl(
                    person["iri"], person["name"], person["email"],
                    "Cross-Team Contributor", person["location"],
                    person["skills"][:2],
                )}
            """, graph_iri=f"{target}/interior/shared-people")

    # ── Datasets ──
    if datasets > 0:
        data_iri = f"{company_iri}:data-platform"
        ds.add_holon(data_iri, "Data Platform", member_of=company_iri)

        ds_ttl = ["@prefix schema: <https://schema.org/> ."]
        for ds_name in _pick(DATASET_NAMES, datasets):
            d_iri = _iri("dataset", ds_name)
            size = f"{random.choice([0.5, 1.2, 2.4, 5.8, 12.3, 48.0])} TB"
            modified = _date_near(date(2026, 3, 1), 60)
            desc = f"Enterprise {ds_name.lower()} dataset."
            ds_ttl.append(_dataset_ttl(d_iri, ds_name, desc, size, modified))

        ds.add_interior(data_iri, "\n".join(ds_ttl))
        ds.add_boundary(data_iri, DATASET_BOUNDARY)

    # ── Events ──
    if events > 0:
        events_iri = f"{company_iri}:events"
        ds.add_holon(events_iri, "Events", member_of=company_iri)

        ev_ttl = ["@prefix schema: <https://schema.org/> ."]
        for ev_name in _pick(EVENT_NAMES, events):
            ev_iri = _iri("event", ev_name)
            start = _date_near(date(2026, 6, 1), 180)
            end_d = date.fromisoformat(start) + timedelta(days=random.randint(1, 4))
            loc = random.choice(location_list)
            attendees = [p["iri"] for p in _pick(all_people, random.randint(2, 6))]
            ev_ttl.append(_event_ttl(
                ev_iri, ev_name, start, end_d.isoformat(), loc, attendees,
            ))

        # Add place nodes for events
        for loc_ttl in location_ttl_parts:
            ev_ttl.append(loc_ttl)

        ds.add_interior(events_iri, "\n".join(ev_ttl))
        ds.add_boundary(events_iri, EVENT_BOUNDARY)

    # ── Inter-department portals ──
    for _ in range(min(portals_per_dept * len(dept_holons), len(dept_holons) * (len(dept_holons) - 1))):
        src, tgt = random.sample(dept_holons, 2)
        src_name = src.rsplit(":", 1)[-1]
        tgt_name = tgt.rsplit(":", 1)[-1]

        # Portal: share expertise (people) across departments
        portal_iri = f"urn:portal:{src_name}-to-{tgt_name}-{uuid.uuid4().hex[:6]}"
        portal_type = random.choice(["expertise", "projects"])

        if portal_type == "expertise":
            construct = f"""
                PREFIX schema: <https://schema.org/>
                CONSTRUCT {{
                    ?person a schema:Person ;
                        schema:name       ?name ;
                        schema:knowsAbout ?skill ;
                        .
                }}
                WHERE {{
                    GRAPH ?g {{
                        ?person a schema:Person ;
                            schema:name       ?name ;
                            schema:knowsAbout ?skill ;
                            .
                    }}
                    FILTER(STRSTARTS(STR(?g), "{src}/"))
                }}
            """
            label = f"{src_name} → {tgt_name} Expertise"
        else:
            construct = f"""
                PREFIX schema: <https://schema.org/>
                CONSTRUCT {{
                    ?proj a schema:SoftwareApplication ;
                        schema:name        ?name ;
                        schema:description ?desc ;
                        .
                }}
                WHERE {{
                    GRAPH ?g {{
                        ?proj a schema:SoftwareApplication ;
                            schema:name        ?name ;
                            .
                        OPTIONAL {{ ?proj schema:description ?desc }}
                    }}
                    FILTER(STRSTARTS(STR(?g), "{src}/"))
                }}
            """
            label = f"{src_name} → {tgt_name} Projects"

        ds.add_portal(portal_iri, src, tgt, construct, label=label)

    # ── Traverse some portals to generate provenance ──
    from holonic.sparql import ALL_PORTALS
    portal_rows = ds.backend.query(ALL_PORTALS)
    traversal_count = min(len(portal_rows), max(2, len(portal_rows) // 2))
    for r in random.sample(portal_rows, traversal_count):
        try:
            ds.traverse(
                r["source"], r["target"],
                inject=True, validate=True,
                agent_iri="urn:agent:holarchy-generator",
            )
        except Exception:
            pass

    return ds


# ══════════════════════════════════════════════════════════════
# Generator: Research lab holarchy
# ══════════════════════════════════════════════════════════════

RESEARCH_DOMAINS = [
    ("Knowledge Graphs", ["RDF", "SPARQL", "SHACL", "OWL", "ontology alignment"]),
    ("Machine Learning", ["transformers", "GNNs", "PyTorch", "RLHF", "fine-tuning"]),
    ("Natural Language Processing", ["NLP", "RAG", "embeddings", "text generation"]),
    ("Computer Vision", ["object detection", "segmentation", "diffusion models"]),
    ("Robotics", ["ROS", "SLAM", "motion planning", "sim-to-real"]),
    ("Quantum Computing", ["qubits", "error correction", "variational algorithms"]),
    ("Systems Biology", ["gene networks", "protein folding", "pathway analysis"]),
    ("Climate Science", ["climate models", "remote sensing", "carbon accounting"]),
]

PAPER_TITLES = [
    "On the Expressivity of {domain} with {method}",
    "Scaling {method} for {domain} Applications",
    "A Unified Framework for {domain} and {method}",
    "{method}-Augmented {domain}: Theory and Practice",
    "Benchmarking {method} Approaches in {domain}",
    "Self-Supervised {method} for {domain}",
    "Efficient {method} in Resource-Constrained {domain}",
    "Cross-Domain Transfer via {method} in {domain}",
]

METHODS = [
    "Graph Neural Networks", "Attention Mechanisms", "Reinforcement Learning",
    "Ontology Alignment", "Federated Learning", "Knowledge Distillation",
    "Contrastive Learning", "Diffusion Models", "Prompt Engineering",
    "Holonic Systems", "Hypergraph Transformers", "Neuro-Symbolic Reasoning",
]


def generate_research_lab(
    name: str = "Semantic Systems Lab",
    groups: int = 4,
    researchers_per_group: int = 3,
    papers_per_group: int = 2,
    shared_collaborators: int = 2,
    seed: int | None = None,
) -> HolonicDataset:
    """Generate a research lab holarchy with papers, datasets, and collaborations.

    Parameters
    ----------
    name :
        Lab name.
    groups :
        Number of research groups.
    researchers_per_group :
        Researchers per group.
    papers_per_group :
        Papers per group.
    shared_collaborators :
        Researchers who appear in multiple groups.
    seed :
        Random seed.

    Returns
    -------
    HolonicDataset
    """
    if seed is not None:
        random.seed(seed)

    ds = HolonicDataset()
    lab_slug = _slug(name)
    lab_iri = f"urn:holon:{lab_slug}"

    ds.add_holon(lab_iri, name)
    ds.add_interior(lab_iri, f"""
        @prefix schema: <https://schema.org/> .
        <urn:org:{lab_slug}> a schema:Organization ;
            schema:name "{name}" ;
            schema:description "A research laboratory." ;
            .
    """)

    selected_groups = _pick(RESEARCH_DOMAINS, groups)
    all_researchers: list[dict] = []
    group_holons: list[str] = []
    name_idx = 0
    available_names = list(zip(
        random.sample(FIRST_NAMES, len(FIRST_NAMES)),
        random.sample(LAST_NAMES * 2, len(FIRST_NAMES)),
    ))

    for domain_name, domain_skills in selected_groups:
        group_iri = f"{lab_iri}:{_slug(domain_name)}"
        group_holons.append(group_iri)
        ds.add_holon(group_iri, domain_name, member_of=lab_iri)

        # Researchers
        people_ttl = ["@prefix schema: <https://schema.org/> ."]
        group_people = []
        titles = ["PhD Student", "Postdoc", "Research Scientist",
                  "Senior Researcher", "Principal Scientist"]

        for i in range(researchers_per_group):
            if name_idx >= len(available_names):
                name_idx = 0
            first, last = available_names[name_idx]
            name_idx += 1

            full_name = f"{first} {last}"
            person_iri = _iri("person", f"{first.lower()}-{last.lower()}")
            email = f"{first[0].lower()}{last.lower()}@{lab_slug}.edu"
            title = titles[min(i, len(titles) - 1)]
            skills = _pick(domain_skills, random.randint(2, min(4, len(domain_skills))))

            researcher = {
                "iri": person_iri, "name": full_name,
                "group_iri": group_iri,
            }
            all_researchers.append(researcher)
            group_people.append(researcher)

            people_ttl.append(_person_ttl(
                person_iri, full_name, email, title,
                _iri("place", random.choice(CITIES)[0]),
                skills,
            ))

        ds.add_interior(group_iri, "\n".join(people_ttl))
        ds.add_boundary(group_iri, PERSON_BOUNDARY)

        # Papers
        paper_ttl = ["@prefix schema: <https://schema.org/> ."]
        for _ in range(papers_per_group):
            template = random.choice(PAPER_TITLES)
            method = random.choice(METHODS)
            paper_title = template.format(domain=domain_name, method=method)
            paper_iri = _iri("paper", f"{uuid.uuid4().hex[:8]}")
            pub_date = _date_near(date(2026, 1, 1), 365)

            authors = " ,\n                     ".join(
                f"<{p['iri']}>" for p in _pick(group_people,
                    min(3, len(group_people)))
            )
            paper_ttl.append(f"""
    <{paper_iri}> a schema:ScholarlyArticle ;
        schema:name          "{paper_title}" ;
        schema:datePublished "{pub_date}"^^xsd:date ;
        schema:author        {authors} ;
        schema:keywords      "{domain_name}" ;
        .
""")

        ds.add_interior(group_iri, "\n".join(paper_ttl),
                       graph_iri=f"{group_iri}/interior/papers")

    # Shared collaborators
    if all_researchers and shared_collaborators > 0:
        shared = _pick(all_researchers, min(shared_collaborators, len(all_researchers)))
        for researcher in shared:
            other_groups = [g for g in group_holons if g != researcher["group_iri"]]
            if other_groups:
                target = random.choice(other_groups)
                ds.add_interior(target, f"""
                    @prefix schema: <https://schema.org/> .
                    <{researcher['iri']}> a schema:Person ;
                        schema:name     "{researcher['name']}" ;
                        schema:jobTitle "Visiting Collaborator" ;
                        .
                """, graph_iri=f"{target}/interior/collaborators")

    # Inter-group portals (collaboration channels)
    for i, src in enumerate(group_holons):
        others = [g for g in group_holons if g != src]
        targets = _pick(others, min(2, len(others)))
        for tgt in targets:
            src_name = src.rsplit(":", 1)[-1]
            tgt_name = tgt.rsplit(":", 1)[-1]
            portal_iri = f"urn:portal:{src_name}-to-{tgt_name}"

            ds.add_portal(
                portal_iri, src, tgt,
                construct_query=f"""
                    PREFIX schema: <https://schema.org/>
                    CONSTRUCT {{
                        ?paper a schema:ScholarlyArticle ;
                            schema:name          ?title ;
                            schema:datePublished ?date ;
                            schema:keywords      ?kw ;
                            .
                    }}
                    WHERE {{
                        GRAPH <{src}/interior/papers> {{
                            ?paper a schema:ScholarlyArticle ;
                                schema:name          ?title ;
                                schema:datePublished ?date ;
                                .
                            OPTIONAL {{ ?paper schema:keywords ?kw }}
                        }}
                    }}
                """,
                label=f"{src_name} → {tgt_name} Papers",
            )

    return ds


# ══════════════════════════════════════════════════════════════
# Generator: Configurable random holarchy
# ══════════════════════════════════════════════════════════════

def generate_holarchy(
    n_holons: int = 20,
    max_depth: int = 3,
    branching: int = 4,
    portal_density: float = 0.15,
    interior_density: float = 0.8,
    boundary_density: float = 0.6,
    seed: int | None = None,
) -> HolonicDataset:
    """Generate a random holarchy of arbitrary size.

    Uses Schema.org vocabulary with realistic data. Useful for
    stress testing, benchmarking, and visualization experiments.

    Parameters
    ----------
    n_holons :
        Total number of holons to generate.
    max_depth :
        Maximum nesting depth.
    branching :
        Maximum children per parent.
    portal_density :
        Fraction of possible inter-holon portals to create (0.0–1.0).
    interior_density :
        Fraction of holons that get populated interiors.
    boundary_density :
        Fraction of holons that get SHACL boundaries.
    seed :
        Random seed.

    Returns
    -------
    HolonicDataset
    """
    if seed is not None:
        random.seed(seed)

    ds = HolonicDataset()

    # Build tree structure
    holons: list[dict] = []
    root_iri = "urn:holon:root"
    ds.add_holon(root_iri, "Root")
    holons.append({"iri": root_iri, "depth": 0, "label": "Root"})

    # BFS to build tree
    queue = [root_iri]
    depth_map = {root_iri: 0}

    while len(holons) < n_holons and queue:
        parent = queue.pop(0)
        parent_depth = depth_map[parent]

        if parent_depth >= max_depth:
            continue

        n_children = random.randint(1, branching)
        for _ in range(n_children):
            if len(holons) >= n_holons:
                break

            label = f"Holon-{len(holons):03d}"
            iri = f"urn:holon:h{len(holons):03d}"
            ds.add_holon(iri, label, member_of=parent)
            holons.append({"iri": iri, "depth": parent_depth + 1, "label": label})
            depth_map[iri] = parent_depth + 1
            queue.append(iri)

    # Populate interiors
    name_pool = list(zip(
        random.sample(FIRST_NAMES * 3, len(FIRST_NAMES) * 3),
        random.sample(LAST_NAMES * 5, len(LAST_NAMES) * 5),
    ))
    name_idx = 0
    all_person_iris: list[str] = []

    for h in holons:
        if random.random() > interior_density:
            continue

        n_entities = random.randint(1, 6)
        ttl_parts = ["@prefix schema: <https://schema.org/> ."]

        for _ in range(n_entities):
            entity_type = random.choice(["person", "project", "dataset"])

            if entity_type == "person" and name_idx < len(name_pool):
                first, last = name_pool[name_idx]
                name_idx += 1
                person_iri = _iri("person", f"{first.lower()}-{last.lower()}-{uuid.uuid4().hex[:4]}")
                all_person_iris.append(person_iri)
                skills = _pick(
                    sum(SKILLS_BY_DOMAIN.values(), []),
                    random.randint(1, 3),
                )
                ttl_parts.append(_person_ttl(
                    person_iri, f"{first} {last}",
                    f"{first[0].lower()}{last.lower()}@example.com",
                    random.choice(sum(JOB_TITLES.values(), [])),
                    _iri("place", random.choice(CITIES)[0]),
                    skills,
                ))
            elif entity_type == "project":
                proj_name = random.choice(PROJECT_NAMES) + f"-{uuid.uuid4().hex[:4]}"
                ttl_parts.append(_project_ttl(
                    _iri("project", proj_name),
                    proj_name,
                    f"A {random.choice(PROJECT_CATEGORIES).lower()} project.",
                    random.choice(PROJECT_CATEGORIES),
                    _date_near(date(2025, 6, 1), 365),
                ))
            else:
                ds_name = random.choice(DATASET_NAMES)
                ttl_parts.append(_dataset_ttl(
                    _iri("dataset", f"{ds_name}-{uuid.uuid4().hex[:4]}"),
                    ds_name,
                    f"Enterprise {ds_name.lower()}.",
                    f"{random.choice([0.1, 0.5, 1.2, 5.0])} TB",
                    _date_near(date(2026, 3, 1), 90),
                ))

        ds.add_interior(h["iri"], "\n".join(ttl_parts))

    # Add boundaries
    boundary_types = [PERSON_BOUNDARY, PROJECT_BOUNDARY, DATASET_BOUNDARY]
    for h in holons:
        if random.random() > boundary_density:
            continue
        ds.add_boundary(h["iri"], random.choice(boundary_types))

    # Add portals
    n_portals = max(1, int(len(holons) * (len(holons) - 1) * portal_density / 2))
    portal_pairs: set[tuple[str, str]] = set()
    attempts = 0
    while len(portal_pairs) < n_portals and attempts < n_portals * 10:
        attempts += 1
        src, tgt = random.sample(holons, 2)
        pair = (src["iri"], tgt["iri"])
        if pair in portal_pairs:
            continue
        portal_pairs.add(pair)

        src_slug = src["iri"].rsplit(":", 1)[-1]
        tgt_slug = tgt["iri"].rsplit(":", 1)[-1]
        portal_iri = f"urn:portal:{src_slug}-to-{tgt_slug}"

        ds.add_portal(
            portal_iri, src["iri"], tgt["iri"],
            construct_query=f"""
                PREFIX schema: <https://schema.org/>
                CONSTRUCT {{
                    ?s a schema:Person ;
                        schema:name ?name ;
                        .
                }}
                WHERE {{
                    GRAPH ?g {{
                        ?s a schema:Person ;
                            schema:name ?name ;
                            .
                    }}
                    FILTER(STRSTARTS(STR(?g), "{src['iri']}/"))
                }}
            """,
            label=f"{src['label']} → {tgt['label']}",
        )

    return ds
