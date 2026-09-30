"""
Azure OpenAI client adapters for LightRAG integration
"""

import os
import asyncio
from typing import List, Dict, Any, Optional
import numpy as np
from openai import AsyncAzureOpenAI
import logging

logger = logging.getLogger(__name__)

# Configuration
AZURE_API_KEY = os.getenv("AZURE_API_KEY", "")
AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT", "")
AZURE_VERSION = os.getenv("AZURE_VERSION", "2024-12-01-preview")
AZURE_LLM_MODEL = os.getenv("AZURE_LLM_MODEL", "gpt-4o")
AZURE_EMBED_MODEL = os.getenv("AZURE_EMBED_MODEL", "text-embedding-3-small")

# Initialize Azure OpenAI client
azure_client = AsyncAzureOpenAI(
    api_key=AZURE_API_KEY,
    azure_endpoint=AZURE_ENDPOINT,
    api_version=AZURE_VERSION
)

async def azure_llm_model_func(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: List[Dict[str, str]] = None,
    **kwargs
) -> str:
    """
    LLM completion function for LightRAG using Azure OpenAI

    Args:
        prompt: User prompt/query
        system_prompt: System message
        history_messages: Conversation history
        **kwargs: Additional parameters for the API call

    Returns:
        Generated text response
    """
    if history_messages is None:
        history_messages = []

    try:
        # Build messages array
        messages = []

        # Add system prompt if provided
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Add history messages
        for msg in history_messages:
            messages.append(msg)

        # Add current prompt
        messages.append({"role": "user", "content": prompt})

        # Call Azure OpenAI
        response = await azure_client.chat.completions.create(
            model=AZURE_LLM_MODEL,
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 4000),
            top_p=kwargs.get("top_p", 0.9),
            frequency_penalty=kwargs.get("frequency_penalty", 0),
            presence_penalty=kwargs.get("presence_penalty", 0)
        )

        result = response.choices[0].message.content
        logger.debug(f"Azure LLM response length: {len(result) if result else 0}")
        return result or ""

    except Exception as e:
        logger.error(f"Azure LLM call failed: {e}")
        raise e

async def azure_embedding_func(texts: List[str]) -> np.ndarray:
    """
    Embedding function for LightRAG using Azure OpenAI

    Args:
        texts: List of texts to embed

    Returns:
        Numpy array of embeddings
    """
    try:
        # Azure OpenAI has a limit on batch size, so we'll process in chunks
        batch_size = 100
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            response = await azure_client.embeddings.create(
                model=AZURE_EMBED_MODEL,
                input=batch
            )

            batch_embeddings = [data.embedding for data in response.data]
            all_embeddings.extend(batch_embeddings)

        embeddings_array = np.array(all_embeddings, dtype=np.float32)
        logger.debug(f"Generated embeddings for {len(texts)} texts, shape: {embeddings_array.shape}")
        return embeddings_array

    except Exception as e:
        logger.error(f"Azure embedding call failed: {e}")
        raise e

# Wrapper function for single text embedding (used by some LightRAG components)
async def azure_embed_single(text: str) -> List[float]:
    """Embed a single text and return as list"""
    result = await azure_embedding_func([text])
    return result[0].tolist()

# Synchronous wrappers for compatibility
def azure_llm_model_func_sync(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: List[Dict[str, str]] = None,
    **kwargs
) -> str:
    """Synchronous wrapper for Azure LLM function"""
    return asyncio.run(azure_llm_model_func(prompt, system_prompt, history_messages, **kwargs))

def azure_embedding_func_sync(texts: List[str]) -> np.ndarray:
    """Synchronous wrapper for Azure embedding function"""
    return asyncio.run(azure_embedding_func(texts))