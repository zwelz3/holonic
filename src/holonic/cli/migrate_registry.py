"""Migration CLI: backfill graph-type declarations in the registry.

Added in 0.3.4. Scans the registry graph for layer graphs declared
via ``cga:hasInterior`` / ``cga:hasBoundary`` / ``cga:hasProjection``
/ ``cga:hasContext`` that lack the graph-type typing triples
(``a cga:HolonicGraph`` and ``cga:graphRole <role>``) introduced in
0.3.4, and adds them.

Usage::

    holonic-migrate-registry <fuseki-or-rdflib-url> [--apply]

Without ``--apply``, prints the plan (which graphs would get typed,
and with which role). With ``--apply``, writes the triples and
prints a summary.

The migration is idempotent. Running twice is safe; the second run
will find nothing to do. See docs/DECISIONS.md § D-0.3.4-2 for
rationale.
"""

from __future__ import annotations

import argparse
import sys

from holonic import HolonicDataset, RdflibBackend
from holonic import sparql as Q


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="holonic-migrate-registry",
        description="Backfill graph-type declarations in the holonic registry.",
    )
    parser.add_argument(
        "backend",
        nargs="?",
        default="rdflib",
        help=(
            "Backend to migrate. Either 'rdflib' for an in-memory "
            "dataset (useful for testing), or a Fuseki URL like "
            "'http://localhost:3030/holarchy'."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the typing triples. Without this flag, only print the plan.",
    )
    parser.add_argument(
        "--registry-graph",
        default="urn:holarchy:registry",
        help="Registry graph IRI (default: urn:holarchy:registry).",
    )
    return parser.parse_args(argv)


def _make_dataset(backend_spec: str, registry_graph: str) -> HolonicDataset:
    """Build a HolonicDataset for the given backend spec."""
    if backend_spec == "rdflib":
        return HolonicDataset(RdflibBackend(), registry_iri=registry_graph)
    if backend_spec.startswith("http://") or backend_spec.startswith("https://"):
        from holonic.backends.fuseki_backend import FusekiBackend

        # URL form: http://host:port/dataset
        parts = backend_spec.rstrip("/").rsplit("/", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Fuseki URL must be of the form http://host:port/dataset, got {backend_spec!r}"
            )
        endpoint, dataset = parts
        return HolonicDataset(
            FusekiBackend(endpoint, dataset=dataset),
            registry_iri=registry_graph,
            load_ontology=False,
        )
    raise ValueError(f"Unknown backend spec: {backend_spec!r}")


def _plan(ds: HolonicDataset) -> list[tuple[str, str]]:
    """Return the list of (graph_iri, role_local_name) pairs needing typing."""
    rows = ds.backend.query(
        Q.LIST_UNTYPED_LAYER_GRAPHS_TEMPLATE.format(registry_iri=ds.registry_iri)
    )
    plan: list[tuple[str, str]] = []
    for r in rows:
        graph_iri = str(r["graph"])
        role_iri = str(r["role"])
        # Extract local name ("InteriorRole" from "urn:holonic:ontology:InteriorRole")
        role_local = role_iri.rsplit(":", 1)[-1] if ":" in role_iri else role_iri
        plan.append((graph_iri, role_local))
    return plan


def _apply(ds: HolonicDataset, plan: list[tuple[str, str]]) -> int:
    """Apply the typing plan. Returns the number of graphs typed."""
    for graph_iri, role_local in plan:
        ds.backend.update(
            Q.TYPE_GRAPH_TEMPLATE.format(
                registry_iri=ds.registry_iri,
                graph_iri=graph_iri,
                role=role_local,
            )
        )
    return len(plan)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    try:
        ds = _make_dataset(args.backend, args.registry_graph)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    plan = _plan(ds)
    if not plan:
        print("nothing to do — every layer graph is already typed.")
        return 0

    print(f"plan ({len(plan)} graphs to type):")
    for graph_iri, role_local in plan:
        print(f"  + <{graph_iri}>")
        print(f"      a cga:HolonicGraph ; cga:graphRole cga:{role_local} .")

    if not args.apply:
        print()
        print("dry run — pass --apply to write these triples.")
        return 0

    n = _apply(ds, plan)
    print()
    print(f"applied: {n} graphs typed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
