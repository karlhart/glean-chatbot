# Troubleshooting Log & Fixes

A chronological record of every issue encountered during development, what caused it, and how it was resolved. Useful context for the live session and for understanding the non-obvious parts of the codebase.

---

## Fix 1 — Indexing failed: URL did not match datasource `urlRegex`

**Symptom**: `POST /indexdocuments` returned HTTP 400:
```
View URL https://intranet.luminastreamstudios.com/docs/... does not match
the URL Regex pattern https://internal\.example\.com/policies/.*
```

**Cause**: The sandbox datasource `interviewds` was pre-configured with a fixed `urlRegex`. Documents whose `viewURL` doesn't match that regex are rejected at ingest time.

**Fix**: Changed `INTRANET_BASE` in `indexer.py` from the fictional Lumina intranet URL to the pattern the sandbox datasource expects:
```python
INTRANET_BASE = "https://internal.example.com/policies"
```

**Lesson**: In a real deployment you control the datasource configuration (via `/adddatasource`) and can set any `urlRegex` you like. In the shared sandbox, you must conform to what's already there.

---

## Fix 2 — Best practices pass 1: retry logic, logging, empty-results guard

**Symptom**: No explicit failures, but the code had no resilience against Glean's rate limits or slow responses, and would crash with a cryptic `KeyError` on missing env vars.

**Changes made** (driven by Glean API documentation review):
- Added exponential backoff retry on HTTP 429 responses (`_post_with_retry`)
- Added structured logging with `requestId` and `backendTimeMillis` captured from each API response
- Added startup env var validation that fails fast with a clear error message
- Added guard in `ask()` that returns an explicit "no documents found" message rather than calling Chat with zero context (which would produce hallucinated answers)
- Capped `top_k` at 5 per Glean's recommendation of 3–5 results passed to Chat

---

## Fix 3 — Best practices pass 2: keyword extraction, read_document pattern, anti-hallucination prompt

**Symptom**: After connecting the official Glean MCP servers and reading their tool schemas directly, several gaps in our implementation became clear.

**Changes made**:

**Keyword extraction**: The Glean MCP `search` tool schema explicitly states: *"Queries MUST be a SHORT sequence of highly targeted, discriminative keywords. AVOID full sentences."* Our code was passing the full natural-language question to the Search API. Added `_extract_keywords()` to strip stop words before querying.

**read_document enrichment**: The MCP guidelines say to use a `search → read_document` workflow — after finding relevant documents, fetch full content rather than relying on snippets alone. Since our docs are local markdown files, implemented `_enrich_with_full_content()` to load the full file and prepend it to the Chat context.

**Anti-hallucination prompt**: The MCP guidelines state *"Do not invent documents. If tools cannot find relevant results, say so explicitly."* Added this instruction directly into the Chat prompt so Glean Chat is anchored to the provided context.

**Date filters**: The Glean MCP `search` tool schema exposes `after` and `before` YYYY-MM-DD filter params. Added matching `after_date` / `before_date` parameters to `ask()` and `ask_lumina`.

---

## Fix 4 — Chat API timeouts from large prompt size

**Symptom**: After implementing full document content enrichment, Chat API response times spiked to 30–45 seconds. Claude Desktop's MCP call timeout was shorter than that, causing tool calls to fail.

**Cause**: Full markdown documents average 5–6 KB each. Passing 5 untruncated documents created ~30 KB Chat prompts, making the API much slower.

**Fix**: Capped content per document at `MAX_CONTENT_CHARS_PER_DOC = 1500` characters.

**Secondary regression**: Simple head-truncation cut off the relevant section on longer documents (e.g. the VFX shot review process lives deep in `post-production-vfx-workflow.md`). Chat returned *"I don't have that information"* even though the doc was present.

**Fix for the regression**: Changed truncation strategy to always lead with Glean's snippet (which is already the most relevant excerpt selected by Glean's ranking), then append additional document context up to the character cap:
```python
content = f"{snippet}\n\n[Additional context:]\n{full_text[:remaining]}"
```
This way the key passage is never lost to truncation.

---

## Fix 5 — URL enrichment returning `Enriched 0/5`

**Symptom**: Logs showed `Enriched 0/5 results with full document content` — the read_document enrichment was silently skipping all results.

