from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any

import aiohttp
from aiohttp import ClientResponse
from rdflib import Graph

log = logging.getLogger(__name__)


class FusekiError(RuntimeError):
    pass


class FusekiClient:
    """Minimal, extensible async client for Apache Jena Fuseki.

    Parameters
    ----------
    base_url:
        Base URL for the Fuseki server, e.g. "http://localhost:3030"
    dataset:
        Optional default dataset name, e.g. "mydataset".
        Can be omitted and supplied per-call instead.
    session_kwargs:
        Extra kwargs forwarded to aiohttp.ClientSession.
    max_retries:
        Number of retry attempts on 5xx / timeout errors.
    retry_backoff:
        Base backoff in seconds (exponential).
    default_graph_content_type:
        Default Content-Type for graph payloads.
    """

    # ------------------------------------------------------------------
    # Fuseki dataset type constants (used when creating datasets)
    # ------------------------------------------------------------------
    DB_TYPE_TDB2 = "tdb2"  # Persistent – TDB2 (recommended)
    DB_TYPE_TDB1 = "tdb"  # Persistent – TDB1 (legacy)
    DB_TYPE_MEM = "mem"  # In-memory (non-persistent)

    def __init__(
        self,
        base_url: str,
        dataset: str | None = None,
        *,
        session_kwargs: dict | None = None,
        max_retries: int = 3,
        retry_backoff: float = 0.5,
        default_graph_content_type: str = "text/turtle",
    ):
        self.base_url = base_url.rstrip("/")
        self.dataset = dataset  # default dataset; may be None
        self._session_kwargs = session_kwargs or {}
        self._session: aiohttp.ClientSession | None = None
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.default_ct = default_graph_content_type

    # ------------------------------------------------------------------
    # Admin API endpoint
    # ------------------------------------------------------------------

    @property
    def _admin_datasets_endpoint(self) -> str:
        """Fuseki admin datasets endpoint: /$/datasets"""
        return f"{self.base_url}/$/datasets"

    # ------------------------------------------------------------------
    # Dataset-scoped endpoint helpers
    # ------------------------------------------------------------------

    def _resolve_dataset(self, dataset: str | None = None) -> str:
        """Return the dataset name to use.  Prefers an explicit argument;
        falls back to self.dataset; raises if neither is set.
        """
        ds = dataset or self.dataset
        if not ds:
            raise FusekiError("No dataset specified. Pass `dataset=` or set self.dataset.")
        return ds

    def gsp_endpoint(self, dataset: str | None = None) -> str:
        """Graph Store Protocol endpoint for PUT/GET/POST/DELETE."""
        ds = self._resolve_dataset(dataset)
        return f"{self.base_url}/{ds}/data"

    def sparql_query_endpoint(self, dataset: str | None = None) -> str:
        """SPARQL query endpoint."""
        ds = self._resolve_dataset(dataset)
        return f"{self.base_url}/{ds}/sparql"

    def sparql_update_endpoint(self, dataset: str | None = None) -> str:
        """SPARQL update endpoint."""
        ds = self._resolve_dataset(dataset)
        return f"{self.base_url}/{ds}/update"

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        data: Any | None = None,
        expected_status: Iterable[int] = (200,),
        allow_redirects: bool = True,
        raise_for_status: bool = True,
        timeout: int | None = None,
    ) -> ClientResponse:
        """Issue an HTTP request with automatic retry on 5xx / timeout.
        Returns the aiohttp ClientResponse.
        """
        if self._session is None:
            raise FusekiError(
                "Client session is not open; use 'async with FusekiClient(...)' or call .open()"
            )

        expected = set(expected_status)
        attempt = 0
        while True:
            attempt += 1
            try:
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    data=data,
                    allow_redirects=allow_redirects,
                    timeout=timeout,
                ) as resp:
                    # Read the body so the connection is released
                    body = await resp.read()
                    text = body.decode("utf-8", errors="replace")

                    if resp.status not in expected:
                        # Retry on server errors
                        if attempt <= self.max_retries and 500 <= resp.status < 600:
                            backoff = self.retry_backoff * (2 ** (attempt - 1))
                            log.warning(
                                "Server error %s; retrying in %s s (attempt %s)",
                                resp.status,
                                backoff,
                                attempt,
                            )
                            await asyncio.sleep(backoff)
                            continue
                        if raise_for_status:
                            raise FusekiError(f"HTTP {resp.status} for {method} {url}: {text}")
                    return resp, body
            except TimeoutError:
                if attempt <= self.max_retries:
                    backoff = self.retry_backoff * (2 ** (attempt - 1))
                    log.warning("Timeout; retrying in %s s (attempt %s)", backoff, attempt)
                    await asyncio.sleep(backoff)
                    continue
                raise

    async def _request_json(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> Any:
        """Convenience wrapper: issue a request and return the parsed JSON body.
        Adds Accept: application/json automatically.
        """
        headers = kwargs.pop("headers", {}) or {}
        headers.setdefault("Accept", "application/json")
        resp, *_ = await self._request(method, url, headers=headers, **kwargs)
        # resp.read() was already called inside _request; re-read from cache
        return await resp.json(content_type=None)

    # ==================================================================
    # Dataset management  (Fuseki Admin API – /$/datasets)
    # ==================================================================

    async def list_datasets(self) -> list[dict[str, Any]]:
        """List all datasets on the server.

        Returns:
        -------
        list[dict]
            Each dict contains keys such as ``ds.name``, ``ds.state``,
            ``ds.services``, etc., as returned by Fuseki.



        Reference: https://jena.apache.org/documentation/fuseki2/fuseki-server-protocol.html
        """
        result = await self._request_json(
            "GET",
            self._admin_datasets_endpoint,
            expected_status=(200,),
        )
        # Fuseki wraps the list under {"datasets": [...]}
        return result.get("datasets", [])

    async def get_dataset(self, dataset: str | None = None) -> dict[str, Any]:
        """Get detailed information about a single dataset.

        Parameters
        ----------
        dataset:
            Dataset name.  Falls back to ``self.dataset`` if omitted.

        Returns:
        -------
        dict
            Dataset descriptor as returned by Fuseki (name, state, services …).
        """
        ds = self._resolve_dataset(dataset)
        url = f"{self._admin_datasets_endpoint}/{ds}"
        return await self._request_json(
            "GET",
            url,
            expected_status=(200,),
        )

    async def create_dataset(
        self,
        dataset: str | None = None,
        *,
        db_type: str = DB_TYPE_TDB2,
    ) -> dict[str, Any]:
        """Create a new dataset on the Fuseki server.

        Parameters
        ----------
        dataset:
            Name for the new dataset.  Falls back to ``self.dataset``.
        db_type:
            Storage type.  One of ``FusekiClient.DB_TYPE_TDB2`` (default),
            ``FusekiClient.DB_TYPE_TDB1``, or ``FusekiClient.DB_TYPE_MEM``.

        Returns:
        -------
        dict
            Confirmation payload from Fuseki (may be empty on 200).

        Raises:
        ------
        FusekiError
            If the server rejects the request (e.g. dataset already exists → 409).
        """
        ds = self._resolve_dataset(dataset)

        # Fuseki expects a form-encoded POST with dbName and dbType
        form_data = aiohttp.FormData()
        form_data.add_field("dbName", ds)
        form_data.add_field("dbType", db_type)

        resp, *_ = await self._request(
            "POST",
            self._admin_datasets_endpoint,
            data=form_data,
            expected_status=(200, 201),
        )

        # Try to return JSON if available; otherwise return status info
        try:
            return await resp.json(content_type=None)
        except Exception:
            return {"status": resp.status, "dataset": ds, "dbType": db_type}

    async def get_or_create_dataset(
        self,
        dataset: str | None = None,
        *,
        db_type: str = DB_TYPE_TDB2,
    ) -> dict[str, Any]:
        """Return dataset info if it already exists; otherwise create it first.

        This is an idempotent operation — safe to call repeatedly without
        side effects on an existing dataset.

        Parameters
        ----------
        dataset:
            Dataset name.  Falls back to ``self.dataset`` if omitted.
        db_type:
            Storage type used only if the dataset needs to be created.
            One of ``DB_TYPE_TDB2`` (default), ``DB_TYPE_TDB1``, or
            ``DB_TYPE_MEM``.

        Returns:
        -------
        dict
            Dataset descriptor as returned by Fuseki (name, state, services …).

        Example:
        -------
            async with FusekiClient("http://localhost:3030", dataset="mydata") as client:
                info = await client.get_or_create_dataset()
                # First call creates it; subsequent calls just return info.
        """
        ds = self._resolve_dataset(dataset)

        # --- Try to fetch existing dataset --------------------------------
        url = f"{self._admin_datasets_endpoint}/{ds}"
        resp, *_ = await self._request(
            "GET",
            url,
            expected_status=(200, 404),
            raise_for_status=False,
        )

        if resp.status == 200:
            # Dataset already exists — return its metadata
            log.debug("Dataset '%s' already exists", ds)
            try:
                return await resp.json(content_type=None)
            except Exception:
                return {"ds.name": f"/{ds}", "status": "exists"}

        # --- Does not exist — create it -----------------------------------
        log.info("Dataset '%s' not found; creating with dbType=%s", ds, db_type)
        await self.create_dataset(dataset=ds, db_type=db_type)

        # --- Fetch and return the newly created dataset's metadata --------
        return await self.get_dataset(dataset=ds)

    async def delete_dataset(
        self,
        dataset: str | None = None,
    ) -> bool:
        """Delete a dataset from the Fuseki server.

        .. warning::
            This permanently removes the dataset and all its data.

        Parameters
        ----------
        dataset:
            Dataset name to delete.  Falls back to ``self.dataset``.

        Returns:
        -------
        bool
            ``True`` if the dataset was successfully deleted.

        Raises:
        ------
        FusekiError
            If the server rejects the request (e.g. dataset not found → 404).
        """
        ds = self._resolve_dataset(dataset)
        url = f"{self._admin_datasets_endpoint}/{ds}"

        await self._request(
            "DELETE",
            url,
            expected_status=(200, 204),
        )
        return True

    async def set_dataset_state(
        self,
        *,
        dataset: str | None = None,
        online: bool = True,
    ) -> bool:
        """Take a dataset online or offline without deleting it.

        Parameters
        ----------
        dataset:
            Dataset name.  Falls back to ``self.dataset``.
        online:
            ``True`` to bring the dataset online; ``False`` to take it offline.

        Returns:
        -------
        bool
            ``True`` on success.

        Reference: Fuseki supports POST to /$/datasets/{name}?state=active|offline
        """
        ds = self._resolve_dataset(dataset)
        url = f"{self._admin_datasets_endpoint}/{ds}"
        state = "active" if online else "offline"

        await self._request(
            "POST",
            url,
            params={"state": state},
            expected_status=(200,),
        )
        return True

    async def dataset_exists(self, dataset: str | None = None) -> bool:
        """Check whether a dataset exists on the server.

        Parameters
        ----------
        dataset:
            Dataset name.  Falls back to ``self.dataset``.

        Returns:
        -------
        bool
        """
        ds = self._resolve_dataset(dataset)
        url = f"{self._admin_datasets_endpoint}/{ds}"

        try:
            await self._request(
                "GET",
                url,
                expected_status=(200,),
                raise_for_status=False,
            )
            resp, *_ = await self._request(
                "GET",
                url,
                expected_status=(200, 404),
                raise_for_status=False,
            )
            return resp.status == 200
        except FusekiError:
            return False

    # --- Utilities -------------------------------------------------------

    @staticmethod
    def _format_to_mime(format_name: str) -> str:
        mapping = {
            "turtle": "text/turtle",
            "nt": "application/n-triples",
            "xml": "application/rdf+xml",
            "json-ld": "application/ld+json",
        }
        return mapping.get(format_name, format_name)

    # --- Graph store operations (GSP) ------------------------------------

    async def get_graph(self, graph_uri: str, *, format: str = "turtle") -> Graph:
        """Retrieve a named graph as an rdflib.Graph.
        Raises FusekiError on 404 or other failure.
        """
        params = {"graph": graph_uri}
        headers = {"Accept": self._format_to_mime(format)}
        resp, body = await self._request(
            "GET", self.gsp_endpoint(), params=params, headers=headers, expected_status=(200, 404)
        )
        if resp.status == 404:
            raise FusekiError(f"Graph {graph_uri} not found (404).")
        g = Graph()
        g.parse(data=body.decode("utf-8"), format=format)
        return g

    async def graph_exists(self, graph_uri: str) -> bool:
        """Check existence of a named graph. Uses a lightweight ASK SPARQL query to avoid heavy graph transfers."""
        ask = f"ASK {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}"
        result = await self.query_sparql(ask, accept="application/sparql-results+json")
        # expect JSON with boolean field "boolean"
        boolean = result.get("boolean", False)
        return bool(boolean)

    @staticmethod
    def _mime_to_rdflib_format(mime: str) -> str:
        reverse = {
            "text/turtle": "turtle",
            "application/turtle": "turtle",
            "application/n-triples": "nt",
            "application/rdf+xml": "xml",
            "application/ld+json": "json-ld",
        }
        return reverse.get(mime, "turtle")

    async def put_graph(self, graph_uri: str, g: Graph, *, content_type: str | None = None):
        """Replace (PUT) the named graph with the serialization of `g`.
        Uses HTTP PUT to the GSP endpoint with ?graph=<graph_uri>.
        """
        content_type = content_type or self.default_ct
        data = g.serialize(format=self._mime_to_rdflib_format(content_type)).encode("utf-8")
        params = {"graph": graph_uri}
        headers = {"Content-Type": content_type}
        resp, *_ = await self._request(
            "PUT",
            self.gsp_endpoint(),
            params=params,
            headers=headers,
            data=data,
            expected_status=(200, 201, 204),
        )
        return resp.status

    async def post_graph(self, graph_uri: str, g: Graph, *, content_type: str | None = None):
        """Append triples to an existing graph (POST)."""
        content_type = content_type or self.default_ct
        data = g.serialize(format=self._mime_to_rdflib_format(content_type)).encode("utf-8")
        params = {"graph": graph_uri}
        headers = {"Content-Type": content_type}
        resp, *_ = await self._request(
            "POST",
            self.gsp_endpoint(),
            params=params,
            headers=headers,
            data=data,
            expected_status=(200, 201, 204),
        )
        return resp.status

    async def delete_graph(self, graph_uri: str) -> int:
        """Delete a named graph (HTTP DELETE to GSP)."""
        params = {"graph": graph_uri}
        resp, *_ = await self._request(
            "DELETE", self.gsp_endpoint(), params=params, expected_status=(200, 204, 404)
        )
        return resp.status

    # --- SPARQL Query / Update -------------------------------------------

    async def query_sparql(
        self, query: str, *, accept: str = "application/sparql-results+json"
    ) -> dict:
        """Run a SPARQL SELECT/ASK/CONSTRUCT/DESCRIBE query against the query endpoint.
        Returns parsed JSON for SELECT/ASK when accept is json. For other forms, returns a dict with 'raw' key.
        """
        headers = {"Accept": accept}
        data = {"query": query}
        resp, *_ = await self._request(
            "POST", self.sparql_query_endpoint(), data=data, headers=headers, expected_status=(200,)
        )
        text = await resp.text()
        if "application/sparql-results+json" in resp.headers.get("Content-Type", ""):
            import json

            return json.loads(text)
        return {"raw": text, "content_type": resp.headers.get("Content-Type", "")}

    async def update_sparql(self, update: str) -> int:
        """Execute a SPARQL Update (INSERT/DELETE/DROP/CREATE ...). Returns HTTP status."""
        data = {"update": update}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp, *_ = await self._request(
            "POST",
            self.sparql_update_endpoint(),
            data=data,
            headers=headers,
            expected_status=(200, 204),
        )
        return resp.status

    # --- Convenience / higher-level operations ----------------------------

    async def list_named_graphs(self) -> list[str]:
        """Return a list of named graph URIs present in the dataset.
        Uses SPARQL to ask for distinct graphs that contain triples.
        """
        q = """
        SELECT DISTINCT ?g WHERE {
          GRAPH ?g { ?s ?p ?o }
        }
        """
        res = await self.query_sparql(q, accept="application/sparql-results+json")
        bindings = res.get("results", {}).get("bindings", [])
        graphs = [b["g"]["value"] for b in bindings if "g" in b]
        return graphs

    async def replace_graph_atomically(
        self,
        graph_uri: str,
        g: Graph,
        *,
        tmp_graph_uri: str | None = None,
        content_type: str | None = None,
    ):
        """Replace a graph atomically using SPARQL Update:
         1) DELETE WHERE { GRAPH <g> { ?s ?p ?o } } ; (or DROP GRAPH)
         2) INSERT DATA { GRAPH <g> { ... } }

        If graph size is large, it may be better to PUT via GSP (non-atomic on server-side),
        or load to a temporary graph and then do a single DROP + MOVE (if server supports).

        This implementation uses a single SPARQL Update with DELETE/INSERT to preserve atomicity
        on the server (where supported).
        """
        # Serialize triples as N-Triples for safe inline insertion
        nt = (
            g.serialize(format="nt").decode("utf-8")
            if isinstance(g.serialize(format="nt"), bytes)
            else g.serialize(format="nt")
        )
        # Build an INSERT DATA snippet
        # Note: for very large graphs this approach may be inefficient; for very large data, prefer GSP PUT.
        insert_snippets = []
        for line in nt.splitlines():
            if not line.strip():
                continue
            insert_snippets.append(line)
        insert_block = "\n".join(insert_snippets)
        update = f"""
        DROP GRAPH <{graph_uri}>;
        INSERT DATA {{ GRAPH <{graph_uri}> {{ {insert_block} }} }};
        """
        return await self.update_sparql(update)

    # Optional: open/close helpers for non-context usage
    async def open(self):
        if self._session is None:
            self._session = aiohttp.ClientSession(**self._session_kwargs)
        return self

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(**self._session_kwargs)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._session:
            await self._session.close()
            self._session = None
