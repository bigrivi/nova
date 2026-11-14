"""Server-side request, response, and streaming event schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from nova.llm.images import MAX_IMAGE_BYTES, image_size_bytes


class AttachmentData(BaseModel):
    """One client attachment: an image, or a document folded into the prompt."""

    id: str
    type: str
    name: str
    content_type: str | None = None
    content: list[dict[str, Any]]

    @model_validator(mode="after")
    def _images_are_usable(self) -> AttachmentData:
        for part in self.content:
            if part.get("type") != "image":
                continue
            ref = part.get("image")
            if not isinstance(ref, str) or not ref.strip():
                raise ValueError("image attachment is missing its data")
            size = image_size_bytes(ref)
            if size > MAX_IMAGE_BYTES:
                raise ValueError(
                    f"image attachment is {size} bytes, limit is {MAX_IMAGE_BYTES}"
                )
        return self


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    provider: str | None = None
    model: str | None = None
    # Reasoning level for this turn. Validated against what the model accepts
    # server-side; an unknown level is dropped rather than forwarded.
    reasoning_effort: str | None = None
    agent_key: str = Field(default="main")
    workspace_dir: str | None = None
    project_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    attachments: list[AttachmentData] = Field(default_factory=list)
    # What the client showed the user; `message` may carry prompt decoration
    # (`Attached file:` lines, inlined documents) that the transcript hides.
    display_text: str | None = None
    # Optional permission-mode override for this turn ("ask", "dontAsk",
    # "acceptEdits"). None keeps the previous behaviour: build_agent reads the
    # permissions file. Headless runs (scheduled jobs) pass "dontAsk" so a tool
    # that would wait for approval is refused instead of hanging a turn nobody
    # is watching.
    permission_mode: str | None = None
    # SSE resume cursor: replay buffered frames after this sequence number, then
    # live-tail while the stream is in flight. None = start a new turn.
    # Unknown cursors replay the full in-flight buffer with resync
    # (signalled via the x-nova-stream-resync header), never a skip.
    resume_from_seq: int | None = None
    # Re-run the last assistant answer instead of appending `message` as a new
    # user turn. Only the /regenerate route sets this; clients keep using the
    # normal chat frames.
    regenerate: bool = False


class RegenerateRequest(BaseModel):
    """Re-run the last assistant answer without appending a user message."""

    provider: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    permission_mode: str | None = None


class ChatResponse(BaseModel):
    session_id: str | None = None
    status: Literal["completed", "cancelled", "input_required", "error"]
    message: str = ""


class SessionSummary(BaseModel):
    id: str
    title: str | None = None
    updated_at: int
    agent_key: str = Field(default="main")
    workspace_dir: str | None = None
    pinned: bool = False
    project_id: str | None = None
    #: Set on a copy: the session it was forked from, so a client can nest it.
    forked_from: str | None = None
    fork_point_message_id: str | None = None


class SessionListResponse(BaseModel):
    items: list[SessionSummary]


class RenameSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class UpdateSessionWorkspaceRequest(BaseModel):
    workspace_dir: str | None = None


class UpdateSessionPinnedRequest(BaseModel):
    pinned: bool


class DirectoryEntry(BaseModel):
    name: str
    path: str


class DirectoryListing(BaseModel):
    path: str
    parent: str | None = None
    entries: list[DirectoryEntry]


class GitCommitRequest(BaseModel):
    """Paths come from the plan, so the UI cannot commit something unseen."""

    session_id: str
    message: str
    paths: list[str]


class GitReviewRequest(BaseModel):
    session_id: str


class ForkSessionRequest(BaseModel):
    """Where to cut the copy; both optional, both default to "all of it"."""

    message_id: str | None = None
    title: str | None = None


class SessionActionResponse(BaseModel):
    status: str
    session_id: str


class ProjectRecord(BaseModel):
    id: str
    name: str
    path: str | None = None
    created_at: int
    updated_at: int


class ProjectListResponse(BaseModel):
    items: list[ProjectRecord]


class ProjectCreateRequest(BaseModel):
    name: str | None = None
    path: str | None = None


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    path: str | None = None


class ResolveProjectRequest(BaseModel):
    path: str
    name: str | None = None


class ProjectActionResponse(BaseModel):
    status: str
    project_id: str


class UpdateSessionProjectRequest(BaseModel):
    project_id: str | None = None


class MemoryRecordSchema(BaseModel):
    id: str
    key: str
    scope: str
    memory_type: str
    summary: str
    content: str
    tags: list[str] = Field(default_factory=list)
    session_id: str | None = None
    created_at: int
    updated_at: int


class MemoryListResponse(BaseModel):
    items: list[MemoryRecordSchema]


class MemoryActionResponse(BaseModel):
    status: str
    memory_id: str


class MessageEditRequest(BaseModel):
    """A question being replaced by an edited one."""

    text: str
    force: bool = False


class MessageRecord(BaseModel):
    id: str
    session_id: str
    role: str
    content: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    time_created: int
    images: list[str] | None = None
    reasoning_content: str | None = None
    reasoning_elapsed_ms: int | None = None
    # Prompt size and how much of it the provider served from cache. Both are
    # None when the provider reports neither, so a client can tell "unknown"
    # from "nothing was cached".
    tokens_input: int | None = None
    cache_read_tokens: int | None = None
    group_id: str | None = None
    error: str | None = None
    variant: str | None = None
    # Text a UI should render instead of `content`; None means "same as content".
    display_text: str | None = None


class MessageListResponse(BaseModel):
    items: list[MessageRecord]


class ModelRecord(BaseModel):
    id: str
    provider: str
    provider_name: str
    model: str
    label: str
    tools: bool = False
    # Reasoning levels this model accepts, empty when it has none. The UI offers
    # exactly these and nothing when the list is empty.
    efforts: list[str] = []
    # The context window Nova will plan against, and nothing when no source
    # stated one: config, then what the provider said, then models.dev, then
    # the built-in family table.
    context: int | None = None


class ModelListResponse(BaseModel):
    items: list[ModelRecord]
    #: Set when a provider was connected but its models could not be discovered.
    #: The provider still exists; only the catalogue is missing.
    warning: str | None = None


class ProviderRecord(BaseModel):
    key: str
    name: str
    type: str
    base_url: str = ""
    has_api_key: bool = False
    #: A key Nova stores for the machine, in credentials.json. A provider whose
    #: key sits in config.json is a hand-authored one, and the UI treats the two
    #: differently: only this is "connected".
    authenticated: bool = False


class ProviderListResponse(BaseModel):
    items: list[ProviderRecord]


class ProviderPresetRecord(BaseModel):
    """A vendor the add-provider form can fill in for the user."""

    id: str
    label: str
    type: str
    base_url: str = ""
    key_env: str | None = None
    note: str = ""
    #: True for an endpoint the user declared themselves: the form must ask for
    #: the base URL, and nothing polls it for a model list.
    custom: bool = False


class ProviderPresetListResponse(BaseModel):
    items: list[ProviderPresetRecord]


class ProviderSyncResponse(BaseModel):
    """Result of re-reading every provider's catalogue in one pass."""

    synced: list[str] = []
    failed: dict[str, str] = {}


