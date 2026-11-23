"""Generic registry used to make every variable concept pluggable.

Each registered implementation is described by an ``id``, a display ``name``, a
``description`` and an optional Pydantic parameter schema. The API publishes
``describe()`` output so the UI can render available options without hardcoding
them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

type IdList = list[str]


@dataclass(frozen=True)
class RegistryInfo:
    """Public metadata describing a single registry entry."""

    id: str
    name: str
    description: str
    parameter_schema: dict[str, Any] | None


type InfoList = list[RegistryInfo]


class Registry[T]:
    """A registry mapping stable ids to implementation classes of type ``T``."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[str, str, dict[str, Any] | None, type[T]]] = {}

    def register(
        self,
        *,
        id: str,
        name: str,
        description: str,
        parameter_schema: type[BaseModel] | None = None,
    ) -> Callable[[type[T]], type[T]]:
        """Return a decorator that registers the wrapped class under ``id``.

        Args:
            id: Stable identifier used by the API and the UI.
            name: Human-readable display name.
            description: Short explanation of what the implementation does.
            parameter_schema: Optional Pydantic model describing its parameters.
                Its JSON schema is exposed through :meth:`describe`.

        Raises:
            ValueError: If ``id`` is already registered.
        """
        if id in self._entries:
            raise ValueError(f"An entry with id {id!r} is already registered")

        schema = parameter_schema.model_json_schema() if parameter_schema is not None else None

        def decorator(cls: type[T]) -> type[T]:
            self._entries[id] = (name, description, schema, cls)
            return cls

        return decorator

    def get(self, id: str) -> type[T]:
        """Return the implementation registered under ``id``.

        Raises:
            KeyError: If ``id`` is unknown.
        """
        try:
            return self._entries[id][3]
        except KeyError:
            raise KeyError(f"Unknown id {id!r}") from None

    def list(self) -> IdList:
        """Return the registered ids in registration order."""
        return list(self._entries)

    def describe(self) -> InfoList:
        """Return metadata for every registered entry."""
        return [
            RegistryInfo(id=entry_id, name=name, description=description, parameter_schema=schema)
            for entry_id, (name, description, schema, _) in self._entries.items()
        ]
