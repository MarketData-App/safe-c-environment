"""Narrow test-source adaptation for strict UBSan function-signature checks.

GTest's fixture ABI is void(gpointer,gconstpointer). Register typed forwarding
functions instead of converting void(void), data-only or typed-fixture functions
to that ABI. Test bodies/inputs/assertions are unchanged. A separately inventoried GBytes
callback bridge fixes the same ABI mismatch in the actual library.
This deliberately does not approve GTest as an application-facing facility.
"""
import re

TOKEN = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[A-Za-z_]\w*|\S', re.S)
METHODS = {'g_test_add_func': 2, 'g_test_add_data_func': 3,
           'g_test_add_data_func_full': 4, 'g_test_add': 6, 'add_array_test': 3}

# ABI adapters for callbacks in the selected tests, not library changes.
CALLBACK_TYPES = {
    'GDestroyNotify': ('void', [('gpointer', 'data')]),
    'GHashFunc': ('guint', [('gconstpointer', 'data')]),
    'GEqualFunc': ('gboolean', [('gconstpointer', 'a'), ('gconstpointer', 'b')]),
    'GCompareFunc': ('gint', [('gconstpointer', 'a'), ('gconstpointer', 'b')]),
    'GCompareDataFunc': ('gint', [('gconstpointer', 'a'), ('gconstpointer', 'b'), ('gpointer', 'data')]),
    'GCopyFunc': ('gpointer', [('gconstpointer', 'data'), ('gpointer', 'user_data')]),
    'GFunc': ('void', [('gpointer', 'data'), ('gpointer', 'user_data')]),
    'GHFunc': ('void', [('gpointer', 'key'), ('gpointer', 'value'), ('gpointer', 'data')]),
    'GHRFunc': ('gboolean', [('gpointer', 'key'), ('gpointer', 'value'), ('gpointer', 'data')]),
}
CALLBACK_APIS = {
    'g_bytes_new_with_free_func': {2: 'GDestroyNotify'},
    'g_array_set_clear_func': {1: 'GDestroyNotify'},
    'g_array_sort': {1: 'GCompareFunc'},
    'g_array_sort_with_data': {1: 'GCompareDataFunc'},
    'g_array_binary_search': {2: 'GCompareFunc'},
    'g_byte_array_sort': {1: 'GCompareFunc'},
    'g_byte_array_sort_with_data': {1: 'GCompareDataFunc'},
    'g_ptr_array_sort': {1: 'GCompareFunc'},
    'g_ptr_array_sort_values': {1: 'GCompareFunc'},
    'g_ptr_array_sort_with_data': {1: 'GCompareDataFunc'},
    'g_ptr_array_sort_values_with_data': {1: 'GCompareDataFunc'},
    'g_ptr_array_find_with_equal_func': {2: 'GEqualFunc'},
    'g_ptr_array_foreach': {1: 'GFunc'},
    'g_ptr_array_copy': {1: 'GCopyFunc'},
    'g_ptr_array_extend': {2: 'GCopyFunc'},
    'g_ptr_array_new_from_array': {2: 'GCopyFunc', 4: 'GDestroyNotify'},
    'g_ptr_array_new_from_null_terminated_array': {1: 'GCopyFunc', 3: 'GDestroyNotify'},
    'g_ptr_array_new_take': {2: 'GDestroyNotify'},
    'g_ptr_array_new_take_null_terminated': {1: 'GDestroyNotify'},
    'g_ptr_array_new_null_terminated': {1: 'GDestroyNotify'},
    'g_ptr_array_new_full': {1: 'GDestroyNotify'},
    'g_ptr_array_new_with_free_func': {0: 'GDestroyNotify'},
    'g_ptr_array_set_free_func': {1: 'GDestroyNotify'},
    'g_tree_new': {0: 'GCompareFunc'},
    'g_tree_new_with_data': {0: 'GCompareDataFunc'},
    'g_tree_new_full': {0: 'GCompareDataFunc', 2: 'GDestroyNotify', 3: 'GDestroyNotify'},
    'g_hash_table_new': {0: 'GHashFunc', 1: 'GEqualFunc'},
    'g_hash_table_new_full': {0: 'GHashFunc', 1: 'GEqualFunc', 2: 'GDestroyNotify', 3: 'GDestroyNotify'},
    'g_hash_table_find': {1: 'GHRFunc'},
    'g_hash_table_foreach': {1: 'GHFunc'},
    'g_hash_table_foreach_remove': {1: 'GHRFunc'},
    'g_hash_table_foreach_steal': {1: 'GHRFunc'},
}

