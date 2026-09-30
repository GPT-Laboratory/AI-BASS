from __future__ import annotations

import os
import asyncio
import logging
import random
from typing import List, Dict, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
from openai import AsyncOpenAI, AsyncAzureOpenAI
from openai import APIConnectionError, APITimeoutError, APIStatusError
from pymongo import MongoClient
from .llm_interface import LLMClient

# Get logger for this module
logger = logging.getLogger(__name__)

# ENV config
CHAT_TIMEOUT_S = float(os.getenv("CHAT_TIMEOUT_SECONDS", "30"))
CHAT_MAX_RETRIES = int(os.getenv("CHAT_MAX_RETRIES", "3"))
CHAT_BACKOFF_S = float(os.getenv("CHAT_BACKOFF_SECONDS", "0.8"))
CHAT_COMPLETION_MAX_TOKENS = int(os.getenv("CHAT_COMPLETION_MAX_TOKENS", "768"))

CLASSIFIER_MODEL = os.getenv("GPT_CLASSIFIER_MODEL", "gpt-4o-mini")
CHAT_MODEL = os.getenv("GPT_CHAT_MODEL", "gpt-4o")

class WebSearchDecision(BaseModel):
    requires_web_search: bool
    search_query: str = ""  # Only populated if requires_web_search is True

class MemoryAnalysisResult(BaseModel):
    has_important_content: bool
    memories: List[str]

