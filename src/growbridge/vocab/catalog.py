"""Loading and checking the variable catalog (``catalog.toml``).

The catalog is append-only: an entry's defining fields never change once released, which
``catalog.lock.json`` pins. Names resolve exactly, with no fuzzy matching.
"""

import functools
import hashlib
import re
import tomllib
from collections.abc import Mapping
from importlib import resources
from types import MappingProxyType
from typing import Any, Literal

from pydantic import ValidationError

from growbridge.archive.ids import content_digest
from growbridge.archive.models import Model

QUANTITIES = frozenset(
    {
        "temperature",
        "relative_humidity",
        "pressure",
        "concentration",
        "photon_flux_density",
        "area_growth_rate",
        "length",
        "mass",
        "level",
        "count",
        "score",
    }
)
DEFINING_FIELDS = ("id", "kind", "quantity", "unit", "method", "min", "max")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


class CatalogError(ValueError):
    pass


class Variable(Model):
    id: str
    kind: Literal["manual", "sensor", "factor"]
    label_en: str
    label_zh: str
    quantity: str
    unit: str
    method: str = ""
    min: float | None = None
    max: float | None = None
    aliases: tuple[str, ...] = ()
    deprecated: bool = False
    replaced_by: str | None = None
    refs: tuple[str, ...] = ()

    def defining_digest(self) -> str:
        return content_digest({name: getattr(self, name) for name in DEFINING_FIELDS})


class Catalog:
    """An immutable, validated catalog. Build it with ``load_catalog``."""

    __slots__ = ("_by_alias", "_by_id", "digest", "unit_aliases", "variables", "version")

    def __init__(
        self,
        version: int,
        digest: str,
        unit_aliases: Mapping[str, str],
        variables: tuple[Variable, ...],
    ) -> None:
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "digest", digest)
        object.__setattr__(self, "unit_aliases", MappingProxyType(dict(unit_aliases)))
        object.__setattr__(self, "variables", variables)
        object.__setattr__(self, "_by_id", {v.id: v for v in variables})
        object.__setattr__(self, "_by_alias", {a: v for v in variables for a in v.aliases})

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Catalog is immutable")

    def get(self, variable_id: str) -> Variable | None:
        return self._by_id.get(variable_id)

    def resolve(self, name: str) -> Variable | None:
        return self._by_id.get(name) or self._by_alias.get(name)

    def canonical(self, name: str) -> str | None:
        variable = self.resolve(name)
        return variable.id if variable else None

    def same(self, a: str, b: str) -> bool:
        first, second = self.canonical(a), self.canonical(b)
        if first is None and second is None:
            return a == b
        return first == second


def _entry(raw: Any, index: int) -> Variable:
    label = raw.get("id", f"entry #{index}") if isinstance(raw, dict) else f"entry #{index}"
    try:
        return Variable.model_validate(raw)
    except ValidationError as exc:
        raise CatalogError(f"{label}: {exc}") from exc


def _check_entries(variables: list[Variable]) -> None:
    ids: set[str] = set()
    for variable in variables:
        if not ID_PATTERN.match(variable.id):
            raise CatalogError(f"{variable.id}: id must match {ID_PATTERN.pattern}")
        if variable.id in ids:
            raise CatalogError(f"{variable.id}: duplicate id")
        ids.add(variable.id)
    aliases: set[str] = set()
    for variable in variables:
        _check_variable(variable, ids)
        for alias in variable.aliases:
            if alias in ids:
                raise CatalogError(f"{variable.id}: alias {alias} equals a variable id")
            if alias in aliases:
                raise CatalogError(f"{variable.id}: duplicate alias {alias}")
            aliases.add(alias)


def _check_variable(variable: Variable, ids: set[str]) -> None:
    name = variable.id
    if variable.quantity not in QUANTITIES:
        raise CatalogError(f"{name}: unknown quantity {variable.quantity}")
    if variable.kind == "manual" and not variable.method:
        raise CatalogError(f"{name}: a manual entry needs a method")
    if variable.aliases and variable.kind != "sensor":
        raise CatalogError(f"{name}: only sensor entries have aliases")
    if variable.replaced_by is not None:
        if not variable.deprecated:
            raise CatalogError(f"{name}: replaced_by needs deprecated = true")
        if variable.replaced_by not in ids:
            raise CatalogError(f"{name}: replaced_by {variable.replaced_by} is not in the catalog")
    if variable.min is not None and variable.max is not None and variable.min > variable.max:
        raise CatalogError(f"{name}: min is above max")


def load_catalog(text: str) -> Catalog:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CatalogError(f"catalog is not valid TOML: {exc}") from exc
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise CatalogError("catalog version must be a positive integer")
    units = data.get("unit_aliases", {})
    if not isinstance(units, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in units.items()
    ):
        raise CatalogError("unit_aliases must map text to text")
    entries = data.get("variable", [])
    if not isinstance(entries, list):
        raise CatalogError("variable must be an array of tables")
    variables = [_entry(raw, index) for index, raw in enumerate(entries, start=1)]
    _check_entries(variables)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Catalog(version, digest, units, tuple(sorted(variables, key=lambda v: v.id)))


def packaged_text() -> str:
    return resources.files("growbridge.vocab").joinpath("catalog.toml").read_text("utf-8")


@functools.cache
def packaged_catalog() -> Catalog:
    return load_catalog(packaged_text())
