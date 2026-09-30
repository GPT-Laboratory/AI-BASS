"""
Email provider implementations for different email services.
Supports Gmail (OAuth2), Microsoft 365 (OAuth2), and Generic IMAP (username/password).
"""

import imaplib
import email
import datetime
import logging
import base64
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple
from email.header import decode_header
from email.utils import parsedate_to_datetime
import re
import html

from cryptography.fernet import Fernet
import msal
import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


class EmailProvider(ABC):
    """Abstract base class for email providers"""

    @abstractmethod
    def authenticate(self, credentials: Dict) -> Tuple[bool, str]:
        """Authenticate with the email provider"""
        pass

    @abstractmethod
    def get_folders(self) -> List[Dict]:
        """Get list of available folders/mailboxes"""
        pass

    @abstractmethod
    def fetch_emails(self, folder: str, since_date: datetime.datetime, limit: int = 200) -> List[Dict]:
        """Fetch emails from a specific folder since a given date"""
        pass

    @abstractmethod
    def refresh_credentials(self, credentials: Dict) -> Tuple[bool, str, Dict]:
        """Refresh authentication credentials"""
        pass

    @abstractmethod
    def disconnect(self):
        """Clean up connections"""
        pass


class GmailProvider(EmailProvider):
    """Gmail provider using OAuth2 and IMAP"""

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.gmail_service = None
        self.credentials = None
        self.email_address = None

    def authenticate(self, credentials: Dict) -> Tuple[bool, str]:
        """Authenticate with Gmail using OAuth2 credentials and Gmail API instead of IMAP"""
        try:
            # Handle both token formats (unified Google callback uses "token", old format uses "access_token")
            access_token = credentials.get("token") or credentials.get("access_token")

            if not access_token:
                return False, "No access token found in credentials"

            logging.info(f"Gmail authentication starting with token: {access_token[:20]}..." if access_token else "No token")

            self.credentials = Credentials(
                token=access_token,
                refresh_token=credentials.get("refresh_token"),
                token_uri=credentials.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=credentials.get("client_id", self.client_id),
                client_secret=credentials.get("client_secret", self.client_secret),
                scopes=credentials.get("scopes", ["https://www.googleapis.com/auth/gmail.readonly"])
            )

            # Check if credentials are expired and refresh if needed
            logging.info(f"Gmail credentials expired: {self.credentials.expired}")
            if self.credentials.expired and self.credentials.refresh_token:
                logging.info("Gmail credentials expired, refreshing...")
                self.credentials.refresh(Request())
                access_token = self.credentials.token
                logging.info(f"Gmail credentials refreshed, new token: {access_token[:20]}..." if access_token else "No new token")

            # Test authentication by building Gmail service and getting profile
            self.gmail_service = build('gmail', 'v1', credentials=self.credentials)

            # Test the connection by getting user profile
            profile = self.gmail_service.users().getProfile(userId='me').execute()
            email_address = profile.get('emailAddress', '')

            if not email_address:
                return False, "Unable to retrieve email address from Gmail API"

            logging.info(f"Gmail API authentication successful for: {email_address}")

            # Store the email address for use in other methods
            self.email_address = email_address

            return True, "Successfully authenticated with Gmail API"

        except Exception as e:
            error_msg = f"Gmail authentication failed: {str(e)}"
            logging.error(error_msg)

            # Provide more specific error messages for common issues
            if "Invalid SASL argument" in str(e):
                error_msg += " - This usually indicates an expired or invalid access token"
            elif "AUTHENTICATE command error" in str(e):
                error_msg += " - Gmail IMAP authentication failed, check OAuth scopes"

            return False, error_msg

    def get_folders(self) -> List[Dict]:
        """Get Gmail labels using Gmail API"""
        try:
            if not self.gmail_service:
                return []

            # Get all labels from Gmail
            results = self.gmail_service.users().labels().list(userId='me').execute()
            labels = results.get('labels', [])

            folder_list = []
            for label in labels:
                # Filter out system labels that aren't useful for email reading
                label_id = label['id']
                label_name = label['name']

                # Include important system labels and all user labels
                if (label_id in ['INBOX', 'SENT', 'DRAFT', 'SPAM', 'TRASH'] or
                    label['type'] == 'user'):
                    folder_list.append({
                        "id": label_id,
                        "name": label_name,
                        "display_name": label_name,
                        "selectable": True,
                        "messages_total": label.get('messagesTotal', 0),
                        "messages_unread": label.get('messagesUnread', 0)
                    })

            return folder_list

        except Exception as e:
            logging.error(f"Failed to get Gmail labels: {e}")
            return []

    def fetch_emails(self, folder: str, since_date: datetime.datetime, limit: int = 200) -> List[Dict]:
        """Fetch emails from Gmail using Gmail API"""
        try:
            if not self.gmail_service:
                return []

            # Convert datetime to Gmail API format (Unix timestamp)
            since_timestamp = int(since_date.timestamp())

            # Build query for Gmail API
            # Use label instead of folder for Gmail API
            query_parts = []

            # Add label filter if not INBOX (which is default)
            if folder and folder != 'INBOX':
                query_parts.append(f'label:{folder}')

            # Add date filter
            query_parts.append(f'after:{since_timestamp}')

            query = ' '.join(query_parts)

            logging.info(f"Gmail API query: {query}")

            # Get list of message IDs (Gmail API returns newest first by default)
            messages_result = self.gmail_service.users().messages().list(
                userId='me',
                q=query,
                maxResults=limit
            ).execute()

            messages = messages_result.get('messages', [])

            if not messages:
                logging.info(f"No messages found for query: {query}")
                return []

            emails = []
            for message_ref in messages:
                try:
                    email_data = self._fetch_single_gmail_api_email(message_ref['id'], folder)
                    if email_data:
                        emails.append(email_data)
                except Exception as e:
                    logging.error(f"Failed to fetch Gmail email {message_ref['id']}: {e}")
                    continue

            # Sort by date descending (newest first) to ensure prioritization
            emails.sort(key=lambda x: x['date'], reverse=True)

            logging.info(f"Fetched {len(emails)} emails from Gmail API")
            return emails

        except Exception as e:
            logging.error(f"Failed to fetch Gmail emails via API: {e}")
            return []

    def _fetch_single_gmail_api_email(self, message_id: str, folder: str) -> Optional[Dict]:
        """Fetch a single email by ID using Gmail API"""
        try:
            # Get the full message
            message = self.gmail_service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()

            # Extract headers
            headers = {}
            for header in message['payload'].get('headers', []):
                headers[header['name'].lower()] = header['value']

            # Extract basic info
            subject = headers.get('subject', '')
            sender = headers.get('from', '')
            date_str = headers.get('date', '')
            message_id_header = headers.get('message-id', message_id)

            # Parse date
            if date_str:
                try:
                    from email.utils import parsedate_to_datetime
                    email_date = parsedate_to_datetime(date_str)
                except:
                    email_date = datetime.datetime.utcnow()
            else:
                email_date = datetime.datetime.utcnow()

            # Extract recipients
            to_list = self._parse_email_addresses(headers.get('to', ''))
            cc_list = self._parse_email_addresses(headers.get('cc', ''))
            bcc_list = self._parse_email_addresses(headers.get('bcc', ''))

            # Extract body content
            body_text, body_html = self._extract_gmail_api_body(message['payload'])

            # Get labels for this message
            labels = message.get('labelIds', [])

            return {
                "message_id": message_id_header,
                "uid": message_id,
                "folder": folder,
                "labels": labels,
                "subject": subject,
                "sender": sender,
                "recipients": to_list,
                "cc": cc_list,
                "bcc": bcc_list,
                "date": email_date,
                "body_text": body_text,
                "body_html": body_html,
                "has_attachments": self._gmail_api_has_attachments(message['payload']),
                "size_bytes": int(message.get('sizeEstimate', 0))
            }

        except Exception as e:
            logging.error(f"Failed to parse Gmail API email: {e}")
            return None

    def _extract_gmail_api_body(self, payload) -> Tuple[str, str]:
        """Extract text and HTML body from Gmail API payload"""
        body_text = ""
        body_html = ""

        def extract_from_part(part):
            nonlocal body_text, body_html

            mime_type = part.get('mimeType', '')

            if mime_type == 'text/plain':
                data = part.get('body', {}).get('data', '')
                if data:
                    import base64
                    decoded = base64.urlsafe_b64decode(data + '==').decode('utf-8', errors='ignore')
                    body_text += decoded

            elif mime_type == 'text/html':
                data = part.get('body', {}).get('data', '')
                if data:
                    import base64
                    decoded = base64.urlsafe_b64decode(data + '==').decode('utf-8', errors='ignore')
                    body_html += decoded

            elif mime_type.startswith('multipart/'):
                # Recursively process multipart content
                for subpart in part.get('parts', []):
                    extract_from_part(subpart)

        extract_from_part(payload)

        # Convert HTML to text if no plain text is available
        if body_html and not body_text:
            body_text = self._html_to_text(body_html)

        return body_text.strip(), body_html.strip()

    def _gmail_api_has_attachments(self, payload) -> bool:
        """Check if email has attachments using Gmail API payload"""
        def check_part(part):
            filename = part.get('filename', '')
            if filename and part.get('body', {}).get('attachmentId'):
                return True

            for subpart in part.get('parts', []):
                if check_part(subpart):
                    return True
            return False

        return check_part(payload)
        """Fetch a single email by ID"""
        try:
            status, msg_data = self.imap.fetch(msg_id, '(RFC822)')
            if status != 'OK':
                return None

            # Parse the email
            raw_email = msg_data[0][1]
            email_message = email.message_from_bytes(raw_email)

            # Extract email metadata
            subject = self._decode_header(email_message.get('Subject', ''))
            sender = self._decode_header(email_message.get('From', ''))
            date_str = email_message.get('Date', '')
            message_id = email_message.get('Message-ID', '')

            # Parse date
            email_date = parsedate_to_datetime(date_str) if date_str else datetime.datetime.utcnow()

            # Extract recipients
            to_list = self._parse_email_addresses(email_message.get('To', ''))
            cc_list = self._parse_email_addresses(email_message.get('Cc', ''))
            bcc_list = self._parse_email_addresses(email_message.get('Bcc', ''))

            # Extract body content
            body_text, body_html = self._extract_body(email_message)

            return {
                "message_id": message_id,
                "uid": msg_id.decode(),
                "folder": folder,
                "subject": subject,
                "sender": sender,
                "recipients": to_list,
                "cc": cc_list,
                "bcc": bcc_list,
                "date": email_date,
                "body_text": body_text,
                "body_html": body_html,
                "has_attachments": self._has_attachments(email_message),
                "size_bytes": len(raw_email)
            }

        except Exception as e:
            logging.error(f"Failed to parse Gmail email: {e}")
            return None

    def refresh_credentials(self, credentials: Dict) -> Tuple[bool, str, Dict]:
        """Refresh Gmail OAuth2 credentials"""
        try:
            # Handle both token formats (unified Google callback uses "token", old format uses "access_token")
            access_token = credentials.get("token") or credentials.get("access_token")

            creds = Credentials(
                token=access_token,
                refresh_token=credentials.get("refresh_token"),
                token_uri=credentials.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=credentials.get("client_id", self.client_id),
                client_secret=credentials.get("client_secret", self.client_secret),
                scopes=credentials.get("scopes")
            )

            if creds.expired and creds.refresh_token:
                creds.refresh(Request())

                # Return credentials in the same format as the unified Google callback
                updated_creds = {
                    "token": creds.token,  # Use "token" to match unified callback format
                    "refresh_token": creds.refresh_token,
                    "token_uri": creds.token_uri,
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "scopes": creds.scopes,
                    "email_address": credentials.get("email_address")
                }

                return True, "Credentials refreshed successfully", updated_creds

            return True, "Credentials still valid", credentials

        except Exception as e:
            logging.error(f"Failed to refresh Gmail credentials: {e}")
            return False, f"Failed to refresh credentials: {str(e)}", credentials

    def disconnect(self):
        """Disconnect from Gmail API"""
        if self.gmail_service:
            self.gmail_service = None
        self.credentials = None
        self.email_address = None

    def _decode_header(self, header: str) -> str:
        """Decode email header"""
        if not header:
            return ""

        decoded_parts = decode_header(header)
        decoded_str = ""

        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                decoded_str += part.decode(encoding or 'utf-8', errors='ignore')
            else:
                decoded_str += part

        return decoded_str.strip()

    def _parse_email_addresses(self, addr_str: str) -> List[str]:
        """Parse email addresses from header"""
        if not addr_str:
            return []

        # Simple email extraction
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        return re.findall(email_pattern, addr_str)

    def _extract_body(self, email_message) -> Tuple[str, str]:
        """Extract text and HTML body from email"""
        body_text = ""
        body_html = ""

        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                if "attachment" not in content_disposition:
                    if content_type == "text/plain":
                        body_text += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    elif content_type == "text/html":
                        body_html += part.get_payload(decode=True).decode('utf-8', errors='ignore')
        else:
            content_type = email_message.get_content_type()
            if content_type == "text/plain":
                body_text = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')
            elif content_type == "text/html":
                body_html = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')

        # Convert HTML to text for combined content
        if body_html and not body_text:
            body_text = self._html_to_text(body_html)

        return body_text.strip(), body_html.strip()

    def _html_to_text(self, html_content: str) -> str:
        """Convert HTML to plain text"""
        # Remove HTML tags and decode entities
        text = re.sub(r'<[^>]+>', '', html_content)
        text = html.unescape(text)
        return text.strip()

    def _has_attachments(self, email_message) -> bool:
        """Check if email has attachments"""
        if email_message.is_multipart():
            for part in email_message.walk():
                content_disposition = str(part.get("Content-Disposition"))
                if "attachment" in content_disposition:
                    return True
        return False


