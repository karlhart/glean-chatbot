"""
Indexes local markdown documents into a Glean custom datasource.

Uses the Glean Indexing API (/api/index/v1/indexdocuments) to push documents
incrementally — meaning existing documents are updated in place rather than
deleting and re-uploading the entire datasource.
"""

import logging
import os
import time
import uuid
from pathlib import Path

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
INDEXING_TOKEN = _require_env("GLEAN_INDEXING_TOKEN")
DATASOURCE = _require_env("GLEAN_DATASOURCE")

BASE_URL = f"https://{INSTANCE}-be.glean.com/api/index/v1"
DOCS_DIR = Path(__file__).parent.parent / "docs"

# Base URL must match the datasource's configured urlRegex.
# The sandbox datasource 'interviewds' is pre-configured with:
#   urlRegex = https://internal\.example\.com/policies/.*
INTRANET_BASE = "https://internal.example.com/policies"


def _indexing_headers() -> dict:
    return {
        "Authorization": f"Bearer {INDEXING_TOKEN}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def _post_with_retry(url: str, payload: dict, timeout: int = 30) -> requests.Response:
    """POST with exponential backoff on HTTP 429 (rate limit) responses."""
    max_attempts = 4
    for attempt in range(max_attempts):
        response = requests.post(url, json=payload, headers=_indexing_headers(), timeout=timeout)

        if response.status_code == 429:
            wait = 2 ** attempt
            logger.warning("Rate limited by Glean (429). Retrying in %ds (attempt %d/%d).", wait, attempt + 1, max_attempts)
            time.sleep(wait)
            continue

        response.raise_for_status()
        return response

    response = requests.post(url, json=payload, headers=_indexing_headers(), timeout=timeout)
    response.raise_for_status()
    return response


# ---------------------------------------------------------------------------
# Document loading
# ---------------------------------------------------------------------------

def load_docs() -> list[dict]:
    """Read all markdown files from the docs/ directory and return document objects."""
    documents = []
    for md_file in sorted(DOCS_DIR.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        doc_id = f"lumina-{md_file.stem}"
        title = md_file.stem.replace("-", " ").title()
        for line in text.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break

        documents.append({
            "datasource": DATASOURCE,
            "objectType": "Document",
            "id": doc_id,
            "title": title,
            "body": {
                "mimeType": "text/plain",
                "textContent": text,
            },
            "viewURL": f"{INTRANET_BASE}/{md_file.stem}",
            "permissions": {
                # For the sandbox demo, allow all datasource users to see every doc.
                # In production, replace with allowedUsers / allowedGroups lists
                # reflecting the actual access controls from the source system.
                "allowAllDatasourceUsersAccess": True,
            },
        })
    return documents


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def index_documents(documents: list[dict]) -> None:
    """Push documents to Glean using the incremental indexdocuments endpoint."""
    url = f"{BASE_URL}/indexdocuments"
    payload = {
        "datasource": DATASOURCE,
        "documents": documents,
    }

    logger.info("Indexing %d document(s) into datasource '%s' ...", len(documents), DATASOURCE)
    _post_with_retry(url, payload, timeout=30)
    logger.info("Indexing request accepted. Documents searchable in ~15–20 minutes.")


def process_datasource_bulk() -> None:
    """
    Alternative: bulk-replace the entire datasource in one upload.

    Use this when you want to guarantee a clean slate (e.g. on first run or
    when removing documents). Sends isFirstPage + isLastPage = True in one
    request for a small document set. For large sets, paginate with a shared
    uploadId.
    """
    url = f"{BASE_URL}/bulkindexdocuments"
    documents = load_docs()
    upload_id = str(uuid.uuid4())

    payload = {
        "uploadId": upload_id,
        "datasource": DATASOURCE,
        "documents": documents,
        "isFirstPage": True,
        "isLastPage": True,
        "forceRestartUpload": False,
    }

    logger.info("Bulk-indexing %d document(s) (uploadId=%s) ...", len(documents), upload_id)
    _post_with_retry(url, payload, timeout=30)
    logger.info("Bulk indexing request accepted.")


if __name__ == "__main__":
    docs = load_docs()
    logger.info("Found %d document(s) in %s:", len(docs), DOCS_DIR)
    for d in docs:
        logger.info("  [%s] %s  (%d chars)", d["id"], d["title"], len(d["body"]["textContent"]))
    index_documents(docs)
