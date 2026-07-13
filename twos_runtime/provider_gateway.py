from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AIModel, Provider
from .policy import CONNECTOR_STATUSES


class ProviderExecutionUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderHealth:
    provider_name: str
    status: str
    available: bool
    reason: str


class ProviderAdapter(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def list_models(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> ProviderHealth:
        raise NotImplementedError

    @abstractmethod
    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class MetadataProviderAdapter(ProviderAdapter):
    """Registry-backed adapter that never represents an external call as active."""

    def __init__(self, provider: Provider, models: list[AIModel]) -> None:
        self.provider = provider
        self.models = models

    @property
    def provider_name(self) -> str:
        return self.provider.name

    def list_models(self) -> list[dict[str, Any]]:
        return [
            {
                "model_name": model.model_name,
                "capability_tags": json.loads(model.capability_tags),
                "status": model.status,
            }
            for model in self.models
        ]

    def health_check(self) -> ProviderHealth:
        status = self.provider.status if self.provider.status in CONNECTOR_STATUSES else "failed"
        available = self.provider.enabled and status in {"healthy", "degraded"}
        reason = self.provider.details or "No provider health detail recorded."
        if not available and status == "unconfigured":
            reason = "Provider is unconfigured; no external request can be made."
        return ProviderHealth(self.provider.name, status, available, reason)

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        raise ProviderExecutionUnavailable(
            f"{self.provider.name} has metadata only; no external execution adapter is configured."
        )


class ProviderGateway:
    def __init__(self, adapters: list[ProviderAdapter]) -> None:
        self._adapters = {adapter.provider_name: adapter for adapter in adapters}

    @classmethod
    def from_session(cls, session: Session) -> "ProviderGateway":
        providers = session.scalars(select(Provider).where(Provider.kind == "model").order_by(Provider.id)).all()
        models = session.scalars(select(AIModel).order_by(AIModel.id)).all()
        models_by_provider: dict[int, list[AIModel]] = {}
        for model in models:
            models_by_provider.setdefault(model.provider_id, []).append(model)
        return cls(
            [MetadataProviderAdapter(provider, models_by_provider.get(provider.id, [])) for provider in providers]
        )

    def adapters(self) -> list[ProviderAdapter]:
        return list(self._adapters.values())

    def get(self, provider_name: str) -> ProviderAdapter | None:
        return self._adapters.get(provider_name)

    def health_snapshot(self) -> dict[str, ProviderHealth]:
        return {name: adapter.health_check() for name, adapter in self._adapters.items()}
