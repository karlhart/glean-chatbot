# Glean Solutions Architect — Interview Study Guide
**Candidate**: Karl Hart | **Project**: Lumina Stream Studios Internal Chatbot
*Updated to reflect the final implementation, including all fixes and changes made during development.*

---

## What This Guide Covers

- Complete walkthrough of every file and design decision in the final codebase
- Anticipated interview Q&A for Part 1 (take-home) and Part 2 (live session)
- Deep dives: Glean APIs, MCP protocol, RAG architecture
- Real troubleshooting history — what broke, why, and how it was fixed
- Productionization discussion: permissions, scaling, observability
- Prepared answers for live coding changes

---

## 1. Exercise Overview

**Part 1 – Take-Home (Done ✓)**

Build an enterprise chatbot using:
- Glean Indexing API
- Glean Search API
- Glean Chat API
- MCP tool wrapper

**Part 2 – Live Session (90 min)**

Three parts:
1. Walkthrough & Demo
2. Collaborative design discussion (productionise)
3. Live coding change

**Key interviewer mindset**: They care about reasoning, not perfection. They want to see how you think, communicate, and adapt. Be explicit about assumptions and tradeoffs — that *is* the job of an SA. Also, you must use agentic coding tools (Claude Code in this case) and be able to explain every decision.

---

## 2. Architecture & Data Flow

### 2.1 High-Level Architecture

The chatbot implements a Retrieval-Augmented Generation (RAG) pipeline on top of Glean's managed infrastructure:

```
User Question
      │
      ▼
┌──────────────────────────────────────────────────────────┐
│  MCP Tool: ask_lumina  (mcp_server.py)                   │
│  ┌────────────────────────────────────────────────────┐  │
│  │  ask() function  (chatbot.py)                      │  │
│  │                                                    │  │
│  │  Step 1: _extract_keywords()                       │  │
│  │    strip stop words + punctuation from question    │  │
│  │                                                    │  │
│  │  Step 2: search() → Glean Search API               │  │
│  │    returnLlmContentOverSnippets=True (4000 chars)  │  │
│  │    SearchRequestOptions(datasources_filter=[...])  │  │
│  │    + URL allowlist post-filter                     │  │
│  │    → top-K results with full LLM document content  │  │
│  │                                                    │  │
│  │  Step 3: chat() → Glean Chat API                   │  │
│  │    anti-hallucination prompt + injected content    │  │
│  │    25s timeout; snippet fallback if slow           │  │
│  │    → grounded answer with [Source N: Title] cites  │  │
│  │                                                    │  │
│  │  Step 4: format sources list                       │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
      │
      ▼
Answer + Sources (with [1], [2] citations)
```

### 2.2 File Structure

```
glean-chatbot/
├── src/
│   ├── chatbot.py        Core RAG pipeline (Search → Enrich → Chat)
│   ├── indexer.py        Glean Indexing API — push docs into datasource
│   └── mcp_server.py     FastMCP server — exposes ask_lumina tool
├── docs/                 7 Lumina Stream Studios markdown documents
├── validate.py           End-to-end test suite (5 scenarios, live API)
├── .env / .env.example   API tokens and config
├── requirements.txt      glean-api-client, python-dotenv, mcp
├── FIXES.md              Chronological troubleshooting log (11 fixes)
└── DESIGN.md             1-page design note for submission
```

### 2.3 Glean API Tokens

| Token | Env Var | Used For |
|---|---|---|
| Indexing token | `GLEAN_INDEXING_TOKEN` | Push documents into the datasource via `/api/index/v1/indexdocuments` |
| Client token | `GLEAN_CLIENT_TOKEN` | Search + Chat via the official `glean-api-client` Python library |

