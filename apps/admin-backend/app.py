import os
import datetime
import secrets
from functools import wraps

import jwt
from flask import Flask, request, jsonify, Response, send_file
from flask_pymongo import PyMongo
from flask_cors import CORS
from bson.objectid import ObjectId
from bson.json_util import dumps
from openai import OpenAI, AzureOpenAI
import logging, sys
from io import BytesIO

# Scheduler imports
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit

# Google Drive imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import io
from googleapiclient.http import MediaIoBaseDownload

# Microsoft/OneDrive imports
import requests
import msal

# Document processing imports
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

# LightRAG client import
from lightrag_client import (
    insert_company_document,
    update_company_document,
    delete_company_document,
    bulk_delete_company_documents,
    cleanup_company_workspace
)

# RAG background tasks
import lightrag_client
from rag_background_tasks import init_rag_processor, enqueue_rag_insertion, enqueue_rag_update
from report_scripts import list_report_scripts, run_report_script

try:
    from docx import Document as DocxDocument
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    from openpyxl import load_workbook
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

try:
    from pptx import Presentation
    PPTX_AVAILABLE = True
except ImportError:
    PPTX_AVAILABLE = False

# Email provider imports
try:
    from email_providers import get_email_provider
    from cryptography.fernet import Fernet
    EMAIL_PROVIDERS_AVAILABLE = True
except ImportError:
    EMAIL_PROVIDERS_AVAILABLE = False
    logging.warning("Email providers not available. Install required packages: imapclient, cryptography, msal, requests")

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

# Filter to exclude health endpoint logs
class HealthCheckFilter(logging.Filter):
    def filter(self, record):
        return '/health' not in record.getMessage()

# Apply filter to werkzeug logger (Flask's HTTP logger)
logging.getLogger('werkzeug').addFilter(HealthCheckFilter())

# Reduce noise from third-party libraries
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("pymongo.command").setLevel(logging.WARNING)
logging.getLogger("pymongo.topology").setLevel(logging.WARNING)
logging.getLogger("pymongo.connection").setLevel(logging.WARNING)
logging.getLogger("pymongo.pool").setLevel(logging.WARNING)
logging.getLogger("pymongo.server").setLevel(logging.WARNING)

# ─── Config ───────────────────────────────────────────────────────────────────
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
JWT_SECRET     = os.environ["JWT_SECRET"]
JWT_EXPIRES    = int(os.getenv("JWT_EXPIRES", 60))  # minutes

AZURE_API_KEY = os.getenv("AZURE_API_KEY", "your-azure-api-key")
AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT", "your-endpoint")
AZURE_VERSION = os.getenv("AZURE_VERSION", "your-version")

# Google Drive configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "your-google-client-id")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "your-google-client-secret")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5000/auth/google/callback")

# Email integration configuration
# Gmail uses the same OAuth app and redirect URI as Google Drive
GMAIL_REDIRECT_URI = GOOGLE_REDIRECT_URI  # Same callback for both services

MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID", "your-microsoft-client-id")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET", "your-microsoft-client-secret")
MICROSOFT_REDIRECT_URI = os.getenv("MICROSOFT_REDIRECT_URI", "http://localhost:5000/auth/microsoft/callback")
MICROSOFT_TENANT_ID = os.getenv("MICROSOFT_TENANT_ID", "common")

EMAIL_ENCRYPTION_KEY = os.environ["EMAIL_ENCRYPTION_KEY"]

# WhatsApp service configuration
WHATSAPP_SERVICE_URL = os.getenv("WHATSAPP_SERVICE_URL", "http://whatsapp-service:8888")

# Maximum character limit for RAG insertion (prevent oversized documents)
MAX_RAG_CONTENT_LENGTH = int(os.getenv("MAX_RAG_CONTENT_LENGTH", 10000))  # 500k characters default

# Gmail OAuth2 Scopes for email
GMAIL_EMAIL_SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly'
]

# Microsoft OAuth2 Scopes for email
MICROSOFT_EMAIL_SCOPES = [
    'https://graph.microsoft.com/Mail.Read',
    'https://graph.microsoft.com/User.Read'
]

# Microsoft OAuth2 Scopes for OneDrive
MICROSOFT_ONEDRIVE_SCOPES = [
    'https://graph.microsoft.com/Files.Read',
    'https://graph.microsoft.com/User.Read'
]

# Google Drive OAuth2 Scopes (order matters for consistency)
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/drive.metadata.readonly',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]
azure_client = AzureOpenAI(api_key=AZURE_API_KEY, azure_endpoint=AZURE_ENDPOINT, api_version=AZURE_VERSION)

# ─── Utilities ────────────────────────────────────────────────────────────────

def normalize_phone(p: str) -> str:
    """Basic phone normalization: strip spaces, dashes, and leading '+'."""
    if not isinstance(p, str):
        return ""
    return p.replace(" ", "").replace("-", "").lstrip("+")

def oid(id_str: str):
    """Return ObjectId or None if invalid."""
    try:
        return ObjectId(id_str)
    except Exception:
        return None

def json_cursor(cursor):
    """Serialize a cursor/iterable to JSON and return a Flask Response."""
    return Response(dumps(cursor), mimetype="application/json")

