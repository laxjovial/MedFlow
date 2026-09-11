"""Shared (de)serialization machinery for domain models.

Every model can round-trip itself to a plain dict for the storage layer,
the export engine, and the sync engine. Datetime fields are declared once
per class via ``@serializable(...)`` and handled automatically; unknown
keys in incoming rows are dropped so the storage layer can gain columns
without breaking older model versions.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, TypeVar

from app.utils.dates import to_iso, from_iso

M = TypeVar("M")


def serializable(*datetime_fields: str | None):
    """Class decorator attaching ``to_row()``/``from_row()`` to a dataclass.

    ``None`` entries are ignored, so a model with no datetimes can simply
    use ``@serializable(None)`` (or nothing at all) and still receive the
    generic dict round-trip.
    """

    fields = tuple(name for name in datetime_fields if name)

    def apply(cls: type[M]) -> type[M]:
        def to_row(self) -> dict[str, Any]:
            data = asdict(self)
            for name in fields:
                value = getattr(self, name)
                data[name] = to_iso(value) if isinstance(value, datetime) else value
            return data

        @classmethod
        def from_row(cls: type[M], row: dict[str, Any]) -> M:
            row = dict(row)
            for name in fields:
                value = row.get(name)
                row[name] = from_iso(value) if isinstance(value, str) else value
            known = set(cls.__dataclass_fields__)
            return cls(**{k: v for k, v in row.items() if k in known})

        cls.to_row = to_row
        cls.from_row = from_row
        return cls

    return apply
