from __future__ import annotations

from email.mime import text
from urllib.parse import quote
import os
import re
import json
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from collections import Counter

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import numpy as np
from pymongo import MongoClient
from bson.objectid import ObjectId
import psycopg

# LightRAG imports
from lightrag import LightRAG, QueryParam
from lightrag.utils import EmbeddingFunc
from lightrag.kg.shared_storage import initialize_pipeline_status

# Custom Azure OpenAI implementations for LightRAG
from azure_openai_client import azure_llm_model_func, azure_embedding_func

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Filter to exclude health endpoint logs
class HealthCheckFilter(logging.Filter):
    def filter(self, record):
        return '/health' not in record.getMessage()

# Apply filter to uvicorn access logger
logging.getLogger('uvicorn.access').addFilter(HealthCheckFilter())

app = FastAPI(title="LightRAG Service", version="1.0.0")

# Configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
AZURE_API_KEY = os.getenv("AZURE_API_KEY", "")
AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT", "")
AZURE_VERSION = os.getenv("AZURE_VERSION", "2024-12-01-preview")
AZURE_LLM_MODEL = os.getenv("AZURE_LLM_MODEL", "gpt-4o")
AZURE_EMBED_MODEL = os.getenv("AZURE_EMBED_MODEL", "text-embedding-3-small")
LIGHTRAG_BACKEND = os.getenv("LIGHTRAG_BACKEND", "mongo").lower()

# Postgres settings for LightRAG storages
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "lightrag-postgres")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "lightrag")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DATABASE = os.getenv("POSTGRES_DATABASE", "lightrag")
LIGHTRAG_PG_POOL_MIN = int(os.getenv("LIGHTRAG_PG_POOL_MIN", "1"))
LIGHTRAG_PG_POOL_MAX = int(os.getenv("LIGHTRAG_PG_POOL_MAX", "10"))
LIGHTRAG_PG_DSN = os.getenv(
    "LIGHTRAG_PG_DSN",
    f"postgresql://{quote(POSTGRES_USER, safe='')}:{quote(POSTGRES_PASSWORD, safe='')}@{POSTGRES_HOST}:{POSTGRES_PORT}/{quote(POSTGRES_DATABASE, safe='')}",
)

# MongoDB setup
client = MongoClient(MONGO_URI)
db = client["companydb"]
users_col = db["users"]
companies_col = db["companies"]
settings_col = db["settings"]
metadata_col = db["company_metadata"]

# LightRAG MongoDB database (separate from companydb)
LIGHTRAG_DB_NAME = os.getenv("MONGO_DATABASE", "LightRAG")
# Ensure env var is set for LightRAG storage checks when using MongoGraphStorage
os.environ.setdefault("MONGO_DATABASE", LIGHTRAG_DB_NAME)
lightrag_db = client[LIGHTRAG_DB_NAME]

# LightRAG instances per company (workspace isolation)
lightrag_instances: Dict[str, LightRAG] = {}

# Per-company locks to prevent race conditions during instance creation
_company_init_locks: Dict[str, asyncio.Lock] = {}
_locks_lock = asyncio.Lock()  # Lock to protect the locks dictionary itself

# Global flag to track if pipeline status has been initialized
# This is a shared global state that only needs to be initialized once
_pipeline_status_initialized = False
_pipeline_init_lock = asyncio.Lock()

# LightRAG storage backend toggle
def _use_postgres_storage() -> bool:
    return LIGHTRAG_BACKEND == "postgres"

# Ensure Postgres env vars are populated for LightRAG PG storages
def _ensure_postgres_env():
    os.environ.setdefault("POSTGRES_HOST", POSTGRES_HOST)
    os.environ.setdefault("POSTGRES_PORT", str(POSTGRES_PORT))
    os.environ.setdefault("POSTGRES_USER", POSTGRES_USER)
    os.environ.setdefault("POSTGRES_PASSWORD", POSTGRES_PASSWORD)
    os.environ.setdefault("POSTGRES_DATABASE", POSTGRES_DATABASE)
    os.environ.setdefault("POSTGRES_MAX_CONNECTIONS", str(LIGHTRAG_PG_POOL_MAX))