def generate_token(subject: str, extra: dict | None = None) -> str:
    """Create and sign a JWT. `extra` lets you add custom claims (role, uid, company_id, etc.)."""
    now = datetime.datetime.utcnow()
    payload = {
        "sub": subject,
        "iat": now,
        "nbf": now,
        "exp": now + datetime.timedelta(minutes=JWT_EXPIRES),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def generate_api_key() -> str:
    """Generate a URL-safe API key for external chat access."""
    return secrets.token_urlsafe(32)

def verify_token():
    """Decode the bearer token from the Authorization header or raise."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise jwt.InvalidTokenError("Missing Bearer token")
    token = auth_header.split(" ", 1)[1]
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])

def token_required(f):
    """View decorator that enforces JWT authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            request.user = verify_token()  # store the decoded payload
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError as exc:
            return jsonify({"error": str(exc)}), 401
        return f(*args, **kwargs)
    return decorated

def is_admin() -> bool:
    return (request.user or {}).get("role") == "admin"

def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_admin():
            return jsonify({"error": "Admin only"}), 403
        return f(*args, **kwargs)
    return wrapper

def claim_company_id() -> str | None:
    return (request.user or {}).get("company_id")

def claim_user_oid() -> ObjectId | None:
    uid = (request.user or {}).get("uid")
    return oid(uid) if uid else None

def store_google_oauth_pkce_state(state: str, company_id: str, service_type: str, code_verifier: str):
    """Persist PKCE verifier by OAuth state so callback can exchange code reliably across workers."""
    now = datetime.datetime.utcnow()
    expires_at = now + datetime.timedelta(minutes=15)
    oauth_states_col.update_one(
        {"state": state},
        {"$set": {
            "state": state,
            "company_id": company_id,
            "service_type": service_type,
            "provider": "google",
            "code_verifier": code_verifier,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat()
        }},
        upsert=True
    )
    # Best-effort cleanup of stale state rows
    oauth_states_col.delete_many({"expires_at": {"$lt": now.isoformat()}})

def pop_google_oauth_pkce_state(state: str):
    """Fetch and remove stored PKCE verifier for one-time OAuth code exchange."""
    doc = oauth_states_col.find_one({"state": state, "provider": "google"})
    if doc:
        oauth_states_col.delete_one({"_id": doc["_id"]})
    return doc

# ─── App & DB ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=True,
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://localhost:27017/companydb")

# Configure maximum file upload size (default 50MB, can be overridden with env var)
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_MB", 50)) * 1024 * 1024  # Convert MB to bytes
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_SIZE

mongo = PyMongo(app)

companies_col = mongo.db.companies
metadata_col  = mongo.db.company_metadata
users_col     = mongo.db.users
settings_col  = mongo.db.settings
oauth_states_col = mongo.db.oauth_states

# ─── Error Handlers ───────────────────────────────────────────────────────────
@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle request entity too large error (file upload too big)"""
    max_size_mb = int(os.getenv("MAX_UPLOAD_SIZE_MB", 50))
    return jsonify({
        "error": "File upload too large",
        "message": f"Maximum upload size is {max_size_mb}MB. Please select smaller files or reduce the number of files uploaded at once.",
        "max_size_mb": max_size_mb
    }), 413

@app.errorhandler(400)
def bad_request(error):
    """Handle bad request errors"""
    return jsonify({"error": "Bad request", "message": str(error)}), 400

# ─── Automatic Google Drive Sync ─────────────────────────────────────────────
def sync_all_google_drives():
    """Automatically sync all connected Google Drive accounts"""
    try:
        app.logger.info("Starting automatic Google Drive sync for all companies")

        # Find all companies with connected Google Drive
        connected_companies = companies_col.find({
            "google_drive.connected": True,
            "google_drive.credentials": {"$exists": True}
        })

        sync_results = []

        for company in connected_companies:
            company_id = str(company["_id"])
            company_name = company.get("name", "Unknown")

            try:
                app.logger.info(f"Syncing Google Drive for company: {company_name} ({company_id})")

                google_drive_config = company.get("google_drive", {})
                creds_dict = google_drive_config.get("credentials")

                if not creds_dict:
                    app.logger.warning(f"No credentials found for company {company_name}")
                    continue

                # Reconstruct credentials
                creds_dict = google_drive_config.get("credentials")

                if not creds_dict:
                    app.logger.warning(f"No credentials found for company {company_name}")
                    continue

                # Validate that all required fields are present and not None
                required_fields = ['token', 'refresh_token', 'token_uri', 'client_id', 'client_secret']
                missing_fields = []
                for field in required_fields:
                    if not creds_dict.get(field):
                        missing_fields.append(field)

                if missing_fields:
                    app.logger.error(f"Missing credential fields for company {company_name}: {missing_fields}. Reconnection required.")
                    sync_results.append({
                        "company_id": company_id,
                        "company_name": company_name,
                        "status": "error",
                        "error": f"Missing credential fields: {missing_fields}. Please reconnect Google Drive.",
                        "requires_reauth": True
                    })
                    continue

                credentials = Credentials(
                    token=creds_dict.get("token"),
                    refresh_token=creds_dict.get("refresh_token"),
                    token_uri=creds_dict.get("token_uri"),
                    client_id=creds_dict.get("client_id"),
                    client_secret=creds_dict.get("client_secret"),
                    scopes=creds_dict.get("scopes")
                )

                # Refresh credentials if needed
                if credentials.expired and credentials.refresh_token:
                    success, error = refresh_google_credentials(credentials, company_id, company["_id"])
                    if not success:
                        sync_results.append({
                            "company_id": company_id,
                            "company_name": company_name,
                            "status": "error",
                            "error": error
                        })
                        continue

                # Build Drive service
                service = build('drive', 'v3', credentials=credentials)

                # Get or update email address if missing
                if not google_drive_config.get("email_address"):
                    try:
                        # Use OAuth2 service to get user info
                        oauth2_service = build('oauth2', 'v2', credentials=credentials)
                        user_info = oauth2_service.userinfo().get().execute()
                        email_address = user_info.get('email', '')

                        if email_address:
                            app.logger.info(f"Retrieved missing email address for company {company_name}: {email_address}")
                            companies_col.update_one(
                                {"_id": company["_id"]},
                                {"$set": {"google_drive.email_address": email_address}}
                            )
                    except Exception as e:
                        app.logger.warning(f"Failed to retrieve email address for company {company_name}: {e}")

                # Get monitored folders
                monitored_folders = google_drive_config.get("monitored_folders", [])

                synced_count = 0

                if not monitored_folders:
                    # If no specific folders are monitored, skip this company
                    # This prevents syncing all files when no folders are selected
                    app.logger.info(f"Skipping company {company_name} - no folders selected for monitoring")
                    sync_results.append({
                        "company_id": company_id,
                        "company_name": company_name,
                        "status": "skipped",
                        "message": "No folders selected for monitoring"
                    })
                    continue
                else:
                    # Sync files from monitored folders only
                    files = []
                    for folder_id in monitored_folders:
                        try:
                            folder_results = service.files().list(
                                q=f"'{folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder'",
                                pageSize=50,
                                fields="nextPageToken, files(id, name, mimeType, modifiedTime, size, parents)",
                                supportsAllDrives=True,
                                includeItemsFromAllDrives=True,
                                corpora="allDrives"
                            ).execute()
                            files.extend(folder_results.get('files', []))
                        except HttpError as e:
                            app.logger.warning(f"Error accessing folder {folder_id} for company {company_name}: {e}")
                            continue

                # Process each file
                for file_info in files:
                    try:
                        file_id = file_info['id']
                        file_name = file_info['name']
                        mime_type = file_info['mimeType']
                        modified_time = file_info['modifiedTime']

                        # Check if we already have this file with the same modification time
                        existing_metadata = metadata_col.find_one({
                            "company_id": company_id,
                            "type": "google_drive_file",
                            "google_drive.file_id": file_id,
                            "google_drive.modified_time": modified_time
                        })

                        if existing_metadata:
                            continue  # Skip if already up-to-date

                        # Download and process the file
                        content = ""
                        supported_mime_types = [
                            'text/plain',
                            'text/csv',
                            'application/pdf',
                            'application/vnd.google-apps.document',
                            'application/vnd.google-apps.spreadsheet',
                            'application/vnd.google-apps.presentation',
                            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                            'application/msword',
                            'application/vnd.ms-excel',
                            'application/vnd.ms-powerpoint'
                        ]

                        if mime_type in supported_mime_types:
                            content = download_and_extract_content(service, file_id, mime_type)

                        if content:
                            # STEP 1: Create/update metadata document in MongoDB
                            now = datetime.datetime.utcnow().isoformat()

                            # Check if we already have metadata for this file (by file_id)
                            existing_doc = metadata_col.find_one({
                                "company_id": company_id,
                                "type": "google_drive_file",
                                "google_drive.file_id": file_id
                            })

                            if existing_doc:
                                # Update existing document
                                mongodb_id = str(existing_doc["_id"])
                                metadata_col.update_one(
                                    {"_id": existing_doc["_id"]},
                                    {
                                        "$set": {
                                            "content": {"full_content": content},
                                            "text_length": len(content),
                                            "google_drive": {
                                                "file_id": file_id,
                                                "file_name": file_name,
                                                "mime_type": mime_type,
                                                "modified_time": modified_time,
                                                "size": file_info.get('size'),
                                                "parent_folders": file_info.get('parents', [])
                                            },
                                            "updated_at": now,
                                            "rag_sync_status": "waiting"
                                        }
                                    }
                                )
                                app.logger.info(f"Updated metadata for Google Drive file {file_name}")

                                # STEP 2: Check content size before RAG update
                                if len(content) > MAX_RAG_CONTENT_LENGTH:
                                    app.logger.warning(f"Google Drive file {file_name} too large for update ({len(content)} chars, max {MAX_RAG_CONTENT_LENGTH})")
                                    metadata_col.update_one(
                                        {"_id": ObjectId(mongodb_id)},
                                        {"$set": {"rag_sync_status": "too_large"}}
                                    )
                                else:
                                    # Enqueue for background RAG UPDATE (delete + reinsert)
                                    enqueue_rag_update(
                                        company_id=company_id,
                                        doc_id=mongodb_id,
                                        content=content,
                                        metadata={
                                            "source": "google_drive",
                                            "file_id": mongodb_id,
                                            "file_name": file_name,
                                            "mime_type": mime_type,
                                            "modified_time": modified_time,
                                            "size": file_info.get('size'),
                                            "parent_folders": file_info.get('parents', []),
                                            "updated_at": now
                                        }
                                    )
                                    app.logger.info(f"Enqueued RAG update for Google Drive file {file_name}")
                            else:
                                # Create new metadata document
                                metadata_doc = {
                                    "company_id": company_id,
                                    "type": "google_drive_file",
                                    "source": "google_drive",
                                    "title": file_name,
                                    "content": {"full_content": content},
                                    "text_length": len(content),
                                    "google_drive": {
                                        "file_id": file_id,
                                        "file_name": file_name,
                                        "mime_type": mime_type,
                                        "modified_time": modified_time,
                                        "size": file_info.get('size'),
                                        "parent_folders": file_info.get('parents', [])
                                    },
                                    "created_at": now,
                                    "updated_at": now,
                                    "rag_sync_status": "waiting"
                                }
                                app.logger.info(f"[RAG] Queuing Google Drive file {file_name} for RAG insertion at {now}")
                                result = metadata_col.insert_one(metadata_doc)
                                mongodb_id = str(result.inserted_id)
                                app.logger.info(f"Created metadata for Google Drive file {file_name} with ID: {mongodb_id}")

                            # STEP 2: Check content size before RAG insertion
                            if len(content) > MAX_RAG_CONTENT_LENGTH:
                                app.logger.warning(f"Google Drive file {file_name} too large ({len(content)} chars, max {MAX_RAG_CONTENT_LENGTH})")
                                metadata_col.update_one(
                                    {"_id": ObjectId(mongodb_id)},
                                    {"$set": {"rag_sync_status": "too_large"}}
                                )
                                synced_count += 1
                            else:
                                # Enqueue for background RAG insertion
                                enqueue_rag_insertion(
                                    company_id=company_id,
                                    doc_id=mongodb_id,
                                    content=content,
                                    metadata={
                                        "source": "google_drive",
                                        "file_id": mongodb_id,
                                        "file_name": file_name,
                                        "mime_type": mime_type,
                                        "modified_time": modified_time,
                                        "size": file_info.get('size'),
                                        "parent_folders": file_info.get('parents', []),
                                        "updated_at": now
                                    }
                                )
                                synced_count += 1
                                app.logger.info(f"Enqueued RAG insertion for Google Drive file {file_name}")

                    except Exception as e:
                        app.logger.error(f"Error processing file {file_info.get('name', 'unknown')} for company {company_name}: {e}")
                        continue

                # STEP 3: Detect and remove deleted files
                # Get all file IDs from Google Drive API
                drive_file_ids = {file_info['id'] for file_info in files}

                # Get all file IDs from MongoDB for this company
                mongodb_files = list(metadata_col.find(
                    {"company_id": company_id, "type": "google_drive_file"},
                    {"_id": 1, "google_drive.file_id": 1}
                ))

                # Find files that exist in MongoDB but not in Google Drive
                deleted_docs = []
                for doc in mongodb_files:
                    drive_file_id = doc.get("google_drive", {}).get("file_id")
                    if drive_file_id and drive_file_id not in drive_file_ids:
                        deleted_docs.append(doc)

                if deleted_docs:
                    app.logger.info(f"Found {len(deleted_docs)} deleted files for company {company_name}")
                    doc_ids = [str(doc["_id"]) for doc in deleted_docs]

                    # Delete from LightRAG first
                    bulk_delete_company_documents(company_id, doc_ids)

                    # Then delete from MongoDB
                    result = metadata_col.delete_many({
                        "_id": {"$in": [doc["_id"] for doc in deleted_docs]}
                    })
                    app.logger.info(f"Removed {result.deleted_count} deleted Google Drive files from MongoDB and LightRAG")

                # Update sync status only for companies that were actually synced
                if monitored_folders:  # Only update if folders were actually processed
                    # Calculate total count of Google Drive files for this company
                    total_file_count = metadata_col.count_documents({
                        "company_id": company_id,
                        "type": "google_drive_file"
                    })

                    # Update sync status
                    companies_col.update_one(
                        {"_id": company["_id"]},
                        {
                            "$set": {
                                "google_drive.last_sync": datetime.datetime.utcnow().isoformat(),
                                "google_drive.file_count": total_file_count,
                                "google_drive.folder_count": len(monitored_folders)
                            }
                        }
                    )

                    sync_results.append({
                        "company_id": company_id,
                        "company_name": company_name,
                        "synced_files": synced_count,
                    "total_files": total_file_count,
                    "status": "success"
                })

                app.logger.info(f"Successfully synced {synced_count} files for company {company_name}. Total files: {total_file_count}")

            except HttpError as e:
                app.logger.error(f"Google Drive API error for company {company_name}: {e}")
                sync_results.append({
                    "company_id": company_id,
                    "company_name": company_name,
                    "status": "error",
                    "error": f"Google Drive API error: {str(e)}"
                })
            except Exception as e:
                app.logger.error(f"Error syncing Google Drive for company {company_name}: {e}")
                sync_results.append({
                    "company_id": company_id,
                    "company_name": company_name,
                    "status": "error",
                    "error": str(e)
                })

        app.logger.info(f"Automatic Google Drive sync completed. Processed {len(sync_results)} companies")
        return sync_results

    except Exception as e:
        app.logger.error(f"Fatal error in automatic Google Drive sync: {e}")
        return []

# ─── Automatic OneDrive Sync ─────────────────────────────────────────────────
def sync_all_onedrives():
    """Automatically sync all connected OneDrive accounts"""
    try:
        app.logger.info("Starting automatic OneDrive sync for all companies")

        # Find all companies with connected OneDrive
        connected_companies = companies_col.find({
            "onedrive.connected": True,
            "onedrive.credentials": {"$exists": True}
        })

        sync_results = []

        for company in connected_companies:
            try:
                company_id = str(company["_id"])
                company_name = company.get("name", "Unknown")
                app.logger.info(f"Syncing OneDrive for company: {company_name} ({company_id})")

                onedrive_config = company.get("onedrive", {})
                creds_dict = onedrive_config.get("credentials")

                if not creds_dict:
                    sync_results.append({
                        "company_id": company_id,
                        "company_name": company_name,
                        "status": "error",
                        "error": "No OneDrive credentials found"
                    })
                    continue

                # Get monitored folders
                monitored_folders = onedrive_config.get("monitored_folders", [])

                if not monitored_folders:
                    # If no specific folders are monitored, skip this company
                    app.logger.info(f"Skipping company {company_name} - no folders selected for monitoring")
                    sync_results.append({
                        "company_id": company_id,
                        "company_name": company_name,
                        "status": "skipped",
                        "message": "No folders selected for monitoring"
                    })
                    continue

                # Sync OneDrive files using Microsoft Graph API
                import requests
                access_token = creds_dict.get("access_token")
                if not access_token:
                    sync_results.append({
                        "company_id": company_id,
                        "company_name": company_name,
                        "status": "error",
                        "error": "No access token found"
                    })
                    continue

                headers = {"Authorization": f"Bearer {access_token}"}
                synced_count = 0

                # Track all file IDs from OneDrive for deletion detection
                onedrive_file_ids = set()

                # Process each monitored folder
                for folder_id in monitored_folders:
                    try:
                        # Get files from this folder
                        files_url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children"
                        files_response = requests.get(files_url, headers=headers)

                        if files_response.status_code == 401:
                            # Token expired, try to refresh
                            success, error = refresh_microsoft_credentials(creds_dict, company_id, company["_id"])
                            if success:
                                # Update headers with new token
                                updated_company = companies_col.find_one({"_id": company["_id"]})
                                updated_creds = updated_company.get("onedrive", {}).get("credentials", {})
                                access_token = updated_creds.get("access_token")
                                headers = {"Authorization": f"Bearer {access_token}"}
                                # Retry the request
                                files_response = requests.get(files_url, headers=headers)
                            else:
                                app.logger.error(f"Failed to refresh OneDrive credentials for {company_name}: {error}")
                                continue

                        if files_response.status_code != 200:
                            app.logger.warning(f"Error accessing OneDrive folder {folder_id} for company {company_name}: {files_response.status_code}")
                            continue

                        files_data = files_response.json()
                        files = files_data.get("value", [])

                        # Process each file
                        for file_info in files:
                            try:
                                # Skip folders
                                if "folder" in file_info:
                                    continue

                                file_id = file_info['id']
                                file_name = file_info['name']
                                modified_time = file_info['lastModifiedDateTime']

                                # Track this file ID for deletion detection
                                onedrive_file_ids.add(file_id)

                                # Check if this file already exists and is up to date
                                existing = metadata_col.find_one({
                                    "company_id": company_id,
                                    "type": "onedrive_file",
                                    "content.file_id": file_id
                                })

                                if existing and existing.get("content", {}).get("modified_time") == modified_time:
                                    continue  # File hasn't changed, skip

                                # Download and extract content
                                content_text = download_and_extract_onedrive_content(file_info, headers)
                                if not content_text:
                                    continue

                                # STEP 1: Create/update metadata document in MongoDB
                                now = datetime.datetime.utcnow().isoformat()

                                # Check if we already have metadata for this file
                                if existing:
                                    # Update existing document
                                    mongodb_id = str(existing["_id"])
                                    metadata_col.update_one(
                                        {"_id": existing["_id"]},
                                        {
                                            "$set": {
                                                "content": {
                                                    "full_content": content_text,
                                                    "file_id": file_id,
                                                    "file_name": file_name,
                                                    "modified_time": modified_time
                                                },
                                                "text_length": len(content_text),
                                                "updated_at": now,
                                                "rag_sync_status": "waiting"
                                            }
                                        }
                                    )
                                    app.logger.info(f"[RAG] Queuing OneDrive file update {file_name} for RAG update at {now}")

                                    # STEP 2: Check content size before RAG update
                                    if len(content_text) > MAX_RAG_CONTENT_LENGTH:
                                        app.logger.warning(f"OneDrive file {file_name} too large for update ({len(content_text)} chars, max {MAX_RAG_CONTENT_LENGTH})")
                                        metadata_col.update_one(
                                            {"_id": ObjectId(mongodb_id)},
                                            {"$set": {"rag_sync_status": "too_large"}}
                                        )
                                    else:
                                        # Enqueue for background RAG UPDATE (delete + reinsert)
                                        enqueue_rag_update(
                                            company_id=company_id,
                                            doc_id=mongodb_id,
                                            content=content_text,
                                            metadata={
                                                "source": "onedrive",
                                                "file_id": mongodb_id,
                                                "file_name": file_name,
                                                "modified_time": modified_time,
                                                "folder_id": folder_id,
                                                "updated_at": now
                                            }
                                        )
                                        app.logger.info(f"Enqueued RAG update for OneDrive file {file_name}")
                                else:
                                    # Create new metadata document
                                    metadata_doc = {
                                        "company_id": company_id,
                                    "type": "onedrive_file",
                                    "source": "onedrive",
                                    "title": file_name,
                                    "content": {
                                        "full_content": content_text,
                                        "file_id": file_id,
                                        "file_name": file_name,
                                        "modified_time": modified_time
                                    },
                                    "text_length": len(content_text),
                                    "created_at": now,
                                    "updated_at": now,
                                    "rag_sync_status": "waiting"
                                }
                                    app.logger.info(f"[RAG] Queuing OneDrive file {file_name} for RAG insertion at {now}")
                                    result = metadata_col.insert_one(metadata_doc)
                                    mongodb_id = str(result.inserted_id)

                                    # STEP 2: Check content size before RAG insertion
                                    if len(content_text) > MAX_RAG_CONTENT_LENGTH:
                                        app.logger.warning(f"OneDrive file {file_name} too large ({len(content_text)} chars, max {MAX_RAG_CONTENT_LENGTH})")
                                        metadata_col.update_one(
                                            {"_id": ObjectId(mongodb_id)},
                                            {"$set": {"rag_sync_status": "too_large"}}
                                        )
                                    else:
                                        # Enqueue for background RAG insertion
                                        enqueue_rag_insertion(
                                            company_id=company_id,
                                            doc_id=mongodb_id,
                                            content=content_text,
                                            metadata={
                                                "source": "onedrive",
                                                "file_id": mongodb_id,
                                                "file_name": file_name,
                                                "modified_time": modified_time,
                                                "folder_id": folder_id,
                                                "updated_at": now
                                            }
                                        )
                                        app.logger.info(f"Enqueued RAG insertion for OneDrive file {file_name}")

                                    synced_count += 1

                            except Exception as e:
                                app.logger.error(f"Error processing OneDrive file {file_info.get('name', 'unknown')} for company {company_name}: {e}")
                                continue

                    except Exception as e:
                        app.logger.error(f"Error accessing OneDrive folder {folder_id} for company {company_name}: {e}")
                        continue

                # STEP 3: Detect and remove deleted files
                # Get all file IDs from MongoDB for this company
                mongodb_files = list(metadata_col.find(
                    {"company_id": company_id, "type": "onedrive_file"},
                    {"_id": 1, "content.file_id": 1}
                ))

                # Find files that exist in MongoDB but not in OneDrive
                deleted_docs = []
                for doc in mongodb_files:
                    onedrive_file_id = doc.get("content", {}).get("file_id")
                    if onedrive_file_id and onedrive_file_id not in onedrive_file_ids:
                        deleted_docs.append(doc)

                if deleted_docs:
                    app.logger.info(f"Found {len(deleted_docs)} deleted files for company {company_name}")
                    doc_ids = [str(doc["_id"]) for doc in deleted_docs]

                    # Delete from LightRAG first
                    bulk_delete_company_documents(company_id, doc_ids)

                    # Then delete from MongoDB
                    result = metadata_col.delete_many({
                        "_id": {"$in": [doc["_id"] for doc in deleted_docs]}
                    })
                    app.logger.info(f"Removed {result.deleted_count} deleted OneDrive files from MongoDB and LightRAG")

                # Update company's OneDrive sync status
                companies_col.update_one(
                    {"_id": company["_id"]},
                    {
                        "$set": {
                            "onedrive.last_sync": datetime.datetime.utcnow().isoformat(),
                            "onedrive.sync_status": "success",
                            "onedrive.file_count": synced_count
                        }
                    }
                )

                sync_results.append({
                    "company_id": company_id,
                    "company_name": company_name,
                    "status": "success",
                    "files_synced": synced_count
                })

            except Exception as e:
                app.logger.error(f"Error syncing OneDrive for company {company.get('name', 'unknown')}: {e}")
                sync_results.append({
                    "company_id": str(company["_id"]),
                    "company_name": company.get("name", "Unknown"),
                    "status": "error",
                    "error": str(e)
                })

        app.logger.info(f"Automatic OneDrive sync completed. Processed {len(sync_results)} companies")
        return sync_results

    except Exception as e:
        app.logger.error(f"Fatal error in automatic OneDrive sync: {e}")
        return []

# ─── Automatic Email Sync ────────────────────────────────────────────────────
def sync_all_emails():
    """Automatically sync all connected email accounts"""
    try:
        app.logger.info("Starting automatic email sync for all companies")

        if not EMAIL_PROVIDERS_AVAILABLE:
            app.logger.warning("Email providers not available, skipping email sync")
            return []

        # Find all companies with connected email integration
        connected_companies = companies_col.find({
            "email_integration.connected": True,
            "email_integration.credentials": {"$exists": True}
        })

        sync_results = []

        for company in connected_companies:
            company_id = str(company["_id"])
            company_name = company.get("name", "Unknown")

            try:
                app.logger.info(f"Syncing emails for company: {company_name} ({company_id})")

                email_config = company.get("email_integration", {})
                provider = email_config.get("provider")
                credentials = email_config.get("credentials")

                if not provider or not credentials:
                    app.logger.warning(f"No email provider or credentials found for company {company_name}")
                    continue

                # Get email provider
                email_provider = get_email_provider(
                    provider_type=provider,
                    client_id=GOOGLE_CLIENT_ID if provider == "gmail" else MICROSOFT_CLIENT_ID,
                    client_secret=GOOGLE_CLIENT_SECRET if provider == "gmail" else MICROSOFT_CLIENT_SECRET,
                    tenant_id=MICROSOFT_TENANT_ID if provider == "microsoft" else None,
                    encryption_key=EMAIL_ENCRYPTION_KEY if provider == "generic" else None
                )

                # Authenticate
                auth_success, auth_error = email_provider.authenticate(credentials)
                if not auth_success:
                    sync_results.append({
                        "company_id": company_id,
                        "company_name": company_name,
                        "status": "error",
                        "error": f"Authentication failed: {auth_error}",
                        "requires_reauth": True
                    })
                    continue

                # Calculate since date - keep emails from last 7 days
                since_date = datetime.datetime.utcnow() - datetime.timedelta(days=7)
                cutoff_date = datetime.datetime.utcnow() - datetime.timedelta(days=7)
                max_emails_per_sync = 200  # Increased limit

                # Delete old emails (older than 7 days)
                # First, get the IDs of old emails to delete
                old_emails = list(metadata_col.find({
                    "company_id": company_id,
                    "type": "email",
                    "content.date": {"$lt": cutoff_date.isoformat()}
                }, {"_id": 1}))

                if old_emails:
                    old_email_ids = [str(email["_id"]) for email in old_emails]
                    app.logger.info(f"Deleting {len(old_email_ids)} old emails from LightRAG for company {company_name}...")

                    # Delete from LightRAG FIRST
                    lightrag_response = bulk_delete_company_documents(company_id, old_email_ids)
                    if lightrag_response.get("status") == "completed":
                        lightrag_result = lightrag_response.get("results", {})
                        app.logger.info(
                            f"LightRAG cleanup: {lightrag_result.get('successful', 0)} successful, "
                            f"{lightrag_result.get('failed', 0)} failed"
                        )

                    # Then delete from MongoDB
                    deleted_count = metadata_col.delete_many({
                        "company_id": company_id,
                        "type": "email",
                        "content.date": {"$lt": cutoff_date.isoformat()}
                    }).deleted_count

                    app.logger.info(f"Deleted {deleted_count} old emails from MongoDB for company {company_name}")

                # Get sync settings for folders (but ignore other settings)
                settings = email_config.get("settings", {})
                sync_folders = settings.get("sync_folders", ["INBOX"])

                synced_count = 0

                # Sync each folder
                for folder in sync_folders:
                    try:
                        emails = email_provider.fetch_emails(folder, since_date, max_emails_per_sync)

                        for email_data in emails:
                            try:
                                # Check if email already exists
                                existing_email = metadata_col.find_one({
                                    "company_id": company_id,
                                    "type": "email",
                                    "email_metadata.message_id": email_data["message_id"]
                                })

                                if existing_email:
                                    continue

                                # Create email content for LightRAG
                                combined_content = f"Subject: {email_data['subject']}\nFrom: {email_data['sender']}\nTo: {email_data['recipients']}\nDate: {email_data['date'].isoformat()}\n\n{email_data['body_text']}"

                                # STEP 1: Create metadata document in MongoDB
                                now = datetime.datetime.utcnow().isoformat()
                                metadata_doc = {
                                    "company_id": company_id,
                                    "type": "email",
                                    "source": "email",
                                    "title": email_data["subject"],
                                    "content": {
                                        "subject": email_data["subject"],
                                        "sender": email_data["sender"],
                                        "recipients": email_data["recipients"],
                                        "date": email_data["date"].isoformat(),
                                        "body_text": email_data["body_text"]
                                    },
                                    "text_length": len(combined_content),
                                    "email_metadata": {
                                        "message_id": email_data["message_id"],
                                        "folder": email_data["folder"],
                                        "provider": provider
                                    },
                                    "created_at": now,
                                    "updated_at": now,
                                    "rag_sync_status": "waiting"
                                }
                                app.logger.info(f"[RAG] Queuing email '{email_data['subject']}' for RAG insertion at {now}")

                                result = metadata_col.insert_one(metadata_doc)
                                mongodb_id = str(result.inserted_id)

                                # STEP 2: Check content size before RAG insertion
                                if len(combined_content) > MAX_RAG_CONTENT_LENGTH:
                                    app.logger.warning(f"Email '{email_data['subject']}' too large ({len(combined_content)} chars, max {MAX_RAG_CONTENT_LENGTH})")
                                    metadata_col.update_one(
                                        {"_id": ObjectId(mongodb_id)},
                                        {"$set": {"rag_sync_status": "too_large"}}
                                    )
                                else:
                                    # Enqueue for background RAG insertion
                                    enqueue_rag_insertion(
                                        company_id=company_id,
                                        doc_id=mongodb_id,
                                        content=combined_content,
                                        metadata={
                                            "source": "email",
                                            "file_id": mongodb_id,
                                            "message_id": email_data["message_id"],
                                            "subject": email_data["subject"],
                                            "sender": email_data["sender"],
                                            "recipients": email_data["recipients"],
                                            "cc": email_data["cc"],
                                            "bcc": email_data["bcc"],
                                            "date": email_data["date"].isoformat(),
                                            "folder": email_data["folder"],
                                            "provider": provider,
                                            "updated_at": now
                                        }
                                    )
                                synced_count += 1

                            except Exception as e:
                                app.logger.error(f"Error processing email for company {company_name}: {e}")
                                continue

                    except Exception as e:
                        app.logger.error(f"Error syncing folder {folder} for company {company_name}: {e}")
                        continue

                # If we have more than 200 emails total, keep only the newest 200
                total_emails = metadata_col.count_documents({
                    "company_id": company_id,
                    "type": "email"
                })

                if total_emails > max_emails_per_sync:
                    # Get all emails sorted by date descending
                    all_emails = list(metadata_col.find({
                        "company_id": company_id,
                        "type": "email"
                    }).sort("content.date", -1))

                    # Keep only the newest max_emails_per_sync emails
                    emails_to_keep = all_emails[:max_emails_per_sync]
                    emails_to_delete = all_emails[max_emails_per_sync:]

                    # Delete the older emails
                    if emails_to_delete:
                        email_ids_to_delete = [email["_id"] for email in emails_to_delete]
                        email_ids_str = [str(email_id) for email_id in email_ids_to_delete]

                        app.logger.info(f"Deleting {len(email_ids_str)} excess emails from LightRAG for company {company_name}...")

                        # Delete from LightRAG FIRST
                        lightrag_response = bulk_delete_company_documents(company_id, email_ids_str)
                        if lightrag_response.get("status") == "completed":
                            lightrag_result = lightrag_response.get("results", {})
                            app.logger.info(
                                f"LightRAG bulk delete: {lightrag_result.get('successful', 0)} successful, "
                                f"{lightrag_result.get('failed', 0)} failed"
                            )

                        # Then delete from MongoDB
                        deleted_excess = metadata_col.delete_many({
                            "_id": {"$in": email_ids_to_delete}
                        }).deleted_count

                        app.logger.info(f"Deleted {deleted_excess} excess emails from MongoDB to maintain limit of {max_emails_per_sync} for company {company_name}")

                # Disconnect from email provider
                email_provider.disconnect()

                # Update company's email sync status
                companies_col.update_one(
                    {"_id": company["_id"]},
                    {
                        "$set": {
                            "email_integration.last_sync": datetime.datetime.utcnow().isoformat(),
                            "email_integration.stats.total_emails_synced":
                                email_config.get("stats", {}).get("total_emails_synced", 0) + synced_count,
                            "email_integration.stats.last_sync_count": synced_count
                        }
                    }
                )

                sync_results.append({
                    "company_id": company_id,
                    "company_name": company_name,
                    "status": "success",
                    "emails_synced": synced_count
                })

            except Exception as e:
                app.logger.error(f"Error syncing emails for company {company_name}: {e}")
                sync_results.append({
                    "company_id": company_id,
                    "company_name": company_name,
                    "status": "error",
                    "error": str(e)
                })

        app.logger.info(f"Automatic email sync completed. Processed {len(sync_results)} companies")
        return sync_results

    except Exception as e:
        app.logger.error(f"Fatal error in automatic email sync: {e}")
        return []

# ─── Automatic WhatsApp Reminder ──────────────────────────────────────────────
def send_weekly_reminders():
    """Send WhatsApp reminders to inactive users in production companies"""
    try:
        app.logger.info("Starting weekly WhatsApp reminder task")

        # Get conversations collection
        conversations_col = mongo.db.conversations

        # Step 1: Find all production companies
        production_companies = companies_col.find({"environment": "production"})

        reminder_stats = {
            "companies_checked": 0,
            "users_checked": 0,
            "reminders_sent": 0,
            "errors": 0
        }

        # Calculate the threshold date (7 days ago)
        from datetime import datetime, timedelta
        seven_days_ago = datetime.utcnow() - timedelta(days=7)

        for company in production_companies:
            company_id = str(company["_id"])
            company_name = company.get("name", "Unknown")
            reminder_stats["companies_checked"] += 1

            app.logger.info(f"Checking users for company: {company_name} ({company_id})")

            # Step 2: Find all users for this company
            users = users_col.find({"company_id": company_id})

            for user in users:
                phone_number = user.get("phone_number")
                first_name = user.get("first_name", "")

                if not phone_number or not first_name:
                    app.logger.warning(f"Skipping user {user.get('_id')} - missing phone number or first name")
                    continue

                reminder_stats["users_checked"] += 1

                # Step 3: Find the latest message from this user
                latest_message = conversations_col.find_one(
                    {
                        "user_id": phone_number,
                        "role": "user"
                    },
                    sort=[("timestamp", -1)]
                )

                # Check if user needs a reminder
                should_send_reminder = False

                if not latest_message:
                    # User has never sent a message
                    app.logger.info(f"User {phone_number} has never sent a message")
                    should_send_reminder = True
                else:
                    # Check if last message was over 7 days ago
                    last_message_time = latest_message.get("timestamp")

                    # Handle both datetime objects and dict with $date
                    if isinstance(last_message_time, dict) and "$date" in last_message_time:
                        last_message_time = datetime.fromisoformat(last_message_time["$date"].replace("Z", "+00:00"))

                    if last_message_time and last_message_time < seven_days_ago:
                        days_since_last_message = (datetime.utcnow() - last_message_time).days
                        app.logger.info(f"User {phone_number} last message was {days_since_last_message} days ago")
                        should_send_reminder = True
                    else:
                        app.logger.info(f"User {phone_number} is active, no reminder needed")

                # Step 4: Send reminder if needed
                if should_send_reminder:
                    try:
                        whatsapp_url = f"{WHATSAPP_SERVICE_URL}/send_template"
                        params = {
                            "phone_number": phone_number,
                            "template_name": "reminder",
                            "language_code": "en",
                            "userName": first_name
                        }

                        response = requests.get(whatsapp_url, params=params, timeout=10)

                        if response.status_code == 200:
                            reminder_stats["reminders_sent"] += 1
                            app.logger.info(f"Successfully sent reminder to {phone_number} ({first_name})")
                        else:
                            reminder_stats["errors"] += 1
                            app.logger.warning(f"Failed to send reminder to {phone_number}: {response.text}")

                    except Exception as e:
                        reminder_stats["errors"] += 1
                        app.logger.error(f"Error sending reminder to {phone_number}: {e}")

        app.logger.info(
            f"Weekly reminder task completed. "
            f"Companies: {reminder_stats['companies_checked']}, "
            f"Users checked: {reminder_stats['users_checked']}, "
            f"Reminders sent: {reminder_stats['reminders_sent']}, "
            f"Errors: {reminder_stats['errors']}"
        )

        return reminder_stats

    except Exception as e:
        app.logger.error(f"Fatal error in weekly reminder task: {e}")
        return None

# Initialize scheduler
scheduler = BackgroundScheduler()

# Schedule the sync to run at 4 AM Finnish time (Europe/Helsinki timezone)
scheduler.add_job(
    func=sync_all_google_drives,
    trigger=CronTrigger(hour=4, minute=0, timezone='Europe/Helsinki'),
    id='google_drive_auto_sync',
    name='Automatic Google Drive Sync',
    replace_existing=True
)

# Schedule OneDrive sync to run at 4:15 AM Finnish time (15 min after Google Drive)
scheduler.add_job(
    func=sync_all_onedrives,
    trigger=CronTrigger(hour=4, minute=15, timezone='Europe/Helsinki'),
    id='onedrive_auto_sync',
    name='Automatic OneDrive Sync',
    replace_existing=True
)

# Schedule email sync to run at 4:30 AM Finnish time (30 min after Google Drive)
scheduler.add_job(
    func=sync_all_emails,
    trigger=CronTrigger(hour=4, minute=30, timezone='Europe/Helsinki'),
    id='email_auto_sync',
    name='Automatic Email Sync',
    replace_existing=True
)

# Schedule weekly WhatsApp reminders every Monday at 9 AM Finnish time
scheduler.add_job(
    func=send_weekly_reminders,
    trigger=CronTrigger(day_of_week='mon', hour=9, minute=0, timezone='Europe/Helsinki'),
    id='whatsapp_weekly_reminder',
    name='Weekly WhatsApp Reminder',
    replace_existing=True
)

# Start the scheduler
scheduler.start()

# Shut down the scheduler when exiting the app
atexit.register(lambda: scheduler.shutdown())

# ─── Background RAG Processor ─────────────────────────────────────────────────
# Initialize the background processor for RAG insertions
rag_processor = init_rag_processor(metadata_col, lightrag_client)
atexit.register(lambda: rag_processor.stop())

# ─── Auth Endpoints ───────────────────────────────────────────────────────────
@app.route("/login", methods=["POST"])
def login():
    """
    POST one of:
      { "username": "admin", "password": "..." }   (env admin)
      { "username": "12025550102", "password": "..." }  (phone + admin_password)

    → { "token": "JWT" }
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        # 1) Environment admin login
        if data.get("username") == ADMIN_USERNAME and data.get("password") == ADMIN_PASSWORD:
            return jsonify(token=generate_token("admin", {"role": "admin"})), 200

        # 2) User doc login via phone_number + admin_password
        phone = normalize_phone(data.get("username", ""))
        upass = data.get("password", "")

        if phone and upass:
            app.logger.debug("Looking for user with phone: %s", phone)
            user = users_col.find_one({
                "phone_number": {"$in": [phone, f"+{phone}"]},  # accept with/without '+'
                "admin_password": upass
            })

            if user:
                app.logger.debug("Found user _id=%s", user.get("_id"))
                uid = str(user["_id"])
                extra_claims = {
                    "role": "user",
                    "uid": uid,
                    "phone_number": user.get("phone_number", phone),
                    "company_id": user.get("company_id")
                }
                return jsonify(token=generate_token(f"user:{uid}", extra_claims)), 200

        return jsonify({"error": "Invalid credentials"}), 401
    except Exception:
        app.logger.exception("Login error")
        return jsonify({"error": "Internal server error"}), 500

# ─── Companies CRUD (scoped) ──────────────────────────────────────────────────
@app.route("/companies", methods=["POST"])
@token_required
def add_company():
    if not is_admin():
        return jsonify({"error": "Admin only"}), 403
    doc = request.get_json(force=True)
    result = companies_col.insert_one(doc)
    return jsonify({"message": "Company added", "id": str(result.inserted_id)}), 201

@app.route("/companies", methods=["GET"])
@token_required
def get_companies():
    if is_admin():
        q = request.args.to_dict()
        return json_cursor(companies_col.find(q)), 200
    # non-admin: only their company
    cid = claim_company_id()
    if not cid:
        return jsonify({"error": "No company assigned"}), 403
    _id = oid(cid)
    if not _id:
        return jsonify({"error": "Invalid company id in token"}), 400
    doc = companies_col.find_one({"_id": _id})
    return (dumps([doc]) if doc else dumps([]), 200)

@app.route("/companies/<id>", methods=["GET", "PUT", "DELETE"])
@token_required
def handle_company(id):
    _id = oid(id)
    if not _id:
        return jsonify({"error": "Invalid company ID"}), 400

    if request.method == "GET":
        if not is_admin():
            # allow only their own company
            if claim_company_id() != id:
                return jsonify({"error": "Forbidden"}), 403
        doc = companies_col.find_one({"_id": _id})
        return (dumps(doc), 200) if doc else (jsonify({"error": "Company not found"}), 404)

    if request.method == "PUT":
        if not is_admin():
            if claim_company_id() != id:
                return jsonify({"error": "Forbidden"}), 403
        result = companies_col.update_one({"_id": _id}, {"$set": request.get_json(force=True)})
        if result.matched_count:
            return jsonify({"message": "Company updated"}), 200
        return jsonify({"error": "Company not found"}), 404

    if request.method == "DELETE":
        if not is_admin():
            return jsonify({"error": "Admin only"}), 403

        company_id = str(_id)
        company_doc = companies_col.find_one({"_id": _id})
        if not company_doc:
            return jsonify({"error": "Company not found"}), 404

        company_name = company_doc.get("name", "Unknown")

        try:
            # Step 1: Get count and IDs of all documents to delete
            doc_count = metadata_col.count_documents({"company_id": company_id})

            if doc_count > 0:
                app.logger.info(f"Cleaning up {doc_count} documents before deleting company {company_name} ({company_id})")

                docs = metadata_col.find({"company_id": company_id}, {"_id": 1})
                doc_ids = [str(doc["_id"]) for doc in docs]

                # Step 2: Bulk delete from LightRAG
                if doc_ids:
                    app.logger.info(f"Deleting {len(doc_ids)} documents from LightRAG...")
                    lightrag_response = bulk_delete_company_documents(company_id, doc_ids)

                    if lightrag_response.get("status") == "completed":
                        lightrag_result = lightrag_response.get("results", {})
                        app.logger.info(
                            f"LightRAG bulk delete: {lightrag_result.get('successful', 0)} successful, "
                            f"{lightrag_result.get('failed', 0)} failed"
                        )
                    else:
                        app.logger.warning(f"LightRAG bulk delete had issues: {lightrag_response.get('message', 'Unknown error')}")

                # Step 3: Delete all metadata from MongoDB
                metadata_result = metadata_col.delete_many({"company_id": company_id})
                app.logger.info(f"Deleted {metadata_result.deleted_count} metadata documents from MongoDB")

                # Step 4: Cleanup LightRAG workspace (finalize instance + drop collections)
                app.logger.info(f"Cleaning up LightRAG workspace for company {company_id}...")
                workspace_result = cleanup_company_workspace(company_id)

                if workspace_result.get("status") == "success":
                    app.logger.info(
                        f"LightRAG workspace cleanup: instance_removed={workspace_result.get('instance_removed', False)}, "
                        f"collections_dropped={workspace_result.get('collections_dropped', 0)}"
                    )
                else:
                    app.logger.warning(f"LightRAG workspace cleanup had issues: {workspace_result.get('message', 'Unknown error')}")

            # Step 5: Delete all users for this company
            users_result = users_col.delete_many({"company_id": company_id})
            app.logger.info(f"Deleted {users_result.deleted_count} users from MongoDB")

            # Step 6: Delete the company itself
            result = companies_col.delete_one({"_id": _id})
            if result.deleted_count:
                app.logger.info(f"Successfully deleted company {company_name} ({company_id})")
                return jsonify({
                    "message": "Company and all associated data deleted successfully",
                    "company_id": company_id,
                    "company_name": company_name,
                    "cleanup_details": {
                        "documents_deleted": doc_count,
                        "users_deleted": users_result.deleted_count
                    }
                }), 200
            else:
                return jsonify({"error": "Company not found"}), 404

        except Exception as e:
            app.logger.error(f"Error deleting company {company_id}: {e}", exc_info=True)
            return jsonify({"error": f"Failed to delete company: {str(e)}"}), 500

@app.route("/companies/<company_id>/api-key", methods=["GET", "POST", "DELETE"])
@token_required
def handle_company_api_key(company_id):
    """
    Manage external chat API keys for a company.
    - GET: return current API key (if any) and metadata.
    - POST: generate or regenerate a new API key.
    - DELETE: revoke the current API key.
    """
    _id = oid(company_id)
    if not _id:
        return jsonify({"error": "Invalid company ID"}), 400

    # Only admins or the company itself can manage the key
    if not is_admin() and claim_company_id() != company_id:
        return jsonify({"error": "Forbidden"}), 403

    if request.method == "GET":
        company = companies_col.find_one({"_id": _id}, {"api_key": 1, "api_key_created_at": 1})
        if not company:
            return jsonify({"error": "Company not found"}), 404
        return jsonify({
            "api_key": company.get("api_key"),
            "created_at": company.get("api_key_created_at")
        }), 200

    if request.method == "POST":
        new_key = generate_api_key()
        created_at = datetime.datetime.utcnow().isoformat()
        result = companies_col.update_one(
            {"_id": _id},
            {"$set": {"api_key": new_key, "api_key_created_at": created_at}}
        )
        if not result.matched_count:
            return jsonify({"error": "Company not found"}), 404
        return jsonify({
            "message": "API key generated",
            "api_key": new_key,
            "created_at": created_at
        }), 201

    if request.method == "DELETE":
        result = companies_col.update_one(
            {"_id": _id},
            {"$unset": {"api_key": "", "api_key_created_at": ""}}
        )
        if not result.matched_count:
            return jsonify({"error": "Company not found"}), 404
        return jsonify({"message": "API key revoked"}), 200

@app.route("/companies/<id>/cleanup", methods=["POST"])
@token_required
def cleanup_company(id):
    """
    Cleanup all data for a company before deletion

    This endpoint:
    1. Gets all document IDs for the company
    2. Bulk deletes documents from LightRAG
    3. Deletes all metadata from MongoDB
    4. Deletes all users for this company
    5. Cleans up LightRAG workspace (cache + collections)

    Must be called BEFORE deleting the company
    """
    if not is_admin():
        return jsonify({"error": "Admin only"}), 403

    _id = oid(id)
    if not _id:
        return jsonify({"error": "Invalid company ID"}), 400

    # Verify company exists
    company_doc = companies_col.find_one({"_id": _id})
    if not company_doc:
        return jsonify({"error": "Company not found"}), 404

    company_id = str(_id)
    company_name = company_doc.get("name", "Unknown")

    try:
        # Step 1: Get count and IDs of all documents to delete
        doc_count = metadata_col.count_documents({"company_id": company_id})
        docs = metadata_col.find({"company_id": company_id}, {"_id": 1, "source": 1, "type": 1})
        doc_ids = []
        file_paths = []
        for doc in docs:
            doc_id = str(doc["_id"])
            doc_ids.append(doc_id)
            # Build file_path for LightRAG routing
            source = doc.get('source', 'unknown')
            doc_type = doc.get('type', 'document')
            file_path = f"{source}/{doc_type}/{doc_id}"
            file_paths.append(file_path)

        app.logger.info(f"Starting cleanup for company {company_name} ({company_id}): {doc_count} documents")

        # Step 2: Bulk delete from LightRAG (with file_paths for proper routing)
        lightrag_result = {"total": 0, "successful": 0, "failed": 0}
        if doc_ids:
            app.logger.info(f"Deleting {len(doc_ids)} documents from LightRAG...")
            lightrag_response = bulk_delete_company_documents(company_id, doc_ids, file_paths)

            if lightrag_response.get("status") == "completed":
                lightrag_result = lightrag_response.get("results", lightrag_result)
                app.logger.info(
                    f"LightRAG bulk delete: {lightrag_result['successful']} successful, "
                    f"{lightrag_result['failed']} failed"
                )
            else:
                app.logger.error(f"LightRAG bulk delete failed: {lightrag_response.get('message', 'Unknown error')}")

        # Step 3: Delete all metadata from MongoDB
        metadata_result = metadata_col.delete_many({"company_id": company_id})
        app.logger.info(f"Deleted {metadata_result.deleted_count} metadata documents from MongoDB")

        # Step 4: Delete all users for this company
        users_result = users_col.delete_many({"company_id": company_id})
        app.logger.info(f"Deleted {users_result.deleted_count} users from MongoDB")

        # Step 5: Cleanup LightRAG workspace (finalize both instances + drop collections)
        app.logger.info(f"Cleaning up LightRAG workspaces (main + memories) for company {company_id}...")
        workspace_result = cleanup_company_workspace(company_id)

        if workspace_result.get("status") == "success":
            app.logger.info(
                f"LightRAG workspace cleanup: instances_removed={workspace_result.get('instances_removed', 0)}/2, "
                f"collections_dropped={workspace_result.get('collections_dropped', 0)}"
            )
        else:
            app.logger.error(f"LightRAG workspace cleanup failed: {workspace_result.get('message', 'Unknown error')}")

        return jsonify({
            "status": "success",
            "message": f"Company data cleaned up for {company_name}",
            "company_id": company_id,
            "company_name": company_name,
            "cleanup_details": {
                "documents_total": doc_count,
                "lightrag_deleted": lightrag_result["successful"],
                "lightrag_failed": lightrag_result["failed"],
                "metadata_deleted": metadata_result.deleted_count,
                "users_deleted": users_result.deleted_count,
                "workspace_cleaned": workspace_result.get("status") == "success",
                "instances_removed": workspace_result.get("instances_removed", 0),
                "collections_dropped": workspace_result.get("collections_dropped", 0)
            }
        }), 200

    except Exception as e:
        app.logger.error(f"Error cleaning up company data: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ─── Metadata CRUD (scoped) ───────────────────────────────────────────────────
@app.route("/metadata", methods=["POST"])
@token_required
def add_metadata():
    data = request.get_json(force=True)

    # Non-admin can only add for their company, enforce/overwrite company_id
    if not is_admin():
        cid = claim_company_id()
        if not cid:
            return jsonify({"error": "No company assigned"}), 403
        data["company_id"] = cid

    company_id = data.get("company_id")
    if not company_id:
        return jsonify({"error": "Missing company_id"}), 400

    # Add timestamps
    if "created_at" not in data:
        data["created_at"] = datetime.datetime.utcnow().isoformat()
    data["updated_at"] = datetime.datetime.utcnow().isoformat()

    # Extract content early for enrichment
    content_data = data.get("content", {})
    content_text = content_data.get("description", "") or content_data.get("full_content", "") or str(content_data)
    if content_text:
        data["text_length"] = len(content_text)

    # Initialize RAG sync status
    data["rag_sync_status"] = "waiting"

    # STEP 1: Insert into MongoDB first (for Admin UI visibility)
    result = metadata_col.insert_one(data)
    app.logger.info(f"Inserted metadata into MongoDB with ID: {result.inserted_id}")

    # STEP 2: Extract content and enqueue for background RAG insertion
    if content_text:
        # Prepare metadata for LightRAG
        metadata = {
            "source": data.get("source", "manual_upload"),
            "type": data.get("type", "unknown"),
            "file_id": str(result.inserted_id),  # Reference to MongoDB document
            "updated_at": data["updated_at"]
        }

        # Enqueue RAG insertion task (non-blocking)
        mongodb_id = str(result.inserted_id)
        enqueue_rag_insertion(
            company_id=company_id,
            doc_id=mongodb_id,
            content=content_text,
            metadata=metadata
        )
        app.logger.info(f"Enqueued RAG insertion for metadata {mongodb_id}")

    # Return immediately without waiting for RAG insertion
    return jsonify({"_id": str(result.inserted_id)}), 201

@app.route("/metadata", methods=["GET"])
@token_required
def get_metadata():
    q = request.args.to_dict()
    if not is_admin():
        cid = claim_company_id()
        if not cid:
            return jsonify({"error": "No company assigned"}), 403
        q["company_id"] = cid
    return json_cursor(metadata_col.find(q)), 200

@app.route("/metadata/<id>", methods=["GET", "PUT", "DELETE"])
@token_required
def handle_metadata(id):
    _id = oid(id)
    if not _id:
        return jsonify({"error": "Invalid metadata ID"}), 400

    # Fetch first to enforce scope
    doc = metadata_col.find_one({"_id": _id})
    if not doc:
        return jsonify({"error": "Metadata not found"}), 404

    if not is_admin():
        cid = claim_company_id()
        if not cid or doc.get("company_id") != cid:
            return jsonify({"error": "Forbidden"}), 403

    if request.method == "GET":
        return dumps(doc), 200

    if request.method == "PUT":
        update_data = request.get_json(force=True)

        # Update timestamp
        update_data["updated_at"] = datetime.datetime.utcnow().isoformat()

        # Set RAG sync status to waiting for background processing
        update_data["rag_sync_status"] = "waiting"

        # Perform MongoDB update first
        result = metadata_col.update_one({"_id": _id}, {"$set": update_data})

        if result.modified_count or result.matched_count:
            # Get company_id for LightRAG update
            company_id = doc.get("company_id") or update_data.get("company_id")

            # Extract content for LightRAG update
            content_data = update_data.get("content", {})
            content_text = content_data.get("description", "") or content_data.get("full_content", "") or str(content_data)

            if content_text and company_id:
                # Prepare metadata for LightRAG
                metadata = {
                    "source": update_data.get("source", doc.get("source", "manual_upload")),
                    "type": update_data.get("type", doc.get("type", "unknown")),
                    "file_id": str(_id),
                    "updated_at": update_data["updated_at"]
                }

                # Use MongoDB _id as the document ID
                doc_id = str(_id)

                # Enqueue RAG update task (non-blocking, uses delete + reinsert)
                enqueue_rag_update(
                    company_id=company_id,
                    doc_id=doc_id,
                    content=content_text,
                    metadata=metadata
                )
                app.logger.info(f"Enqueued RAG update for metadata {_id}")

            return jsonify({"message": "Metadata updated"}), 200
        return jsonify({"error": "No changes made"}), 304

    if request.method == "DELETE":
        if not is_admin():
            # allow delete within own company
            pass

        # Get company_id and metadata before deleting from MongoDB
        company_id = doc.get("company_id")

        # Build file_path from metadata for LightRAG routing
        source = doc.get('source', 'unknown')
        doc_type = doc.get('type', 'document')
        file_id = str(_id)
        file_path = f"{source}/{doc_type}/{file_id}"

        # Delete from MongoDB
        result = metadata_col.delete_one({"_id": _id})

        if result.deleted_count:
            # Delete from LightRAG knowledge graph (best effort)
            if company_id:
                try:
                    # Use MongoDB _id as the document ID
                    doc_id = str(_id)
                    success = delete_company_document(
                        company_id=company_id,
                        doc_id=doc_id,
                        file_path=file_path  # Pass file_path for proper routing
                    )
                    if success:
                        app.logger.info(f"Deleted document {_id} from LightRAG knowledge graph")
                    else:
                        app.logger.warning(f"Failed to delete document {_id} from LightRAG")
                except Exception as e:
                    app.logger.error(f"Error deleting from LightRAG: {e}")

            return jsonify({"message": "Metadata deleted"}), 200
        return jsonify({"error": "Metadata not found"}), 404

@app.route("/metadata/company/<company_id>", methods=["GET"])
@token_required
def get_metadata_by_company(company_id):
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403
    return json_cursor(metadata_col.find({"company_id": company_id})), 200

@app.route("/metadata/company/<company_id>/rag-status", methods=["GET"])
@token_required
def get_rag_status_by_company(company_id):
    """
    Get RAG sync status for all metadata/files of a company
    Returns a lightweight list of {_id, rag_sync_status} for frontend polling
    """
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    # Only fetch _id and rag_sync_status fields for efficiency
    cursor = metadata_col.find(
        {"company_id": company_id},
        {"_id": 1, "rag_sync_status": 1}
    )

    results = []
    for doc in cursor:
        results.append({
            "_id": str(doc["_id"]),
            "rag_sync_status": doc.get("rag_sync_status", "unknown")
        })

    return jsonify(results), 200

# ─── Memory Management (AI Generated Memories) ──────────────────────────────
@app.route("/memories/company/<company_id>", methods=["GET"])
@token_required
def get_memories_by_company(company_id):
    """Get all AI-generated memories for a specific company"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    memories = metadata_col.find({
        "company_id": company_id,
        "type": "ai_generated_memory"
    }).sort("created_at", -1)

    return json_cursor(memories), 200

@app.route("/memories/<memory_id>", methods=["DELETE"])
@token_required
def delete_memory(memory_id):
    """Delete a specific AI-generated memory"""
    _id = oid(memory_id)
    if not _id:
        return jsonify({"error": "Invalid memory ID"}), 400

    # Fetch memory to check permissions
    memory = metadata_col.find_one({"_id": _id, "type": "ai_generated_memory"})
    if not memory:
        return jsonify({"error": "Memory not found"}), 404

    if not is_admin():
        cid = claim_company_id()
        if not cid or memory.get("company_id") != cid:
            return jsonify({"error": "Forbidden"}), 403

    # Get company_id before deleting from MongoDB
    company_id = memory.get("company_id")

    # Delete from MongoDB
    result = metadata_col.delete_one({"_id": _id})

    if result.deleted_count:
        # Delete from LightRAG knowledge graph (best effort)
        if company_id:
            try:
                # Use MongoDB _id as the document ID
                doc_id = str(_id)
                success = delete_company_document(
                    company_id=company_id,
                    doc_id=doc_id
                )
                if success:
                    app.logger.info(f"Deleted memory {_id} from LightRAG knowledge graph")
                else:
                    app.logger.warning(f"Failed to delete memory {_id} from LightRAG")
            except Exception as e:
                app.logger.error(f"Error deleting memory from LightRAG: {e}")

        return jsonify({"message": "Memory deleted"}), 200
    return jsonify({"error": "Memory not found"}), 404

@app.route("/memories/stats/<company_id>", methods=["GET"])
@token_required
def get_memory_stats(company_id):
    """Get statistics about AI-generated memories for a company"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    # Count total memories
    total_memories = metadata_col.count_documents({
        "company_id": company_id,
        "type": "ai_generated_memory"
    })

    # Get recent memories (last 30 days)
    from datetime import datetime, timedelta
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    recent_memories = metadata_col.count_documents({
        "company_id": company_id,
        "type": "ai_generated_memory",
        "created_at": {"$gte": thirty_days_ago}
    })

    # Get memory generation sources
    pipeline = [
        {"$match": {"company_id": company_id, "type": "ai_generated_memory"}},
        {"$group": {
            "_id": "$content.generated_from_user",
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}}
    ]

    user_stats = list(metadata_col.aggregate(pipeline))

    return jsonify({
        "total_memories": total_memories,
        "recent_memories": recent_memories,
        "memories_by_user": user_stats
    }), 200

# ─── Users CRUD (scoped) ──────────────────────────────────────────────────────
@app.route("/users", methods=["POST"])
@token_required
def add_user():
    if not is_admin():
        return jsonify({"error": "Admin only"}), 403

    data = request.get_json(force=True)
    send_welcome_message = data.pop("send_welcome_message", False)

    # Add welcome message timestamp field (null if not sent)
    data["whatsapp_welcome_sent_at"] = None

    result = users_col.insert_one(data)
    user_id = str(result.inserted_id)

    # Send welcome message if requested
    if send_welcome_message and data.get("phone_number") and data.get("first_name"):
        try:
            whatsapp_url = f"{WHATSAPP_SERVICE_URL}/send_template"
            params = {
                "phone_number": data["phone_number"],
                "template_name": "welcome",
                "language_code": "en",
                "userName": data["first_name"]
            }

            response = requests.get(whatsapp_url, params=params, timeout=10)

            if response.status_code == 200:
                # Update the user document with the timestamp
                from datetime import datetime
                users_col.update_one(
                    {"_id": result.inserted_id},
                    {"$set": {"whatsapp_welcome_sent_at": datetime.utcnow()}}
                )
                logging.info(f"Welcome WhatsApp message sent to user {user_id}")
            else:
                logging.warning(f"Failed to send welcome WhatsApp message to user {user_id}: {response.text}")
        except Exception as e:
            logging.error(f"Error sending welcome WhatsApp message to user {user_id}: {e}")

    return jsonify({"message": "User added", "id": user_id}), 201

@app.route("/users", methods=["GET"])
@token_required
def get_users():
    if is_admin():
        return json_cursor(users_col.find(request.args.to_dict())), 200
    # Non-admin: only themselves
    uoid = claim_user_oid()
    if not uoid:
        return jsonify({"error": "Invalid user in token"}), 400
    user = users_col.find_one({"_id": uoid})
    return (dumps([user]) if user else dumps([]), 200)

@app.route("/users/<id>", methods=["GET", "PUT", "DELETE"])
@token_required
def handle_user(id):
    _id = oid(id)
    if not _id:
        return jsonify({"error": "Invalid user ID"}), 400

    if request.method == "GET":
        if not is_admin():
            if claim_user_oid() != _id:
                return jsonify({"error": "Forbidden"}), 403
        user = users_col.find_one({"_id": _id})
        return (dumps(user), 200) if user else (jsonify({"error": "User not found"}), 404)

    if request.method == "PUT":
        if not is_admin():
            if claim_user_oid() != _id:
                return jsonify({"error": "Forbidden"}), 403
            # prevent non-admin from changing company_id or admin flags
            data = request.get_json(force=True)
            data.pop("company_id", None)
            data.pop("role", None)
        else:
            data = request.get_json(force=True)
        result = users_col.update_one({"_id": _id}, {"$set": data})
        if result.matched_count:
            return jsonify({"message": "User updated"}), 200
        return jsonify({"error": "User not found"}), 404

    if request.method == "DELETE":
        if not is_admin():
            if claim_user_oid() != _id:
                return jsonify({"error": "Forbidden"}), 403
        result = users_col.delete_one({"_id": _id})
        if result.deleted_count:
            return jsonify({"message": "User deleted"}), 200
        return jsonify({"error": "User not found"}), 404

@app.route("/users/company/<company_id>", methods=["GET"])
@token_required
def get_users_by_company(company_id):
    if is_admin():
        return json_cursor(users_col.find({"company_id": company_id})), 200
    # Non-admin: only their own user doc, regardless of path param
    if claim_company_id() != company_id:
        return jsonify({"error": "Forbidden"}), 403
    uoid = claim_user_oid()
    if not uoid:
        return jsonify({"error": "Invalid user in token"}), 400
    user = users_col.find_one({"_id": uoid})
    return (dumps([user]) if user else dumps([]), 200)

# ─── Settings Singleton (admin-only) ──────────────────────────────────────────
@app.route("/settings", methods=["GET", "PUT"])
@token_required
@require_admin
def handle_settings():
    """
    GET  → return the existing settings document or empty object
    PUT  → create/update the single settings document
    """
    if request.method == "GET":
        doc = settings_col.find_one()
        return (dumps(doc), 200) if doc else (jsonify({}), 200)

    if request.method == "PUT":
        new_data = request.get_json(force=True)
        result = settings_col.replace_one({}, new_data, upsert=True)
        if result.matched_count:
            return jsonify({"message": "Settings updated"}), 200
        return jsonify({"message": "Settings created"}), 201

# ─── Token Usage Statistics (admin-only) ──────────────────────────────────────
@app.route("/admin/token-usage", methods=["GET"])
@token_required
@require_admin
def get_token_usage():
    """
    Get token usage statistics for a given time range with optional filtering.

    Query params:
        start_time (ISO timestamp): Start of time range
        end_time (ISO timestamp): End of time range
        user_id (optional): Filter by specific user ID
        company_id (optional): Filter by specific company ID
        company_env (optional): Filter by company environment (course, development, production)

    Returns:
        Object with:
        - data: Array of token usage documents
        - users: List of unique users in the time range
        - companies: List of unique companies in the time range
        - classifications: Classification statistics from log_entries
    """
    try:
        start_time_str = request.args.get('start_time')
        end_time_str = request.args.get('end_time')
        filter_user_id = request.args.get('user_id')
        filter_company_id = request.args.get('company_id')
        filter_company_env = request.args.get('company_env')

        if not start_time_str or not end_time_str:
            return jsonify({"error": "start_time and end_time query parameters are required"}), 400

        # Parse ISO timestamps
        from datetime import datetime
        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))

        # Query token_usage collection
        token_usage_col = mongo.db.token_usage
        log_entries_col = mongo.db.log_entries

        # Build query with optional filters
        query = {
            "timestamp": {
                "$gte": start_time,
                "$lte": end_time
            }
        }

        if filter_user_id:
            query["user_id"] = filter_user_id

        if filter_company_id:
            query["company_id"] = filter_company_id

        if filter_company_env:
            env_clause = {"company_env": filter_company_env}
            # Older token_usage records may lack company_env; treat missing as "development" to keep filters usable.
            if filter_company_env == "development":
                env_clause = {"$or": [{"company_env": filter_company_env}, {"company_env": {"$exists": False}}]}
            query.setdefault("$and", []).append(env_clause)

        # Get all matching documents, sorted by timestamp
        usage_docs = list(token_usage_col.find(query).sort("timestamp", 1))

        # Build query for log_entries - timestamp can be string or datetime
        log_query = {}
        if filter_user_id:
            log_query["metrics.user_id"] = filter_user_id
        if filter_company_id:
            log_query["metrics.company_id"] = filter_company_id
        if filter_company_env:
            env_clause = {"metrics.company_env": filter_company_env}
            if filter_company_env == "development":
                env_clause = {"$or": [{"metrics.company_env": filter_company_env}, {"metrics.company_env": {"$exists": False}}]}
            log_query.setdefault("$and", []).append(env_clause)

        # Query log_entries with timestamp as string (ISO format)
        log_query["timestamp"] = {
            "$gte": start_time.isoformat(),
            "$lte": end_time.isoformat()
        }

        log_entries = list(log_entries_col.find(log_query).sort("timestamp", 1))

        # Extract unique users and companies from both collections
        unique_users = set()
        unique_companies = set()

        for doc in usage_docs:
            if doc.get("user_id"):
                unique_users.add(doc["user_id"])
            if doc.get("company_id"):
                unique_companies.add(doc["company_id"])

        for log in log_entries:
            metrics = log.get("metrics", {})
            if metrics.get("user_id"):
                unique_users.add(metrics["user_id"])
            if metrics.get("company_id"):
                unique_companies.add(metrics["company_id"])

        # Get user and company details
        users_list = []
        if unique_users:
            users = users_col.find({"phone_number": {"$in": list(unique_users)}})
            for user in users:
                users_list.append({
                    "id": user.get("phone_number"),
                    "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user.get("phone_number"),
                    "company_id": user.get("company_id")
                })

        companies_list = []
        if unique_companies:
            companies = companies_col.find({"_id": {"$in": [oid(cid) for cid in unique_companies if oid(cid)]}})
            for company in companies:
                company_id_str = str(company["_id"])
                companies_list.append({
                    "id": company_id_str,
                    "name": company_id_str,
                    "environment": company.get("environment", "development")
                })

        # Format response - extract only the fields we need
        result = []
        for doc in usage_docs:
            item = {
                "timestamp": doc.get("timestamp").isoformat() if doc.get("timestamp") else None,
                "model": doc.get("model"),
                "provider": doc.get("provider"),
                "success": doc.get("success", False),
                "call_type": doc.get("call_type", "other"),
                "user_id": doc.get("user_id"),
                "company_id": doc.get("company_id"),
                "company_env": doc.get("company_env", "development"),
            }

            # Add usage data if successful
            if doc.get("success") and doc.get("usage"):
                usage = doc["usage"]
                item["prompt_tokens"] = usage.get("prompt_tokens", 0)
                item["completion_tokens"] = usage.get("completion_tokens", 0)
                item["total_tokens"] = usage.get("total_tokens", 0)
                item["cached_tokens"] = usage.get("cached_tokens", 0)

            # Add error if failed
            if not doc.get("success") and doc.get("error"):
                item["error"] = doc.get("error")

            result.append(item)

        # Add classification token usage from log_entries
        for log in log_entries:
            metrics = log.get("metrics", {})
            classification_usage = log.get("classification_token_usage", {})

            # Parse timestamp - handle both string and datetime
            timestamp = log.get("timestamp")
            if isinstance(timestamp, str):
                try:
                    timestamp_iso = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).isoformat()
                except:
                    timestamp_iso = timestamp
            else:
                timestamp_iso = timestamp.isoformat() if timestamp else None

            item = {
                "timestamp": timestamp_iso,
                "model": "classification",
                "provider": "classification",
                "success": True,
                "call_type": "classification",
                "user_id": metrics.get("user_id"),
                "company_id": metrics.get("company_id"),
                "company_env": metrics.get("company_env", "development"),
                "prompt_tokens": classification_usage.get("prompt_tokens", 0),
                "completion_tokens": classification_usage.get("completion_tokens", 0),
                "total_tokens": classification_usage.get("total_tokens", 0),
                "cached_tokens": classification_usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
            }

            result.append(item)

        # Extract classification statistics
        classifications = {
            "prompt_type": {},
            "response_type": {},
            "tone": {},
            "source": {}
        }

        for log in log_entries:
            log_classifications = log.get("classifications", {})

            prompt_type = log_classifications.get("prompt_type")
            if prompt_type:
                classifications["prompt_type"][prompt_type] = classifications["prompt_type"].get(prompt_type, 0) + 1

            response_type = log_classifications.get("response_type")
            if response_type:
                classifications["response_type"][response_type] = classifications["response_type"].get(response_type, 0) + 1

            tone = log_classifications.get("tone")
            if tone:
                classifications["tone"][tone] = classifications["tone"].get(tone, 0) + 1

            # Track source (whatsapp vs web)
            source = log.get("source", "web")
            if source:
                classifications["source"][source] = classifications["source"].get(source, 0) + 1

        # Sort result by timestamp
        result.sort(key=lambda x: x["timestamp"] if x["timestamp"] else "")

        # Calculate actual date range from data (useful for dynamic "all" time range)
        actual_start = None
        actual_end = None
        if result:
            timestamps = [r["timestamp"] for r in result if r.get("timestamp")]
            if timestamps:
                actual_start = min(timestamps)
                actual_end = max(timestamps)

        return jsonify({
            "data": result,
            "users": sorted(users_list, key=lambda x: x["name"]),
            "companies": sorted(companies_list, key=lambda x: x["name"]),
            "classifications": classifications,
            "date_range": {
                "requested_start": start_time.isoformat(),
                "requested_end": end_time.isoformat(),
                "actual_start": actual_start,
                "actual_end": actual_end
            }
        }), 200

    except ValueError as e:
        return jsonify({"error": f"Invalid timestamp format: {str(e)}"}), 400
    except Exception as e:
        app.logger.error(f"Error fetching token usage: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/admin/report-scripts", methods=["GET"])
