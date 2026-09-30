from datetime import datetime
from pymongo import MongoClient
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class ConversationService:
    """
    Manages individual message storage with rolling window retrieval.
    """

    def __init__(self, mongo_uri: str, db_name: str = "companydb"):
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        self.conversations_col = self.db["conversations"]

        # Create index for efficient user message retrieval
        self.conversations_col.create_index([("user_id", 1), ("timestamp", -1)])
        logger.info("ConversationService initialized")

    def add_message(self, user_id: str, role: str, content: str, metadata: Dict[str, Any] = None) -> str:
        """
        Add a single message (user or assistant) to the conversation history.

        Args:
            user_id: MongoDB user _id as string
            role: "user" or "assistant"
            content: Message content
            metadata: Optional metadata (phone_number, message_type, processing_time_ms, etc.)

        Returns:
            MongoDB document _id as string
        """
        if role not in ["user", "assistant"]:
            raise ValueError(f"Invalid role: {role}. Must be 'user' or 'assistant'")

        now = datetime.utcnow()
        message_doc = {
            "user_id": user_id,
            "timestamp": now,
            "role": role,
            "content": content,
            "session_date": now.date().isoformat(),
            "metadata": metadata or {}
        }

        result = self.conversations_col.insert_one(message_doc)
        logger.debug(f"Added {role} message for user {user_id}: {len(content)} chars")

        # Trigger memory generation check after adding message
        self._check_and_trigger_memory_generation(user_id)

        return str(result.inserted_id)

    def get_recent_messages(self, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Get the most recent messages for a user, ordered by timestamp (oldest first).

        Args:
            user_id: MongoDB user _id as string
            limit: Maximum number of messages to retrieve (default: 5)

        Returns:
            List of message documents, ordered chronologically
        """
        # Get messages in reverse chronological order, then reverse to get chronological
        messages = list(
            self.conversations_col
            .find({"user_id": user_id})
            .sort("timestamp", -1)  # Most recent first
            .limit(limit)
        )

        # Reverse to get chronological order (oldest first)
        messages.reverse()

        logger.debug(f"Retrieved {len(messages)} recent messages for user {user_id}")
        return messages

    def get_messages_paginated(self, user_id: str, limit: int = 10, skip: int = 0) -> List[Dict[str, Any]]:
        """
        Get paginated messages for a user with skip/limit support for infinite scroll.

        Args:
            user_id: MongoDB user _id as string (phone number)
            limit: Maximum number of messages to retrieve (default: 10)
            skip: Number of messages to skip from the most recent (default: 0)

        Returns:
            List of message documents ordered chronologically (oldest first in the batch)
        """
        messages = list(
            self.conversations_col
            .find({"user_id": user_id})
            .sort("timestamp", -1)  # Most recent first
            .skip(skip)
            .limit(limit)
        )

        # Reverse to get chronological order (oldest first within the batch)
        messages.reverse()

        logger.debug(f"Retrieved {len(messages)} paginated messages for user {user_id} (skip={skip}, limit={limit})")
        return messages

    def format_for_llm(self, messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """
        Format conversation messages for OpenAI LLM consumption.

        Args:
            messages: List of message documents from MongoDB

        Returns:
            List of messages in OpenAI format [{"role": "user", "content": "..."}, ...]
        """
        formatted = []
        for msg in messages:
            formatted.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        logger.debug(f"Formatted {len(formatted)} messages for LLM")
        return formatted

    def get_conversation_for_llm(self, user_id: str, limit: int = 5) -> List[Dict[str, str]]:
        """
        Convenience method to get recent messages already formatted for LLM.

        Args:
            user_id: MongoDB user _id as string
            limit: Maximum number of messages to retrieve (default: 5)

        Returns:
            List of messages in OpenAI format, ready for LLM
        """
        recent_messages = self.get_recent_messages(user_id, limit)
        return self.format_for_llm(recent_messages)

    def add_user_message(self, user_id: str, content: str, phone_number: str = None, message_type: str = "text") -> str:
        """
        Convenience method to add a user message with common metadata.

        Args:
            user_id: MongoDB user _id as string
            content: User message content
            phone_number: Phone number for backwards compatibility
            message_type: Type of message (text, audio, document)

        Returns:
            MongoDB document _id as string
        """
        metadata = {
            "phone_number": phone_number,
            "message_type": message_type
        }
        return self.add_message(user_id, "user", content, metadata)

    def add_assistant_message(self, user_id: str, content: str, processing_time_ms: int = None) -> str:
        """
        Convenience method to add an assistant message with processing time metadata.

        Args:
            user_id: MongoDB user _id as string
            content: Assistant response content
            processing_time_ms: Time taken to generate response

        Returns:
            MongoDB document _id as string
        """
        metadata = {}
        if processing_time_ms is not None:
            metadata["processing_time_ms"] = processing_time_ms

        return self.add_message(user_id, "assistant", content, metadata)

    def get_user_message_count(self, user_id: str, days: int = None) -> int:
        """
        Get total message count for a user, optionally within a time period.

        Args:
            user_id: MongoDB user _id as string
            days: If specified, count messages from last N days only

        Returns:
            Number of messages
        """
        query = {"user_id": user_id}

        if days is not None:
            from datetime import timedelta
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            query["timestamp"] = {"$gte": cutoff_date}

        count = self.conversations_col.count_documents(query)
        logger.debug(f"User {user_id} has {count} messages" + (f" in last {days} days" if days else ""))
        return count

    def cleanup_old_messages(self, days_to_keep: int = 30) -> int:
        """
        Remove messages older than specified days to manage storage.

        Args:
            days_to_keep: Number of days of message history to retain

        Returns:
            Number of messages deleted
        """
        from datetime import timedelta

        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
        result = self.conversations_col.delete_many({"timestamp": {"$lt": cutoff_date}})

        deleted_count = result.deleted_count
        logger.info(f"Cleaned up {deleted_count} messages older than {days_to_keep} days")
        return deleted_count

    def get_user_conversation_stats(self, user_id: str) -> Dict[str, Any]:
        """
        Get conversation statistics for a user.

        Args:
            user_id: MongoDB user _id as string

        Returns:
            Dictionary with conversation statistics
        """
        pipeline = [
            {"$match": {"user_id": user_id}},
            {"$group": {
                "_id": "$role",
                "count": {"$sum": 1},
                "avg_length": {"$avg": {"$strLenCP": "$content"}},
                "latest": {"$max": "$timestamp"}
            }}
        ]

        results = list(self.conversations_col.aggregate(pipeline))

        stats = {
            "total_messages": 0,
            "user_messages": 0,
            "assistant_messages": 0,
            "avg_user_length": 0,
            "avg_assistant_length": 0,
            "latest_activity": None
        }

        for result in results:
            role = result["_id"]
            count = result["count"]
            avg_length = result["avg_length"]
            latest = result["latest"]

            stats["total_messages"] += count

            if role == "user":
                stats["user_messages"] = count
                stats["avg_user_length"] = round(avg_length, 1)
            elif role == "assistant":
                stats["assistant_messages"] = count
                stats["avg_assistant_length"] = round(avg_length, 1)

            if stats["latest_activity"] is None or latest > stats["latest_activity"]:
                stats["latest_activity"] = latest

        logger.debug(f"Generated conversation stats for user {user_id}: {stats['total_messages']} total messages")
        return stats

    def _check_and_trigger_memory_generation(self, user_id: str):
        """
        Check if memory generation should be triggered and handle it asynchronously.
        Called after each message is added to check if we've reached the threshold.

        Args:
            user_id: MongoDB user _id as string
        """
        try:
            # Import here to avoid circular imports
            from services.memory_generation_service import MemoryGenerationService

            # Create memory service instance
            # Use the same mongo connection string as the conversation service
            mongo_uri = f"mongodb://{self.client.address[0]}:{self.client.address[1]}/companydb"
            memory_service = MemoryGenerationService(mongo_uri=mongo_uri)

            # Check if we should generate memories (every 10 messages)
            total_messages = self.conversations_col.count_documents({"user_id": user_id})

            if total_messages > 0 and total_messages % 10 == 0:
                logger.info(f"Memory generation threshold reached for user {user_id} at {total_messages} messages")

                # Import asyncio to handle async memory generation
                import asyncio

                # Run memory generation in background
                try:
                    # Try to get the current event loop
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # If we're in an async context, schedule as a task
                        loop.create_task(memory_service.process_memory_generation(user_id))
                    else:
                        # If no loop is running, run it
                        asyncio.run(memory_service.process_memory_generation(user_id))
                except RuntimeError:
                    # If no event loop exists, create one
                    asyncio.run(memory_service.process_memory_generation(user_id))

                logger.debug(f"Memory generation task scheduled for user {user_id}")

        except Exception as e:
            logger.error(f"Error in memory generation trigger: {e}")
            # Don't let memory generation errors affect normal message processing