**Cause**: The original check used `url.startswith(INTRANET_BASE)`. Glean can wrap `viewURL` values in a redirect prefix (e.g. `https://app.glean.com/r?url=...`), so `startswith` failed even when the URL contained our base.

**Fix**: Changed to substring match:
```python
if INTRANET_BASE not in url:
    return None
```
Then extracted the stem using `url.index(INTRANET_BASE)` to handle any prefix.

---

## Fix 6 — Claude Desktop MCP call timing out

**Symptom**: Claude Desktop showed *"the Lumina MCP server timed out"*. MCP logs revealed the actual error:
```
HTTPSConnectionPool(host='support-lab-be.glean.com', port=443):
Read timed out. (read timeout=45)
```

**Cause**: The `requests.post` timeout was set to 45 seconds. The Glean Chat API was taking longer than that for some queries in the sandbox. Claude Desktop received our error response and surfaced it as a timeout.

**Fix**:
- Reduced Chat `requests.post` timeout to 25 seconds
- Added `_snippets_fallback()`: on `requests.exceptions.Timeout`, return the search snippets directly as a structured response so the tool always returns grounded content even when Chat is slow

---

## Fix 7 — Datasource filtering silently ignored

**Symptom**: Search results contained GitLab handbook pages, NXP datasheets, Ontario government documents, and other public web content — not Lumina documents. The `datasourcesFilter` parameter in the Search API payload appeared to have no effect.

**Root cause investigation**:
1. Placed `datasourcesFilter: ["interviewds"]` at the top level of the payload → silently ignored
2. Moved to `requestOptions.datasourcesFilter: ["interviewds"]` → also ignored
3. Added client-side filter on the `datasource` field of each result → `datasource` is `None` on all results from the REST API (the MCP layer annotates this field; the raw REST API does not return it)

**What the MCP search results revealed**: Direct queries via the official Glean MCP `search` tool returned our Lumina documents correctly. The `matchingFilters` in those results showed `"app": ["engineering policies demo", "interviewds"]`, confirming our documents ARE indexed and findable — the problem was purely in how we were filtering the REST API results.

**Fix**: Post-filter by URL. Our indexed documents have deterministic `viewURL` values (`https://internal.example.com/policies/{stem}`). Filter results to only those whose URL contains `INTRANET_BASE`:
```python
if INTRANET_BASE not in result_url:
    skipped += 1
    continue
```

---

## Fix 8 — Switch to official `glean-api-client`

**Motivation**: The raw `requests` approach required manual workarounds for authentication, filtering, and response parsing. The official Python client (`glean-api-client`) handles these correctly.

**Changes**:
- Replaced `requests` with `glean-api-client` for Search and Chat
- `SearchRequestOptions(datasources_filter=[datasource])` is the correct server-side filter in the official client (the raw REST API field name behaved differently)
- `timeout_ms=25000` passed to `Glean()` constructor sets the httpx client timeout — without this, the default httpx timeout of ~5 seconds caused every Chat call to immediately fall back to snippets
- Retained URL post-filter as a secondary guard (see Fix 9)
- `indexer.py` kept as raw HTTP — the official client covers Search and Chat only; indexing still uses the Indexing API directly

---

## Fix 9 — Shared sandbox contamination ("Spellbook Manual")

**Symptom**: Claude Desktop returned *"Spellbook Manual — a document about a sleep ritual..."* when asked about the knowledge base. This was not a Lumina document.

**Cause**: The `interviewds` datasource is shared across all interview candidates. At least one other candidate indexed their own documents using the same `https://internal.example.com/policies/` URL prefix. The URL prefix filter (Fix 7) was therefore not exclusive to our documents.

**Fix**: Replaced prefix matching with an exact URL allowlist containing only the 7 documents we indexed:
```python
KNOWN_URLS = {
    f"{INTRANET_BASE}/{stem}"
    for stem in [
        "content-delivery-standards",
        "employee-onboarding",
        "international-coproduction-guidelines",
        "it-security-policy",
        "legal-contracts-policy",
        "post-production-vfx-workflow",
        "production-workflow",
    ]
}
```
Any result whose URL is not in this set is excluded before enrichment or Chat.

---

## Fix 10 — Citations not visible in Claude Desktop

