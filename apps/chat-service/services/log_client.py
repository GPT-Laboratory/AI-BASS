import aiohttp
import os

LOG_SERVICE_URL = os.getenv("LOG_SERVICE_URL", "http://log-service:8000/log")

async def log_interaction_to_service(log_payload: dict):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(LOG_SERVICE_URL, json=log_payload) as resp:
                if resp.status != 200:
                    print(f"Log service error: {resp.status}")
        except Exception as e:
            print(f"Failed to log interaction: {e}")
