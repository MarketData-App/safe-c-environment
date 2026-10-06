"""Pure parsers of the project source policy: lexer, linemarker attribution,
dependency filter and token stream comparison (tools/project_source.py).

Forbidden spellings are built from fragments so this file does not hold them."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'tools'))
import project_source as ps

US = '_'+'_'
PRAGMA = 'pra'+'gma'
SYSHDR = 'GCC system'+'_header'
NOSAN = 'no'+'_sanitize'


def texts(source):
    return [t.text for t in ps.lex(source).tokens]


class LexerTests(unittest.TestCase):
    def test_line_splice_joins_identifiers(self):
        self.assertEqual(texts('in\\\nt x;'), ['int', 'x', ';'])
        # Compilers accept blanks between the backslash and the newline.
        self.assertEqual(texts('in\\ \t\nt x;'), ['int', 'x', ';'])
        self.assertEqual(texts('in\\\r\nt x;'), ['int', 'x', ';'])

    def test_comment_inside_string_is_not_a_comment(self):
        source = 'const char *a = "/*";\nint b;\nconst char *c = "*/";\n'
        self.assertIn('b', texts(source))
        self.assertNotIn('/*', ps.lex(source).code)

    def test_block_comment_start_inside_line_comment(self):
        source = '// /*\n#'+PRAGMA+' once\n// */\n'
        self.assertEqual(ps.directives(ps.lex(source).tokens)[0][1], PRAGMA)

    def test_line_comment_continues_over_a_splice(self):
        self.assertEqual(texts('// comment \\\nint hidden;\nint x;'), ['int', 'x', ';'])

    def test_string_and_char_literals_with_escapes_and_prefixes(self):
        tokens = ps.lex('a = "q\\"/*"; b = \'\\\'\'; c = u8"x"; d = L\'y\'; e = U"z" u"w";').tokens
        kinds = [(t.kind, t.text) for t in tokens if t.kind in ('string', 'char')]
        self.assertEqual(kinds, [('string', '"q\\"/*"'), ('char', "'\\''"), ('string', 'u8"x"'), ('char', "L'y'"),
                                 ('string', 'U"z"'), ('string', 'u"w"')])
        code = ps.lex('x = "'+NOSAN+'";').code
        self.assertNotIn(NOSAN, code)
        self.assertIn('""', code)

    def test_code_view_keeps_spliced_forbidden_identifier(self):
        code = ps.lex('int f(void) '+US+'attribute'+US+'(('+NOSAN[:5]+'\\\n'+NOSAN[5:]+'("address")));').code
        self.assertIn(NOSAN, code)

    def test_header_names_are_not_comments(self):
        tokens = ps.lex('#include <a//b.h>\n#include "c/*d.h"\nint x;').tokens
        self.assertEqual([t.text for t in tokens if t.kind == 'header'], ['<a//b.h>', '"c/*d.h"'])
        self.assertIn('x', [t.text for t in tokens])

    def test_digraphs_and_trigraphs(self):
        self.assertEqual(texts('%:define X <: :> <% %>'), ['%:', 'define', 'X', '<:', ':>', '<%', '%>'])
        self.assertEqual(texts('?'+'?=define X 1'), ['#', 'define', 'X', '1'])
        # A trigraph backslash splices the line.
        self.assertEqual(texts('in?'+'?/\nt'), ['int'])

    def test_form_feed_and_vertical_tab_before_hash_start_a_directive(self):
        for blank in ('\f', '\v', ' \f\v\t'):
            with self.subTest(blank=repr(blank)):
                found = ps.include_targets(ps.lex(blank+'#include "../review/x.txt"\n').tokens)
                self.assertEqual(found, [(1, 'include', 'quoted', '../review/x.txt')])

    def test_comment_before_hash_still_a_directive(self):
        self.assertEqual(ps.directives(ps.lex('/* c */ # /* c */ '+PRAGMA+' x\n').tokens)[0][1], PRAGMA)

    def test_pp_numbers(self):
        self.assertEqual(texts('0x1e+1 1.5e-3 .5 1p+2'), ['0x1e+1', '1.5e-3', '.5', '1p+2'])

    def test_lines_and_logical_lines(self):
        tokens = ps.lex('a\\\nb c\n/* x\ny */ d\n').tokens
        self.assertEqual([(t.text, t.line, t.logical, t.first) for t in tokens],
                         [('ab', 1, 0, True), ('c', 2, 0, False), ('d', 4, 1, True)])

    def test_unterminated_forms_are_problems(self):
        self.assertTrue(ps.lex('/* open').problems)
        self.assertTrue(ps.lex('x = "open\n').problems)
        self.assertFalse(ps.lex('x = "closed";').problems)


class DirectiveTests(unittest.TestCase):
    def problem(self, source):
        return ps.directive_problem(ps.lex(source).tokens)

    def test_only_pragma_once(self):
        self.assertIsNone(self.problem('#'+PRAGMA+' once\n'))
        self.assertIsNone(self.problem('%:'+PRAGMA+' once\n'))
        self.assertIsNotNone(self.problem('#'+PRAGMA+' once extra\n'))
        self.assertIsNotNone(self.problem('#'+PRAGMA+' '+SYSHDR+'\n'))

    def test_allowlist(self):
        self.assertIsNone(self.problem('#define A 1\n#undef A\n#if 1\n#elif 0\n#else\n#endif\n#ifdef A\n#endif\n#ifndef A\n#endif\n#\n'))
        for name in ('line 3', 'ident "x"', 'warning x', 'elifdef A', 'embed "x"', 'assert x(y)', 'sccs "x"'):
            with self.subTest(name=name):
                self.assertIsNotNone(self.problem('#'+name+'\n'))
        # The GNU linemarker form has no directive name.
        self.assertIsNotNone(self.problem('# 1 "x.h"\n'))

    def test_hidden_pragma_probe_cases(self):
        # Round-3 probes: a /* inside a // comment or a string no longer opens a comment.
        for source in ('// /*\n#'+PRAGMA[:3]+'\\\n'+PRAGMA[3:]+' '+SYSHDR+'\n// */\n',
                       'const char *a = "/*";\n#'+PRAGMA+' '+SYSHDR+'\nconst char *b = "*/";\n'):
            with self.subTest(source=source[:12]):
                self.assertIsNotNone(self.problem(source))

    def test_include_targets(self):
        found = ps.include_targets(ps.lex('#include "a.h"\n#include <b.h>\n#include M\n#include'+'_next <c.h>\n').tokens)
        self.assertEqual(found, [(1, 'include', 'quoted', 'a.h'), (2, 'include', 'angle', 'b.h'),
                                 (3, 'include', None, None), (4, 'include_next', 'angle', 'c.h')])


GCC_OUT = '''# 0 "/src/p/src/a.c"
# 0 "<built-in>"
# 0 "<command-line>"
# 1 "/usr/include/stdc-predef.h" 1 3 4
# 0 "<command-line>" 2
# 1 "/src/p/src/a.c"
# 1 "/src/p/src/../include/a.h" 1
int f(void);
# 2 "/src/p/src/a.c" 2
# 1 "/usr/include/stdio.h" 1 3 4
extern int printf(const char *, ...);
# 3 "/src/p/src/a.c" 2

int f(void) { return 1 <: 0 :> ; }
'''

CLANG_OUT = '''# 1 "/src/p/src/a.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 400 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "/src/p/src/a.c" 2
# 1 "/src/p/include/a.h" 1
int f( void );
# 2 "/src/p/src/a.c" 2
# 1 "/usr/include/stdio.h" 1 3 4
extern int printf(const char *, ...);
# 3 "/src/p/src/a.c" 2


int f(void) { return 1 [ 0 ] ; }
'''

DEPS = ['/src/p/src/a.c', '/src/p/include/a.h', '/usr/include/stdio.h', '/usr/include/stdc-predef.h']


class PreprocessedTests(unittest.TestCase):
    prefixes = ps.origin_prefixes('/src/p')

    def scan(self, text, deps=DEPS):
        return ps.scan_preprocessed(text, '/src/p/src/a.c', self.prefixes, deps)

    def code(self, text):
        return ps.split_origin(self.scan(text)['lines'])[0]

    def test_gcc_and_clang_streams_are_equal(self):
        gcc, clang = self.scan(GCC_OUT), self.scan(CLANG_OUT)
        self.assertEqual(gcc['markers'], [])
        self.assertEqual(clang['markers'], [])
        gcc_code, clang_code = ps.split_origin(gcc['lines'])[0], ps.split_origin(clang['lines'])[0]
        self.assertEqual([(f, t) for f, _l, t in gcc_code], [(f, t) for f, _l, t in clang_code])
        self.assertIsNone(ps.first_difference([('gcc-O0', gcc_code), ('clang-O0', clang_code)]))
        self.assertNotIn('printf', [t for _f, _l, t in gcc_code])
        self.assertEqual(gcc_code[0][:2], ('/src/p/include/a.h', 1))
        self.assertEqual([l for f, l, _t in gcc_code if f.endswith('a.c')][0], 4)

    def test_gcc_system_macro_expansion_markers_are_not_a_problem(self):
        text = GCC_OUT + 'char *p =\n# 5 "/src/p/src/a.c" 3 4\n ((void *)0)\n# 5 "/src/p/src/a.c"\n ;\n'
        scan = self.scan(text)
        self.assertEqual(scan['markers'], [])
        tokens = [t for _f, _l, t in ps.split_origin(scan['lines'])[0]]
        self.assertEqual(tokens[-12:], ['char', '*', 'p', '=', '(', '(', 'void', '*', ')', '0', ')'] + [';'])

    def test_working_directory_marker_is_ignored(self):
        text = GCC_OUT.replace('# 0 "<built-in>"\n', '# 1 "/work/project/strict-gcc-O0//"\n# 0 "<built-in>"\n')
        self.assertEqual(self.scan(text)['markers'], [])

    def test_pragma_attributed_to_project_file(self):
        text = CLANG_OUT + '#'+PRAGMA+' clang diagnostic ignored "-Wconversion"\n#define X 1\n'
        _code, found = ps.split_origin(self.scan(text)['lines'])
        self.assertEqual([(f, l, n) for f, l, n, _r in found], [('/src/p/src/a.c', 6, PRAGMA), ('/src/p/src/a.c', 7, 'define')])
        self.assertEqual(ps.define_stream(found), [('/src/p/src/a.c', 7, '#'), ('/src/p/src/a.c', 7, 'define'),
                                                   ('/src/p/src/a.c', 7, 'X'), ('/src/p/src/a.c', 7, '1')])
        system = CLANG_OUT.replace('extern int printf', '#'+PRAGMA+' GCC visibility push(default)\nextern int printf')
        self.assertEqual(ps.split_origin(self.scan(system)['lines'])[1], [])

    def test_system_header_state_left_on_a_project_file(self):
        # A system_header pragma leaves the file in flag-3 state until it returns or ends.
        text = CLANG_OUT.replace('# 1 "/src/p/include/a.h" 1\n', '# 1 "/src/p/include/a.h" 1\n# 1 "/src/p/include/a.h" 3\n')
        markers = self.scan(text)['markers']
        self.assertEqual([(m[0], m[2]) for m in markers], [('/src/p/include/a.h', 'project file marked as a system header')])
        at_end = CLANG_OUT + '# 9 "/src/p/src/a.c" 3\nint hidden;\n'
        self.assertEqual([m[2] for m in self.scan(at_end)['markers']], ['project file marked as a system header'])
        returned = CLANG_OUT.replace('# 3 "/src/p/src/a.c" 2', '# 3 "/src/p/src/a.c" 2 3')
        self.assertEqual([m[2] for m in self.scan(returned)['markers']], ['project file marked as a system header'])

    def test_project_header_in_a_system_include_directory_is_exempt(self):
        # The AST scan finds project headers through -idirafter: entered with flags 1 3.
        text = CLANG_OUT.replace('# 1 "/src/p/include/a.h" 1\n', '# 1 "/src/p/include/a.h" 1 3\n')
        self.assertEqual(self.scan(text)['markers'], [])
        self.assertIn('f', [t for _f, _l, t in self.code(text)])

    def test_line_directive_rename_is_refused(self):
        text = CLANG_OUT + '# 1 "/usr/include/stdlib.h"\nint hidden;\n'
        markers = self.scan(text)['markers']
        self.assertEqual([(m[0], m[2]) for m in markers], [('/src/p/src/a.c', 'line directive renames a project file')])
        # The renamed lines still count as project origin.
        self.assertIn('hidden', [t for _f, _l, t in self.code(text)])

    def test_entered_file_must_be_a_dependency(self):
        text = CLANG_OUT + '# 1 "/src/p/review/x.h" 1\nint y;\n# 9 "/src/p/src/a.c" 2\n'
        markers = self.scan(text)['markers']
        self.assertEqual([(m[0], m[2]) for m in markers], [('/src/p/review/x.h', 'entered file is not a compiler dependency')])
        # Without a dependency list nothing is checked.
        self.assertEqual(ps.scan_preprocessed(text, '/src/p/src/a.c', self.prefixes)['markers'], [])

    def test_escaped_linemarker_names(self):
        text = '# 1 "/src/p/src/a\\"b.c"\nint x;\n'
        lines = ps.scan_preprocessed(text, '/src/p/src/a"b.c', self.prefixes)['lines']
        self.assertEqual(lines[0][0], '/src/p/src/a"b.c')

    def test_non_project_files_are_not_origin(self):
        prefixes = ps.origin_prefixes('/src')
        self.assertTrue('/src/fuzz/project/x.c'.startswith(prefixes))
        self.assertFalse('/src/fuzz/parser.h'.startswith(prefixes))
        self.assertFalse('/src/foundation/include/sc-foundation.h'.startswith(prefixes))

    def test_directives_only_output_with_comments_and_defines(self):
        # gcc -fdirectives-only keeps comments and (with -dD) definitions; clang drops them.
        gcc = '# 1 "/src/p/src/a.c"\n#define V 1\n/* a\n comment */ int k = V;\n// tail\n'
        clang = '# 1 "/src/p/src/a.c"\n\n\nint k = V;\n'
        a = ps.split_origin(ps.scan_preprocessed(gcc, '/src/p/src/a.c', self.prefixes)['lines'])[0]
        b = ps.split_origin(ps.scan_preprocessed(clang, '/src/p/src/a.c', self.prefixes)['lines'])[0]
        self.assertEqual([t for _f, _l, t in a], ['int', 'k', '=', 'V', ';'])
        self.assertEqual(a[0][1], 3)
        self.assertIsNone(ps.first_difference([('gcc', a), ('clang', b)]))


GCC_MACROS = (
    '#define '+US+'GNUC'+US+' 14\n#define '+US+'INT_MAX'+US+' 0x7fffffff\n#define INT_MAX '+US+'INT_MAX'+US+'\n'
    '#define INT_MIN (-INT_MAX - 1)\n#define '+US+'DBL_MAX'+US+' ((double)1.79769313486231570814527423731704357e+308L)\n'
    '#define DBL_MAX '+US+'DBL_MAX'+US+'\n#define '+US+'FLT_MAX'+US+' 3.40282346638528859811704183484516925e+38F\n'
    '#define NULL ((void *)0)\n#define va_start(v,l) '+US+'builtin_va_start(v,l)\n'
    '#define G_CHECK(major, minor) (('+US+'GNUC'+US+' > (major)) || (minor))\n'
    '#define '+US+'glibc_clang_prereq(maj, min) 0\n#define ONLY_GCC 1\n#define E\n')
CLANG_MACROS = (
    '#define '+US+'GNUC'+US+' 4\n#define '+US+'INT_MAX'+US+' 2147483647\n#define INT_MAX '+US+'INT_MAX'+US+'\n'
    '#define INT_MIN (-'+US+'INT_MAX'+US+' -1)\n#define '+US+'DBL_MAX'+US+' 1.7976931348623157e+308\n'
    '#define DBL_MAX '+US+'DBL_MAX'+US+'\n#define '+US+'FLT_MAX'+US+' 3.40282347e+38F\n'
    '#define NULL ((void*)0)\n#define va_start(ap, param) '+US+'builtin_va_start(ap, param)\n'
    '#define G_CHECK(major, minor) (('+US+'GNUC'+US+' > (major)) || (minor))\n'
    '#define '+US+'glibc_clang_prereq(maj, min) (('+US+'clang_major'+US+' << 16) >= (maj))\n#define E\n')


class MacroTests(unittest.TestCase):
    def test_parse_macros(self):
        table = ps.parse_macros(GCC_MACROS)
        self.assertEqual(table['va_start'], (('v', 'l'), US+'builtin_va_start(v,l)'))
        self.assertEqual(table['E'], (None, ''))
        self.assertEqual(table['NULL'], (None, '((void *)0)'))

    def test_canonical_numbers(self):
        self.assertEqual(ps.canonical_number('0x7fffffff'), ps.canonical_number('2147483647'))
        self.assertEqual(ps.canonical_number('0x7fffffffffffffffL'), ps.canonical_number('9223372036854775807l'))
        self.assertEqual(ps.canonical_number('18446744073709551615UL'), ps.canonical_number('0xffffffffffffffffLU'))
        self.assertNotEqual(ps.canonical_number('1U'), ps.canonical_number('1'))
        self.assertEqual(ps.canonical_number('010'), ps.canonical_number('8'))
        self.assertEqual(ps.canonical_number('3.40282346638528859811704183484516925e+38F'), ps.canonical_number('3.40282347e+38F'))
        self.assertNotEqual(ps.canonical_number('1.5F'), ps.canonical_number('1.5'))
        self.assertEqual(ps.canonical_number('0x1p-2'), ps.canonical_number('0.25'))
        self.assertEqual(ps.canonical_number('x'), 'x')
        self.assertEqual(ps.canonical_tokens(['(', '(', 'double', ')', '1.5L', ')']), ps.canonical_tokens(['1.5']))

    def test_differing_macros(self):
        found = ps.differing_macros([ps.parse_macros(GCC_MACROS), ps.parse_macros(CLANG_MACROS)]) - ps.TIME_MACROS
        # Equal values in other spellings do not differ; compiler-dependent values do.
        for name in ('INT_MAX', 'INT_MIN', 'DBL_MAX', US+'DBL_MAX'+US, US+'FLT_MAX'+US, 'NULL', 'va_start', 'E', US+'INT_MAX'+US):
            self.assertNotIn(name, found, name)
        for name in (US+'GNUC'+US, 'G_CHECK', US+'glibc_clang_prereq', 'ONLY_GCC'):
            self.assertIn(name, found, name)
        self.assertTrue(ps.TIME_MACROS <= ps.differing_macros([ps.parse_macros(GCC_MACROS)] * 2))
        self.assertEqual(ps.differing_macros([]), set(ps.TIME_MACROS))

    def test_object_and_function_like_forms_differ(self):
        found = ps.differing_macros([ps.parse_macros('#define F(x) x\n'), ps.parse_macros('#define F x\n')])
        self.assertIn('F', found)

    def test_build_macro_uses(self):
        names = {'BUILD_X'}
        code = [('/src/p/src/a.c', 3, 'int'), ('/src/p/src/a.c', 3, 'BUILD_X')]
        found = [('/src/p/src/a.c', 1, 'define', ['V', 'BUILD_X']), ('/src/p/src/a.c', 2, 'define', ['BUILD_X', '1']),
                 ('/src/p/src/a.c', 4, 'undef', ['BUILD_X'])]
        self.assertEqual(ps.build_macro_uses(code, found, names), [('/src/p/src/a.c', 3, 'BUILD_X'), ('/src/p/src/a.c', 1, 'BUILD_X')])

    def test_runtime_interface_prefixes_match_the_ast_rule_and_policy(self):
        import json
        from qualification import RUNTIME_INTERFACE_PREFIXES
        self.assertEqual(ps.RUNTIME_INTERFACE_PREFIXES, RUNTIME_INTERFACE_PREFIXES)
        policy = json.loads((Path(__file__).resolve().parents[2]/'safety/project-policy.json').read_text())
        self.assertTrue(set(RUNTIME_INTERFACE_PREFIXES) <= set(policy['forbidden_text']))


class DifferenceTests(unittest.TestCase):
    def test_first_difference_reports_file_and_line(self):
        base = [('/src/p/src/a.c', 3, 'int'), ('/src/p/src/a.c', 3, 'x'), ('/src/p/src/a.c', 4, ';')]
        other = [('/src/p/src/a.c', 3, 'int'), ('/src/p/src/a.c', 5, 'y'), ('/src/p/src/a.c', 5, ';')]
        found = ps.first_difference([('gcc-O0', base), ('gcc-O2', base), ('clang-O2', other)])
        self.assertEqual(found, {'config': 'clang-O2', 'baseline': 'gcc-O0', 'index': 1, 'file': '/src/p/src/a.c',
                                 'line': 3, 'token': 'x', 'other_file': '/src/p/src/a.c', 'other_line': 5,
                                 'other_token': 'y'})

    def test_length_difference(self):
        base = [('/src/p/src/a.c', 1, 'int')]
        found = ps.first_difference([('a', base), ('b', base + [('/src/p/src/a.c', 2, 'y')])])
        self.assertEqual((found['index'], found['file'], found['other_line']), (1, None, 2))
        self.assertIsNone(ps.first_difference([('a', base), ('b', list(base))]))
        self.assertIsNone(ps.first_difference([]))

    def test_same_tokens_in_another_file_differ(self):
        found = ps.first_difference([('a', [('/src/p/src/a.c', 1, 'x')]), ('b', [('/src/p/include/a.h', 1, 'x')])])
        self.assertEqual(found['other_file'], '/src/p/include/a.h')

    def test_digraph_spelling_is_canonical(self):
        self.assertEqual(ps.canonical('<:'), '[')
        self.assertEqual(ps.canonical('%:%:'), '##')
        self.assertEqual(ps.canonical('x'), 'x')


class DependencyTests(unittest.TestCase):
    def test_parse_depfile(self):
        text = 'unit: /src/p/src/a.c /src/p/include/a\\ b.h \\\n  /usr/include/stdio.h \\\n /x/$$y.h\n'
        self.assertEqual(ps.parse_depfile(text), ['/src/p/src/a.c', '/src/p/include/a b.h', '/usr/include/stdio.h', '/x/$y.h'])
        with self.assertRaises(ValueError):
            ps.parse_depfile('no target here\n')

    def test_preprocess_argv(self):
        argv = ['/usr/bin/clang', '-I/src/p/include', '-O2', '-MD', '-MT', 'x.o', '-MF', 'x.o.d', '-o', 'x.o',
                '-c', '/src/p/src/a.c']
        self.assertEqual(ps.preprocess_argv(argv, ps.dependency_pass('/w/a.d')),
                         ['/usr/bin/clang', '-I/src/p/include', '-O2', '/src/p/src/a.c', '-E', '-dD', '-MD', '-MF', '/w/a.d', '-MT', 'unit'])
        self.assertEqual(ps.preprocess_argv(argv, ps.DIRECTIVES_PASS)[-2:], ['-E', '-fdirectives-only'])
        moved = ps.preprocess_argv(argv, ps.DIRECTIVES_PASS, '/src/p/src/a.c', '/src/p/fuzz/project/h.c')
        self.assertIn('/src/p/fuzz/project/h.c', moved)
        self.assertNotIn('/src/p/src/a.c', moved)
        self.assertEqual(ps.preprocess_argv(['gcc', '-oout.o', '-MFdep', 'a.c'], ['-E']), ['gcc', 'a.c', '-E'])
        with self.assertRaises(ValueError):
            ps.preprocess_argv(['gcc', 'b.c'], ['-E'], 'a.c', 'h.c')

    def test_macros_pass(self):
        self.assertEqual(ps.preprocess_argv(['clang', '-include', 'f.h', '-c', 'a.c'], ps.MACROS_PASS),
                         ['clang', '-include', 'f.h', 'a.c', '-E', '-dM'])

    def problems(self, deps, project_dir='examples/p', unit='examples/p/src/a.c'):
        return ps.dependency_problems(deps, unit, project_dir, {'include/a.h'}, {'fuzz/parser.h'})

    def test_allowed_dependencies(self):
        self.assertEqual(self.problems(['/src/examples/p/src/a.c', '/src/examples/p/src/../include/a.h',
                                        '/usr/include/stdio.h', '/opt/foundation/clang-O0/include/glib-2.0/glib.h',
                                        '/src/fuzz/parser.h']), [])

    def test_refused_dependencies(self):
        for path, problem in (('/src/examples/p/include/b.h', 'project dependency is not a declared header'),
                              ('/src/examples/p/review/x.txt', 'project dependency is not a declared header'),
                              ('/src/examples/p/fuzz/project/corpus/g/seed', 'project dependency is not a declared header'),
                              ('/src/examples/p/specs/project/g.md', 'project dependency is not a declared header'),
                              ('/src/examples/p/src/b.c', 'project dependency is not a declared header'),
                              ('/src/examples/p/README.md', 'project dependency is not a declared header'),
                              ('/src/tools/policy.py', 'dependency is not a framework header'),
                              ('/work/project/x.h', 'dependency outside the source and system directories'),
                              ('relative.h', 'relative dependency')):
            with self.subTest(path=path):
                self.assertEqual([p['problem'] for p in self.problems([path])], [problem])

    def test_child_layout_project_paths(self):
        found = ps.dependency_problems(['/src/src/a.c', '/src/fuzz/project/data.inc', '/src/include/a.h', '/src/fuzz/parser.h'],
                                       'src/a.c', '.', {'include/a.h'}, {'fuzz/parser.h'})
        self.assertEqual(found, [{'file': 'fuzz/project/data.inc', 'problem': 'project dependency is not a declared header'}])
        found = ps.dependency_problems(['/src/other/x.h'], 'src/a.c', '.', set(), {'fuzz/parser.h'})
        self.assertEqual([p['problem'] for p in found], ['dependency is not a framework header'])


if __name__ == '__main__':
    unittest.main()
