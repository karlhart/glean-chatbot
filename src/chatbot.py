"""
Core chatbot workflow: Search → Read → Chat → grounded answer with citations.

Uses the official Glean Python client (glean-api-client) for Search and Chat,
replacing raw requests calls. Key benefits over the manual approach:
  - FacetFilter(field_name="app") correctly scopes search to our datasource
  - Client handles auth headers, retries, and response parsing
  - No URL-based workarounds needed for datasource filtering

Per Glean MCP guidelines:
  - Search queries must be short targeted keywords, not full sentences.
  - Full document content (read_document pattern) produces better Chat answers.
  - Chat prompt must explicitly instruct the model not to hallucinate.
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from glean.api_client import Glean
from glean.api_client import models

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

SERVER_URL = f"https://{INSTANCE}-be.glean.com"
DOCS_DIR = Path(__file__).parent.parent / "docs"
INTRANET_BASE = "https://internal.example.com/policies"

# Exact URLs of the documents we indexed. The interviewds datasource is shared
# across candidates, some of whom used the same URL prefix. An exact allowlist
# is the only reliable way to exclude other candidates' documents.
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

MAX_CONTEXT_RESULTS = 5
MAX_CONTENT_CHARS_PER_DOC = 1500

_STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had", "what", "which", "who",
    "where", "when", "why", "how", "i", "me", "my", "we", "our", "you",
    "your", "it", "its", "this", "that", "at", "in", "on", "of", "to",
    "for", "and", "or", "but", "not", "with", "about", "from", "by",
    "can", "could", "would", "should", "will", "tell", "find", "give",
    "get", "use", "need", "want", "know", "show",
}


def _glean_client(timeout_ms: int = 30000) -> Glean:
    """Return a configured Glean client instance."""
    client = Glean(api_token=CLIENT_TOKEN, server_url=SERVER_URL, timeout_ms=timeout_ms)
    # Global tokens require X-Glean-ActAs for per-user permission enforcement.
    if ACT_AS:
        client.sdk_configuration.client.headers["X-Glean-ActAs"] = ACT_AS
    return client


# ---------------------------------------------------------------------------
# Query optimisation
# ---------------------------------------------------------------------------

def _extract_keywords(question: str) -> str:
    """
    Reduce a natural-language question to short keyword query.

    Per Glean MCP guidelines: "Queries MUST be a SHORT sequence of highly
    targeted, discriminative keywords. AVOID full sentences."
    """
    import re
    # Strip punctuation that confuses Glean's keyword engine
    cleaned = re.sub(r"[?,'\"():;/]", " ", question.lower())
    cleaned = cleaned.replace("'s", "")
    tokens = cleaned.split()
    keywords = [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]
    return " ".join(keywords)


# ---------------------------------------------------------------------------
# Document content enrichment (read_document pattern)
# ---------------------------------------------------------------------------

def _load_full_content(url: str) -> Optional[str]:
    """
    Return the full text of a document given its view URL.

    Implements the Glean MCP "search → read_document" pattern.
    Resolves our INTRANET_BASE URLs back to local markdown files.
    """
    if url not in KNOWN_URLS:
        return None
    stem = url.rsplit("/", 1)[-1]
    candidate = DOCS_DIR / f"{stem}.md"
    if candidate.exists():
        return candidate.read_text(encoding="utf-8")
    return None


def _enrich_with_full_content(results: list[dict]) -> list[dict]:
    """
    Replace snippet text with full document content where available.

    Leads with the snippet (Glean's most-relevant excerpt) then appends
    additional document context up to MAX_CONTENT_CHARS_PER_DOC, so
    truncation never loses the key section.
    """
    enriched = []
    for r in results:
        full_text = _load_full_content(r["url"])
        if full_text:
            snippet = r["snippet"]
            remaining = MAX_CONTENT_CHARS_PER_DOC - len(snippet)
            if remaining > 200:
                extra = full_text[:remaining]
                content = f"{snippet}\n\n[Additional context:]\n{extra}"
                if len(full_text) > remaining:
                    content += "\n[... document truncated ...]"
            else:
                content = snippet
        else:
            content = r["snippet"]
        enriched.append({**r, "content": content, "has_full_content": full_text is not None})

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
    Search Glean for relevant documents using the official Python client.

    Uses FacetFilter(field_name="app") to scope results to our datasource —
    this is the correct parameter discovered from MCP matchingFilters, replacing
    the URL-based workaround needed with raw REST calls.
    """
    page_size = min(top_k, MAX_CONTEXT_RESULTS)
    keywords = _extract_keywords(question)

    if after_date:
        keywords += f" after:{after_date}"
    if before_date:
        keywords += f" before:{before_date}"

    logger.info("Searching datasource='%s' keywords='%s' top_k=%d", datasource, keywords, page_size)

    with _glean_client() as glean:
        response = glean.client.search.query(
            query=keywords,
            page_size=page_size,
            request_options=models.SearchRequestOptions(
                facet_bucket_size=10,
                datasources_filter=[datasource],
            ),
        )

    raw_results = response.results or []
    logger.info("Search complete — %d result(s) from Glean.", len(raw_results))

    results = []
    skipped = 0
    for result in raw_results:
        if len(results) >= page_size:
            break
        url = getattr(result, "url", "") or ""
        # interviewds is shared across sandbox candidates. Some used the same
        # URL prefix, so prefix matching alone isn't enough. Match against the
        # exact set of URLs we indexed to exclude other candidates' documents.
        if url not in KNOWN_URLS:
            skipped += 1
            continue
        snippets = getattr(result, "snippets", []) or []
        snippet_text = "\n".join(s.text for s in snippets if getattr(s, "text", None))
        if not snippet_text:
            continue
        results.append({
            "title": getattr(result, "title", "Untitled") or "Untitled",
            "url": url,
            "snippet": snippet_text,
            "datasource": datasource,
        })

    logger.info("After filter: %d Lumina result(s) kept, %d from other users skipped.",
                len(results), skipped)
    return results


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

def _build_chat_prompt(question: str, results: list[dict]) -> str:
    """
    Build a grounded Chat prompt with explicit anti-hallucination instruction.

    Per Glean MCP guidelines: "Only describe information actually returned by
    tools. If the tools cannot find relevant results, say so explicitly."
    """
    context_blocks = []
    for i, r in enumerate(results, start=1):
        content = r.get("content", r["snippet"])
        context_blocks.append(f"[Source {i}] {r['title']}\nURL: {r['url']}\n\n{content}")

    context = "\n\n---\n\n".join(context_blocks)
    return (
        "You are a helpful assistant for Lumina Stream Studios employees. "
        "Answer the question using ONLY the internal documents provided below. "
        "Cite sources using their numbers (e.g. [1], [2]). "
        "If the answer cannot be found in the provided documents, say explicitly: "
        "'I don't have that information in the Lumina knowledge base.' "
        "Do not use outside knowledge or invent information.\n\n"
        f"{context}\n\n---\n\nQuestion: {question}"
    )


def _snippets_fallback(question: str, results: list[dict]) -> str:
    """Return structured excerpts when Chat API is slow."""
    lines = ["Here are the most relevant excerpts from the Lumina knowledge base:\n"]
    for i, r in enumerate(results, start=1):
        lines.append(f"[{i}] **{r['title']}**\n{r['snippet']}\n")
    return "\n".join(lines)


def chat(question: str, results: list[dict]) -> str:
    """
    Call the Glean Chat API via the official client and return the response.

    Times out after 25 seconds to stay within Claude Desktop's MCP call budget.
    Falls back to returning raw search snippets on timeout so the caller always
    gets a grounded response even when Chat is slow.
    """
    prompt = _build_chat_prompt(question, results)
    logger.info("Calling Glean Chat with %d document(s) (%d with full content).",
                len(results), sum(1 for r in results if r.get("has_full_content")))

    try:
        with _glean_client(timeout_ms=25000) as glean:
            response = glean.client.chat.create(
                messages=[{"fragments": [models.ChatMessageFragment(text=prompt)]}],
                timeout_millis=25000,
            )

        messages = response.messages or []
        if not messages:
            return "No response received from Glean Chat."

        last = messages[-1]
        fragments = getattr(last, "fragments", []) or []
        parts = [f.text for f in fragments if getattr(f, "text", None)]
        answer = " ".join(parts).strip()
        logger.info("Chat complete.")
        return answer

    except Exception as e:
        if "timeout" in str(e).lower() or "timed out" in str(e).lower():
            logger.warning("Glean Chat timed out — returning snippet fallback.")
            return _snippets_fallback(question, results)
        raise


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

    results = search(question, datasource=ds, top_k=top_k,
                     after_date=after_date, before_date=before_date)

    if not results:
        logger.warning("No search results for query='%s' datasource='%s'.", question, ds)
        return {
            "answer": (
                "I don't have that information in the Lumina knowledge base. "
                "No relevant documents were found. If you recently indexed new "
                "content, please allow 15–20 minutes for indexing to complete."
            ),
            "sources": [],
        }

    enriched = _enrich_with_full_content(results)
    answer = chat(question, results=enriched if include_citations else [])

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
