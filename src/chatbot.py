"""
Core chatbot workflow: Search → Chat → grounded answer with citations.

Orchestrates two Glean Client API calls:
  1. /rest/api/v1/search  — retrieve relevant document snippets
  2. /rest/api/v1/chat    — generate a grounded answer citing those documents
"""

import logging
import os
import time
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

# Glean docs recommend passing 3–5 search results to Chat to keep context focused.
MAX_CONTEXT_RESULTS = 5


def _client_headers() -> dict:
    headers = {
        "Authorization": f"Bearer {CLIENT_TOKEN}",
        "Content-Type": "application/json",
    }
    # Global tokens require X-Glean-ActAs to impersonate a real user so that
    # Glean enforces per-user document permissions on search results.
    if ACT_AS:
        headers["X-Glean-ActAs"] = ACT_AS
    return headers


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def _post_with_retry(url: str, payload: dict, headers: dict, timeout: int = 30) -> requests.Response:
    """
    POST with exponential backoff on HTTP 429 (rate limit) responses.
    Raises for any non-retriable HTTP error after retries are exhausted.
    """
    max_attempts = 4
    for attempt in range(max_attempts):
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)

        if response.status_code == 429:
            wait = 2 ** attempt
            logger.warning("Rate limited by Glean (429). Retrying in %ds (attempt %d/%d).", wait, attempt + 1, max_attempts)
            time.sleep(wait)
            continue

        response.raise_for_status()
        return response

    # Final attempt after all backoffs
    response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search(query: str, datasource: str, top_k: int = 5) -> list[dict]:
    """
    Call the Glean Search API and return up to top_k result objects.

    Scopes the search to a single datasource so results are grounded in the
    indexed documents rather than the broader Glean index.
    """
    # Cap at MAX_CONTEXT_RESULTS — passing more than 5 to Chat degrades focus.
    page_size = min(top_k, MAX_CONTEXT_RESULTS)
    url = f"{BASE_URL}/search"
    payload = {
        "query": query,
        "pageSize": page_size,
        "datasourcesFilter": [datasource],
        "disableSpellcheck": False,
    }

    logger.info("Searching datasource='%s' query='%s' top_k=%d", datasource, query, page_size)
    response = _post_with_retry(url, payload, _client_headers(), timeout=30)
    data = response.json()

    # Log Glean's request ID and backend timing for debugging.
    request_id = data.get("requestId", "n/a")
    backend_ms = data.get("backendTimeMillis", "n/a")
    logger.info("Search complete — requestId=%s backendTimeMillis=%s results=%d",
                request_id, backend_ms, len(data.get("results", [])))

    results = []
    for result in data.get("results", []):
        snippets = result.get("snippets", [])
        snippet_text = "\n".join(s.get("text", "") for s in snippets if s.get("text"))
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

def _build_chat_prompt(question: str, search_results: list[dict]) -> str:
    """
    Inject retrieved document snippets into the prompt so Glean Chat grounds
    its answer in the indexed content rather than general knowledge.
    """
    context_blocks = []
    for i, r in enumerate(search_results, start=1):
        block = f"[Source {i}] {r['title']}\nURL: {r['url']}\n{r['snippet']}"
        context_blocks.append(block)

    context = "\n\n---\n\n".join(context_blocks)

    return (
        f"Use the following internal Lumina Stream Studios documents to answer "
        f"the question. Cite source numbers (e.g. [1], [2]) where relevant.\n\n"
        f"{context}\n\n"
        f"---\n\n"
        f"Question: {question}"
    )


def chat(question: str, search_results: list[dict]) -> str:
    """Call the Glean Chat API and return the AI-generated response text."""
    url = f"{BASE_URL}/chat"
    prompt = _build_chat_prompt(question, search_results)

    payload = {
        "messages": [
            {
                "author": "USER",
                "fragments": [{"text": prompt}],
            }
        ],
        "timeoutMillis": 30000,
    }

    logger.info("Calling Glean Chat with %d context document(s).", len(search_results))
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
) -> dict:
    """
    Full pipeline: search relevant documents, then generate a grounded answer.

    Returns:
        {
            "answer":  str,           # Grounded response from Glean Chat
            "sources": list[dict],    # Search results used as context
        }
    """
    ds = datasource or DATASOURCE

    # Step 1: retrieve relevant documents
    results = search(question, datasource=ds, top_k=top_k)

    # Step 2: guard against empty results — return early rather than calling
    # Chat with no context, which would produce an ungrounded hallucinated answer.
    if not results:
        logger.warning("No search results returned for query='%s' datasource='%s'. "
                       "Documents may still be indexing (allow 15–20 min after ingestion).", question, ds)
        return {
            "answer": (
                "No relevant documents were found in the knowledge base for your question. "
                "If you recently indexed new content, please wait 15–20 minutes for indexing to complete."
            ),
            "sources": [],
        }

    # Step 3: generate grounded answer
    answer = chat(question, search_results=results if include_citations else [])

    # Step 4: format sources for the caller
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
            print(f"  [{s['index']}] {s['title']} — {s['url']}")
