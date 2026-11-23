from __future__ import annotations

from app.core.config import settings
from app.model.base import ModelConfig, ModelError, ModelProvider
from app.model.deepseek import DeepSeekProvider

PROVIDER_CLASSES: dict[str, type[DeepSeekProvider]] = {
    "deepseek": DeepSeekProvider,
}


class ModelRegistry:
    """按配置创建统一的模型提供者实例。"""

    def __init__(self) -> None:
        self._cache: dict[str, ModelProvider] = {}

    @staticmethod
    def config_for(
        *, model: str | None = None, temperature: float = 0.5, max_tokens: int | None = None
    ) -> ModelConfig:
        return ModelConfig(
            provider="deepseek",
            model=model or settings.deepseek_model,
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
            temperature=temperature,
            max_tokens=max_tokens or settings.max_output_tokens,
            thinking_enabled=settings.deepseek_thinking_enabled,
            timeout_seconds=60.0,
        )

    def create(self, config: ModelConfig) -> ModelProvider:
        provider_cls = PROVIDER_CLASSES.get(config.provider)
        if provider_cls is None:
            raise ModelError(f"不支持的模型供应商：{config.provider}", kind="config_error")
        return provider_cls(config)

    def get(
        self,
        *,
        model: str | None = None,
        temperature: float = 0.5,
        max_tokens: int | None = None,
    ) -> ModelProvider:
        key = f"{model or settings.deepseek_model}:{temperature}:{max_tokens or settings.max_output_tokens}"
        provider = self._cache.get(key)
        if provider is None:
            provider = self.create(
                self.config_for(model=model, temperature=temperature, max_tokens=max_tokens)
            )
            self._cache[key] = provider
        return provider


model_registry = ModelRegistry()
