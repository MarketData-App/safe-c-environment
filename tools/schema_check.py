"""Use the upstream JSON Schema validator, plus exact inventory/input accounting."""
from pathlib import Path
import json
import jsonschema
from evidence import CAPPED_JSON_MAX_BYTES, GateError, load_project_json, read_capped, read_json

# FR3-R10: a validator per exact schema file content, and the outcome per exact (schema content, instance text). The
# schema file is read on every call (so an edited schema is never stale) and parsed through the capped boundary only
# when its bytes are new. An outcome is reused only for a plain JSON instance (exact dict with str keys, list, str, int,
# float, bool, None; no subclass, no tuple) of at most _RESULT_TEXT characters, keyed by its json.dumps text in its own
# key order, so the same instance always gives the same first error. Each cache keeps at most _CACHE_SIZE entries.
_VALIDATORS = {}
_RESULTS = {}
_CACHE_SIZE = 4096
_RESULT_TEXT = 16384
_PLAIN = (str, int, float, bool, type(None))

def _validator(path):
    data = read_capped(path, CAPPED_JSON_MAX_BYTES, 'schema-file', 'schema file')
    key = (str(path), data)
    found = _VALIDATORS.get(key)
    if found is None:
        schema = load_project_json(data, 'schema-file', CAPPED_JSON_MAX_BYTES, label='schema file', finite=False)
        if len(_VALIDATORS) >= _CACHE_SIZE:
            _VALIDATORS.clear()
            _RESULTS.clear()
        found = _VALIDATORS[key] = (key, jsonschema.Draft202012Validator(schema))
    return found          # the stored key: the outcome cache shares its bytes

def _instance_text(value):
    """The json.dumps text of a plain JSON instance, or None (not plain, or too large to keep)."""
    stack = [value]
    nodes = 0
    while stack:
        v = stack.pop()
        nodes += 1
        if nodes > _RESULT_TEXT:
            return None
        t = type(v)
        if t is dict:
            if any(type(k) is not str for k in v):
                return None
            stack.extend(v.values())
        elif t is list:
            stack.extend(v)
        elif t not in _PLAIN:
            return None
    try:
        text = json.dumps(value, separators=(',', ':'))
    except (TypeError, ValueError, RecursionError):
        return None
    return text if len(text) <= _RESULT_TEXT else None

def validate(root: Path, kind: str, value):
    key, validator = _validator(Path(root)/'schemas'/f'{kind}.json')
    text = _instance_text(value)
    if text is not None and (key, text) in _RESULTS:
        message = _RESULTS[(key, text)]
        if message is None:
            return True
        raise GateError('schema '+kind+': '+message)
    try:
        validator.validate(value)
    except jsonschema.ValidationError as exc:
        if text is not None:
            _remember((key, text), exc.message)
        raise GateError('schema '+kind+': '+exc.message) from exc
    if text is not None:
        _remember((key, text), None)
    return True

def _remember(key, message):
    if len(_RESULTS) >= _CACHE_SIZE:
        _RESULTS.clear()
    _RESULTS[key] = message
