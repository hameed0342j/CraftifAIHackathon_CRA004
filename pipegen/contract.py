"""The MQTT contract shared by PipeGen, FirmGen and the simulator (see /contracts)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"

SCHEMA_EVENT = "leaklatch/leak_event/v1"
SCHEMA_STATE = "leaklatch/device_state/v1"
SCHEMA_RECEIPT = "leaklatch/receipt/v1"
SCHEMA_COMMAND = "leaklatch/command/v1"

_SCHEMA_FILES = {
    SCHEMA_EVENT: "leak_event.schema.json",
    SCHEMA_STATE: "device_state.schema.json",
    SCHEMA_RECEIPT: "receipt.schema.json",
    SCHEMA_COMMAND: "command.schema.json",
}


def topic(prefix: str, site: str, zone: str, leaf: str) -> str:
    """leaklatch/<site>/zone/<zone>/<event|state|receipt|cmd>"""
    return f"{prefix}/{site}/zone/{zone}/{leaf}"


def iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@lru_cache(maxsize=None)
def _validator(schema_id: str):
    import jsonschema

    schema = json.loads((CONTRACTS / _SCHEMA_FILES[schema_id]).read_text(encoding="utf-8"))
    cls = jsonschema.validators.validator_for(schema)
    return cls(schema, format_checker=cls.FORMAT_CHECKER)


def validate(message: dict) -> None:
    """Raise jsonschema.ValidationError if `message` breaks its declared schema."""
    schema_id = message.get("schema")
    if schema_id not in _SCHEMA_FILES:
        raise ValueError(f"unknown schema {schema_id!r}")
    _validator(schema_id).validate(message)
