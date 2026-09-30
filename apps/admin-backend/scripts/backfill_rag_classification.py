import argparse
import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional

from bson.objectid import ObjectId
from openai import AzureOpenAI
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/companydb")
AZURE_API_KEY = os.getenv("AZURE_API_KEY", "")
AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT", "")
AZURE_VERSION = os.getenv("AZURE_VERSION", "2024-12-01-preview")
RAG_CLASSIFIER_MODEL = os.getenv("RAG_CLASSIFIER_MODEL", "gpt-4o-mini")


def get_taxonomy(settings_col) -> list[str]:
    settings = settings_col.find_one() or {}
    taxonomy = settings.get("rag_document_taxonomy", [])
    if isinstance(taxonomy, list):
        return [t.strip() for t in taxonomy if isinstance(t, str) and t.strip()]
    return []


def extract_content(doc: Dict[str, Any]) -> str:
    content = doc.get("content", {})
    if isinstance(content, dict):
        return (
            content.get("full_content")
            or content.get("description")
            or content.get("body_text")
            or ""
        )
    return str(content or "")


def classify_document(client: Optional[AzureOpenAI], taxonomy: list[str], content: str, title: str = "") -> Optional[Dict[str, Any]]:
    if not client or not taxonomy or not content:
        return None

    prompt = (
        "Classify the following document into exactly one category from the provided taxonomy.\n"
        f"Available categories: {', '.join(taxonomy)}\n"
        "Return JSON with keys \"class\" (one of the categories) and \"reason\" (short rationale).\n"
        f"Title: {title or 'N/A'}\n\n"
        f"Document (truncated):\n{content[:4000]}"
    )

    completion = client.chat.completions.create(
        model=RAG_CLASSIFIER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=120,
        response_format={"type": "json_object"},
    )

    parsed = json.loads(completion.choices[0].message.content or "{}")
    doc_class = parsed.get("class") or parsed.get("category")
    if doc_class and doc_class not in taxonomy and "other" in taxonomy:
        doc_class = "other"

    if not doc_class:
        return None

    usage = None
    if completion.usage:
        usage = {
            "prompt_tokens": getattr(completion.usage, "prompt_tokens", 0),
            "completion_tokens": getattr(completion.usage, "completion_tokens", 0),
            "total_tokens": getattr(completion.usage, "total_tokens", 0),
        }
        if getattr(completion.usage, "prompt_tokens_details", None):
            usage["prompt_tokens_details"] = completion.usage.prompt_tokens_details.model_dump()
        if getattr(completion.usage, "completion_tokens_details", None):
            usage["completion_tokens_details"] = completion.usage.completion_tokens_details.model_dump()

    return {
        "class": doc_class,
        "reason": parsed.get("reason") or parsed.get("explanation", ""),
        "taxonomy": taxonomy,
        "model": RAG_CLASSIFIER_MODEL,
        "provider": "azure",
        "timestamp": datetime.utcnow().isoformat(),
        **({"usage": usage} if usage else {}),
    }


def main(force: bool, limit: Optional[int]):
    client = MongoClient(MONGO_URI)
    default_db = client.get_default_database()
    db = default_db if default_db is not None else client["companydb"]
    metadata_col = db["company_metadata"]
    settings_col = db["settings"]

    taxonomy = get_taxonomy(settings_col)
    if not taxonomy:
        logger.warning("No RAG document taxonomy configured in settings; only text_length will be backfilled")

    azure_client = None
    if taxonomy and AZURE_API_KEY and AZURE_ENDPOINT:
        azure_client = AzureOpenAI(
            api_key=AZURE_API_KEY,
            azure_endpoint=AZURE_ENDPOINT,
            api_version=AZURE_VERSION,
            timeout=90,
        )
    elif taxonomy:
        logger.warning("Azure credentials missing; classification will be skipped")

    query = {} if force else {"$or": [{"rag_document_class": {"$exists": False}}, {"text_length": {"$exists": False}}]}
    cursor = metadata_col.find(query)
    processed = 0
    classified = 0

    for doc in cursor:
        if limit and processed >= limit:
            break

        content_text = extract_content(doc)
        if not content_text:
            processed += 1
            continue

        update_fields: Dict[str, Any] = {
            "text_length": len(content_text),
        }

        title = (
            doc.get("title")
            or doc.get("file_metadata", {}).get("file_name")
            or doc.get("google_drive", {}).get("file_name")
            or doc.get("onedrive", {}).get("file_name")
            or doc.get("email_metadata", {}).get("subject")
            or ""
        )

        classification = classify_document(azure_client, taxonomy, content_text, title)
        if classification:
            update_fields["rag_document_class"] = classification.get("class")
            update_fields["rag_classification"] = classification
            classified += 1

        metadata_col.update_one({"_id": ObjectId(doc["_id"])}, {"$set": update_fields})
        processed += 1

        if processed % 50 == 0:
            logger.info(f"Processed {processed} documents... (classified {classified})")

    logger.info(f"Finished. Processed {processed} documents, classified {classified}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill RAG document classification and text length")
    parser.add_argument("--force", action="store_true", help="Reclassify documents even if class already present")
    parser.add_argument("--limit", type=int, help="Optional limit on number of documents to process")
    args = parser.parse_args()
    main(force=args.force, limit=args.limit)
