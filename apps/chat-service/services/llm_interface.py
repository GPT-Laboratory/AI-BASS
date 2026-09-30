from abc import ABC, abstractmethod

class LLMClient(ABC):
    @abstractmethod
    async def chat(self, prompt: list[dict]) -> str:
        pass
