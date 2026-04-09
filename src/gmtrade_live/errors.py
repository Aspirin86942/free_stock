"""项目统一错误模型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ServiceError(Exception):
    """对外暴露的结构化业务错误。"""

    code: str
    message: str
    retryable: bool
    context: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