@token_required
@require_admin
def get_report_scripts():
    try:
        return jsonify({"scripts": list_report_scripts()}), 200
    except Exception as e:
        app.logger.error(f"Error listing report scripts: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/admin/report-scripts/<script_id>/run", methods=["POST"])
@token_required
@require_admin
def run_admin_report_script(script_id):
    try:
        params = request.get_json(silent=True) or {}
        report = run_report_script(
            script_id,
            context={
                "mongo": mongo,
                "azure_client": azure_client,
                "logger": app.logger,
            },
            params=params,
        )

        return send_file(
            BytesIO(report["content"]),
            mimetype=report["mimetype"],
            as_attachment=True,
            download_name=report["filename"],
        )
    except KeyError:
        return jsonify({"error": "Unknown report script"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Error running report script {script_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/admin/turn-classifications", methods=["GET"])
@token_required
@require_admin
def get_turn_classifications():
    """
    Per-turn classification view: prompt/response/tone + referenced RAG document classes (if available).
    """
    try:
        start_time_str = request.args.get("start_time")
        end_time_str = request.args.get("end_time")
        filter_user_id = request.args.get("user_id")
        filter_company_id = request.args.get("company_id")

        if not start_time_str or not end_time_str:
            return jsonify({"error": "start_time and end_time query parameters are required"}), 400

        from datetime import datetime
        start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))

        log_query = {
            "timestamp": {
                "$gte": start_time.isoformat(),
                "$lte": end_time.isoformat()
            }
        }
        if filter_user_id:
            log_query["metrics.user_id"] = filter_user_id
        if filter_company_id:
            log_query["metrics.company_id"] = filter_company_id

        log_entries = list(mongo.db.log_entries.find(log_query))

        # Collect referenced doc ids
        doc_ids = []
        for log in log_entries:
            for ref in log.get("rag_references", []) or []:
                src = ref.get("source")
                if not src:
                    continue
                try:
                    doc_ids.append(ObjectId(src))
                except Exception:
                    continue

        doc_class_map = {}
        if doc_ids:
            for doc in metadata_col.find({"_id": {"$in": doc_ids}}, {"rag_document_class": 1}):
                doc_class_map[str(doc["_id"])] = doc.get("rag_document_class") or "unknown"

        result = []
        for log in log_entries:
            refs = log.get("rag_references", []) or []
            ref_classes = []
            for ref in refs:
                src = ref.get("source")
                cls = doc_class_map.get(src, "unknown")
                ref_classes.append({"document_id": src, "class": cls})

            classifications = log.get("classifications", {}) or {}
            metrics = log.get("metrics", {}) or {}
            result.append({
                "timestamp": log.get("timestamp"),
                "user_id": metrics.get("user_id"),
                "company_id": metrics.get("company_id"),
                "prompt_type": classifications.get("prompt_type"),
                "response_type": classifications.get("response_type"),
                "tone": classifications.get("tone"),
                "rag_classes": ref_classes,
            })

        return jsonify({
            "data": result,
            "date_range": {
                "requested_start": start_time.isoformat(),
                "requested_end": end_time.isoformat(),
            },
            "filters": {
                "user_id": filter_user_id,
                "company_id": filter_company_id,
            },
        }), 200

    except ValueError as e:
        return jsonify({"error": f"Invalid timestamp format: {str(e)}"}), 400
    except Exception as e:
        app.logger.error(f"Error fetching turn classifications: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/admin/log-entries", methods=["GET"])
@token_required
@require_admin
def export_log_entries():
    """
    Export raw log_entries for a given time range with optional filtering.

    Query params:
        start_time (ISO timestamp): Start of time range
        end_time (ISO timestamp): End of time range
        user_id (optional): Filter by user id
        company_id (optional): Filter by company id
        company_env (optional): Filter by company environment
    """
    try:
        start_time_str = request.args.get('start_time')
        end_time_str = request.args.get('end_time')
        filter_user_id = request.args.get('user_id')
        filter_company_id = request.args.get('company_id')
        filter_company_env = request.args.get('company_env')

        if not start_time_str or not end_time_str:
            return jsonify({"error": "start_time and end_time query parameters are required"}), 400

        from datetime import datetime
        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))

        log_entries_col = mongo.db.log_entries

        # Build query for log_entries - timestamp is stored as ISO string
        log_query = {
            "timestamp": {
                "$gte": start_time.isoformat(),
                "$lte": end_time.isoformat(),
            }
        }

        if filter_user_id:
            log_query["metrics.user_id"] = filter_user_id
        if filter_company_id:
            log_query["metrics.company_id"] = filter_company_id
        if filter_company_env:
            env_clause = {"metrics.company_env": filter_company_env}
            if filter_company_env == "development":
                env_clause = {"$or": [{"metrics.company_env": filter_company_env}, {"metrics.company_env": {"$exists": False}}]}
            # Combine with existing conditions
            log_query.setdefault("$and", []).append(env_clause)

        log_entries = list(log_entries_col.find(log_query).sort("timestamp", 1))

        def serialize_log(log: dict):
            serialized = {}
            for key, value in log.items():
                # Remove sensitive/chat content fields before export
                if key in {"question", "response", "context_used", "system_prompt_used"}:
                    continue
                if key == "_id":
                    serialized["_id"] = str(value)
                elif key == "timestamp":
                    if isinstance(value, datetime):
                        serialized["timestamp"] = value.isoformat()
                    else:
                        serialized["timestamp"] = value
                else:
                    serialized[key] = value
            return serialized

        serialized_logs = [serialize_log(log) for log in log_entries]

        return jsonify({
            "logs": serialized_logs,
            "count": len(serialized_logs),
            "date_range": {
                "requested_start": start_time.isoformat(),
                "requested_end": end_time.isoformat(),
            },
            "filters": {
                "user_id": filter_user_id,
                "company_id": filter_company_id,
                "company_env": filter_company_env,
            },
        }), 200
    except ValueError as e:
        return jsonify({"error": f"Invalid timestamp format: {str(e)}"}), 400
    except Exception as e:
        app.logger.error(f"Error exporting log entries: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/admin/metadata-stats", methods=["GET"])
