import logging
import sys
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)

# Log uncaught exceptions
def log_uncaught_exceptions(exctype, value, tb):
    logger.error("Uncaught exception", exc_info=(exctype, value, tb))
sys.excepthook = log_uncaught_exceptions

import os
import re
from dotenv import load_dotenv
from flask import Flask, request
import requests
import asyncio
import tempfile
from pymongo import MongoClient
from urllib.parse import unquote
from services.chatgpt_client import ChatGPTClient
from core.chat_engine import ChatEngine
from core.settings_provider import SettingsProvider
from services.conversation_service import ConversationService
from services.audio_transcription_service import AudioTranscriptionService

load_dotenv()

app = Flask(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_BUSINESS_ID = os.getenv("WHATSAPP_BUSINESS_ID")
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "https://graph.facebook.com/v23.0")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://mongo:27017/")
COURSE_URL = os.getenv("COURSE_URL")
COURSE_API_SECRET = os.getenv("COURSE_API_SECRET")

# Track processed message IDs to avoid duplicate processing
processed_message_ids = []

# Setup MongoDB connection
mongo_client = MongoClient(MONGODB_URI)
db = mongo_client["companydb"]
users_col = db["users"]
settings_col = db["settings"]
settings_provider = SettingsProvider(db)
conversation_service = ConversationService(mongo_uri=MONGODB_URI)
audio_transcription_service = AudioTranscriptionService()
chat_engine = ChatEngine(
    llm=ChatGPTClient(mongo_client=mongo_client),
    settings=settings_provider,
    conversation_service=conversation_service,
    db=db
)

def create_auth_token():
    """Create a JWT token by logging into the admin backend"""
    try:
        # Get credentials from environment variables
        chat_username = os.getenv("CHAT_USERNAME", "admin")
        chat_password = os.environ["CHAT_PASSWORD"]
        admin_backend_url = os.getenv("ADMIN_BACKEND_URL", "http://backend:5000")

        # Make login request to admin backend
        login_url = f"{admin_backend_url}/login"
        login_data = {
            "username": chat_username,
            "password": chat_password
        }

        response = requests.post(login_url, json=login_data, timeout=10)

        if response.status_code == 200:
            response_data = response.json()
            token = response_data.get("token")
            if token:
                logger.info("Successfully obtained JWT token from admin backend")
                return token
            else:
                logger.error("No token in login response: %s", response_data)
                return None
        else:
            logger.error("Login failed with status %s: %s", response.status_code, response.text)
            return None

    except Exception as e:
        logger.error("Error logging into admin backend: %s", e)
        return None

# Fetch WhatsApp error message from settings
def get_whatsapp_error_message():
    doc = settings_col.find_one()
    if doc and "whatsapp_error_message" in doc and doc["whatsapp_error_message"].strip():
        return doc["whatsapp_error_message"]
    return "Hello, you are not registered in the system."

async def download_whatsapp_document(media_id):
    """Download a document from WhatsApp"""
    try:
        # Get media URL from WhatsApp
        url = f"https://graph.facebook.com/v20.0/{media_id}"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}"
        }

        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            logger.error("Failed to get media info for %s: %s", media_id, response.text)
            return None, None

        media_info = response.json()
        media_url = media_info.get("url")
        if not media_url:
            logger.error("No URL found in media info for %s", media_id)
            return None, None

        # Download the actual file
        download_response = requests.get(media_url, headers=headers)
        if download_response.status_code != 200:
            logger.error("Failed to download media from %s: %s", media_url, download_response.text)
            return None, None

        logger.info("Successfully downloaded document with media ID: %s", media_id)
        return download_response.content, media_info.get("mime_type")

    except Exception as e:
        logger.error("Error downloading WhatsApp document: %s", e)
        return None, None

