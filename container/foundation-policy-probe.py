"""Protected finite API-policy probes, generated only in qualified scratch."""
from pathlib import Path
import json,hashlib,sys

def definitions():
    approved='if (!sc_bytes_copy(NULL, 0, 0, &value, NULL)) { return 1; } return g_bytes_get_size(value) == 0 ? 0 : 2;'
    rows={}
    def add(name,body,rule,macro=''):
        source='#include "sc-foundation.h"\n#include "dependency-identity.h"\n'+macro+'\nint main(void) { '+body+' }\n'
        rows[name]={'source':source,'rule':rule}
    add('approved','g_autoptr(GBytes) value = NULL; '+approved,None)
    add('comment-only','/* g_bytes_new_static and GString.str are text only */ g_autoptr(GBytes) value = NULL; '+approved,None)
    add('direct-static','GBytes *value = g_bytes_new_static("x", 1); g_bytes_unref(value); return 0;','forbidden-glib-api')
    add('macro-static','GBytes *value = MAKE("x", 1); g_bytes_unref(value); return 0;','forbidden-glib-api','#define MAKE(p,n) g_bytes_new_static(p,n)')
    add('direct-take','GBytes *value = g_bytes_new_take(NULL, 0); g_bytes_unref(value); return 0;','forbidden-glib-api')
    add('macro-take','GBytes *value = MAKE(NULL, 0); g_bytes_unref(value); return 0;','forbidden-glib-api','#define MAKE(p,n) g_bytes_new_take(p,n)')
    add('alias-static','GBytes *(*ctor)(gconstpointer, gsize) = g_bytes_new_static; GBytes *value = ctor("x", 1); g_bytes_unref(value); return 0;','forbidden-glib-api')
    add('direct-backing','GString *value = NULL; return value == NULL ? 0 : (int)value->len;','restricted-mutable-type')
    add('macro-backing','GString *value = NULL; return value == NULL ? 0 : (FIELD(value) == NULL ? 0 : 1);','restricted-mutable-type','#define FIELD(x) ((x)->str)')
    add('unchecked-index','GPtrArray *value = NULL; return value == NULL ? 0 : (g_ptr_array_index(value, 0) == NULL ? 0 : 1);','raw-indexing')
    add('raw-allocation','void *value = g_malloc(1); g_free(value); return 0;','unapproved-glib-api')
    add('allocator-hook','g_mem_set_vtable(NULL); return 0;','forbidden-glib-api')
    add('unknown-api','return g_get_monotonic_time() == 0 ? 0 : 1;','unapproved-glib-api')
    add('renamed-application','GString *value = NULL; return value == NULL ? 0 : (int)value->len;','restricted-mutable-type')
    add('ignored-result','GBytes *value = NULL; sc_bytes_copy(NULL, 0, 0, &value, NULL); return 0;','unused-result')
    add('suppression','return 0;','suppression-or-inline-assembly','#define main __attribute__((no_sanitize("address"))) main')
    return rows

def main():
    if len(sys.argv)!=2 or sys.argv[1] not in definitions():raise ValueError('inventoried_policy_probe_required')
    name=sys.argv[1];row=definitions()[name]
    directory=Path('/work/foundation-probes')/name
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'probe.c';path.write_text(row['source'])
    receipt={'id':name,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'rule':row['rule'],'file_path':str(path),'recipe_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (directory/'source.json').write_text(json.dumps(receipt,sort_keys=True)+'\n')
    print(json.dumps(receipt));return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'verdict':'BLOCKED','error_type':type(error).__name__}));raise SystemExit(2)
