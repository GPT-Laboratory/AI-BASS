"""
Backfill all company documents from MongoDB into the new Postgres-backed LightRAG.

This script:
- Reads documents from the company_metadata collection in Mongo.
- For each document with textual content, posts it to LightRAG's /insert endpoint.
- Reuses the existing document ID (Mongo _id) so delete/update continues to work.
- Sends file_path for proper routing (source/type/file_id).

Environment variables:
- MONGO_URI (default: mongodb://mongo:27017/companydb)
- MONGO_DB (default: companydb)
- LIGHTRAG_SERVICE_URL (default: http://lightrag-service:9001)
- COMPANY_ID (optional: limit migration to a single company ObjectId as string)
"""

import os
import sys
import time
import logging
from typing import Any, Dict, Optional

import requests
from pymongo import MongoClient
from bson.objectid import ObjectId

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("migrate_to_pg")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017/companydb")
MONGO_DB = os.getenv("MONGO_DB", "companydb")
LIGHTRAG_SERVICE_URL = os.getenv("LIGHTRAG_SERVICE_URL", "http://lightrag-service:9001")
COMPANY_FILTER = os.getenv("COMPANY_ID")  # optional


def get_content(doc: Dict[str, Any]) -> Optional[str]:
    """Extract textual content from a metadata document, trying common fields."""
    for field in ("content", "text", "body", "email_body", "transcript"):
        val = doc.get(field)
        if isinstance(val, str) and val.strip():
            return val
    return None


def build_file_path(doc: Dict[str, Any], default_id: str) -> str:
    source = doc.get("source", "unknown")
    doc_type = doc.get("type", "document")
    file_id = doc.get("file_id") or doc.get("message_id") or default_id
    return f"{source}/{doc_type}/{file_id}"


def migrate_company(metadata_col, company_id: str) -> Dict[str, Any]:
    """Migrate all documents for a single company."""
    docs = metadata_col.find({"company_id": ObjectId(company_id)})
    migrated = 0
    skipped = 0
    errors = 0

    for doc in docs:
        doc_id = str(doc.get("_id"))
        content = get_content(doc)
        if not content:
            skipped += 1
            continue

        file_path = build_file_path(doc, doc_id)
        payload = {
            "documents": [content],
            "company_id": company_id,
            "ids": [doc_id],
            "file_paths": [file_path],
        }

        try:
            resp = requests.post(f"{LIGHTRAG_SERVICE_URL}/insert", json=payload, timeout=900)
            if resp.status_code == 200:
                migrated += 1
            else:
                errors += 1
                logger.error(
                    "Insert failed company=%s doc=%s status=%s body=%s",
                    company_id,
                    doc_id,
                    resp.status_code,
                    resp.text,
                )
        except Exception as e:
            errors += 1
            logger.exception("Exception inserting company=%s doc=%s: %s", company_id, doc_id, e)

    return {"migrated": migrated, "skipped": skipped, "errors": errors}


def main():
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    metadata_col = db["company_metadata"]

    if COMPANY_FILTER:
        company_ids = [COMPANY_FILTER]
    else:
        company_ids = metadata_col.distinct("company_id")
        company_ids = [str(cid) for cid in company_ids if isinstance(cid, ObjectId)]

    logger.info("Starting migration for %d companies", len(company_ids))
    overall = {"migrated": 0, "skipped": 0, "errors": 0}
    started = time.time()

    for cid in company_ids:
        logger.info("Migrating company %s", cid)
        stats = migrate_company(metadata_col, cid)
        logger.info("Company %s: %s", cid, stats)
        overall["migrated"] += stats["migrated"]
        overall["skipped"] += stats["skipped"]
        overall["errors"] += stats["errors"]

    elapsed = time.time() - started
    logger.info("Done. Overall: %s (%.1fs)", overall, elapsed)


if __name__ == "__main__":
    sys.exit(main())
