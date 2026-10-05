"""Finite test-only source transformations; never modify shipping inputs.

The protected recipe and source inventory bind each generated translation unit.
No arbitrary patch, source path, output path or compiler flags are accepted.
"""
from pathlib import Path
import hashlib,json,sys

def main():
    if len(sys.argv)!=3:raise ValueError('typed_mutant_arguments')
    name,directory=sys.argv[1:]
    definitions=json.loads(Path('/src/safety/foundation-mutants.json').read_text())
    if name not in definitions['mutants']:raise ValueError('inventoried_mutant_required')
    output=Path(directory)
    if not output.is_relative_to('/work/build') or '..' in output.parts:raise ValueError('owned_mutant_destination_required')
    source=Path('/src/foundation/src/sc-foundation.c')
    original=source.read_text();current=hashlib.sha256(source.read_bytes()).hexdigest()
    inventory=json.loads(Path('/src/safety/source-inventory.json').read_text())
    if current!=inventory['files']['foundation/src/sc-foundation.c']['sha256']:raise ValueError('source_identity_changed')
    text=original
    def change(before,after,count=1):
        nonlocal text
        if text.count(before)!=count:raise ValueError('mutant_anchor_changed')
        text=text.replace(before,after,count)
    if name=='index-guard':
        change('if (index >= (gsize)list->values->len) {\n        return fail(error, SC_ERROR_RANGE, "list index");\n    }','if (index >= (gsize)list->values->len) {\n        return TRUE;\n    }',3)
    elif name=='list-destroy':
        change('g_ptr_array_new_with_free_func(release_bytes)','g_ptr_array_new_with_free_func(NULL)')
    elif name=='list-retain':
        change('g_ptr_array_add(list->values, g_bytes_ref(value));','g_ptr_array_add(list->values, value);')
    elif name=='map-key':
        change('gchar *owned_key = g_strndup(key, length);',"gchar *owned_key = g_strnfill(length, 'X');")
    elif name=='empty-region':
        change('return offset <= total && length <= total - offset;','return length != 0 && offset <= total && length <= total - offset;')
    elif name=='arithmetic-publication':
        change('if (out == NULL || !g_size_checked_add(&result, a, b)) {\n        return FALSE;','if (out == NULL || !g_size_checked_add(&result, a, b)) {\n        if (out != NULL) { *out = 0; }\n        return FALSE;')
    elif name=='signed-conversion':
        change('if (out == NULL || length < 0)', 'if (out == NULL)')
    elif name=='text-validation':
        change('if (length != 0 &&\n        (memchr', 'if (FALSE && length != 0 &&\n        (memchr')
    elif name in {'growth-order','text-cap'}:
        before='if (!sc_size_add(text->value->len, length, &next) || !sc_size_add(next, 1, &terminated) ||\n        next > text->maximum)'
        if name=='text-cap':
            change(before,before.replace('next > text->maximum','next >= text->maximum'))
        else:
            change('        next > text->maximum)', '        FALSE)')
            anchor='    if (!text_span(data, length, error)) {\n        return FALSE;\n    }\n    if (length != 0) {\n        g_string_append_len(text->value, data, (gssize)length);\n    }'
            change(anchor,anchor+'\n    if (next > text->maximum) { return fail(error, SC_ERROR_LIMIT, "text limit"); }')
    elif name=='pending-error':
        start=text.index('gboolean sc_text_append(');end=text.index('\ngsize sc_text_length',start)
        fragment=text[start:end]
        changed=fragment.replace('if (!ready(error)) {\n        return FALSE;','if (!ready(error)) {\n        return TRUE;',1)
        if fragment==changed:raise ValueError('mutant_anchor_changed')
        text=text[:start]+changed+text[end:]
    elif name=='assertion-only':
        change('return offset <= total && length <= total - offset;','g_assert(offset <= total && length <= total - offset);\n    (void)offset; (void)length; (void)total;\n    return TRUE;')
    else:raise ValueError('unknown_mutant_recipe')
    if text==original:raise ValueError('mutation_not_applied')
    output.mkdir(parents=True,exist_ok=True)
    path=output/'sc-foundation-mutant.c';path.write_text(text)
    record={'status':'PASS','mutant':name,'original_source':'foundation/src/sc-foundation.c','source_sha256':current,'generated_source':str(path),'generated_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'recipe_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (output/'mutation.json').write_text(json.dumps(record,sort_keys=True)+'\n')
    print(json.dumps({'case_id':name,'verdict':'GENERATED','file_path':str(path)}))
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'verdict':'BLOCKED','error_type':type(error).__name__}));raise SystemExit(2)
