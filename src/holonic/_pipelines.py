"""Projection-pipeline registry and execution (0.8.0).

Extracted from :class:`holonic.client.HolonicDataset` as part of the
0.8.0 god-class decomposition (AR1/CQ1). This module owns everything
about *governed* projection pipelines -- the RDF-declared
``cga:ProjectionPipelineSpec`` model: registering specs into the
registry graph, reading them back in ``rdf:List`` order, and executing
them against a holon's interiors with full ``prov:Activity`` recording.

The manager holds a back-reference to its owning ``HolonicDataset``
(``self._ds``) rather than a bare backend, because pipeline execution
reaches back into the facade's layer-registration and metadata-refresh
machinery (``_register_layer`` / ``_maybe_refresh``). This mirrors the
delegate pattern used by :class:`holonic._metadata.MetadataRefresher`
and :class:`holonic.scope.ScopeResolver`, differing only in that those
two are stateless over ``(backend, registry_iri)`` whereas pipeline
runs need the richer facade surface.

``HolonicDataset`` keeps thin delegating wrappers for the public
methods (``register_pipeline``, ``register_pipeline_ttl``,
``attach_pipeline``, ``list_pipelines``, ``get_pipeline``,
``run_projection``) so the public API is unchanged.

.. versionadded:: 0.8.0
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from rdflib import RDF, Graph, URIRef

from holonic import sparql as Q

if TYPE_CHECKING:
    from holonic.client import HolonicDataset
    from holonic.console_model import (
        ProjectionPipelineSpec,
        ProjectionPipelineStep,
        ProjectionPipelineSummary,
    )


class PipelineManager:
    """Registry and executor for governed projection pipelines.

    Constructed once per :class:`~holonic.client.HolonicDataset` and
    reached via ``ds._pipelines``. Public dataset methods delegate here.
    """

    def __init__(self, ds: HolonicDataset):
        self._ds = ds

    # ── Serialization ───────────────────────────────────────────

    def _pipeline_to_ttl(self, spec: ProjectionPipelineSpec) -> str:
        """Convert a ProjectionPipelineSpec to Turtle for the registry."""
        from holonic.client import _escape_construct, _escape_ttl

        lines = [
            "@prefix cga:  <urn:holonic:ontology:> .",
            "@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
            "",
            f"<{spec.iri}> a cga:ProjectionPipelineSpec ;",
            f'    rdfs:label "{_escape_ttl(spec.name)}" ;',
        ]
        if spec.description:
            lines[-1] += ""
            lines.append(f'    rdfs:comment "{_escape_ttl(spec.description)}" ;')

        if not spec.steps:
            # Empty pipeline -- no steps, close the spec
            lines[-1] = lines[-1].rstrip(" ;") + " ."
            return "\n".join(lines)

        # Build an rdf:List of blank-node step resources
        step_iris = [f"<{spec.iri}/step/{i}>" for i in range(len(spec.steps))]
        lines[-1] += ""  # keep trailing ;
        lines.append(f"    cga:hasStep ({' '.join(step_iris)}) .")
        lines.append("")

        # Emit each step resource
        for iri, step in zip(step_iris, spec.steps):
            lines.append(f"{iri} a cga:ProjectionPipelineStep ;")
            lines.append(f'    cga:stepName "{_escape_ttl(step.name)}"')
            extras = []
            if step.transform_name:
                extras.append(f'    cga:transformName "{_escape_ttl(step.transform_name)}"')
            if step.construct_query:
                extras.append(
                    f'    cga:constructQuery """{_escape_construct(step.construct_query)}"""'
                )
            if extras:
                lines[-1] += " ;"
                for i, extra in enumerate(extras):
                    suffix = " ;" if i < len(extras) - 1 else " ."
                    lines.append(extra + suffix)
            else:
                lines[-1] += " ."
            lines.append("")
        return "\n".join(lines)

    # ── Registration ────────────────────────────────────────────

    def register_pipeline(self, spec: ProjectionPipelineSpec) -> str:
        """Register a projection pipeline in the registry.

        Validates that every step's ``transform_name`` (if any) is
        known to the plugin registry. Raises ``TransformNotFoundError``
        at registration time rather than later at run time.

        Returns the pipeline's IRI.
        """
        from holonic.plugins import resolve_transform

        # Validate named transforms up front
        for step in spec.steps:
            if step.transform_name:
                resolve_transform(step.transform_name)

        # Serialize to Turtle and write to registry
        ttl = self._pipeline_to_ttl(spec)
        self._ds.backend.parse_into(self._ds.registry_iri, ttl, "turtle")
        return spec.iri

    def register_pipeline_ttl(self, ttl: str) -> None:
        """Escape hatch: register a pipeline from caller-supplied Turtle.

        Parses the Turtle into the registry graph without validation.
        Caller is responsible for conforming to the
        ``cga:ProjectionPipelineSpec`` + ``cga:ProjectionPipelineStep``
        vocabulary and for valid rdf:List ordering.
        """
        self._ds.backend.parse_into(self._ds.registry_iri, ttl, "turtle")

    def attach_pipeline(self, holon_iri: str, spec_iri: str) -> None:
        """Declare that a holon has access to a registered pipeline.

        Writes ``<holon_iri> cga:hasPipeline <spec_iri>`` into the
        registry graph. Idempotent at the RDF level (duplicate
        triples in the same graph are coalesced).
        """
        self._ds.backend.parse_into(
            self._ds.registry_iri,
            f"""
            @prefix cga: <urn:holonic:ontology:> .
            <{holon_iri}> cga:hasPipeline <{spec_iri}> .
            """,
            "turtle",
        )

    # ── Reads ───────────────────────────────────────────────────

    def list_pipelines(self, holon_iri: str) -> list[ProjectionPipelineSummary]:
        """Return projection pipelines attached to a holon.

        Each summary carries just iri, name, description, and step
        count -- use ``get_pipeline(iri)`` for full step content.
        """
        from holonic.console_model import ProjectionPipelineSummary

        rows = self._ds.backend.query(
            Q.LIST_PIPELINES_FOR_HOLON_TEMPLATE.format(
                registry_iri=self._ds.registry_iri,
                holon_iri=holon_iri,
            )
        )
        return [
            ProjectionPipelineSummary(
                iri=str(r["spec"]),
                name=str(r["name"]),
                description=str(r["description"]) if r.get("description") else None,
                step_count=int(r.get("step_count") or 0),
            )
            for r in rows
        ]

    def _step_from_node(self, reg_graph, step_node):
        """Materialize a ProjectionPipelineStep from its graph node."""
        from holonic.console_model import ProjectionPipelineStep

        cga_stepName = URIRef("urn:holonic:ontology:stepName")
        cga_transformName = URIRef("urn:holonic:ontology:transformName")
        cga_constructQuery = URIRef("urn:holonic:ontology:constructQuery")
        name = reg_graph.value(step_node, cga_stepName)
        transform = reg_graph.value(step_node, cga_transformName)
        construct = reg_graph.value(step_node, cga_constructQuery)
        return ProjectionPipelineStep(
            name=str(name) if name else "",
            transform_name=str(transform) if transform else None,
            construct_query=str(construct) if construct else None,
        )

    def _read_pipeline_steps_ordered(self, spec_iri: str) -> list[ProjectionPipelineStep]:
        """Read pipeline steps preserving rdf:List order."""
        reg = self._ds.backend.get_graph(self._ds.registry_iri)
        spec = URIRef(spec_iri)
        cga_hasStep = URIRef("urn:holonic:ontology:hasStep")
        head = reg.value(spec, cga_hasStep)
        if head is None:
            return []
        # Walk rdf:first / rdf:rest
        steps: list[ProjectionPipelineStep] = []
        current = head
        while current and current != RDF.nil:
            step_node = reg.value(current, RDF.first)
            if step_node is None:
                break
            step = self._step_from_node(reg, step_node)
            steps.append(step)
            current = reg.value(current, RDF.rest)
        return steps

    def get_pipeline(self, spec_iri: str) -> ProjectionPipelineSpec | None:
        """Return the full pipeline spec as a ``ProjectionPipelineSpec``.

        Returns ``None`` if no pipeline with the given IRI is registered.
        Steps are returned in their declared rdf:List order.
        """
        from holonic.console_model import ProjectionPipelineSpec

        detail_rows = self._ds.backend.query(
            Q.READ_PIPELINE_DETAIL_TEMPLATE.format(
                registry_iri=self._ds.registry_iri,
                spec_iri=spec_iri,
            )
        )
        if not detail_rows:
            return None
        name = str(detail_rows[0]["name"])
        description = (
            str(detail_rows[0]["description"]) if detail_rows[0].get("description") else None
        )
        # Walk the rdf:List in registered order. We pull it from the
        # registry graph directly so ordering is canonical.
        steps = self._read_pipeline_steps_ordered(spec_iri)
        return ProjectionPipelineSpec(
            iri=spec_iri,
            name=name,
            description=description,
            steps=steps,
        )

    # ── Execution + provenance ──────────────────────────────────

    def _record_projection_activity(
        self,
        *,
        holon_iri: str,
        spec_iri: str,
        output_graph_iri: str | None,
        started: datetime,
        ended: datetime,
        agent_iri: str | None,
        transform_versions: list[str],
        host_meta: dict[str, str],
    ) -> str:
        """Write a prov:Activity for a projection run. Returns activity IRI."""
        from holonic.client import _bind_iri, _escape_ttl

        activity_iri = f"urn:activity:projection:{uuid4()}"
        # Find or default the holon's context graph
        context_rows = self._ds.backend.query(Q.GET_HOLON_CONTEXTS, holon=_bind_iri(holon_iri))
        if context_rows:
            ctx_graph_iri = str(context_rows[0]["graph"])
        else:
            ctx_graph_iri = f"{holon_iri}/context"
            self._ds._register_layer(holon_iri, ctx_graph_iri, "hasContext")

        ttl_lines = [
            "@prefix cga:  <urn:holonic:ontology:> .",
            "@prefix prov: <http://www.w3.org/ns/prov#> .",
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
            "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .",
            "",
            f"<{activity_iri}> a prov:Activity ;",
            f'    rdfs:label "Projection run: {_escape_ttl(spec_iri)}" ;',
            f"    prov:used <{spec_iri}> ;",
            f'    prov:startedAtTime "{started.isoformat()}"^^xsd:dateTime ;',
            f'    prov:endedAtTime "{ended.isoformat()}"^^xsd:dateTime ;',
        ]
        if output_graph_iri:
            ttl_lines.append(f"    prov:generated <{output_graph_iri}> ;")
        if agent_iri:
            ttl_lines.append(f"    prov:wasAssociatedWith <{agent_iri}> ;")
        for v in transform_versions:
            ttl_lines.append(f'    cga:transformVersion "{_escape_ttl(v)}" ;')
        ttl_lines.append(f'    cga:runHost "{_escape_ttl(host_meta["host"])}" ;')
        ttl_lines.append(f'    cga:runPlatform "{_escape_ttl(host_meta["platform"])}" ;')
        ttl_lines.append(f'    cga:runPythonVersion "{_escape_ttl(host_meta["python_version"])}" ;')
        ttl_lines.append(
            f'    cga:runHolonicVersion "{_escape_ttl(host_meta["holonic_version"])}" .'
        )

        self._ds.backend.parse_into(ctx_graph_iri, "\n".join(ttl_lines), "turtle")
        return activity_iri

    def run_projection(
        self,
        holon_iri: str,
        spec_iri: str,
        *,
        store_as: str | None = None,
        agent_iri: str | None = None,
    ) -> Graph:
        """Execute a registered pipeline against a holon's interiors.

        See :meth:`holonic.client.HolonicDataset.run_projection` for the
        full contract; this is the implementation it delegates to.
        """
        from holonic.client import _bind_iri, _run_construct_on_graph
        from holonic.plugins import (
            host_metadata,
            resolve_transform,
            transform_version,
        )

        spec = self.get_pipeline(spec_iri)
        if spec is None:
            raise ValueError(f"No pipeline registered with IRI {spec_iri!r}")

        started = datetime.now(UTC)

        # Merge interiors
        interior_rows = self._ds.backend.query(
            Q.GET_HOLON_INTERIORS, holon=_bind_iri(holon_iri)
        )
        merged = Graph()
        for row in interior_rows:
            g = self._ds.backend.get_graph(row["graph"])
            for triple in g:
                merged.add(triple)

        # Execute steps
        current = merged
        transform_versions: list[str] = []
        for step in spec.steps:
            if step.transform_name:
                fn = resolve_transform(step.transform_name)
                current = fn(current)
                ver = transform_version(step.transform_name)
                if ver:
                    transform_versions.append(ver)
            if step.construct_query:
                # Run the CONSTRUCT against the current intermediate graph
                current = _run_construct_on_graph(current, step.construct_query)

        ended = datetime.now(UTC)

        # Optionally store result and register as a projection
        if store_as:
            self._ds.backend.put_graph(store_as, current)
            self._ds._register_layer(holon_iri, store_as, "hasProjection")
            self._ds._maybe_refresh(store_as)

        # Record provenance in the holon's context graph
        self._record_projection_activity(
            holon_iri=holon_iri,
            spec_iri=spec_iri,
            output_graph_iri=store_as,
            started=started,
            ended=ended,
            agent_iri=agent_iri,
            transform_versions=transform_versions,
            host_meta=host_metadata(),
        )

        return current
