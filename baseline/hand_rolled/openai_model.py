from __future__ import annotations

import json
from typing import cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam
from pydantic import TypeAdapter

from baseline.hand_rolled.agent import (
    BaselineText,
    BaselineToolCall,
    BaselineToolCalls,
    BaselineTurn,
)


class OpenAICompatibleModel:
    _client: AsyncOpenAI
    _model_name: str

    def __init__(self, *, base_url: str, api_key: str, model_name: str) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model_name = model_name

    async def complete(
        self,
        messages: tuple[dict[str, object], ...],
        tools: tuple[dict[str, object], ...],
    ) -> BaselineTurn:
        response = await self._client.chat.completions.create(
            model=self._model_name,
            messages=cast(tuple[ChatCompletionMessageParam, ...], messages),
            tools=cast(tuple[ChatCompletionToolParam, ...], tools),
            tool_choice="auto",
        )
        message = response.choices[0].message
        if message.tool_calls:
            calls = tuple(
                BaselineToolCall(
                    call_id=call.id,
                    name=call.function.name,
                    arguments=TypeAdapter(dict[str, object]).validate_python(
                        json.loads(call.function.arguments)
                    ),
                )
                for call in message.tool_calls
                if call.type == "function"
            )
            return BaselineToolCalls(calls=calls)
        return BaselineText(text=message.content or "")