class MicrosoftProvider(EmailProvider):
    """Microsoft 365/Outlook provider using Microsoft Graph API"""

    def __init__(self, client_id: str, client_secret: str, tenant_id: str = "common"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.access_token = None
        self.refresh_token = None

    def authenticate(self, credentials: Dict) -> Tuple[bool, str]:
        """Authenticate with Microsoft Graph API"""
        try:
            self.access_token = credentials.get("access_token")
            self.refresh_token = credentials.get("refresh_token")

            # Test the connection by getting user info
            headers = {"Authorization": f"Bearer {self.access_token}"}
            response = requests.get("https://graph.microsoft.com/v1.0/me", headers=headers)

            if response.status_code == 200:
                return True, "Successfully authenticated with Microsoft"
            else:
                return False, f"Microsoft authentication failed: {response.status_code}"

        except Exception as e:
            logging.error(f"Microsoft authentication failed: {e}")
            return False, f"Microsoft authentication failed: {str(e)}"

    def get_folders(self) -> List[Dict]:
        """Get Microsoft mail folders"""
        try:
            headers = {"Authorization": f"Bearer {self.access_token}"}
            response = requests.get("https://graph.microsoft.com/v1.0/me/mailFolders", headers=headers)

            if response.status_code != 200:
                return []

            folders_data = response.json()
            folders = []

            for folder in folders_data.get("value", []):
                folders.append({
                    "id": folder["id"],
                    "name": folder["displayName"],
                    "display_name": folder["displayName"],
                    "selectable": True
                })

            return folders

        except Exception as e:
            logging.error(f"Failed to get Microsoft folders: {e}")
            return []

    def fetch_emails(self, folder: str, since_date: datetime.datetime, limit: int = 200) -> List[Dict]:
        """Fetch emails from Microsoft folder"""
        try:
            headers = {"Authorization": f"Bearer {self.access_token}"}

            # Format date for Microsoft Graph API
            since_str = since_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")

            # Build the API URL
            url = f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages"
            params = {
                "$filter": f"receivedDateTime ge {since_str}",
                "$top": limit,
                "$orderby": "receivedDateTime desc"
            }

            response = requests.get(url, headers=headers, params=params)

            if response.status_code != 200:
                logging.error(f"Failed to fetch Microsoft emails: {response.status_code}")
                return []

            emails_data = response.json()
            emails = []

            for email_item in emails_data.get("value", []):
                try:
                    email_data = self._parse_microsoft_email(email_item, folder)
                    if email_data:
                        emails.append(email_data)
                except Exception as e:
                    logging.error(f"Failed to parse Microsoft email: {e}")
                    continue

            return emails

        except Exception as e:
            logging.error(f"Failed to fetch Microsoft emails: {e}")
            return []

    def _parse_microsoft_email(self, email_item: Dict, folder: str) -> Optional[Dict]:
        """Parse Microsoft Graph email item"""
        try:
            # Extract recipients
            to_list = [addr["emailAddress"]["address"] for addr in email_item.get("toRecipients", [])]
            cc_list = [addr["emailAddress"]["address"] for addr in email_item.get("ccRecipients", [])]
            bcc_list = [addr["emailAddress"]["address"] for addr in email_item.get("bccRecipients", [])]

            # Parse date
            received_date = datetime.datetime.fromisoformat(
                email_item["receivedDateTime"].replace("Z", "+00:00")
            )

            # Extract body content
            body_content = email_item.get("body", {})
            content_type = body_content.get("contentType", "")
            content = body_content.get("content", "")

            body_text = ""
            body_html = ""

            if content_type == "text":
                body_text = content
            elif content_type == "html":
                body_html = content
                # Convert HTML to text for body_text field
                body_text = self._html_to_text(content)

            return {
                "message_id": email_item["internetMessageId"],
                "uid": email_item["id"],
                "folder": folder,
                "subject": email_item.get("subject", ""),
                "sender": email_item.get("sender", {}).get("emailAddress", {}).get("address", ""),
                "recipients": to_list,
                "cc": cc_list,
                "bcc": bcc_list,
                "date": received_date,
                "body_text": body_text,
                "body_html": body_html,
                "has_attachments": email_item.get("hasAttachments", False),
                "size_bytes": 0  # Microsoft Graph doesn't provide size directly
            }

        except Exception as e:
            logging.error(f"Failed to parse Microsoft email: {e}")
            return None

    def _html_to_text(self, html_content: str) -> str:
        """Convert HTML to plain text"""
        if not html_content:
            return ""
        # Remove HTML tags and decode entities
        text = re.sub(r'<[^>]+>', '', html_content)
        text = html.unescape(text)
        return text.strip()

    def refresh_credentials(self, credentials: Dict) -> Tuple[bool, str, Dict]:
        """Refresh Microsoft OAuth2 credentials"""
        try:
            app = msal.ConfidentialClientApplication(
                self.client_id,
                authority=f"https://login.microsoftonline.com/{self.tenant_id}",
                client_credential=self.client_secret
            )

            result = app.acquire_token_by_refresh_token(
                refresh_token=credentials.get("refresh_token"),
                scopes=["https://graph.microsoft.com/Mail.Read"]
            )

            if "access_token" in result:
                updated_creds = credentials.copy()
                updated_creds["access_token"] = result["access_token"]
                if "refresh_token" in result:
                    updated_creds["refresh_token"] = result["refresh_token"]

                return True, "Credentials refreshed successfully", updated_creds
            else:
                return False, f"Failed to refresh: {result.get('error_description', 'Unknown error')}", credentials

        except Exception as e:
            logging.error(f"Failed to refresh Microsoft credentials: {e}")
            return False, f"Failed to refresh credentials: {str(e)}", credentials

    def disconnect(self):
        """Disconnect from Microsoft (no persistent connection)"""
        self.access_token = None
        self.refresh_token = None


class GenericIMAPProvider(EmailProvider):
    """Generic IMAP provider using username/password authentication"""

    def __init__(self, encryption_key: str):
        self.encryption_key = encryption_key
        self.fernet = Fernet(encryption_key.encode()) if encryption_key else None
        self.imap = None
        self.server_config = None

    def authenticate(self, credentials: Dict) -> Tuple[bool, str]:
        """Authenticate with generic IMAP server"""
        try:
            server = credentials.get("imap_server")
            port = credentials.get("imap_port", 993)
            username = credentials.get("username")
            password = credentials.get("password")
            use_ssl = credentials.get("use_ssl", True)

            # Decrypt password if it's encrypted
            if self.fernet and isinstance(password, str) and password.startswith("encrypted:"):
                password = self.fernet.decrypt(password[10:].encode()).decode()

            # Connect to IMAP server
            if use_ssl:
                self.imap = imaplib.IMAP4_SSL(server, port)
            else:
                self.imap = imaplib.IMAP4(server, port)

            # Login
            self.imap.login(username, password)

            self.server_config = credentials
            return True, f"Successfully authenticated with {server}"

        except Exception as e:
            logging.error(f"Generic IMAP authentication failed: {e}")
            return False, f"IMAP authentication failed: {str(e)}"

    def get_folders(self) -> List[Dict]:
        """Get IMAP folders"""
        try:
            if not self.imap:
                return []

            status, folders = self.imap.list()
            if status != 'OK':
                return []

            folder_list = []
            for folder in folders:
                folder_info = folder.decode('utf-8')
                # Parse folder info
                parts = folder_info.split('"')
                if len(parts) >= 3:
                    folder_name = parts[-2]
                    folder_list.append({
                        "name": folder_name,
                        "display_name": folder_name,
                        "selectable": True
                    })

            return folder_list

        except Exception as e:
            logging.error(f"Failed to get IMAP folders: {e}")
            return []

    def fetch_emails(self, folder: str, since_date: datetime.datetime, limit: int = 200) -> List[Dict]:
        """Fetch emails from IMAP folder"""
        try:
            if not self.imap:
                return []

            # Select the folder
            status, _ = self.imap.select(folder)
            if status != 'OK':
                logging.error(f"Failed to select IMAP folder: {folder}")
                return []

            # Search for emails since the given date
            date_str = since_date.strftime("%d-%b-%Y")
            search_criteria = f'SINCE {date_str}'

            status, messages = self.imap.search(None, search_criteria)
            if status != 'OK':
                return []

            message_ids = messages[0].split()

            # Limit the number of emails
            if len(message_ids) > limit:
                message_ids = message_ids[-limit:]  # Get most recent emails

            emails = []
            for msg_id in message_ids:
                try:
                    email_data = self._fetch_single_imap_email(msg_id, folder)
                    if email_data:
                        emails.append(email_data)
                except Exception as e:
                    logging.error(f"Failed to fetch IMAP email {msg_id}: {e}")
                    continue

            return emails

        except Exception as e:
            logging.error(f"Failed to fetch IMAP emails: {e}")
            return []

    def _fetch_single_imap_email(self, msg_id: bytes, folder: str) -> Optional[Dict]:
        """Fetch a single email by ID from IMAP"""
        try:
            status, msg_data = self.imap.fetch(msg_id, '(RFC822)')
            if status != 'OK':
                return None

            # Parse the email (reuse Gmail parsing logic)
            raw_email = msg_data[0][1]
            email_message = email.message_from_bytes(raw_email)

            # Extract email metadata
            subject = self._decode_header(email_message.get('Subject', ''))
            sender = self._decode_header(email_message.get('From', ''))
            date_str = email_message.get('Date', '')
            message_id = email_message.get('Message-ID', '')

            # Parse date
            email_date = parsedate_to_datetime(date_str) if date_str else datetime.datetime.utcnow()

            # Extract recipients
            to_list = self._parse_email_addresses(email_message.get('To', ''))
            cc_list = self._parse_email_addresses(email_message.get('Cc', ''))
            bcc_list = self._parse_email_addresses(email_message.get('Bcc', ''))

            # Extract body content
            body_text, body_html = self._extract_body(email_message)

            return {
                "message_id": message_id,
                "uid": msg_id.decode(),
                "folder": folder,
                "subject": subject,
                "sender": sender,
                "recipients": to_list,
                "cc": cc_list,
                "bcc": bcc_list,
                "date": email_date,
                "body_text": body_text,
                "body_html": body_html,
                "has_attachments": self._has_attachments(email_message),
                "size_bytes": len(raw_email)
            }

        except Exception as e:
            logging.error(f"Failed to parse IMAP email: {e}")
            return None

    def refresh_credentials(self, credentials: Dict) -> Tuple[bool, str, Dict]:
        """Generic IMAP doesn't need token refresh"""
        return True, "Generic IMAP credentials don't require refresh", credentials

    def disconnect(self):
        """Disconnect from IMAP server"""
        if self.imap:
            try:
                self.imap.close()
                self.imap.logout()
            except:
                pass
            self.imap = None

    def encrypt_password(self, password: str) -> str:
        """Encrypt a password for storage"""
        if not self.fernet:
            return password
        return "encrypted:" + self.fernet.encrypt(password.encode()).decode()

    # Reuse helper methods from GmailProvider
    def _decode_header(self, header: str) -> str:
        """Decode email header"""
        if not header:
            return ""

        decoded_parts = decode_header(header)
        decoded_str = ""

        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                decoded_str += part.decode(encoding or 'utf-8', errors='ignore')
            else:
                decoded_str += part

        return decoded_str.strip()

    def _parse_email_addresses(self, addr_str: str) -> List[str]:
        """Parse email addresses from header"""
        if not addr_str:
            return []

        # Simple email extraction
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        return re.findall(email_pattern, addr_str)

    def _extract_body(self, email_message) -> Tuple[str, str]:
        """Extract text and HTML body from email"""
        body_text = ""
        body_html = ""

        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                if "attachment" not in content_disposition:
                    if content_type == "text/plain":
                        body_text += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    elif content_type == "text/html":
                        body_html += part.get_payload(decode=True).decode('utf-8', errors='ignore')
        else:
            content_type = email_message.get_content_type()
            if content_type == "text/plain":
                body_text = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')
            elif content_type == "text/html":
                body_html = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')

        # Convert HTML to text for combined content
        if body_html and not body_text:
            body_text = self._html_to_text(body_html)

        return body_text.strip(), body_html.strip()

    def _html_to_text(self, html_content: str) -> str:
        """Convert HTML to plain text"""
        # Remove HTML tags and decode entities
        text = re.sub(r'<[^>]+>', '', html_content)
        text = html.unescape(text)
        return text.strip()

    def _has_attachments(self, email_message) -> bool:
        """Check if email has attachments"""
        if email_message.is_multipart():
            for part in email_message.walk():
                content_disposition = str(part.get("Content-Disposition"))
                if "attachment" in content_disposition:
                    return True
        return False


def get_email_provider(provider_type: str, **kwargs) -> EmailProvider:
    """Factory function to create email providers"""
    if provider_type == "gmail":
        return GmailProvider(
            client_id=kwargs.get("client_id"),
            client_secret=kwargs.get("client_secret")
        )
    elif provider_type == "microsoft":
        return MicrosoftProvider(
            client_id=kwargs.get("client_id"),
            client_secret=kwargs.get("client_secret"),
            tenant_id=kwargs.get("tenant_id", "common")
        )
    elif provider_type == "generic":
        return GenericIMAPProvider(
            encryption_key=kwargs.get("encryption_key")
        )
    else:
        raise ValueError(f"Unsupported email provider: {provider_type}")