class AvailableModelListResponse(BaseModel):
    """What a provider says it serves, asked for by a form rather than cached."""

    provider: str
    items: list[str]


class ProviderCreateRequest(BaseModel):
    key: str
    type: str
    name: str = ""
    base_url: str = ""
    api_key: str = ""
    #: Extra provider options — headers, a request hook, a client identity for a
    #: gateway that fingerprints them. Anything here makes the connection an
    #: explicit config entry rather than a key with preset-supplied transport.
    options: dict[str, Any] = {}
    #: The endpoint is the caller's own, not a vendor Nova knows how to poll.
    custom: bool = False


class AgentCreateRequest(BaseModel):
    key: str
    name: str
    description: str = ""
    model: str
    provider: str
    tools: list[str] | None = None
    workspace_dir: str | None = None
    parent_ids: list[str] | None = None


class ModelCreateRequest(BaseModel):
    provider: str
    model: str
    label: str = ""
    tools: bool = True


class ProviderUpdateRequest(BaseModel):
    key: str
    name: str | None = None
    type: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class ProviderDeleteRequest(BaseModel):
    key: str


class UpdateSessionRouteRequest(BaseModel):
    # Written as one unit: an effort only means something next to its model.
    # The write replaces the whole route, so a body naming a level without a
    # model would record an effort belonging to nothing; rejecting it here
    # keeps every reachable session state one a model can actually run.
    provider: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None

    @model_validator(mode="after")
    def _effort_needs_a_model(self) -> UpdateSessionRouteRequest:
        if self.reasoning_effort is not None and not self.model:
            raise ValueError("reasoning_effort requires a model")
        return self


