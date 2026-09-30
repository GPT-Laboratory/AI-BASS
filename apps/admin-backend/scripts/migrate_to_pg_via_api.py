"""
Requeue all documents (metadata/files/memories) into LightRAG via the admin API.

Flow:
- Login with ADMIN_USERNAME/ADMIN_PASSWORD to /login
- List companies via /companies (or a single COMPANY_ID if provided)
- For each company, GET /metadata/company/<company_id> and /memories/company/<company_id>
- PUT each doc back to /metadata/<id> to trigger the existing RAG update/enqueue logic

Run inside admin-backend container (after rebuild):
  docker compose exec admin-backend python /app/scripts/migrate_to_pg_via_api.py

Limit to one company:
  docker compose exec -e COMPANY_ID=<company_id> admin-backend python /app/scripts/migrate_to_pg_via_api.py

Env vars:
- ADMIN_API_BASE (default http://localhost:5000)
- ADMIN_USERNAME / ADMIN_PASSWORD (from compose)
- COMPANY_ID (optional filter)
"""

import os
import sys
import time
import logging
from typing import Any, Dict, List

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("migrate_to_pg_via_api")

API_BASE = os.getenv("ADMIN_API_BASE", "http://localhost:5000")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
COMPANY_FILTER = os.getenv("COMPANY_ID")


def api(path: str) -> str:
    return f"{API_BASE.rstrip('/')}{path}"


def normalize_id(raw: Any) -> Any:
    if isinstance(raw, dict):
        for key in ("$oid", "oid", "_id", "id"):
            if key in raw:
                return raw[key]
    return raw


def login() -> str:
    resp = requests.post(api("/login"), json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}, timeout=30)
    resp.raise_for_status()
    token = resp.json().get("token")
    if not token:
        raise RuntimeError("Login succeeded but no token in response")
    return token


def get_companies(session: requests.Session) -> List[Dict[str, Any]]:
    resp = session.get(api("/companies"), timeout=60)
    resp.raise_for_status()
    return resp.json()


def get_docs_for_company(session: requests.Session, company_id: str) -> List[Dict[str, Any]]:
    docs: Dict[str, Dict[str, Any]] = {}

    # Metadata/files
    resp = session.get(api(f"/metadata/company/{company_id}"), timeout=300)
    if resp.status_code == 200:
        for doc in resp.json():
            doc_id = normalize_id(doc.get("_id") or doc.get("id"))
            if doc_id:
                docs[doc_id] = doc
    else:
        logger.error("Failed to fetch metadata for company %s: %s %s", company_id, resp.status_code, resp.text)

    # Memories (likely overlapping, but ensure inclusion)
    resp = session.get(api(f"/memories/company/{company_id}"), timeout=300)
    if resp.status_code == 200:
        for doc in resp.json():
            doc_id = normalize_id(doc.get("_id") or doc.get("id"))
            if doc_id:
                docs[doc_id] = doc
    else:
        logger.error("Failed to fetch memories for company %s: %s %s", company_id, resp.status_code, resp.text)

    return [d for d in docs.values() if d]


def reenqueue_doc(session: requests.Session, doc: Dict[str, Any]) -> bool:
    doc_id = normalize_id(doc.get("_id") or doc.get("id"))
    if not doc_id:
        return False
    payload = {k: v for k, v in doc.items() if k != "_id"}
    # PUT triggers rag_sync_status change and reinsert via existing handler
    resp = session.put(api(f"/metadata/{doc_id}"), json=payload, timeout=300)
    if resp.status_code == 200:
        return True
    logger.error("Failed to reenqueue doc %s: %s %s", doc_id, resp.status_code, resp.text)
    return False


def main() -> int:
    token = login()
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    if COMPANY_FILTER:
        companies = [{"_id": COMPANY_FILTER}]
    else:
        companies = get_companies(session)

    logger.info("Starting migration for %d companies", len(companies))
    started = time.time()
    totals = {"companies": 0, "docs": 0, "ok": 0, "fail": 0}

    for company in companies:
        cid = normalize_id(company.get("_id") or company.get("id"))
        if not cid:
            continue

        totals["companies"] += 1
        logger.info("Company %s: fetching docs", cid)
        docs = get_docs_for_company(session, cid)
        totals["docs"] += len(docs)

        for doc in docs:
            if reenqueue_doc(session, doc):
                totals["ok"] += 1
            else:
                totals["fail"] += 1

        logger.info("Company %s done: docs=%d ok=%d fail=%d", cid, len(docs), totals["ok"], totals["fail"])

    elapsed = time.time() - started
    logger.info("Finished. Companies=%d docs=%d ok=%d fail=%d (%.1fs)", totals["companies"], totals["docs"], totals["ok"], totals["fail"], elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