**Why two tokens?** Indexing is a write operation (modifies Glean's index) and uses a separate, privileged Indexing token. Search and Chat are read operations, using the Client token. Keeping them separate follows least-privilege.

**X-Glean-ActAs**: The Client token is Global-scoped, meaning it bypasses user-level permissions by default. Setting `X-Glean-ActAs: alex@glean-sandbox.com` tells Glean to enforce document permissions as if that user made the request. In production this would be the logged-in employee's email set dynamically.

---

## 3. File-by-File Code Walkthrough

### 3.1 `src/chatbot.py` — Core Pipeline

This is the heart of the application. Here are all the components in order:

#### Constants and config (top of file)

```python
INSTANCE = _require_env("GLEAN_INSTANCE")       # e.g. "support-lab"
CLIENT_TOKEN = _require_env("GLEAN_CLIENT_TOKEN") # for Search + Chat
DATASOURCE = os.environ.get("GLEAN_DATASOURCE", "interviewds")
ACT_AS = os.environ.get("GLEAN_ACT_AS", "")
SERVER_URL = f"https://{INSTANCE}-be.glean.com"
INTRANET_BASE = "https://internal.example.com/policies"
MAX_CONTEXT_RESULTS = 5       # Glean recommends 3–5 results for Chat
MAX_SNIPPET_SIZE = 4000       # chars of LLM content per doc (API max: 10,000)
```

`_require_env()` validates at startup and raises a clear `EnvironmentError` rather than a cryptic `KeyError` mid-request.

`KNOWN_URLS` is the exact allowlist of the 7 document URLs we indexed:
```python
KNOWN_URLS = {
    f"{INTRANET_BASE}/{stem}"
    for stem in ["content-delivery-standards", "employee-onboarding", ...]
}
```
This is critical — the sandbox `interviewds` datasource is shared across all interview candidates. At least one other candidate indexed documents using the same URL prefix, so prefix matching alone is not exclusive. An exact allowlist is the only reliable guard.

#### `_glean_client(timeout_ms=30000)`

```python
def _glean_client(timeout_ms: int = 30000) -> Glean:
    client = Glean(api_token=CLIENT_TOKEN, server_url=SERVER_URL, timeout_ms=timeout_ms)
    if ACT_AS:
        client.sdk_configuration.client.headers["X-Glean-ActAs"] = ACT_AS
    return client
```

Uses the official `glean-api-client` Python library. The `timeout_ms` parameter sets the underlying httpx client timeout — without it, the default 5-second httpx timeout causes every Chat call to immediately fall back to snippets.

#### `_extract_keywords(question)`

```python
cleaned = re.sub(r"[?,'\"():;/]", " ", question.lower())
tokens = cleaned.replace("'s", "").split()
keywords = [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]
return " ".join(keywords)
```

Per Glean MCP guidelines: *"Queries MUST be a SHORT sequence of highly targeted, discriminative keywords. AVOID full sentences."* Strips stop words and punctuation before querying. Without this, commas and filler words degrade search quality.

**Example**: `"What is Lumina's parental leave policy?"` → `"lumina parental leave policy"`

#### `returnLlmContentOverSnippets` — full document content from Glean directly

The original prototype read local markdown files (`docs/`) to enrich search snippets with full content. This was a prototype-only workaround — in production, indexed documents are remote (Drive, Confluence, Box) and can't be read from disk.

The correct pattern is `returnLlmContentOverSnippets=True` in `SearchRequestOptions`. Glean returns up to `maxSnippetSize` characters of full document content per result, directly in the search response — no separate `read_document` call needed.

```python
response = glean.client.search.query(
    query=keywords,
    page_size=fetch_size,
    max_snippet_size=MAX_SNIPPET_SIZE,       # top-level SearchRequest param
    request_options=models.SearchRequestOptions(
        facet_bucket_size=10,
        datasources_filter=[datasource],
        returnLlmContentOverSnippets=True,   # SearchRequestOptions param
    ),
)
```

The `snippets[].text` field in each result now contains full content in document order (up to 4,000 chars), replacing both the short relevance snippet and the old local file read. The `_enrich_with_full_content()` and `_load_full_content()` functions were removed entirely.

#### `search(question, datasource, top_k, after_date, before_date)`

```python
response = glean.client.search.query(
    query=keywords,
    page_size=fetch_size,
    max_snippet_size=MAX_SNIPPET_SIZE,
    request_options=models.SearchRequestOptions(
        facet_bucket_size=10,
        datasources_filter=[datasource],
        returnLlmContentOverSnippets=True,
    ),
)
```

**Why `datasources_filter` in `SearchRequestOptions`?** This is the correct way to scope search in the official client. We discovered through debugging that placing `datasourcesFilter` at the top level of a raw REST API POST payload is silently ignored by the Glean backend. The official client handles the correct nesting automatically.

**Post-filter by exact URL allowlist**: Even with `datasources_filter`, the shared sandbox returns results from other candidates. After getting API results, we filter to `KNOWN_URLS` only.

#### `chat(question, results)`

```python
with _glean_client(timeout_ms=25000) as glean:
    response = glean.client.chat.create(
        messages=[{"fragments": [models.ChatMessageFragment(text=prompt)]}],
        timeout_millis=25000,
    )
```

**Two timeouts**: `timeout_ms=25000` on the client (httpx connection timeout) and `timeout_millis=25000` in the payload (server-side Glean timeout). Both must be set.

**Snippet fallback**: If a `Timeout` exception is raised, `_snippets_fallback()` returns the search excerpts directly, labelled *"Here are the most relevant excerpts from the Lumina knowledge base."* This ensures the tool always returns grounded content even during sandbox slowdowns.

**Anti-hallucination prompt** (per Glean MCP guidelines):
```
"Answer using ONLY the internal documents provided below. Cite sources
using their numbers (e.g. [1], [2]). If the answer cannot be found in
the provided documents, say explicitly: 'I don't have that information
in the Lumina knowledge base.' Do not use outside knowledge or invent
information."
```

#### `ask(question, datasource, top_k, include_citations, after_date, before_date)`

The public interface — orchestrates the full pipeline:

1. `search()` → keyword query, `returnLlmContentOverSnippets=True`, URL-filtered results with full content
2. Empty-results guard → return early with "no documents found" rather than calling Chat with no context
3. `chat()` → grounded answer, 25s timeout, fallback
4. Format and return `{"answer": str, "sources": list[dict]}`

---

### 3.2 `src/indexer.py` — Glean Indexing API

Pushes documents to Glean using raw HTTP (the official client covers Search/Chat only; indexing uses the separate Indexing API directly):

```python
POST https://{instance}-be.glean.com/api/index/v1/indexdocuments
Authorization: Bearer {GLEAN_INDEXING_TOKEN}

{
  "datasource": "interviewds",
  "documents": [{
    "datasource": "interviewds",
    "objectType": "Document",
    "id": "lumina-employee-onboarding",
    "title": "Employee Onboarding Guide",
    "body": {"mimeType": "text/plain", "textContent": "..."},
    "viewURL": "https://internal.example.com/policies/employee-onboarding",
    "permissions": {"allowAllDatasourceUsersAccess": true}
  }]
}
```

**Key decisions**:
- **Incremental indexing** (`/indexdocuments`) rather than bulk replacement (`/bulkindexdocuments`) — re-running updates changed documents without deleting the rest
- **Stable IDs** (`lumina-{filename}`) — re-indexing updates in place, no duplicates
- **`viewURL` must match the datasource's `urlRegex`** — the sandbox datasource requires `https://internal.example.com/policies/.*`. Using any other URL pattern produces an HTTP 400 at ingest time (Fix #1 in FIXES.md)

---

### 3.3 `src/mcp_server.py` — MCP Tool Layer

```python
mcp = FastMCP(
    name="lumina-chatbot",
    instructions=(
        "...IMPORTANT: Always present the complete text returned by ask_lumina "
        "to the user, including the full Sources list at the end. Do not summarize, "
        "paraphrase, or omit any part of the tool response..."
    ),
)
```

The `instructions` field is how you tell Claude Desktop's model to handle tool output. Without this instruction, Claude Desktop summarizes the tool result and drops the Sources section. This was not obvious — it required reading MCP logs to diagnose (Fix #10 in FIXES.md).

```python
@mcp.tool()
def ask_lumina(
    question: str,
    datasource: str = "interviewds",
    top_k: int = 5,
    include_citations: bool = True,
    after_date: Optional[str] = None,   # YYYY-MM-DD
    before_date: Optional[str] = None,  # YYYY-MM-DD
) -> str:
```

Date filters (`after_date`, `before_date`) were added after inspecting the official Glean MCP `search` tool schema, which exposes these as standard parameters.

---

### 3.4 `validate.py` — Test Suite

Five end-to-end test cases against the live Glean pipeline:

```bash
python validate.py
```

Each test submits a question and checks:
1. Answer is non-empty and over 20 characters
2. At least one source is returned
3. Source titles contain expected keywords

All API calls emit structured logs at INFO level, including `requestId` and `backendTimeMillis` from each Glean response — useful for correlating slow responses against Glean's own telemetry.

---

## 4. The Indexed Document Corpus

Seven internal Lumina Stream Studios documents indexed into `interviewds`:

| Document | Domain | Key Content |
|---|---|---|
| `employee-onboarding.md` | HR / People & Culture | PTO (20 days), parental leave (16 wks primary / 6 wks secondary), benefits, hybrid policy, onboarding checklist |
| `production-workflow.md` | Production Operations | Google Drive folder structure, script versioning (WGA color order), call sheet workflows, access control tiers |
| `it-security-policy.md` | IT / InfoSec | Okta SSO, MFA (no SMS — SIM-swap risk), Jamf/Intune device management, data classification, incident response SLAs |
| `legal-contracts-policy.md` | Legal / Business Affairs | Box as contract repo, contract initiation process, talent buyout rules by guild (SAG/DGA/WGA), music clearance |
| `post-production-vfx-workflow.md` | Post-Production | Jira project structure, editorial phases (assembly → director → producer → locked), VFX shot tracking, delivery formats |
| `international-coproduction-guidelines.md` | Business Affairs / Global | Treaty vs. non-treaty co-pros, tax incentives by territory (UK HETV 25%, Canada 25%, Australia 16.5–30%), shared Drive/Confluence setup |
| `content-delivery-standards.md` | Technology / Distribution | Lumina+ specs (IMF, Dolby Atmos, Dolby Vision), DRM (Widevine/FairPlay/PlayReady), broadcast vs. OTT delivery, TPN watermarking |

**Why these 7?** They cover the full breadth of a media/entertainment company's internal knowledge: HR, IT, legal, production, post-production, finance/international, and distribution — demonstrating that Glean serves as a single source of truth across departments.

---

## 5. Part 1 – Anticipated Interview Questions & Answers

### 5.1 Glean API Questions

**Q: Walk me through how a document gets into Glean.**

A: Documents are pushed via the Glean Indexing API — a POST to `/api/index/v1/indexdocuments` with the Indexing token. Each document needs a unique `id`, `datasource`, `title`, plain-text `body`, a `viewURL` that matches the datasource's configured `urlRegex`, and optional `permissions`. After indexing, Glean processes and makes the content searchable asynchronously — there's typically a 15–20 minute propagation delay in the sandbox.

**Q: Why did you scope the Search API to a single datasource?**

A: `SearchRequestOptions(datasources_filter=["interviewds"])` constrains results to our custom datasource rather than searching across all Glean-connected sources. Without it, search returns results from every indexed source in the tenant — Slack, Google Drive, email, Jira, and so on. For a focused internal chatbot, you want answers grounded in your specific document set. In production, you might broaden the filter to span multiple datasources (e.g. HR docs + Jira tickets for an IT helpdesk bot).

**Q: Why do you call Search before Chat? Can't Chat retrieve documents on its own?**

A: Glean Chat does have native retrieval — in a fully configured production deployment, it can search the corpus autonomously. However, in our sandbox the custom datasource may not be fully crawlable by Chat's internal retrieval engine. More importantly, the explicit Search → inject → Chat pattern gives us control: we can filter to our exact document set, apply the URL allowlist, and control exactly what context Chat sees. The tradeoff is an extra API call and added latency, but it's worth it for reliability and observability.

**Q: What does `X-Glean-ActAs` do and why is it important?**

A: When using a Global API token (which bypasses user permissions by design), `X-Glean-ActAs` tells Glean to enforce document-level permissions as if the specified user made the request. Without it, every user would see every indexed document — including confidential ones. In production, this would be set dynamically to the logged-in employee's email, ensuring the chatbot respects Glean's permission model natively.

**Q: Why did you switch from raw `requests` to `glean-api-client`?**

A: Three reasons. First, the raw REST API silently ignores `datasourcesFilter` when placed at certain nesting levels — the official client uses the correct structure internally. Second, the default httpx timeout in the official client is configurable via `timeout_ms` on the constructor; without this, every Chat call was timing out after 5 seconds. Third, the client handles authentication headers, response parsing, and retries, reducing our boilerplate significantly and ensuring we're aligned with Glean's supported patterns.

**Q: How does the Chat API return its response?**

A: The Chat API returns a `messages` array where each message has an `author` (`USER` or `GLEAN_AI`) and a `fragments` array. Fragments are structured text blocks — we join the `text` values from all fragments in the last message to produce the final answer string.

### 5.2 Architecture & Design Questions

**Q: What assumptions did you make?**

A: First, the sandbox datasource was pre-configured — in a real deployment you'd call `/adddatasource` first. Second, I assumed a stateless, single-turn interaction model — no conversation history between calls. Third, I assumed all users share the same datasource, which is fine for a prototype. Fourth, I assumed the indexing propagation delay (~15–20 min) is acceptable for a demo context.

**Q: What are the main failure modes and how do you handle them?**

A:
1. **Search returns no results** — `ask()` returns early with an explicit "no documents found" message rather than calling Chat with no context, which would produce hallucinated answers.
2. **Chat API is slow** — 25-second timeout with a snippet fallback. The tool always returns grounded content (the search excerpts) even when Chat can't respond in time.
3. **Rate limiting (HTTP 429)** — `indexer.py` has exponential backoff retry logic.
4. **Wrong documents from shared sandbox** — URL allowlist filters to exactly our 7 document URLs.
5. **Missing env vars** — `_require_env()` validates at startup and raises a clear error immediately.

**Q: Walk me through what happens when I call `ask_lumina("What is the parental leave policy?")`**

A:
1. MCP client invokes `ask_lumina` with the question and defaults.
2. `ask_lumina` calls `ask()` in `chatbot.py`.
3. `_extract_keywords()` reduces the question to `"parental leave policy"` (strips "what", "is", "the").
4. `search()` POSTs to `/rest/api/v1/search` via the official client with `datasources_filter=["interviewds"]` and `returnLlmContentOverSnippets=True`, gets back up to 20 results with up to 4,000 chars of full content each, post-filters to our `KNOWN_URLS`, returns up to 5 Lumina documents.
5. `chat()` builds a grounded prompt with anti-hallucination instruction (using the full LLM content directly from search), POSTs to `/rest/api/v1/chat` with `timeout_ms=25000`.
6. Chat returns an answer citing `[Source 1: Employee Onboarding Guide]` (16 weeks primary / 6 weeks secondary).
7. `ask()` returns `{"answer": "...", "sources": [{"title": "Employee Onboarding Guide", "url": "..."}]}`.
8. `ask_lumina` appends a `**Sources:**` section and returns the full string to Claude Desktop.
9. Claude Desktop presents the complete response including sources to the user.

**Q: Why the exact URL allowlist rather than just a datasource filter?**

A: The `interviewds` sandbox datasource is shared across all interview candidates. During testing, we discovered another candidate had indexed their own documents ("Spellbook Manual") using the same `https://internal.example.com/policies/` URL prefix. Prefix matching alone was not exclusive to our documents. An exact allowlist of the 7 URLs we indexed is the only reliable guard in a shared environment. In production with a dedicated datasource, this wouldn't be necessary.

**Q: What went wrong during development that you'd flag as non-obvious?**

A: Several things documented in `FIXES.md`:
- `datasourcesFilter` at the top level of the raw REST API payload is silently ignored — this cost significant debugging time
- The official `glean-api-client` has a 5-second default httpx timeout that's separate from `timeoutMillis` in the payload — both must be set
- The MCP server `instructions` field controls whether Claude Desktop paraphrases or presents tool output verbatim — without it, sources get dropped in the model's summary
- The `interviewds` datasource is shared; at least one other candidate used the same URL prefix

---

## 6. Part 2 – Productionisation Design Discussion

*The live session will extend the scenario: "Productionise this for multiple teams, connect to an internal support chatbot, with stronger permissions, observability, and rollout controls."*

### 6.1 Updated Production Architecture

```
Employees (Web / Slack / Teams)
      │
      ▼
API Gateway / Auth Layer (OAuth2 / SSO)
      │ ← validates identity, extracts user email from JWT
      ▼
Chatbot Service (containerised, horizontally scalable)
├── Rate limiting per user/team
├── Request logging (question, user, datasource, timestamp)
├── Glean Search API (datasources_filter per team, X-Glean-ActAs = user email)
├── Glean Chat API (grounded answer with sources)
└── Response with sources + feedback buttons (thumbs up/down)
      │
      ▼
Observability Stack
├── Structured logs (Datadog / CloudWatch)
├── Latency metrics (search_ms, chat_ms, total_ms)
├── Zero-result rate dashboard
└── Alert: P99 > 10s, error rate > 1%
```

### 6.2 Permissions & Security

**User-scoped tokens**: Replace the static `GLEAN_ACT_AS` env var with a dynamic value extracted from the SSO JWT per request. The chatbot service sets `X-Glean-ActAs` to `user@company.com` for every API call, ensuring Glean's document-level ACLs are enforced per user.

**Datasource-level access control**: Different teams get different datasource filters. Legal documents get restrictive ACLs at index time (`allowedUsers` / `allowedGroups` in the indexing payload). Glean respects these in search results without any application-layer enforcement.

**Token management**: Tokens stored in AWS Secrets Manager or HashiCorp Vault — never in environment variables in production. Rotate quarterly and on any suspected compromise. Separate tokens per environment (dev/staging/prod).

### 6.3 Observability

| Signal | What to Capture | Alert Threshold |
|---|---|---|
| Latency | `search_ms`, `chat_ms`, `total_ms` per request | P99 > 10s |
| Error rate | HTTP 4xx/5xx from Glean APIs | > 1% over 5-min window |
| Zero-result rate | Searches returning 0 Lumina docs | > 10% → indexing gap |
| Citation quality | Answer contains [N] references | Flag answers with no citations |
| User feedback | Thumbs up/down on answers | < 70% positive → review corpus |

We already capture `requestId` and `backendTimeMillis` from every Glean API response in structured logs — these directly correlate with Glean's own telemetry for support escalations.

### 6.4 Scaling

**Stateless service**: Each request is independent — no server-side session state. Enables horizontal scaling.

**Rate limit handling**: The indexer already has exponential backoff on 429. The chatbot service needs the same pattern for Search and Chat.

**top_k tuning**: Higher top_k = better recall, larger prompts, higher Chat latency. Default of 5 is a good starting point; tune based on answer quality metrics from user feedback.

**Streaming**: Switch to `POST /rest/api/v1/chat` with `stream: true` for real-time token streaming to the UI. This eliminates the perceived latency problem entirely — users see words appearing rather than waiting for a 15-second response.

**Multi-turn**: Use the Chat API's `chatId` to maintain conversation context across follow-up questions. Each session gets a `chatId` returned in the first response; subsequent messages include it to continue the thread.

### 6.5 Rollout Plan

| Phase | Scope | Criteria to Advance |
|---|---|---|
| Alpha | Internal team (5 users) | Zero critical bugs, < 5s P99, manual quality review |
| Beta | One department (50 users) | > 75% positive feedback, error rate < 0.5%, no data leakage |
| GA | All employees | Feature flags → gradual rollout by department, 24/7 on-call |

---

## 7. Anticipated Live Coding Changes

### 7.1 Handle no search results (already implemented — walk through it)

The empty-results guard in `ask()`:
```python
if not results:
    return {
        "answer": "I don't have that information in the Lumina knowledge base. "
                  "No relevant documents were found...",
        "sources": [],
    }
```
**Why**: Without this, Chat would hallucinate an answer from its training data rather than internal documents.

### 7.2 Add a new document type or metadata field

Add a `department` field to indexed documents and surface it in search results:

```python
# In indexer.py, add to the document payload:
"customProperties": [
    {"name": "department", "value": infer_department(md_file.stem)}
]

# In chatbot.py search(), extract from result:
"department": (getattr(result, "custom_properties") or {}).get("department", "")

# In mcp_server.py, include in source citation:
f"[{source['index']}] [{source['department']}] {source['title']} — {source['url']}"
```

### 7.3 Change how retrieved content is filtered

Tighten the snippet filter to require a minimum length:
```python
MIN_SNIPPET_LENGTH = 100  # characters

# In search(), after building snippet_text:
if len(snippet_text) < MIN_SNIPPET_LENGTH:
    logger.debug("Skipping '%s' — snippet too short (%d chars)", title, len(snippet_text))
    continue
```
**Why**: Very short snippets (metadata matches without body text) add noise to the Chat prompt without useful context.

### 7.4 Improve citation formatting

```python
# Format with clickable URL:
f"[{source['index']}] **{source['title']}**\n    {source['url']}"
```

### 7.5 Add multi-turn conversation support

```python
# In chat(), accept optional history:
def chat(question: str, results: list, history: Optional[list] = None) -> tuple[str, list]:
    messages = list(history or [])
    messages.append({"author": "USER", "fragments": [{"text": prompt}]})
    # ... call API ...
    ai_message = {"author": "GLEAN_AI", "fragments": response_fragments}
    messages.append(ai_message)
    return answer, messages  # caller stores and passes history back next turn
```

---

## 8. Glean Platform Knowledge

### 8.1 What is Glean?

Glean is an enterprise AI search and knowledge platform. It connects to 100+ enterprise data sources (Google Drive, Slack, Jira, Confluence, Salesforce, etc.) via native connectors, indexes all content, and provides unified semantic search across all of them. On top of search, it layers AI-generated answers (GleanChat) and an agent/API layer for building custom AI-powered workflows.

### 8.2 Three APIs We Used

| API | Endpoint | What It Does |
|---|---|---|
| Indexing API | `POST /api/index/v1/indexdocuments` | Push custom documents into a custom datasource; supports metadata, permissions, content sections |
| Search API | `POST /rest/api/v1/search` | Semantic + keyword search; returns results with snippets, facets, metadata |
| Chat API | `POST /rest/api/v1/chat` | LLM-powered conversational interface; multi-turn, grounded in indexed content |

### 8.3 Glean's Permission Model

- Respects source permissions natively — if a Google Drive doc is restricted, Glean excludes it from search for users without access
- For custom datasources, permissions are set at index time via `allowedUsers`, `allowedGroups`, `denyUsers`
- `X-Glean-ActAs` bridges Global API tokens with per-user permission enforcement
- In production, Glean supports Okta/Azure AD group-based access control

### 8.4 MCP Protocol Overview

MCP (Model Context Protocol) is an open standard from Anthropic for connecting AI agents to external tools. Instead of agents calling arbitrary REST APIs, MCP defines a standard protocol where:
- **Tools** expose a schema describing inputs and outputs
- **Agents** discover available tools and invoke them via JSON-RPC over stdio (local subprocess) or HTTP (remote)
- The agent (Claude Desktop) decides when to invoke which tool based on the user's intent

Our `mcp_server.py` runs as a local subprocess — Claude Desktop starts it and communicates via stdin/stdout, so no network port or separate auth is needed for local use.

---

## 9. Key Fixes to Know (from FIXES.md)

These are the non-obvious issues that came up during development. Knowing them demonstrates real-world engineering judgment, not just code that works on a clean path.

| Fix | Issue | Root Cause | What You Learned |
|---|---|---|---|
| 1 | HTTP 400 on indexing | viewURL didn't match datasource urlRegex | Sandbox datasources have pre-configured regex — must conform |
| 4 | Chat timeouts | 30KB prompts from full document content | Truncate content; lead with snippet to preserve relevance |
| 5 | `Enriched 0/5` | `startswith()` fails when Glean wraps URLs | Use substring match, not prefix match |
| 6 | MCP tool timeout | Chat API slow; requests timeout too long | 25s timeout + snippet fallback so tool always returns something |
| 7 | Wrong search results | `datasourcesFilter` at top level silently ignored | Server-side filter unreliable; URL post-filter is authoritative |
| 8 | Raw API fragility | 5s default httpx timeout, manual auth/parsing | Official `glean-api-client` with explicit `timeout_ms` |
| 9 | "Spellbook Manual" returned | Shared sandbox; another candidate used same URL prefix | Exact URL allowlist, not prefix matching |
| 10 | Sources not shown | Claude Desktop paraphrases tool output, drops Sources | MCP `instructions` field tells the model to present verbatim |
| 11 | Commas in queries | Keyword extractor didn't strip punctuation | Regex strip before tokenising |
| 14 | Local file enrichment (prototype-only) | Production docs are remote — can't read from disk | `returnLlmContentOverSnippets=True` returns full content from Glean |
| 15 | Sources silently stripped on "summarize" | Claude Desktop passed `include_citations=False` | Removed parameter from schema; hardcoded `True` in tool |

---

## 10. Quick-Reference Cheat Sheet

### Key Numbers & Defaults

| Parameter | Value | Reasoning |
|---|---|---|
| `top_k` default | 5 | Glean recommends 3–5 results for Chat context |
| `MAX_SNIPPET_SIZE` | 4000 | LLM content chars per doc via returnLlmContentOverSnippets (API max: 10,000) |
| Chat `timeout_ms` (client) | 25,000 ms | Leaves headroom within Claude Desktop's MCP call budget |
| Chat `timeoutMillis` (payload) | 25,000 ms | Server-side Glean timeout |
| Indexing propagation | ~15–20 min | Documents not immediately searchable after ingest |
| Datasource | `interviewds` | Shared sandbox; 6 available (interviewds–interviewds6) |
| Glean instance | `support-lab` → `https://support-lab-be.glean.com` | |
| Documents indexed | 7 Markdown files | HR, IT, Legal, Production, Post, International, Distribution |
| Test cases | 5 scenarios | All pass: `python validate.py` |

### Key Policy Facts (for demo questions)

- **Parental leave**: 16 weeks fully paid (primary caregiver), 6 weeks (secondary)
- **MFA policy**: Required for all systems; Okta Verify preferred; **no SMS** (SIM-swap risk)
- **Talent buyout threshold**: Finance approval required for buyouts > $25,000
- **Delivery deadline**: QC-approved IMF master due 6 weeks before platform launch
- **Script locking**: WGA color order (White → Blue → Pink → Yellow) after table read
- **VFX shot review**: Vendor → ShotGrid → max 3 revision rounds → deliver to Aspera

### Elevator Pitch

*The chatbot implements a RAG pipeline using Glean's APIs: it takes a natural-language question, reduces it to keywords, retrieves the top-5 most relevant internal document snippets via the Glean Search API scoped to a custom datasource, enriches those snippets with full document content, then injects that context into a Glean Chat API call to generate a grounded answer with numbered citations back to source documents. The entire pipeline is exposed as a single MCP tool — `ask_lumina` — so any MCP-compatible AI agent can invoke it with just a question string.*

### Tradeoffs Table (for live discussion)

| Decision | Choice | Tradeoff |
|---|---|---|
| Official client vs. raw HTTP | `glean-api-client` | Correct filtering, less boilerplate; adds dependency |
| Explicit context injection | Inject search results into Chat prompt | Reliable grounding; extra API call and latency |
| URL allowlist | Exact match on 7 known URLs | Eliminates sandbox pollution; must update if docs change |
| 25s timeout + fallback | Always returns something | Fallback is excerpts not synthesised answer |
| Stateless requests | One call = one answer | No multi-turn memory; simple to scale |
| Single MCP tool | One `ask_lumina` wraps full pipeline | Less granular; can't call Search without Chat |

---

*When the interviewer asks "why did you structure it this way?" — give YOUR reasoning, not "the AI suggested it." Reference the tradeoffs above and be ready to defend or change any decision confidently.*

*Good luck, Karl. You built this, you debugged it, you understand every line.*
