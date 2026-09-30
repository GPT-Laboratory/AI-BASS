from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, Header
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import logging
from pymongo import MongoClient
from urllib.parse import unquote
import json
import jwt
import requests
from datetime import datetime, timezone
from typing import Optional
from services.chatgpt_client import ChatGPTClient
from core.chat_engine import ChatEngine
from core.settings_provider import SettingsProvider
from services.conversation_service import ConversationService
from core.logging_config import logger

# Pydantic models
class LoginRequest(BaseModel):
    username: str
    password: str

class WhatsAppForwardRequest(BaseModel):
    phone_number: str
    message: str
    secret: str

class ExternalChatRequest(BaseModel):
    message: str
    user_id: Optional[str] = None
    task: Optional[str] = None

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
TEST_CLIENT_USER = os.getenv("TEST_CLIENT_USER", "")
COURSE_API_SECRET = os.getenv("COURSE_API_SECRET")

# Security
security = HTTPBearer()

def normalize_phone_number(phone: str) -> str:
    decoded = unquote(phone or "")
    return decoded if decoded.startswith('+') else '+' + decoded.lstrip('+')

def _admin_api_base() -> str:
    base = os.getenv("ADMIN_API_BASE", "").rstrip("/")
    if not base:
        raise RuntimeError("ADMIN_API_BASE is not set")
    return base


def _get_company_by_api_key(api_key: str):
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    company = db["companies"].find_one({"api_key": api_key})
    if not company:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return company

