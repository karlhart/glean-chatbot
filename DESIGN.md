# Design Note: Lumina Stream Studios — Glean Chatbot Prototype

**Author**: Karl Hart  
**Date**: April 2025  
**Scope**: Take-home exercise — Glean Solutions Architect interview

---

## Problem Statement

Lumina Stream Studios' institutional knowledge is scattered across Google Drive, Box, Slack, Confluence, and Jira. Employees have no single place to ask questions and get reliable, source-grounded answers. This prototype demonstrates how Glean's APIs can serve as the backbone of an internal enterprise chatbot.

---

## API Usage

### 1. Glean Indexing API

**Endpoint**: `POST https://{instance}-be.glean.com/api/index/v1/indexdocuments`  
**Auth**: `Authorization: Bearer {INDEXING_TOKEN}`

The Indexing API ingests content from external systems that Glean doesn't natively crawl. In this prototype, that content is a set of Markdown files representing Lumina internal documents.

**Key design choices:**
- I use **`/indexdocuments`** (incremental) rather than **`/bulkindexdocuments`** (full replacement). Incremental is better for a CI/CD pipeline where only changed files need re-indexing. Bulk is simpler for a first-time full upload but deletes any documents not included in the batch.
- Each document is given a **stable ID** (`lumina-{filename}`) so re-runs update in place rather than creating duplicates.
- `objectType: "Document"` is used for all docs. In production, you'd define more specific types per content type (e.g. `PolicyDocument`, `RunbookPage`) to enable richer filtering.
- `allowAllDatasourceUsersAccess: true` is used for the sandbox. In production, permissions would be synced from the source system (e.g. Box share permissions, Google Drive ACLs) using `allowedUsers` or `allowedGroups`.

### 2. Glean Search API

**Endpoint**: `POST https://{instance}-be.glean.com/rest/api/v1/search`  
**Auth**: `Authorization: Bearer {CLIENT_TOKEN}` + `X-Glean-ActAs: {user_email}`

Search retrieves relevant document snippets for the user's question. This serves as the **retrieval** step in a Retrieval-Augmented Generation (RAG) pattern.

**Key design choices:**
- I scope search to the specific datasource (`datasourcesFilter`) so results come only from indexed Lumina documents, not from noise in the broader Glean index. In production, you might broaden this to search across all connected datasources so the chatbot can answer questions that span Drive, Slack, and Confluence simultaneously.
- `pageSize` is configurable via `top_k` (default 5). More results give Chat more context but increase prompt length and latency.
- The `X-Glean-ActAs` header is required for Global tokens so that Glean enforces per-user document permissions. Without it, the API returns a 401.

### 3. Glean Chat API

**Endpoint**: `POST https://{instance}-be.glean.com/rest/api/v1/chat`  
**Auth**: Same as Search

Chat generates a grounded natural-language answer. I inject the Search results directly into the Chat prompt to ensure the answer is grounded in indexed content.

**Key design choices:**
- **Explicit context injection**: I prepend retrieved document snippets to the question before sending to Chat. This is belt-and-suspenders grounding — the Chat API can also do its own retrieval natively from the full index, but scoping it to our specific datasource via the prompt ensures we don't hallucinate content from outside our document set.
- **Source citation instructions**: The prompt instructs Glean Chat to use numbered references (`[1]`, `[2]`), making citations auditable.
- **Single-turn only**: This prototype is stateless. The Chat API supports multi-turn conversations via `chatId`; adding that would be the first enhancement for a real deployment.

---

## Data Flow

```
1. INGEST
   docs/*.md → indexer.py → POST /indexdocuments → Glean index
                                                    (async, ~15-20 min lag)

2. QUERY (at runtime)
   User question
        │
        ▼
   POST /search (datasourcesFilter: [interviewds])
        │
        ▼ top-k results (title, URL, snippet)
        │
   Build prompt: question + retrieved context
        │
        ▼
   POST /chat (messages: [{author: USER, fragments: [{text: prompt}]}])
        │
        ▼
   Extract answer text from response.messages[-1].fragments
        │
        ▼
   Return: {answer: str, sources: [{title, url, index}]}

3. MCP TOOL
   Claude Desktop → ask_lumina(question, ...) → step 2 → formatted response
```

---

## Key Tradeoffs

| Decision | Choice | Alternative | Reason |
|---|---|---|---|
| Indexing mode | Incremental (`/indexdocuments`) | Bulk (`/bulkindexdocuments`) | Safer for ongoing use; bulk deletes unincluded docs |
| Context injection | Explicit (inject search results into prompt) | Native (let Chat do its own retrieval) | Datasource scoping; predictable grounding |
| Auth scope | Global token + X-Glean-ActAs | User-scoped tokens | Simpler for single-service demo; user tokens preferred in prod |
| Conversation model | Stateless (single turn) | Multi-turn via chatId | Scope; multi-turn is the obvious next step |
| Streaming | No (full response) | Yes (stream: true) | Simpler for MCP tool return value |
| Permissions | allowAllDatasourceUsersAccess | Per-document ACLs | Sandbox only; production needs ACL sync |

---

## Failure Modes

- **No search results**: If the query returns zero results, Chat receives only the question with no context. The chatbot will still respond but the answer will not be grounded in Lumina documents. Mitigation: detect empty results and return an explicit "no documents found" message before calling Chat (easy live coding change).
- **Indexing lag**: Documents take 15–20 minutes to become searchable after `/indexdocuments`. A freshly indexed document won't be findable immediately. Mitigation: expose a "last indexed" timestamp in the tool response; in production, use webhooks or polling to confirm indexing completion.
- **Token expiry**: API tokens are long-lived in the sandbox but rotate in production. Mitigation: use a secrets manager (AWS Secrets Manager, HashiCorp Vault) and implement token refresh or rotation detection.
- **Rate limits**: The APIs return HTTP 429 on rate limit. The prototype does not implement retry logic. Mitigation: add exponential backoff with jitter.
- **Chat timeout**: The Chat API has a configurable `timeoutMillis`. Long or complex queries may time out. Mitigation: set a reasonable timeout (30s), surface the error clearly, and potentially fall back to returning search results without a generated answer.

---

## What I'd Do Next (Production Path)

1. **Sync permissions from source systems**: Replace `allowAllDatasourceUsersAccess` with per-document ACLs pulled from Google Drive, Box, and Slack APIs.
2. **Multi-turn conversation**: Use `chatId` to maintain session context across follow-up questions.
3. **Streaming responses**: Switch to `POST /chat` with `stream: true` for a more responsive UX in a web UI.
4. **Scheduled re-indexing**: Run the indexer on a cron job (or triggered by file change events) to keep the Glean index current.
5. **Observability**: Log question, search result count, answer length, and latency for every request. Add alerting on zero-result rate and error rate.
6. **Multi-datasource search**: Remove the datasource filter to enable cross-system search (Drive + Box + Slack + Jira) in a single query.