# Readiness helpers
async def _wait_for_postgres_ready() -> None:
    """
    Wait for Postgres to be ready before initializing LightRAG storages.
    Retries with backoff to avoid failing on startup races.
    """
    retries = 5
    delay = 2
    for attempt in range(1, retries + 1):
        try:
            with psycopg.connect(LIGHTRAG_PG_DSN) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    cur.fetchone()
            logger.info("Postgres connection successful for LightRAG")
            return
        except Exception as e:
            if attempt == retries:
                logger.error(f"Postgres not ready after {retries} attempts: {e}")
                raise
            logger.warning(
                f"Postgres not ready (attempt {attempt}/{retries}): {e}. "
                f"Retrying in {delay}s..."
            )
            await asyncio.sleep(delay)
            delay *= 2  # backoff

# Models
class QueryRequest(BaseModel):
    query: str
    user: str  # MongoDB user _id as string

class InsertRequest(BaseModel):
    documents: List[str]
    company_id: Optional[str] = None  # Direct company ID (for company-level data)
    user: Optional[str] = None  # MongoDB user _id as string (optional, for user-specific data)
    file_paths: Optional[List[str]] = None
    ids: Optional[List[str]] = None

class LightRAGResponse(BaseModel):
    user_id: str
    company_id: str
    session_id: str
    user_name: str
    company_name: str
    company_industry: str
    company_founded: str
    company_headquarters: str
    context: str
    system_prompt: Optional[str]
    rag_documents: List[Dict[str, Any]]
    stats: Dict[str, Any]

# Delete operation
class DeleteRequest(BaseModel):
    doc_id: str  # Document ID (file_id from metadata)
    company_id: str  # Company ID
    file_path: Optional[str] = None  # File path to determine if it's a memory

class BulkDeleteRequest(BaseModel):
    doc_ids: List[str]  # List of document IDs to delete
    company_id: str  # Company ID
    file_paths: Optional[List[str]] = None  # File paths to determine which are memories

# Utility functions
def _find_reference_block(text: str) -> str | None:
    # 1) Most common: heading, then the next fenced block
    m = re.search(
        r"reference document list[^\r\n`]*[\r\n]+```(?:[a-zA-Z0-9_-]+)?\s*([\s\S]*?)```",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)

    # 2) Heading is *inside* a fenced block, then the list is in the next fenced block
    m = re.search(
        r"```[\s\S]*?reference document list[\s\S]*?```[\s\r\n]*```(?:[a-zA-Z0-9_-]+)?\s*([\s\S]*?)```",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)

    # 3) Fallback: pick the fenced block with the most lines that look like "[n] ..."
    best = None
    best_count = 0
    for m in re.finditer(r"```(?:[a-zA-Z0-9_-]+)?\s*([\s\S]*?)```", text):
        block = m.group(1)
        cnt = len(re.findall(r"^\s*\[\d+\]\s+", block, re.MULTILINE))
        if cnt > best_count:
            best = block
            best_count = cnt
    return best

def _parse_references(text: str, metadata_col=None) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    block = _find_reference_block(text)
    if not block:
        return refs

    # Grab each "[n] rest-of-line"
    for num, path in re.findall(r"^\s*\[(\d+)\]\s+(.+)$", block, re.MULTILINE):
        number = int(num)
        path = path.strip()

        # Prefer a 24-hex ObjectId anywhere on the line; if none, fall back to trailing segment
        m_id = re.search(r"\b([0-9a-f]{24})\b", path, re.IGNORECASE)
        source = m_id.group(1) if m_id else path.rsplit("/", 1)[-1].strip()

        doc = {"number": number, "source": source, "type": "", "title": ""}
        dbitem = metadata_col.find_one({"_id": ObjectId(source)}) or {}
        doc["type"] = dbitem.get("type", "") or dbitem.get("kind", "")
        doc["title"] = dbitem.get("title", "") or dbitem.get("name", "")

        refs.append(doc)

    return refs

def _split_top_level_json_objects(block: str) -> List[str]:
    objs, depth, start = [], 0, None
    in_str = False
    esc = False
    for i, ch in enumerate(block):
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        else:
            if ch == '"':
                in_str = True
            elif ch == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start is not None:
                    objs.append(block[start:i+1])
                    start = None
    return objs

def _parse_json_block(block: str) -> List[Dict[str, Any]]:
    """Parse a ```json block that could be a list, a single object, or N concatenated objects."""
    block = block.strip()
    try:
        parsed = json.loads(block)
        if isinstance(parsed, list):
            return list(parsed)
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass

    # Fall back: NDJSON / concatenated objects
    out: List[Dict[str, Any]] = []
    for obj in _split_top_level_json_objects(block):
        try:
            out.append(json.loads(obj))
        except json.JSONDecodeError:
            # last resort: tolerate single quotes
            try:
                out.append(json.loads(obj.replace("'", '"')))
            except json.JSONDecodeError:
                pass
    return out

