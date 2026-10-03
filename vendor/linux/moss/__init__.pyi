from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Any,
    ClassVar,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    overload,
)

class MossClient:
    """Semantic search client for vector similarity operations."""

    DEFAULT_MODEL_ID: ClassVar[str]

    def __init__(
        self,
        project_id: str,
        project_key: str,
        *,
        cache_path: Optional[str] = None,
    ) -> None: ...

    async def session(
        self,
        index_name: str,
        model_id: Optional[str] = None,
        *,
        artifact_version: Optional[str] = None,
        manifest_sha256: Optional[str] = None,
    ) -> SessionIndex: ...

    @overload
    async def create_index(
        self,
        name: str,
        docs: List[DocumentInfo],
        model_id: Optional[str] = ...,
        *,
        wait: Literal[True] = ...,
    ) -> MutationResult: ...
    @overload
    async def create_index(
        self,
        name: str,
        docs: List[DocumentInfo],
        model_id: Optional[str] = ...,
        *,
        wait: Literal[False],
    ) -> JobHandle: ...

    async def add_docs(
        self,
        name: str,
        docs: List[DocumentInfo],
        options: Optional[MutationOptions] = None,
    ) -> MutationResult: ...

    async def delete_docs(
        self,
        name: str,
        doc_ids: List[str],
    ) -> MutationResult: ...

    async def get_job_status(self, job_id: str) -> JobStatusResponse: ...

    async def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval_seconds: float = ...,
        timeout_seconds: float = ...,
    ) -> JobStatusResponse: ...

    async def get_index(self, name: str) -> IndexInfo: ...

    async def list_indexes(self) -> List[IndexInfo]: ...

    async def delete_index(self, name: str) -> bool: ...

    async def get_docs(
        self,
        name: str,
        options: Optional[GetDocumentsOptions] = None,
    ) -> List[DocumentInfo]: ...

    async def create_web_source(
        self,
        root_url: str,
        index_name: str,
        *,
        max_pages: Optional[int] = None,
        max_documents: Optional[int] = None,
        max_depth: Optional[int] = None,
        include_paths: Optional[List[str]] = None,
        exclude_paths: Optional[List[str]] = None,
        respect_robots: Optional[bool] = None,
        parse_documents: Optional[bool] = None,
        refresh_cadence: Optional[Literal["daily", "weekly"]] = None,
        model_id: Optional[str] = None,
    ) -> CreateWebSourceResult: ...

    async def list_web_sources(
        self,
        index_name: Optional[str] = None,
    ) -> List[WebSource]: ...

    async def get_web_source(self, source_id: str) -> WebSource: ...

    async def update_web_source(
        self,
        source_id: str,
        *,
        refresh_cadence: Optional[Literal["daily", "weekly", "manual"]] = None,
        root_url: Optional[str] = None,
        include_paths: Optional[List[str]] = None,
        exclude_paths: Optional[List[str]] = None,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
        resync: Optional[bool] = None,
    ) -> UpdateWebSourceResult: ...

    async def resync_web_source(self, source_id: str) -> ResyncWebSourceResult: ...

    async def delete_web_source(self, source_id: str) -> DeleteWebSourceResult: ...

    async def load_index(
        self,
        name: str,
        auto_refresh: bool = False,
        polling_interval_in_seconds: int = 600,
        cache_path: Optional[str] = None,
    ) -> str: ...

    async def unload_index(self, name: str) -> None: ...

    async def load_indexes(
        self,
        names: List[str],
        auto_refresh: bool = False,
        polling_interval_in_seconds: int = 600,
        cache_path: Optional[str] = None,
    ) -> LoadIndexesResult: ...

    async def unload_indexes(self, names: List[str]) -> None: ...

    async def was_served_stale(self, name: str) -> bool: ...

    async def query(
        self,
        name: str,
        query: str,
        options: Optional[QueryOptions] = None,
    ) -> SearchResult:
        """Search a loaded index in memory.

        A blank query with no options.embedding returns no results at every
        alpha and embeds nothing. With an embedding, a blank query ranks by it.
        """
        ...

    async def query_multi_index(
        self,
        names: List[str],
        query: str,
        options: Optional[QueryOptions] = None,
    ) -> SearchResult:
        """Search across multiple loaded indexes; returns the global top_k.

        All indexes must be loaded and share the same embedding model.
        options.alpha works as in query (default 0.8): 1.0 embedding-only,
        0.0 keyword-only, in between hybrid via Reciprocal Rank Fusion.
        Each result doc carries index_name set to its source index.
        A blank query with no options.embedding returns no results.
        """
        ...


class ManageApiError(RuntimeError):
    """HTTP error from POST /v1/manage."""

    status: int
    body: str

    def __init__(self, status: int, body: str) -> None: ...


