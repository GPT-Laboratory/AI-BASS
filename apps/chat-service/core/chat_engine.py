from __future__ import annotations

from services.enhanced_rag_client import fetch_context
from services.llm_interface import LLMClient
from services.log_client import log_interaction_to_service
from core.settings_provider import SettingsProvider
from core.commands import CommandHandler
from services.conversation_service import ConversationService
from services.web_search_service import WebSearchService

from time import perf_counter
from collections import Counter
from typing import Any, Dict, List, Optional
from datetime import datetime
import difflib
import logging
import locale
import os
import asyncio
from pytz import timezone
from bson import ObjectId

# Configuration constants
PREVIOUS_MESSAGES_TO_FETCH = int(os.getenv("CHAT_HISTORY_MESSAGE_COUNT", "6"))  # Number of previous messages to include in conversation history

# Get logger for this module
logger = logging.getLogger(__name__)

class ChatEngine:
    def __init__(self, llm: LLMClient, settings: SettingsProvider, conversation_service: ConversationService, db):
        self.llm = llm
        self.settings = settings
        self.conversation_service = conversation_service
        self.command_handler = CommandHandler(db)
        self.web_search = WebSearchService()
        self.db = db

    def _offline_match_task(self, user_input: str, task_list: List[dict]) -> dict | None:
        names = [t["task"] for t in task_list if "task" in t]
        lower_q = user_input.lower()
        for t in task_list:
            if t["task"].lower() in lower_q or lower_q in t["task"].lower():
                return t
        best = difflib.get_close_matches(lower_q, [n.lower() for n in names], n=1, cutoff=0.6)
        if best:
            for t in task_list:
                if t["task"].lower() == best[0]:
                    return t
        return None

    async def select_task(self, user_input: str) -> dict | None:
        task_list = self.settings.get_all_tasks()
        task_descriptions = "\n".join(
            [f"- Name: {t['task']}, Description: {t['description']}" for t in task_list]
        )
        prompt = (
            "You are a classifier. Based on the user input below, pick the exactly matching task from the list if there is one.\n\n"
            f"User input:\n\"{user_input}\"\n\n"
            f"Tasks:\n{task_descriptions}\n\n"
            "Reply with only the task name. If none is suitable, reply with \"none\"."
        )
        messages = [
            {"role": "system", "content": "Classify the user request."},
            {"role": "user", "content": prompt},
        ]
        try:
            task_name = (await self.llm.chat_gpt35(messages)).strip()
            cleaned_name = task_name.strip().lower().strip('"').strip("'")
            if cleaned_name == "none":
                return None
            for t in task_list:
                if t["task"].strip().lower() == cleaned_name:
                    return t
            return self._offline_match_task(user_input, task_list)
        except Exception as e:
            logger.warning(f"Task classification failed, using offline matcher: {e}")
            return self._offline_match_task(user_input, task_list)

    @staticmethod
    def _doc_type(doc: Dict[str, Any]) -> str:
        return (
            doc.get("type")
            or (doc.get("metadata") or {}).get("type")
            or (doc.get("meta") or {}).get("type")
            or (doc.get("source") if isinstance(doc.get("source"), str) else None)
            or "unknown"
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    @staticmethod
    def _token_set(text: str) -> set[str]:
        normalized = ChatEngine._normalize_text(text)
        return {tok for tok in normalized.split(" ") if len(tok) >= 3}

    def _is_memory_answer_redundant(
        self,
        memory_answer: str,
        prior_answer: str,
        recent_messages: List[Dict[str, str]],
        lookback: int = 5
    ) -> bool:
        """
        Heuristic redundancy check to suppress repeated memory follow-ups.
        """
        mem_norm = self._normalize_text(memory_answer)
        if not mem_norm:
            return True

        candidates = [prior_answer or ""]
        candidates.extend((m.get("content", "") for m in (recent_messages or [])[-lookback:]))

        mem_tokens = self._token_set(mem_norm)
        for candidate in candidates:
            cand_norm = self._normalize_text(candidate)
            if not cand_norm:
                continue

            if mem_norm == cand_norm:
                return True

            if len(mem_norm) > 40 and (mem_norm in cand_norm or cand_norm in mem_norm):
                return True

            seq_ratio = difflib.SequenceMatcher(None, mem_norm, cand_norm).ratio()
            if seq_ratio >= 0.88:
                return True

            cand_tokens = self._token_set(cand_norm)
            if mem_tokens and len(mem_tokens) >= 8:
                overlap = len(mem_tokens & cand_tokens) / max(len(mem_tokens), 1)
                if overlap >= 0.8:
                    return True

        return False

    @staticmethod
    def _format_recent_window_for_memory_prompt(recent_messages: List[Dict[str, str]], lookback: int = 5) -> str:
        lines = []
        for msg in (recent_messages or [])[-lookback:]:
            role = (msg.get("role", "") or "").upper()
            content = (msg.get("content", "") or "").strip()
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(f"{role}: {content}")
        return "\n".join(lines) if lines else "(No recent messages available)"

    async def respond(
        self,
        user_input: str,
        user_id: str,
        task: str | None = None,
        source: str = "web",
        company_id_override: Optional[str] = None
    ) -> str:
        # Komento?
        if self.command_handler.is_command(user_input):
            cmd = self.command_handler.extract_command(user_input)
            # NOTE: command handlers may still use the phone number.
            return await self.command_handler.handle_command(cmd, user_id)

        # Fetch conversation history early so we can use it for RAG query optimization and web search classification
        recent_messages = self.conversation_service.get_conversation_for_llm(user_id, limit=PREVIOUS_MESSAGES_TO_FETCH)
        logger.info(f"Fetched {len(recent_messages)} conversation history messages for context")

        # Extract user_id and company_id from the data for token tracking
        user_doc = self.db["users"].find_one({"phone_number": user_id})
        company_id = user_doc.get("company_id") if user_doc else None
        if not company_id and company_id_override:
            company_id = company_id_override

        # Fetch company environment, handling ObjectId conversion
        company_env = "development"  # Default fallback
        if company_id:
            try:
                # Convert to ObjectId if it's a string
                if isinstance(company_id, str):
                    company_id_obj = ObjectId(company_id)
                else:
                    company_id_obj = company_id

                company_doc = self.db["companies"].find_one({"_id": company_id_obj})
                if company_doc:
                    company_env = company_doc.get("environment", "development")
                    logger.info(f"Found company with environment: {company_env}")
                else:
                    logger.warning(f"Company not found for company_id: {company_id}")
            except Exception as e:
                logger.error(f"Error fetching company environment for company_id {company_id}: {e}")

        # Create user context dict for token tracking (passed to all LLM calls)
        user_context = {
            "user_id": user_id,
            "company_id": company_id,
            "company_env": company_env
        }

        # Hae RAG + konteksti (with conversation history for query optimization) - MAIN only
        data = await fetch_context(
            user_input,
            user_id,
            self.llm,
            recent_messages,
            user_context,
            use_main=True,
            use_memories=False,
            enable_query_opt=os.getenv("RAG_OPTIMIZE_QUERY", "true").lower() == "true"
        )
        logger.info("Fetched data (main only): " + str(data))

        base_context = data.get("context", "") or ""
        user_system_prompt = user_doc.get("system_prompt") or ""
        user_name = data.get("user_name", "") or "Not defined"
        company_name = data.get("company_name", "") or "Not defined"
        user_desc = user_doc.get("description") or "Not defined"
        global_prompt = self.settings.get_global_system_prompt() or ""

        # Get current datetime in a format that's clear for the LLM
        now = datetime.now(timezone("Europe/Helsinki"))
        datetime_str = now.strftime("Current date and time (Finnish time): %Y-%m-%d %H:%M")

        # Prepare RAG context with user/company info
        combined_context = base_context

        # Check if web search is needed
        web_search_results = ""
        web_search_query = None
        web_search_results_list = []
        if hasattr(self.llm, 'classify_web_search') and self.web_search:
            try:
                web_search_decision = await self.llm.classify_web_search(user_input, combined_context, recent_messages, datetime_str, user_context)
                logger.info(f"Web search classification for '{user_input}': {web_search_decision.requires_web_search}")

                if web_search_decision.requires_web_search and web_search_decision.search_query:
                    web_search_query = web_search_decision.search_query
                    logger.info(f"Using optimized search query: '{web_search_query}'")
                    try:
                        search_results = await self.web_search.search(web_search_query)
                        if search_results:
                            web_search_results_list = search_results  # Store for debug info
                            web_search_results = self.web_search.format_search_results(web_search_query, search_results)
                            logger.info(f"Web search completed, found {len(search_results)} results")
                        else:
                            logger.info("Web search returned no results, continuing without web search")
                    except Exception as search_e:
                        logger.error(f"Web search execution failed: {search_e}, continuing without web search")
                        # Continue without web search results
                elif web_search_decision.requires_web_search and not web_search_decision.search_query:
                    logger.warning("Web search was requested but no search query was generated, continuing without web search")
            except Exception as e:
                logger.error(f"Web search classification failed: {e}, continuing without web search")
                # Continue without web search
        elif not hasattr(self.llm, 'classify_web_search'):
            logger.debug("Web search classification not available")
        elif not self.web_search:
            logger.warning("Web search service not initialized")        # Add web search results to context if available
        if web_search_results:
            try:
                combined_context += f"\n\n{web_search_results}"
                logger.debug(f"Added web search results to context ({len(web_search_results)} chars)")
            except Exception as e:
                logger.error(f"Failed to add web search results to context: {e}, continuing without web search results")

        # Build system prompt with RAG context
        # System prompt now includes RAG context instead of embedding it in user messages
        if user_system_prompt and global_prompt:
            base_system_prompt = f"{global_prompt}\n\n{user_system_prompt}"
        elif user_system_prompt:
            base_system_prompt = user_system_prompt
        elif global_prompt:
            base_system_prompt = global_prompt
        else:
            base_system_prompt = "Use the given context to answer the user."

        base_system_prompt = f"{base_system_prompt}\n\n{datetime_str}\n\nUser: {user_name}\nDescription: {user_desc}\nCompany: {company_name}"

        # Add RAG context to system prompt
        if combined_context:
            system_prompt = f"{base_system_prompt}\n\nPlease make sure to mark references after sentences and or paragraphs using loose IEEE style citations like [n] [n] [n], where n is the reference number or letter, if it is based on the provided context.\n\nRelevant context: {combined_context}"
        else:
            system_prompt = base_system_prompt

        # Task handling (if needed, apply to current user message)
        task_data = await self.select_task(user_input)
        task = task_data["task"] if task_data else None
        task_template = task_data["prompt"] if task_data else None

        current_user_message = user_input
        if task_template:
            # For tasks, we can modify the current user message
            current_user_message = task_template.replace("{{content}}", "").replace("{{user_input}}", user_input).strip()

        # Conversation history was already fetched earlier for web search classification
        # No need to fetch again here

        # Build traditional conversation format
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(recent_messages)  # Add conversation history
        messages.append({"role": "user", "content": current_user_message})  # Add current message

        logger.info(f"System prompt length: {len(system_prompt)} chars")
        logger.info(f"Conversation messages: {len(recent_messages)} history + 1 current = {len(messages)-1} total")
        logger.info(f"Current user message length: {len(current_user_message)} chars")

        # Log full LLM request for debugging
        logger.info(f"LLM request messages: {messages}")

        # LLM-vastaus ja latenssi
        t0 = perf_counter()
        logger.info(f"Starting LLM request for user: {user_id}")
        answer = await self.llm.chat(messages, user_context)
        latency_ms = int((perf_counter() - t0) * 1000)
        logger.info(f"LLM response completed in {latency_ms}ms")

        # Optional memories follow-up
        memory_answer = ""
        memory_sources_used: List[Dict[str, Any]] = []
        mem_references = []
        mem_latency_ms = 0
        try:
            memories_data = await fetch_context(
                user_input,
                user_id,
                self.llm,
                recent_messages,
                user_context,
                use_main=False,
                use_memories=True
            )
            mem_references = memories_data.get("references", []) or []
            mem_context = memories_data.get("context", "") or ""
            if mem_references and mem_context.strip():
                recent_window_text = self._format_recent_window_for_memory_prompt(recent_messages, lookback=5)
                # Build follow-up prompt referencing prior answer
                mem_messages = [{"role": "system", "content": system_prompt}]
                mem_messages.extend(recent_messages)
                mem_messages.append({"role": "assistant", "content": answer})
                mem_messages.append({
                    "role": "user",
                    "content": (
                        "Additional memories were found. Decide whether a second memory message should be sent.\n"
                        "STRICT RULES:\n"
                        "1) Do not repeat content that appears in the prior answer or the LAST_5_MESSAGES.\n"
                        "2) If the memory relevance is weak, generic, or uncertain, do NOT send a memory addendum.\n"
                        "3) Only send addendum when memories add clear, actionable, and new value to the current user request.\n"
                        "4) If you send it, keep it concise (1-3 sentences), in the same language, and aligned with the conversation tone.\n"
                        "5) If the memory has been mentioned recently, reply EXACTLY: NO_RELEVANT_MEMORIES\n\n"
                        f"PRIOR_ANSWER:\n{answer}\n\n"
                        f"LAST_5_MESSAGES:\n{recent_window_text}\n\n"
                        f"MEMORIES:\n{mem_context}"
                    )
                })
                t1 = perf_counter()
                memory_answer = await self.llm.chat(mem_messages, user_context)
                mem_latency_ms = int((perf_counter() - t1) * 1000)
                logger.info(f"Memory follow-up LLM completed in {mem_latency_ms}ms")

                # Collect memory sources
                for ref in mem_references:
                    ref_number = ref.get("number", "")
                    ref_type = ref.get("type", "")
                    ref_title = ref.get("title", "")
                    ref_source = ref.get("source", "")
                    ref_content = ""
                    for chunk in memories_data.get("chunks", []):
                        if str(chunk.get("reference_id", "")) == str(ref_number):
                            ref_content = chunk.get("content", "")
                            break
                    if ref_type:
                        memory_sources_used.append({
                            "reference_id": ref_number,
                            "type": ref_type,
                            "title": ref_title,
                            "source": ref_source,
                            "content": ref_content
                        })
        except Exception as e:
            logger.warning(f"Memory follow-up failed or skipped: {e}")

        # Sanitize memory_answer: skip if effectively empty or just quotes
        cleaned_memory_answer = memory_answer.strip().strip('"').strip("'")
        if cleaned_memory_answer.upper() == "NO_RELEVANT_MEMORIES":
            cleaned_memory_answer = ""

        if cleaned_memory_answer and self._is_memory_answer_redundant(
            cleaned_memory_answer,
            answer,
            recent_messages,
            lookback=5
        ):
            logger.info("Suppressing memory follow-up due to redundancy with prior answer/recent messages")
            cleaned_memory_answer = ""

        if not cleaned_memory_answer:
            memory_answer = ""
            memory_sources_used = []
            mem_references = []
            mem_latency_ms = 0
        else:
            memory_answer = cleaned_memory_answer

        # Build combined sources list: documents from RAG + websites from web search
        sources_used = []
        mem_references: List[Dict[str, Any]] = []

        # Add document sources from RAG references
        references = data.get("references", [])
        for ref in references:
            ref_number = ref.get("number", "")
            ref_type = ref.get("type", "")
            ref_title = ref.get("title", "")
            ref_source = ref.get("source", "")

            # each chunk has reference_id and content, find matching reference_id to ref_number and then get content
            # Note: ref_number is an integer from the LightRAG service, but chunk reference_id is a string
            ref_content = ""
            chunks = data.get("chunks", [])
            for chunk in chunks:
                # Convert both to string for comparison to handle int/string mismatch
                if str(chunk.get("reference_id", "")) == str(ref_number):
                    ref_content = chunk.get("content", "")
                    break

            if ref_type:
                sources_used.append({
                    "reference_id": ref_number,
                    "type": ref_type,  # e.g., "google_drive_file"
                    "title": ref_title,  # e.g., "Business environment.docx"
                    "source": ref_source,  # MongoDB ObjectId or other identifier
                    "content": ref_content # Actual content of the chunk
                })

        if references:
            logger.info(f"Added {len(references)} document sources from RAG")

        # Add website sources programmatically if web search was used
        if web_search_results_list:
            sources_used.extend(self.web_search.format_search_results_as_refs(web_search_results_list))
            logger.info(f"Added {len(web_search_results_list)} website sources from web search")

        logger.info(f"Total sources (documents + websites): {len(sources_used)}")

        # --- Metrics (MongoID + session_id derived from MongoID) ---
        metrics = {
            "context_length": len(combined_context),
            "question_length": len(user_input),
            "answer_length": len(answer or ""),
            "latency_ms": latency_ms,

            "user_id": user_id,
            "company_id": company_id,
            "company_env": company_env,
            "session_id": data.get("session_id") or "",

            "rag_documents_count": len(references) + len(mem_references),
            "rag_source_count": len(references) + len(mem_references),
        }

        try:
            asyncio.create_task(log_interaction_to_service({
                "task": task or "",
                "question": user_input,
                "response": answer,
                "context_used": combined_context,
                "system_prompt_used": system_prompt,
                "task_prompt_used": task_template or "",
                "metrics": metrics,
                "source": source,  # Track whether this came from whatsapp or web
                "rag_references": [s for s in (sources_used + memory_sources_used) if s.get("source")],  # include RAG doc refs with source ids
            }))
        except Exception as e:
            logger.warning(f"Failed to dispatch log task: {e}")

        # Store user message and assistant response in conversation history
        self.conversation_service.add_user_message(user_id, user_input)
        self.conversation_service.add_assistant_message(user_id, answer, latency_ms)
        if memory_answer:
            self.conversation_service.add_assistant_message(user_id, memory_answer, mem_latency_ms)

        # Return enhanced response with debug info and sources
        debug_info = {
            "messages_sent_to_llm": messages,
            "system_prompt": system_prompt,
            "conversation_history_count": len(recent_messages),
            "current_user_message": current_user_message,
            "task_applied": task,
            "task_template": task_template,
            "rag_context_length": len(combined_context),
            "web_search_used": bool(web_search_results),
        }

        # Add web search details only if web search was actually used
        if web_search_results and web_search_query:
            debug_info["web_search_query"] = web_search_query
            debug_info["web_search_results"] = [
                {
                    "title": result.get("title", ""),
                    "href": result.get("href", ""),
                    "snippet": result.get("snippet", "")[:150] + "..." if len(result.get("snippet", "")) > 150 else result.get("snippet", "")
                }
                for result in web_search_results_list
            ]

        if source != "web" and memory_answer.strip():
            answer = f"{answer}\n\n{memory_answer}"

        return {
            "answer": answer,
            "memory_answer": memory_answer,
            "debug_info": debug_info,
            "sources_used": sources_used,
            "memory_sources_used": memory_sources_used
        }
