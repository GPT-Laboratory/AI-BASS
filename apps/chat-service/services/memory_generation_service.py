from typing import List, Dict, Any, Optional
from datetime import datetime
from pymongo import MongoClient
from services.llm_interface import LLMClient
from services.chatgpt_client import ChatGPTClient
import logging
import os
import requests

logger = logging.getLogger(__name__)


class MemoryGenerationService:
    """
    Service responsible for analyzing conversation history and generating memories
    when significant content is detected. Memories are stored as metadata with embeddings.
    """

    def __init__(self, mongo_uri: str, db_name: str = "companydb", mongo_client: Optional[MongoClient] = None):
        if mongo_client:
            self.client = mongo_client
        else:
            self.client = MongoClient(mongo_uri)

        self.db = self.client[db_name]
        self.conversations_col = self.db["conversations"]
        self.metadata_col = self.db["company_metadata"]
        self.users_col = self.db["users"]
        self.settings_col = self.db["settings"]

        # Initialize LLM client for memory analysis - pass mongo_client for token tracking
        self.llm = ChatGPTClient(mongo_client=self.client)

        # Admin backend configuration for memory storage
        self.admin_api_base = os.getenv("ADMIN_API_BASE", "http://backend:5000")
        self.admin_username = os.getenv("ADMIN_USERNAME", "admin")
        self.admin_password = os.environ["ADMIN_PASSWORD"]
        self._admin_token = None
        self._token_timestamp = None

        logger.info("MemoryGenerationService initialized")

    def _get_admin_token(self) -> Optional[str]:
        """
        Get or refresh admin backend JWT token for API authentication.
        Tokens are cached and reused until they expire.

        Returns:
            JWT token string, or None if authentication fails
        """
        # Check if we have a cached token that's still fresh (within 50 minutes)
        if self._admin_token and self._token_timestamp:
            token_age_seconds = (datetime.utcnow() - self._token_timestamp).total_seconds()
            if token_age_seconds < 3000:  # 50 minutes (tokens expire after 60)
                return self._admin_token

        # Need to get a new token
        try:
            logger.info(f"Authenticating with admin backend at {self.admin_api_base}/login")
            response = requests.post(
                f"{self.admin_api_base}/login",
                json={"username": self.admin_username, "password": self.admin_password},
                timeout=10
            )
            response.raise_for_status()
            token = response.json()["token"]

            # Cache the token
            self._admin_token = token
            self._token_timestamp = datetime.utcnow()

            logger.info("Successfully authenticated with admin backend")
            return token
        except Exception as e:
            logger.error(f"Failed to authenticate with admin backend: {e}")
            return None


    def should_generate_memories(self, user_id: str) -> bool:
        """
        Check if we should generate memories for this user.
        Triggers when user has sent exactly a multiple of 10 total messages.

        Args:
            user_id: MongoDB user _id as string

        Returns:
            True if memories should be generated
        """
        total_messages = self.conversations_col.count_documents({"user_id": user_id})

        # Check if total messages is a multiple of 10 and greater than 0
        should_generate = total_messages > 0 and total_messages % 10 == 0

        if should_generate:
            logger.info(f"Memory generation triggered for user {user_id} at {total_messages} total messages")

        return should_generate

    async def analyze_conversation_for_memories(self, user_id: str, message_limit: int = 10) -> Optional[List[str]]:
        """
        Analyze recent conversation history to extract important memories.

        Args:
            user_id: MongoDB user _id as string
            message_limit: Number of recent messages to analyze (default: 10)

        Returns:
            List of memory strings, or None if no important memories found
        """
        logger.info(f"Starting memory analysis for user {user_id}")

        # Get recent messages for analysis
        recent_messages = list(
            self.conversations_col
            .find({"user_id": user_id})
            .sort("timestamp", -1)
            .limit(message_limit)
        )

        logger.info(f"Retrieved {len(recent_messages)} recent messages for analysis")

        if len(recent_messages) < 2:  # Need at least some conversation
            logger.info(f"Not enough messages for memory analysis: {len(recent_messages)} - skipping")
            return None

        # Reverse to get chronological order
        recent_messages.reverse()

        # Get user's company_id for fetching existing memories and token tracking
        user_doc = self.users_col.find_one({"phone_number": user_id})
        company_id = user_doc.get("company_id") if user_doc else None

        if not company_id:
            logger.warning(f"User {user_id} has no company_id - cannot fetch existing memories")
            existing_memories = []
        else:
            # Fetch existing memories for this company
            existing_memories = self._get_existing_memories(company_id)

        # Format conversation for LLM analysis
        conversation_text = self._format_conversation_for_analysis(recent_messages)
        logger.info(f"Formatted conversation text length: {len(conversation_text)} characters")

        # Format existing memories
        existing_memories_text = self._format_existing_memories(existing_memories)
        logger.info(f"Formatted existing memories: {len(existing_memories)} memories found")

        # Create memory analysis prompt
        doc = self.settings_col.find_one()
        system_prompt = doc.get("memory_generation_prompt", "") if doc else ""

        # Create user context dict for token tracking
        user_context = {
            "user_id": user_id,
            "company_id": company_id or ""
        }

        try:
            logger.info("Sending conversation to LLM for memory analysis")
            # Use the new method in ChatGPTClient with existing memories
            result = await self.llm.analyze_memories(
                system_prompt,
                existing_memories_text,
                conversation_text,
                user_context=user_context
            )

            logger.info(f"LLM analysis result - has_important_content: {result.has_important_content}, memories_count: {len(result.memories)}")

            if result.has_important_content and result.memories:
                logger.info(f"Generated {len(result.memories)} memories for user {user_id}")
                for i, memory in enumerate(result.memories, 1):
                    logger.info(f"Memory {i}: {memory[:100]}{'...' if len(memory) > 100 else ''}")
                return result.memories
            else:
                logger.info(f"No important memories found for user {user_id}")
                return None

        except Exception as e:
            logger.error(f"Error analyzing conversation for memories: {e}")
            return None

    def _get_existing_memories(self, company_id: str) -> List[str]:
        """
        Retrieve all existing AI-generated memories for a company.

        Args:
            company_id: The company ID to fetch memories for

        Returns:
            List of memory description strings
        """
        logger.info(f"Fetching existing memories for company {company_id}")

        try:
            # Query for all AI-generated memory metadata for this company
            memory_docs = list(
                self.metadata_col.find({
                    "company_id": company_id,
                    "type": "ai_generated_memory"
                }).sort("created_at", -1)  # Most recent first
            )

            logger.info(f"Found {len(memory_docs)} existing memories for company {company_id}")

            # Extract memory descriptions
            memories = []
            for doc in memory_docs:
                content = doc.get("content", {})
                description = content.get("description", "")
                if description:
                    memories.append(description)

            return memories
        except Exception as e:
            logger.error(f"Error fetching existing memories: {e}")
            return []

    def _format_existing_memories(self, memories: List[str]) -> str:
        """
        Format existing memories into a readable list for LLM.

        Args:
            memories: List of memory strings

        Returns:
            Formatted string with all memories
        """
        if not memories:
            return "No existing memories found."

        formatted_lines = [
            "Here are all the existing memories. We do not want to generate duplicates:",
            ""
        ]

        for i, memory in enumerate(memories, 1):
            formatted_lines.append(f"{i}. {memory}")

        return "\n".join(formatted_lines)

    def _format_conversation_for_analysis(self, messages: List[Dict[str, Any]]) -> str:
        """Format conversation messages for LLM analysis."""
        formatted_lines = []

        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            timestamp = msg["timestamp"].strftime("%Y-%m-%d %H:%M")

            if role == "user":
                formatted_lines.append(f"[{timestamp}] User: {content}")
            else:
                formatted_lines.append(f"[{timestamp}] Assistant: {content}")

        return "\n".join(formatted_lines)

    async def store_memories_as_metadata(self, user_id: str, memories: List[str]) -> List[str]:
        """
        Store generated memories via admin-backend API which handles LightRAG insertion.

        Args:
            user_id: MongoDB user _id as string (phone number in this system)
            memories: List of memory strings to store

        Returns:
            List of created metadata document IDs
        """
        logger.info(f"Starting to store {len(memories)} memories via admin-backend for user {user_id}")

        # Get user's company_id - user_id is a phone number in this system
        logger.info(f"Looking up user by phone number: {user_id}")
        user_doc = self.users_col.find_one({"phone_number": user_id})
        if not user_doc:
            logger.error(f"User with phone number {user_id} not found")
            return []

        company_id = user_doc.get("company_id")
        if not company_id:
            logger.error(f"User {user_id} has no company_id")
            return []

        logger.info(f"Found user company_id: {company_id}")

        # Get authentication token
        token = self._get_admin_token()
        if not token:
            logger.error("Failed to get admin token - cannot store memories")
            return []

        created_ids = []
        now = datetime.utcnow()

        for i, memory in enumerate(memories, 1):
            logger.info(f"Processing memory {i}/{len(memories)}: {memory[:50]}{'...' if len(memory) > 50 else ''}")

            # Create metadata document for memory
            metadata_doc = {
                "company_id": company_id,
                "type": "ai_generated_memory",
                "source": "chat_service",
                "content": {
                    "description": memory,
                    "generated_from_user": user_id,
                    "generation_method": "conversation_analysis"
                },
                "created_at": now.isoformat(),
                "updated_at": now.isoformat()
            }

            # Store via admin-backend API which will handle LightRAG insertion
            try:
                logger.info(f"Sending memory {i} to admin-backend API")
                response = requests.post(
                    f"{self.admin_api_base}/metadata",
                    json=metadata_doc,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    },
                    timeout=30
                )

                if response.status_code == 201:
                    result = response.json()
                    memory_id = result.get("_id")
                    created_ids.append(memory_id)
                    logger.info(f"Successfully stored memory {i} via admin-backend with ID: {memory_id}")
                else:
                    logger.error(f"Failed to store memory {i} via admin-backend: {response.status_code} - {response.text}")
            except Exception as e:
                logger.error(f"Exception storing memory {i} via admin-backend: {e}")

        logger.info(f"Completed storing memories - successfully created {len(created_ids)} out of {len(memories)} memories")
        return created_ids

    async def process_memory_generation(self, user_id: str) -> bool:
        """
        Complete memory generation process: analyze conversation and store memories.

        Args:
            user_id: MongoDB user _id as string

        Returns:
            True if memories were generated and stored, False otherwise
        """
        logger.info(f"Starting complete memory generation process for user {user_id}")

        try:
            # Check if we should generate memories
            logger.info(f"Checking if memory generation should be triggered for user {user_id}")
            if not self.should_generate_memories(user_id):
                logger.info(f"Memory generation not triggered for user {user_id} - message count not at threshold")
                return False

            # Analyze conversation for memories
            logger.info(f"Analyzing conversation for memories for user {user_id}")
            memories = await self.analyze_conversation_for_memories(user_id)

            if not memories:
                logger.info(f"No memories generated for user {user_id} - analysis found no important content")
                return False

            # Store memories as metadata
            logger.info(f"Storing {len(memories)} memories as metadata for user {user_id}")
            created_ids = await self.store_memories_as_metadata(user_id, memories)

            if created_ids:
                logger.info(f"Successfully completed memory generation process for user {user_id} - created {len(created_ids)} memories with IDs: {created_ids}")
                return True
            else:
                logger.warning(f"Memory generation process failed for user {user_id} - could not store memories")
                return False

        except Exception as e:
            logger.error(f"Error in memory generation process for user {user_id}: {e}")
            return False