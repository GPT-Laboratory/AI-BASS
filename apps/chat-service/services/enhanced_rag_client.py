"""
RAG client for LightRAG service
"""

from __future__ import annotations

import aiohttp
import asyncio
import os
import logging
from typing import Dict, Any, Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .llm_interface import LLMClient
from collections import OrderedDict

logger = logging.getLogger(__name__)

# Configuration
LIGHTRAG_SERVICE_BASE = os.getenv("LIGHTRAG_SERVICE_URL", "http://lightrag-service:9001")
LIGHTRAG_URL = f"{LIGHTRAG_SERVICE_BASE}/query"
LIGHTRAG_MEMORIES_URL = f"{LIGHTRAG_SERVICE_BASE}/query-memories"

async def fetch_context(
    query: str,
    user_identifier: str,
    llm_client: Optional['LLMClient'] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    user_context: Optional[Dict[str, str]] = None,
    use_main: bool = True,
    use_memories: bool = True,
    enable_query_opt: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Fetch context from LightRAG service and format the response.

    This function can query TWO separate LightRAG instances:
    1. Main instance - regular documents, full query (use_main=True)
    2. Memories instance - AI-generated memories, max 5 results (use_memories=True)

    Both results are combined before being returned to the chat engine.

    Args:
        query: The user's query
        user_identifier: User ID for context
        llm_client: Optional LLM client for query optimization
        conversation_history: Optional conversation history for query optimization
        user_context: Optional user context for query optimization
    """
    # Optimize query using LLM if available
    optimized_query = query
    if enable_query_opt is None:
        enable_query_opt = os.getenv("RAG_OPTIMIZE_QUERY", "true").lower() == "true"

    if llm_client and enable_query_opt:
        try:
            optimized_query = await llm_client.optimize_rag_query(query, conversation_history, user_context)
            logger.info(f"Original query: '{query}'")
            logger.info(f"Optimized query: '{optimized_query}'")
        except Exception as e:
            logger.warning(f"Query optimization failed, using original query: {e}")
            optimized_query = query

    payload = {
        "query": optimized_query,
        "user": user_identifier
    }

    async with aiohttp.ClientSession() as session:
        try:
            tasks = []
            if use_main:
                tasks.append(session.post(LIGHTRAG_URL, json=payload))
            else:
                tasks.append(None)
            if use_memories:
                tasks.append(session.post(LIGHTRAG_MEMORIES_URL, json=payload))
            else:
                tasks.append(None)

            results = await asyncio.gather(*[t for t in tasks if t is not None], return_exceptions=True) if any(tasks) else []
            # map back
            main_resp = results[0] if use_main else None
            memories_resp = results[1 if use_main else 0] if use_memories else None

            main_result = {}
            if use_main:
                if isinstance(main_resp, Exception):
                    logger.error(f"Main LightRAG query failed: {main_resp}")
                elif main_resp.status != 200:
                    text = await main_resp.text()
                    logger.error(f"Main LightRAG service error: {main_resp.status} - {text}")
                else:
                    main_result = await main_resp.json()

            memories_result = {}
            if use_memories:
                if isinstance(memories_resp, Exception):
                    logger.warning(f"Memories query failed (non-critical): {memories_resp}")
                elif memories_resp.status != 200:
                    text = await memories_resp.text()
                    logger.warning(f"Memories service error (non-critical): {memories_resp.status} - {text}")
                else:
                    memories_result = await memories_resp.json()

            if use_main and not main_result:
                return _get_error_response(user_identifier, "LightRAG service error")

            # Combine results from selected instances
            combined_entities = main_result.get("entities", []) if use_main else []
            combined_relationships = main_result.get("relationships", []) if use_main else []
            combined_chunks = main_result.get("chunks", []) if use_main else []
            combined_references = main_result.get("references", []) if use_main else []

            # Add memories data if available
            if use_memories and memories_result:
                logger.info(f"Memories results: {memories_result}")
                memory_entities = memories_result.get("entities", [])
                memory_relationships = memories_result.get("relationships", [])
                memory_chunks = memories_result.get("chunks", [])
                memory_references = memories_result.get("references", [])

                max_ref_id = 100
                if combined_references:
                    try:
                        max_ref_id = max(int(ref.get("number", 0)) for ref in combined_references)
                    except (ValueError, TypeError):
                        max_ref_id = 100
                for ref in memory_references:
                    try:
                        ref["number"] = int(ref["number"]) + max_ref_id
                    except (ValueError, TypeError):
                        pass
                for chunk in memory_chunks:
                    try:
                        chunk["reference_id"] = str(int(chunk["reference_id"]) + max_ref_id)
                    except (ValueError, TypeError):
                        pass

                combined_entities.extend(memory_entities)
                combined_relationships.extend(memory_relationships)
                combined_chunks.extend(memory_chunks)
                combined_references.extend(memory_references)

            # Group and format chunks
            grouped_chunks = _groupChunksByReferenceId(combined_chunks)
            formatted_context = _format_to_context(combined_entities, combined_relationships, grouped_chunks)

            # Build response compatible with chat_engine expectations
            return {
                "context": formatted_context,
                "user_id": main_result.get("user_id", user_identifier),
                "company_id": main_result.get("company_id", ""),
                "session_id": main_result.get("session_id", ""),
                "user_name": main_result.get("user_name", ""),
                "company_name": main_result.get("company_name", ""),
                #"entities": combined_entities,
                #"relationships": combined_relationships,
                "chunks": grouped_chunks,
                "references": combined_references
            }

        except Exception as e:
            logger.error(f"LightRAG fetch failed: {e}")
            return _get_error_response(user_identifier, "LightRAG unavailable")

def _groupChunksByReferenceId(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Group chunks by their reference_id, concatenating contents of chunks with the same reference_id.
    """
    grouped_chunks = {}
    for chunk in chunks:
        reference_id = chunk.get("reference_id", "")
        content = chunk.get("content", "")
        if reference_id in grouped_chunks:
            grouped_chunks[reference_id]["content"] += f"\n{content}"
        else:
            grouped_chunks[reference_id] = {
                "reference_id": reference_id,
                "content": content
            }

    grouped_chunks = OrderedDict(sorted(grouped_chunks.items(), key=lambda item: int(item[0])))

    return list(grouped_chunks.values())

def _format_to_context(entities: List[Dict[str, Any]], relationships: List[Dict[str, Any]], chunks: List[Dict[str, Any]]) -> str:
    """
    Format knowledge graph entities into context string.
    Each entity is formatted as:
    entity:
    description
    """
    formatted_parts = []
    for entity in entities:
        entity_name = entity.get("entity", "")
        description = entity.get("description", "")
        # For now, lets not include entities to avoid overloading the context
        #formatted_parts.append(f"{entity_name}: {description}")

    for relationship in relationships:
        entity1 = relationship.get("entity1", "")
        entity2 = relationship.get("entity2", "")
        description = relationship.get("description", "")
        # For now, lets not include relationships to avoid overloading the context
        #formatted_parts.append(f"{entity1} <-> {entity2}: {description}")

    for chunk in chunks:
        reference_id = chunk.get("reference_id", "")
        content = chunk.get("content", "")
        formatted_parts.append(f"\n\n--\n\n[{reference_id}]: {content}")

    return "".join(formatted_parts)

def _get_error_response(user_identifier: str, error_message: str) -> Dict[str, Any]:
    """Create a standardized error response"""
    return {
        "context": error_message,
        "system_prompt": None,
        "user_id": user_identifier,
        "company_id": "",
        "session_id": "",
        "user_name": "",
        "company_name": "",
        "references": []
    }

async def get_rag_service_status() -> Dict[str, Any]:
    """Get status of LightRAG service"""
    status = {
        "lightrag": {"available": False, "url": LIGHTRAG_URL}
    }

    # Check LightRAG service
    try:
        async with aiohttp.ClientSession() as session:
            health_url = LIGHTRAG_URL.replace("/query", "/health")
            async with session.get(health_url, timeout=5) as resp:
                status["lightrag"]["available"] = resp.status == 200
                if resp.status == 200:
                    status["lightrag"]["response"] = await resp.json()
    except Exception as e:
        status["lightrag"]["error"] = str(e)

    return status
