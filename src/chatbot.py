"""
Core chatbot workflow: Search → Chat → grounded answer with citations.

Orchestrates two Glean Client API calls:
  1. /rest/api/v1/search  — retrieve relevant document snippets
  2. /rest/api/v1/chat    — generate a grounded answer citing those documents
"""

import os
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

INSTANCE = os.environ["GLEAN_INSTANCE"]
CLIENT_TOKEN = os.environ["GLEAN_CLIENT_TOKEN"]
DATASOURCE = os.environ.get("GLEAN_DATASOURCE", "interviewds")
ACT_AS = os.environ.get("GLEAN_ACT_AS", "")

BASE_URL = f"https://{INSTANCE}-be.glean.com/rest/api/v1"


def _client_headers() -> dict:
    headers = {
        "Authorization": f"Bearer {CLIENT_TOKEN}",
        "Content-Type": "application/json",
    }
    # Global tokens require X-Glean-ActAs to impersonate a real user so that
    # Glean can enforce per-user permissions in search results.
    if ACT_AS:
        headers["X-Glean-ActAs"] = ACT_AS
    return headers


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search(query: str, datasource: str, top_k: int = 5) -> list[dict]:
    """
    Call the Glean Search API and return up to top_k result objects.

    Each result dict contains: title, url, snippet text, and the datasource.
    We scope the search to a single datasource so results are grounded in the
    indexed documents rather than the broader Glean index.
    """
    url = f"{BASE_URL}/search"
    payload = {
        "query": query,
        "pageSize": top_k,
        "datasourcesFilter": [datasource],
        "disableSpellcheck": False,
    }

    response = requests.post(url, json=payload, headers=_client_headers(), timeout=30)
    response.raise_for_status()
    data = response.json()

    results = []
    for result in data.get("results", []):
        # Each result can have multiple snippets; we join them into one block.
        snippets = result.get("snippets", [])
        snippet_text = "\n".join(
            s.get("text", "") for s in snippets if s.get("text")
        )
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
    Construct a prompt that injects the retrieved document snippets so that
    Glean Chat can ground its answer in the indexed content.

    We pass context explicitly because the sandbox datasource may not yet be
    fully crawlable by the Chat API's native retrieval.  In a production
    deployment where Glean has full access to the corpus, the Chat API can do
    its own retrieval internally and the search step may be optional.
    """
    if not search_results:
        return question

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
    """
    Call the Glean Chat API and return the AI-generated response text.
    """
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

    response = requests.post(url, json=payload, headers=_client_headers(), timeout=45)
    response.raise_for_status()
    data = response.json()

    # The response contains a messages array; we want the last AI message.
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
            "answer":  str,              # The grounded response from Glean Chat
            "sources": list[dict],       # The search results used as context
        }
    """
    ds = datasource or DATASOURCE

    # Step 1: retrieve relevant documents
    results = search(question, datasource=ds, top_k=top_k)

    # Step 2: generate grounded answer
    answer = chat(question, search_results=results if include_citations else [])

    # Step 3: format sources for the caller
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
    import json
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
