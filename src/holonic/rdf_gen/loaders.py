"""loaders.py — Mock adapters that translate source formats to RDF.

In a production system, these would be real adapters reading SysML v2 API,
DOORS ReqIF exports, AFSIM HDF5 outputs, etc.  Here they produce
TTL strings representing what those adapters would emit.

Each loader returns a TTL string ready for ``engine.load_data()``.

The value proposition: once data is in RDF, it participates in SPARQL
queries, SHACL validation, and template rendering — regardless of its
original format.  Adding a new source means writing one adapter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _slug(s: str) -> str:
    return s.lower().replace(" ", "-").replace("/", "-").replace("_", "-")


def sysml_to_ttl(
    blocks: list[dict],
    package: str = "urn:sysml:pkg:default",
) -> str:
    """Mock SysML v2 → RDF adapter.

    Accepts a list of block definitions with parameters and produces
    TTL in the ``eng:`` namespace.

    Expected dict format::

        {
            "name": "ThermalMgmtSubsystem",
            "stereotype": "Block",
            "parameters": [
                {"name": "mass", "value": 142.3, "unit": "kg"},
                {"name": "maxPower", "value": 2.8, "unit": "kW"},
            ],
            "ports": [
                {"name": "coolantInlet", "direction": "in", "type": "FlowPort"},
            ],
        }
    """
    lines = [
        "@prefix eng: <urn:eng:> .",
        "@prefix sysml: <urn:sysml:> .",
        "",
        "# SysML v2 model data (translated from SysML API)",
        f"# Source package: {package}",
        f"# Loaded at: {datetime.now(UTC).isoformat()}",
        "",
        f"<{package}> a eng:Package ;",
        f'    rdfs:label "{package.split(":")[-1]}" .',
        "",
    ]

    for block in blocks:
        bname = block["name"]
        buri = f"urn:eng:block:{_slug(bname)}"
        stereo = block.get("stereotype", "Block")

        lines.append(f"<{buri}> a eng:{stereo} ;")
        lines.append(f'    rdfs:label "{bname}" ;')
        lines.append(f"    eng:owner <{package}> .")
        lines.append("")

        for param in block.get("parameters", []):
            pname = param["name"]
            puri = f"urn:eng:param:{_slug(bname)}:{_slug(pname)}"
            pval = param["value"]
            punit = param.get("unit", "")

            lines.append(f"<{puri}> a eng:Parameter ;")
            lines.append(f'    rdfs:label "{pname}" ;')
            lines.append(f"    eng:paramValue {pval} ;")
            if punit:
                lines.append(f'    eng:paramUnit "{punit}" ;')
            lines.append(f"    eng:belongsTo <{buri}> .")
            lines.append("")

        for port in block.get("ports", []):
            port_name = port["name"]
            port_uri = f"urn:eng:port:{_slug(bname)}:{_slug(port_name)}"
            port_type = port.get("type", "Port")
            direction = port.get("direction", "inout")

            lines.append(f"<{port_uri}> a eng:{port_type} ;")
            lines.append(f'    rdfs:label "{port_name}" ;')
            lines.append(f'    eng:direction "{direction}" ;')
            lines.append(f"    eng:belongsTo <{buri}> .")
            lines.append("")

    return "\n".join(lines)


def _escape(s: str) -> str:
    return s.replace('"', '\\"').replace("\n", " ")


def requirements_to_ttl(
    requirements: list[dict],
    document: str = "urn:eng:doc:system-spec",
) -> str:
    """Mock DOORS/Jama → RDF adapter.

    Expected dict format::

        {
            "id": "REQ-MASS-001",
            "title": "Subsystem Mass Limit",
            "text": "The subsystem shall have mass not exceeding 150 kg.",
            "priority": "SHALL",
            "category": "Performance",
            "allocated_to": "urn:eng:block:thermal-mgmt-subsystem",
        }
    """
    lines = [
        "@prefix eng: <urn:eng:> .",
        "@prefix dt:  <urn:dt:> .",
        "",
        "# Requirements (translated from requirements management tool)",
        f"# Document: {document}",
        "",
        f"<{document}> a eng:RequirementsDocument ;",
        f'    rdfs:label "{document.split(":")[-1]}" .',
        "",
    ]

    for req in requirements:
        rid = req["id"]
        ruri = f"urn:eng:req:{rid}"
        title = req.get("title", rid)
        text = req.get("text", "")
        priority = req.get("priority", "SHALL")
        category = req.get("category", "")
        alloc = req.get("allocated_to")

        lines.append(f"<{ruri}> a eng:Requirement ;")
        lines.append(f'    rdfs:label "{title}" ;')
        lines.append(f'    eng:reqId "{rid}" ;')
        lines.append(f'    eng:reqText "{_escape(text)}" ;')
        lines.append(f'    eng:reqPriority "{priority}" ;')
        if category:
            lines.append(f'    eng:reqCategory "{category}" ;')
        lines.append(f"    eng:inDocument <{document}> .")
        if alloc:
            lines.append(f"<{alloc}> dt:satisfies <{ruri}> .")
        lines.append("")

    return "\n".join(lines)


def simulation_results_to_ttl(
    results: list[dict],
    tool: str = "AFSIM",
    case_name: str = "Default Analysis",
) -> str:
    """Mock simulation tool → RDF adapter.

    Expected dict format::

        {
            "name": "Peak Temperature",
            "value": 72.1,
            "unit": "C",
            "status": "PASS",
            "margin": 12.9,
            "analyzed_block": "urn:eng:block:thermal-mgmt-subsystem",
        }
    """
    case_uri = f"urn:sim:case:{_slug(case_name)}"

    lines = [
        "@prefix sim: <urn:sim:> .",
        "@prefix eng: <urn:eng:> .",
        "",
        f"# Simulation results (translated from {tool})",
        "",
        f"<{case_uri}> a eng:AnalysisCase ;",
        f'    rdfs:label "{case_name}" ;',
        f'    sim:tool "{tool}" ;',
        '    sim:status "COMPLETE" .',
        "",
    ]

    for r in results:
        rname = r["name"]
        ruri = f"urn:sim:result:{_slug(rname)}"
        val = r["value"]
        unit = r.get("unit", "")
        status = r.get("status", "")
        margin = r.get("margin")
        block = r.get("analyzed_block")

        lines.append(f"<{ruri}> a eng:SimulationResult ;")
        lines.append(f'    rdfs:label "{rname}" ;')
        lines.append(f"    sim:resultValue {val} ;")
        if unit:
            lines.append(f'    sim:resultUnit "{unit}" ;')
        if status:
            lines.append(f'    sim:status "{status}" ;')
        if margin is not None:
            lines.append(f"    sim:margin {margin} ;")
        lines.append(f"    sim:fromCase <{case_uri}> .")
        if block:
            lines.append(f"<{case_uri}> sim:analyzes <{block}> .")
        lines.append("")

    return "\n".join(lines)


def _lit(v: Any) -> str:
    if isinstance(v, bool):
        return f'"{str(v).lower()}"^^xsd:boolean'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(v)
    return f'"{_escape(str(v))}"'


def _json_to_triples(data, uri, cls, ns, lines, depth=0):
    if isinstance(data, dict):
        lines.append(f"<{uri}> a <{ns}{cls}> .")
        for key, val in data.items():
            pred = f"<{ns}{key}>"
            if isinstance(val, dict):
                child_uri = f"{uri}/{key}"
                lines.append(f"<{uri}> {pred} <{child_uri}> .")
                _json_to_triples(val, child_uri, key.title(), ns, lines, depth + 1)
            elif isinstance(val, list):
                for i, item in enumerate(val):
                    if isinstance(item, dict):
                        child_uri = f"{uri}/{key}/{i}"
                        lines.append(f"<{uri}> {pred} <{child_uri}> .")
                        _json_to_triples(item, child_uri, key.title(), ns, lines, depth + 1)
                    else:
                        lines.append(f"<{uri}> {pred} {_lit(item)} .")
            else:
                lines.append(f"<{uri}> {pred} {_lit(val)} .")


def json_to_ttl(
    data: dict,
    base_uri: str = "urn:data:json",
    class_name: str = "JsonRecord",
    namespace: str = "urn:data:",
) -> str:
    """Generic JSON → RDF adapter.

    Converts a flat or nested dict into TTL triples under a given
    namespace.  Nested dicts become linked resources.
    """
    lines = [
        f"@prefix d: <{namespace}> .",
        "",
    ]
    _json_to_triples(data, base_uri, class_name, namespace, lines)
    return "\n".join(lines)
