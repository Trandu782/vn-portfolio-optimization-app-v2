"""Unit tests for the generic Registry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from core.registry import Registry, RegistryInfo


class _SampleParams(BaseModel):
    window: int = 20
    annualize: bool = True


class _Covariance:
    """Minimal base class used as the registry's element type in these tests."""


def _make_registry() -> Registry[_Covariance]:
    registry: Registry[_Covariance] = Registry()

    @registry.register(
        id="sample",
        name="Sample covariance",
        description="Plain historical sample covariance.",
        parameter_schema=_SampleParams,
    )
    class Sample(_Covariance):
        pass

    return registry


def test_register_and_get_returns_implementation() -> None:
    registry = _make_registry()
    assert registry.get("sample").__name__ == "Sample"


def test_list_returns_registered_ids_in_order() -> None:
    registry = _make_registry()

    @registry.register(id="other", name="Other", description="Another one.")
    class Other(_Covariance):
        pass

    assert registry.list() == ["sample", "other"]


def test_describe_returns_id_name_description_and_schema() -> None:
    registry = _make_registry()
    [info] = registry.describe()

    assert isinstance(info, RegistryInfo)
    assert info.id == "sample"
    assert info.name == "Sample covariance"
    assert info.description == "Plain historical sample covariance."
    assert info.parameter_schema is not None
    assert info.parameter_schema["properties"]["window"]["default"] == 20


def test_describe_without_parameter_schema_returns_none() -> None:
    registry: Registry[object] = Registry()

    @registry.register(id="no_params", name="No params", description="No schema.")
    class NoParams:
        pass

    [info] = registry.describe()
    assert info.parameter_schema is None


def test_duplicate_id_raises_value_error() -> None:
    registry = _make_registry()

    with pytest.raises(ValueError, match="already registered"):

        @registry.register(id="sample", name="Duplicate", description="Clash.")
        class Duplicate(_Covariance):
            pass


def test_unknown_id_raises_key_error() -> None:
    registry = _make_registry()
    with pytest.raises(KeyError):
        registry.get("does-not-exist")
