"""Fixed literal-argv bridge for the pinned debugger; own inferior, Docker only."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys


def main():
    path=Path('/work/debug-argv.json')
    if sys.argv[1:]!=[str(path)] or path.is_symlink() or path.stat().st_size>131072:
        raise ValueError('invalid_argv_manifest')
    value=json.loads(path.read_text())
    if set(value)!={'executable','sha256','arguments'}:
        raise ValueError('invalid_manifest_fields')
    binary=Path(value['executable'])
    if (binary.parent!=Path('/work/developer-build') or
            not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',binary.name) or
            binary.is_symlink() or not binary.is_file() or binary.stat().st_size>33554432 or
            hashlib.sha256(binary.read_bytes()).hexdigest()!=value['sha256']):
        raise ValueError('invalid_own_executable')
    arguments=value['arguments']
    if (not isinstance(arguments,list) or len(arguments)>16 or
            any(not isinstance(p,str) or len(p.encode())>4096 or any(c in p for c in '\0\n\r') for p in arguments)):
        raise ValueError('invalid_literal_arguments')
    environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','HOME':'/work/debug-home'}
    os.execve(binary,[str(binary),*arguments],environment)


if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'argv_launcher_error':type(error).__name__}))
        raise SystemExit(96)
