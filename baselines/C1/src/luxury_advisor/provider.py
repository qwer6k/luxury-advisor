"""DeepSeek Responses API adapter. No network calls happen at import time."""

import os

from openai import AsyncOpenAI

from luxury_advisor.models import CandidateSet
from luxury_advisor.service import ProviderOutput


class DeepSeekProvider:
    def __init__(self):
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")
        self.model = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
        self.client = AsyncOpenAI(
            api_key=key,
            base_url="https://api.deepseek.com",
            timeout=60.0,
            max_retries=0,
        )

    async def generate(self, instructions: str, context: str) -> ProviderOutput:
        response = await self.client.responses.create(
            model=self.model,
            instructions=instructions,
            input=context,
            reasoning={"effort": "none"},
            max_output_tokens=2048,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "advisor_candidates",
                    "schema": CandidateSet.model_json_schema(),
                }
            },
        )
        if response.status != "completed":
            raise ValueError("Provider response is incomplete or failed")
        usage = response.usage
        return ProviderOutput(
            text=response.output_text,
            model=response.model,
            usage={
                "input_tokens": usage.input_tokens if usage else 0,
                "output_tokens": usage.output_tokens if usage else 0,
            },
        )

    async def close(self) -> None:
        await self.client.close()