@dataclass(frozen=True)
class WebSource:
    id: str
    index_name: str
    root_url: str
    max_pages: int
    max_documents: int
    max_depth: int
    respect_robots: bool
    parse_documents: bool
    refresh_cadence: Literal["daily", "weekly", "manual"]
    next_refresh_at: Optional[str]
    last_crawled_at: Optional[str]
    last_page_count: Optional[int]
    last_doc_count: Optional[int]
    status: Literal["idle", "crawling", "failed", "removing"]
    last_error_code: Optional[str]
    include_paths: Optional[List[str]] = None
    exclude_paths: Optional[List[str]] = None
    created_at: Optional[str] = None


@dataclass(frozen=True)
class CreateWebSourceResult(WebSource):
    job_id: str = field(kw_only=True)


@dataclass(frozen=True)
class UpdateWebSourceResult(WebSource):
    job_id: Optional[str] = field(default=None, kw_only=True)


@dataclass(frozen=True)
class ResyncWebSourceResult:
    id: str
    job_id: str
    status: Optional[str] = None
    index_name: Optional[str] = None


@dataclass(frozen=True)
class DeleteWebSourceResult:
    deleted: bool
    id: str
    purge_job_id: Optional[str] = None


class SessionIndex:
    """Local in-session index for real-time indexing and querying."""

    name: str
    doc_count: int

    async def add_docs(
        self,
        docs: List[DocumentInfo],
        options: Optional[MutationOptions] = None,
    ) -> Tuple[int, int]: ...

    async def delete_docs(self, doc_ids: List[str]) -> int: ...

    async def get_docs(
        self,
        options: Optional[GetDocumentsOptions] = None,
    ) -> List[DocumentInfo]: ...

    async def query(
        self,
        query: str,
        options: Optional[QueryOptions] = None,
    ) -> SearchResult:
        """Search the session in memory.

        A blank query with no options.embedding returns no results at every
        alpha and embeds nothing. With an embedding, a blank query ranks by it.
        """
        ...

    async def push_index(self) -> PushIndexResult: ...


class PushIndexResult:
    """Result from SessionIndex.push_index()."""

    job_id: str
    index_name: str
    doc_count: int
    status: str


class MutationResult:
    """Return value from create_index/add_docs/delete_docs."""

    job_id: str
    index_name: str
    doc_count: int


class JobHandle:
    """Returned by create_index(..., wait=False) for an in-flight build."""

    @property
    def job_id(self) -> str: ...
    async def status(self) -> JobStatusResponse: ...
    async def wait(self) -> JobStatusResponse: ...


class MutationOptions:
    """Options for add_docs.

    `upsert` is whether a document replaces a stored one with the same ID.
    `SessionIndex.add_docs` applies it locally and treats `None` as `True`.
    `MossClient.add_docs` sends it only when set, and the cloud service decides how to apply it.
    """

    upsert: Optional[bool]

    def __init__(self, upsert: Optional[bool] = None) -> None: ...


class ParentGrouping:
    """Collapse sibling documents sharing ``parent_field`` into one result per
    unit, assembled in ``order_field`` order (numeric-aware)."""

    parent_field: str
    order_field: str

    def __init__(self, parent_field: str, order_field: str) -> None: ...


class GetDocumentsOptions:
    """Options for ``get_docs`` — deterministic retrieval (no query vector)."""

    doc_ids: Optional[List[str]]
    filter: Optional[Dict[str, Any]]
    sort_by: Optional[str]
    ascending: Optional[bool]
    group_by: Optional[ParentGrouping]

    def __init__(
        self,
        doc_ids: Optional[List[str]] = ...,
        filter: Optional[Dict[str, Any]] = ...,
        sort_by: Optional[str] = ...,
        ascending: Optional[bool] = ...,
        group_by: Optional[ParentGrouping] = ...,
    ) -> None: ...


class JobStatus:
    """Enum-like class for job status values."""

    PENDING_UPLOAD: ClassVar[str]
    UPLOADING: ClassVar[str]
    BUILDING: ClassVar[str]
    COMPLETED: ClassVar[str]
    FAILED: ClassVar[str]

    value: str


class JobPhase:
    """Enum-like class for job phase values."""

    DOWNLOADING: ClassVar[str]
    DESERIALIZING: ClassVar[str]
    GENERATING_EMBEDDINGS: ClassVar[str]
    BUILDING_INDEX: ClassVar[str]
    UPLOADING: ClassVar[str]
    CLEANUP: ClassVar[str]
    WAITING_FOR_PARSER: ClassVar[str]
    PARSING: ClassVar[str]
    PARSING_COMPLETE: ClassVar[str]
    QUEUED: ClassVar[str]

    value: str


class JobProgress:
    """Progress update for a job."""

    job_id: str
    status: JobStatus
    progress: float
    current_phase: Optional[JobPhase]


class JobStatusResponse:
    """Full status response from get_job_status."""

    job_id: str
    status: JobStatus
    progress: float
    current_phase: Optional[JobPhase]
    error: Optional[str]
    created_at: str
    updated_at: str
    completed_at: Optional[str]


