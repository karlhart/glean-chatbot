"""
Core chatbot workflow: Search → Read → Chat → grounded answer with citations.

Orchestrates three Glean Client API calls, mirroring the official MCP server
best-practice workflow:
  1. /rest/api/v1/search        — keyword search to find relevant documents
  2. /rest/api/v1/search (read) — fetch full document content by URL
  3. /rest/api/v1/chat          — generate a grounded answer from full content

Per Glean MCP guidelines:
  - Search queries must be short targeted keywords, not full sentences.
  - Full document content (via read_document equivalent) produces better Chat
    answers than snippets alone.
  - Chat prompt must explicitly instruct the model not to hallucinate beyond
    the provided context.
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config & validation
# ---------------------------------------------------------------------------

def _require_env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            "Copy .env.example to .env and fill in your values."
        )
    return val


INSTANCE = _require_env("GLEAN_INSTANCE")
CLIENT_TOKEN = _require_env("GLEAN_CLIENT_TOKEN")
DATASOURCE = os.environ.get("GLEAN_DATASOURCE", "interviewds")
ACT_AS = os.environ.get("GLEAN_ACT_AS", "")

BASE_URL = f"https://{INSTANCE}-be.glean.com/rest/api/v1"
DOCS_DIR = Path(__file__).parent.parent / "docs"

# Glean MCP guidelines recommend 3–5 results passed to Chat for focused context.
MAX_CONTEXT_RESULTS = 5

# URL prefix used when indexing local docs — maps back to the docs/ directory.
INTRANET_BASE = "https://internal.example.com/policies"

# Stop words stripped when building keyword search queries from natural language.
_STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had", "what", "which", "who",
    "where", "when", "why", "how", "i", "me", "my", "we", "our", "you",
    "your", "it", "its", "this", "that", "at", "in", "on", "of", "to",
    "for", "and", "or", "but", "not", "with", "about", "from", "by",
    "can", "could", "would", "should", "will", "tell", "find", "give",
    "get", "use", "need", "want", "know", "show",
}


def _client_headers() -> dict:
    headers = {
        "Authorization": f"Bearer {CLIENT_TOKEN}",
        "Content-Type": "application/json",
    }
    # Global tokens require X-Glean-ActAs so Glean enforces per-user permissions.
    if ACT_AS:
        headers["X-Glean-ActAs"] = ACT_AS
    return headers


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def _post_with_retry(url: str, payload: dict, headers: dict, timeout: int = 30) -> requests.Response:
    """POST with exponential backoff on HTTP 429 (rate limit) responses."""
    max_attempts = 4
    for attempt in range(max_attempts):
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)

        if response.status_code == 429:
            wait = 2 ** attempt
            logger.warning("Rate limited by Glean (429). Retrying in %ds (attempt %d/%d).",
                           wait, attempt + 1, max_attempts)
            time.sleep(wait)
            continue

        response.raise_for_status()
        return response

    response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response


# ---------------------------------------------------------------------------
# Query optimisation
# ---------------------------------------------------------------------------

def _extract_keywords(question: str) -> str:
    """
    Reduce a natural-language question to a short keyword query.

    Per Glean MCP guidelines: "Queries MUST be a SHORT sequence of highly
    targeted, discriminative keywords. AVOID full sentences."

    Example: "What is Lumina's parental leave policy?" → "parental leave policy"
    """
    tokens = question.lower().replace("?", "").replace("'s", "").split()
    keywords = [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]
    return " ".join(keywords)


# ---------------------------------------------------------------------------
# Document content enrichment (read_document pattern)
# ---------------------------------------------------------------------------

def _load_full_content(url: str) -> Optional[str]:
    """
    Return the full text of a document given its view URL.

    Implements the Glean MCP "search → read_document" pattern: after search
    returns document URLs, fetch full content for richer Chat context rather
    than relying on snippets alone.

    Since our docs are local markdown files indexed under INTRANET_BASE, we
    resolve the URL back to the corresponding file in docs/.  In a production
    deployment this step would call Glean's read_document endpoint with the
    real document URL.
    """
    if not url.startswith(INTRANET_BASE):
        return None
    stem = url[len(INTRANET_BASE):].lstrip("/")
    candidate = DOCS_DIR / f"{stem}.md"
    if candidate.exists():
        return candidate.read_text(encoding="utf-8")
    return None


def _enrich_with_full_content(results: list[dict]) -> list[dict]:
    """
    Replace snippet text with full document content where available.

    Implements the Glean MCP read_document best practice. Keeps snippet as
    fallback when the full file cannot be resolved (e.g. external URLs).
    """
    enriched = []
    for r in results:
        full_text = _load_full_content(r["url"])
        enriched.append({
            **r,
            "content": full_text if full_text else r["snippet"],
            "has_full_content": full_text is not None,
        })
    logger.info("Enriched %d/%d results with full document content.",
                sum(1 for r in enriched if r["has_full_content"]), len(enriched))
    return enriched


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search(
    question: str,
    datasource: str,
    top_k: int = 5,
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
) -> list[dict]:
    """
    Call the Glean Search API and return up to top_k result objects.

    Extracts keywords from the natural-language question before querying, per
    Glean MCP guidelines. Supports optional date range filters.
    """
    page_size = min(top_k, MAX_CONTEXT_RESULTS)

    # Keyword extraction: Glean search is a keyword engine, not a semantic one.
    keywords = _extract_keywords(question)

    # Append date filters inline if provided (Glean filter syntax).
    query = keywords
    if after_date:
        query += f" after:{after_date}"
    if before_date:
        query += f" before:{before_date}"

    url = f"{BASE_URL}/search"
    payload = {
        "query": query,
        "pageSize": page_size,
        "datasourcesFilter": [datasource],
        "disableSpellcheck": False,
    }

    logger.info("Searching datasource='%s' keywords='%s' top_k=%d", datasource, query, page_size)
    response = _post_with_retry(url, payload, _client_headers(), timeout=30)
    data = response.json()

    request_id = data.get("requestId", "n/a")
    backend_ms = data.get("backendTimeMillis", "n/a")
    raw_results = data.get("results", [])
    logger.info("Search complete — requestId=%s backendTimeMillis=%s results=%d",
                request_id, backend_ms, len(raw_results))

    results = []
    for result in raw_results:
        snippets = result.get("snippets", [])
        snippet_text = "\n".join(s.get("text", "") for s in snippets if s.get("text"))
        # Per Glean MCP guidelines: prefer a small number of highly relevant
        # sources. Skip results with no snippet — they matched on metadata only
        # and won't contribute useful context to Chat.
        if not snippet_text:
            logger.debug("Skipping result '%s' — no snippet returned.", result.get("title"))
            continue
        results.append({
            "title": result.get("title", "Untitled"),
            "url": result.get("url", ""),
            "snippet": snippet_text,
            "datasource": result.get("datasource", datasource),
        })

    return results


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

def _build_chat_prompt(question: str, results: list[dict]) -> str:
    """
    Build a grounded Chat prompt from full document content.

    Includes an explicit anti-hallucination instruction per Glean MCP guidelines:
    "Only describe information actually returned by tools. Do not invent documents
    or other resources. If the tools cannot find relevant results, say so."
    """
    context_blocks = []
    for i, r in enumerate(results, start=1):
        content = r.get("content", r["snippet"])
        block = f"[Source {i}] {r['title']}\nURL: {r['url']}\n\n{content}"
        context_blocks.append(block)

    context = "\n\n---\n\n".join(context_blocks)

    return (
        "You are a helpful assistant for Lumina Stream Studios employees. "
        "Answer the question using ONLY the internal documents provided below. "
        "Cite sources using their numbers (e.g. [1], [2]). "
        "If the answer cannot be found in the provided documents, say explicitly: "
        "'I don't have that information in the Lumina knowledge base.' "
        "Do not use outside knowledge or invent information.\n\n"
        f"{context}\n\n"
        f"---\n\n"
        f"Question: {question}"
    )


def chat(question: str, results: list[dict]) -> str:
    """Call the Glean Chat API and return the AI-generated response text."""
    url = f"{BASE_URL}/chat"
    prompt = _build_chat_prompt(question, results)

    payload = {
        "messages": [
            {
                "author": "USER",
                "fragments": [{"text": prompt}],
            }
        ],
        "timeoutMillis": 30000,
    }

    logger.info("Calling Glean Chat with %d document(s) (%d with full content).",
                len(results), sum(1 for r in results if r.get("has_full_content")))
    response = _post_with_retry(url, payload, _client_headers(), timeout=45)
    data = response.json()

    request_id = data.get("requestId", "n/a")
    backend_ms = data.get("backendTimeMillis", "n/a")
    logger.info("Chat complete — requestId=%s backendTimeMillis=%s", request_id, backend_ms)

    messages = data.get("messages", [])
    if not messages:
        return "No response received from Glean Chat."

    last_message = messages[-1]
    fragments = last_message.get("fragments", [])
    answer_parts = [f.get("text", "") for f in fragments if f.get("text")]
    return " ".join(answer_parts).strip()


# ---------------------------------------------------------------------------
# End-to-end workflow
# ---------------------------------------------------------------------------

def ask(
    question: str,
    datasource: Optional[str] = None,
    top_k: int = 5,
    include_citations: bool = True,
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
) -> dict:
    """
    Full pipeline: search → enrich with full content → chat → grounded answer.

    Returns:
        {
            "answer":  str,           # Grounded response from Glean Chat
            "sources": list[dict],    # Source documents used as context
        }
    """
    ds = datasource or DATASOURCE

    # Step 1: keyword search
    results = search(question, datasource=ds, top_k=top_k,
                     after_date=after_date, before_date=before_date)

    # Step 2: guard against empty results before calling Chat
    if not results:
        logger.warning("No search results for query='%s' datasource='%s'. "
                       "Documents may still be indexing (~15–20 min after ingestion).",
                       question, ds)
        return {
            "answer": (
                "I don't have that information in the Lumina knowledge base. "
                "No relevant documents were found. If you recently indexed new "
                "content, please allow 15–20 minutes for indexing to complete."
            ),
            "sources": [],
        }

    # Step 3: enrich results with full document content (read_document pattern)
    enriched = _enrich_with_full_content(results)

    # Step 4: generate grounded answer
    answer = chat(question, results=enriched if include_citations else [])

    # Step 5: format sources
    sources = []
    if include_citations:
        for i, r in enumerate(enriched, start=1):
            sources.append({
                "index": i,
                "title": r["title"],
                "url": r["url"],
                "datasource": r["datasource"],
            })

    return {"answer": answer, "sources": sources}


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What is the parental leave policy?"
    print(f"Question: {question}\n")

    result = ask(question)

    print("Answer:")
    print(result["answer"])
    print()
    if result["sources"]:
        print("Sources:")
        for s in result["sources"]:
            print(f"  [{s['index']}] {s['title']} — {s['url']}")