# Accept opaque external JWTs: decode without verifying signature, only check exp.
def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        # Do NOT verify signature (we don't have the admin API's secret).
        payload = jwt.decode(
            token,
            options={"verify_signature": False, "verify_exp": False, "verify_aud": False},
            algorithms=["HS256", "RS256", "HS512", "RS512"],
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Best-effort expiry check if 'exp' exists
    exp = payload.get("exp")
    if exp is not None:
        try:
            if datetime.fromtimestamp(exp, tz=timezone.utc) <= datetime.now(tz=timezone.utc):
                raise HTTPException(status_code=401, detail="Token expired")
        except Exception:
            # If exp is malformed, reject
            raise HTTPException(status_code=401, detail="Invalid token")

    # Return both payload and raw token if you want to forward downstream
    return {"payload": payload, "token": token}

# Mongo & services
mongo_client = MongoClient(os.getenv("MONGODB_URI", "mongodb://mongo:27017/"))
db = mongo_client["companydb"]
users_col = db["users"]
settings_provider = SettingsProvider(db)
conversation_service = ConversationService(
    mongo_uri=os.getenv("MONGODB_URI", "mongodb://mongo:27017/")
)

chat_engine = ChatEngine(
    llm=ChatGPTClient(mongo_client=mongo_client),
    settings=settings_provider,
    conversation_service=conversation_service,
    db=db
)

logger.info("Chat service initialized successfully")
logger.info(f"Using Azure first: {os.getenv('USE_AZURE_FIRST', 'false')}")
logger.info(f"Web search enabled: {os.getenv('WEB_SEARCH_ENABLED', 'true')}")

@app.get("/users")
async def list_users(token_info: dict = Depends(verify_token)):
    payload = token_info.get("payload", {}) if isinstance(token_info, dict) else {}
    role = payload.get("role")
    if role == "admin":
        users = list(users_col.find({}, {"first_name": 1, "last_name": 1, "phone_number": 1, "_id": 0}))
        return users

    # Non-admin: return only the logged-in user's own record, found by phone_number from JWT
    phone = payload.get("phone_number")
    if not phone:
        # If upstream token didn't include phone_number for a non-admin, deny
        raise HTTPException(status_code=403, detail="Missing phone_number in token")

    phone_number = normalize_phone_number(phone)
    user = users_col.find_one({"phone_number": phone_number}, {"first_name": 1, "last_name": 1, "phone_number": 1, "_id": 0})
    if not user:
        # Keep response type consistent (array) for the frontend
        return []
    return [user]


@app.get("/user/{phone}")
async def get_user(phone: str, token_info: dict = Depends(verify_token)):
    payload = token_info.get("payload", {})
    role = payload.get("role")
    requester_phone = payload.get("phone_number")

    phone_number = normalize_phone_number(phone)

    if role != "admin":
        if not requester_phone or normalize_phone_number(requester_phone) != phone_number:
            raise HTTPException(status_code=403, detail="Forbidden")

    user = users_col.find_one({"phone_number": phone_number})
    if not user:
        return {"error": "User not found"}
    return {
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "description": user.get("description"),
        "company_id": user.get("company_id")
    }


@app.get("/settings")
async def get_settings(token_info: dict = Depends(verify_token)):
    doc = db["settings"].find_one() or {}
    return {
        "system_prompts": doc.get("system_prompts", []),
        "predefined_prompts": doc.get("predefined_prompts", []),
    }

@app.get("/conversation/{phone}")
async def get_conversation(
    phone: str,
    skip: int = 0,
    limit: int = 10,
    token_info: dict = Depends(verify_token)
):
    """
    Fetch conversation history for a user with pagination support.

    Args:
        phone: User's phone number
        skip: Number of most recent messages to skip (for pagination)
        limit: Maximum number of messages to return (default: 10)

    Returns:
        List of messages ordered chronologically (oldest first in batch)
    """
    payload = token_info.get("payload", {})
    role = payload.get("role")
    requester_phone = payload.get("phone_number")

    phone_number = normalize_phone_number(phone)

    # Authorization: admin can access all, non-admin only their own
    if role != "admin":
        if not requester_phone or normalize_phone_number(requester_phone) != phone_number:
            raise HTTPException(status_code=403, detail="Forbidden")

    # Fetch paginated messages
    messages = conversation_service.get_messages_paginated(
        user_id=phone_number,
        limit=limit,
        skip=skip
    )

    # Format messages for frontend
    formatted_messages = []
    for msg in messages:
        formatted_messages.append({
            "id": str(msg.get("_id")),  # Include message ID to prevent duplicates
            "role": msg.get("role"),
            "content": msg.get("content"),
            "timestamp": msg.get("timestamp").isoformat() if msg.get("timestamp") else None,
            "metadata": msg.get("metadata", {})
        })

    return formatted_messages

@app.post("/login")
async def login(login_request: LoginRequest):
    """
    Proxy to the admin API's /login using ADMIN_API_BASE.
    Forwards {username, password}, returns the upstream {token} as-is.
    """
    base = _admin_api_base()
    url = f"{base}/login"
    try:
        resp = requests.post(url, json=login_request.dict(), timeout=10)
    except requests.RequestException as e:
        logger.error(f"Upstream login request failed: {e}")
        raise HTTPException(status_code=502, detail="Login upstream unreachable")

    # Pass through upstream response semantics
    try:
        data = resp.json()
    except ValueError:
        logger.error(f"Non-JSON from upstream login: status={resp.status_code}")
        raise HTTPException(status_code=502, detail="Invalid response from login upstream")

    if resp.ok and isinstance(data, dict) and "token" in data:
        return {"token": data["token"]}
    else:
        # Mirror upstream error code if sensible, else 401
        detail = (data.get("error") or data.get("detail") or "Invalid credentials") if isinstance(data, dict) else "Invalid credentials"
        raise HTTPException(status_code=resp.status_code if 400 <= resp.status_code < 600 else 401, detail=detail)

@app.post("/whatsapp")
async def whatsapp_webhook_forward(request: WhatsAppForwardRequest):
    """
    Endpoint for forwarding WhatsApp messages from business deployment to course deployment.
    Validates secret, checks if user exists, and processes the message through chat_engine.
    """
    # Validate secret
    if not COURSE_API_SECRET:
        logger.error("COURSE_API_SECRET not configured")
        raise HTTPException(status_code=500, detail="Service not configured for WhatsApp forwarding")

    if request.secret != COURSE_API_SECRET:
        logger.warning(f"Invalid secret provided for WhatsApp forwarding from {request.phone_number}")
        raise HTTPException(status_code=401, detail="Invalid secret")

    # Normalize phone number
    phone_number = normalize_phone_number(request.phone_number)

    # Check if user exists in this database
    user = users_col.find_one({"phone_number": phone_number})
    if not user:
        logger.warning(f"User not found in course database: {phone_number}")
        return {"success": False, "error": "User not found in this deployment"}

    logger.info(f"Processing forwarded WhatsApp message from {phone_number}: {request.message[:100]}...")

    # Process message through chat engine
    try:
        response = await chat_engine.respond(request.message, phone_number, task=None, source="whatsapp")

        # Handle both old string response and new dict response
        if isinstance(response, dict):
            reply = response.get("answer", "")
        else:
            reply = response

        logger.info(f"Generated response for forwarded message from {phone_number}: {reply[:100]}...")
        return {"success": True, "response": reply}

    except Exception as e:
        logger.error(f"Error processing forwarded WhatsApp message from {phone_number}: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

@app.post("/api/chat")
async def external_chat(request: ExternalChatRequest, api_key: str = Header(None, alias="X-API-Key")):
    """
    Accept external chat prompts using a company API key and route through the same chat engine.
    """
    company = _get_company_by_api_key(api_key)
    company_id = str(company.get("_id"))
    user_id = request.user_id or f"api:{company_id}"
    task = request.task or None

    logger.info(f"External chat request for company {company_id} (user_id={user_id})")

    try:
        response = await chat_engine.respond(
            request.message,
            user_id,
            task,
            source="api",
            company_id_override=company_id
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing external chat for company {company_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process message")

    if isinstance(response, dict):
        return response
    return {
        "answer": response,
        "memory_answer": "",
        "sources_used": [],
        "memory_sources_used": []
    }

@app.get("/")
async def get(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "test_client_user": TEST_CLIENT_USER,
        },
    )

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # If you want to gate WS by token, accept a ?token=... param:
    # token = websocket.query_params.get("token")
    # (Optional) parse/validate similar to verify_token above.
    await websocket.accept()
    logger.info("WebSocket connection established")
    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            # Handle heartbeat/ping messages
            msg_type = data.get("type")
            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "t": data.get("t")}))
                continue

            # Extract message data
            msg = data.get("message", "") or ""
            phone = normalize_phone_number(data.get("phone_number", "") or "")
            task = data.get("task") or None

            # Ignore empty messages or invalid phone numbers
            if not msg.strip() or not phone or phone == "+":
                logger.warning(f"Ignoring invalid message: msg='{msg[:50]}', phone='{phone}'")
                continue

            logger.info(f"Received message from {phone}: {msg[:100]}...")

            response = await chat_engine.respond(msg, phone, task, source="web")

            # Handle both old string response and new dict response
            if isinstance(response, dict):
                reply = response.get("answer", "")
                memory_reply = response.get("memory_answer", "")
                debug_info = response.get("debug_info", {})
                sources_used = response.get("sources_used", [])
                memory_sources = response.get("memory_sources_used", [])

                # Send sources FIRST so client can build citation map before processing message
                if sources_used:
                    await websocket.send_text(json.dumps({
                        "type": "sources",
                        "data": sources_used
                    }))

                # Send the answer as regular message AFTER sources
                await websocket.send_text(reply)

                # Send memory sources and follow-up message if present
                if memory_reply and memory_reply.strip():
                    if memory_sources:
                        await websocket.send_text(json.dumps({
                            "type": "sources",
                            "data": memory_sources
                        }))
                    await websocket.send_text(memory_reply)

                # Send debug info as a separate JSON message for console logging
                await websocket.send_text(json.dumps({
                    "type": "debug_info",
                    "data": debug_info
                }))

                logger.info(f"Sent reply to {phone}: {reply[:100]}...")
                logger.info(f"Sent {len(sources_used)} sources")
            else:
                # Backward compatibility: if respond still returns string
                reply = response
                await websocket.send_text(reply)
                logger.info(f"Sent reply to {phone}: {reply[:100]}...")

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
