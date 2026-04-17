# Backends

## HolonicStore Protocol

```{eval-rst}
.. autoclass:: holonic.backends.store.HolonicStore
   :members:
```

## AbstractHolonicStore

Recommended base class for new backend implementations. Marks
mandatory methods as abstract and provides hook points for optional
native methods (0.4.x growing).

```{eval-rst}
.. autoclass:: holonic.backends.store.AbstractHolonicStore
   :members:
   :show-inheritance:
```

## RdflibBackend

```{eval-rst}
.. autoclass:: holonic.backends.rdflib_backend.RdflibBackend
   :members:
   :show-inheritance:
```

## FusekiBackend

```{eval-rst}
.. autoclass:: holonic.backends.fuseki_backend.FusekiBackend
   :members:
   :show-inheritance:
```

## Implementing a Custom Backend

Any object satisfying the `HolonicStore` protocol can back a
`HolonicDataset`. The protocol requires named-graph CRUD and SPARQL
query/update methods. Inheriting `AbstractHolonicStore` is
recommended (you get `@abstractmethod` enforcement of the mandatory
surface) but not required — duck-typing works too.

```python
from holonic.backends.store import AbstractHolonicStore

class MyBackend(AbstractHolonicStore):
    def graph_exists(self, graph_iri: str) -> bool: ...
    def get_graph(self, graph_iri: str) -> Graph: ...
    def put_graph(self, graph_iri: str, g: Graph) -> None: ...
    def post_graph(self, graph_iri: str, g: Graph) -> None: ...
    def delete_graph(self, graph_iri: str) -> None: ...
    def parse_into(self, graph_iri: str, data: str, format: str) -> None: ...
    def query(self, sparql: str, **bindings) -> list[dict]: ...
    def construct(self, sparql: str, **bindings) -> Graph: ...
    def ask(self, sparql: str, **bindings) -> bool: ...
    def update(self, sparql: str) -> None: ...
    def list_named_graphs(self) -> list[str]: ...

# Use it:
ds = HolonicDataset(backend=MyBackend())
```

## Optional Native Methods

Backends that can compute operations natively (faster than the
library's Python fallback) can override optional methods. The library
discovers them via `hasattr` — no registration required. As of 0.4.0,
one optional method is recognized:

```python
class MyBackend(AbstractHolonicStore):
    # ... mandatory methods above ...

    def refresh_graph_metadata(
        self,
        graph_iri: str,
        registry_iri: str,
    ) -> GraphMetadata | None:
        # Fast native path: compute triple count + class inventory,
        # write to registry, return GraphMetadata (or None to let
        # the library re-read it via the standard read path).
        ...
```

If `refresh_graph_metadata` is absent, `MetadataRefresher` runs its
generic Python implementation. Additional optional methods (scope
walking, bulk load, pipeline execution) are planned additively
across the 0.4.x series.

## Migrating from `GraphBackend` (0.3.x)

`GraphBackend` is a deprecated alias for `HolonicStore` kept through
all of 0.4.x. New code should import `HolonicStore` from
`holonic.backends.store` (or from the top-level `holonic` package).
See `docs/MIGRATION.md` for the full 0.3.x → 0.4.0 migration
checklist.