class SessionRouteResponse(BaseModel):
    provider: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None


class ModelUpdateRequest(BaseModel):
    provider: str
    model: str
    label: str | None = None
    tools: bool | None = None


class ModelDeleteRequest(BaseModel):
    provider: str
    model: str


class McpKeyValue(BaseModel):
    """One env var or header, as a name and a value.

    A list of pairs rather than a map so the form can hold a half-typed row
    (a key with no value yet) without it becoming a key named "" -- and so the
    order the user entered them in survives the round trip.
    """

    key: str
    value: str = ""


class McpSkippedTool(BaseModel):
    """A tool the server advertised that the agent cannot reach, and why."""

    tool: str
    reason: str


class McpServerRecord(BaseModel):
    """A configured server as the UI lists it, with secret values withheld.

    ``env`` and ``headers`` carry credential values, so the list returns their
    names only -- the same choice the provider list makes for ``api_key``. To
    change a value the form re-enters it; to see one, read the config file. The
    client already runs with the config owner's trust, but a value never has to
    cross the wire to render the list, so it does not.

    ``loaded_tools`` and ``skipped_tools`` describe what an agent can actually
    call, under the namespaced names the model sees. Both are None rather than
    empty until a toolset has been built, because "nothing loaded yet" and "the
    server offers nothing" are different facts and only one of them is a problem.

    ``error`` is set when the server could not be connected at all. A server that
    fails silently is the worst case: its tools simply stop existing and the user
    has no symptom to chase, only a tool that used to work and does not.
    """

    name: str
    transport: str  # "stdio" | "http"
    command: str = ""
    args: list[str] = []
    url: str = ""
    env_keys: list[str] = []
    header_keys: list[str] = []
    loaded_tools: list[str] | None = None
    skipped_tools: list[McpSkippedTool] | None = None
    error: str | None = None


class McpServerListResponse(BaseModel):
    items: list[McpServerRecord]


class McpServerCreateRequest(BaseModel):
    name: str
    command: str = ""
    args: list[str] = []
    env: list[McpKeyValue] = []
    url: str = ""
    headers: list[McpKeyValue] = []


class McpServerUpdateRequest(McpServerCreateRequest):
    # The name under which the server is currently stored. ``name`` on the base
    # is the new name, so a rename is one request.
    original_name: str


class McpServerDeleteRequest(BaseModel):
    name: str


class McpTestRequest(McpServerCreateRequest):
    """The same shape a create carries: a test connects the config as given."""


class McpTestResponse(BaseModel):
    ok: bool
    server_name: str = ""
    server_version: str = ""
    tool_count: int = 0
    tool_names: list[str] = []
    error: str = ""


class InterruptRequest(BaseModel):
    session_id: str


class InterruptResponse(BaseModel):
    session_id: str
    interrupted: bool


class BackgroundTaskCancelRequest(BaseModel):
    session_id: str


class ApproveRequest(BaseModel):
    request_id: str
    approved: bool
    remember: bool = False


class PermissionRuleRecord(BaseModel):
    """One user rule from the `shell.ask` list: a regex and why it is asked."""

    description: str
    match: str


class ToolEffectRecord(BaseModel):
    """One entry of the `tools` map, e.g. ``write`` -> ``ask``."""

    name: str
    effect: str


class SavedGrantRecord(BaseModel):
    """One approval the user chose to keep, for this workspace only."""

    rule: str
    family: str = ""
    digest: str = ""
    created_at: int = 0


class PermissionPolicy(BaseModel):
    """The mode and rules a tool call is judged by, as configured on disk."""

    mode: str
    path: str
    #: False when the file is absent, so a client can say "built-in defaults"
    #: instead of showing an empty rule list that looks like "nothing is asked".
    configured: bool
    block_reads_outside_workspace: bool
    shell_allow: list[str] = Field(default_factory=list)
    shell_ask: list[PermissionRuleRecord] = Field(default_factory=list)
    shell_disable: list[str] = Field(default_factory=list)
    tools: list[ToolEffectRecord] = Field(default_factory=list)
    #: Remembered approvals for the workspace the caller asked about.
    saved_grants: list[SavedGrantRecord] = Field(default_factory=list)
