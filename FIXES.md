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
