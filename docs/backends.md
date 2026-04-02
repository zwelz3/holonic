# Backends

## GraphBackend Protocol

```{eval-rst}
.. autoclass:: holonic.backends.protocol.GraphBackend
   :members:
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

Any class implementing the `GraphBackend` protocol can back a `HolonicDataset`.
The protocol requires named-graph CRUD and SPARQL query/update methods:

```python
from holonic.backends.protocol import GraphBackend

class MyBackend:
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