@token_required
@require_admin
def get_metadata_stats():
    """
    Return counts of metadata documents grouped by source/type for a time window.
    Query params:
        - start_time (ISO, required)
        - end_time   (ISO, required)
        - company_id (optional)
    """
    try:
        start_time_str = request.args.get('start_time')
        end_time_str = request.args.get('end_time')
        filter_company_id = request.args.get('company_id')

        if not start_time_str or not end_time_str:
            return jsonify({"error": "start_time and end_time query parameters are required"}), 400

        from datetime import datetime
        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))

        # Most metadata docs store created_at as ISO string; use string comparison for the range
        time_filter = {
            "created_at": {
                "$gte": start_time.isoformat(),
                "$lte": end_time.isoformat(),
            }
        }

        if filter_company_id:
            time_filter["company_id"] = filter_company_id

        pipeline = [
            {"$match": time_filter},
            {"$group": {"_id": {"source": "$source", "type": "$type"}, "count": {"$sum": 1}}},
        ]

        agg_results = list(metadata_col.aggregate(pipeline))

        by_source = {}
        by_type = {}
        total = 0

        for item in agg_results:
            total += item.get("count", 0)
            source_key = item["_id"].get("source") or "unknown"
            type_key = item["_id"].get("type") or "unknown"

            by_source[source_key] = by_source.get(source_key, 0) + item.get("count", 0)
            by_type[type_key] = by_type.get(type_key, 0) + item.get("count", 0)

        return jsonify(
            {
                "total": total,
                "by_source": by_source,
                "by_type": by_type,
                "date_range": {
                    "requested_start": start_time.isoformat(),
                    "requested_end": end_time.isoformat(),
                },
                "filters": {
                    "company_id": filter_company_id,
                },
            }
        ), 200

    except ValueError as e:
        return jsonify({"error": f"Invalid timestamp format: {str(e)}"}), 400
    except Exception as e:
        app.logger.error(f"Error fetching metadata stats: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/admin/metadata-class-mass", methods=["GET"])
@token_required
@require_admin
def get_metadata_class_mass():
    """
    Return total text_length per rag_document_class for a time window (textual mass).
    Query params:
        - start_time (ISO, required)
        - end_time   (ISO, required)
        - company_id (optional)
    """
    try:
        start_time_str = request.args.get('start_time')
        end_time_str = request.args.get('end_time')
        filter_company_id = request.args.get('company_id')

        if not start_time_str or not end_time_str:
            return jsonify({"error": "start_time and end_time query parameters are required"}), 400

        from datetime import datetime
        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))

        match: dict = {
            "created_at": {
                "$gte": start_time.isoformat(),
                "$lte": end_time.isoformat(),
            }
        }
        if filter_company_id:
            match["company_id"] = filter_company_id

        pipeline = [
            {"$match": match},
            {"$group": {
                "_id": {"class": "$rag_document_class"},
                "text_length": {"$sum": {"$ifNull": ["$text_length", 0]}},
                "count": {"$sum": 1}
            }},
        ]

        agg_results = list(metadata_col.aggregate(pipeline))
        by_class = {}
        total_length = 0
        total_count = 0

        for item in agg_results:
            cls = item["_id"].get("class") or "unclassified"
            length = item.get("text_length", 0)
            count = item.get("count", 0)
            total_length += length
            total_count += count
            by_class[cls] = {
                "text_length": length,
                "count": count,
            }

        return jsonify({
            "total_text_length": total_length,
            "total_count": total_count,
            "by_class": by_class,
            "date_range": {
                "requested_start": start_time.isoformat(),
                "requested_end": end_time.isoformat(),
            },
            "filters": {
                "company_id": filter_company_id,
            },
        }), 200

    except ValueError as e:
        return jsonify({"error": f"Invalid timestamp format: {str(e)}"}), 400
    except Exception as e:
        app.logger.error(f"Error fetching metadata class mass: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/admin/rag-class-usage", methods=["GET"])
@token_required
@require_admin
def get_rag_class_usage():
    """
    Return how many times RAG documents (by class) were referenced in chats.
    Counts references from log_entries.rag_references within a time range.

    Query params:
        - start_time (ISO, required)
        - end_time   (ISO, required)
        - company_id (optional): filter by metrics.company_id
    """
    try:
        start_time_str = request.args.get("start_time")
        end_time_str = request.args.get("end_time")
        filter_company_id = request.args.get("company_id")

        if not start_time_str or not end_time_str:
            return jsonify({"error": "start_time and end_time query parameters are required"}), 400

        from datetime import datetime

        start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))

        query = {
            "timestamp": {"$gte": start_time.isoformat(), "$lte": end_time.isoformat()},
        }
        if filter_company_id:
            query["metrics.company_id"] = filter_company_id

        logs = list(mongo.db.log_entries.find(query, {"rag_references": 1, "metrics": 1}))

        # Collect referenced metadata ids
        ref_ids = []
        for log in logs:
            refs = log.get("rag_references") or []
            for ref in refs:
                src = ref.get("source")
                if src:
                    try:
                        ref_ids.append(ObjectId(src))
                    except Exception:
                        continue

        metadata_map = {}
        if ref_ids:
            for doc in metadata_col.find({"_id": {"$in": ref_ids}}, {"rag_document_class": 1}):
                metadata_map[str(doc["_id"])] = doc.get("rag_document_class") or "unclassified"

        by_class = {}
        total_refs = 0
        unique_docs = set()

        for log in logs:
            refs = log.get("rag_references") or []
            for ref in refs:
                src = ref.get("source")
                if not src:
                    continue
                cls = metadata_map.get(src, "unclassified")
                by_class[cls] = by_class.get(cls, 0) + 1
                total_refs += 1
                unique_docs.add(src)

        return jsonify({
            "total_references": total_refs,
            "unique_documents": len(unique_docs),
            "by_class": by_class,
            "date_range": {
                "requested_start": start_time.isoformat(),
                "requested_end": end_time.isoformat(),
            },
            "filters": {
                "company_id": filter_company_id,
            },
        }), 200

    except ValueError as e:
        return jsonify({"error": f"Invalid timestamp format: {str(e)}"}), 400
    except Exception as e:
        app.logger.error(f"Error fetching RAG class usage: {e}")
        return jsonify({"error": "Internal server error"}), 500


# ─── Google Drive Integration ─────────────────────────────────────────────────
@app.route("/companies/<company_id>/google-drive/auth", methods=["POST"])
@token_required
def initiate_google_drive_auth(company_id):
    """Initiate Google Drive OAuth flow for a company"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [GOOGLE_REDIRECT_URI]
                }
            },
            scopes=SCOPES
        )
        flow.redirect_uri = GOOGLE_REDIRECT_URI

        state_nonce = secrets.token_urlsafe(16)
        state_value = f"{company_id}|drive|{state_nonce}"
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='false',  # Prevent automatic scope additions
            prompt='consent',  # Force consent screen to ensure refresh token and avoid scope conflicts
            code_challenge_method='S256',
            state=state_value  # Include service type + nonce in state
        )

        if not getattr(flow, "code_verifier", None):
            return jsonify({"error": "Failed to initialize OAuth PKCE verifier"}), 500
        store_google_oauth_pkce_state(state, company_id, "drive", flow.code_verifier)

        return jsonify({
            "authorization_url": authorization_url,
            "state": state
        }), 200

    except Exception as e:
        logging.error(f"Error initiating Google Drive auth: {e}")
        return jsonify({"error": "Failed to initiate authentication"}), 500

@app.route("/auth/google/callback", methods=["GET"])
def google_callback():
    """Handle Google OAuth callback for both Drive and Gmail"""
    try:
        code = request.args.get('code')
        state = request.args.get('state')
        error = request.args.get('error')

        if error:
            return jsonify({"error": f"OAuth error: {error}"}), 400

        if not code or not state:
            return jsonify({"error": "Missing authorization code or state"}), 400

        # Parse state to determine service type and company ID
        state_parts = state.split("|")
        if len(state_parts) >= 2:
            company_id, service_type = state_parts[0], state_parts[1]
        else:
            # Backward compatibility - assume it's Google Drive if no service type
            company_id = state
            service_type = "drive"

        # Determine scopes based on service type
        if service_type == "gmail":
            scopes = GMAIL_EMAIL_SCOPES
            service_name = "Gmail"
        else:  # drive
            scopes = SCOPES
            service_name = "Google Drive"

        # Exchange code for credentials
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [GOOGLE_REDIRECT_URI]
                }
            },
            scopes=scopes
        )
        flow.redirect_uri = GOOGLE_REDIRECT_URI
        pkce_state = pop_google_oauth_pkce_state(state)
        if pkce_state and pkce_state.get("code_verifier"):
            flow.code_verifier = pkce_state.get("code_verifier")

        try:
            flow.fetch_token(code=code)
        except Exception as token_error:
            # Handle scope change errors specifically
            token_error_text = str(token_error)
            token_error_text_lower = token_error_text.lower()

            if "scope has changed" in token_error_text_lower:
                return f"""
                <html>
                <head><title>Re-authorization Required</title></head>
                <body>
                    <h2>Re-authorization Required</h2>
                    <p>The application permissions have been updated. Please disconnect and reconnect your Google Drive integration.</p>
                    <p>Steps to fix:</p>
                    <ol>
                        <li>Go back to the application</li>
                        <li>Disconnect Google Drive</li>
                        <li>Connect Google Drive again</li>
                    </ol>
                    <script>
                    setTimeout(function() {{ window.close(); }}, 10000);
                </script>
                </body>
                </html>
                """
            elif "invalid_grant" in token_error_text_lower:
                return f"""
                <html>
                <head><title>Google OAuth Error</title></head>
                <body>
                    <h2>Google OAuth Error</h2>
                    <p>Authentication failed with <code>invalid_grant</code>.</p>
                    <p>Common causes:</p>
                    <ol>
                        <li>The OAuth client redirect URI does not exactly match the callback URL.</li>
                        <li>The authorization code expired before exchange.</li>
                        <li>The previous Google consent/token was revoked.</li>
                    </ol>
                    <p>Please verify <code>GOOGLE_REDIRECT_URI</code> and reconnect Google Drive.</p>
                    <script>
                        setTimeout(function() {{ window.close(); }}, 12000);
                    </script>
                </body>
                </html>
                """
            elif "missing code verifier" in token_error_text_lower:
                return f"""
                <html>
                <head><title>Google OAuth Error</title></head>
                <body>
                    <h2>Google OAuth Error</h2>
                    <p>Authentication failed because the PKCE code verifier was not found.</p>
                    <p>Please close this window and start Google connection again from the app.</p>
                    <script>
                        setTimeout(function() {{ window.close(); }}, 10000);
                    </script>
                </body>
                </html>
                """
            else:
                raise token_error

        credentials = flow.credentials

        # Validate that we have all required credential fields
        if not credentials.refresh_token:
            return f"""
            <html>
            <head><title>Authentication Error</title></head>
            <body>
                <h2>Authentication Error</h2>
                <p>No refresh token received. This usually happens when you have already authorized this app.</p>
                <p>Please revoke access in your Google Account settings and try again.</p>
                <script>
                    setTimeout(function() {{ window.close(); }}, 5000);
                </script>
            </body>
            </html>
            """

        # Store credentials in company document
        creds_dict = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri or "https://oauth2.googleapis.com/token",
            "client_id": credentials.client_id or GOOGLE_CLIENT_ID,
            "client_secret": credentials.client_secret or GOOGLE_CLIENT_SECRET,
            "scopes": sorted(scopes)  # Always use sorted scopes for consistency
        }

        # Final validation that all required fields are present
        required_fields = ['token', 'refresh_token', 'token_uri', 'client_id', 'client_secret']
        missing_fields = [field for field in required_fields if not creds_dict.get(field)]

        if missing_fields:
            return f"""
            <html>
            <head><title>Authentication Error</title></head>
            <body>
                <h2>Authentication Error</h2>
                <p>OAuth completed but missing required fields: {', '.join(missing_fields)}. Please try again.</p>
                <script>
                    setTimeout(function() {{ window.close(); }}, 5000);
                </script>
            </body>
            </html>
            """

        _id = oid(company_id)
        if not _id:
            return f"""
            <html>
            <head><title>Authentication Error</title></head>
            <body>
                <h2>Authentication Error</h2>
                <p>Invalid company ID. Please try again.</p>
                <script>
                    setTimeout(function() {{ window.close(); }}, 5000);
                </script>
            </body>
            </html>
            """

        # Store credentials based on service type
        if service_type == "gmail":
            # Get user email address for Gmail using Gmail API
            email_address = ""
            try:
                gmail_service = build('gmail', 'v1', credentials=credentials)
                profile = gmail_service.users().getProfile(userId='me').execute()
                email_address = profile.get('emailAddress', '')
                app.logger.info(f"Retrieved Gmail email address: {email_address}")
            except Exception as e:
                app.logger.error(f"Failed to get Gmail email address: {e}")
                email_address = ""

            # Add email address to credentials
            creds_dict["email_address"] = email_address

            companies_col.update_one(
                {"_id": _id},
                {
                    "$set": {
                        "email_integration": {
                            "connected": True,
                            "provider": "gmail",
                            "email_address": email_address,
                            "connection_type": "oauth",
                            "credentials": creds_dict,
                            "connected_at": datetime.datetime.utcnow().isoformat(),
                            "last_sync": None,
                            "sync_status": "connected",
                            "settings": {
                                "sync_folders": ["INBOX"],
                                "sync_since_days": 30,
                                "max_emails_per_sync": 100,
                                "include_attachments": False,
                                "skip_large_emails": True,
                                "max_email_size_mb": 10
                            },
                            "stats": {
                                "total_emails_synced": 0,
                                "last_sync_count": 0,
                                "errors_count": 0
                            }
                        }
                    }
                }
            )
        else:  # service_type == "drive"
            # Get user email address for Google Drive using Google+ API (userinfo)
            email_address = ""
            try:
                # Use OAuth2 service to get user info
                oauth2_service = build('oauth2', 'v2', credentials=credentials)
                user_info = oauth2_service.userinfo().get().execute()
                email_address = user_info.get('email', '')
                app.logger.info(f"Retrieved Google Drive user email address: {email_address}")
            except Exception as e:
                app.logger.error(f"Failed to get Google Drive user email address: {e}")
                email_address = ""

            # Add email address to credentials
            creds_dict["email_address"] = email_address

            companies_col.update_one(
                {"_id": _id},
                {
                    "$set": {
                        "google_drive": {
                            "connected": True,
                            "email_address": email_address,
                            "credentials": creds_dict,
                            "connected_at": datetime.datetime.utcnow().isoformat(),
                            "last_sync": None,
                            "folder_count": 0,
                            "file_count": 0,
                            "monitored_folders": []
                        }
                    }
                }
            )

        # Return a simple HTML page that closes the popup
        return f"""
        <html>
        <head><title>{service_name} Connected</title></head>
        <body>
            <h2>{service_name} Connected Successfully!</h2>
            <p>You can close this window and return to the application.</p>
            <script>
                window.close();
            </script>
        </body>
        </html>
        """

    except Exception as e:
        logging.error(f"Error in Google callback: {e}")
        return f"""
        <html>
        <head><title>Authentication Error</title></head>
        <body>
            <h2>Authentication Error</h2>
            <p>Failed to complete authentication: {str(e)}</p>
            <script>
                setTimeout(function() {{ window.close(); }}, 5000);
            </script>
        </body>
        </html>
        """

@app.route("/companies/<company_id>/google-drive/sync", methods=["POST"])
@token_required
def sync_google_drive(company_id):
    """Sync Google Drive files for a company"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        company = companies_col.find_one({"_id": _id})
        if not company:
            return jsonify({"error": "Company not found"}), 404

        google_drive_config = company.get("google_drive")
        if not google_drive_config or not google_drive_config.get("connected"):
            return jsonify({"error": "Google Drive not connected"}), 400

        # Reconstruct credentials
        creds_dict = google_drive_config.get("credentials")
        if not creds_dict:
            return jsonify({"error": "No stored credentials"}), 400

        # Validate that all required fields are present and not None
        required_fields = ['token', 'refresh_token', 'token_uri', 'client_id', 'client_secret']
        missing_fields = []
        for field in required_fields:
            if not creds_dict.get(field):
                missing_fields.append(field)

        if missing_fields:
            return jsonify({
                "error": f"Missing credential fields: {missing_fields}. Please reconnect your Google Drive account.",
                "details": f"Required fields are missing: {', '.join(missing_fields)}",
                "requires_reauth": True
            }), 401

        credentials = Credentials(
            token=creds_dict.get("token"),
            refresh_token=creds_dict.get("refresh_token"),
            token_uri=creds_dict.get("token_uri"),
            client_id=creds_dict.get("client_id"),
            client_secret=creds_dict.get("client_secret"),
            scopes=creds_dict.get("scopes")
        )

        # Refresh credentials if needed
        if credentials.expired and credentials.refresh_token:
            success, error = refresh_google_credentials(credentials, company_id, _id)
            if not success:
                return jsonify({
                    "error": "Google Drive authentication expired. Please reconnect your Google Drive account.",
                    "details": error,
                    "requires_reauth": True
                }), 401

        # Build Drive service
        service = build('drive', 'v3', credentials=credentials)

        # Get or update email address if missing
        if not google_drive_config.get("email_address"):
            try:
                # Use OAuth2 service to get user info
                oauth2_service = build('oauth2', 'v2', credentials=credentials)
                user_info = oauth2_service.userinfo().get().execute()
                email_address = user_info.get('email', '')

                if email_address:
                    app.logger.info(f"Retrieved missing email address for company {company_id}: {email_address}")
                    companies_col.update_one(
                        {"_id": _id},
                        {"$set": {"google_drive.email_address": email_address}}
                    )
            except Exception as e:
                app.logger.warning(f"Failed to retrieve email address for company {company_id}: {e}")

        # Get monitored folders
        monitored_folders = google_drive_config.get("monitored_folders", [])

        synced_count = 0

        if not monitored_folders:
            # If no specific folders are monitored, don't sync anything
            # This prevents syncing all files when no folders are selected
            return jsonify({
                "error": "No folders selected for monitoring. Please select folders before syncing.",
                "requires_folder_selection": True
            }), 400
        else:
            # VALIDATION: Check total file count before starting sync
            total_file_count = 0
            for folder_id in monitored_folders:
                folder_results = service.files().list(
                    q=f"'{folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder'",
                    pageSize=1,  # We only need count, not the actual files
                    fields="files(id)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives"
                ).execute()
                total_file_count += len(folder_results.get('files', []))

                # For efficiency, we'll do a rough estimate by checking first page
                # If we already exceed threshold, stop counting
                if total_file_count > 100:
                    break

            # Get more accurate count if needed
            if total_file_count > 100:
                # Recalculate exact count
                exact_count = 0
                for folder_id in monitored_folders:
                    page_token = None
                    while True:
                        folder_results = service.files().list(
                            q=f"'{folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder'",
                            pageSize=100,
                            fields="nextPageToken, files(id)",
                            pageToken=page_token,
                            supportsAllDrives=True,
                            includeItemsFromAllDrives=True,
                            corpora="allDrives"
                        ).execute()
                        exact_count += len(folder_results.get('files', []))
                        page_token = folder_results.get('nextPageToken')
                        if not page_token:
                            break

                # If file count exceeds threshold, return error
                return jsonify({
                    "error": f"Too many files selected for sync. The selected folders contain {exact_count} files. Please reduce the number of selected folders (maximum 100 files recommended).",
                    "validation_error": "too_many_files",
                    "file_count": exact_count
                }), 400

            # Sync files from monitored folders only
            files = []
            for folder_id in monitored_folders:
                folder_results = service.files().list(
                    q=f"'{folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder'",
                    pageSize=50,
                    fields="nextPageToken, files(id, name, mimeType, modifiedTime, size, parents)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives"
                ).execute()
                files.extend(folder_results.get('files', []))

        # Process each file
        for file_info in files:
            try:
                file_id = file_info['id']
                file_name = file_info['name']
                mime_type = file_info['mimeType']
                modified_time = file_info['modifiedTime']

                # Check if we already have this file with the same modification time
                existing_metadata = metadata_col.find_one({
                    "company_id": company_id,
                    "type": "google_drive_file",
                    "google_drive.file_id": file_id,
                    "google_drive.modified_time": modified_time
                })

                if existing_metadata:
                    continue  # Skip if already up-to-date

                # Download and process the file
                content = ""
                supported_mime_types = [
                    # Plain text
                    'text/plain',
                    'text/csv',                     # CSV files
                    # PDF files
                    'application/pdf',
                    # Google Workspace files
                    'application/vnd.google-apps.document',      # Google Docs
                    'application/vnd.google-apps.spreadsheet',  # Google Sheets
                    'application/vnd.google-apps.presentation', # Google Slides
                    # Microsoft Office files
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',     # .docx
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',           # .xlsx
                    'application/vnd.openxmlformats-officedocument.presentationml.presentation',   # .pptx
                    # Legacy Microsoft Office files
                    'application/msword',           # .doc
                    'application/vnd.ms-excel',     # .xls
                    'application/vnd.ms-powerpoint' # .ppt
                ]

                if mime_type in supported_mime_types:
                    content = download_and_extract_content(service, file_id, mime_type)

                if content:
                    # STEP 1: Create/update metadata document in MongoDB
                    now = datetime.datetime.utcnow().isoformat()

                    # Check if we already have metadata for this file (by file_id)
                    existing_doc = metadata_col.find_one({
                        "company_id": company_id,
                        "type": "google_drive_file",
                        "google_drive.file_id": file_id
                    })

                    if existing_doc:
                        # Update existing document
                        mongodb_id = str(existing_doc["_id"])
                        metadata_col.update_one(
                            {"_id": existing_doc["_id"]},
                            {
                                "$set": {
                                    "content": {"full_content": content},
                                    "text_length": len(content),
                                    "google_drive": {
                                        "file_id": file_id,
                                        "file_name": file_name,
                                        "mime_type": mime_type,
                                        "modified_time": modified_time,
                                        "size": file_info.get('size'),
                                        "parent_folders": file_info.get('parents', [])
                                    },
                                    "updated_at": now,
                                    "rag_sync_status": "waiting"
                                }
                            }
                        )
                        app.logger.info(f"[RAG] Queuing Google Drive file update {file_name} for RAG insertion at {now}")
                    else:
                        # Create new metadata document
                        metadata_doc = {
                            "company_id": company_id,
                            "type": "google_drive_file",
                            "source": "google_drive",
                            "title": file_name,
                            "content": {"full_content": content},
                            "text_length": len(content),
                            "google_drive": {
                                "file_id": file_id,
                                "file_name": file_name,
                                "mime_type": mime_type,
                                "modified_time": modified_time,
                                "size": file_info.get('size'),
                                "parent_folders": file_info.get('parents', [])
                            },
                            "created_at": now,
                            "updated_at": now,
                            "rag_sync_status": "waiting"
                        }
                        app.logger.info(f"[RAG] Queuing Google Drive file {file_name} for RAG insertion at {now}")
                        result = metadata_col.insert_one(metadata_doc)
                        mongodb_id = str(result.inserted_id)

                    # STEP 2: Check content size before RAG insertion
                    if len(content) > MAX_RAG_CONTENT_LENGTH:
                        app.logger.warning(f"Google Drive file {file_name} too large ({len(content)} chars, max {MAX_RAG_CONTENT_LENGTH})")
                        metadata_col.update_one(
                            {"_id": ObjectId(mongodb_id)},
                            {"$set": {"rag_sync_status": "too_large"}}
                        )
                    else:
                        # Enqueue for background RAG insertion
                        enqueue_rag_insertion(
                            company_id=company_id,
                            doc_id=mongodb_id,
                            content=content,
                            metadata={
                                "source": "google_drive",
                                "file_id": mongodb_id,
                                "file_name": file_name,
                                "mime_type": mime_type,
                                "modified_time": modified_time,
                                "size": file_info.get('size'),
                                "parent_folders": file_info.get('parents', []),
                                "updated_at": now
                            }
                        )
                    synced_count += 1

            except Exception as e:
                logging.error(f"Error processing file {file_info.get('name', 'unknown')}: {e}")
                continue

        # Calculate total count of Google Drive files for this company
        total_file_count = metadata_col.count_documents({
            "company_id": company_id,
            "type": "google_drive_file"
        })

        # Update sync status
        companies_col.update_one(
            {"_id": _id},
            {
                "$set": {
                    "google_drive.last_sync": datetime.datetime.utcnow().isoformat(),
                    "google_drive.file_count": total_file_count,
                    "google_drive.folder_count": len(monitored_folders)
                }
            }
        )

        return jsonify({
            "message": f"Sync completed. {synced_count} files processed, {total_file_count} total files available.",
            "processed_files": synced_count,
            "total_files": total_file_count
        }), 200

    except HttpError as e:
        logging.error(f"Google Drive API error: {e}")
        return jsonify({"error": "Google Drive API error"}), 500
    except Exception as e:
        logging.error(f"Error syncing Google Drive: {e}")
        return jsonify({"error": "Failed to sync Google Drive"}), 500

