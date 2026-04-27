"""
MCP server exposing the Lumina Stream Studios chatbot as a single tool.

Invoke via Claude Desktop or any MCP-compatible client.
The tool runs the full Glean pipeline: Search → Chat → grounded answer + sources.
"""

import os
import sys

# Add the src directory to the path when the server is launched as a subprocess
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load .env from the project root (one level above src/)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Validate required env vars at startup so the MCP server fails fast with a
# clear message rather than crashing mid-request with a cryptic KeyError.
_REQUIRED = ["GLEAN_INSTANCE", "GLEAN_CLIENT_TOKEN", "GLEAN_DATASOURCE"]
_missing = [k for k in _REQUIRED if not os.environ.get(k)]
if _missing:
    raise EnvironmentError(
        f"Missing required environment variable(s): {', '.join(_missing)}. "
        "Copy .env.example to .env and fill in your values."
    )

from chatbot import ask

mcp = FastMCP(
    name="lumina-chatbot",
    instructions=(
        "Ask the Lumina Stream Studios internal knowledge base questions about "
        "HR policies, production workflows, IT security, legal/contracts, "
        "post-production processes, co-production guidelines, and content delivery. "
        "All answers are grounded in indexed internal documents."
    ),
)


@mcp.tool()
def ask_lumina(
    question: str,
    datasource: str = "interviewds",
    top_k: int = 5,
    include_citations: bool = True,
) -> str:
    """
    Ask the Lumina Stream Studios internal chatbot a natural-language question.

    Internally this tool:
      1. Searches the Glean index for relevant internal documents (Search API).
      2. Sends those documents as context to Glean Chat to generate a grounded answer.
      3. Returns the answer together with the source documents used.

    Args:
        question:          The natural-language question to answer (required).
        datasource:        Glean datasource name to search within (default: interviewds).
        top_k:             Maximum number of search results to retrieve (default: 5).
        include_citations: Whether to append source references to the answer (default: True).

    Returns:
        A formatted string containing the grounded answer and, if include_citations
        is True, a list of source documents with titles and URLs.
    """
    result = ask(
        question=question,
        datasource=datasource,
        top_k=top_k,
        include_citations=include_citations,
    )

    response_parts = [result["answer"]]

    if include_citations and result["sources"]:
        response_parts.append("\n\n**Sources:**")
        for source in result["sources"]:
            response_parts.append(
                f"[{source['index']}] {source['title']} — {source['url']}"
            )

    return "\n".join(response_parts)


if __name__ == "__main__":
    mcp.run()