async def upload_file_to_admin_backend(file_content, filename, mime_type, company_id):
    """Upload a file to the admin backend's manual files system"""
    try:
        # Admin backend URL
        admin_backend_url = os.getenv("ADMIN_BACKEND_URL", "http://backend:5000")
        upload_url = f"{admin_backend_url}/companies/{company_id}/files/upload"

        # Create authentication token
        auth_token = create_auth_token()
        if not auth_token:
            logger.error("Failed to create authentication token")
            return False, "Authentication failed"

        # Prepare headers with authentication
        headers = {
            "Authorization": f"Bearer {auth_token}"
        }

        # Prepare the file for upload
        files = {
            'files': (filename, file_content, mime_type)
        }

        response = requests.post(upload_url, files=files, headers=headers, timeout=30)

        if response.status_code in [200, 201]:
            logger.info("Successfully uploaded file %s to company %s", filename, company_id)
            # Parse the success response to get details
            try:
                response_data = response.json()
                processed_files = response_data.get("processed_files", [])
                if processed_files:
                    file_info = processed_files[0]
                    return True, f"File uploaded successfully (ID: {file_info.get('id', 'unknown')})"
                else:
                    return True, "File uploaded successfully"
            except:
                return True, "File uploaded successfully"
        else:
            logger.error("Failed to upload file %s (status %s): %s", filename, response.status_code, response.text)
            return False, f"Upload failed (status {response.status_code}): {response.text}"

    except Exception as e:
        logger.error("Error uploading file to admin backend: %s", e)
        return False, f"Upload error: {str(e)}"

def get_user_company_id(phone_number):
    """Get the company ID for a user based on their phone number"""
    try:
        # Use existing MongoDB connection
        users_col = db["users"]

        # Normalize phone number before lookup
        normalized_phone = normalize_phone_number(phone_number)

        # Find user by phone number
        user = users_col.find_one({"phone_number": normalized_phone})
        if user and "company_id" in user:
            return user["company_id"]
        else:
            logger.warning("No company found for user with phone: %s (normalized: %s)", phone_number, normalized_phone)
            return None

    except Exception as e:
        logger.error("Error getting company ID for user %s: %s", phone_number, e)
        return None

async def handle_file_message(message, user_id, from_number, user):
    """Handle file attachments from WhatsApp messages"""
    message_type = message.get("type")

    if message_type == "document":
        document = message.get("document", {})
        filename = document.get("filename", "unknown")
        mime_type = document.get("mime_type", "")
        file_id = document.get("id", "")

        logger.info("Received document: %s (type: %s, id: %s)", filename, mime_type, file_id)

        # Check if it's a supported document type
        supported_docs = [
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
            "application/msword",  # .doc
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
            "application/vnd.ms-excel",  # .xls
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
            "application/vnd.ms-powerpoint",  # .ppt
            "text/csv",
            "text/plain"
        ]

        if mime_type in supported_docs:
            # Get the user's company ID
            company_id = get_user_company_id(from_number)
            if not company_id:
                return "Your company account could not be found. Your phone number is not linked to a company."

            # Download the document from WhatsApp
            file_content, actual_mime_type = await download_whatsapp_document(file_id)
            if not file_content:
                return "Your file could not be uploaded. Please try again."

            # Upload to admin backend
            success, message = await upload_file_to_admin_backend(
                file_content, filename, actual_mime_type or mime_type, company_id
            )

            if success:
                return f"✅ File {filename} was uploaded to your company document library and is available for AI analysis."
            else:
                return f"❌ Uploading {filename} failed. Please try again."
        else:
            return f"File type '{mime_type}' is not supported. You can send PDF, Word, Excel, PowerPoint, CSV or TXT files."

    elif message_type == "audio":
        audio = message.get("audio", {})
        audio_id = audio.get("id", "")
        mime_type = audio.get("mime_type", "")

        logger.info("Received audio file (type: %s, id: %s)", mime_type, audio_id)

        # Check if it's a supported audio type
        # Extract base MIME type (remove codecs and other parameters)
        base_mime_type = mime_type.split(';')[0].strip()

        supported_audio = [
            "audio/ogg",
            "audio/mpeg",
            "audio/mp4",
            "audio/amr",
            "audio/wav"
        ]

        if base_mime_type in supported_audio:
            # Transcribe the audio file
            try:
                logger.info("Starting audio transcription for file: %s", audio_id)
                transcription = await audio_transcription_service.process_whatsapp_audio(audio_id)

                if transcription:
                    logger.info("Audio transcription successful, processing as text message")
                    # Process the transcription as a regular text message
                    response = await chat_engine.respond(transcription, user_id, source="whatsapp")
                    # Extract answer from response (handle both dict and string for backward compatibility)
                    reply = response.get("answer") if isinstance(response, dict) else response
                    return reply
                else:
                    return "The audio could not be transcribed. Please send a text message."

            except Exception as e:
                logger.error("Error during audio transcription: %s", e)
                return "An error occurred while processing the audio message. Please try again or send a text message."
        else:
            return f"Audio format '{mime_type}' is not supported."

    else:
        return "This file type is not supported."

