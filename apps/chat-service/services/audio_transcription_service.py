import os
import logging
import asyncio
import tempfile
import requests
from typing import Optional
from openai import AsyncAzureOpenAI
from openai import APIConnectionError, APITimeoutError, APIStatusError

logger = logging.getLogger(__name__)

class AudioTranscriptionService:
    """Service for transcribing audio files using Azure OpenAI Whisper"""

    def __init__(self):
        self.azure_api_key = os.getenv("AZURE_API_KEY")
        self.azure_endpoint = os.getenv("AZURE_ENDPOINT")
        self.azure_version = os.getenv("AZURE_VERSION", "2024-06-01")
        self.deployment_name = "whisper"  # Based on the URL provided

        # WhatsApp API settings
        self.whatsapp_token = os.getenv("WHATSAPP_TOKEN")
        self.whatsapp_api_url = os.getenv("WHATSAPP_API_URL", "https://graph.facebook.com/v23.0")

        if not self.azure_api_key or not self.azure_endpoint:
            logger.error("Azure API key or endpoint not configured for audio transcription")
            return

        self.client = AsyncAzureOpenAI(
            api_key=self.azure_api_key,
            azure_endpoint=self.azure_endpoint,
            api_version=self.azure_version,
            timeout=30.0,  # 30 second timeout for audio processing
            max_retries=2,
        )

    async def download_whatsapp_audio(self, media_id: str) -> Optional[bytes]:
        """Download audio file from WhatsApp using media ID"""
        try:
            # First, get the media URL
            media_url_endpoint = f"{self.whatsapp_api_url}/{media_id}"
            headers = {
                "Authorization": f"Bearer {self.whatsapp_token}",
            }

            logger.info("Getting media URL for audio file: %s", media_id)
            response = requests.get(media_url_endpoint, headers=headers)
            response.raise_for_status()

            media_data = response.json()
            download_url = media_data.get("url")

            if not download_url:
                logger.error("No download URL found in media response")
                return None

            # Download the actual audio file
            logger.info("Downloading audio file from: %s", download_url)
            download_response = requests.get(download_url, headers=headers)
            download_response.raise_for_status()

            return download_response.content

        except requests.RequestException as e:
            logger.error("Error downloading audio file: %s", e)
            return None
        except Exception as e:
            logger.error("Unexpected error downloading audio: %s", e)
            return None

    async def transcribe_audio(self, audio_data: bytes, filename: str = "audio.ogg") -> Optional[str]:
        """Transcribe audio data using Azure OpenAI Whisper"""
        try:
            # Create a temporary file to store the audio data
            with tempfile.NamedTemporaryFile(delete=False, suffix=self._get_file_extension(filename)) as temp_file:
                temp_file.write(audio_data)
                temp_file.flush()

                logger.info("Transcribing audio file: %s (size: %d bytes)", filename, len(audio_data))

                # Transcribe using Azure OpenAI
                with open(temp_file.name, 'rb') as audio_file:
                    result = await self.client.audio.transcriptions.create(
                        model=self.deployment_name,
                        file=audio_file,
                        response_format="text"  # Get plain text response
                    )

                # Clean up temp file
                os.unlink(temp_file.name)

                transcription = result.strip() if isinstance(result, str) else result.text.strip()
                logger.info("Audio transcription completed successfully: %s", transcription[:100] + "..." if len(transcription) > 100 else transcription)

                return transcription

        except (APITimeoutError, APIConnectionError, APIStatusError) as e:
            logger.error("Azure OpenAI API error during transcription: %s", e)
            return None
        except Exception as e:
            logger.error("Error transcribing audio: %s", e)
            return None

    def _get_file_extension(self, filename: str) -> str:
        """Get appropriate file extension for temporary file"""
        if filename.endswith('.ogg'):
            return '.ogg'
        elif filename.endswith('.mp3'):
            return '.mp3'
        elif filename.endswith('.wav'):
            return '.wav'
        elif filename.endswith('.m4a'):
            return '.m4a'
        else:
            return '.ogg'  # Default to ogg for WhatsApp audio

    async def process_whatsapp_audio(self, media_id: str, filename: str = "audio.ogg") -> Optional[str]:
        """Complete workflow: download WhatsApp audio and transcribe it"""
        try:
            # Download the audio file
            audio_data = await self.download_whatsapp_audio(media_id)
            if not audio_data:
                return None

            # Transcribe the audio
            transcription = await self.transcribe_audio(audio_data, filename)
            return transcription

        except Exception as e:
            logger.error("Error processing WhatsApp audio: %s", e)
            return None
