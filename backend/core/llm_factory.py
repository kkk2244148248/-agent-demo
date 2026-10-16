"""LLM Factory：优先 DP_Apikey（DeepSeek），OpenAI 兼容接口。"""
from __future__ import annotations

from typing import Type

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from backend.config import get_settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

_AGENT_MODEL_ROUTING = {
    "requirement": "default",
    "vendor_match": "default",
    "compare": "default",
    "reply": "default",
    "factory_brief": "default",
    "intent": "default",
    "quote": "default",
    "followup": "default",
    "summarize": "default",
}


class LLMFactory:
    _instances: dict[str, BaseChatModel] = {}

    @classmethod
    def clear_cache(cls) -> None:
        cls._instances.clear()

    @classmethod
    def get_llm(cls, agent_type: str, temperature: float = 0.2) -> BaseChatModel:
        if agent_type not in _AGENT_MODEL_ROUTING:
            raise ValueError(f"未知 agent_type: {agent_type}")

        settings = get_settings()
        if not settings.use_real_llm:
            from backend.core.mock_llm import MockChatModel

            logger.info(f"llm_factory.mock agent={agent_type}")
            return MockChatModel(agent_type=agent_type)

        model = settings.resolved_llm_model
        cache_key = f"{settings.llm_base_url}_{model}_{temperature}_{settings.resolved_api_key[-8:]}"
        if cache_key not in cls._instances:
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model=model,
                api_key=settings.resolved_api_key,
                base_url=settings.llm_base_url.rstrip("/"),
                temperature=temperature,
            )
            cls._instances[cache_key] = llm
            logger.info(f"llm_factory.ready model={model} base={settings.llm_base_url}")
        return cls._instances[cache_key]

    @classmethod
    def get_structured_llm(
        cls,
        agent_type: str,
        output_schema: Type[BaseModel],
        temperature: float = 0,
    ) -> Runnable:
        llm = cls.get_llm(agent_type, temperature=temperature)
        if hasattr(llm, "with_structured_output"):
            try:
                return llm.with_structured_output(output_schema, method="function_calling")
            except Exception:
                return llm.with_structured_output(output_schema)
        return llm


def get_llm(agent_type: str, temperature: float = 0.2) -> BaseChatModel:
    return LLMFactory.get_llm(agent_type, temperature=temperature)


def get_structured_llm(agent_type: str, output_schema: Type[BaseModel]) -> Runnable:
    return LLMFactory.get_structured_llm(agent_type, output_schema)