def normalize_phone_number(phone: str) -> str:
    decoded = unquote(phone)
    return decoded if decoded.startswith('+') else '+' + decoded.lstrip('+')

def strip_citations(text: str) -> str:
    """
    Remove citation markers like [1], [A], [12], [ABC] from text.
    This matches the same pattern used in client.js for removing citations.
    Also cleans up leftover whitespace before punctuation marks.
    """
    # Match patterns like [1], [A], [12], [ABC] and consecutive citations like [4][10][B]
    # This is the Python equivalent of the JavaScript regex: /(\[([A-Za-z0-9]+)\])+/g
    result = re.sub(r'(\[[A-Za-z0-9]+\])+', '', text)

    # Clean up leftover whitespace before punctuation marks
    # This handles cases like "text . " -> "text. " or "text  ." -> "text."
    result = re.sub(r'\s+([.,;:!?])', r'\1', result)

    return result

def try_forward_to_course(phone_number: str, message: str) -> str:
    """
    Try to forward a WhatsApp message to the course deployment.
    Returns the response text if successful, None if failed or not configured.
    """
    # Check if course forwarding is configured
    if not COURSE_URL or not COURSE_API_SECRET:
        logger.info("Course forwarding not configured (COURSE_URL or COURSE_API_SECRET missing)")
        return None

    try:
        # Construct the endpoint URL
        forward_url = COURSE_URL.rstrip('/') + '/whatsapp'

        # Prepare the request payload
        payload = {
            "phone_number": phone_number,
            "message": message,
            "secret": COURSE_API_SECRET
        }

        # Make the request to course deployment
        logger.info("Forwarding message to course deployment: %s", forward_url)
        response = requests.post(forward_url, json=payload, timeout=90)

        # Check if request was successful
        if response.status_code == 200:
            response_data = response.json()
            if response_data.get("success"):
                reply = response_data.get("response", "")
                logger.info("Course deployment returned response: %s", reply[:100])
                # Public URLs are configured through environment variables.
                return reply
            else:
                error = response_data.get("error", "Unknown error")
                logger.warning("Course deployment returned error: %s", error)
                return None
        else:
            logger.error("Course deployment request failed with status %s: %s", response.status_code, response.text)
            return None

    except Exception as e:
        logger.error("Error forwarding to course deployment: %s", e)
        return None

# Webhook verification
@app.route("/webhook", methods=["GET"])
def verify():
    logger.info("Verifying WhatsApp webhook...")
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

# Webhook handler
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    logger.info("Received webhook data!")
    if data and data.get("entry"):
        for entry in data["entry"]:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                for message in messages:
                    from_number = message["from"]
                    message_id = message["id"]
                    message_type = message.get("type", "unknown")

                    # Check if we've already processed this message
                    if message_id in processed_message_ids:
                        logger.info("Ignoring duplicate message ID: %s", message_id)
                        continue

                    # Add message ID to processed list
                    processed_message_ids.append(message_id)

                    # Keep list size manageable (keep last 100 messages)
                    if len(processed_message_ids) > 100:
                        processed_message_ids.pop(0)

                    mark_message_as_read(message_id)

                    # Check if user exists
                    user = users_col.find_one({"phone_number": normalize_phone_number(from_number)})
                    if not user:
                        logger.info("User not found for phone number: %s", from_number)

                        # Try to forward to course deployment only for text messages
                        if message_type == "text":
                            text = message["text"]["body"]
                            forwarded_response = try_forward_to_course(from_number, text)

                            if forwarded_response:
                                # Successfully got response from course deployment
                                logger.info("Successfully forwarded message to course deployment for: %s", from_number)
                                send_whatsapp_message(from_number, forwarded_response)
                                continue
                            else:
                                # Course forwarding failed, send error message
                                logger.info("Course forwarding failed or not configured for: %s", from_number)
                                send_whatsapp_message(from_number, get_whatsapp_error_message())
                                continue
                        else:
                            # Not a text message (file/audio), don't forward
                            logger.info("Non-text message type %s from unregistered user, not forwarding", message_type)
                            send_whatsapp_message(from_number, get_whatsapp_error_message())
                            continue

                    # Handle different message types
                    try:
                        logger.info("Processing %s message for user: %s", message_type, from_number)

                        if message_type == "text":
                            # Handle text messages
                            text = message["text"]["body"]
                            user_id = normalize_phone_number(from_number)  # Use phone number as consistent user ID
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            response = loop.run_until_complete(chat_engine.respond(text, user_id, source="whatsapp"))
                            # Extract answer from response (handle both dict and string for backward compatibility)
                            reply = response.get("answer") if isinstance(response, dict) else response
                            loop.close()

                        elif message_type in ["document", "audio"]:
                            # Handle file attachments
                            user_id = normalize_phone_number(from_number)  # Use phone number as consistent user ID
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            reply = loop.run_until_complete(handle_file_message(message, user_id, from_number, user))
                            loop.close()

                        else:
                            # Handle unsupported message types
                            logger.warning("Unsupported message type: %s", message_type)
                            reply = "Only text messages and supported file types (documents, audio, PDF, CSV, TXT) can be processed."

                    except Exception as e:
                        logger.error("Error processing message: %s", e)
                        reply = "An error occurred while processing the message."

                    send_whatsapp_message(from_number, reply)
    return "OK", 200

