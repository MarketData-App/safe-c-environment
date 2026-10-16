"""Finite test-only transformations of foundation/parallel/sc-parallel.c; never modify shipping inputs."""
from pathlib import Path
import hashlib,json,sys

def main():
    if len(sys.argv)!=3:raise ValueError('typed_mutant_arguments')
    name,directory=sys.argv[1:]
    definitions=json.loads(Path('/src/safety/parallel-mutants.json').read_text())
    if name not in definitions['mutants']:raise ValueError('inventoried_mutant_required')
    output=Path(directory)
    if not output.is_relative_to('/work/build') or '..' in output.parts:raise ValueError('owned_mutant_destination_required')
    source=Path('/src/foundation/parallel/sc-parallel.c');original=source.read_text()
    inventory=json.loads(Path('/src/safety/source-inventory.json').read_text())
    if hashlib.sha256(source.read_bytes()).hexdigest()!=inventory['files']['foundation/parallel/sc-parallel.c']['sha256']:raise ValueError('source_identity_changed')
    text=original
    def change(before,after):
        nonlocal text
        if text.count(before)!=1:raise ValueError('mutant_anchor_changed')
        text=text.replace(before,after,1)
    if name=='plain-stop-read':change('gboolean run = g_atomic_int_get(&s->stop) == 0;','gboolean run = s->stop == 0;')
    elif name=='no-wait-teardown':change('    submit_all(s, pool, config, task_count);\n    g_thread_pool_free(pool, FALSE, TRUE);','    submit_all(s, pool, config, task_count);\n    g_thread_pool_free(pool, TRUE, FALSE);')
    elif name=='accounting-skip':change('    } else {\n        s->skipped++;\n    }','    } else {\n    }')
    output.mkdir(parents=True,exist_ok=True);target=output/'sc-parallel-mutant.c';target.write_text(text)
    receipt={'status':'PASS','mutant':name,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
             'recipe_sha256':hashlib.sha256(Path('/src/container/parallel-mutant.py').read_bytes()).hexdigest(),
             'generated_source':str(target),'generated_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    (output/'mutation.json').write_text(json.dumps(receipt,sort_keys=True))
    return 0

if __name__=='__main__':raise SystemExit(main())
