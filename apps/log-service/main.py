from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from pymongo import MongoClient
import os
from openai import AsyncAzureOpenAI
import json
from typing import List, Optional, Dict
import logging

# Get logger for this module
logger = logging.getLogger(__name__)

app = FastAPI()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")

client = MongoClient(MONGO_URI)
db = client["companydb"]
log_col = db["log_entries"]
settings_col = db["settings"]
usage_collection = db["token_usage"]  # Token usage tracking collection

AZURE_API_KEY = os.getenv("AZURE_API_KEY", "your-azure-api-key")
AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT", "your-endpoint")
AZURE_VERSION = os.getenv("AZURE_VERSION", "your-version")
azure_client = AsyncAzureOpenAI(api_key=AZURE_API_KEY, azure_endpoint=AZURE_ENDPOINT, api_version=AZURE_VERSION)

def _save_token_usage(
    model: str,
    provider: str,
    success: bool,
    call_type: str = "log_classification",
    usage_data: Optional[Dict] = None,
    error: Optional[str] = None,
    user_context: Optional[Dict[str, str]] = None
):
    """Save token usage data to MongoDB."""
    try:
        doc = {
            "timestamp": datetime.now(timezone.utc),
            "model": model,
            "provider": provider,  # 'azure'
            "success": success,
            "call_type": call_type,  # 'log_classification'
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
            if "completion_tokens_details" in usage_data:
                doc["usage"]["completion_tokens_details"] = usage_data["completion_tokens_details"]

        if error:
            doc["error"] = error

        usage_collection.insert_one(doc)
    except Exception as e:
        logger.error(f"Failed to save token usage: {e}")


class Metrics(BaseModel):
    # lengths & perf
    context_length: int = Field(ge=0)
    question_length: int = Field(ge=0)
    answer_length: int = Field(ge=0)
    latency_ms: int = Field(ge=0)

    # ids (MongoID + session)
    user_id: str
    company_id: Optional[str] = None
    company_env: Optional[str] = "development"
    session_id: str

    # per-turn RAG usage
    rag_documents_count: int = Field(ge=0)
    rag_source_count: int = Field(ge=0, default=0)  # Match what chat_engine.py sends

class LogPayload(BaseModel):
    task: str
    question: str
    response: str
    context_used: str
    system_prompt_used: str
    task_prompt_used: str
    metrics: Optional[Metrics] = None  # backward compatible
    source: Optional[str] = "web"  # Track interaction source: "whatsapp" or "web"
    rag_references: Optional[list] = None  # RAG document refs used in answer

class LLMOutput(BaseModel):
    prompt_type: str
    response_type: str
    tone: str

@app.post("/log")
async def log_interaction(payload: LogPayload):
    settings = settings_col.find_one() or {}
    prompt_types = settings.get("prompt_classification", [])
    response_types = settings.get("response_classification", [])
    tones = settings.get("interaction_tone_classification", [])

    # Extract user context for token tracking
    user_context = None
    if payload.metrics:
        user_context = {
            "user_id": payload.metrics.user_id,
            "company_id": payload.metrics.company_id,
            "company_env": payload.metrics.company_env or "development",
        }

    classification_prompt = (
        f"Classify the following interaction.\n\n"
        f"User question:\n{payload.question}\n\n"
        f"Response:\n{payload.response}\n\n"
        f"Choose from the following:\n"
        f"- prompt_type: {prompt_types}\n"
        f"- response_type: {response_types}\n"
        f"- tone: {tones}\n\n"
        f"Return JSON:\n"
        f"{{\"prompt_type\": \"...\", \"response_type\": \"...\", \"tone\": \"...\"}}"
    )

    classification_result = {}
    token_usage_data = None

    try:
        completion = await azure_client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": classification_prompt}],
            temperature=0,
            response_format=LLMOutput,
        )
        content = completion.choices[0].message.content.strip()
        classification_result = json.loads(content)

        # Extract token usage from response
        if completion.usage:
            token_usage_data = {
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
                "total_tokens": completion.usage.total_tokens,
            }
            # Include detailed breakdowns if available
            if hasattr(completion.usage, "prompt_tokens_details") and completion.usage.prompt_tokens_details:
                token_usage_data["prompt_tokens_details"] = completion.usage.prompt_tokens_details.model_dump()
            if hasattr(completion.usage, "completion_tokens_details") and completion.usage.completion_tokens_details:
                token_usage_data["completion_tokens_details"] = completion.usage.completion_tokens_details.model_dump()

        # Save successful token usage
        _save_token_usage(
            model="gpt-4o-mini",
            provider="azure",
            success=True,
            call_type="log_classification",
            usage_data=token_usage_data,
            user_context=user_context
        )

    except Exception as e:
        logger.error(f"Classification failed: {e}")
        # Save failed token usage
        _save_token_usage(
            model="gpt-4o-mini",
            provider="azure",
            success=False,
            call_type="log_classification",
            error=f"{type(e).__name__}: {str(e)}",
            user_context=user_context
        )

    log_entry = {
        **payload.dict(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "classifications": classification_result,
        "classification_token_usage": token_usage_data,  # Add token usage to log entry
    }

    log_col.insert_one(log_entry)
    return {"status": "ok"}
