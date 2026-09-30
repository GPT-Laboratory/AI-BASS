"""
One-off index creation script for the admin backend MongoDB.

Usage (inside container):
  python scripts/create_indexes.py

Honors env var MONGO_URI (defaults to mongodb://localhost:27017/companydb).
Safe to rerun; create_index is idempotent.
"""

import os
from pymongo import MongoClient


def ix(collection, keys, **opts):
    """
    Helper to create an index with clear ordering.
    keys: list of (field, direction) tuples
    """
    collection.create_index(keys, **opts)


def main() -> None:
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/companydb")
    client = MongoClient(mongo_uri)
    db = client.get_default_database()

    # Collections
    token_usage = db.get_collection("token_usage")
    log_entries = db.get_collection("log_entries")
    metadata = db.get_collection("company_metadata")
    users = db.get_collection("users")
    companies = db.get_collection("companies")

    print(f"Using database: {db.name}")

    # Token usage + logs
    ix(token_usage, [("timestamp", 1), ("user_id", 1), ("company_id", 1), ("company_env", 1)])
    ix(log_entries, [("timestamp", 1), ("metrics.user_id", 1), ("metrics.company_id", 1), ("metrics.company_env", 1)])
    ix(log_entries, [("metrics.company_id", 1), ("timestamp", 1)])

    # Metadata (general and per-source upserts)
    ix(metadata, [("created_at", 1), ("company_id", 1), ("source", 1), ("type", 1)])
    ix(metadata, [("company_id", 1), ("type", 1)])
    ix(metadata, [("company_id", 1), ("type", 1), ("google_drive.file_id", 1)])
    ix(metadata, [("company_id", 1), ("type", 1), ("onedrive.file_id", 1)])
    ix(metadata, [("company_id", 1), ("type", 1), ("email_metadata.message_id", 1)])
    ix(metadata, [("company_id", 1), ("type", 1), ("file_metadata.filename", 1), ("created_at", 1)])

    # Users / companies
    ix(users, [("phone_number", 1)], unique=True)
    ix(companies, [("environment", 1)])

    # Memories (stored in company_metadata)
    ix(metadata, [("company_id", 1), ("type", 1), ("created_at", 1)])

    print("Indexes ensured.")


if __name__ == "__main__":
    main()
