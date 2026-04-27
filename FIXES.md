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