**Symptom**: The `ask_lumina` tool was correctly appending a `**Sources:**` section to every response (confirmed in MCP logs), but users reported not seeing citations in Claude Desktop.

**Cause**: When Claude Desktop's model receives a tool result, it sometimes paraphrases rather than presenting it verbatim. The model was summarizing the answer and omitting the Sources list in its response to the user.

**Fix**: Updated the `FastMCP` `instructions` field — this is the mechanism for telling the model how to handle tool output:
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

---

## Fix 11 — Commas and punctuation leaking into search queries

**Symptom**: MCP logs showed search queries containing commas and other punctuation:
```
keywords='specific technical specifications, formats, resolution, bitrate, codec requirements...'
```
Glean's keyword search engine does not handle punctuation gracefully and returns degraded results.

**Cause**: The keyword extractor only stripped `?` and `'s`. When Claude Desktop passed detailed multi-part questions, commas and other punctuation passed through to the search query.

**Fix**: Added a regex strip of all common punctuation before tokenising:
```python
cleaned = re.sub(r"[?,'\"():;/]", " ", question.lower())
```

---

## Fix 12 — Generic queries returning zero Lumina results

**Symptom**: Querying `"Can you summarize the onboarding checklist?"` returned *"I don't have that information in the Lumina knowledge base"* even though the Employee Onboarding Guide clearly contains a detailed first-week checklist.

**Root cause (two parts)**:

1. **Task verbs in the keyword query**: The keyword extractor passed `"summarize onboarding checklist"` to the Search API. The word `"summarize"` doesn't appear in any of our documents but does appear in other candidates' documents, causing their docs to rank above ours for this query.

2. **Fetch size too small**: Our document ranked at position **10** in the shared `interviewds` datasource for `"onboarding checklist"` — other candidates have more documents explicitly titled "onboarding checklist". We were only fetching 5 results, so ours never made it into the filter.

**Diagnosis**: Ran a direct API probe fetching 20 results and printing their positions:
```
 1. Employee Onboarding Checklist   (another candidate)
...
10. Employee Onboarding Guide       https://internal.example.com/policies/employee-onboarding  ← OUR DOC
```

**Fix**:

1. Expanded the stop words list to include task-instruction verbs — words that describe what to *do* with content rather than what to *find*:
```python
"summarize", "summary", "explain", "description", "describe", "list",
"detail", "details", "outline", "provide", "please", "help",
"overview", "walkthrough", "breakdown",
```

2. Increased fetch size from `page_size` (5) back to `min(page_size * 4, 20)` in the official client search call, matching the approach used before the `glean-api-client` migration. The URL allowlist then filters to our exact 7 documents from the broader result set.

3. Increased `MAX_CONTENT_CHARS_PER_DOC` from 1500 to 2500 so longer sections (like multi-day checklists) are fully captured in the Chat context.

**Result**: `"Can you summarize the onboarding checklist?"` now extracts keywords `"onboarding checklist"`, finds the Employee Onboarding Guide at position 10 out of 20 fetched, and returns the full Day 1 / Days 2–5 checklist with sources.

---

## Fix 13 — High latency (10–20s responses)

**Symptom**: Every query to the MCP tool took 10–20 seconds to respond. Users experienced a long blank wait before seeing any output.

**Diagnosis**: Added timestamps around each pipeline step to isolate the bottleneck:

| Step | Time |
|---|---|
| Glean Search API | ~500ms |
| Local content enrichment | ~6ms |
| Glean Chat API | ~10–17s |

The Glean Chat API accounts for ~95% of total latency. This is a sandbox infrastructure limitation — the shared sandbox is not optimised for throughput in the way a production deployment would be.

**What we cannot fix**: The Chat API response time itself. The prompt is already size-capped at 2500 chars per document, and the official client's `timeout_ms` is set correctly. The sandbox will simply be slower than production.

**Fix**: Added a `fast_mode` parameter to `ask()` and `ask_lumina` that bypasses the Glean Chat API entirely and returns the search excerpts directly:

```python
# Normal mode: Search (~500ms) + Chat (~15s) = ~16s total
result = ask("What is the parental leave policy?")

# Fast mode: Search (~500ms) only = ~800ms total
result = ask("What is the parental leave policy?", fast_mode=True)
```

