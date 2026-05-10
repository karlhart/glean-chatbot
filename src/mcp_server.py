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

from typing import Optional

from chatbot import ask

mcp = FastMCP(
    name="lumina-chatbot",
    instructions=(
        "This server answers questions about Lumina Stream Studios internal policies "
        "and procedures using a Glean-powered knowledge base.\n\n"
        "After calling ask_lumina, your response to the user MUST:\n"
        "1. Present the full answer from the tool.\n"
        "2. End with a Sources section listing every source returned by the tool, "
        "formatted exactly as:\n"
        "   Sources:\n"
        "   - [Title](URL)\n"
        "Never omit or abbreviate the Sources section."
    ),
)


@mcp.tool()
def ask_lumina(
    question: str,
    datasource: str = "interviewds",
    top_k: int = 5,
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
    fast_mode: bool = False,
) -> str:
    """
    Ask the Lumina Stream Studios internal chatbot a natural-language question.

    Internally this tool runs the full Glean + Claude pipeline:
      1. Extracts keywords from the question and searches the Glean index.
      2. Sends full document content to Claude (claude-opus-4-7) to generate a grounded answer.

    CRITICAL INSTRUCTIONS FOR CLAUDE: This tool returns a fully synthesized,
    grounded answer that already includes inline citations and a formatted Sources
    footer. You MUST present the EXACT output of this tool back to the user verbatim.
    Do not paraphrase the answer, do not summarize it, and absolutely DO NOT remove
    the Sources section or URLs.

    Args:
        question:    The natural-language question to answer (required).
        datasource:  Glean datasource to search within (default: interviewds).
        top_k:       Number of search results to retrieve, max 5 (default: 5).
        after_date:  Only include documents updated after this date (YYYY-MM-DD).
        before_date: Only include documents updated before this date (YYYY-MM-DD).
        fast_mode:   Skip Glean Chat and return search excerpts directly (~500ms
                     instead of 10-20s). Use when speed matters more than a
                     synthesised answer (default: False).

    Returns:
        A fully formatted string with the grounded answer and a Sources section.
        Citations are always included and cannot be disabled.
    """
    # Citations are hardcoded to True — removing the parameter from the schema
    # prevents Claude from setting include_citations=False when summarising,
    # which would silently strip all source attribution from the response.
    result = ask(
        question=question,
        datasource=datasource,
        top_k=top_k,
        include_citations=True,
        after_date=after_date,
        before_date=before_date,
        fast_mode=fast_mode,
    )

    response_parts = [result["answer"]]

    if result["sources"]:
        response_parts.append("\n\n**Sources:**")
        for source in result["sources"]:
            response_parts.append(f"[{source['index']}] **{source['title']}**\n    {source['url']}")

    return "\n".join(response_parts)


if __name__ == "__main__":
    mcp.run()
