"""Use the upstream JSON Schema validator, plus exact inventory/input accounting."""
from pathlib import Path
import jsonschema
from evidence import read_json, GateError

def validate(root: Path, kind: str, value):
    try:
        jsonschema.Draft202012Validator(read_json(root/'schemas'/f'{kind}.json')).validate(value)
    except jsonschema.ValidationError as exc:
        raise GateError('schema '+kind+': '+exc.message) from exc
    return True
