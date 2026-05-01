"""
Core chatbot workflow: Search → Chat → grounded answer with citations.

Uses the official Glean Python client (glean-api-client) for Search and Chat.

Per Glean MCP guidelines:
  - Search queries must be short targeted keywords, not full sentences.
  - returnLlmContentOverSnippets=True returns up to maxSnippetSize chars of
    full document content per result, replacing any manual read_document step.
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
# Maximum characters of LLM content to request per document from Glean Search.
# returnLlmContentOverSnippets supports up to 10,000 chars; 4,000 keeps prompts
# manageable while providing far more context than the default ~255-char snippet.
MAX_SNIPPET_SIZE = 4000

_STOP_WORDS = {
    # Articles, pronouns, prepositions
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had", "what", "which", "who",
    "where", "when", "why", "how", "i", "me", "my", "we", "our", "you",
    "your", "it", "its", "this", "that", "at", "in", "on", "of", "to",
    "for", "and", "or", "but", "not", "with", "about", "from", "by",
    "can", "could", "would", "should", "will", "tell", "find", "give",
    "get", "use", "need", "want", "know", "show",
    # Task-instruction verbs — describe what to DO with content, not what to FIND.
    # Passing these to the keyword search engine returns unrelated documents.
    "summarize", "summary", "explain", "description", "describe", "list",
    "detail", "details", "outline", "provide", "give", "please", "help",
    "overview", "walkthrough", "breakdown",
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

    Uses returnLlmContentOverSnippets=True so each result contains up to
    MAX_SNIPPET_SIZE chars of full document content — no separate read step needed.
    Uses datasources_filter in SearchRequestOptions to scope results to our datasource.
    """
    page_size = min(top_k, MAX_CONTEXT_RESULTS)
    keywords = _extract_keywords(question)

    if after_date:
        keywords += f" after:{after_date}"
    if before_date:
        keywords += f" before:{before_date}"

    # Fetch 4× more results than needed. The interviewds datasource is shared
    # across sandbox candidates, so our documents may not rank in the top 5
    # even when they are the most relevant for the user's question. Fetching
    # up to 20 and post-filtering by exact URL allowlist reliably finds them.
    fetch_size = min(page_size * 4, 20)

    logger.info("Searching datasource='%s' keywords='%s' top_k=%d (fetching %d)",
                datasource, keywords, page_size, fetch_size)

    with _glean_client() as glean:
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
        context_blocks.append(f"[Source {i}: {r['title']}]\nURL: {r['url']}\n\n{r['snippet']}")

    context = "\n\n---\n\n".join(context_blocks)
    # Inline citations use markdown link format [Title](URL) so the URL survives
    # even when an orchestrating LLM paraphrases the response. Plain [Source N]
    # tags are treated as metadata and stripped; markdown links look like content.
    example_title = results[0]["title"] if results else "Employee Onboarding Guide"
    example_url = results[0]["url"] if results else "https://internal.example.com/policies/employee-onboarding"
    return (
        "You are a helpful assistant for Lumina Stream Studios employees. "
        "Answer the question using ONLY the internal documents provided below. "
        "After each fact or claim, cite the source as a markdown link in this format: "
        f"[{example_title}]({example_url}). "
        "Use the exact title and URL from the source headers above. "
        "If the answer cannot be found in the provided documents, say explicitly: "
        "'I don't have that information in the Lumina knowledge base.' "
        "Do not use outside knowledge or invent information.\n\n"
        f"{context}\n\n---\n\nQuestion: {question}"
    )


def _snippets_fallback(question: str, results: list[dict]) -> str:
    """Return structured excerpts when Chat API is slow."""
    lines = ["Here are the most relevant excerpts from the Lumina knowledge base:\n"]
    for i, r in enumerate(results, start=1):
        lines.append(f"[Source {i}: {r['title']}]\n{r['snippet']}\n")
    return "\n".join(lines)


def chat(question: str, results: list[dict]) -> str:
    """
    Call the Glean Chat API via the official client and return the response.

    Times out after 25 seconds to stay within Claude Desktop's MCP call budget.
    Falls back to returning raw search snippets on timeout so the caller always
    gets a grounded response even when Chat is slow.
    """
    prompt = _build_chat_prompt(question, results)
    logger.info("Calling Glean Chat with %d document(s).", len(results))

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
    fast_mode: bool = False,
) -> dict:
    """
    Full pipeline: search (with LLM content) → chat → grounded answer.

    returnLlmContentOverSnippets=True means search results already contain full
    document content (up to MAX_SNIPPET_SIZE chars), so no separate enrichment
    step is needed.

    fast_mode=True skips the Glean Chat API entirely and returns the raw search
    excerpts. Responses come back in ~500ms instead of 10–20s. Useful when the
    user needs a quick lookup rather than a synthesised answer. The Glean Chat
    API accounts for ~95% of total latency in the sandbox; fast_mode eliminates
    that cost at the expense of a less polished, non-synthesised response.

    Returns:
        {
            "answer":  str,           # Grounded response (Chat or snippets)
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

    if fast_mode:
        logger.info("fast_mode=True — skipping Chat API, returning search excerpts.")
        answer = _snippets_fallback(question, results)
    else:
        answer = chat(question, results=results if include_citations else [])

    sources = []
    if include_citations:
        for i, r in enumerate(results, start=1):
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
            print(f"  [Source {s['index']}: {s['title']}] — {s['url']}")