def parse_knowledge_graph_and_refs(text: str) -> Tuple[
    List[Dict[str, Any]],  # Entities
    List[Dict[str, Any]],  # Relationships
    List[Dict[str, Any]],  # Document Chunks
    List[Dict[str, Any]],  # References
]:
    """
    Extract and return four separate lists:
      1) Entities                   (from the "Knowledge Graph Data (Entity)" json fence)
      2) Relationships              (from the "Knowledge Graph Data (Relationship)" json fence)
      3) Document Chunks            (from the "Document Chunks ..." json fence)
      4) References                 (from the 'Reference Document List' code fence)
    Returns: (entities, relationships, document_chunks, references)
    """
    entities: List[Dict[str, Any]] = []
    relationships: List[Dict[str, Any]] = []
    document_chunks: List[Dict[str, Any]] = []
    references: List[Dict[str, Any]] = []

    # --- Walk all ```json fences and classify by the nearby heading text
    for m in re.finditer(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE):
        block = m.group(1)
        ctx = text[max(0, m.start()-400):m.start()].lower()

        parsed = _parse_json_block(block)

        if "knowledge graph data (entity" in ctx:
            entities.extend(parsed)
        elif "knowledge graph data (relationship" in ctx:
            relationships.extend(parsed)
        elif "document chunks" in ctx:
            document_chunks.extend(parsed)
        else:
            # Unknown json fence near no recognizable heading -> ignore
            pass

    # --- References: grab the code fence immediately following the heading
    references = _parse_references(text, metadata_col)

    return entities, relationships, document_chunks, references

def normalize_phone(phone: str) -> str:
    """Normalize phone number by removing spaces, dashes, and leading +"""
    if not isinstance(phone, str):
        return ""
    return phone.replace(" ", "").replace("-", "").lstrip("+")

def _find_user_from_identifier(user_identifier: str) -> Dict[str, Any]:
    """
    Find user by MongoDB _id OR phone number

    Args:
        user_identifier: Either a MongoDB ObjectId string OR a phone number

    Returns:
        Dict with 'doc' (user document) and 'normalized_phone' keys
    """
    # First, try to find by MongoDB ObjectId
    try:
        user_oid = ObjectId(user_identifier)
        user_doc = users_col.find_one({"_id": user_oid})
        if user_doc:
            return {"doc": user_doc, "normalized_phone": normalize_phone(user_doc.get("phone_number", ""))}
    except Exception:
        # Not a valid ObjectId, will try phone number lookup
        pass

    # If not found by ObjectId, try phone number lookup
    normalized = normalize_phone(user_identifier)
    if normalized:
        user_doc = users_col.find_one({"phone_number": {"$regex": f"^\\+?{normalized}$", "$options": "i"}})
        if user_doc:
            return {"doc": user_doc, "normalized_phone": normalized}

    # No user found
    raise HTTPException(
        status_code=404,
        detail=f"User not found with identifier: {user_identifier}"
    )

