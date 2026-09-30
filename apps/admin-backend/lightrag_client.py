"""
LightRAG client for admin backend to insert/update/delete documents in LightRAG
Uses requests for synchronous HTTP calls compatible with Flask
"""

import requests
import logging
import os
from typing import Dict, Any

logger = logging.getLogger(__name__)

LIGHTRAG_SERVICE_URL = os.getenv("LIGHTRAG_SERVICE_URL", "http://lightrag-service:9001")

def insert_company_document(company_id: str, content: str, metadata: Dict[str, Any] = None, doc_id: str = None) -> bool:
    """
    Insert a company document into LightRAG (synchronous for Flask compatibility)

    Args:
        company_id: MongoDB company ID (ObjectId as string)
        content: Document content to insert
        metadata: Optional metadata about the document
        doc_id: Document ID to use in LightRAG (MongoDB _id as string)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Extract file_id from metadata to use as the LightRAG document ID
        if not doc_id and metadata:
            doc_id = metadata.get('file_id', metadata.get('message_id'))

        # Prepare payload for LightRAG using company_id directly
        payload = {
            "documents": [content],
            "company_id": company_id  # Use company_id directly instead of finding a user
        }

        # IMPORTANT: Pass the document ID as 'ids' parameter so LightRAG uses our ID
        # This is crucial for delete operations to work correctly
        if doc_id:
            payload["ids"] = [doc_id]

        # Add metadata as file_paths if provided (used for citation tracking)
        if metadata:
            source = metadata.get('source', 'unknown')
            doc_type = metadata.get('type', 'document')
            file_id = metadata.get('file_id', metadata.get('message_id', 'auto'))
            file_path = f"{source}/{doc_type}/{file_id}"
            payload["file_paths"] = [file_path]

        # Make synchronous HTTP request to LightRAG service
        response = requests.post(
            f"{LIGHTRAG_SERVICE_URL}/insert",
            json=payload,
            timeout=900  # 15 minutes timeout for long RAG insertions
        )

        if response.status_code == 200:
            logger.info(f"Inserted document to LightRAG with ID: {doc_id}")
            return True
        else:
            logger.error(f"LightRAG insert failed: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        logger.exception(f"Exception inserting document to LightRAG: {e}")
        return False

def update_company_document(company_id: str, doc_id: str, content: str, metadata: Dict[str, Any] = None) -> bool:
    """
    Update a company document in LightRAG by deleting and reinserting

    LightRAG doesn't have a native update operation, so we:
    1. Delete the old document by doc_id
    2. Insert the updated content using the SAME doc_id

    Args:
        company_id: MongoDB company ID (ObjectId as string)
        doc_id: Document ID to update (MongoDB _id as string)
        content: Updated document content
        metadata: Optional metadata about the document

    Returns:
        True if successful, False otherwise
    """
    try:
        # Step 1: Delete the old document
        delete_success = delete_company_document(company_id, doc_id)
        if not delete_success:
            logger.warning(f"Failed to delete document {doc_id} before update (may not exist)")
            # Continue anyway - the document might not have existed in LightRAG

        # Step 2: Insert the updated document using the SAME ID
        payload = {
            "documents": [content],
            "company_id": company_id,
            "ids": [doc_id]  # IMPORTANT: Reuse the same ID
        }

        # Build file_path from metadata (same as insert)
        if metadata:
            source = metadata.get('source', 'unknown')
            doc_type = metadata.get('type', 'document')
            file_id = metadata.get('file_id', 'auto')
            file_path = f"{source}/{doc_type}/{file_id}"
            payload["file_paths"] = [file_path]

        # Insert the updated document
        response = requests.post(
            f"{LIGHTRAG_SERVICE_URL}/insert",
            json=payload,
            timeout=900  # 15 minutes timeout for long RAG insertions
        )

        if response.status_code == 200:
            logger.info(f"Successfully updated document in LightRAG for company {company_id}, ID: {doc_id}")
            return True
        else:
            logger.error(f"LightRAG update failed: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        logger.exception(f"Exception updating document in LightRAG: {e}")
        return False

def delete_company_document(company_id: str, doc_id: str, file_path: str = None) -> bool:
    """
    Delete a company document from LightRAG knowledge graph

    Args:
        company_id: MongoDB company ID (ObjectId as string)
        doc_id: Document ID to delete (file_id from metadata)
        file_path: Optional file path to determine if document is a memory

    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(f"Starting deletion process for document {doc_id}")

        # Proceed with deletion
        payload = {
            "company_id": company_id,
            "doc_id": doc_id
        }

        # Add file_path if provided so LightRAG can route to correct instance
        if file_path:
            payload["file_path"] = file_path

        response = requests.post(
            f"{LIGHTRAG_SERVICE_URL}/delete",
            json=payload,
            timeout=60
        )

        if response.status_code == 200:
            result = response.json()
            # Check if document was found and deleted
            if result.get("found", True):  # Default to True for backward compatibility
                logger.info(f"Successfully deleted document {doc_id} from LightRAG for company {company_id}")
            else:
                logger.warning(f"Document {doc_id} was not found in LightRAG (may have been deleted already)")
            return True
        else:
            logger.error(f"LightRAG delete failed: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        logger.exception(f"Exception deleting document from LightRAG: {e}")
        return False

def bulk_delete_company_documents(company_id: str, doc_ids: list, file_paths: list = None) -> Dict[str, Any]:
    """
    Delete multiple documents from LightRAG in one request

    Args:
        company_id: MongoDB company ID (ObjectId as string)
        doc_ids: List of document IDs to delete
        file_paths: Optional list of file paths corresponding to doc_ids (for routing to correct instance)

    Returns:
        Dict with deletion results containing:
        - status: 'completed' or 'error'
        - results: Dict with 'total', 'successful', 'failed', 'errors'
    """
    try:
        payload = {
            "company_id": company_id,
            "doc_ids": doc_ids
        }

        # Add file_paths if provided
        if file_paths:
            payload["file_paths"] = file_paths

        response = requests.post(
            f"{LIGHTRAG_SERVICE_URL}/bulk-delete",
            json=payload,
            timeout=120  # Longer timeout for bulk operations
        )

        if response.status_code == 200:
            result = response.json()
            logger.info(
                f"Bulk delete completed: {result['results']['successful']} successful, "
                f"{result['results']['failed']} failed"
            )
            return result
        else:
            logger.error(f"Bulk delete failed: {response.status_code} - {response.text}")
            return {
                "status": "error",
                "message": response.text,
                "results": {"total": len(doc_ids), "successful": 0, "failed": len(doc_ids), "errors": []}
            }

    except Exception as e:
        logger.exception(f"Exception during bulk delete: {e}")
        return {
            "status": "error",
            "message": str(e),
            "results": {"total": len(doc_ids), "successful": 0, "failed": len(doc_ids), "errors": []}
        }

def cleanup_company_workspace(company_id: str) -> Dict[str, Any]:
    """
    Cleanup entire LightRAG workspace for a company

    This function:
    1. Drops all data from LightRAG storage instances (including cache)
    2. Finalizes and removes the cached LightRAG instance
    3. Drops all MongoDB collections for this workspace as backup
    4. Cleans up any remaining resources

    CRITICAL: This calls drop() on ALL storage instances including:
    - llm_response_cache (the cache that was being left behind)
    - full_docs, text_chunks, full_entities, full_relations
    - entities_vdb, relationships_vdb, chunks_vdb
    - chunk_entity_relation_graph (nodes and edges)
    - doc_status

    Should be called AFTER all documents are deleted from MongoDB

    Args:
        company_id: MongoDB company ID (ObjectId as string)

    Returns:
        Dict with cleanup results containing:
        - status: 'success' or 'error'
        - instance_removed: bool
        - storage_drop_results: List of drop results for each storage
        - collections_dropped: int
        - collections_list: List[str]
    """
    try:
        response = requests.post(
            f"{LIGHTRAG_SERVICE_URL}/companies/{company_id}/cleanup",
            timeout=120  # Increased timeout for dropping multiple storages
        )

        if response.status_code == 200:
            result = response.json()

            # Log detailed results
            storage_drops = result.get('storage_drop_results', [])
            success_count = sum(1 for r in storage_drops if r.get('status') == 'success')
            failed_drops = [r for r in storage_drops if r.get('status') != 'success']

            logger.info(
                f"Workspace cleanup for company {company_id}: "
                f"instance_removed={result.get('instance_removed', False)}, "
                f"storages_dropped={success_count}/{len(storage_drops)}, "
                f"collections_dropped={result.get('collections_dropped', 0)}"
            )

            if failed_drops:
                failed_list = [f"{r['storage']}: {r.get('message', 'unknown error')}" for r in failed_drops]
                logger.warning(
                    f"Some storage drops failed for company {company_id}: {failed_list}"
                )

            return result
        else:
            logger.error(f"Workspace cleanup failed: {response.status_code} - {response.text}")
            return {
                "status": "error",
                "message": response.text
            }

    except Exception as e:
        logger.exception(f"Exception during workspace cleanup: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