def download_and_extract_content(service, file_id, mime_type):
    """Download and extract text content from Google Drive file"""
    try:
        # Handle Google Workspace files by exporting to text/plain
        if mime_type == 'application/vnd.google-apps.document':
            # Export Google Docs as plain text
            request = service.files().export_media(fileId=file_id, mimeType='text/plain')
            file_content = io.BytesIO()
            downloader = MediaIoBaseDownload(file_content, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            return file_content.getvalue().decode('utf-8')

        elif mime_type == 'application/vnd.google-apps.spreadsheet':
            # Export Google Sheets as CSV and extract text
            request = service.files().export_media(fileId=file_id, mimeType='text/csv')
            file_content = io.BytesIO()
            downloader = MediaIoBaseDownload(file_content, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            return file_content.getvalue().decode('utf-8')

        elif mime_type == 'application/vnd.google-apps.presentation':
            # Export Google Slides as plain text
            request = service.files().export_media(fileId=file_id, mimeType='text/plain')
            file_content = io.BytesIO()
            downloader = MediaIoBaseDownload(file_content, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            return file_content.getvalue().decode('utf-8')

        # Handle plain text files
        elif mime_type == 'text/plain':
            request = service.files().get_media(fileId=file_id)
            file_content = io.BytesIO()
            downloader = MediaIoBaseDownload(file_content, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            return file_content.getvalue().decode('utf-8')

        # Handle CSV files
        elif mime_type == 'text/csv':
            request = service.files().get_media(fileId=file_id)
            file_content = io.BytesIO()
            downloader = MediaIoBaseDownload(file_content, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            return file_content.getvalue().decode('utf-8')

        # Handle binary files that need special processing
        else:
            # Download the binary file first
            request = service.files().get_media(fileId=file_id)
            file_content = io.BytesIO()
            downloader = MediaIoBaseDownload(file_content, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()

            file_content.seek(0)  # Reset to beginning

            # Extract text based on mime type
            if mime_type == 'application/pdf':
                return extract_pdf_text(file_content)
            elif mime_type in ['application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
                return extract_docx_text(file_content)
            elif mime_type in ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']:
                return extract_xlsx_text(file_content)
            elif mime_type in ['application/vnd.openxmlformats-officedocument.presentationml.presentation']:
                return extract_pptx_text(file_content)
            elif mime_type == 'application/msword':
                # Legacy .doc files - limited support
                logging.warning(f"Legacy .doc file detected. Limited text extraction available.")
                return ""
            elif mime_type in ['application/vnd.ms-excel', 'application/vnd.ms-powerpoint']:
                # Legacy Office files - limited support
                logging.warning(f"Legacy Office file detected. Consider converting to modern format.")
                return ""
            else:
                logging.warning(f"Unsupported mime type: {mime_type}")
                return ""

    except Exception as e:
        logging.error(f"Error downloading file {file_id}: {e}")
        return ""

def extract_pdf_text(file_content):
    """Extract text from PDF file using PyMuPDF"""
    if not PYMUPDF_AVAILABLE:
        logging.warning("PyMuPDF not available. Install with: pip install PyMuPDF")
        return ""

    try:
        # Open PDF document from bytes
        pdf_document = fitz.open(stream=file_content, filetype="pdf")
        text_content = []

        # Extract text from all pages
        for page_num in range(pdf_document.page_count):
            page = pdf_document[page_num]
            text_content.append(page.get_text())

        pdf_document.close()
        return "\n".join(text_content)
    except Exception as e:
        logging.error(f"Error extracting PDF text: {e}")
        return ""

def extract_docx_text(file_content):
    """Extract text from Word document"""
    if not DOCX_AVAILABLE:
        logging.warning("python-docx not available. Install with: pip install python-docx")
        return ""

    try:
        # If file_content is bytes, wrap it in BytesIO
        if isinstance(file_content, bytes):
            file_content = io.BytesIO(file_content)

        doc = DocxDocument(file_content)
        text_content = []

        for paragraph in doc.paragraphs:
            text_content.append(paragraph.text)

        # Also extract text from tables
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    text_content.append(cell.text)

        return "\n".join(text_content)
    except Exception as e:
        logging.error(f"Error extracting DOCX text: {e}")
        return ""

def extract_xlsx_text(file_content):
    """Extract text from Excel spreadsheet"""
    if not OPENPYXL_AVAILABLE:
        logging.warning("openpyxl not available. Install with: pip install openpyxl")
        return ""

    try:
        # If file_content is bytes, wrap it in BytesIO
        if isinstance(file_content, bytes):
            file_content = io.BytesIO(file_content)

        workbook = load_workbook(file_content, data_only=True)
        text_content = []

        for sheet_name in workbook.sheetnames:
            sheet = workbook[sheet_name]
            text_content.append(f"Sheet: {sheet_name}")

            for row in sheet.iter_rows(values_only=True):
                row_text = []
                for cell in row:
                    if cell is not None:
                        row_text.append(str(cell))
                if row_text:
                    text_content.append(" | ".join(row_text))

        return "\n".join(text_content)
    except Exception as e:
        logging.error(f"Error extracting XLSX text: {e}")
        return ""

def extract_pptx_text(file_content):
    """Extract text from PowerPoint presentation"""
    if not PPTX_AVAILABLE:
        logging.warning("python-pptx not available. Install with: pip install python-pptx")
        return ""

    try:
        # If file_content is bytes, wrap it in BytesIO
        if isinstance(file_content, bytes):
            file_content = io.BytesIO(file_content)

        presentation = Presentation(file_content)
        text_content = []

        for slide_num, slide in enumerate(presentation.slides, 1):
            text_content.append(f"Slide {slide_num}:")

            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    text_content.append(shape.text)

        return "\n".join(text_content)
    except Exception as e:
        logging.error(f"Error extracting PPTX text: {e}")
        return ""

@app.route("/companies/<company_id>/google-drive/disconnect", methods=["POST"])
@token_required
def disconnect_google_drive(company_id):
    """Disconnect Google Drive for a company and optionally remove synced files"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        company = companies_col.find_one({"_id": _id})
        if not company:
            return jsonify({"error": "Company not found"}), 404

        google_drive_config = company.get("google_drive")
        if not google_drive_config or not google_drive_config.get("connected"):
            return jsonify({"error": "Google Drive not connected"}), 400

        # Get request data to check if user wants to remove synced files
        data = request.get_json(force=True) if request.is_json else {}
        remove_synced_files = data.get("remove_synced_files", False)

        # Remove Google Drive connection from company
        companies_col.update_one(
            {"_id": _id},
            {"$unset": {"google_drive": ""}}
        )

        # Optionally remove all synced Google Drive files from metadata
        if remove_synced_files:
            # Get all Google Drive file IDs before deleting from MongoDB
            google_drive_docs = list(metadata_col.find({
                "company_id": company_id,
                "type": "google_drive_file"
            }, {"_id": 1}))

            doc_ids = [str(doc["_id"]) for doc in google_drive_docs]

            if doc_ids:
                # Delete from LightRAG FIRST
                app.logger.info(f"Deleting {len(doc_ids)} Google Drive files from LightRAG for company {company_id}...")
                lightrag_response = bulk_delete_company_documents(company_id, doc_ids)
                if lightrag_response.get("status") == "completed":
                    lightrag_result = lightrag_response.get("results", {})
                    app.logger.info(
                        f"LightRAG bulk delete: {lightrag_result.get('successful', 0)} successful, "
                        f"{lightrag_result.get('failed', 0)} failed"
                    )

                # Then delete from MongoDB
                result = metadata_col.delete_many({
                    "company_id": company_id,
                    "type": "google_drive_file"
                })
                removed_files = result.deleted_count
                app.logger.info(f"Deleted {removed_files} Google Drive files from MongoDB")
            else:
                removed_files = 0

            return jsonify({
                "message": "Google Drive disconnected and synced files removed",
                "removed_files": removed_files
            }), 200
        else:
            return jsonify({
                "message": "Google Drive disconnected. Synced files preserved.",
                "removed_files": 0
            }), 200

    except Exception as e:
        logging.error(f"Error disconnecting Google Drive: {e}")
        return jsonify({"error": "Failed to disconnect Google Drive"}), 500

@app.route("/companies/<company_id>/google-drive/folders", methods=["GET"])
@token_required
def get_google_drive_folders(company_id):
    """Get list of Google Drive folders for folder selection"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        company = companies_col.find_one({"_id": _id})
        if not company:
            return jsonify({"error": "Company not found"}), 404

        google_drive_config = company.get("google_drive")
        if not google_drive_config or not google_drive_config.get("connected"):
            return jsonify({"error": "Google Drive not connected"}), 400

        # Reconstruct credentials
        creds_dict = google_drive_config.get("credentials")
        if not creds_dict:
            return jsonify({"error": "No stored credentials"}), 400

        # Validate that all required fields are present and not None
        required_fields = ['token', 'refresh_token', 'token_uri', 'client_id', 'client_secret']
        missing_fields = []
        for field in required_fields:
            if not creds_dict.get(field):
                missing_fields.append(field)

        if missing_fields:
            return jsonify({
                "error": f"Missing credential fields: {missing_fields}. Please reconnect your Google Drive account.",
                "details": f"Required fields are missing: {', '.join(missing_fields)}",
                "requires_reauth": True
            }), 401

        credentials = Credentials(
            token=creds_dict.get("token"),
            refresh_token=creds_dict.get("refresh_token"),
            token_uri=creds_dict.get("token_uri"),
            client_id=creds_dict.get("client_id"),
            client_secret=creds_dict.get("client_secret"),
            scopes=creds_dict.get("scopes")
        )

        # Refresh credentials if needed
        if credentials.expired and credentials.refresh_token:
            success, error = refresh_google_credentials(credentials, company_id, _id)
            if not success:
                return jsonify({
                    "error": "Google Drive authentication expired. Please reconnect your Google Drive account.",
                    "details": error,
                    "requires_reauth": True
                }), 401

        # Build Drive service
        service = build('drive', 'v3', credentials=credentials)

        # Get all folders the user has access to
        folders = []
        page_token = None

        while True:
            results = service.files().list(
                q="mimeType='application/vnd.google-apps.folder' and trashed=false",
                pageSize=100,
                fields="nextPageToken, files(id, name, parents, createdTime, modifiedTime)",
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                corpora="allDrives"
            ).execute()

            items = results.get('files', [])

            for item in items:
                folder_info = {
                    "id": item["id"],
                    "name": item["name"],
                    "parents": item.get("parents", []),
                    "created_time": item.get("createdTime"),
                    "modified_time": item.get("modifiedTime")
                }
                folders.append(folder_info)

            page_token = results.get('nextPageToken')
            if not page_token:
                break

        # Build folder hierarchy for better UX
        folder_hierarchy = build_folder_hierarchy(folders)

        # Get currently monitored folders
        monitored_folders = google_drive_config.get("monitored_folders", [])

        return jsonify({
            "folders": folders,
            "folder_hierarchy": folder_hierarchy,
            "monitored_folders": monitored_folders
        }), 200

    except HttpError as e:
        logging.error(f"Google Drive API error: {e}")
        return jsonify({"error": "Google Drive API error"}), 500
    except Exception as e:
        logging.error(f"Error fetching Google Drive folders: {e}")
        return jsonify({"error": "Failed to fetch folders"}), 500

@app.route("/companies/<company_id>/google-drive/folders/children", methods=["GET"])
@token_required
def get_google_drive_folder_children(company_id):
    """Get children folders of a specific folder (or root folders if parent_id not provided)"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        company = companies_col.find_one({"_id": _id})
        if not company:
            return jsonify({"error": "Company not found"}), 404

        google_drive_config = company.get("google_drive")
        if not google_drive_config or not google_drive_config.get("connected"):
            return jsonify({"error": "Google Drive not connected"}), 400

        # Get parent_id from query params
        parent_id = request.args.get("parent_id", None)
        drive_id_param = request.args.get("drive_id", None)

        # Reconstruct credentials
        creds_dict = google_drive_config.get("credentials")
        if not creds_dict:
            return jsonify({"error": "No stored credentials"}), 400

        # Validate credentials
        required_fields = ['token', 'refresh_token', 'token_uri', 'client_id', 'client_secret']
        missing_fields = []
        for field in required_fields:
            if not creds_dict.get(field):
                missing_fields.append(field)

        if missing_fields:
            return jsonify({
                "error": f"Missing credential fields: {missing_fields}. Please reconnect your Google Drive account.",
                "details": f"Required fields are missing: {', '.join(missing_fields)}",
                "requires_reauth": True
            }), 401

        credentials = Credentials(
            token=creds_dict.get("token"),
            refresh_token=creds_dict.get("refresh_token"),
            token_uri=creds_dict.get("token_uri"),
            client_id=creds_dict.get("client_id"),
            client_secret=creds_dict.get("client_secret"),
            scopes=creds_dict.get("scopes")
        )

        # Refresh credentials if needed
        if credentials.expired and credentials.refresh_token:
            success, error = refresh_google_credentials(credentials, company_id, _id)
            if not success:
                return jsonify({
                    "error": "Google Drive authentication expired. Please reconnect your Google Drive account.",
                    "details": error,
                    "requires_reauth": True
                }), 401

        # Build Drive service
        service = build('drive', 'v3', credentials=credentials)

        folders = []
        page_token = None

        # Build query based on whether we're fetching root folders or children
        if parent_id:
            if parent_id == "__shared_drives__":
                # Return shared drive entries as virtual folders under "Shared drives"
                drive_page_token = None
                while True:
                    drives_result = service.drives().list(
                        pageSize=100,
                        fields="nextPageToken, drives(id,name)",
                        pageToken=drive_page_token
                    ).execute()

                    shared_drives = drives_result.get("drives", [])
                    for drive in shared_drives:
                        folders.append({
                            "id": f"shared_drive::{drive.get('id')}",
                            "name": drive.get("name", "Shared drive"),
                            "parents": ["__shared_drives__"],
                            "created_time": None,
                            "modified_time": None,
                            "has_children": True,
                            "virtual": True
                        })

                    drive_page_token = drives_result.get("nextPageToken")
                    if not drive_page_token:
                        break
            elif parent_id.startswith("shared_drive::"):
                # Return root folders of one shared drive
                drive_id = parent_id.split("::", 1)[1]
                query = f"'{drive_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
                while True:
                    results = service.files().list(
                        q=query,
                        pageSize=100,
                        fields="nextPageToken, files(id, name, parents, createdTime, modifiedTime)",
                        pageToken=page_token,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                        corpora="drive",
                        driveId=drive_id
                    ).execute()

                    items = results.get('files', [])
                    for item in items:
                        folders.append({
                            "id": item["id"],
                            "name": item["name"],
                            "parents": item.get("parents", []),
                            "created_time": item.get("createdTime"),
                            "modified_time": item.get("modifiedTime"),
                            "has_children": True,
                            "drive_id": drive_id
                        })

                    page_token = results.get('nextPageToken')
                    if not page_token:
                        break
            else:
                # Fetch children of specific folder
                query = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
                request_kwargs = {
                    "q": query,
                    "pageSize": 100,
                    "fields": "nextPageToken, files(id, name, parents, createdTime, modifiedTime)",
                    "supportsAllDrives": True,
                    "includeItemsFromAllDrives": True,
                    "corpora": "allDrives"
                }

                parent_drive_id = drive_id_param
                if parent_drive_id:
                    request_kwargs["corpora"] = "drive"
                    request_kwargs["driveId"] = parent_drive_id
                else:
                    # If this parent folder belongs to a Shared Drive, query that drive explicitly.
                    try:
                        parent_meta = service.files().get(
                            fileId=parent_id,
                            fields="id, driveId",
                            supportsAllDrives=True
                        ).execute()
                        parent_drive_id = parent_meta.get("driveId")
                        if parent_drive_id:
                            request_kwargs["corpora"] = "drive"
                            request_kwargs["driveId"] = parent_drive_id
                    except Exception:
                        # Fallback to allDrives query if parent metadata lookup fails.
                        pass
                def _list_children(list_kwargs):
                    local_folders = []
                    local_page_token = None
                    while True:
                        list_kwargs["pageToken"] = local_page_token
                        results = service.files().list(**list_kwargs).execute()

                        items = results.get('files', [])
                        for item in items:
                            local_folders.append({
                                "id": item["id"],
                                "name": item["name"],
                                "parents": item.get("parents", []),
                                "created_time": item.get("createdTime"),
                                "modified_time": item.get("modifiedTime"),
                                "has_children": True,
                                "drive_id": parent_drive_id
                            })

                        local_page_token = results.get('nextPageToken')
                        if not local_page_token:
                            break
                    return local_folders

                # Primary query
                folders = _list_children(dict(request_kwargs))

                # Fallback only for unknown-drive cases; if drive_id is explicit, do not mix results from other drives.
                if len(folders) == 0 and request_kwargs.get("corpora") == "drive" and not drive_id_param:
                    fallback_kwargs = dict(request_kwargs)
                    fallback_kwargs.pop("driveId", None)
                    fallback_kwargs["corpora"] = "allDrives"
                    folders = _list_children(fallback_kwargs)
        else:
            # Fetch root-level folders from My Drive and each Shared Drive.
            # In Drive API, 'root' is interpreted against the selected corpus/drive.
            query = "'root' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            seen_folder_ids = set()

            # 1) My Drive roots
            page_token = None
            while True:
                results = service.files().list(
                    q=query,
                    pageSize=100,
                    fields="nextPageToken, files(id, name, parents, createdTime, modifiedTime)",
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="user"
                ).execute()

                items = results.get('files', [])
                for item in items:
                    if item["id"] in seen_folder_ids:
                        continue
                    seen_folder_ids.add(item["id"])
                    folders.append({
                        "id": item["id"],
                        "name": item["name"],
                        "parents": item.get("parents", []),
                        "created_time": item.get("createdTime"),
                        "modified_time": item.get("modifiedTime"),
                        "has_children": True
                    })

                page_token = results.get('nextPageToken')
                if not page_token:
                    break

            # 2) Shared Drive roots
            drive_page_token = None
            while True:
                drives_result = service.drives().list(
                    pageSize=100,
                    fields="nextPageToken, drives(id,name)",
                    pageToken=drive_page_token
                ).execute()

                shared_drives = drives_result.get("drives", [])
                for drive in shared_drives:
                    sd_page_token = None
                    while True:
                        sd_results = service.files().list(
                            q=query,
                            pageSize=100,
                            fields="nextPageToken, files(id, name, parents, createdTime, modifiedTime)",
                            pageToken=sd_page_token,
                            supportsAllDrives=True,
                            includeItemsFromAllDrives=True,
                            corpora="drive",
                            driveId=drive.get("id")
                        ).execute()

                        items = sd_results.get("files", [])
                        for item in items:
                            if item["id"] in seen_folder_ids:
                                continue
                            seen_folder_ids.add(item["id"])
                            folders.append({
                                "id": item["id"],
                                "name": item["name"],
                                "parents": item.get("parents", []),
                                "created_time": item.get("createdTime"),
                                "modified_time": item.get("modifiedTime"),
                                "has_children": True
                            })

                        sd_page_token = sd_results.get("nextPageToken")
                        if not sd_page_token:
                            break

                drive_page_token = drives_result.get("nextPageToken")
                if not drive_page_token:
                    break

            # 3) "Shared with me" folders that may not belong to My Drive root or a Shared Drive root
            shared_query = "sharedWithMe=true and mimeType='application/vnd.google-apps.folder' and trashed=false"
            shared_page_token = None
            while True:
                shared_results = service.files().list(
                    q=shared_query,
                    pageSize=100,
                    fields="nextPageToken, files(id, name, parents, createdTime, modifiedTime)",
                    pageToken=shared_page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives"
                ).execute()

                items = shared_results.get("files", [])
                for item in items:
                    if item["id"] in seen_folder_ids:
                        continue
                    seen_folder_ids.add(item["id"])
                    folders.append({
                        "id": item["id"],
                        "name": item["name"],
                        "parents": item.get("parents", []),
                        "created_time": item.get("createdTime"),
                        "modified_time": item.get("modifiedTime"),
                        "has_children": True
                    })

                shared_page_token = shared_results.get("nextPageToken")
                if not shared_page_token:
                    break

            # 4) Add virtual container for shared drives
            try:
                drives_probe = service.drives().list(pageSize=1, fields="drives(id), nextPageToken").execute()
                if drives_probe.get("drives"):
                    folders.append({
                        "id": "__shared_drives__",
                        "name": "Shared drives",
                        "parents": [],
                        "created_time": None,
                        "modified_time": None,
                        "has_children": True,
                        "virtual": True
                    })
            except Exception:
                # Ignore if user has no Shared Drives or listing is unavailable
                pass

        # Sort folders alphabetically
        folders.sort(key=lambda f: f["name"].lower())

        # Get folders_to_expand and monitored_folders data for the response
        monitored_folders = google_drive_config.get("monitored_folders", [])
        folders_to_expand = google_drive_config.get("folders_to_expand", {})
        parent_chains = google_drive_config.get("parent_chains", {})

        return jsonify({
            "folders": folders,
            "parent_id": parent_id,
            "monitored_folders": monitored_folders,
            "folders_to_expand": folders_to_expand,
            "parent_chains": parent_chains
        }), 200

    except HttpError as e:
        logging.error(f"Google Drive API error: {e}")
        return jsonify({"error": "Google Drive API error"}), 500
    except Exception as e:
        logging.error(f"Error fetching Google Drive folder children: {e}")
        return jsonify({"error": "Failed to fetch folder children"}), 500

@app.route("/companies/<company_id>/google-drive/folders", methods=["PUT"])
@token_required
def update_monitored_folders(company_id):
    """Update the list of monitored Google Drive folders"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        company = companies_col.find_one({"_id": _id})
        if not company:
            return jsonify({"error": "Company not found"}), 404

        google_drive_config = company.get("google_drive")
        if not google_drive_config or not google_drive_config.get("connected"):
            return jsonify({"error": "Google Drive not connected"}), 400

        data = request.get_json(force=True)
        app.logger.info(f"Received folder update request: {data}")

        # Accept both 'monitored_folders' (old format) and 'folder_ids' (new format)
        monitored_folders = data.get("monitored_folders") or data.get("folder_ids", [])
        app.logger.info(f"Parsed monitored_folders: {monitored_folders}")

        # Validate that all folder IDs are strings
        if not isinstance(monitored_folders, list) or not all(isinstance(f, str) for f in monitored_folders):
            return jsonify({"error": "folder_ids must be a list of folder ID strings"}), 400

        # VALIDATION: At least 1 folder must be selected
        if len(monitored_folders) == 0:
            return jsonify({
                "error": "At least one folder must be selected for monitoring",
                "validation_error": "min_folders"
            }), 400

        # VALIDATION: Maximum 10 folders can be selected
        if len(monitored_folders) > 10:
            return jsonify({
                "error": f"Maximum 10 folders can be selected. You have selected {len(monitored_folders)} folders.",
                "validation_error": "max_folders",
                "folder_count": len(monitored_folders)
            }), 400

        # Get current monitored folders to determine which ones to remove
        current_monitored_folders = google_drive_config.get("monitored_folders", [])

        # Find folders that are no longer being monitored
        removed_folders = [folder_id for folder_id in current_monitored_folders if folder_id not in monitored_folders]

        # Clean up files from folders that are no longer monitored
        removed_files_count = 0
        if removed_folders:
            app.logger.info(f"Removing files from {len(removed_folders)} unselected folders: {removed_folders}")

            # Find files that belong to folders that are no longer monitored
            # Use the stored parent_folders information for efficient cleanup
            files_to_remove = metadata_col.find({
                "company_id": company_id,
                "type": "google_drive_file",
                "google_drive.parent_folders": {"$elemMatch": {"$in": removed_folders}}
            })

            files_to_remove_ids = []
            for file_doc in files_to_remove:
                file_parents = file_doc.get("google_drive", {}).get("parent_folders", [])
                # Only remove if ALL parent folders are no longer monitored
                # (a file could be in multiple folders, and we only remove if none are monitored)
                file_is_still_monitored = any(parent in monitored_folders for parent in file_parents)

                if not file_is_still_monitored:
                    files_to_remove_ids.append(file_doc["_id"])

            # Remove files that are no longer in any monitored folders
            if files_to_remove_ids:
                result = metadata_col.delete_many({"_id": {"$in": files_to_remove_ids}})
                removed_files_count = result.deleted_count
                app.logger.info(f"Removed {removed_files_count} files from unmonitored folders")

            # For older files that don't have parent_folders stored, fall back to API check
            legacy_files = list(metadata_col.find({
                "company_id": company_id,
                "type": "google_drive_file",
                "google_drive.parent_folders": {"$exists": False}
            }))

            if legacy_files:
                app.logger.info(f"Checking {len(legacy_files)} legacy files without stored parent folder info")
                try:
                    # Build Google Drive service for legacy files
                    creds_data = google_drive_config.get("credentials")
                    if creds_data:
                        creds = Credentials.from_authorized_user_info(creds_data)

                        # Refresh credentials if needed
                        success, error_msg = refresh_google_credentials(creds, company_id, _id)
                        if not success:
                            app.logger.warning(f"Could not refresh credentials for legacy cleanup: {error_msg}")
                        else:
                            service = build('drive', 'v3', credentials=creds)

                            legacy_files_to_remove = []

                            # Check each legacy file to see if it's still in a monitored folder
                            for file_doc in legacy_files:
                                file_id = file_doc.get("google_drive", {}).get("file_id")
                                if file_id:
                                    try:
                                        # Get current file info from Google Drive
                                        file_info = service.files().get(
                                            fileId=file_id,
                                            fields="parents",
                                            supportsAllDrives=True
                                        ).execute()
                                        file_parents = file_info.get("parents", [])

                                        # Update the file document with parent folder info for future use
                                        metadata_col.update_one(
                                            {"_id": file_doc["_id"]},
                                            {"$set": {"google_drive.parent_folders": file_parents}}
                                        )

                                        # Check if any of the file's parents are in monitored folders
                                        file_is_monitored = any(parent in monitored_folders for parent in file_parents)

                                        if not file_is_monitored:
                                            legacy_files_to_remove.append(file_doc["_id"])

                                    except Exception as e:
                                        app.logger.warning(f"Could not check legacy file {file_id} location: {e}")
                                        # If we can't verify the file location, we'll keep it to be safe

                            # Remove legacy files that are no longer in monitored folders
                            if legacy_files_to_remove:
                                result = metadata_col.delete_many({"_id": {"$in": legacy_files_to_remove}})
                                legacy_removed_count = result.deleted_count
                                removed_files_count += legacy_removed_count
                                app.logger.info(f"Removed {legacy_removed_count} legacy files from unmonitored folders")

                except Exception as e:
                    app.logger.error(f"Error during legacy file cleanup: {e}")
                    # Continue with folder update even if cleanup fails

        # Compute folders_to_expand information for frontend
        folders_to_expand_data = None
        try:
            # Build Google Drive service
            creds_dict = google_drive_config.get("credentials")
            if creds_dict:
                credentials = Credentials(
                    token=creds_dict.get("token"),
                    refresh_token=creds_dict.get("refresh_token"),
                    token_uri=creds_dict.get("token_uri"),
                    client_id=creds_dict.get("client_id"),
                    client_secret=creds_dict.get("client_secret"),
                    scopes=creds_dict.get("scopes")
                )

                # Refresh if needed
                if credentials.expired and credentials.refresh_token:
                    refresh_google_credentials(credentials, company_id, _id)

                service = build('drive', 'v3', credentials=credentials)
                folders_to_expand_data = compute_folders_to_expand_google(service, monitored_folders)

                app.logger.info(f"Computed folders_to_expand: {folders_to_expand_data}")
        except Exception as e:
            app.logger.error(f"Error computing folders_to_expand: {e}")
            # Continue even if this fails - frontend can fall back to basic behavior

        # Update the monitored folders list and folders_to_expand data
        update_data = {
            "google_drive.monitored_folders": monitored_folders,
            "google_drive.folder_count": len(monitored_folders)
        }

        if folders_to_expand_data:
            update_data["google_drive.folders_to_expand"] = folders_to_expand_data["folders_to_expand"]
            update_data["google_drive.parent_chains"] = folders_to_expand_data["parent_chains"]

        companies_col.update_one(
            {"_id": _id},
            {"$set": update_data}
        )

        # Update file count after cleanup
        total_file_count = metadata_col.count_documents({
            "company_id": company_id,
            "type": "google_drive_file"
        })

        companies_col.update_one(
            {"_id": _id},
            {"$set": {"google_drive.file_count": total_file_count}}
        )

        message = f"Updated monitored folders. Now monitoring {len(monitored_folders)} folders."
        if removed_files_count > 0:
            message += f" Removed {removed_files_count} files from unselected folders."

        return jsonify({
            "message": message,
            "monitored_folders": monitored_folders,
            "removed_files": removed_files_count
        }), 200

    except Exception as e:
        logging.error(f"Error updating monitored folders: {e}")
        return jsonify({"error": "Failed to update monitored folders"}), 500

def build_folder_hierarchy(folders):
    """Build a hierarchical structure of folders for better UX"""
    folder_dict = {folder["id"]: folder for folder in folders}
    hierarchy = []

    for folder in folders:
        folder_copy = folder.copy()
        folder_copy["children"] = []
        folder_copy["path"] = get_folder_path(folder["id"], folder_dict)

        # If this folder has no parents or parent is not in our list, it's a root folder
        parents = folder.get("parents", [])
        if not parents or not any(parent in folder_dict for parent in parents):
            hierarchy.append(folder_copy)
        else:
            # Add as child to parent folder
            for parent_id in parents:
                if parent_id in folder_dict:
                    parent = next((f for f in hierarchy if f["id"] == parent_id), None)
                    if parent:
                        parent["children"].append(folder_copy)
                    break

    return hierarchy

def get_folder_path(folder_id, folder_dict, visited=None):
    """Get the full path of a folder (e.g., 'Parent/Child/Folder')"""
    if visited is None:
        visited = set()

    if folder_id in visited:
        return "..."  # Circular reference protection

    visited.add(folder_id)

    if folder_id not in folder_dict:
        return "Unknown"

    folder = folder_dict[folder_id]
    parents = folder.get("parents", [])

    if not parents:
        return folder["name"]

    # Use the first parent to build path
    parent_id = parents[0]
    if parent_id in folder_dict:
        parent_path = get_folder_path(parent_id, folder_dict, visited)
        return f"{parent_path}/{folder['name']}"

    return folder["name"]

# ─── Google Drive Helper Functions ───────────────────────────────────────────
def get_folder_parent_chain_google(service, folder_id, max_depth=10):
    """
    Get the parent chain for a Google Drive folder (from folder up to root)
    Returns list of folder IDs from the folder itself up to root
    """
    chain = [folder_id]
    current_id = folder_id
    depth = 0

    while depth < max_depth:
        try:
            folder = service.files().get(
                fileId=current_id,
                fields="parents",
                supportsAllDrives=True
            ).execute()
            parents = folder.get("parents", [])

            if not parents:
                break

            parent_id = parents[0]  # Google Drive folders typically have one parent
            chain.append(parent_id)
            current_id = parent_id
            depth += 1
        except Exception as e:
            app.logger.warning(f"Could not get parent for folder {current_id}: {e}")
            break

    return chain

def compute_folders_to_expand_google(service, selected_folder_ids):
    """
    Compute which folders need to be expanded to show all selected folders
    Returns a dict with:
      - folders_to_expand: dict mapping parent_id -> set of child_ids that need to be loaded
      - parent_chains: dict mapping folder_id -> list of parent ids (for frontend to know structure)
    """
    # Get parent chains for all selected folders
    parent_chains = {}
    for folder_id in selected_folder_ids:
        chain = get_folder_parent_chain_google(service, folder_id)
        parent_chains[folder_id] = chain

    # Build a set of all folders that need to be expanded (have selected descendants)
    folders_to_expand = {}

    for folder_id, chain in parent_chains.items():
        # For each folder in the chain (except the first which is the selected folder itself)
        for i in range(len(chain) - 1):
            child_id = chain[i]
            parent_id = chain[i + 1]

            if parent_id not in folders_to_expand:
                folders_to_expand[parent_id] = set()
            folders_to_expand[parent_id].add(child_id)

    # Handle root folders (those with no parent in our chains)
    root_folders = set()
    for folder_id, chain in parent_chains.items():
        if len(chain) > 0:
            root_id = chain[-1]  # The topmost parent
            root_folders.add(root_id)

    # Add root folders under a special "root" key
    if root_folders:
        folders_to_expand["root"] = root_folders

    # Convert sets to lists for JSON serialization
    folders_to_expand_json = {k: list(v) for k, v in folders_to_expand.items()}

    return {
        "folders_to_expand": folders_to_expand_json,
        "parent_chains": parent_chains
    }

def refresh_google_credentials(credentials, company_id=None, company_obj_id=None):
    """
    Helper function to refresh Google Drive credentials with proper error handling
    Returns (success: bool, error_message: str)
    """
    try:
        # Validate that we have all required fields for refresh
        if not credentials.refresh_token:
            return False, "No refresh token available"

        if not credentials.client_id:
            return False, "Missing client_id in credentials"

        if not credentials.client_secret:
            return False, "Missing client_secret in credentials"

        if not credentials.token_uri:
            return False, "Missing token_uri in credentials"

        credentials.refresh(Request())

        if company_obj_id:
            # Update stored credentials
            updated_creds = {
                "token": credentials.token,
                "refresh_token": credentials.refresh_token,
                "token_uri": credentials.token_uri,
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "scopes": credentials.scopes
            }

            companies_col.update_one(
                {"_id": company_obj_id},
                {"$set": {"google_drive.credentials": updated_creds}}
            )

        app.logger.info(f"Successfully refreshed Google Drive credentials for company {company_id}")
        return True, None

    except Exception as e:
        raw_error = str(e)
        is_invalid_grant = "invalid_grant" in raw_error.lower()
        if is_invalid_grant:
            error_msg = "Failed to refresh Google Drive credentials: invalid_grant (reconnect required)"
        else:
            error_msg = f"Failed to refresh Google Drive credentials: {raw_error}"
        app.logger.error(error_msg)

        if company_obj_id:
            if is_invalid_grant:
                # Stale/revoked refresh token: mark integration as disconnected so UI prompts reconnect.
                companies_col.update_one(
                    {"_id": company_obj_id},
                    {"$set": {
                        "google_drive.connected": False,
                        "google_drive.requires_reauth": True,
                        "google_drive.connection_error": error_msg,
                        "google_drive.last_error": datetime.datetime.utcnow().isoformat()
                    }}
                )
            else:
                # Mark connection as having issues
                companies_col.update_one(
                    {"_id": company_obj_id},
                    {"$set": {
                        "google_drive.connection_error": error_msg,
                        "google_drive.last_error": datetime.datetime.utcnow().isoformat()
                    }}
                )

        return False, error_msg

# ─── OneDrive Helper Functions ────────────────────────────────────────────────
def get_folder_parent_chain_onedrive(headers, folder_id, max_depth=10):
    """
    Get the parent chain for a OneDrive folder (from folder up to root)
    Returns list of folder IDs from the folder itself up to root
    """
    import requests

    chain = [folder_id]
    current_id = folder_id
    depth = 0

    while depth < max_depth:
        try:
            # Get folder info including parent reference
            folder_url = f"https://graph.microsoft.com/v1.0/me/drive/items/{current_id}"
            folder_response = requests.get(folder_url, headers=headers)

            if folder_response.status_code != 200:
                break

            folder_data = folder_response.json()
            parent_ref = folder_data.get("parentReference", {})
            parent_id = parent_ref.get("id")

            if not parent_id:
                break

            chain.append(parent_id)
            current_id = parent_id
            depth += 1
        except Exception as e:
            app.logger.warning(f"Could not get parent for OneDrive folder {current_id}: {e}")
            break

    return chain

def compute_folders_to_expand_onedrive(headers, selected_folder_ids):
    """
    Compute which folders need to be expanded to show all selected folders for OneDrive
    Returns a dict with:
      - folders_to_expand: dict mapping parent_id -> set of child_ids that need to be loaded
      - parent_chains: dict mapping folder_id -> list of parent ids (for frontend to know structure)
    """
    # Get parent chains for all selected folders
    parent_chains = {}
    for folder_id in selected_folder_ids:
        chain = get_folder_parent_chain_onedrive(headers, folder_id)
        parent_chains[folder_id] = chain

    # Build a set of all folders that need to be expanded (have selected descendants)
    folders_to_expand = {}

    for folder_id, chain in parent_chains.items():
        # For each folder in the chain (except the first which is the selected folder itself)
        for i in range(len(chain) - 1):
            child_id = chain[i]
            parent_id = chain[i + 1]

            if parent_id not in folders_to_expand:
                folders_to_expand[parent_id] = set()
            folders_to_expand[parent_id].add(child_id)

    # Handle root folders (those with no parent in our chains)
    root_folders = set()
    for folder_id, chain in parent_chains.items():
        if len(chain) > 0:
            root_id = chain[-1]  # The topmost parent
            root_folders.add(root_id)

    # Add root folders under a special "root" key
    if root_folders:
        folders_to_expand["root"] = root_folders

    # Convert sets to lists for JSON serialization
    folders_to_expand_json = {k: list(v) for k, v in folders_to_expand.items()}

    return {
        "folders_to_expand": folders_to_expand_json,
        "parent_chains": parent_chains
    }

def refresh_microsoft_credentials(credentials_dict, company_id=None, company_obj_id=None):
    """
    Helper function to refresh Microsoft OneDrive credentials with proper error handling
    Returns (success: bool, error_message: str)
    """
    try:
        import msal
        import requests

        if not credentials_dict.get("refresh_token"):
            return False, "No refresh token available"

        app_instance = msal.ConfidentialClientApplication(
            credentials_dict.get("client_id", MICROSOFT_CLIENT_ID),
            authority=f"https://login.microsoftonline.com/{credentials_dict.get('tenant_id', MICROSOFT_TENANT_ID)}",
            client_credential=credentials_dict.get("client_secret", MICROSOFT_CLIENT_SECRET)
        )

        # Refresh the token
        result = app_instance.acquire_token_by_refresh_token(
            credentials_dict["refresh_token"],
            scopes=credentials_dict.get("scopes", MICROSOFT_ONEDRIVE_SCOPES)
        )

        if "access_token" not in result:
            return False, f"Failed to refresh token: {result.get('error_description', 'Unknown error')}"

        # Update credentials dict
        credentials_dict["access_token"] = result["access_token"]
        if "refresh_token" in result:
            credentials_dict["refresh_token"] = result["refresh_token"]

        if company_obj_id:
            # Update stored credentials
            companies_col.update_one(
                {"_id": company_obj_id},
                {"$set": {"onedrive.credentials": credentials_dict}}
            )

        app.logger.info(f"Successfully refreshed OneDrive credentials for company {company_id}")
        return True, None

    except Exception as e:
        error_msg = f"Failed to refresh OneDrive credentials: {str(e)}"
        app.logger.error(error_msg)

        if company_obj_id:
            # Mark connection as having issues
            companies_col.update_one(
                {"_id": company_obj_id},
                {"$set": {
                    "onedrive.connection_error": error_msg,
                    "onedrive.last_error": datetime.datetime.utcnow().isoformat()
                }}
            )

        return False, error_msg

def download_and_extract_onedrive_content(file_info, headers):
    """Download and extract text content from OneDrive file with detailed logging"""
    file_name = file_info.get('name', 'Unknown')
    file_id = file_info.get('id', 'Unknown')

    app.logger.info(f"=== Starting content extraction for OneDrive file: {file_name} ===")
    app.logger.debug(f"File info: {file_info}")

    try:
        # Get download URL
        download_url = f"https://graph.microsoft.com/v1.0/me/drive/items/{file_id}/content"
        app.logger.info(f"Download URL: {download_url}")

        # Download file content
        app.logger.info(f"Downloading file content for {file_name}")
        response = requests.get(download_url, headers=headers)
        app.logger.info(f"Download response status: {response.status_code}")

        if response.status_code != 200:
            app.logger.warning(f"Failed to download OneDrive file {file_name}: {response.status_code}")
            app.logger.warning(f"Response content: {response.text}")
            return None

        file_content = response.content
        content_length = len(file_content)
        app.logger.info(f"Downloaded {content_length} bytes for {file_name}")

        if content_length == 0:
            app.logger.warning(f"File {file_name} has zero bytes content")
            return None

        file_extension = file_name.lower().split('.')[-1] if '.' in file_name else ''
        app.logger.info(f"File extension detected: '{file_extension}' for {file_name}")

        # Extract text based on file type
        extracted_text = None

        if file_extension == 'pdf':
            app.logger.info(f"Processing PDF file: {file_name}")
            extracted_text = extract_pdf_text(file_content)
        elif file_extension in ['doc', 'docx']:
            app.logger.info(f"Processing Word document: {file_name}")
            extracted_text = extract_docx_text(file_content)
        elif file_extension in ['xls', 'xlsx']:
            app.logger.info(f"Processing Excel spreadsheet: {file_name}")
            extracted_text = extract_xlsx_text(file_content)
        elif file_extension in ['ppt', 'pptx']:
            app.logger.info(f"Processing PowerPoint presentation: {file_name}")
            extracted_text = extract_pptx_text(file_content)
        elif file_extension in ['txt', 'md', 'rtf', 'csv']:
            app.logger.info(f"Processing text file: {file_name}")
            try:
                extracted_text = file_content.decode('utf-8', errors='ignore')
                app.logger.info(f"Successfully decoded {file_name} as UTF-8")
            except Exception as decode_error:
                app.logger.warning(f"UTF-8 decode failed for {file_name}, trying latin-1: {decode_error}")
                try:
                    extracted_text = file_content.decode('latin-1', errors='ignore')
                    app.logger.info(f"Successfully decoded {file_name} as latin-1")
                except Exception as fallback_error:
                    app.logger.error(f"All decode attempts failed for {file_name}: {fallback_error}")
                    return None
        else:
            # For unsupported file types, try to extract as plain text
            app.logger.info(f"Unknown file type '{file_extension}' for {file_name}, attempting text extraction")
            try:
                extracted_text = file_content.decode('utf-8', errors='ignore')[:5000]  # Limit to prevent huge files
                app.logger.info(f"Successfully extracted text from unknown file type: {file_name}")
            except Exception as unknown_error:
                app.logger.warning(f"Cannot extract text from unsupported file type: {file_name} - {unknown_error}")
                return None

        if extracted_text:
            text_length = len(extracted_text)
            app.logger.info(f"Successfully extracted {text_length} characters from {file_name}")

            # Log a preview of the content
            preview = extracted_text[:200] + "..." if len(extracted_text) > 200 else extracted_text
            app.logger.debug(f"Content preview for {file_name}: {preview}")

            return extracted_text
        else:
            app.logger.warning(f"No text content extracted from {file_name}")
            return None

    except Exception as e:
        app.logger.error(f"Error downloading/extracting OneDrive file content for {file_name}: {e}")
        app.logger.exception("Full stack trace:")
        return None

# ─── Email Integration ────────────────────────────────────────────────────────
@app.route("/companies/<company_id>/email/auth/<provider>", methods=["POST"])
@token_required
def initiate_email_auth(company_id, provider):
    """Initiate email OAuth flow for a company"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    if not EMAIL_PROVIDERS_AVAILABLE:
        return jsonify({"error": "Email providers not available"}), 500

    try:
        if provider == "gmail":
            from google_auth_oauthlib.flow import Flow

            flow = Flow.from_client_config(
                {
                    "web": {
                        "client_id": GOOGLE_CLIENT_ID,
                        "client_secret": GOOGLE_CLIENT_SECRET,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": [GOOGLE_REDIRECT_URI]  # Use same redirect URI
                    }
                },
                scopes=GMAIL_EMAIL_SCOPES
            )
            flow.redirect_uri = GOOGLE_REDIRECT_URI

            state_nonce = secrets.token_urlsafe(16)
            state_value = f"{company_id}|gmail|{state_nonce}"
            authorization_url, state = flow.authorization_url(
                access_type='offline',
                # include_granted_scopes='true',  # Removed: This makes scopes optional
                prompt='consent',
                code_challenge_method='S256',
                state=state_value  # Include service type + nonce in state
            )

            if not getattr(flow, "code_verifier", None):
                return jsonify({"error": "Failed to initialize OAuth PKCE verifier"}), 500
            store_google_oauth_pkce_state(state, company_id, "gmail", flow.code_verifier)

            return jsonify({
                "authorization_url": authorization_url,
                "state": state
            }), 200

        elif provider == "microsoft":
            import msal

            app_instance = msal.ConfidentialClientApplication(
                MICROSOFT_CLIENT_ID,
                authority=f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}",
                client_credential=MICROSOFT_CLIENT_SECRET
            )

            auth_url = app_instance.get_authorization_request_url(
                MICROSOFT_EMAIL_SCOPES,
                redirect_uri=MICROSOFT_REDIRECT_URI,
                state=f"{company_id}|microsoft"
            )

            return jsonify({
                "authorization_url": auth_url,
                "state": f"{company_id}|microsoft"
            }), 200

        else:
            return jsonify({"error": "Unsupported email provider"}), 400

    except Exception as e:
        logging.error(f"Error initiating email auth for {provider}: {e}")
        return jsonify({"error": "Failed to initiate authentication"}), 500

@app.route("/companies/<company_id>/email/connect/generic", methods=["POST"])
@token_required
def connect_generic_email(company_id):
    """Connect generic IMAP email for a company"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    if not EMAIL_PROVIDERS_AVAILABLE:
        return jsonify({"error": "Email providers not available"}), 500

    try:
        data = request.get_json(force=True)

        # Validate required fields
        required_fields = ["email_address", "password", "imap_server"]
        for field in required_fields:
            if not data.get(field):
                return jsonify({"error": f"Missing required field: {field}"}), 400

        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        # Create generic email provider to test connection
        email_provider = get_email_provider(
            provider_type="generic",
            encryption_key=EMAIL_ENCRYPTION_KEY
        )

        # Encrypt password
        encrypted_password = email_provider.encrypt_password(data["password"])

        # Test credentials
        test_credentials = {
            "email_address": data["email_address"],
            "username": data.get("username", data["email_address"]),
            "password": data["password"],
            "imap_server": data["imap_server"],
            "imap_port": data.get("imap_port", 993),
            "use_ssl": data.get("use_ssl", True)
        }

        auth_success, auth_error = email_provider.authenticate(test_credentials)
        email_provider.disconnect()

        if not auth_success:
            return jsonify({"error": f"Authentication failed: {auth_error}"}), 401

        # Store encrypted credentials
        credentials = {
            "email_address": data["email_address"],
            "username": data.get("username", data["email_address"]),
            "password": encrypted_password,
            "imap_server": data["imap_server"],
            "imap_port": data.get("imap_port", 993),
            "use_ssl": data.get("use_ssl", True)
        }

        companies_col.update_one(
            {"_id": _id},
            {
                "$set": {
                    "email_integration": {
                        "connected": True,
                        "provider": "generic",
                        "email_address": data["email_address"],
                        "connection_type": "password",
                        "credentials": credentials,
                        "connected_at": datetime.datetime.utcnow().isoformat(),
                        "last_sync": None,
                        "sync_status": "connected",
                        "settings": {
                            "sync_folders": ["INBOX"],
                            "sync_since_days": 30,
                            "max_emails_per_sync": 100,
                            "include_attachments": False,
                            "skip_large_emails": True,
                            "max_email_size_mb": 10
                        },
                        "stats": {
                            "total_emails_synced": 0,
                            "last_sync_count": 0,
                            "errors_count": 0
                        }
                    }
                }
            }
        )

        return jsonify({"message": "Generic email connected successfully"}), 200

    except Exception as e:
        logging.error(f"Error connecting generic email: {e}")
        return jsonify({"error": "Failed to connect email account"}), 500

@app.route("/auth/microsoft/callback", methods=["GET"])
def microsoft_callback():
    """Handle Microsoft OAuth callback"""
    try:
        code = request.args.get('code')
        state = request.args.get('state')
        error = request.args.get('error')

        if error:
            return jsonify({"error": f"OAuth error: {error}"}), 400

        if not code or not state:
            return jsonify({"error": "Missing authorization code or state"}), 400

        # Parse state to get company_id and service type
        state_parts = state.split("|")
        if len(state_parts) != 2 or state_parts[1] not in ["microsoft", "onedrive"]:
            return jsonify({"error": "Invalid state parameter"}), 400

        company_id = state_parts[0]
        service_type = state_parts[1]  # "microsoft" for email, "onedrive" for OneDrive

        # Exchange code for credentials
        import msal

        app_instance = msal.ConfidentialClientApplication(
            MICROSOFT_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}",
            client_credential=MICROSOFT_CLIENT_SECRET
        )

        # Use appropriate scopes based on service type
        scopes = MICROSOFT_EMAIL_SCOPES if service_type == "microsoft" else MICROSOFT_ONEDRIVE_SCOPES

        result = app_instance.acquire_token_by_authorization_code(
            code,
            scopes=scopes,
            redirect_uri=MICROSOFT_REDIRECT_URI
        )

        if "access_token" not in result:
            return jsonify({"error": f"Failed to get access token: {result.get('error_description', 'Unknown error')}"}), 400

        # Get user email address
        import requests
        headers = {"Authorization": f"Bearer {result['access_token']}"}
        user_info = requests.get("https://graph.microsoft.com/v1.0/me", headers=headers)
        email_address = user_info.json().get("mail", "") if user_info.status_code == 200 else ""

        # Store credentials with appropriate scopes
        creds_dict = {
            "access_token": result["access_token"],
            "refresh_token": result.get("refresh_token"),
            "email_address": email_address,
            "tenant_id": MICROSOFT_TENANT_ID,
            "client_id": MICROSOFT_CLIENT_ID,
            "client_secret": MICROSOFT_CLIENT_SECRET,
            "scopes": scopes
        }

        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        if service_type == "microsoft":
            # Email integration
            companies_col.update_one(
                {"_id": _id},
                {
                    "$set": {
                        "email_integration": {
                            "connected": True,
                            "provider": "microsoft",
                            "email_address": email_address,
                            "connection_type": "oauth",
                            "credentials": creds_dict,
                            "connected_at": datetime.datetime.utcnow().isoformat(),
                            "last_sync": None,
                            "sync_status": "connected",
                            "settings": {
                                "sync_folders": ["Inbox"],
                                "sync_since_days": 30,
                                "max_emails_per_sync": 100,
                                "include_attachments": False,
                                "skip_large_emails": True,
                                "max_email_size_mb": 10
                            },
                            "stats": {
                                "total_emails_synced": 0,
                                "last_sync_count": 0,
                                "errors_count": 0
                            }
                        }
                    }
                }
            )

            return """
            <html>
            <head><title>Microsoft Email Connected</title></head>
            <body>
                <h2>Microsoft Email Connected Successfully!</h2>
                <p>You can close this window and return to the application.</p>
                <script>
                    window.close();
                </script>
            </body>
            </html>
            """

        else:  # service_type == "onedrive"
            # OneDrive integration
            companies_col.update_one(
                {"_id": _id},
                {
                    "$set": {
                        "onedrive": {
                            "connected": True,
                            "email_address": email_address,
                            "connection_type": "oauth",
                            "credentials": creds_dict,
                            "connected_at": datetime.datetime.utcnow().isoformat(),
                            "last_sync": None,
                            "sync_status": "connected",
                            "folder_count": 0,
                            "file_count": 0,
                            "monitored_folders": []
                        }
                    }
                }
            )

            return """
            <html>
            <head><title>OneDrive Connected</title></head>
            <body>
                <h2>OneDrive Connected Successfully!</h2>
                <p>You can close this window and return to the application.</p>
                <script>
                    window.close();
                </script>
            </body>
            </html>
            """

    except Exception as e:
        logging.error(f"Error in Microsoft callback: {e}")
        return jsonify({"error": "Failed to complete authentication"}), 500

@app.route("/companies/<company_id>/email/sync", methods=["POST"])
@token_required
def sync_company_emails(company_id):
    """Manually sync emails for a company"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    if not EMAIL_PROVIDERS_AVAILABLE:
        return jsonify({"error": "Email providers not available"}), 500

    try:
        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        company = companies_col.find_one({"_id": _id})
        if not company:
            return jsonify({"error": "Company not found"}), 404

        email_config = company.get("email_integration")
        if not email_config or not email_config.get("connected"):
            return jsonify({"error": "Email not connected for this company"}), 400

        provider = email_config.get("provider")
        credentials = email_config.get("credentials")

        # Get email provider
        email_provider = get_email_provider(
            provider_type=provider,
            client_id=GOOGLE_CLIENT_ID if provider == "gmail" else MICROSOFT_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET if provider == "gmail" else MICROSOFT_CLIENT_SECRET,
            tenant_id=MICROSOFT_TENANT_ID if provider == "microsoft" else None,
            encryption_key=EMAIL_ENCRYPTION_KEY if provider == "generic" else None
        )

        # Authenticate
        auth_success, auth_error = email_provider.authenticate(credentials)
        if not auth_success:
            # Try to refresh credentials if authentication failed
            if provider in ["gmail", "microsoft"]:
                logging.info(f"Initial {provider} authentication failed, attempting to refresh credentials...")
                refresh_success, refresh_error, updated_credentials = email_provider.refresh_credentials(credentials)

                if refresh_success and updated_credentials != credentials:
                    # Update stored credentials
                    companies_col.update_one(
                        {"_id": _id},
                        {"$set": {"email_integration.credentials": updated_credentials}}
                    )

                    # Try authentication again with refreshed credentials
                    auth_success, auth_error = email_provider.authenticate(updated_credentials)

                    if not auth_success:
                        return jsonify({"error": f"Authentication failed after credential refresh: {auth_error}"}), 401
                else:
                    return jsonify({"error": f"Failed to refresh credentials: {refresh_error}"}), 401
            else:
                return jsonify({"error": f"Authentication failed: {auth_error}"}), 401

        # Calculate since date - keep emails from last 7 days
        since_date = datetime.datetime.utcnow() - datetime.timedelta(days=7)
        cutoff_date = datetime.datetime.utcnow() - datetime.timedelta(days=7)
        max_emails_per_sync = 200  # Increased limit

        # Delete old emails (older than 7 days)
        # First, get the IDs of old emails to delete
        old_emails = list(metadata_col.find({
            "company_id": company_id,
            "type": "email",
            "content.date": {"$lt": cutoff_date.isoformat()}
        }, {"_id": 1}))

        if old_emails:
            old_email_ids = [str(email["_id"]) for email in old_emails]
            app.logger.info(f"Deleting {len(old_email_ids)} old emails from LightRAG for company {company_id}...")

            # Delete from LightRAG FIRST
            lightrag_response = bulk_delete_company_documents(company_id, old_email_ids)
            if lightrag_response.get("status") == "completed":
                lightrag_result = lightrag_response.get("results", {})
                app.logger.info(
                    f"LightRAG cleanup: {lightrag_result.get('successful', 0)} successful, "
                    f"{lightrag_result.get('failed', 0)} failed"
                )

            # Then delete from MongoDB
            deleted_count = metadata_col.delete_many({
                "company_id": company_id,
                "type": "email",
                "content.date": {"$lt": cutoff_date.isoformat()}
            }).deleted_count

            app.logger.info(f"Deleted {deleted_count} old emails from MongoDB for company {company_id}")

        # Get sync settings for folders (but ignore other settings)
        settings = email_config.get("settings", {})
        sync_folders = settings.get("sync_folders", ["INBOX"])

        synced_count = 0

        # Sync each folder
        for folder in sync_folders:
            emails = email_provider.fetch_emails(folder, since_date, max_emails_per_sync)

            for email_data in emails:
                try:
                    # Check if email already exists
                    existing_email = metadata_col.find_one({
                        "company_id": company_id,
                        "type": "email",
                        "email_metadata.message_id": email_data["message_id"]
                    })

                    if existing_email:
                        continue

                    # Create email content for LightRAG
                    combined_content = f"Subject: {email_data['subject']}\nFrom: {email_data['sender']}\nTo: {email_data['recipients']}\nDate: {email_data['date'].isoformat()}\n\n{email_data['body_text']}"

                    # STEP 1: Create metadata document in MongoDB
                    now = datetime.datetime.utcnow().isoformat()
                    metadata_doc = {
                        "company_id": company_id,
                        "type": "email",
                        "source": "email",
                        "title": email_data["subject"],
                        "content": {
                            "subject": email_data["subject"],
                            "sender": email_data["sender"],
                            "recipients": email_data["recipients"],
                            "date": email_data["date"].isoformat(),
                            "body_text": email_data["body_text"]
                        },
                        "email_metadata": {
                            "message_id": email_data["message_id"],
                            "folder": email_data["folder"],
                            "provider": provider
                        },
                        "created_at": now,
                        "updated_at": now,
                        "rag_sync_status": "waiting"
                    }
                    app.logger.info(f"[RAG] Creating metadata for email '{email_data['subject']}' at {now}")

                    result = metadata_col.insert_one(metadata_doc)
                    mongodb_id = str(result.inserted_id)

                    # STEP 2: Check content size before RAG insertion
                    if len(combined_content) > MAX_RAG_CONTENT_LENGTH:
                        app.logger.warning(f"Email '{email_data['subject']}' too large ({len(combined_content)} chars, max {MAX_RAG_CONTENT_LENGTH})")
                        metadata_col.update_one(
                            {"_id": ObjectId(mongodb_id)},
                            {"$set": {"rag_sync_status": "too_large"}}
                        )
                    else:
                        # Enqueue for background RAG insertion
                        enqueue_rag_insertion(
                            company_id=company_id,
                            doc_id=mongodb_id,
                            content=combined_content,
                            metadata={
                                "source": "email",
                                "file_id": mongodb_id,
                                "message_id": email_data["message_id"],
                                "subject": email_data["subject"],
                                "sender": email_data["sender"],
                                "recipients": email_data["recipients"],
                                "cc": email_data["cc"],
                                "bcc": email_data["bcc"],
                                "date": email_data["date"].isoformat(),
                                "folder": email_data["folder"],
                                "provider": provider,
                                "updated_at": now
                            }
                        )
                    synced_count += 1

                except Exception as e:
                    app.logger.error(f"Error processing email for company {company_id}: {e}")
                    continue

        # If we have more than 200 emails total, keep only the newest 200
        total_emails = metadata_col.count_documents({
            "company_id": company_id,
            "type": "email"
        })

        if total_emails > max_emails_per_sync:
            # Get all emails sorted by date descending
            all_emails = list(metadata_col.find({
                "company_id": company_id,
                "type": "email"
            }).sort("content.date", -1))

            # Keep only the newest max_emails_per_sync emails
            emails_to_keep = all_emails[:max_emails_per_sync]
            emails_to_delete = all_emails[max_emails_per_sync:]

            # Delete the older emails
            if emails_to_delete:
                email_ids_to_delete = [email["_id"] for email in emails_to_delete]
                email_ids_str = [str(email_id) for email_id in email_ids_to_delete]

                app.logger.info(f"Deleting {len(email_ids_str)} excess emails from LightRAG for company {company_id}...")

                # Delete from LightRAG FIRST
                lightrag_response = bulk_delete_company_documents(company_id, email_ids_str)
                if lightrag_response.get("status") == "completed":
                    lightrag_result = lightrag_response.get("results", {})
                    app.logger.info(
                        f"LightRAG bulk delete: {lightrag_result.get('successful', 0)} successful, "
                        f"{lightrag_result.get('failed', 0)} failed"
                    )

                # Then delete from MongoDB
                deleted_excess = metadata_col.delete_many({
                    "_id": {"$in": email_ids_to_delete}
                }).deleted_count

                app.logger.info(f"Deleted {deleted_excess} excess emails from MongoDB to maintain limit of {max_emails_per_sync} for company {company_id}")

        # Disconnect from email provider
        email_provider.disconnect()

        # Update company's email sync status
        companies_col.update_one(
            {"_id": _id},
            {
                "$set": {
                    "email_integration.last_sync": datetime.datetime.utcnow().isoformat(),
                    "email_integration.sync_status": "success",
                    "email_integration.stats.total_emails_synced":
                        email_config.get("stats", {}).get("total_emails_synced", 0) + synced_count,
                    "email_integration.stats.last_sync_count": synced_count
                }
            }
        )

        return jsonify({
            "message": f"Successfully synced {synced_count} emails",
            "emails_synced": synced_count
        }), 200

    except Exception as e:
        logging.error(f"Error syncing emails for company {company_id}: {e}")

        # Update sync status to error
        companies_col.update_one(
            {"_id": oid(company_id)},
            {
                "$set": {
                    "email_integration.sync_status": "error",
                    "email_integration.last_error": str(e),
                    "email_integration.last_error_time": datetime.datetime.utcnow().isoformat()
                }
            }
        )

        return jsonify({"error": f"Failed to sync emails: {str(e)}"}), 500

@app.route("/companies/<company_id>/email/disconnect", methods=["POST"])
@token_required
def disconnect_company_email(company_id):
    """Disconnect email for a company"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        data = request.get_json(force=True) or {}
        remove_synced_emails = data.get("remove_synced_emails", False)

        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        # Remove email integration from company
        companies_col.update_one(
            {"_id": _id},
            {"$unset": {"email_integration": ""}}
        )

        # Optionally remove synced emails
        if remove_synced_emails:
            # First get the document IDs
            docs = list(metadata_col.find(
                {"company_id": company_id, "type": "email"},
                {"_id": 1}
            ))
            doc_ids = [str(doc["_id"]) for doc in docs]

            # Delete from LightRAG first
            if doc_ids:
                bulk_delete_company_documents(company_id, doc_ids)

            # Then delete from MongoDB
            result = metadata_col.delete_many({
                "company_id": company_id,
                "type": "email"
            })
            return jsonify({
                "message": "Email disconnected and synced emails removed",
                "emails_removed": result.deleted_count
            }), 200

        return jsonify({"message": "Email disconnected successfully"}), 200

    except Exception as e:
        logging.error(f"Error disconnecting email for company {company_id}: {e}")
        return jsonify({"error": "Failed to disconnect email"}), 500

@app.route("/companies/<company_id>/email/folders", methods=["GET"])
@token_required
def get_email_folders(company_id):
    """Get available email folders for a company"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    if not EMAIL_PROVIDERS_AVAILABLE:
        return jsonify({"error": "Email providers not available"}), 500

    try:
        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        company = companies_col.find_one({"_id": _id})
        if not company:
            return jsonify({"error": "Company not found"}), 404

        email_config = company.get("email_integration")
        if not email_config or not email_config.get("connected"):
            return jsonify({"error": "Email not connected for this company"}), 400

        provider = email_config.get("provider")
        credentials = email_config.get("credentials")

        # Get email provider
        email_provider = get_email_provider(
            provider_type=provider,
            client_id=GOOGLE_CLIENT_ID if provider == "gmail" else MICROSOFT_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET if provider == "gmail" else MICROSOFT_CLIENT_SECRET,
            tenant_id=MICROSOFT_TENANT_ID if provider == "microsoft" else None,
            encryption_key=EMAIL_ENCRYPTION_KEY if provider == "generic" else None
        )

        # Authenticate and get folders
        auth_success, auth_error = email_provider.authenticate(credentials)
        if not auth_success:
            return jsonify({"error": f"Authentication failed: {auth_error}"}), 401

        folders = email_provider.get_folders()
        email_provider.disconnect()

        return jsonify({"folders": folders}), 200

    except Exception as e:
        logging.error(f"Error getting email folders for company {company_id}: {e}")
        return jsonify({"error": "Failed to get email folders"}), 500

@app.route("/companies/<company_id>/email/settings", methods=["GET", "PUT"])
@token_required
def handle_email_settings(company_id):
    """Get or update email settings for a company"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        if request.method == "GET":
            company = companies_col.find_one({"_id": _id})
            if not company:
                return jsonify({"error": "Company not found"}), 404

            email_config = company.get("email_integration", {})
            settings = email_config.get("settings", {})

            return jsonify({"settings": settings}), 200

        elif request.method == "PUT":
            data = request.get_json(force=True)
            settings = data.get("settings", {})

            # Validate settings
            if "sync_folders" in settings and not isinstance(settings["sync_folders"], list):
                return jsonify({"error": "sync_folders must be a list"}), 400

            # Update settings
            companies_col.update_one(
                {"_id": _id},
                {"$set": {"email_integration.settings": settings}}
            )

            return jsonify({"message": "Email settings updated successfully"}), 200

    except Exception as e:
        logging.error(f"Error handling email settings for company {company_id}: {e}")
        return jsonify({"error": "Failed to handle email settings"}), 500

# ─── OneDrive Integration ─────────────────────────────────────────────────────
@app.route("/companies/<company_id>/onedrive/auth", methods=["POST"])
@token_required
def initiate_onedrive_auth(company_id):
    """Initiate OneDrive OAuth flow for a company"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        import msal

        app_instance = msal.ConfidentialClientApplication(
            MICROSOFT_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}",
            client_credential=MICROSOFT_CLIENT_SECRET
        )

        # Include company_id and service type in state
        state = f"{company_id}|onedrive"

        auth_url = app_instance.get_authorization_request_url(
            scopes=MICROSOFT_ONEDRIVE_SCOPES,
            state=state,
            redirect_uri=MICROSOFT_REDIRECT_URI
        )

        return jsonify({"auth_url": auth_url}), 200

    except Exception as e:
        logging.error(f"Error initiating OneDrive auth for company {company_id}: {e}")
        return jsonify({"error": "Failed to initiate OneDrive authentication"}), 500

@app.route("/companies/<company_id>/onedrive/sync", methods=["POST"])
@token_required
def sync_onedrive(company_id):
    """Manually sync OneDrive files for a company with extensive debug logging"""
    app.logger.info(f"=== Starting OneDrive sync for company {company_id} ===")

    if not is_admin():
        if claim_company_id() != company_id:
            app.logger.warning(f"Access denied: User tried to sync OneDrive for company {company_id}")
            return jsonify({"error": "Forbidden"}), 403

    try:
        _id = oid(company_id)
        if not _id:
            app.logger.error(f"Invalid company ID format: {company_id}")
            return jsonify({"error": "Invalid company ID"}), 400

        # Get company and check OneDrive connection
        company = companies_col.find_one({"_id": _id})
        if not company:
            app.logger.error(f"Company not found: {company_id}")
            return jsonify({"error": "Company not found"}), 404

        app.logger.info(f"Found company: {company.get('name', 'Unknown')}")

        onedrive_config = company.get("onedrive", {})
        app.logger.info(f"OneDrive config found: {onedrive_config.keys() if onedrive_config else 'None'}")

        if not onedrive_config.get("connected"):
            app.logger.error(f"OneDrive not connected for company {company_id}")
            return jsonify({"error": "OneDrive not connected"}), 400

        # Check if folders are selected
        monitored_folders = onedrive_config.get("monitored_folders", [])
        app.logger.info(f"Monitored folders: {monitored_folders} (count: {len(monitored_folders)})")

        if not monitored_folders:
            app.logger.warning(f"No folders selected for monitoring in company {company_id}")
            return jsonify({
                "error": "No folders selected for monitoring",
                "requires_folder_selection": True
            }), 400

        creds_dict = onedrive_config.get("credentials")
        if not creds_dict:
            app.logger.error(f"No OneDrive credentials found for company {company_id}")
            return jsonify({"error": "No OneDrive credentials found"}), 400

        app.logger.info(f"Credentials available: {list(creds_dict.keys()) if creds_dict else 'None'}")

        access_token = creds_dict.get("access_token")
        if not access_token:
            app.logger.error(f"No access token found in credentials for company {company_id}")
            return jsonify({"error": "No access token found"}), 400


        headers = {"Authorization": f"Bearer {access_token}"}

        # VALIDATION: Check total file count before starting sync
        total_file_count = 0
        for folder_id in monitored_folders:
            try:
                files_url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children"
                files_response = requests.get(files_url, headers=headers)

                if files_response.status_code == 401:
                    # Token expired, try to refresh
                    success, error = refresh_microsoft_credentials(creds_dict, company_id, _id)
                    if success:
                        updated_company = companies_col.find_one({"_id": _id})
                        updated_creds = updated_company.get("onedrive", {}).get("credentials", {})
                        access_token = updated_creds.get("access_token")
                        headers = {"Authorization": f"Bearer {access_token}"}
                        files_response = requests.get(files_url, headers=headers)
                    else:
                        return jsonify({"error": f"Failed to refresh credentials: {error}"}), 401

                if files_response.status_code == 200:
                    files_data = files_response.json()
                    files = files_data.get("value", [])
                    # Count only files, not folders
                    file_count = sum(1 for item in files if "file" in item)
                    total_file_count += file_count

                    # Early exit if we exceed threshold
                    if total_file_count > 100:
                        break
            except Exception as e:
                app.logger.warning(f"Error counting files in folder {folder_id}: {e}")

        # If file count exceeds threshold, return error
        if total_file_count > 100:
            return jsonify({
                "error": f"Too many files selected for sync. The selected folders contain {total_file_count} files. Please reduce the number of selected folders (maximum 100 files recommended).",
                "validation_error": "too_many_files",
                "file_count": total_file_count
            }), 400

        synced_count = 0
        total_files_found = 0
        processed_folders = 0

        # Process each monitored folder
        for folder_index, folder_id in enumerate(monitored_folders, 1):
            app.logger.info(f"=== Processing folder {folder_index}/{len(monitored_folders)}: {folder_id} ===")

            try:
                # Get files from this folder
                files_url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children"
                app.logger.info(f"Requesting files from URL: {files_url}")

                files_response = requests.get(files_url, headers=headers)
                app.logger.info(f"API Response status: {files_response.status_code}")

                if files_response.status_code == 401:
                    app.logger.warning(f"Token expired for folder {folder_id}, attempting to refresh")
                    # Token expired, try to refresh
                    success, error = refresh_microsoft_credentials(creds_dict, company_id, _id)
                    if success:
                        app.logger.info("Successfully refreshed credentials")
                        # Update headers with new token
                        updated_company = companies_col.find_one({"_id": _id})
                        updated_creds = updated_company.get("onedrive", {}).get("credentials", {})
                        access_token = updated_creds.get("access_token")
                        headers = {"Authorization": f"Bearer {access_token}"}
                        # Retry the request
                        files_response = requests.get(files_url, headers=headers)
                        app.logger.info(f"Retry API Response status: {files_response.status_code}")
                    else:
                        app.logger.error(f"Failed to refresh credentials: {error}")
                        return jsonify({"error": f"Failed to refresh credentials: {error}"}), 401

                if files_response.status_code != 200:
                    app.logger.error(f"Error accessing OneDrive folder {folder_id}: {files_response.status_code}")
                    app.logger.error(f"Response content: {files_response.text}")
                    continue

                try:
                    files_data = files_response.json()
                except Exception as json_error:
                    app.logger.error(f"Failed to parse JSON response for folder {folder_id}: {json_error}")
                    app.logger.error(f"Raw response: {files_response.text}")
                    continue

                files = files_data.get("value", [])
                app.logger.info(f"Found {len(files)} items in folder {folder_id}")
                total_files_found += len(files)

                # Log details about each item found
                for i, item in enumerate(files):
                    item_type = "folder" if "folder" in item else "file"
                    item_name = item.get('name', 'Unknown')
                    app.logger.info(f"  Item {i+1}: {item_name} (type: {item_type})")

                # Process each file
                file_count_in_folder = 0
                for file_info in files:
                    try:
                        # Skip folders
                        if "folder" in file_info:
                            app.logger.debug(f"Skipping folder: {file_info.get('name', 'Unknown')}")
                            continue

                        file_count_in_folder += 1
                        file_id = file_info['id']
                        file_name = file_info['name']
                        modified_time = file_info['lastModifiedDateTime']
                        file_size = file_info.get('size', 0)

                        app.logger.info(f"Processing file: {file_name} (ID: {file_id}, Size: {file_size} bytes)")

                        # Check if this file already exists and is up to date
                        existing = metadata_col.find_one({
                            "company_id": company_id,
                            "type": "onedrive_file",
                            "content.file_id": file_id
                        })

                        if existing and existing.get("content", {}).get("modified_time") == modified_time:
                            app.logger.info(f"File {file_name} already up to date, skipping")
                            continue  # File hasn't changed, skip

                        app.logger.info(f"File {file_name} is new or modified, downloading content...")

                        # Download and extract content
                        content_text = download_and_extract_onedrive_content(file_info, headers)
                        if not content_text:
                            app.logger.warning(f"No content extracted from file {file_name}")
                            continue

                        app.logger.info(f"Extracted {len(content_text)} characters from {file_name}")

                        # STEP 1: Create/update metadata document in MongoDB
                        now = datetime.datetime.utcnow().isoformat()

                        if existing:
                            # Update existing document
                            mongodb_id = str(existing["_id"])
                            metadata_col.update_one(
                                {"_id": existing["_id"]},
                                        {
                                            "$set": {
                                                "content": {
                                                    "full_content": content_text,
                                                    "file_id": file_id,
                                                    "file_name": file_name,
                                                    "modified_time": modified_time
                                                },
                                                "text_length": len(content_text),
                                                "updated_at": now,
                                                "rag_sync_status": "waiting"
                                            }
                                        }
                                    )
                            app.logger.info(f"[RAG] Queuing OneDrive file update {file_name} for RAG insertion at {now}")
                        else:
                            # Create new metadata document
                            metadata_doc = {
                                "company_id": company_id,
                                    "type": "onedrive_file",
                                    "source": "onedrive",
                                    "title": file_name,
                                    "content": {
                                        "full_content": content_text,
                                        "file_id": file_id,
                                        "file_name": file_name,
                                        "modified_time": modified_time
                                    },
                                    "text_length": len(content_text),
                                    "created_at": now,
                                    "updated_at": now,
                                    "rag_sync_status": "waiting"
                                }
                            app.logger.info(f"[RAG] Queuing OneDrive file {file_name} for RAG insertion at {now}")
                            result = metadata_col.insert_one(metadata_doc)
                            mongodb_id = str(result.inserted_id)

                        # STEP 2: Check content size before RAG insertion
                        if len(content_text) > MAX_RAG_CONTENT_LENGTH:
                            app.logger.warning(f"OneDrive file {file_name} too large ({len(content_text)} chars, max {MAX_RAG_CONTENT_LENGTH})")
                            metadata_col.update_one(
                                {"_id": ObjectId(mongodb_id)},
                                {"$set": {"rag_sync_status": "too_large"}}
                            )
                        else:
                            # Enqueue for background RAG insertion
                            enqueue_rag_insertion(
                                company_id=company_id,
                                doc_id=mongodb_id,
                                content=content_text,
                                metadata={
                                    "source": "onedrive",
                                    "file_id": mongodb_id,
                                    "file_name": file_name,
                                    "modified_time": modified_time,
                                    "folder_id": folder_id,
                                    "file_size": file_size,
                                    "updated_at": now
                                }
                            )
                            app.logger.info(f"Enqueued RAG insertion for {file_name} (total synced: {synced_count})")
                        synced_count += 1

                    except Exception as e:
                        app.logger.error(f"Error processing OneDrive file {file_info.get('name', 'unknown')}: {e}")
                        app.logger.exception("Full stack trace:")
                        continue

                app.logger.info(f"Completed folder {folder_id}: {file_count_in_folder} files found")
                processed_folders += 1

            except Exception as e:
                app.logger.error(f"Error accessing OneDrive folder {folder_id}: {e}")
                app.logger.exception("Full stack trace:")
                continue

        # Calculate final file count
        total_onedrive_files = metadata_col.count_documents({
            "company_id": company_id,
            "type": "onedrive_file"
        })

        app.logger.info(f"=== OneDrive sync summary ===")
        app.logger.info(f"Processed folders: {processed_folders}/{len(monitored_folders)}")
        app.logger.info(f"Total items found: {total_files_found}")
        app.logger.info(f"Files synced this run: {synced_count}")
        app.logger.info(f"Total OneDrive files in database: {total_onedrive_files}")

        # Update company's OneDrive sync status
        companies_col.update_one(
            {"_id": _id},
            {
                "$set": {
                    "onedrive.last_sync": datetime.datetime.utcnow().isoformat(),
                    "onedrive.sync_status": "success",
                    "onedrive.file_count": total_onedrive_files,
                    "onedrive.last_sync_count": synced_count
                }
            }
        )

        app.logger.info(f"=== OneDrive sync completed for company {company_id} ===")

        return jsonify({
            "message": f"OneDrive sync completed successfully. Synced {synced_count} files.",
            "files_synced": synced_count,
            "total_files": total_onedrive_files,
            "processed_folders": processed_folders,
            "total_items_found": total_files_found
        }), 200

    except Exception as e:
        app.logger.error(f"Fatal error syncing OneDrive for company {company_id}: {e}")
        app.logger.exception("Full stack trace:")
        return jsonify({"error": "Failed to sync OneDrive"}), 500

@app.route("/companies/<company_id>/onedrive/disconnect", methods=["POST"])
@token_required
def disconnect_onedrive(company_id):
    """Disconnect OneDrive from a company"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        data = request.get_json(force=True)
        remove_synced_files = data.get("remove_synced_files", False)

        # Remove synced files if requested
        if remove_synced_files:
            # First get the document IDs
            docs = list(metadata_col.find(
                {"company_id": company_id, "type": "onedrive_file"},
                {"_id": 1}
            ))
            doc_ids = [str(doc["_id"]) for doc in docs]

            # Delete from LightRAG first
            if doc_ids:
                bulk_delete_company_documents(company_id, doc_ids)

            # Then delete from MongoDB
            result = metadata_col.delete_many({
                "company_id": company_id,
                "type": "onedrive_file"
            })
            app.logger.info(f"Removed {result.deleted_count} OneDrive files for company {company_id}")

        # Remove OneDrive connection
        companies_col.update_one(
            {"_id": _id},
            {"$unset": {"onedrive": ""}}
        )

        response_data = {
            "message": "OneDrive disconnected successfully"
        }
        if remove_synced_files:
            response_data["removed_files"] = result.deleted_count

        return jsonify(response_data), 200

    except Exception as e:
        app.logger.error(f"Error disconnecting OneDrive for company {company_id}: {e}")
        return jsonify({"error": "Failed to disconnect OneDrive"}), 500

@app.route("/companies/<company_id>/onedrive/debug", methods=["GET"])
@token_required
def debug_onedrive_connection(company_id):
    """Debug OneDrive connection for troubleshooting"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        # Get company and check OneDrive connection
        company = companies_col.find_one({"_id": _id})
        if not company:
            return jsonify({"error": "Company not found"}), 404

        onedrive_config = company.get("onedrive", {})
        debug_info = {
            "onedrive_connected": onedrive_config.get("connected", False),
            "has_credentials": bool(onedrive_config.get("credentials")),
            "connection_type": onedrive_config.get("connection_type"),
            "connected_at": onedrive_config.get("connected_at"),
            "last_sync": onedrive_config.get("last_sync"),
            "sync_status": onedrive_config.get("sync_status"),
        }

        if not onedrive_config.get("connected"):
            debug_info["error"] = "OneDrive not connected"
            return jsonify(debug_info), 200

        creds_dict = onedrive_config.get("credentials")
        if not creds_dict:
            debug_info["error"] = "No OneDrive credentials found"
            return jsonify(debug_info), 200

        # Check credential structure
        debug_info["credential_fields"] = list(creds_dict.keys())
        debug_info["has_access_token"] = bool(creds_dict.get("access_token"))
        debug_info["has_refresh_token"] = bool(creds_dict.get("refresh_token"))
        debug_info["scopes"] = creds_dict.get("scopes", [])

        access_token = creds_dict.get("access_token")
        if not access_token:
            debug_info["error"] = "No access token found"
            return jsonify(debug_info), 200

        headers = {"Authorization": f"Bearer {access_token}"}

        # Test various Microsoft Graph API endpoints
        test_endpoints = [
            ("me", "https://graph.microsoft.com/v1.0/me"),
            ("drive", "https://graph.microsoft.com/v1.0/me/drive"),
            ("drive_root", "https://graph.microsoft.com/v1.0/me/drive/root"),
            ("drive_children", "https://graph.microsoft.com/v1.0/me/drive/root/children")
        ]

        test_results = {}
        for name, url in test_endpoints:
            try:
                response = requests.get(url, headers=headers)
                test_results[name] = {
                    "status_code": response.status_code,
                    "success": response.status_code == 200,
                    "response_size": len(response.text),
                    "error": response.text if response.status_code != 200 else None
                }

                if response.status_code == 200 and name == "drive_children":
                    data = response.json()
                    items = data.get("value", [])
                    folders = [item for item in items if "folder" in item]
                    test_results[name]["item_count"] = len(items)
                    test_results[name]["folder_count"] = len(folders)
                    test_results[name]["folder_names"] = [folder["name"] for folder in folders[:5]]  # First 5 folder names

            except Exception as e:
                test_results[name] = {
                    "error": str(e),
                    "success": False
                }

        debug_info["api_tests"] = test_results
        return jsonify(debug_info), 200

    except Exception as e:
        app.logger.error(f"Error debugging OneDrive for company {company_id}: {e}")
        return jsonify({"error": f"Debug failed: {str(e)}"}), 500

@app.route("/companies/<company_id>/onedrive/folders", methods=["GET"])
@token_required
def get_onedrive_folders(company_id):
    """Get available OneDrive folders for selection"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        # Get company and check OneDrive connection
        company = companies_col.find_one({"_id": _id})
        if not company:
            return jsonify({"error": "Company not found"}), 404

        onedrive_config = company.get("onedrive", {})
        if not onedrive_config.get("connected"):
            return jsonify({"error": "OneDrive not connected"}), 400

        creds_dict = onedrive_config.get("credentials")
        if not creds_dict:
            return jsonify({"error": "No OneDrive credentials found"}), 400

        access_token = creds_dict.get("access_token")
        if not access_token:
            app.logger.error(f"No access token found for company {company_id}. Credentials: {list(creds_dict.keys())}")
            return jsonify({"error": "No access token found"}), 400

        headers = {"Authorization": f"Bearer {access_token}"}
        app.logger.info(f"Getting OneDrive folders for company {company_id}")

        # Test the initial connection with a simple request to the root drive
        test_url = "https://graph.microsoft.com/v1.0/me/drive"
        test_response = requests.get(test_url, headers=headers)
        app.logger.info(f"OneDrive test connection response: {test_response.status_code}")

        if test_response.status_code == 401:
            app.logger.info("Access token expired, attempting to refresh...")
            # Token expired, try to refresh
            success, error = refresh_microsoft_credentials(creds_dict, company_id, _id)
            if success:
                # Update headers with new token
                updated_company = companies_col.find_one({"_id": _id})
                updated_creds = updated_company.get("onedrive", {}).get("credentials", {})
                access_token = updated_creds.get("access_token")
                headers = {"Authorization": f"Bearer {access_token}"}
                # Retry the test request
                test_response = requests.get(test_url, headers=headers)
                app.logger.info(f"OneDrive test connection response after refresh: {test_response.status_code}")
            else:
                app.logger.error(f"Failed to refresh OneDrive credentials: {error}")
                return jsonify({"error": f"Failed to refresh credentials: {error}"}), 401

        if test_response.status_code != 200:
            app.logger.error(f"OneDrive connection test failed: {test_response.status_code} - {test_response.text}")
            return jsonify({"error": f"OneDrive connection failed: {test_response.status_code}"}), 400

        # Get all folders from OneDrive root
        def get_folders_recursive(folder_id="root", path="", level=0):
            nonlocal headers  # Allow access to the outer scope headers variable
            if level > 5:  # Prevent infinite recursion
                return []

            folders = []
            try:
                if folder_id == "root":
                    url = "https://graph.microsoft.com/v1.0/me/drive/root/children"
                else:
                    url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children"

                app.logger.debug(f"Requesting OneDrive folder: {url}")
                response = requests.get(url, headers=headers)
                app.logger.debug(f"OneDrive folder response: {response.status_code}")

                if response.status_code == 401:
                    # Token expired, try to refresh
                    app.logger.info("Token expired during folder listing, refreshing...")
                    success, error = refresh_microsoft_credentials(creds_dict, company_id, _id)
                    if success:
                        # Update headers with new token
                        updated_company = companies_col.find_one({"_id": _id})
                        updated_creds = updated_company.get("onedrive", {}).get("credentials", {})
                        access_token = updated_creds.get("access_token")
                        headers = {"Authorization": f"Bearer {access_token}"}
                        # Retry the request
                        response = requests.get(url, headers=headers)
                        app.logger.debug(f"OneDrive folder response after refresh: {response.status_code}")

                if response.status_code != 200:
                    app.logger.warning(f"Failed to get OneDrive folder {folder_id}: {response.status_code} - {response.text}")
                    return folders

                try:
                    response_data = response.json()
                    items = response_data.get("value", [])
                    app.logger.debug(f"Found {len(items)} items in folder {folder_id}")
                except Exception as json_error:
                    app.logger.error(f"Failed to parse OneDrive response JSON: {json_error}")
                    return folders

                for item in items:
                    if "folder" in item:  # This is a folder
                        folder_path = f"{path}/{item['name']}" if path else item['name']
                        folder_info = {
                            "id": item["id"],
                            "name": item["name"],
                            "path": folder_path,
                            "modified_time": item.get("lastModifiedDateTime", ""),
                            "parent_id": folder_id if folder_id != "root" else None
                        }
                        folders.append(folder_info)
                        app.logger.debug(f"Found folder: {item['name']} (ID: {item['id']})")

                        # Recursively get subfolders
                        subfolders = get_folders_recursive(item["id"], folder_path, level + 1)
                        folders.extend(subfolders)

            except requests.RequestException as req_error:
                app.logger.error(f"Request error getting OneDrive folders: {req_error}")
            except Exception as e:
                app.logger.error(f"Error getting OneDrive folders: {e}")

            return folders

        folders = get_folders_recursive()
        app.logger.info(f"Total OneDrive folders found: {len(folders)}")

        # Get currently monitored folders
        monitored_folders = onedrive_config.get("monitored_folders", [])

        return jsonify({
            "folders": folders,
            "monitored_folders": monitored_folders
        }), 200

    except Exception as e:
        app.logger.error(f"Error getting OneDrive folders for company {company_id}: {e}")
        return jsonify({"error": "Failed to get OneDrive folders"}), 500

@app.route("/companies/<company_id>/onedrive/folders/children", methods=["GET"])
@token_required
def get_onedrive_folder_children(company_id):
    """Get children folders of a specific OneDrive folder (or root folders if parent_id not provided)"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        # Get company and check OneDrive connection
        company = companies_col.find_one({"_id": _id})
        if not company:
            return jsonify({"error": "Company not found"}), 404

        onedrive_config = company.get("onedrive", {})
        if not onedrive_config.get("connected"):
            return jsonify({"error": "OneDrive not connected"}), 400

        creds_dict = onedrive_config.get("credentials")
        if not creds_dict:
            return jsonify({"error": "No OneDrive credentials found"}), 400

        access_token = creds_dict.get("access_token")
        if not access_token:
            return jsonify({"error": "No access token found"}), 400

        # Get parent_id from query params
        parent_id = request.args.get("parent_id", None)

        headers = {"Authorization": f"Bearer {access_token}"}

        # Build URL based on parent_id
        if not parent_id or parent_id == "null":
            # Get root folders
            url = "https://graph.microsoft.com/v1.0/me/drive/root/children"
        else:
            # Get children of specific folder
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{parent_id}/children"

        app.logger.info(f"Fetching OneDrive folder children from: {url}")
        response = requests.get(url, headers=headers)

        if response.status_code == 401:
            # Token expired, try to refresh
            app.logger.info("Access token expired, attempting to refresh...")
            success, error = refresh_microsoft_credentials(creds_dict, company_id, _id)
            if success:
                # Update headers with new token
                updated_company = companies_col.find_one({"_id": _id})
                updated_creds = updated_company.get("onedrive", {}).get("credentials", {})
                access_token = updated_creds.get("access_token")
                headers = {"Authorization": f"Bearer {access_token}"}
                # Retry the request
                response = requests.get(url, headers=headers)
            else:
                return jsonify({"error": f"Failed to refresh credentials: {error}"}), 401

        if response.status_code != 200:
            app.logger.error(f"OneDrive API error: {response.status_code} - {response.text}")
            return jsonify({"error": f"OneDrive API error: {response.status_code}"}), 500

        response_data = response.json()
        items = response_data.get("value", [])

        # Filter to only include folders
        folders = []
        for item in items:
            if "folder" in item:  # This is a folder
                folder_info = {
                    "id": item["id"],
                    "name": item["name"],
                    "modified_time": item.get("lastModifiedDateTime", ""),
                    "created_time": item.get("createdDateTime", ""),
                    "parent_id": parent_id if parent_id and parent_id != "null" else None,
                    "has_children": item.get("folder", {}).get("childCount", 0) > 0
                }
                folders.append(folder_info)

        # Sort folders alphabetically
        folders.sort(key=lambda f: f["name"].lower())

        # Get folders_to_expand and monitored_folders data for the response
        onedrive_config = company.get("onedrive", {})
        monitored_folders = onedrive_config.get("monitored_folders", [])
        folders_to_expand = onedrive_config.get("folders_to_expand", {})
        parent_chains = onedrive_config.get("parent_chains", {})

        return jsonify({
            "folders": folders,
            "parent_id": parent_id,
            "monitored_folders": monitored_folders,
            "folders_to_expand": folders_to_expand,
            "parent_chains": parent_chains
        }), 200

    except Exception as e:
        app.logger.error(f"Error getting OneDrive folder children for company {company_id}: {e}")
        return jsonify({"error": "Failed to get OneDrive folder children"}), 500

@app.route("/companies/<company_id>/onedrive/folders", methods=["PUT"])
@token_required
def update_monitored_onedrive_folders(company_id):
    """Update which OneDrive folders to monitor"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        data = request.get_json(force=True)
        folder_ids = data.get("folder_ids", [])

        if not isinstance(folder_ids, list):
            return jsonify({"error": "folder_ids must be a list"}), 400

        # VALIDATION: At least 1 folder must be selected
        if len(folder_ids) == 0:
            return jsonify({
                "error": "At least one folder must be selected for monitoring",
                "validation_error": "min_folders"
            }), 400

        # VALIDATION: Maximum 10 folders can be selected
        if len(folder_ids) > 10:
            return jsonify({
                "error": f"Maximum 10 folders can be selected. You have selected {len(folder_ids)} folders.",
                "validation_error": "max_folders",
                "folder_count": len(folder_ids)
            }), 400

        # Get current monitored folders to check for removals
        company = companies_col.find_one({"_id": _id})
        if not company:
            return jsonify({"error": "Company not found"}), 404

        current_folders = company.get("onedrive", {}).get("monitored_folders", [])
        removed_folders = set(current_folders) - set(folder_ids)

        # Remove files from unselected folders
        removed_files_count = 0
        if removed_folders:
            for folder_id in removed_folders:
                result = metadata_col.delete_many({
                    "company_id": company_id,
                    "type": "onedrive_file",
                    "content.folder_id": folder_id
                })
                removed_files_count += result.deleted_count

        # Compute folders_to_expand information for frontend
        folders_to_expand_data = None
        try:
            # Get OneDrive credentials and build headers
            onedrive_config = company.get("onedrive", {})
            if onedrive_config and onedrive_config.get("connected"):
                creds_dict = onedrive_config.get("credentials", {})
                access_token = creds_dict.get("access_token")

                if not access_token:
                    # Try to refresh credentials
                    success, error = refresh_microsoft_credentials(creds_dict, company_id, _id)
                    if success:
                        # Get fresh credentials after refresh
                        company = companies_col.find_one({"_id": _id})
                        creds_dict = company.get("onedrive", {}).get("credentials", {})
                        access_token = creds_dict.get("access_token")

                if access_token:
                    headers = {
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json"
                    }
                    folders_to_expand_data = compute_folders_to_expand_onedrive(headers, folder_ids)
                    app.logger.info(f"Computed folders_to_expand for OneDrive: {folders_to_expand_data}")
        except Exception as e:
            app.logger.error(f"Error computing folders_to_expand for OneDrive: {e}")
            # Continue even if this fails - frontend can fall back to basic behavior

        # Update monitored folders and folders_to_expand data
        update_data = {
            "onedrive.monitored_folders": folder_ids,
            "onedrive.folder_count": len(folder_ids)
        }

        if folders_to_expand_data:
            update_data["onedrive.folders_to_expand"] = folders_to_expand_data["folders_to_expand"]
            update_data["onedrive.parent_chains"] = folders_to_expand_data["parent_chains"]

        # Update monitored folders
        companies_col.update_one(
            {"_id": _id},
            {"$set": update_data}
        )

        response_data = {
            "message": f"OneDrive folder selection updated. Monitoring {len(folder_ids)} folders.",
            "monitored_folders": folder_ids
        }

        if removed_files_count > 0:
            response_data["removed_files"] = removed_files_count

        return jsonify(response_data), 200

    except Exception as e:
        app.logger.error(f"Error updating OneDrive folder selection for company {company_id}: {e}")
        return jsonify({"error": "Failed to update folder selection"}), 500

# ─── Manual File Upload ──────────────────────────────────────────────────────
@app.route("/companies/<company_id>/files/upload", methods=["POST"])
@token_required
def upload_files(company_id):
    """Upload and process files for a company"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        _id = oid(company_id)
        if not _id:
            return jsonify({"error": "Invalid company ID"}), 400

        company = companies_col.find_one({"_id": _id})
        if not company:
            return jsonify({"error": "Company not found"}), 404

        # Check if files were uploaded
        if 'files' not in request.files:
            return jsonify({"error": "No files uploaded"}), 400

        files = request.files.getlist('files')
        if not files or len(files) == 0:
            return jsonify({"error": "No files selected"}), 400

        processed_files = []
        skipped_files = []
        total_submitted = len(files)

        supported_extensions = {
            '.txt': 'text/plain',
            '.csv': 'text/csv',
            '.pdf': 'application/pdf',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
        }

        for file in files:
            if file.filename == '':
                skipped_files.append({"filename": "unnamed", "reason": "Empty filename"})
                continue

            # Get file extension
            filename = file.filename.lower()
            file_ext = None
            for ext in supported_extensions:
                if filename.endswith(ext):
                    file_ext = ext
                    break

            if not file_ext:
                app.logger.warning(f"Unsupported file type: {filename}")
                skipped_files.append({"filename": file.filename, "reason": "Unsupported file type"})
                continue

            # Read file content
            file_content = file.read()
            if not file_content:
                app.logger.warning(f"Empty file: {filename}")
                skipped_files.append({"filename": file.filename, "reason": "Empty file"})
                continue

            # Check individual file size (additional check beyond Flask's MAX_CONTENT_LENGTH)
            individual_file_limit = 25 * 1024 * 1024  # 25MB per file
            if len(file_content) > individual_file_limit:
                app.logger.warning(f"File too large: {filename} ({len(file_content)} bytes)")
                skipped_files.append({"filename": file.filename, "reason": f"File too large ({len(file_content)} bytes, max 25MB)"})
                continue

            # Extract text content based on file type
            content = ""
            mime_type = supported_extensions[file_ext]

            try:
                if file_ext == '.txt':
                    content = file_content.decode('utf-8', errors='ignore')
                elif file_ext == '.csv':
                    content = file_content.decode('utf-8', errors='ignore')
                elif file_ext == '.pdf':
                    content = extract_pdf_text(file_content)
                elif file_ext == '.docx':
                    content = extract_docx_text(file_content)
                elif file_ext == '.xlsx':
                    content = extract_xlsx_text(file_content)
                elif file_ext == '.pptx':
                    content = extract_pptx_text(file_content)

                if content and content.strip():
                    # STEP 1: Create MongoDB metadata document first with RAG status
                    now = datetime.datetime.utcnow().isoformat()
                    metadata_doc = {
                        "company_id": company_id,
                        "type": "manual_upload_file",
                        "source": "manual_file_upload",
                        "title": file.filename,
                        "content": {
                            "full_content": content
                        },
                        "text_length": len(content),
                        "file_metadata": {
                            "file_name": file.filename,
                            "file_size": len(file_content),
                            "mime_type": mime_type,
                            "file_extension": file_ext
                        },
                        "created_at": now,
                        "updated_at": now,
                        "rag_sync_status": "waiting"
                    }
                    app.logger.info(f"[RAG] Queuing manual file upload {file.filename} for RAG insertion at {now}")

                    # Insert into MongoDB first to get an _id
                    result = metadata_col.insert_one(metadata_doc)
                    mongodb_id = str(result.inserted_id)
                    app.logger.info(f"Created MongoDB metadata document for {file.filename} with ID: {mongodb_id}")

                    # STEP 2: Check content size before RAG insertion
                    if len(content) > MAX_RAG_CONTENT_LENGTH:
                        app.logger.warning(f"Manual file {file.filename} too large ({len(content)} chars, max {MAX_RAG_CONTENT_LENGTH})")
                        metadata_col.update_one(
                            {"_id": ObjectId(mongodb_id)},
                            {"$set": {"rag_sync_status": "too_large"}}
                        )
                        processed_files.append({
                            "filename": file.filename,
                            "size": len(file_content),
                            "content_length": len(content),
                            "lightrag": "too_large"
                        })
                    else:
                        # Enqueue document for background RAG insertion
                        enqueue_rag_insertion(
                            company_id=company_id,
                            doc_id=mongodb_id,
                            content=content,
                            metadata={
                                "source": "manual_file_upload",
                                "file_id": mongodb_id,  # Use MongoDB _id
                                "file_name": file.filename,
                                "file_size": len(file_content),
                                "mime_type": mime_type,
                                "file_extension": file_ext,
                                "updated_at": now
                            }
                        )

                        app.logger.info(f"Enqueued RAG insertion for {file.filename} with ID: {mongodb_id}")
                        processed_files.append({
                            "filename": file.filename,
                            "size": len(file_content),
                            "content_length": len(content),
                            "lightrag": "queued"
                        })

                else:
                    app.logger.warning(f"No content extracted from file: {filename}")
                    skipped_files.append({"filename": file.filename, "reason": "No content could be extracted"})

            except Exception as e:
                app.logger.error(f"Error processing file {filename}: {e}")
                skipped_files.append({"filename": file.filename, "reason": f"Processing error: {str(e)}"})
                continue

        # Update company stats
        total_file_count = metadata_col.count_documents({
            "company_id": company_id,
            "type": "manual_upload_file"
        })

        companies_col.update_one(
            {"_id": _id},
            {
                "$set": {
                    "manual_uploads.file_count": total_file_count,
                    "manual_uploads.last_upload": datetime.datetime.utcnow().isoformat()
                }
            }
        )

        response_data = {
            "message": f"Successfully processed {len(processed_files)} out of {total_submitted} files",
            "processed_files": processed_files,
            "skipped_files": skipped_files,
            "total_submitted": total_submitted,
            "total_processed": len(processed_files),
            "total_skipped": len(skipped_files),
            "total_manual_files": total_file_count
        }

        return jsonify(response_data), 200

    except Exception as e:
        app.logger.error(f"Error uploading files for company {company_id}: {e}")
        return jsonify({"error": "Failed to upload files"}), 500

@app.route("/companies/<company_id>/files", methods=["GET"])
@token_required
def get_manual_files(company_id):
    """Get list of manually uploaded files for a company"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        files = metadata_col.find({
            "company_id": company_id,
            "type": "manual_upload_file"
        }).sort("updated_at", -1)

        return json_cursor(files)

    except Exception as e:
        app.logger.error(f"Error getting manual files for company {company_id}: {e}")
        return jsonify({"error": "Failed to get files"}), 500

@app.route("/companies/<company_id>/files/<file_id>", methods=["DELETE"])
@token_required
def delete_manual_file(company_id, file_id):
    """Delete a manually uploaded file"""
    if not is_admin():
        if claim_company_id() != company_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        _id = oid(file_id)
        if not _id:
            return jsonify({"error": "Invalid file ID"}), 400

        # Check if file exists
        file_doc = metadata_col.find_one({
            "_id": _id,
            "company_id": company_id,
            "type": "manual_upload_file"
        })

        if not file_doc:
            return jsonify({"error": "File not found"}), 404

        # Delete from MongoDB
        result = metadata_col.delete_one({
            "_id": _id,
            "company_id": company_id,
            "type": "manual_upload_file"
        })

        if result.deleted_count == 0:
            return jsonify({"error": "File not found"}), 404

        # Delete from LightRAG knowledge graph (best effort)
        try:
            # Use MongoDB _id as the document ID
            doc_id = str(_id)
            success = delete_company_document(
                company_id=company_id,
                doc_id=doc_id
            )
            if success:
                app.logger.info(f"Successfully deleted manual file from LightRAG: {file_id}")
            else:
                app.logger.warning(f"Failed to delete manual file from LightRAG: {file_id}")
        except Exception as e:
            app.logger.error(f"Error deleting from LightRAG: {e}")
            # Don't fail the request - file is already deleted from MongoDB

        # Update company stats
        _company_id = oid(company_id)
        if _company_id:
            total_file_count = metadata_col.count_documents({
                "company_id": company_id,
                "type": "manual_upload_file"
            })

            companies_col.update_one(
                {"_id": _company_id},
                {
                    "$set": {
                        "manual_uploads.file_count": total_file_count
                    }
                }
            )

        return jsonify({"message": "File deleted successfully"}), 200

    except Exception as e:
        app.logger.error(f"Error deleting manual file {file_id} for company {company_id}: {e}")
        return jsonify({"error": "Failed to delete file"}), 500

# ─── Misc ─────────────────────────────────────────────────────────────────────
@app.route("/health")
def health_check():
    return jsonify({"status": "ok"}), 200

# ─── Entrypoint ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # For Docker logs, prefer unbuffered prints or logging (already set)
    app.run(debug=False, host="0.0.0.0", port=5000)