async def get_lightrag_instance(company_id_str: str, is_memory: bool = False) -> LightRAG:
    """
    Get or create LightRAG instance for a company with proper workspace isolation.

    Args:
        company_id_str: Company ID
        is_memory: If True, returns the memory-specific instance with _memories suffix

    Returns:
        LightRAG instance
    """
    # Create instance key - append _memories for memory instances
    instance_key = f"{company_id_str}_memories" if is_memory else company_id_str

    # Fast path: check if instance already exists (no lock needed for read)
    if instance_key in lightrag_instances:
        return lightrag_instances[instance_key]

    # Get or create a lock for this specific instance
    async with _locks_lock:
        if instance_key not in _company_init_locks:
            _company_init_locks[instance_key] = asyncio.Lock()
        company_lock = _company_init_locks[instance_key]

    # Acquire the company-specific lock to prevent race conditions
    async with company_lock:
        # Double-check: another coroutine might have created the instance
        # while we were waiting for the lock
        if instance_key in lightrag_instances:
            return lightrag_instances[instance_key]

        # Create new LightRAG instance with MongoDB storage backends
        working_dir = f"./lightrag_storage/{instance_key}"

        # Configure embedding function with Azure OpenAI
        embedding_func = EmbeddingFunc(
            embedding_dim=1536,  # text-embedding-3-small dimension
            func=azure_embedding_func
        )

        # Get configuration from MongoDB settings (with fallback to defaults)
        chunk_token_size = get_setting_from_singleton("lightrag_chunk_token_size", 800)
        chunk_overlap_size = get_setting_from_singleton("lightrag_chunk_overlap_size", 100)
        entity_extract_max_gleaning = get_setting_from_singleton("lightrag_entity_extract_max_gleaning", 1)
        max_async_llm = get_setting_from_singleton("lightrag_max_async_llm", 4)
        max_async_embedding = get_setting_from_singleton("lightrag_max_async_embedding", 16)
        embedding_batch_size = get_setting_from_singleton("lightrag_embedding_batch_size", 32)
        max_parallel_insert = get_setting_from_singleton("lightrag_max_parallel_insert", 4)

        # Storage backend selection
        if _use_postgres_storage():
            storage_kwargs = {
                "kv_storage": "PGKVStorage",
                "vector_storage": "PGVectorStorage",
                # Keep graph storage on Mongo to avoid AGE dependency in Postgres
                "graph_storage": "MongoGraphStorage",
                "doc_status_storage": "PGDocStatusStorage",
            }
            _ensure_postgres_env()
            logger.info("Using Postgres storage backend for LightRAG")
        else:
            storage_kwargs = {
                "kv_storage": "MongoKVStorage",
                "vector_storage": "MongoVectorDBStorage",
                "graph_storage": "MongoGraphStorage",
                "doc_status_storage": "MongoDocStatusStorage",
            }
            logger.info("Using Mongo storage backend for LightRAG")

        # Create LightRAG instance
        rag = LightRAG(
            working_dir=working_dir,
            # Storage configurations
            **storage_kwargs,
            # Workspace for company isolation (used as collection prefix/namespace)
            workspace=f"lightrag_{instance_key}",
            # LLM and embedding functions
            llm_model_func=azure_llm_model_func,
            embedding_func=embedding_func,
            # Configuration parameters (from MongoDB settings)
            chunk_token_size=int(chunk_token_size),
            chunk_overlap_token_size=int(chunk_overlap_size),
            entity_extract_max_gleaning=int(entity_extract_max_gleaning),
            # Performance tuning (from MongoDB settings)
            llm_model_max_async=int(max_async_llm),
            embedding_func_max_async=int(max_async_embedding),
            embedding_batch_num=int(embedding_batch_size),
            max_parallel_insert=int(max_parallel_insert),
            # Enable caching
            enable_llm_cache=True,
            enable_llm_cache_for_entity_extract=True
        )

        try:
            # Initialize storage backends for this company
            await rag.initialize_storages()
            global _pipeline_status_initialized
            async with _pipeline_init_lock:
                if not _pipeline_status_initialized:
                    logger.info("Initializing global pipeline status (first time)")
                    await initialize_pipeline_status()
                    _pipeline_status_initialized = True
                    logger.info("Pipeline status initialized successfully")

            # Cache the instance
            lightrag_instances[instance_key] = rag
            memory_suffix = " (memories)" if is_memory else ""
            logger.info(f"Initialized LightRAG instance for company: {company_id_str}{memory_suffix}")
            return rag

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to initialize vector search: {error_msg}")
            logger.error(f"Failed to initialize LightRAG for company {company_id_str}: {e}", exc_info=True)
            raise

def _is_memory_document(file_path: str) -> bool:
    """
    Check if a document is an AI-generated memory based on file_path.
    Memories have file_path like: source/ai_generated_memory/file_id
    """
    if not file_path:
        return False
    parts = file_path.split("/")
    return len(parts) >= 2 and parts[1] == "ai_generated_memory"

def get_setting_from_singleton(key: str, default: Any) -> Any:
    """Get setting from MongoDB settings collection"""
    settings = settings_col.find_one({}) or {}
    return settings.get(key, default)

# Routes
@app.on_event("startup")
async def startup_event():
    """Wait for required databases to be ready"""
    storage_backend = "Postgres" if _use_postgres_storage() else "Mongo/mongot"
    logger.info(f"Starting with LightRAG storage backend: {storage_backend}")

    # Always ensure Mongo is reachable for app data (users/companies/settings)
    try:
        client.admin.command('ping')
        logger.info("MongoDB connection successful")
    except Exception as e:
        logger.warning(f"Could not verify MongoDB connection: {e}")

    # Storage-specific readiness
    if _use_postgres_storage():
        _ensure_postgres_env()
        await _wait_for_postgres_ready()
    else:
        # Wait for mongot to be available for vector search
        wait_time = int(os.getenv("MONGODB_VECTOR_SEARCH_WAIT_TIME", "30"))
        logger.info("Waiting for MongoDB vector search (mongot) to be ready...")
        await asyncio.sleep(wait_time)
        try:
            result = client.admin.command('getParameter', 1, 'searchIndexManagementHostAndPort')
            mongot_host = result.get('searchIndexManagementHostAndPort', 'not configured')
            logger.info(f"MongoDB configured with mongot at: {mongot_host}")
        except Exception as e:
            logger.warning(f"Could not verify MongoDB/mongot configuration: {e}")