class ModelRef:
    id: str
    version: str
    def __init__(self, id: str, version: str) -> None: ...


class QueryResultDocumentInfo:
    id: str
    text: str
    metadata: Optional[Dict[str, str]]
    score: float
    """Relevance to the query from 0 to 1.

    It comes from vector similarity alone, so alpha and rank never change it.
    Results are ordered by hybrid relevance, so a lower result can show a
    higher score. A keyword-only query (alpha 0, or an index without vectors)
    scores every hit 0. Scores depend on the embedding model: tune min_score
    on your own queries.
    """
    index_name: Optional[str]
    payload: Optional[str]
    def __init__(
        self,
        id: str,
        text: str,
        metadata: Optional[Dict[str, str]] = ...,
        score: float = ...,
        index_name: Optional[str] = ...,
        payload: Optional[str] = ...,
    ) -> None: ...


class DocumentInfo:
    id: str
    text: str
    metadata: Optional[Dict[str, str]]
    embedding: Optional[Sequence[float]]
    payload: Optional[str]
    def __init__(
        self,
        id: str,
        text: str,
        metadata: Optional[Dict[str, str]] = ...,
        embedding: Optional[Sequence[float]] = ...,
        payload: Optional[str] = ...,
    ) -> None: ...


class QueryOptions:
    embedding: Optional[Sequence[float]]
    """Query vector. At every alpha its components must be finite and its length the index dimension."""
    top_k: Optional[int]
    """Most results to return (5 by default, 10 for query_multi_index); 0 returns none."""
    alpha: Optional[float]
    filter: Optional[Dict[str, Any]]
    group_by: Optional[ParentGrouping]
    min_score: Optional[float]
    """Drops results whose score is below this floor, from 0 to 1.

    A query returns up to top_k results that clear it, in hybrid order.
    Not allowed on keyword-only queries (alpha 0).
    """
    candidate_depth: Optional[int]
    """How many hits a hybrid query ranks on each signal before fusion.

    A hit outside both lists is never returned, so a deeper list raises recall
    and query time. Defaults to 2 * top_k. A set value must be at least 1 and is
    raised to top_k when below it. Keyword-only and vector-only queries (alpha 0
    or 1) ignore it. Used by MossClient.query and query_multi_index.
    SessionIndex.query ignores it.
    """
    def __init__(
        self,
        embedding: Optional[Sequence[float]] = ...,
        top_k: Optional[int] = ...,
        alpha: Optional[float] = ...,
        filter: Optional[Dict[str, Any]] = ...,
        group_by: Optional[ParentGrouping] = ...,
        min_score: Optional[float] = ...,
        candidate_depth: Optional[int] = ...,
    ) -> None: ...


class IndexInfo:
    id: str
    name: str
    version: str
    status: str
    doc_count: int
    created_at: str
    updated_at: str
    model: ModelRef
    def __init__(
        self,
        id: str,
        name: str,
        version: str,
        status: str,
        doc_count: int,
        created_at: str,
        updated_at: str,
        model: ModelRef,
    ) -> None: ...


class SearchResult:
    docs: List[QueryResultDocumentInfo]
    query: str
    index_name: Optional[str]
    time_taken_ms: Optional[int]
    def __init__(
        self,
        docs: List[QueryResultDocumentInfo],
        query: str,
        index_name: Optional[str] = None,
        time_taken_ms: Optional[int] = None,
    ) -> None: ...


class IndexStatus:
    NotStarted: ClassVar[str]
    Building: ClassVar[str]
    Ready: ClassVar[str]
    Failed: ClassVar[str]
    def __init__(self, value: str) -> None: ...


class LoadIndexesResult:
    """Outcome of a load_indexes call. Best-effort: indexes that succeed are
    retained even if others fail."""

    loaded: List[str]
    failed: Dict[str, str]
    def __init__(
        self,
        loaded: Optional[List[str]] = None,
        failed: Optional[Dict[str, str]] = None,
    ) -> None: ...


IndexStatusValues: Dict[str, str]

__version__: str

__all__ = [
    "MossClient",
    "SessionIndex",
    "JobHandle",
    "PushIndexResult",
    "DocumentInfo",
    "GetDocumentsOptions",
    "IndexInfo",
    "SearchResult",
    "QueryResultDocumentInfo",
    "ModelRef",
    "IndexStatus",
    "IndexStatusValues",
    "QueryOptions",
    "LoadIndexesResult",
    "MutationResult",
    "MutationOptions",
    "JobStatus",
    "JobPhase",
    "JobProgress",
    "JobStatusResponse",
    "ManageApiError",
    "WebSource",
    "CreateWebSourceResult",
    "UpdateWebSourceResult",
    "ResyncWebSourceResult",
    "DeleteWebSourceResult",
]