Both modes return grounded content from indexed Lumina documents with source citations. `fast_mode` trades a synthesised answer for an immediate response — the raw excerpt contains the key information for most factual lookups.

In production, the correct fix for perceived latency is **streaming** — the Chat API supports `stream: true`, which sends tokens as they are generated. Users would see the answer building word by word rather than waiting 15 seconds for nothing.

---

## Fix 14 — Replace manual read_document enrichment with `returnLlmContentOverSnippets`

**Discovery**: Reading the Glean Search API documentation revealed the `returnLlmContentOverSnippets` request parameter, which instructs Glean to return up to `maxSnippetSize` characters of full document content directly in the search response — instead of the default ~255-char relevance-ranked snippet.

**What we had (workaround)**:
- `search()` returned ~255-char snippets
- `_enrich_with_full_content()` resolved each result's `viewURL` back to a local markdown file on disk, read the full content, and prepended snippet + appended additional context up to `MAX_CONTENT_CHARS_PER_DOC = 2500` chars
- This only worked because our indexed documents happened to also exist as local files — a prototype-only assumption

**Why this matters**: In a production deployment, indexed documents are remote (Google Drive, Confluence, Box). You don't have local copies. `returnLlmContentOverSnippets=True` is how you get full content without a separate `read_document` API call — Glean returns it directly in the search response.

**Changes**:
- Added `returnLlmContentOverSnippets=True` and `max_snippet_size=4000` to the `glean.client.search.query()` call
- Removed `_load_full_content()`, `_enrich_with_full_content()`, `DOCS_DIR`, and `MAX_CONTENT_CHARS_PER_DOC`
- Removed enrichment step from `ask()` — search results now contain full LLM-ready content directly
- Updated `_build_chat_prompt()` to use `r["snippet"]` directly (now contains full content, not just the excerpt)

**Key parameters**:
```python
response = glean.client.search.query(
    query=keywords,
    page_size=fetch_size,
    max_snippet_size=4000,          # top-level SearchRequest param
    request_options=models.SearchRequestOptions(
        facet_bucket_size=10,
        datasources_filter=[datasource],
        returnLlmContentOverSnippets=True,  # SearchRequestOptions param
    ),
)
```

The `snippets[].text` field in each result now contains up to 4,000 chars of document content in document order, replacing both the old snippet text and the local file read.

---

## Fix 15 — `include_citations=False` silently stripped all sources

**Symptom**: Claude Desktop returned complete, accurate answers with no source citations — even after multiple attempts to strengthen the MCP `instructions` field and reformat the tool response.

**Root cause**: The `ask_lumina` tool exposed `include_citations` as an optional boolean parameter. When a user asks Claude Desktop to *"summarize"* something, Claude Desktop's model infers that citations are unnecessary for a summary and passes `include_citations=False` to the tool. This happens silently at the tool-call layer, before the tool returns anything — no amount of MCP instructions or response formatting can recover sources that were never put into the result in the first place.

**Diagnosis**: The CLI (`python src/chatbot.py "..."`) produced a fully cited response, confirming the pipeline was correct. The failure was at the Claude Desktop invocation layer, not in the chat or search logic. Removing the parameter from the schema (so Claude Desktop cannot pass it) was the fix.

**Lesson — tool schema design**: Optional boolean parameters that control output verbosity or attribution are dangerous when the tool is called by an orchestrating LLM. The LLM will set them to `False` in compression contexts (summaries, concise requests, long conversations where context pressure is high). Any output that the tool *must always* include — citations, attributions, warnings — should not be gated behind an optional parameter.

**Fix**:
- Removed `include_citations` from the `ask_lumina` signature entirely
- Hardcoded `include_citations=True` in the `ask()` call inside the tool
- Simplified output to clean standard Markdown links: `- [Title](URL)`
- Added a comment explaining why the parameter was removed, for future maintainers

```python
# Citations are hardcoded to True — removing the parameter from the schema
# prevents Claude from setting include_citations=False when summarising,
# which would silently strip all source attribution from the response.
result = ask(
    question=question,
    ...
    include_citations=True,
    ...
)
```

---

## Summary table