def adapt_callbacks(source):
    tokens = [(m.group(), m.start(), m.end()) for m in TOKEN.finditer(source)
              if not m.group().startswith(('/*', '//'))]
    definitions = {}
    depth = 0
    current = None
    for i, (token, left, right) in enumerate(tokens):
        if token == '{':
            if depth == 0 and i > 0 and tokens[i - 1][0] == ')':
                paren = 1
                j = i - 2
                while j >= 0 and paren:
                    paren += (tokens[j][0] == ')') - (tokens[j][0] == '(')
                    j -= 1
                current = tokens[j][0] if j >= 0 else None
            depth += 1
        elif token == '}':
            depth -= 1
            if depth == 0 and current:
                definitions[current] = right
                current = None
    edits = []
    bridges = {}
    insertions = {}
    for i, (name, start, _) in enumerate(tokens):
        if name not in CALLBACK_APIS or i + 1 >= len(tokens) or tokens[i + 1][0] != '(':
            continue
        depth = 0
        begin = tokens[i + 1][2]
        args = []
        for token, left, right in tokens[i + 1:]:
            if token == '(':
                depth += 1
            elif token == ')':
                depth -= 1
                if depth == 0:
                    args.append((begin, left))
                    break
            elif token == ',' and depth == 1:
                args.append((begin, left))
                begin = right
        for arg_index, abi in CALLBACK_APIS[name].items():
            if arg_index >= len(args):
                raise ValueError('upstream_callback_argument_missing')
            left, right = args[arg_index]
            argument = source[left:right].strip()
            if argument in {'NULL', '0'}:
                continue
            expression = re.sub(r'^\(\s*\w+\s*\)\s*', '', argument)
            conditional = re.fullmatch(r'(\w+)\s*\?\s*(\w+)\s*:\s*(\w+)', expression)
            functions = list(conditional.groups()[1:]) if conditional else [expression]
            if any(not re.fullmatch(r'[A-Za-z_]\w*', f) for f in functions):
                raise ValueError('unapproved_upstream_callback_expression')
            replacements = []
            for function in functions:
                key = (function, abi)
                if key not in bridges:
                    bridge = f'sc_qualified_callback_{len(bridges)}'
                    bridges[key] = bridge
                    result, parameters = CALLBACK_TYPES[abi]
                    arguments = [arg for _, arg in parameters]
                    # Upstream deliberately casts one-argument g_strdup as GCopyFunc.
                    if function == 'g_strdup' and abi == 'GCopyFunc':
                        arguments = arguments[:1]
                    text = '\nstatic ' + result + ' ' + bridge + '(' + ', '.join(t + ' ' + n for t, n in parameters) + ') {\n'
                    for _, parameter in parameters:
                        text += '  (void)' + parameter + ';\n'
                    text += '  ' + ('' if result == 'void' else 'return ') + function + '(' + ', '.join(arguments) + ');\n}\n'
                    if function in definitions:
                        position = definitions[function]
                    elif function.startswith(('g_', '_g_')) or function == 'strcmp':
                        match = re.search(r'^static\s', source, re.M)
                        if match is None:
                            raise ValueError('upstream_callback_insertion_missing')
                        position = match.start()
                    else:
                        raise ValueError('upstream_callback_definition_missing')
                    insertions.setdefault(position, []).append(text)
                replacements.append(bridges[key])
            replacement = (f'{conditional.group(1)} ? {replacements[0]} : {replacements[1]}'
                           if conditional else replacements[0])
            edits.append((left, right, replacement))
    edits += [(position, position, ''.join(texts)) for position, texts in insertions.items()]
    for left, right, text in sorted(edits, reverse=True):
        source = source[:left] + text + source[right:]
    return source, len(bridges)

