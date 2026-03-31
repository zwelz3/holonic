"""
membrane.py — SHACL validation interpreted as holonic membrane health.

In Cagel's model, SHACL *constitutes* the boundary membrane — it is not
an external checker but the structural definition of what the holon allows
inside and what it permits out.

Severity mapping
----------------
sh:Violation  →  COMPROMISED   The membrane is genuinely breached.
sh:Warning    →  WEAKENED      The membrane is degraded but functional.
sh:Info       →  (advisory)    No structural concern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from rdflib import Graph, URIRef, Namespace
from rdflib.namespace import SH

from .holon import Holon


class MembraneHealth(Enum):
    INTACT = "intact"
    WEAKENED = "weakened"
    COMPROMISED = "compromised"


@dataclass
class MembraneResult:
    holon_label: str
    health: MembraneHealth
    conforms: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    infos: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Membrane [{self.holon_label}]: {self.health.value.upper()}",
            f"  conforms: {self.conforms}",
        ]
        for tag, items in [("✗ violation", self.violations),
                           ("⚠ warning", self.warnings),
                           ("ℹ info", self.infos)]:
            for item in items:
                lines.append(f"  {tag}: {item}")
        return "\n".join(lines)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def validate_membrane(
    holon: Holon,
    extra_shapes: Optional[Graph] = None,
) -> MembraneResult:
    """
    Validate a holon's interior against its boundary membrane.

    Parameters
    ----------
    holon : Holon
        The holon to check.
    extra_shapes : Graph, optional
        Additional SHACL shapes to merge with the boundary (e.g. from
        a parent holon or a shared shapes library).

    Returns
    -------
    MembraneResult
    """
    shapes = Graph()
    for t in holon.boundary:
        shapes.add(t)
    if extra_shapes:
        for t in extra_shapes:
            shapes.add(t)

    return validate_membrane_raw(holon.interior, shapes, label=holon.label)


def validate_membrane_raw(
    data: Graph,
    shapes: Graph,
    label: str = "raw",
) -> MembraneResult:
    """Validate an arbitrary data graph against an arbitrary shapes graph."""
    import pyshacl

    conforms, results_graph, _ = pyshacl.validate(
        data_graph=data,
        shacl_graph=shapes,
        inference="none",
        abort_on_first=False,
    )

    SH_NS = Namespace("http://www.w3.org/ns/shacl#")
    RDF_TYPE = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")

    violations, warnings, infos = [], [], []

    for node in results_graph.subjects(RDF_TYPE, SH_NS.ValidationResult):
        severity = None
        message = "(no message)"
        focus = path = None

        for _, _, s in results_graph.triples((node, SH_NS.resultSeverity, None)):
            severity = s
        for _, _, m in results_graph.triples((node, SH_NS.resultMessage, None)):
            message = str(m)
        for _, _, f in results_graph.triples((node, SH_NS.focusNode, None)):
            focus = str(f)
        for _, _, p in results_graph.triples((node, SH_NS.resultPath, None)):
            path = str(p)

        detail = message
        if focus:
            detail = f"[{focus}] {detail}"
        if path:
            detail += f" (path: {path})"

        if severity == SH_NS.Violation:
            violations.append(detail)
        elif severity == SH_NS.Warning:
            warnings.append(detail)
        else:
            infos.append(detail)

    if violations:
        health = MembraneHealth.COMPROMISED
    elif warnings:
        health = MembraneHealth.WEAKENED
    else:
        health = MembraneHealth.INTACT

    return MembraneResult(
        holon_label=label,
        health=health,
        conforms=conforms,
        violations=violations,
        warnings=warnings,
        infos=infos,
    )
