# Lumina Stream Studios — Glean Enterprise Chatbot

A prototype internal chatbot for **Lumina Stream Studios** that indexes internal company documents into Glean and exposes a grounded Q&A workflow through the Glean Indexing, Search, and Chat APIs. The chatbot is exposed as a single **MCP tool** for use in Claude Desktop.

---

## Architecture

```
docs/               ← Markdown files (simulated internal docs)
  └─ *.md

src/
  indexer.py        ← Glean Indexing API: pushes docs into a custom datasource
  chatbot.py        ← Glean Search + Chat APIs: retrieves context, generates answer
  mcp_server.py     ← MCP server: exposes ask_lumina tool to Claude Desktop

.env                ← API tokens + config (not committed)
requirements.txt
```

### Data flow

```
User question
     │
     ▼
[Glean Search API]  ← finds relevant document snippets from indexed datasource
     │
     ▼ search results (title, URL, snippet)
     │
[Glean Chat API]    ← receives question + retrieved context, generates grounded answer
     │
     ▼
Answer + source citations → returned to MCP client (Claude Desktop)
```

---

## Setup

### Prerequisites
- Python 3.10+
- Claude Desktop (for MCP integration)

### 1. Install dependencies

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Required variables:

| Variable | Description |
|---|---|
| `GLEAN_INSTANCE` | Your Glean instance name (e.g. `support-lab`) |
| `GLEAN_INDEXING_TOKEN` | Glean Indexing API token |
| `GLEAN_CLIENT_TOKEN` | Glean Client API token (Chat + Search scope) |
| `GLEAN_DATASOURCE` | Custom datasource name (e.g. `interviewds`) |
| `GLEAN_ACT_AS` | Email to impersonate for user-scoped API calls |

### 3. Index documents

```bash
python src/indexer.py
```

Documents typically become searchable within **15–20 minutes** after indexing.

### 4. Test the chatbot directly

```bash
python src/chatbot.py "What is the parental leave policy?"
python src/chatbot.py "How do I request access to Box?"
python src/chatbot.py "What is the VFX shot review process?"
```

---

## MCP Tool: Claude Desktop Integration

### Configure Claude Desktop

Add the following to your Claude Desktop config file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "lumina-chatbot": {
      "command": "/absolute/path/to/glean-chatbot/.venv/bin/python",
      "args": ["/absolute/path/to/glean-chatbot/src/mcp_server.py"]
    }
  }
}
```

Replace `/absolute/path/to/glean-chatbot` with the actual path on your machine.

Restart Claude Desktop after saving the config.

### Using the tool

Once connected, ask Claude Desktop:

> "Use the ask_lumina tool to find out what Lumina's parental leave policy is."

Or Claude will automatically invoke it for questions about Lumina Stream Studios.

### Tool parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `question` | string | required | Natural-language question |
| `datasource` | string | `interviewds` | Glean datasource to search |
| `top_k` | int | `5` | Number of search results to retrieve |
| `include_citations` | bool | `true` | Whether to include source references |

---

## Document Set

The `docs/` folder contains 7 fictional internal documents for Lumina Stream Studios:

| File | Topic |
|---|---|
| `employee-onboarding.md` | New hire checklist, benefits, tools, expenses |
| `production-workflow.md` | Google Drive structure, script versioning, scheduling |
| `legal-contracts-policy.md` | Box, contract initiation, talent buyout process |
| `post-production-vfx-workflow.md` | Jira/Confluence, editorial flow, VFX pipeline |
| `it-security-policy.md` | Okta SSO, MFA, device security, data classification |
| `international-coproduction-guidelines.md` | Treaty co-pros, finance, partner data sharing |
| `content-delivery-standards.md` | Lumina+ specs, broadcast formats, QC, DRM |

---

## Assumptions

- **Datasource is pre-configured**: The sandbox datasource (`interviewds`) was already registered in Glean with a fixed `urlRegex`. Documents must have view URLs matching that pattern. In a real deployment, you would call `/adddatasource` first with the correct URL regex for your source system.
- **Indexing is incremental**: This prototype uses `/indexdocuments` (incremental) rather than `/bulkindexdocuments` (full replacement) so that re-running the indexer only updates changed documents.
- **Global token with X-Glean-ActAs**: The Client API token is Global-scoped, so all Search/Chat requests impersonate a sandbox user via the `X-Glean-ActAs` header. In production, user-scoped tokens ensure per-user permission enforcement.
- **Context injection**: Search results are explicitly injected into the Chat prompt. In production, Glean Chat can retrieve context natively from the full index, making the explicit Search step optional but useful for datasource scoping.
- **No streaming**: The Chat API response is collected in full before returning. Streaming (`/chat` with `stream: true`) would improve perceived latency in a production UI.

---

## Limitations

- **15–20 minute indexing lag**: Documents are not immediately searchable after indexing.
- **Single datasource**: The tool currently scopes search to one datasource. A production system would search across all connected datasources.
- **Query specificity affects grounding**: Generic queries (e.g. "what is parental leave?") may surface results from Glean's broader index rather than the custom datasource, even with `datasourcesFilter` set. Including the company name in the query (e.g. "what is Lumina's parental leave policy?") reliably returns indexed documents. A production fix would hard-filter search to the custom datasource only, removing the fallback to the global index entirely.
- **No conversation memory**: Each `ask_lumina` call is stateless. The Chat API supports multi-turn conversations via `chatId`, which this prototype does not implement.
- **No permission enforcement**: All documents are indexed with `allowAllDatasourceUsersAccess: true`. Real deployments need per-document ACLs synced from the source system.

---

## Design Note

### How the Glean APIs are used

**Glean Indexing API** (`POST /api/index/v1/indexdocuments`)

Authenticated with the Indexing API token. `indexer.py` reads each markdown file from `docs/`, constructs a document payload with a stable ID, title, plain-text body, view URL, and open permissions, then pushes the batch to Glean. Incremental indexing (`/indexdocuments`) is used rather than bulk replacement (`/bulkindexdocuments`) so re-running only updates changed documents without deleting the rest.

Key choices:
- `objectType: "Document"` — a generic type that works for all policy docs; in production you'd define specific types (e.g. `PolicyDocument`, `RunbookPage`) per content category.
- `allowAllDatasourceUsersAccess: true` — sandbox shortcut. Production deployments would sync per-document ACLs from the source system (Google Drive sharing, Box permissions).
- View URLs must match the datasource's pre-configured `urlRegex`. The sandbox datasource requires `https://internal.example.com/policies/...`.

