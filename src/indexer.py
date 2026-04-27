"""
Indexes local markdown documents into a Glean custom datasource.

Uses the Glean Indexing API (/api/index/v1/indexdocuments) to push documents
incrementally — meaning existing documents are updated in place rather than
deleting and re-uploading the entire datasource.
"""

import os
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

INSTANCE = os.environ["GLEAN_INSTANCE"]
INDEXING_TOKEN = os.environ["GLEAN_INDEXING_TOKEN"]
DATASOURCE = os.environ["GLEAN_DATASOURCE"]

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


def load_docs() -> list[dict]:
    """Read all markdown files from the docs/ directory and return document objects."""
    documents = []
    for md_file in sorted(DOCS_DIR.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        # Use filename (without extension) as a stable document ID
        doc_id = f"lumina-{md_file.stem}"
        # Extract title from the first H1 heading, fall back to filename
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


def index_documents(documents: list[dict]) -> None:
    """Push documents to Glean using the incremental indexdocuments endpoint."""
    url = f"{BASE_URL}/indexdocuments"
    payload = {
        "datasource": DATASOURCE,
        "documents": documents,
    }

    print(f"Indexing {len(documents)} document(s) into datasource '{DATASOURCE}' ...")
    response = requests.post(url, json=payload, headers=_indexing_headers(), timeout=30)

    if response.status_code == 200:
        print("Indexing request accepted by Glean.")
        print("Note: documents typically become searchable within 15–20 minutes.")
    else:
        print(f"Indexing failed: HTTP {response.status_code}")
        print(response.text)
        response.raise_for_status()


def process_datasource_bulk() -> None:
    """
    Alternative: bulk-replace the entire datasource in one upload.

    Use this when you want to guarantee a clean slate (e.g. on first run or
    when removing documents).  Sends isFirstPage + isLastPage = True in one
    request for a small document set.  For large sets, paginate with a shared
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

    print(f"Bulk-indexing {len(documents)} document(s) (uploadId={upload_id}) ...")
    response = requests.post(url, json=payload, headers=_indexing_headers(), timeout=30)

    if response.status_code == 200:
        print("Bulk indexing request accepted.")
    else:
        print(f"Bulk indexing failed: HTTP {response.status_code}")
        print(response.text)
        response.raise_for_status()


if __name__ == "__main__":
    docs = load_docs()
    print(f"Found {len(docs)} document(s) in {DOCS_DIR}:")
    for d in docs:
        print(f"  [{d['id']}] {d['title']}  ({len(d['body']['textContent'])} chars)")
    print()
    index_documents(docs)
