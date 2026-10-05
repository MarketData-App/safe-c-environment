"""Typed, finite scratch CMake inputs for developer qualification only."""
from pathlib import Path
import hashlib
import json

from evidence import GateError, read_json, file_hash
from schema_check import validate

DEFAULT = {'schema_version':1,'primary':'candidate.c','extra':False,
           'generated_value':0,'define_value':0}


def descriptor(root,directory):
    if any(p.is_symlink() for p in [directory,*directory.parents]):
        raise GateError('developer demo workspace link rejected')
    context=directory/'context.json'
    value=read_json(context) if context.is_file() else dict(DEFAULT)
    validate(root,'developer-workspace',value)
    wanted={value['primary']}
    if value['extra']:wanted.add('extra.c')
    if context.is_file():wanted.add('context.json')
    actual=set()
    total=0
    for path in directory.rglob('*'):
        if path.is_symlink():raise GateError('developer demo input link rejected')
        if path.is_dir():continue
        if not path.is_file():raise GateError('developer demo special input rejected')
        actual.add(str(path.relative_to(directory)))
        size=path.stat().st_size
        total+=size
        if size>1048576 or total>4194304 or len(actual)>4:
            raise GateError('developer demo input budget exceeded')
    if actual!=wanted:raise GateError('developer demo input registration is missing or ambiguous')
    return value,{name:file_hash(directory/name) for name in sorted(actual)}


def identity(files):
    return hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