**Glean Search API** (`POST /rest/api/v1/search`)

Authenticated with the Client API token via the official `glean-api-client` Python library. Before querying, the user's natural-language question is reduced to discriminative keywords (stop words removed, punctuation stripped) per Glean's MCP guideline that the search engine is keyword-based, not semantic. Results are scoped to the target datasource using `SearchRequestOptions(datasources_filter=[datasource])` and further post-filtered to an exact URL allowlist to exclude other candidates' documents in the shared sandbox.

**Glean Chat API** (`POST /rest/api/v1/chat`)

Also via the official client. Retrieved document snippets are injected into the Chat prompt alongside an explicit anti-hallucination instruction: *"Answer using ONLY the provided documents. If the answer is not there, say so."* The prompt follows the Glean MCP read-document pattern — Glean's search snippet (the most relevant excerpt) is always included first, with additional document context appended up to a character cap. This ensures the key passage is never lost to truncation.

---

### End-to-end flow

```
1. INGEST (one-time / on update)
   docs/*.md
     → indexer.py extracts title, body, stable ID
     → POST /api/index/v1/indexdocuments
     → Glean indexes async (~15–20 min propagation)

2. QUERY (per ask_lumina invocation)
   User question
     → keyword extraction (strip stop words & punctuation)
     → POST /rest/api/v1/search  (datasourcesFilter + URL allowlist)
     → top-k results (title, URL, snippet)
     → enrich with full local document content (read_document pattern)
     → build grounded Chat prompt (snippet-first + additional context)
     → POST /rest/api/v1/chat  (25s timeout, snippet fallback on slow response)
     → extract answer text from response.messages[-1].fragments
     → return: { answer, sources: [{index, title, url}] }

3. MCP TOOL
   Claude Desktop → ask_lumina(question, ...) → step 2 → answer + Sources list
```

---

### Key tradeoffs

| Decision | Choice | Rationale |
|---|---|---|
| Indexing mode | Incremental (`/indexdocuments`) | Safer for re-runs; bulk deletes all unincluded docs |
| Search client | Official `glean-api-client` | Correct `datasourcesFilter` handling; handles auth/retries |
| Context injection | Explicit (inject results into Chat prompt) | Scopes Chat to our datasource; prevents answers from unindexed content |
| Datasource filter | `datasourcesFilter` + exact URL allowlist | Shared sandbox requires allowlist; prefix matching alone was not exclusive |
| Chat timeout | 25s with snippet fallback | Sandbox Chat is slow; fallback ensures the tool always returns grounded content |
| Auth | Global token + `X-Glean-ActAs` | Simpler for a single-service demo; user-scoped tokens are preferred in production |
| Conversation model | Stateless (single-turn) | Scope; multi-turn via `chatId` is the obvious next step for production |

---

## Validation & Testing

`validate.py` runs 5 end-to-end test cases against the live Glean pipeline and reports pass/fail with timing:

```bash
python validate.py
```

Each test case submits a question, checks that:
1. A non-empty answer is returned
2. At least one source is cited
3. The source titles match expected Lumina document keywords

All API calls emit structured log lines at INFO level, including the Glean `requestId` and `backendTimeMillis` for each Search and Chat request — useful for correlating slow responses against Glean's own telemetry.

