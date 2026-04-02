"""Lightweight result types for holonic operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MembraneHealth(Enum):
    INTACT = "intact"
    WEAKENED = "weakened"
    COMPROMISED = "compromised"


@dataclass
class MembraneResult:
    """Result of SHACL membrane validation."""

    holon_iri: str
    conforms: bool
    health: MembraneHealth
    report_text: str
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        label = self.holon_iri.rsplit(":", 1)[-1] if ":" in self.holon_iri else self.holon_iri
        lines = [f"Membrane [{label}]: {self.health.value.upper()}"]
        lines.append(f"  conforms: {self.conforms}")
        if self.violations:
            lines.append(f"  violations ({len(self.violations)}):")
            for v in self.violations[:5]:
                lines.append(f"    - {v}")
        if self.warnings:
            lines.append(f"  warnings ({len(self.warnings)}):")
            for w in self.warnings[:5]:
                lines.append(f"    - {w}")
        return "\n".join(lines)


@dataclass
class PortalInfo:
    """Descriptor for a discovered portal."""

    iri: str
    source_iri: str
    target_iri: str
    label: str | None = None
    construct_query: str | None = None

    def __repr__(self) -> str:
        lbl = self.label or self.iri.rsplit(":", 1)[-1]
        return f"Portal({lbl}: {self.source_iri} → {self.target_iri})"


@dataclass
class HolonInfo:
    """Descriptor for a discovered holon."""

    iri: str
    label: str | None = None
    interior_graphs: list[str] = field(default_factory=list)
    boundary_graphs: list[str] = field(default_factory=list)
    projection_graphs: list[str] = field(default_factory=list)
    context_graphs: list[str] = field(default_factory=list)


class MembraneBreachError(Exception):
    """Raised when a portal traversal would produce membrane-invalid data."""

    def __init__(self, result: MembraneResult):
        self.result = result
        super().__init__(
            f"Membrane COMPROMISED for {result.holon_iri}: "
            f"{len(result.violations)} violation(s)"
        )
