"""
Background task processing for RAG insertions
Handles asynchronous RAG document insertion without blocking API responses
"""

import threading
import queue
import logging
import os
import json
from typing import Dict, Any, Optional
from datetime import datetime
from bson.objectid import ObjectId
from openai import AzureOpenAI

logger = logging.getLogger(__name__)

RAG_CLASSIFIER_MODEL = os.getenv("RAG_CLASSIFIER_MODEL", "gpt-4o-mini")
AZURE_API_KEY = os.getenv("AZURE_API_KEY", "")
AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT", "")
AZURE_VERSION = os.getenv("AZURE_VERSION", "2024-12-01-preview")

# Task queue for background processing
rag_task_queue = queue.Queue()

# Status constants
RAG_STATUS_WAITING = "waiting"
RAG_STATUS_PROCESSING = "processing"
RAG_STATUS_INSERTED = "inserted"
RAG_STATUS_ERROR = "error"


class RAGBackgroundProcessor:
    """Background processor for RAG document insertions"""

    def __init__(self, metadata_col, lightrag_client):
        """
        Initialize the background processor

        Args:
            metadata_col: MongoDB metadata collection
            lightrag_client: Module with insert_company_document function
        """
        self.metadata_col = metadata_col
        self.lightrag_client = lightrag_client
        self.worker_thread = None
        self.running = False
        self.settings_col = metadata_col.database.get_collection("settings")
        self.token_usage_col = metadata_col.database.get_collection("token_usage")
        self.azure_client: Optional[AzureOpenAI] = None

        try:
            if AZURE_API_KEY and AZURE_ENDPOINT:
                self.azure_client = AzureOpenAI(
                    api_key=AZURE_API_KEY,
                    azure_endpoint=AZURE_ENDPOINT,
                    api_version=AZURE_VERSION,
                    timeout=90,
                )
                logger.info("Initialized AzureOpenAI client for RAG classification")
            else:
                logger.warning("Azure credentials missing; RAG document classification disabled")
        except Exception as e:
            logger.error(f"Failed to initialize AzureOpenAI client: {e}")
            self.azure_client = None

    def start(self):
        """Start the background worker thread"""
        if self.running:
            logger.warning("Background processor already running")
            return

        self.running = True
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()
        logger.info("RAG background processor started")

    def stop(self):
        """Stop the background worker thread"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
        logger.info("RAG background processor stopped")

    def _get_taxonomy(self) -> list[str]:
        """Return the configured taxonomy for RAG documents from settings"""
        try:
            settings = self.settings_col.find_one() or {}
            taxonomy = settings.get("rag_document_taxonomy", [])
            if isinstance(taxonomy, list):
                return [t.strip() for t in taxonomy if isinstance(t, str) and t.strip()]
        except Exception as e:
            logger.error(f"Failed to fetch RAG taxonomy from settings: {e}")
        return []

    def _save_token_usage(self, *, usage_data: Optional[Dict[str, Any]], success: bool, company_id: Optional[str], error: Optional[str] = None):
        """Persist token usage for classification calls"""
        if self.token_usage_col is None:
            return

        try:
            doc: Dict[str, Any] = {
                "timestamp": datetime.utcnow(),
                "model": RAG_CLASSIFIER_MODEL,
                "provider": "classification",
                "call_type": "rag_document_classification",
                "success": success,
            }
            if company_id:
                doc["company_id"] = company_id

            if usage_data:
                doc["usage"] = usage_data
            if error:
                doc["error"] = error

            self.token_usage_col.insert_one(doc)
        except Exception as e:
            logger.error(f"Failed to save classification token usage: {e}")

    def _classify_document(self, content: str, *, title: str = "", company_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Classify RAG document content using the configured taxonomy"""
        taxonomy = self._get_taxonomy()
        if not taxonomy or not self.azure_client or not content:
            return None

        snippet = content[:4000]  # keep prompt small while still representative
        taxonomy_str = ", ".join(taxonomy)
        prompt = (
            "Classify the following document into exactly one category from the provided taxonomy.\n"
            f"Available categories: {taxonomy_str}\n"
            "Return JSON with keys \"class\" (exactly one of the categories) and \"reason\" (short rationale).\n"
            f"Title: {title or 'N/A'}\n\n"
            f"Document (truncated):\n{snippet}"
        )

        usage_data = None
        try:
            completion = self.azure_client.chat.completions.create(
                model=RAG_CLASSIFIER_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=120,
                response_format={"type": "json_object"},
            )
            if completion.usage:
                usage_data = {
                    "prompt_tokens": getattr(completion.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(completion.usage, "completion_tokens", 0),
                    "total_tokens": getattr(completion.usage, "total_tokens", 0),
                }
                if getattr(completion.usage, "prompt_tokens_details", None):
                    usage_data["prompt_tokens_details"] = completion.usage.prompt_tokens_details.model_dump()
                if getattr(completion.usage, "completion_tokens_details", None):
                    usage_data["completion_tokens_details"] = completion.usage.completion_tokens_details.model_dump()

            content_json = completion.choices[0].message.content or "{}"
            parsed = json.loads(content_json)
            raw_class = parsed.get("class") or parsed.get("category")
            reason = parsed.get("reason") or parsed.get("explanation")

            if raw_class and raw_class not in taxonomy and "other" in taxonomy:
                raw_class = "other"

            if not raw_class:
                self._save_token_usage(usage_data=usage_data, success=True, company_id=company_id, error="No class returned")
                return None

            classification = {
                "class": raw_class,
                "reason": reason or "",
                "taxonomy": taxonomy,
                "model": RAG_CLASSIFIER_MODEL,
                "provider": "azure",
                "timestamp": datetime.utcnow().isoformat(),
            }
            if usage_data:
                classification["usage"] = usage_data

            self._save_token_usage(usage_data=usage_data, success=True, company_id=company_id)
            return classification
        except Exception as e:
            logger.warning(f"RAG document classification failed: {e}")
            self._save_token_usage(usage_data=usage_data, success=False, company_id=company_id, error=str(e))
            return None

    def _build_enrichment(self, content: str, metadata: Dict[str, Any], company_id: Optional[str]) -> Dict[str, Any]:
        """Prepare enrichment fields (length + classification) for metadata documents"""
        enrichment: Dict[str, Any] = {}
        if content:
            enrichment["text_length"] = len(content)
        else:
            enrichment["text_length"] = 0

        title = (
            metadata.get("title")
            or metadata.get("file_name")
            or metadata.get("subject")
            or metadata.get("message_id")
            or ""
        )
        classification = self._classify_document(content, title=title, company_id=company_id)
        if classification:
            enrichment["rag_document_class"] = classification.get("class")
            enrichment["rag_classification"] = classification

        return enrichment

    def enqueue_task(self, company_id: str, doc_id: str, content: str, metadata: Optional[Dict[str, Any]] = None, is_update: bool = False):
        """
        Add a RAG insertion task to the queue

        Args:
            company_id: MongoDB company ID as string
            doc_id: MongoDB document _id as string
            content: Document content to insert into RAG
            metadata: Metadata dict with source, type, file_id, etc.
            is_update: If True, performs delete+reinsert instead of just insert
        """
        metadata = metadata or {}
        task = {
            "company_id": company_id,
            "doc_id": doc_id,
            "content": content,
            "metadata": metadata,
            "is_update": is_update
        }

        # Update status to waiting
        try:
            self.metadata_col.update_one(
                {"_id": ObjectId(doc_id)},
                {"$set": {"rag_sync_status": RAG_STATUS_WAITING}}
            )
            action = "UPDATE" if is_update else "INSERT"
            logger.info(f"[DOC {doc_id}] Set RAG status to WAITING for {action} (queued at {datetime.utcnow().isoformat()})")
        except Exception as e:
            logger.error(f"[DOC {doc_id}] Failed to set waiting status: {e}")

        rag_task_queue.put(task)
        action = "update" if is_update else "insertion"
        logger.info(f"[DOC {doc_id}] Enqueued RAG {action} task for company {company_id}")

    def _process_queue(self):
        """Worker thread function that processes queued tasks"""
        logger.info("RAG background worker thread started")

        while self.running:
            try:
                # Get task with timeout to allow checking self.running
                task = rag_task_queue.get(timeout=1)

                company_id = task["company_id"]
                doc_id = task["doc_id"]
                content = task["content"]
                metadata = task.get("metadata") or {}
                is_update = task.get("is_update", False)

                action = "UPDATE" if is_update else "INSERT"
                logger.info(f"[DOC {doc_id}] Processing RAG {action} task for company {company_id} (started at {datetime.utcnow().isoformat()})")

                # Update status to processing
                try:
                    self.metadata_col.update_one(
                        {"_id": ObjectId(doc_id)},
                        {"$set": {"rag_sync_status": RAG_STATUS_PROCESSING}}
                    )
                    logger.info(f"[DOC {doc_id}] Set RAG status to PROCESSING")
                except Exception as e:
                    logger.error(f"[DOC {doc_id}] Failed to set processing status: {e}")

                # Enrich metadata with text length and classification before pushing to LightRAG
                try:
                    enrichment = self._build_enrichment(content, metadata, company_id)
                    if enrichment:
                        self.metadata_col.update_one(
                            {"_id": ObjectId(doc_id)},
                            {"$set": enrichment}
                        )
                        # Attach class info to metadata passed downstream (safe no-op for LightRAG)
                        if enrichment.get("rag_document_class"):
                            metadata["rag_document_class"] = enrichment["rag_document_class"]
                    logger.info(f"[DOC {doc_id}] Enriched metadata with classification/length")
                except Exception as e:
                    logger.error(f"[DOC {doc_id}] Failed to enrich metadata: {e}")

                # Perform the actual RAG insertion or update
                try:
                    if is_update:
                        # Use update method (delete + reinsert)
                        success = self.lightrag_client.update_company_document(
                            company_id=company_id,
                            doc_id=doc_id,
                            content=content,
                            metadata=metadata
                        )
                    else:
                        # Use insert method
                        success = self.lightrag_client.insert_company_document(
                            company_id=company_id,
                            content=content,
                            metadata=metadata,
                            doc_id=doc_id
                        )

                    if success:
                        # Update status to inserted
                        self.metadata_col.update_one(
                            {"_id": ObjectId(doc_id)},
                            {"$set": {"rag_sync_status": RAG_STATUS_INSERTED}}
                        )
                        logger.info(f"[DOC {doc_id}] Successfully inserted into RAG (completed at {datetime.utcnow().isoformat()})")
                    else:
                        # Update status to error
                        self.metadata_col.update_one(
                            {"_id": ObjectId(doc_id)},
                            {"$set": {"rag_sync_status": RAG_STATUS_ERROR}}
                        )
                        logger.error(f"[DOC {doc_id}] LightRAG insertion failed (completed at {datetime.utcnow().isoformat()})")

                except Exception as e:
                    # Update status to error
                    error_msg = str(e)
                    self.metadata_col.update_one(
                        {"_id": ObjectId(doc_id)},
                        {"$set": {"rag_sync_status": RAG_STATUS_ERROR}}
                    )
                    logger.exception(f"[DOC {doc_id}] Exception inserting into RAG (completed at {datetime.utcnow().isoformat()}): {error_msg}")

                # Mark task as done
                rag_task_queue.task_done()

            except queue.Empty:
                # Timeout, continue loop to check self.running
                continue
            except Exception as e:
                logger.exception(f"Unexpected error in RAG worker thread: {e}")

        logger.info("RAG background worker thread stopped")


# Global processor instance (initialized in app.py)
rag_processor = None


def init_rag_processor(metadata_col, lightrag_client):
    """Initialize and start the global RAG processor"""
    global rag_processor
    rag_processor = RAGBackgroundProcessor(metadata_col, lightrag_client)
    rag_processor.start()
    return rag_processor


def enqueue_rag_insertion(company_id: str, doc_id: str, content: str, metadata: Optional[Dict[str, Any]] = None):
    """
    Enqueue a RAG insertion task

    Args:
        company_id: MongoDB company ID as string
        doc_id: MongoDB document _id as string
        content: Document content to insert into RAG
        metadata: Metadata dict with source, type, file_id, etc.
    """
    if rag_processor is None:
        logger.error("RAG processor not initialized, cannot enqueue task")
        return False

    rag_processor.enqueue_task(company_id, doc_id, content, metadata, is_update=False)
    return True


def enqueue_rag_update(company_id: str, doc_id: str, content: str, metadata: Optional[Dict[str, Any]] = None):
    """
    Enqueue a RAG update task (delete + reinsert)

    Args:
        company_id: MongoDB company ID as string
        doc_id: MongoDB document _id as string
        content: Updated document content
        metadata: Metadata dict with source, type, file_id, etc.
    """
    if rag_processor is None:
        logger.error("RAG processor not initialized, cannot enqueue update task")
        return False

    rag_processor.enqueue_task(company_id, doc_id, content, metadata, is_update=True)
    return True
