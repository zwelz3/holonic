"""Node label formatters for holonic visualization.

Produces structured labels for yFiles nodes.  The key formatter is
``format_compartmented`` which creates UML-style multi-section labels
showing type, attributes, and relationships in visually distinct
compartments.

SHACL shapes get special treatment: the deeply nested blank-node
property constraint structure is collapsed into a readable table of
paths, datatypes, cardinalities, and severities.
"""

from __future__ import annotations

from typing import Any

from holonic.projections import ProjectedNode
from holonic.viz.styles import shorten_uri


def format_simple(node: ProjectedNode) -> str:
    """Simple one-line label: label or local name."""
    return node.label or shorten_uri(node.iri)


def format_typed(node: ProjectedNode) -> str:
    """Label with type annotation: «Type» Name."""
    name = node.label or shorten_uri(node.iri)
    if node.types:
        t = shorten_uri(node.types[0])
        return f"«{t}»\n{name}"
    return name


def format_compartmented(
    node: ProjectedNode,
    *,
    max_attrs: int = 8,
    max_value_len: int = 35,
    show_types: bool = True,
) -> str:
    """UML-style compartmented label.

    Produces a multi-line string with sections:
      «Type»
      ──────
      Name
      ──────
      attr₁: value₁
      attr₂: value₂
      ...

    For yFiles, this renders as a readable multi-line node label.
    The compartment dividers use unicode box-drawing characters.
    """
    lines: list[str] = []

    # ── Type header ──
    if show_types and node.types:
        type_names = ", ".join(shorten_uri(t) for t in node.types[:3])
        lines.append(f"«{type_names}»")

    # ── Name ──
    name = node.label or shorten_uri(node.iri)
    lines.append(name)

    # ── Attributes ──
    attrs = _filter_display_attrs(node.attributes)
    if attrs:
        lines.append("─" * max(len(name), 12))
        for i, (key, val) in enumerate(attrs.items()):
            if i >= max_attrs:
                remaining = len(attrs) - max_attrs
                lines.append(f"  ... +{remaining} more")
                break
            k = shorten_uri(key)
            v = _format_value(val, max_value_len)
            lines.append(f"  {k}: {v}")

    return "\n".join(lines)


def format_shacl_shape(
    node: ProjectedNode,
    *,
    max_props: int = 10,
) -> str:
    """Format a SHACL NodeShape for visualization.

    SHACL shapes use deeply nested blank nodes for property constraints.
    After blank-node resolution (via project_to_lpg), these appear as
    nested dicts in node.attributes under the sh:property key.

    This formatter collapses them into a readable table:

      «NodeShape»
      TargetClassName
      ──────────────
      ✓ path₁  [string]  1..1
      ⚠ path₂  [integer] 0..1
      ...
    """
    lines: list[str] = []

    # Header
    lines.append("«NodeShape»")

    # Target class
    target = node.attributes.get(
        "http://www.w3.org/ns/shacl#targetClass",
        node.attributes.get("targetClass"),
    )
    if target:
        name = shorten_uri(str(target)) if isinstance(target, str) else str(target)
        lines.append(name)
    else:
        lines.append(shorten_uri(node.iri))

    # Property constraints
    props = node.attributes.get(
        "http://www.w3.org/ns/shacl#property",
        node.attributes.get("property"),
    )
    if props:
        lines.append("─" * 20)
        prop_list = props if isinstance(props, list) else [props]
        for i, prop in enumerate(prop_list):
            if i >= max_props:
                lines.append(f"  ... +{len(prop_list) - max_props} more")
                break
            lines.append(_format_shape_property(prop))

    # Closed?
    closed = node.attributes.get(
        "http://www.w3.org/ns/shacl#closed",
        node.attributes.get("closed"),
    )
    if closed:
        lines.append("─" * 20)
        lines.append("  [closed]")

    return "\n".join(lines)


def _format_shape_property(prop: Any) -> str:
    """Format a single SHACL property constraint line."""
    if not isinstance(prop, dict):
        return f"  · {prop}"

    # Extract key fields
    SH = "http://www.w3.org/ns/shacl#"
    path = prop.get(f"{SH}path", prop.get("path", "?"))
    datatype = prop.get(f"{SH}datatype", prop.get("datatype"))
    min_count = prop.get(f"{SH}minCount", prop.get("minCount"))
    max_count = prop.get(f"{SH}maxCount", prop.get("maxCount"))
    severity = prop.get(f"{SH}severity", prop.get("severity"))

    # Severity icon
    if severity:
        sev_str = str(severity)
        if "Violation" in sev_str:
            icon = "✗"
        elif "Warning" in sev_str:
            icon = "⚠"
        else:
            icon = "ℹ"
    else:
        icon = "·"

    # Path
    path_name = shorten_uri(str(path)) if isinstance(path, str) else str(path)

    # Datatype
    dt_str = f"[{shorten_uri(str(datatype))}]" if datatype else ""

    # Cardinality
    lo = str(min_count) if min_count is not None else "0"
    hi = str(max_count) if max_count is not None else "*"
    card = f"{lo}..{hi}"

    parts = [f"  {icon} {path_name:15s}"]
    if dt_str:
        parts.append(f" {dt_str:10s}")
    parts.append(f" {card}")

    return "".join(parts)


def _filter_display_attrs(
    attrs: dict[str, Any],
    exclude_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Filter attributes for display, removing noisy RDF infrastructure."""
    skip = exclude_keys or set()
    skip_fragments = {
        "rdf-syntax-ns#type",
        "label",  # already shown as node name
        "22-rdf-syntax",
    }
    result = {}
    for k, v in attrs.items():
        k_lower = k.lower()
        if k in skip:
            continue
        if any(frag in k_lower for frag in skip_fragments):
            continue
        result[k] = v
    return result


def _format_value(val: Any, max_len: int = 35) -> str:
    """Format a value for display in a node attribute line."""
    if isinstance(val, dict):
        # Nested blank node — show key count
        return f"{{...{len(val)} fields}}"
    if isinstance(val, list):
        if len(val) <= 3:
            items = ", ".join(str(v)[:15] for v in val)
            return f"[{items}]"
        return f"[{len(val)} items]"
    s = str(val)
    if len(s) > max_len:
        return s[:max_len - 1] + "…"
    return s