def send_whatsapp_message(to, text):
    MAX_LEN = 4096

    # Strip citations before sending to WhatsApp
    text = strip_citations(text)

    def split_message(msg, max_len=MAX_LEN):
        parts = []
        while len(msg) > max_len:
            # Try to split at sentence boundary
            split_idx = max(
                msg.rfind('.', 0, max_len),
                msg.rfind('!', 0, max_len),
                msg.rfind('?', 0, max_len)
            )
            if split_idx == -1:
                # Try to split at whitespace
                split_idx = msg.rfind(' ', 0, max_len)
            if split_idx == -1:
                # Fallback: hard split
                split_idx = max_len
            else:
                split_idx += 1  # include the punctuation/space
            parts.append(msg[:split_idx].rstrip())
            msg = msg[split_idx:].lstrip()
        if msg:
            parts.append(msg)
        return parts

    logger.info("Sending WhatsApp message to %s", to)
    url = f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    for part in split_message(text):
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": part}
        }
        response = requests.post(url, headers=headers, json=payload)
        logger.info("WhatsApp API response: %s %s", response.status_code, response.text)

def mark_message_as_read(message_id):
    logger.info("Marking message as read: %s", message_id)
    try:
        url = f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id
        }
        response = requests.post(url, headers=headers, json=payload)
        logger.info("Mark as read response: %s %s", response.status_code, response.text)
    except Exception as e:
        logger.error("Error marking message as read: %s", e)

def get_all_templates():
    """Fetch all message templates from WhatsApp"""
    try:
        url = f"{WHATSAPP_API_URL}/{WHATSAPP_BUSINESS_ID}/message_templates"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        response = requests.get(url, headers=headers)
        logger.info("Get all templates response: %s %s", response.status_code, response.text)
        if response.status_code == 200:
            return response.json().get("data", [])
        else:
            logger.error("Error fetching templates: %s", response.text)
            return []
    except Exception as e:
        logger.error("Error fetching templates: %s", e)
        return []

@app.route("/send_template", methods=["GET"])
def send_template():
    phone_number = request.args.get("phone_number")
    template_name = request.args.get("template_name")
    language_code = request.args.get("language_code", "en")
    userName = request.args.get("userName")

    if not phone_number or not template_name:
        return "Missing required parameters", 400

    success = send_template_to_phone(phone_number, template_name, language_code, userName)
    if success:
        return "Template sent successfully", 200
    return "Failed to send template", 500

def send_template_to_phone(phone_number: str, template_name: str, language_code: str = "en", userName: str = None):
    """Send a message template to a phone number via WhatsApp"""
    try:
        url = f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "template",
            "template": {
                "name": template_name,
                "language": { "code": language_code },
                "components": [ {
                    "type": "body",
                    "parameters": [ {
                        "type": "text",
                        "parameter_name": "name",
                        "text": userName or "you"
                    } ]
                } ]
            }
        }

        response = requests.post(url, headers=headers, json=payload)
        logger.info("Send template response: %s %s", response.status_code, response.text)
        return response.status_code == 200

    except Exception as e:
        logger.error("Error sending template: %s", e)
        return False

if __name__ == "__main__":
    logger.info("Starting WhatsApp Flask server on 0.0.0.0:8888")
    app.run(host="0.0.0.0", port=8888)