class ChatGPTClient(LLMClient):
    def __init__(self, mongo_client: Optional[MongoClient] = None):
        self.azure_api_key = os.getenv("AZURE_API_KEY")
        self.azure_endpoint = os.getenv("AZURE_ENDPOINT")
        self.azure_version = os.getenv("AZURE_VERSION", "2024-02-01")
        self.azure_client = AsyncAzureOpenAI(
            api_key=self.azure_api_key or "unset",
            azure_endpoint=self.azure_endpoint or "unset",
            api_version=self.azure_version,
            timeout=CHAT_TIMEOUT_S,
            max_retries=0,
        )

        # MongoDB for token usage tracking
        self.mongo_client = mongo_client
        self.usage_collection = None
        if mongo_client:
            self.usage_collection = mongo_client["companydb"]["token_usage"]
            logger.info("Token usage tracking enabled")

        # Log initialization
        logger.info("ChatGPTClient initialized")
        logger.info(f"Chat model: {CHAT_MODEL}")
        logger.info(f"Classifier model: {CLASSIFIER_MODEL}")

    def _save_token_usage(
        self,
        model: str,
        provider: str,
        success: bool,
        call_type: str = "other",
        usage_data: Optional[Dict] = None,
        error: Optional[str] = None,
        user_context: Optional[Dict[str, str]] = None
    ):
        """Save token usage data to MongoDB."""
        if self.usage_collection is None:
            return

        try:
            doc = {
                "timestamp": datetime.now(timezone.utc),
                "model": model,
                "provider": provider,  # 'openai' or 'azure'
                "success": success,
                "call_type": call_type,  # web_search_classification, rag_query_enhancement, memory_generation, final_response_for_user, other
            }

            # Add user and company context if provided
            if user_context:
                if user_context.get("user_id"):
                    doc["user_id"] = user_context["user_id"]
                if user_context.get("company_id"):
                    doc["company_id"] = user_context["company_id"]
                if user_context.get("company_env"):
                    doc["company_env"] = user_context["company_env"]

            if success and usage_data:
                # Save detailed token usage from the API response
                doc["usage"] = {
                    "prompt_tokens": usage_data.get("prompt_tokens", 0),
                    "completion_tokens": usage_data.get("completion_tokens", 0),
                    "total_tokens": usage_data.get("total_tokens", 0),
                }
                # Include detailed breakdowns if available
                if "prompt_tokens_details" in usage_data:
                    doc["usage"]["prompt_tokens_details"] = usage_data["prompt_tokens_details"]
                    # Extract cached_tokens if available
                    if "cached_tokens" in usage_data["prompt_tokens_details"]:
                        doc["usage"]["cached_tokens"] = usage_data["prompt_tokens_details"]["cached_tokens"]
                if "completion_tokens_details" in usage_data:
                    doc["usage"]["completion_tokens_details"] = usage_data["completion_tokens_details"]

            if error:
                doc["error"] = error

            self.usage_collection.insert_one(doc)
        except Exception as e:
            logger.error(f"Failed to save token usage: {e}")

    async def _try_completion(self, client, model: str, messages: List[Dict[str, str]], *, temperature: float, max_tokens: int) -> tuple[str, Dict]:
        """Try a completion call and return both content and usage data."""
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = (resp.choices[0].message.content or "").strip()
        # Extract usage data from response
        usage_data = {}
        if resp.usage:
            usage_data = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            }
            # Include detailed breakdowns if available
            if hasattr(resp.usage, "prompt_tokens_details") and resp.usage.prompt_tokens_details:
                usage_data["prompt_tokens_details"] = resp.usage.prompt_tokens_details.model_dump()
            if hasattr(resp.usage, "completion_tokens_details") and resp.usage.completion_tokens_details:
                usage_data["completion_tokens_details"] = resp.usage.completion_tokens_details.model_dump()

        return content, usage_data

    async def _try_parse(self, client, model: str, messages: List[Dict[str, str]], response_format, *, temperature: float, max_tokens: int):
        """Try a parse call and return both parsed result and usage data."""
        resp = await client.beta.chat.completions.parse(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        parsed = resp.choices[0].message.parsed
        # Extract usage data from response
        usage_data = {}
        if resp.usage:
            usage_data = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            }
            # Include detailed breakdowns if available
            if hasattr(resp.usage, "prompt_tokens_details") and resp.usage.prompt_tokens_details:
                usage_data["prompt_tokens_details"] = resp.usage.prompt_tokens_details.model_dump()
            if hasattr(resp.usage, "completion_tokens_details") and resp.usage.completion_tokens_details:
                usage_data["completion_tokens_details"] = resp.usage.completion_tokens_details.model_dump()

        return parsed, usage_data

    async def _round(self, model: str, messages: List[Dict[str, str]], *, temperature: float, max_tokens: int, call_type: str = "other", user_context: Optional[Dict[str, str]] = None) -> str:
        providers = []
        providers.append(("azure", self.azure_client))

        last_err: Exception | None = None
        for i, (provider_name, client) in enumerate(providers):
            try:
                logger.debug(f"Trying {provider_name} provider (attempt {i+1}/{len(providers)})")
                content, usage_data = await asyncio.wait_for(
                    self._try_completion(client, model, messages, temperature=temperature, max_tokens=max_tokens),
                    timeout=CHAT_TIMEOUT_S * 1.5,
                )
                # Save successful usage
                self._save_token_usage(model, provider_name, success=True, call_type=call_type, usage_data=usage_data, user_context=user_context)
                return content
            except (APITimeoutError, APIConnectionError, APIStatusError, asyncio.TimeoutError) as e:
                logger.warning(f"{provider_name} provider failed: {type(e).__name__}: {e}")
                # Save failed usage
                self._save_token_usage(model, provider_name, success=False, call_type=call_type, error=f"{type(e).__name__}: {str(e)}", user_context=user_context)
                last_err = e
            except Exception as e:
                logger.error(f"{provider_name} provider unexpected error: {type(e).__name__}: {e}")
                # Save failed usage
                self._save_token_usage(model, provider_name, success=False, call_type=call_type, error=f"{type(e).__name__}: {str(e)}", user_context=user_context)
                last_err = e
        if last_err:
            raise last_err
        raise RuntimeError("No LLM provider available")

    async def _with_retries(self, model: str, messages: List[Dict[str, str]], *, temperature: float, max_tokens: int, call_type: str = "other", user_context: Optional[Dict[str, str]] = None) -> str:
        last: Exception | None = None
        for attempt in range(CHAT_MAX_RETRIES + 1):
            try:
                return await self._round(model, messages, temperature=temperature, max_tokens=max_tokens, call_type=call_type, user_context=user_context)
            except (APITimeoutError, APIConnectionError, APIStatusError, asyncio.TimeoutError) as e:
                last = e
                if attempt < CHAT_MAX_RETRIES:
                    backoff = CHAT_BACKOFF_S * (2 ** attempt) * (1 + random.uniform(0, 0.25))
                    await asyncio.sleep(backoff)
                else:
                    raise
            except Exception as e:
                last = e
                if attempt < CHAT_MAX_RETRIES:
                    backoff = CHAT_BACKOFF_S * (2 ** attempt) * (1 + random.uniform(0, 0.25))
                    await asyncio.sleep(backoff)
                else:
                    raise
        if last:
            raise last

    async def chat(self, prompt: List[Dict[str, str]], call_type: str = "final_response_for_user", user_context: Optional[Dict[str, str]] = None) -> str:
        return await self._with_retries(CHAT_MODEL, prompt, temperature=0.2, max_tokens=CHAT_COMPLETION_MAX_TOKENS, call_type=call_type, user_context=user_context)

    async def chat_gpt35(self, prompt: List[Dict[str, str]], call_type: str = "other", user_context: Optional[Dict[str, str]] = None) -> str:
        return await self._with_retries(CLASSIFIER_MODEL, prompt, temperature=0.0, max_tokens=64, call_type=call_type, user_context=user_context)

    async def _parse_with_azure_first(self, model: str, messages: List[Dict[str, str]], response_format, *, temperature: float, max_tokens: int, call_type: str = "other", user_context: Optional[Dict[str, str]] = None):
        """Parse with structured output, trying Azure first if configured."""
        providers = []
        providers.append(("azure", self.azure_client))

        last_err: Exception | None = None
        for provider_name, client in providers:
            try:
                parsed, usage_data = await asyncio.wait_for(
                    self._try_parse(client, model, messages, response_format, temperature=temperature, max_tokens=max_tokens),
                    timeout=CHAT_TIMEOUT_S * 1.5,
                )
                # Save successful usage
                self._save_token_usage(model, provider_name, success=True, call_type=call_type, usage_data=usage_data, user_context=user_context)
                return parsed
            except (APITimeoutError, APIConnectionError, APIStatusError, asyncio.TimeoutError) as e:
                # Save failed usage
                self._save_token_usage(model, provider_name, success=False, call_type=call_type, error=f"{type(e).__name__}: {str(e)}", user_context=user_context)
                last_err = e
            except Exception as e:
                # Save failed usage
                self._save_token_usage(model, provider_name, success=False, call_type=call_type, error=f"{type(e).__name__}: {str(e)}", user_context=user_context)
                last_err = e
        if last_err:
            raise last_err
        raise RuntimeError("No LLM provider available")

    async def classify_web_search(self, user_input: str, context: str = "", conversation_history: list = None, datetime_str: str = "", user_context: Optional[Dict[str, str]] = None) -> WebSearchDecision:
        """
        Classify if the user input requires web search and generate optimized search query.
        Returns WebSearchDecision with requires_web_search bool and search_query string.

        Args:
            user_input: The current user message
            context: Available RAG context
            conversation_history: Recent conversation messages for better context understanding
        """
        # Build system prompt with classification instructions
        system_prompt = f"""You are a classifier that determines if web search is needed and generates optimized search queries.

{datetime_str}

Analyze the conversation and determine if the current user message requires web search.

Set requires_web_search to true if the message:
- Asks about current events, news, or recent developments
- Requests current prices, stock information, or market data
- Needs real-time information (weather, sports scores, etc.)
- Asks about recent updates to software, products, or services
- Requires information that changes frequently
- Cannot be answered with the available context
- Is a follow-up question about a topic that requires real-time data (consider conversation history)

Set requires_web_search to false if the message:
- Can be answered with general knowledge
- Is about historical facts or established information
- Is a personal question or conversational
- Asks about concepts, definitions, or explanations
- Can be answered with the available context
- Is a follow-up that can be answered based on previous context

If requires_web_search is true, provide a search_query that:
- Is optimized for web search engines
- Uses relevant keywords from the user's question
- Removes conversational elements
- Is clear and specific
- Is in the same language as the user's question
- Incorporates context from conversation history if it helps clarify the search intent

If requires_web_search is false, leave search_query empty."""

        # Build messages array with conversation history
        messages = [{"role": "system", "content": system_prompt}]

        # Add recent conversation history if available (last 6 messages = 3 exchanges)
        if conversation_history and len(conversation_history) > 0:
            for msg in conversation_history[-6:]:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role and content:
                    # Truncate very long messages to keep token count reasonable
                    truncated_content = content[:500] + "..." if len(content) > 500 else content
                    messages.append({"role": role, "content": truncated_content})

        # Add context information and current user message
        context_info = f"Available context: {context[:500] + '...' if len(context) > 500 else context}" if context else "No additional context available."
        current_message = f"{context_info}\n\nCurrent user message: {user_input}"
        messages.append({"role": "user", "content": current_message})

        try:
            logger.debug(f"Classifying web search need for: {user_input[:50]}...")
            result = await self._parse_with_azure_first(
                CLASSIFIER_MODEL,
                messages,
                WebSearchDecision,
                temperature=0.0,
                max_tokens=128,  # Increased for search query generation
                call_type="web_search_classification",
                user_context=user_context
            )
            logger.debug(f"Web search classification: {result.requires_web_search}, query: '{result.search_query}'")
            return result
        except Exception as e:
            logger.warning(f"Web search classification failed: {e}")
            return WebSearchDecision(requires_web_search=False, search_query="")

    async def optimize_rag_query(self, user_input: str, conversation_history: list = None, user_context: Optional[Dict[str, str]] = None) -> str:
        """
        Optimize a user message into a concise, relevant factual search query for RAG.

        Args:
            user_input: The current user message
            conversation_history: Recent conversation messages for context

        Returns:
            Optimized search query string
        """
        # Build system prompt for query optimization
        system_prompt = """You are a query optimizer for a knowledge base search system.

Your task is to rewrite the user's message as a concise, relevant, factual search query that will retrieve the most relevant information from a knowledge base.

Guidelines:
- Keep the query focused and specific
- Remove conversational elements and pleasantries
- Preserve key entities, concepts, and relationships
- If it's a follow-up question, incorporate necessary context from conversation history
- Use clear, descriptive terms
- Keep the same language as the user's message
- Make it suitable for semantic search

Return ONLY the optimized query, nothing else."""

        # Build messages array with conversation history
        messages = [{"role": "system", "content": system_prompt}]

        # Add recent conversation history if available (last 4 messages = 2 exchanges)
        if conversation_history and len(conversation_history) > 0:
            for msg in conversation_history[-4:]:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role and content:
                    # Truncate very long messages to keep token count reasonable
                    truncated_content = content[:300] + "..." if len(content) > 300 else content
                    messages.append({"role": role, "content": truncated_content})

        # Add current user message
        messages.append({"role": "user", "content": user_input})

        try:
            logger.debug(f"Optimizing RAG query for: {user_input[:50]}...")
            # Use classifier model for fast optimization
            optimized_query = await self._with_retries(
                CLASSIFIER_MODEL,
                messages,
                temperature=0.0,
                max_tokens=100,
                call_type="rag_query_enhancement",
                user_context=user_context
            )
            logger.debug(f"Optimized RAG query: '{optimized_query}'")
            return optimized_query.strip()
        except Exception as e:
            logger.warning(f"RAG query optimization failed: {e}, using original query")
            return user_input

    async def analyze_memories(self, prompt: str, existing_memories: str, conversation: str, user_context: Optional[Dict[str, str]] = None) -> MemoryAnalysisResult:
        """
        Analyze conversation for memory generation.

        Args:
            prompt: The system prompt with memory generation instructions
            existing_memories: Formatted string of existing memories to avoid duplicates
            conversation: The recent conversation history to analyze
            user_context: Optional dict with user_id and company_id for token tracking

        Returns:
            MemoryAnalysisResult with has_important_content and list of memories
        """
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": existing_memories},
            {"role": "user", "content": conversation}
        ]

        try:
            logger.debug("Analyzing conversation for memory generation")
            result = await self._parse_with_azure_first(
                CLASSIFIER_MODEL,
                messages,
                MemoryAnalysisResult,
                temperature=0.1,
                max_tokens=512,
                call_type="memory_generation",
                user_context=user_context
            )
            logger.debug(f"Memory analysis complete: {len(result.memories) if result.has_important_content else 0} memories found")
            return result
        except Exception as e:
            logger.error(f"Memory analysis failed: {e}")
            return MemoryAnalysisResult(has_important_content=False, memories=[])