def adapt(source):
    if '(GEqualFunc)_g_variant_type_equal' in source:
        return adapt_callbacks(source)
    if 'g_array_sort (GArray' in source:
        pattern = r'\(GCompareDataFunc\) compare_func,\s*NULL'
        if len(re.findall(pattern, source)) != 2:
            raise ValueError('unexpected_array_compare_patch_scope')
        marker = 'void\ng_array_sort (GArray'
        position = source.rfind('\n/**', 0, source.index(marker))
        bridge = ('\nstatic gint\nsc_qualified_array_compare (gconstpointer a, gconstpointer b, gpointer data)\n'
                  '{\n  GCompareFunc *compare = data;\n  return (*compare) (a, b);\n}\n')
        source = source[:position] + bridge + source[position:]
        source = re.sub(pattern, 'sc_qualified_array_compare, &compare_func', source)
        return source, 1
    if '(GFunc) free_func' in source:
        kind = 'gqueue' if 'g_queue_clear_full' in source else 'gslist' if 'g_slist_free_full' in source else 'glist'
        prefix = {'gqueue': 'g_queue', 'gslist': 'g_slist', 'glist': 'g_list'}[kind]
        parameter = 'queue' if kind == 'gqueue' else 'list'
        old = prefix + '_foreach (' + parameter + ', (GFunc) free_func, NULL);'
        if source.count(old) != (2 if kind == 'gqueue' else 1):
            raise ValueError('unexpected_list_destructor_patch_scope')
        marker = 'void\n' + prefix + '_free_full'
        position = source.rfind('\n/**', 0, source.index(marker))
        bridge = ('\nstatic void\nsc_qualified_list_destroy (gpointer data, gpointer user_data)\n'
                  '{\n  GDestroyNotify *destroy = user_data;\n  (*destroy) (data);\n}\n')
        source = source[:position] + bridge + source[position:]
        source = source.replace(old, prefix + '_foreach (' + parameter + ', sc_qualified_list_destroy, &free_func);')
        return source, 1
    if 'g_test_suite_free (GTestSuite *suite)' in source:
        marker = 'void\ng_test_suite_free (GTestSuite *suite)'
        position = source.rfind('\n/**', 0, source.index(marker))
        bridges = []
        for suffix in ['case', 'suite']:
            function = 'g_test_' + suffix + '_free'
            pattern = r'\(GDestroyNotify\)\s*' + function
            if len(re.findall(pattern, source)) != 1:
                raise ValueError('unexpected_gtest_destructor_patch_scope')
            bridge = 'sc_qualified_test_' + suffix + '_destroy'
            source = re.sub(pattern, bridge, source)
            bridges.append('static void\n' + bridge + '(gpointer data)\n{\n  ' + function + '(data);\n}\n')
        source = source[:position] + '\n' + '\n'.join(bridges) + source[position:]
        return source, 2
    if '(GDestroyNotify)g_bytes_unref' in source and 'g_bytes_new_from_bytes' in source:
        # A real library ABI defect: passing void(GBytes*) as void(gpointer).
        # Keep exported signatures and allocation/refcount behavior unchanged.
        marker = 'GBytes *\ng_bytes_new_from_bytes'
        if source.count(marker) != 1 or source.count('(GDestroyNotify)g_bytes_unref') != 1 or source.count('(gpointer)g_bytes_unref') != 1:
            raise ValueError('unexpected_gbytes_callback_patch_scope')
        bridge = ('static void\nsc_qualified_bytes_unref_notify (gpointer data)\n'
                  '{\n  g_bytes_unref (data);\n}\n\n')
        position = source.rfind('\n/**', 0, source.index(marker))
        source = source[:position] + '\n' + bridge + source[position:]
        source = source.replace('(GDestroyNotify)g_bytes_unref', 'sc_qualified_bytes_unref_notify')
        source = source.replace('(gpointer)g_bytes_unref', 'sc_qualified_bytes_unref_notify')
        return source, 1
    source, callback_count = adapt_callbacks(source)
    # The pinned array suite registers callbacks through one typed helper.
    # Preserve that helper's path construction and give its callback the
    # fixture ABI; adapt its concrete call sites below.
    source, helper_count = re.subn(r'GTestDataFunc(\s+)test_func',
                                  r'GTestFixtureFunc\1test_func', source)
    if helper_count > 1:
        raise ValueError('unexpected_upstream_registration_helper')
    tokens = [(m.group(), m.start(), m.end()) for m in TOKEN.finditer(source)
              if not m.group().startswith(('/*', '//'))]
    edits = []
    wrappers = []
    for index, (name, start, _) in enumerate(tokens):
        if name not in METHODS or index + 1 >= len(tokens) or tokens[index + 1][0] != '(':
            continue
        depth = 0
        args = []
        begin = tokens[index + 1][2]
        end = None
        for token, left, right in tokens[index + 1:]:
            if token == '(':
                depth += 1
            elif token == ')':
                depth -= 1
                if depth == 0:
                    args.append(source[begin:left].strip())
                    end = right
                    break
            elif token == ',' and depth == 1:
                args.append(source[begin:left].strip())
                begin = right
        if end is None or len(args) != METHODS[name]:
            raise ValueError('unsupported_upstream_test_registration')
        if name == 'add_array_test' and not re.fullmatch(r'[A-Za-z_]\w*', args[2]):
            continue
        number = len(edits)
        if helper_count and name == 'g_test_add_data_func' and args[2] == 'test_func':
            edits.append((start, end,
                          f'g_test_add_vtable({args[0]}, 0, {args[1]}, NULL, test_func, NULL)'))
            continue
        def forward(function, arguments, suffix):
            if function == 'NULL':
                return 'NULL'
            if not re.fullmatch(r'[A-Za-z_]\w*', function):
                raise ValueError('unapproved_test_callback_indirection')
            bridge = f'sc_qualified_test_{number}_{suffix}'
            wrappers.append('static void ' + bridge + '(gpointer fixture, gconstpointer data) {\n'
                            '  (void)fixture;\n  (void)data;\n  ' + function + '(' + arguments + ');\n}\n')
            return bridge
        if name == 'g_test_add_func':
            test = forward(args[1], '', 'test')
            replacement = f'g_test_add_vtable({args[0]}, 0, NULL, NULL, {test}, NULL)'
        elif name.startswith('g_test_add_data_func') or name == 'add_array_test':
            test = forward(args[2], 'data', 'test')
            destroy = forward(args[3], '(gpointer)data', 'destroy') if len(args) == 4 else 'NULL'
            replacement = (f'add_array_test({args[0]}, {args[1]}, {test})' if name == 'add_array_test' else
                           f'g_test_add_vtable({args[0]}, 0, {args[1]}, NULL, {test}, {destroy})')
        else:
            setup = forward(args[3], 'fixture, data', 'setup')
            test = forward(args[4], 'fixture, data', 'test')
            destroy = forward(args[5], 'fixture, data', 'destroy')
            replacement = f'g_test_add_vtable({args[0]}, sizeof({args[1]}), {args[2]}, {setup}, {test}, {destroy})'
        edits.append((start, end, replacement))
    if not edits:
        raise ValueError('upstream_test_registration_inventory_empty')
    position = re.search(r'\bint\s+main\s*\(', source)
    if position is None:
        raise ValueError('upstream_test_entrypoint_not_found')
    edits.append((position.start(), position.start(), '\n'.join(wrappers) + '\n'))
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source, len(wrappers) + callback_count
