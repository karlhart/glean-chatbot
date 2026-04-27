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