Example output:
```
[1/5] HR / benefits lookup
  Q: What is Lumina Stream Studios parental leave policy?
  ✓ PASS (14.5s)
    Sources: Employee Onboarding Guide, IT Security & Access Control Policy
    Answer preview: Lumina's parental leave policy provides 16 weeks fully paid...
```

---

## What I'd Do Next (Production Path)

1. **Expand document ingestion beyond Markdown**  
   `indexer.py` currently only reads `.md` files. A production ingestion pipeline should handle any file type employees actually use — `.pdf`, `.docx`, `.pptx`, `.txt`, and `.html` at minimum. Each format needs a parser to extract clean plain text before indexing (e.g. `pdfplumber` for PDFs, `python-docx` for Word files, `python-pptx` for decks). The indexer would detect file extension, route to the appropriate parser, and fall back to raw text extraction for unknown types. This also opens the door to watching a shared Drive folder or Box directory and re-indexing on file change events.

2. **Sync permissions from source systems**  
   Replace `allowAllDatasourceUsersAccess: true` with per-document ACLs pulled from the source system at index time — Google Drive sharing settings, Box collaborator lists, Confluence space permissions. The Indexing API supports `allowedUsers`, `allowedGroups`, and `denyUsers` fields on each document. Combined with `X-Glean-ActAs` set to the logged-in user's email on every Search/Chat request, this ensures Glean enforces the same access controls the source system would.

3. **Multi-turn conversation**  
   Use the Chat API's `chatId` field to maintain session context across follow-up questions. The first response returns a `chatId`; subsequent requests include it so Glean Chat can reference earlier turns. The MCP tool would accept an optional `chat_id` parameter and return the new `chatId` alongside the answer.

4. **Streaming responses**  
   Switch to `POST /rest/api/v1/chat` with `stream: true` for real-time token delivery. Users would see the answer building word by word rather than waiting 10–20 seconds for nothing. The `glean-api-client` supports this via `client.client.chat.create_stream()`. For the MCP tool this requires restructuring the return to emit progressive updates rather than a single string.

5. **Observability with OpenTelemetry**  
   Instrument the pipeline with the [OpenTelemetry Python SDK](https://opentelemetry.io/docs/languages/python/) to emit traces and metrics to any compatible backend (Datadog, Honeycomb, Grafana Tempo, etc.):

   ```python
   from opentelemetry import trace
   from opentelemetry.sdk.trace import TracerProvider
   from opentelemetry.sdk.trace.export import BatchSpanProcessor
   from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

   tracer = trace.get_tracer("lumina-chatbot")

   with tracer.start_as_current_span("ask_lumina") as span:
       span.set_attribute("question", question)
       span.set_attribute("datasource", datasource)
       span.set_attribute("fast_mode", fast_mode)
       # ... pipeline runs ...
       span.set_attribute("search.results_returned", len(results))
       span.set_attribute("search.results_after_filter", len(filtered))
       span.set_attribute("chat.timed_out", timed_out)
       span.set_attribute("answer.length_chars", len(answer))
   ```

   Key spans to instrument: `search`, `enrich`, `chat`, and `ask_lumina` (parent). Key attributes per span: `glean.request_id`, `glean.backend_time_ms`, result counts, and whether the Chat fallback was triggered.

   **Metrics to expose** (via `opentelemetry-sdk-metrics`):
   - `chatbot.search.latency_ms` — histogram
   - `chatbot.chat.latency_ms` — histogram
   - `chatbot.chat.timeout_rate` — counter
   - `chatbot.search.zero_result_rate` — counter
   - `chatbot.requests.total` — counter by `datasource`, `fast_mode`

   **Alerts**: P99 total latency > 15s, zero-result rate > 10% (signals indexing gap), Chat timeout rate > 20%.

6. **Token usage tracking for cost optimisation**  
   The Glean Chat API returns token usage metadata in the response. Capture and log it on every call:

   ```python
   # After chat.create() returns:
   usage = getattr(response, "usage", None)
   if usage:
       logger.info("Chat token usage — prompt: %d, completion: %d, total: %d",
                   usage.prompt_tokens, usage.completion_tokens, usage.total_tokens)
       span.set_attribute("llm.prompt_tokens", usage.prompt_tokens)
       span.set_attribute("llm.completion_tokens", usage.completion_tokens)
   ```

   Aggregate token counts per `datasource`, `top_k`, and `fast_mode` to answer: which query patterns are most expensive? Does increasing `top_k` from 3 to 5 meaningfully improve answer quality relative to the token cost increase? Is `fast_mode` (zero Chat tokens) a worthwhile default for simple lookups?

   In production, route this data to a cost dashboard alongside Glean's own usage reporting to track spend per team, per feature, and over time.

7. **Scheduled re-indexing**  
   Run `indexer.py` on a cron schedule (or triggered by file change webhooks from Google Drive/Box) to keep the Glean index current with the latest document versions.

8. **Multi-datasource search**  
   Remove the datasource filter to enable cross-system search — Drive scripts, Box contracts, Slack threads, and Jira tickets — in a single query, returning the most relevant result regardless of source.
