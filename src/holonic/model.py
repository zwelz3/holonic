"""Lightweight result types for holonic operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


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


@dataclass
class HolarchyTree:
    """Holarchy structure with depth, parentage, and labels.

    Returned by ``HolonicDataset.compute_depth()``.  Can be used
    as a dict (``tree[iri]`` returns depth) or printed as a tree.
    """

    depths: dict[str, int] = field(default_factory=dict)
    parents: dict[str, str] = field(default_factory=dict)
    children: dict[str, list[str]] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def roots(self) -> list[str]:
        """Holons with no parent (depth 0)."""
        return sorted(
            [iri for iri, d in self.depths.items() if d == 0],
            key=lambda iri: self.labels.get(iri, iri),
        )

    # ── Dict-like access for backward compat ──

    def __getitem__(self, iri: str) -> int:
        return self.depths[iri]

    def __contains__(self, iri: str) -> bool:
        return iri in self.depths

    def __iter__(self):
        return iter(self.depths)

    def __len__(self) -> int:
        return len(self.depths)

    def items(self):
        return self.depths.items()

    def get(self, iri: str, default: int | None = None) -> int | None:
        return self.depths.get(iri, default)

    # ── Tree rendering ──

    def __str__(self) -> str:
        lines: list[str] = []
        for root in self.roots:
            self._render(root, "", True, lines)
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"HolarchyTree({len(self.depths)} holons, {len(self.roots)} roots)"

    def _render(
        self,
        iri: str,
        prefix: str,
        is_last: bool,
        lines: list[str],
    ) -> None:
        connector = "└── " if is_last else "├── "
        label = self.labels.get(iri, iri.rsplit(":", 1)[-1])
        if not prefix:
            # Root node — no connector
            lines.append(label)
        else:
            lines.append(f"{prefix}{connector}{label}")

        kids = self.children.get(iri, [])
        kids_sorted = sorted(kids, key=lambda k: self.labels.get(k, k))
        child_prefix = prefix + ("    " if is_last else "│   ")
        for i, child in enumerate(kids_sorted):
            self._render(child, child_prefix, i == len(kids_sorted) - 1, lines)


class MembraneBreachError(Exception):
    """Raised when a portal traversal would produce membrane-invalid data."""

    def __init__(self, result: MembraneResult):
        self.result = result
        super().__init__(
            f"Membrane COMPROMISED for {result.holon_iri}: {len(result.violations)} violation(s)"
        )


# ══════════════════════════════════════════════════════════════
# Audit trail types
# ══════════════════════════════════════════════════════════════


@dataclass
class TraversalRecord:
    """A single portal traversal event from the provenance trail."""

    activity_iri: str
    source_iri: str
    target_iri: str
    agent_iri: str | None = None
    portal_label: str | None = None
    timestamp: str | None = None

    @property
    def source_label(self) -> str:
        return self.source_iri.rsplit(":", 1)[-1]

    @property
    def target_label(self) -> str:
        return self.target_iri.rsplit(":", 1)[-1]


@dataclass
class ValidationRecord:
    """A membrane validation event from the provenance trail."""

    activity_iri: str
    holon_iri: str
    health: str
    agent_iri: str | None = None
    timestamp: str | None = None

    @property
    def health_label(self) -> str:
        h = self.health.rsplit(":", 1)[-1] if ":" in self.health else self.health
        return h.upper()

    @property
    def holon_label(self) -> str:
        return self.holon_iri.rsplit(":", 1)[-1]


@dataclass
class SurfaceReport:
    """Summary of what a holon's boundary requires (from SHACL shapes)."""

    holon_iri: str
    target_classes: list[str] = field(default_factory=list)
    required_fields: list[str] = field(default_factory=list)
    optional_fields: list[str] = field(default_factory=list)
    violations: int = 0
    warnings: int = 0


@dataclass
class AuditTrail:
    """Complete provenance audit of all traversals and validations."""

    traversals: list[TraversalRecord] = field(default_factory=list)
    validations: list[ValidationRecord] = field(default_factory=list)
    derivation_chain: list[tuple[str, str]] = field(default_factory=list)
    surfaces: dict[str, SurfaceReport] = field(default_factory=dict)

    @property
    def participating_holons(self) -> set[str]:
        """All holon IRIs involved in the audit trail."""
        holons = set()
        for t in self.traversals:
            holons.add(t.source_iri)
            holons.add(t.target_iri)
        for v in self.validations:
            holons.add(v.holon_iri)
        return holons

    def validation_for(self, holon_iri: str) -> ValidationRecord | None:
        """Find the most recent validation for a holon."""
        matches = [v for v in self.validations if v.holon_iri == holon_iri]
        return matches[-1] if matches else None

    def summary(self) -> str:
        lines = [
            "AuditTrail",
            f"  Traversals:  {len(self.traversals)}",
            f"  Validations: {len(self.validations)}",
            f"  Holons:      {len(self.participating_holons)}",
            f"  Derivations: {len(self.derivation_chain)}",
        ]
        if self.traversals:
            lines.append("\n  Pipeline:")
            for i, t in enumerate(self.traversals):
                arrow = "→"
                v = self.validation_for(t.target_iri)
                health = f" [{v.health_label}]" if v else ""
                lines.append(f"    {i + 1}. {t.source_label} {arrow} {t.target_label}{health}")
                if t.portal_label:
                    lines.append(f"       portal: {t.portal_label}")
                if t.timestamp:
                    lines.append(f"       time:   {t.timestamp[:19]}")
        if self.surfaces:
            lines.append("\n  Surfaces:")
            for iri, s in self.surfaces.items():
                label = iri.rsplit(":", 1)[-1]
                lines.append(
                    f"    {label}: {len(s.required_fields)} required, "
                    f"{len(s.optional_fields)} optional"
                )
        return "\n".join(lines)