@app.get("/health")
def health():
    return {"status": "ok", "service": "lightrag-service"}

@app.post("/insert")
async def insert_documents(req: InsertRequest):
    """Insert documents into LightRAG knowledge graph"""
    # Support both company-level and user-level data insertion
    if req.company_id:
        # Direct company insertion (for company-level metadata)
        try:
            company_oid = ObjectId(req.company_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid company_id format")

        company_doc = companies_col.find_one({"_id": company_oid})
        if not company_doc:
            raise HTTPException(status_code=404, detail="Company not found")

        company_id_str = str(company_oid)
        user_id_str = None

    elif req.user:
        # User-based insertion (for user-specific data)
        user_fetch = _find_user_from_identifier(req.user)
        user_doc = user_fetch["doc"]

        try:
            company_oid = ObjectId(user_doc["company_id"])
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid company_id format")

        company_doc = companies_col.find_one({"_id": company_oid})
        if not company_doc:
            raise HTTPException(status_code=404, detail="Company not found")

        company_id_str = str(company_oid)
        user_id_str = str(user_doc["_id"])
    else:
        raise HTTPException(status_code=400, detail="Either company_id or user must be provided")

    # Determine if this is a memory document based on file_path
    is_memory = False
    if req.file_paths and len(req.file_paths) > 0:
        is_memory = _is_memory_document(req.file_paths[0])

    # Get appropriate LightRAG instance (main or memories)
    rag = await get_lightrag_instance(company_id_str, is_memory=is_memory)

    instance_type = "memories" if is_memory else "main"
    logger.info(f"Routing insert to {instance_type} instance for company {company_id_str}")

    # Insert documents
    try:
        logger.info(f"Inserting {len(req.documents)} documents with IDs: {req.ids}")
        logger.info(f"File paths: {req.file_paths}")

        # Call ainsert - it returns a pipeline ID string, not document IDs
        # We use the IDs we provide as the actual document IDs
        pipeline_id = await rag.ainsert(
            req.documents,
            ids=req.ids,
            file_paths=req.file_paths
        )

        logger.info(f"Insert pipeline ID: {pipeline_id}")

        # Return the IDs we provided - these are the actual document IDs in LightRAG
        lightrag_doc_ids = req.ids if req.ids else []

        return {
            "status": "success",
            "message": f"Inserted {len(req.documents)} documents",
            "company_id": company_id_str,
            "user_id": user_id_str,
            "lightrag_doc_ids": lightrag_doc_ids
        }
    except Exception as e:
        logger.error(f"Failed to insert documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Insert failed: {str(e)}")

@app.post("/query")
async def query_lightrag(req: QueryRequest):
    """Query LightRAG with knowledge graph capabilities - returns formatted data and references"""

    # Logging
    logger.info(f"Received query from user identifier: {req.user} and query: {req.query}")

    # Find user and company (from /queryold)
    user_fetch = _find_user_from_identifier(req.user)
    user_doc = user_fetch["doc"]

    try:
        company_oid = ObjectId(user_doc["company_id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid company_id format")

    company_doc = companies_col.find_one({"_id": company_oid})
    if not company_doc:
        raise HTTPException(status_code=404, detail="Company not found")

    # Get LightRAG instance for this company
    company_id_str = str(company_oid)
    user_id_str = str(user_doc["_id"])

    # Get RAG instance
    rag = await get_lightrag_instance(company_id_str)

    # Get query defaults from settings (from /querynew)
    top_k = get_setting_from_singleton("lightrag_query_top_k", 60)
    max_tokens = get_setting_from_singleton("lightrag_query_max_tokens", 30000)
    mode = get_setting_from_singleton("lightrag_query_mode", "hybrid")

    # Configure query parameters
    query_param = QueryParam(
        mode=mode,
        top_k=int(top_k),
        max_total_tokens=int(max_tokens),
        only_need_context=True,
        enable_rerank=False
    )

    try:
        # Build session ID
        today = datetime.utcnow().date().isoformat()
        session_id = f"{user_id_str}:{today}"

        # Get user name
        user_first = user_doc.get("first_name", "")
        user_last = user_doc.get("last_name", "")
        user_name = f"{user_first} {user_last}".strip() or "Unknown User"

        # Get company name
        company_name = company_doc.get("name", "Unknown Company")

        # Perform query
        t0 = datetime.now()
        result = await rag.aquery(req.query, param=query_param)
        latency_ms = int((datetime.now() - t0).total_seconds() * 1000)
        # log result
        logger.info(f"LightRAG query result: {result}")
        # Parse knowledge graph and references (from /querynew)

        entities = []
        relationships = []
        chunks = []
        references = []
        if result is not None:
            entities, relationships, chunks, references = parse_knowledge_graph_and_refs(result)

        return {
            "entities": entities,
            "relationships": relationships,
            "chunks": chunks,
            "references": references,
            "user_id": user_id_str,
            "company_id": company_id_str,
            "session_id": session_id,
            "user_name": user_name,
            "company_name": company_name,
            "latency_ms": latency_ms
        }

    except Exception as e:
        logger.error(f"LightRAG query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

@app.post("/query-memories")
async def query_memories(req: QueryRequest):
    """
    Query ONLY the memories LightRAG instance for a company.
    Returns max 5 most relevant memories.
    """
    logger.info(f"Received memory query from user: {req.user}, query: {req.query}")

    # Find user and company
    user_fetch = _find_user_from_identifier(req.user)
    user_doc = user_fetch["doc"]

    try:
        company_oid = ObjectId(user_doc["company_id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid company_id format")

    company_doc = companies_col.find_one({"_id": company_oid})
    if not company_doc:
        raise HTTPException(status_code=404, detail="Company not found")

    company_id_str = str(company_oid)
    user_id_str = str(user_doc["_id"])

    # Get memory RAG instance (is_memory=True)
    rag = await get_lightrag_instance(company_id_str, is_memory=True)

    # Configure query parameters - limit to 5 memories
    query_param = QueryParam(
        mode="hybrid",
        top_k=5,  # Only retrieve top 5 memories
        max_total_tokens=10000,  # Smaller token limit for memories
        only_need_context=True,
        enable_rerank=False
    )

    try:
        # Perform query on memories instance
        t0 = datetime.now()
        result = await rag.aquery(req.query, param=query_param)
        latency_ms = int((datetime.now() - t0).total_seconds() * 1000)
        logger.info(f"Memory query result: {result}")

        # Parse knowledge graph and references
        entities = []
        relationships = []
        chunks = []
        references = []
        if result is not None:
            entities, relationships, chunks, references = parse_knowledge_graph_and_refs(result)

        return {
            "entities": entities,
            "relationships": relationships,
            "chunks": chunks,
            "references": references,
            "user_id": user_id_str,
            "company_id": company_id_str,
            "latency_ms": latency_ms
        }

    except Exception as e:
        logger.error(f"Memory query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Memory query failed: {str(e)}")

@app.post("/delete")
async def delete_document(req: DeleteRequest):
    """Delete a document from LightRAG knowledge graph"""
    logger.info(f"Starting deletion process for document {req.doc_id}")
    try:
        # Validate company
        company_oid = ObjectId(req.company_id)
        company_doc = companies_col.find_one({"_id": company_oid})
        if not company_doc:
            raise HTTPException(status_code=404, detail="Company not found")

        company_id_str = str(company_oid)

        # Determine if this is a memory document
        is_memory = False
        if req.file_path:
            is_memory = _is_memory_document(req.file_path)

        # Get appropriate LightRAG instance (main or memories)
        rag = await get_lightrag_instance(company_id_str, is_memory=is_memory)

        instance_type = "memories" if is_memory else "main"
        logger.info(f"Deleting document {req.doc_id} from {instance_type} instance for company {company_id_str}")

        # Delete by document ID
        result = await rag.adelete_by_doc_id(req.doc_id)

        logger.info(f"Successfully deleted document {req.doc_id} result {result}")

        return {
            "status": "success",
            "message": f"Deleted document {req.doc_id} from knowledge graph",
            "company_id": company_id_str,
            "doc_id": req.doc_id,
            "found": True
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete document {req.doc_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

@app.post("/bulk-delete")
async def bulk_delete_documents(req: BulkDeleteRequest):
    """Delete multiple documents from LightRAG knowledge graph in one request"""
    logger.info(f"Starting bulk deletion of {len(req.doc_ids)} documents for company {req.company_id}")

    try:
        # Validate company
        company_oid = ObjectId(req.company_id)
        company_doc = companies_col.find_one({"_id": company_oid})
        if not company_doc:
            raise HTTPException(status_code=404, detail="Company not found")

        company_id_str = str(company_oid)

        # Separate doc_ids by whether they're memories or not
        memory_doc_ids = []
        regular_doc_ids = []

        if req.file_paths and len(req.file_paths) == len(req.doc_ids):
            # We have file_paths, so we can properly route each deletion
            for doc_id, file_path in zip(req.doc_ids, req.file_paths):
                if _is_memory_document(file_path):
                    memory_doc_ids.append(doc_id)
                else:
                    regular_doc_ids.append(doc_id)
        else:
            # No file_paths provided, assume all are regular documents (backward compatibility)
            regular_doc_ids = req.doc_ids
            logger.warning("No file_paths provided in bulk delete, assuming all documents are regular (non-memory)")

        # Delete documents and track results
        results = {
            "total": len(req.doc_ids),
            "successful": 0,
            "failed": 0,
            "errors": []
        }

        # Delete from main instance
        if regular_doc_ids:
            rag = await get_lightrag_instance(company_id_str, is_memory=False)
            logger.info(f"Deleting {len(regular_doc_ids)} regular documents from main instance")
            for doc_id in regular_doc_ids:
                try:
                    await rag.adelete_by_doc_id(doc_id)
                    results["successful"] += 1
                    logger.debug(f"Deleted regular document {doc_id}")
                except Exception as e:
                    results["failed"] += 1
                    results["errors"].append({
                        "doc_id": doc_id,
                        "error": str(e)
                    })
                    logger.error(f"Failed to delete regular document {doc_id}: {e}")

        # Delete from memories instance
        if memory_doc_ids:
            rag = await get_lightrag_instance(company_id_str, is_memory=True)
            logger.info(f"Deleting {len(memory_doc_ids)} memory documents from memories instance")
            for doc_id in memory_doc_ids:
                try:
                    await rag.adelete_by_doc_id(doc_id)
                    results["successful"] += 1
                    logger.debug(f"Deleted memory document {doc_id}")
                except Exception as e:
                    results["failed"] += 1
                    results["errors"].append({
                        "doc_id": doc_id,
                        "error": str(e)
                    })
                    logger.error(f"Failed to delete memory document {doc_id}: {e}")

        logger.info(
            f"Bulk delete completed for company {company_id_str}: "
            f"{results['successful']} successful, {results['failed']} failed"
        )

        return {
            "status": "completed",
            "company_id": company_id_str,
            "results": results
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk delete failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Bulk delete failed: {str(e)}")

@app.post("/companies/{company_id}/cleanup")
async def cleanup_company_workspace(company_id: str):
    """
    Complete cleanup of a company's LightRAG workspaces (BOTH main and memories instances)

    This endpoint:
    1. Drops all data from BOTH LightRAG storage instances (main + memories, including cache)
    2. Finalizes and removes both cached LightRAG instances
    3. Drops all MongoDB collections for both workspaces as backup
    4. Cleans up any remaining resources

    Should be called AFTER all documents are deleted from MongoDB
    """
    logger.info(f"Starting workspace cleanup for company {company_id} (main + memories)")

    try:
        # Validate company ID format
        try:
            company_oid = ObjectId(company_id)
            company_id_str = str(company_oid)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid company_id format")

        # We need to cleanup TWO instances: main and memories
        instances_to_cleanup = [
            (company_id_str, False, "main"),
            (f"{company_id_str}_memories", True, "memories")
        ]

        all_drop_results = []
        instances_removed = 0

        # Step 1: Drop all data from BOTH LightRAG storage instances
        for instance_key, is_memory, instance_type in instances_to_cleanup:
            instance_was_cached = instance_key in lightrag_instances

            if instance_was_cached:
                logger.info(f"Cleaning up {instance_type} instance for company {company_id_str}")
                rag = lightrag_instances[instance_key]

                # Define all storage instances that need to be dropped
                storage_list = [
                    ("llm_response_cache", rag.llm_response_cache),
                    ("full_docs", rag.full_docs),
                    ("text_chunks", rag.text_chunks),
                    ("full_entities", rag.full_entities),
                    ("full_relations", rag.full_relations),
                    ("entities_vdb", rag.entities_vdb),
                    ("relationships_vdb", rag.relationships_vdb),
                    ("chunks_vdb", rag.chunks_vdb),
                    ("chunk_entity_relation_graph", rag.chunk_entity_relation_graph),
                    ("doc_status", rag.doc_status),
                ]

                # Drop all storages - this actually deletes the data
                for storage_name, storage in storage_list:
                    if storage:
                        try:
                            result = await storage.drop()
                            all_drop_results.append({
                                "instance": instance_type,
                                "storage": storage_name,
                                "status": result.get("status", "unknown"),
                                "message": result.get("message", "")
                            })
                            logger.info(f"Dropped {instance_type}.{storage_name}: {result}")
                        except Exception as e:
                            error_msg = f"Failed to drop {instance_type}.{storage_name}: {e}"
                            logger.error(error_msg)
                            all_drop_results.append({
                                "instance": instance_type,
                                "storage": storage_name,
                                "status": "error",
                                "message": str(e)
                            })

                # Finalize the storages (closes connections)
                try:
                    await rag.finalize_storages()
                    logger.info(f"Finalized {instance_type} LightRAG instance")
                except Exception as e:
                    logger.error(f"Error finalizing {instance_type} instance: {e}")

                # Remove from cache
                del lightrag_instances[instance_key]
                instances_removed += 1
                logger.info(f"Removed {instance_type} instance from cache")

        # Remove the company-specific locks for both instances
        async with _locks_lock:
            for instance_key, _, instance_type in instances_to_cleanup:
                if instance_key in _company_init_locks:
                    del _company_init_locks[instance_key]
                    logger.info(f"Removed initialization lock for {instance_type}")

        # Step 2: DROP all MongoDB collections for BOTH workspaces
        workspaces = [f"lightrag_{company_id_str}", f"lightrag_{company_id_str}_memories"]
        collections_to_drop = []

        # Find all collections with these workspace prefixes in the LightRAG database
        for collection_name in lightrag_db.list_collection_names():
            for workspace in workspaces:
                if collection_name.startswith(workspace):
                    collections_to_drop.append(collection_name)
                    break

        dropped_count = 0
        for collection_name in collections_to_drop:
            try:
                lightrag_db.drop_collection(collection_name)
                dropped_count += 1
                logger.info(f"Completely removed collection from LightRAG database: {collection_name}")
            except Exception as e:
                logger.error(f"Failed to remove collection {collection_name}: {e}")

        logger.info(
            f"Workspace cleanup completed for company {company_id_str}: "
            f"instances_removed={instances_removed}/2, "
            f"storage_drops_attempted={len(all_drop_results)}, "
            f"collections_dropped={dropped_count}"
        )

        return {
            "status": "success",
            "message": f"Workspace cleaned up for company {company_id_str} (main + memories)",
            "company_id": company_id_str,
            "instances_removed": instances_removed,
            "storage_drop_results": all_drop_results,
            "collections_dropped": dropped_count,
            "collections_list": collections_to_drop
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Workspace cleanup failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

# Migration and utility endpoints

@app.get("/companies/{company_id}/stats")
async def get_company_stats(company_id: str):
    """Get statistics about a company's knowledge graph"""
    try:
        rag = await get_lightrag_instance(company_id)

        # Get stats from various storages
        stats = {
            "company_id": company_id,
            "storage_types": {
                "kv_storage": type(rag.kv_storage).__name__ if hasattr(rag, 'kv_storage') else None,
                "vector_storage": type(rag.vector_storage).__name__ if hasattr(rag, 'vector_storage') else None,
                "graph_storage": type(rag.graph_storage).__name__ if hasattr(rag, 'graph_storage') else None,
                "doc_status_storage": type(rag.doc_status_storage).__name__ if hasattr(rag, 'doc_status_storage') else None,
            }
        }

        # Try to get document count from doc_status_storage
        try:
            if hasattr(rag, 'doc_status_storage'):
                # Get all documents - implementation depends on storage type
                # For MongoDB storage, we'd need to query the collection
                all_docs = await rag.doc_status_storage.get_all()
                stats["document_count"] = len(all_docs) if all_docs else 0
                stats["document_ids"] = list(all_docs.keys()) if all_docs else []
        except Exception as e:
            logger.warning(f"Could not get document stats: {e}")
            stats["document_count"] = "unknown"
            stats["document_ids"] = []

        return stats
    except Exception as e:
        logger.error(f"Failed to get stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# Cleanup on shutdown
@app.on_event("shutdown")
async def shutdown_event():
    """Clean shutdown of LightRAG instances"""
    for company_id, rag in lightrag_instances.items():
        try:
            await rag.finalize_storages()
            logger.info(f"Finalized LightRAG instance for company: {company_id}")
        except Exception as e:
            logger.error(f"Error finalizing LightRAG for company {company_id}: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9001)