| # | Issue | Root cause | Fix |
|---|---|---|---|
| 1 | Indexing HTTP 400 | viewURL didn't match datasource urlRegex | Align INTRANET_BASE to sandbox regex |
| 2 | No resilience | Missing retry, logging, validation | Backoff, structured logging, fail-fast validation |
| 3 | Suboptimal search/chat | Gaps vs Glean MCP best practices | Keywords, read_document pattern, anti-hallucination |
| 4 | Chat API timeouts | 30KB prompts from full document content | 1500-char cap, snippet-first truncation |
| 5 | Enrichment returning 0/5 | startswith() fails when Glean wraps URLs | Substring match instead |
| 6 | MCP call timeout | Chat API slow; 45s requests timeout | 25s timeout + snippet fallback |
| 7 | Wrong search results | datasourcesFilter silently ignored | URL post-filter on results |
| 8 | Raw API fragility | Manual auth/retry/parsing | Switch to official glean-api-client |
| 9 | Other candidates' docs returned | Shared sandbox; same URL prefix used by others | Exact URL allowlist for our 7 documents |
| 10 | Sources not shown to user | Claude Desktop model paraphrasing tool output | MCP server instructions field |
| 11 | Punctuation in queries | Keyword extractor didn't strip commas etc. | Regex strip of punctuation before tokenising |
| 12 | Generic queries returning 0 results | Task verbs in keywords; doc ranked at position 10 | Strip task verbs; fetch 20 results before filtering |
| 13 | High latency (10–20s) | Glean Chat API is 95% of response time in sandbox | fast_mode param bypasses Chat for ~800ms responses |
| 14 | Manual local-file enrichment | Prototype-only workaround; breaks in production | returnLlmContentOverSnippets=True returns full content from Glean directly |
| 15 | Sources silently stripped | Claude Desktop passed include_citations=False for "summarize" requests | Removed parameter; hardcoded citations=True in tool |

---

## Known Limitation — Claude Desktop citation rendering after `returnLlmContentOverSnippets`

**Symptom**: After implementing `returnLlmContentOverSnippets=True` (Fix 14), citations and source URLs stopped appearing consistently in Claude Desktop responses. The CLI (`python src/chatbot.py "..."`) continued to return fully cited, grounded answers. Claude Desktop produced clean, accurate answers with no source attribution.

**Root cause — architectural, not a bug**: Confirmed via MCP server logs (`~/Library/Logs/Claude/mcp-server-lumina-chatbot.log`). The tool was returning the complete response including sources:

```
For filming in the UK, Lumina can access the HETV program... [Source 1: International Co-Production Guidelines]

**Sources:**
[1] **International Co-Production Guidelines**
    https://internal.example.com/policies/international-coproduction-guidelines
```

Claude Desktop received this verbatim. It then generated its own response to the user, treating the tool result as retrieved context rather than final output to relay. The model's synthesis step discards citation markers and source footers as formatting metadata.

The richer content returned by `returnLlmContentOverSnippets` (4,000 chars of well-structured document text vs. 255-char snippets) made Glean Chat produce higher-quality, more polished answers — which paradoxically made Claude Desktop more likely to synthesise its own clean response rather than relay the tool output.

**Fixes attempted — all insufficient**:
1. Strengthened MCP `instructions` field ("relay verbatim") — ignored; Claude Desktop synthesises regardless
2. Moved sources before the answer — still dropped during synthesis
3. Changed `instructions` to action-based ("end your response with a Sources section") — partially followed but inconsistent
4. Removed `include_citations` parameter (Fix 15) — fixed silent stripping, but sources still dropped post-synthesis
5. Changed inline citation format to markdown links `[Title](URL)` — made attribution worse, reverted
6. Strengthened tool docstring with "CRITICAL: do not paraphrase" — insufficient

**Why it cannot be fully fixed from the MCP server**: The MCP protocol returns tool results as text content to the orchestrating model. What that model does with the content — relay it or synthesise a new response — is determined by the client (Claude Desktop), not the server. There is no MCP mechanism to force verbatim relay of tool output.

**Workaround for demos**: Run `python src/chatbot.py "<question>"` directly. The CLI always returns the full cited response with source URLs. This is the reliable way to demonstrate grounded answers with citations.

**Production fix**: Stream the Glean Chat response directly to a custom UI rather than routing it through a second LLM. When tool output goes directly to a renderer (not through Claude Desktop's model), citations are preserved exactly as the pipeline produces them.
