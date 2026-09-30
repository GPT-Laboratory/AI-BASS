import os
import secrets
import string
from urllib.parse import unquote


class CommandHandler:
    def __init__(self, db):
        """
        Initialize the command handler with a MongoDB database.

        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.users_col = db["users"]

    def normalize_phone_number(self, phone: str) -> str:
        """Normalize phone number format."""
        decoded = unquote(phone or "")
        return decoded if decoded.startswith('+') else '+' + decoded.lstrip('+')

    def generate_password(self, length: int = 5) -> str:
        """Generate a random password of specified length."""
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    async def handle_command(self, cmd: str, phone_number: str) -> str:
        """
        Handle supported commands and return appropriate responses.

        Args:
            cmd: The command string (e.g., "!commands", "!password")
            phone_number: The user's phone number

        Returns:
            Response string for the command
        """
        if cmd == "!commands":
            return "!commands — list available commands\n!password — generate a new 8-character admin password"

        if cmd == "!password" or cmd == "!auth" or cmd == "!login":
            if not phone_number:
                return "Error: phone number is required."

            phone_number = self.normalize_phone_number(phone_number)

            # Ensure user exists
            user = self.users_col.find_one({"phone_number": phone_number})
            if not user:
                return "Error: User not found."

            # Generate new password and update user
            pw = self.generate_password(8)
            self.users_col.update_one(
                {"phone_number": phone_number},
                {"$set": {"admin_password": pw}}
            )
            admin_url = os.getenv("ADMIN_PUBLIC_URL", "http://localhost:8080").rstrip("/")
            chat_url = os.getenv("CHAT_PUBLIC_URL", "http://localhost:8000").rstrip("/")
            return (
                f"You can now log in at {admin_url}/login\n"
                f"Username: {phone_number}\n"
                f"Password: {pw}\n"
                f"Web chat is available at {chat_url}/ with the same credentials."
            )

        return "Error: Unknown command. Type !commands to see available commands."

    def is_command(self, message: str) -> bool:
        """Check if a message is a command (starts with !)."""
        return message.strip().startswith("!")

    def extract_command(self, message: str) -> str:
        """Extract the command from a message (first token)."""
        return message.split()[0].strip()
