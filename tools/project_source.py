"""Pure C source and preprocessor-output analysis for the project source policy.

Standard library only: the host inventory pre-check (project_model) and the
in-container compiler-based checks (container/project-source-policy.py) both
import this module.

- `lex` is a single-pass lexer for C translation phases 1-3: trigraphs, line
  splices (also with trailing blanks, as the compilers accept), comments, string
  and character literals with prefixes and escapes, header names, digraphs.
- `scan_preprocessed` attributes compiler preprocessor output to real files
  through the linemarkers; `split_origin` lexes the project-origin lines into
  code tokens and directives (#pragma, #define, ...).
- `first_difference` compares the project-origin token streams of several build
  configurations; `differing_macros` and `build_macro_uses` find project uses of
  macros whose definition differs between configurations.
- `parse_depfile`, `preprocess_argv` and `dependency_problems` turn compiler
  dependency output into policy findings.

No function here prints; results hold paths, line numbers and short check names
only, never source text.
"""
from __future__ import annotations
import posixpath
import re
import struct
from typing import NamedTuple

PROJECT_PATHS = ('src/', 'include/', 'tests/project/', 'fuzz/project/', 'specs/project/', 'review/')
TRIGRAPHS = {'=': '#', '/': '\\', "'": '^', '(': '[', ')': ']', '!': '|', '<': '{', '>': '}', '-': '~'}
PUNCTUATORS = sorted(['%:%:', '...', '<<=', '>>=', '->', '++', '--', '<<', '>>', '<=', '>=', '==', '!=', '&&',
                      '||', '*=', '/=', '%=', '+=', '-=', '&=', '^=', '|=', '##', '<:', ':>', '<%', '%>', '%:',
                      '[', ']', '(', ')', '{', '}', '.', '&', '*', '+', '-', '~', '!', '/', '%', '<', '>', '^',
                      '|', '?', ':', ';', '=', ',', '#'], key=len, reverse=True)
DIGRAPHS = {'<:': '[', ':>': ']', '<%': '{', '%>': '}', '%:': '#', '%:%:': '##'}
LITERAL_PREFIXES = ('u8', 'u', 'U', 'L')
INCLUDE_DIRECTIVES = ('include', 'include_next', 'import')
# Directives a project may write. #pragma is further limited to `#pragma once`.
ALLOWED_DIRECTIVES = frozenset({'include', 'define', 'undef', 'if', 'ifdef', 'ifndef', 'elif', 'else', 'endif',
                                'error', 'pragma'})
_BLANK = ' \t\f\v'
# Sanitizer, profile and coverage runtime names (tools/qualification.py refuses them in the AST).
RUNTIME_INTERFACE_PREFIXES = ('__asan_', '__lsan_', '__msan_', '__tsan_', '__ubsan_', '__hwasan_', '__dfsan_',
                              '__sanitizer_', '__llvm_profile', '__gcov')


class Token(NamedTuple):
    kind: str    # ident, number, string, char, header, punct, other
    text: str    # spelling after phases 1-2 (literals complete, with prefix)
    line: int    # physical line of the first character (1-based)
    logical: int # logical line index: splices and block comments do not end a line
    first: bool  # first token of its logical line


class Lexed(NamedTuple):
    tokens: list
    code: str          # spliced text; comments are one space, literal contents removed
    problems: list     # (line, problem) for unterminated comments and literals


def _phase12(text):
    """Characters after trigraph replacement and line splicing, each with its physical line."""
    chars, lines = [], []
    line, i, n = 1, 0, len(text)
    while i < n:
        c = text[i]
        if c == '?' and text.startswith('??', i) and i+2 < n and text[i+2] in TRIGRAPHS:
            c, width = TRIGRAPHS[text[i+2]], 3
        elif c == '\r':
            c, width = '\n', 2 if text.startswith('\r\n', i) else 1
        else:
            width = 1
        if c == '\\':
            j = i+width
            while j < n and text[j] in _BLANK:
                j += 1
            if j < n and text[j] in '\r\n':
                j += 2 if text.startswith('\r\n', j) else 1
                line += 1
                i = j
                continue
        chars.append(c)
        lines.append(line)
        if c == '\n':
            line += 1
        i += width
    return ''.join(chars), lines


def _ident_char(c):
    return c.isalnum() or c in '_$' or ord(c) > 127


def lex(text):
    """Tokens of a C source after translation phases 1-3 (see the module docstring)."""
    s, lines = _phase12(text)
    n = len(s)
    tokens, code, problems = [], [], []
    logical, first = 0, True
    i = 0
    directive = []  # tokens of the current logical line while it is a directive

    def add(kind, start, end, view=None):
        nonlocal first
        tok = Token(kind, s[start:end], lines[start], logical, first)
        tokens.append(tok)
        code.append(s[start:end] if view is None else view)
        if first and tok.text in ('#', '%:'):
            directive[:] = [tok]
        elif directive:
            directive.append(tok)
        first = False

    while i < n:
        c = s[i]
        if c == '\n':
            code.append('\n')
            logical += 1
            first = True
            directive.clear()
            i += 1
        elif c in _BLANK:
            code.append(c)
            i += 1
        elif s.startswith('//', i):
            j = s.find('\n', i)
            i = n if j < 0 else j
            code.append(' ')
        elif s.startswith('/*', i):
            j = s.find('*/', i+2)
            if j < 0:
                problems.append((lines[i], 'unterminated comment'))
                i = n
            else:
                i = j+2
            code.append(' ')
        elif (c in '<"' and len(directive) == 2 and directive[1].text in INCLUDE_DIRECTIVES):
            close = '>' if c == '<' else '"'
            j = i+1
            while j < n and s[j] not in (close, '\n'):
                j += 1
            if j >= n or s[j] != close:
                problems.append((lines[i], 'unterminated header name'))
                add('header', i, j)
                i = j
            else:
                add('header', i, j+1)
                i = j+1
        elif c in '"\'' or (_ident_char(c) and not c.isdigit()) or (c == '\\' and i+1 < n and s[i+1] in 'uU'):
            start = i
            if c not in '"\'':
                while i < n and (_ident_char(s[i]) or (s[i] == '\\' and i+1 < n and s[i+1] in 'uU')):
                    i += 2 if s[i] == '\\' else 1
                if not (s[start:i] in LITERAL_PREFIXES and i < n and s[i] in '"\''):
                    add('ident', start, i)
                    continue
            quote = s[i]
            j = i+1
            while j < n and s[j] != quote and s[j] != '\n':
                j += 2 if s[j] == '\\' and j+1 < n and s[j+1] != '\n' else 1
            if j >= n or s[j] != quote:
                problems.append((lines[start], 'unterminated literal'))
                end = j
            else:
                end = j+1
            add('string' if quote == '"' else 'char', start, end, s[start:i+1]+quote)
            i = end
        elif c.isdigit() or (c == '.' and i+1 < n and s[i+1].isdigit()):
            start = i
            i += 1
            while i < n:
                if s[i] in '+-' and s[i-1] in 'eEpP':
                    i += 1
                elif _ident_char(s[i]) or s[i] == '.':
                    i += 1
                else:
                    break
            add('number', start, i)
        else:
            for p in PUNCTUATORS:
                if s.startswith(p, i):
                    add('punct', i, i+len(p))
                    i += len(p)
                    break
            else:
                add('other', i, i+1)
                i += 1
    return Lexed(tokens, ''.join(code), problems)


def directives(tokens):
    """[(line, name, [tokens after the name])] for every directive line; name '' is the null directive."""
    result, current = [], None
    for tok in tokens:
        if tok.first:
            current = None
            if tok.text in ('#', '%:'):
                current = [tok.line, '', []]
                result.append(current)
            continue
        if current is None:
            continue
        if not current[1] and not current[2] and tok.kind == 'ident':
            current[1] = tok.text
        else:
            current[2].append(tok)
    return [(line, name, rest) for line, name, rest in result]


def directive_problem(tokens):
    """(line, reason) for the first directive a project may not write, or None."""
    for line, name, rest in directives(tokens):
        if not name and rest:
            return line, 'malformed directive'
        if name and name not in ALLOWED_DIRECTIVES:
            return line, '#'+name
        if name == 'pragma' and [t.text for t in rest] != ['once']:
            return line, '#pragma other than #pragma once'
    return None


def include_targets(tokens):
    """[(line, directive name, 'quoted'|'angle'|None, target)] for #include, #include_next and #import."""
    result = []
    for line, name, rest in directives(tokens):
        if name not in INCLUDE_DIRECTIVES:
            continue
        if len(rest) == 1 and rest[0].kind == 'header' and len(rest[0].text) >= 2 and rest[0].text[-1] in '">':
            form = 'quoted' if rest[0].text[0] == '"' else 'angle'
            result.append((line, name, form, rest[0].text[1:-1]))
        else:
            result.append((line, name, None, None))
    return result


# ------------------------------------------------------------ preprocessed output

_LINEMARKER = re.compile(r'^#(?:line)?\s*(\d+)\s+"((?:[^"\\]|\\.)*)"((?:\s+\d+)*)\s*$')
_PSEUDO = re.compile(r'^<[^<>]*>$')


def _unescape(name):
    out, i = [], 0
    while i < len(name):
        if name[i] == '\\' and i+1 < len(name):
            octal = re.match(r'[0-7]{1,3}', name[i+1:])
            if octal:
                out.append(chr(int(octal.group(0), 8)))
                i += 1+len(octal.group(0))
                continue
            out.append(name[i+1])
            i += 2
        else:
            out.append(name[i])
            i += 1
    return ''.join(out)


def normal_path(path):
    """Normalized absolute path of a file name in compiler output; pseudo files stay as written."""
    if _PSEUDO.match(path) or not path.startswith('/'):
        return path
    return posixpath.normpath(path)


def origin_prefixes(project_root):
    """Absolute prefixes of project-origin files for a project at `project_root` (for example /src/x)."""
    root = posixpath.normpath(project_root).rstrip('/')
    return tuple(root+'/'+p for p in PROJECT_PATHS)


def canonical(text):
    return DIGRAPHS.get(text, text)


def scan_preprocessed(text, main_file, prefixes, dependencies=None):
    """Attribute preprocessor output (with linemarkers) to real files.

    Returns {'lines': [(file, line, text)] for project-origin output lines,
    'markers': [(file, line, problem)], 'files': [real files entered]} where only
    files under `prefixes` count as project origin. The real file is tracked with
    an include stack (flag 1 enters, flag 2 returns), so a #line directive cannot
    move project code into another file: a flagless marker that names another
    file while the current real file is project origin is a marker problem. A
    project-origin file may be in system-header state (flag 3) only for a span that
    a flagless marker for the same file ends again, as GCC writes around a system
    macro expansion; still in that state when it enters or returns, or at the end,
    it was marked as a system header (#pragma ... system_header). A file entered
    from a system include directory of the configuration (flags 1 3, as the AST
    scan's -idirafter does) is exempt from that check. A file a project
    file enters, and every project-origin file entered, must be in `dependencies`
    (when given). GCC's working-directory marker (a name ending in //) is ignored."""
    main = normal_path(main_file)
    # Stack entries: [real file, system-header state, entered from a system include directory].
    stack, line = [], 1
    result = {'lines': [], 'markers': [], 'files': []}
    known = None if dependencies is None else {normal_path(d) for d in dependencies} | {main}

    def origin(path):
        return path is not None and path.startswith(prefixes)

    def leave_check(where):
        if stack and stack[-1][1] and not stack[-1][2] and origin(stack[-1][0]):
            result['markers'].append((stack[-1][0], where, 'project file marked as a system header'))
            stack[-1][1] = False

    for raw in text.split('\n'):
        marker = _LINEMARKER.match(raw)
        if marker:
            number = int(marker.group(1))
            written = _unescape(marker.group(2))
            flags = {int(f) for f in marker.group(3).split()}
            system = 3 in flags
            if written.endswith('//') and not flags:
                continue
            name = normal_path(written)
            if 1 in flags:
                leave_check(line)
                if known is not None and not _PSEUDO.match(name) and name not in known and (
                        origin(name) or (stack and origin(stack[-1][0]))):
                    result['markers'].append((name, number, 'entered file is not a compiler dependency'))
                stack.append([name, system, system])
                result['files'].append(name)
            elif 2 in flags:
                leave_check(line)
                if len(stack) > 1:
                    stack.pop()
                # Returning into a project file in system-header state is reported once.
                exempt = stack[-1][2]
                stack[-1][1] = system and (exempt or not origin(stack[-1][0]))
                if system and not exempt and origin(stack[-1][0]):
                    result['markers'].append((stack[-1][0], number, 'project file marked as a system header'))
            elif not stack:
                stack.append([name, system, False])
            elif len(stack) == 1 and (_PSEUDO.match(name) or name == main):
                stack[0] = [name, system, False]
            elif name != stack[-1][0]:
                if origin(stack[-1][0]):
                    result['markers'].append((stack[-1][0], line, 'line directive renames a project file'))
            else:
                stack[-1][1] = system
            line = number
            continue
        current = stack[-1][0] if stack else None
        if origin(current):
            result['lines'].append((current, line, raw))
        line += 1
    leave_check(line)
    return result


def split_origin(lines):
    """(code, directives) of project-origin output lines.

    Consecutive lines of one file are lexed together, so comments and splices that
    a directives-only pass keeps are handled. code is [(file, line, token)] outside
    directive lines (digraphs canonical); directives is [(file, line, name, [tokens])]."""
    code, found = [], []
    index = 0
    while index < len(lines):
        file = lines[index][0]
        chunk = [lines[index]]
        index += 1
        while index < len(lines) and lines[index][0] == file:
            chunk.append(lines[index])
            index += 1
        numbers = [line for _f, line, _t in chunk]
        tokens = lex('\n'.join(text for _f, _l, text in chunk)).tokens
        groups = {}
        for tok in tokens:
            where = numbers[min(tok.line, len(numbers))-1]
            if tok.first and tok.text in ('#', '%:'):
                groups[tok.logical] = [file, where, '', []]
                found.append(groups[tok.logical])
            elif tok.logical in groups:
                group = groups[tok.logical]
                if not group[2] and not group[3] and tok.kind == 'ident':
                    group[2] = tok.text
                else:
                    group[3].append(canonical(tok.text))
            else:
                code.append((file, where, canonical(tok.text)))
    return code, [tuple(g) for g in found]


MACRO_DIRECTIVES = ('define', 'undef')


def define_stream(directives_found):
    """[(file, line, token)] of the project's #define and #undef lines (in order)."""
    stream = []
    for file, line, name, rest in directives_found:
        if name in MACRO_DIRECTIVES:
            stream += [(file, line, '#'), (file, line, name)] + [(file, line, t) for t in rest]
    return stream


def parse_macros(text):
    """{name: (parameters or None, body)} from `-dM -E` output."""
    macros = {}
    for raw in text.splitlines():
        match = re.match(r'^#define\s+([A-Za-z_][A-Za-z0-9_]*)(\([^)]*\))?\s?(.*)$', raw)
        if match:
            params = None
            if match.group(2) is not None:
                params = tuple(p.strip() for p in match.group(2)[1:-1].split(',') if p.strip())
            macros[match.group(1)] = (params, match.group(3).strip())
    return macros


# Macros whose value changes from one run to the next.
TIME_MACROS = frozenset({'__DATE__', '__TIME__', '__TIMESTAMP__'})
_INTEGER = re.compile(r'(0x[0-9a-f]+|0b[01]+|0[0-7]*|[1-9][0-9]*)([ul]*)')
_FLOAT = re.compile(r'((?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+(?=e))(?:e[+-]?[0-9]+)?|0x[0-9a-f]*\.?[0-9a-f]*p[+-]?[0-9]+)([fl]?)')
_FLOAT_KIND = {'f': 'float', 'l': 'long double', '': 'double'}


def canonical_number(text):
    """A numeric literal as its value and type ('I:value:suffix' or 'F:type:value'); other text unchanged.

    GCC and Clang spell the same predefined constant differently (0x7fffffff and
    2147483647; 3.40282346638528859811704183484516925e+38F and 3.40282347e+38F)."""
    low = text.lower()
    whole = _INTEGER.fullmatch(low)
    if whole:
        digits = whole.group(1)
        base = 16 if digits.startswith('0x') else 2 if digits.startswith('0b') else 8 if digits.startswith('0') and digits != '0' else 10
        value = int(digits[2:] if base in (16, 2) else digits, base)
        return 'I:%d:%s' % (value, ''.join(sorted(whole.group(2))))
    match = _FLOAT.fullmatch(low)
    if match:
        try:
            value = float.fromhex(match.group(1)) if match.group(1).startswith('0x') else float(match.group(1))
        except ValueError:
            return text
        return _float_value(_FLOAT_KIND[match.group(2)], value)
    return text


def _float_value(kind, value):
    if kind == 'float':
        value = struct.unpack('f', struct.pack('f', value))[0] if abs(value) < 3.5e38 else value
    return 'F:%s:%r' % (kind, value)


def canonical_tokens(tokens):
    """Numbers by value; `( ( double ) <number> )` and `( ( float ) <number> )` as a number of that type."""
    out = [canonical_number(t) for t in tokens]
    result, i = [], 0
    while i < len(out):
        window = out[i:i+6]
        if (len(window) == 6 and window[:2] == ['(', '('] and window[2] in ('double', 'float') and window[3] == ')'
                and window[4].startswith(('F:', 'I:')) and window[5] == ')'):
            number = window[4]
            value = float(number.split(':')[1]) if number.startswith('I:') else float(number.split(':', 2)[2])
            result.append(_float_value(window[2], value))
            i += 6
        else:
            result.append(out[i])
            i += 1
    return tuple(result)


def _body_tokens(definition):
    params, body = definition
    tokens = []
    for tok in lex(body).tokens:
        text = canonical(tok.text)
        tokens.append('$%d' % params.index(text) if params and text in params else text)
    return tokens


def _expansion(name, table, memo, active=frozenset()):
    """The body of `name` with object-like macros of `table` expanded (recursively), canonical."""
    if name in memo:
        return memo[name]
    out = []
    for text in _body_tokens(table[name]):
        if text in table and table[text][0] is None and text not in active and text != name:
            out.extend(_expansion(text, table, memo, active | {name}))
        else:
            out.append(text)
    memo[name] = canonical_tokens(out)
    return memo[name]


def differing_macros(tables):
    """Names of macros whose definition differs between configurations (`tables` from parse_macros).

    A macro differs when it is not defined in every configuration, or when its
    body, with object-like macros expanded and numbers compared by value, differs.
    INT_MAX, INT_MIN, DBL_MAX and NULL are equal by that rule. A macro whose body
    names a differing macro differs too (G_GNUC_CHECK_VERSION names __GNUC__).
    __DATE__, __TIME__ and __TIMESTAMP__ always differ."""
    if not tables:
        return set(TIME_MACROS)
    names = set().union(*tables)
    raw = {}
    for name in names:
        forms = {(t[name][0] is None, tuple(_body_tokens(t[name]))) if name in t else None for t in tables}
        raw[name] = forms
    memos = [{} for _ in tables]
    differing = set()
    for name, forms in raw.items():
        if len(forms) == 1:
            continue
        if None in forms or len({f[0] for f in forms}) > 1:
            differing.add(name)
            continue
        if len({_expansion(name, t, m) for t, m in zip(tables, memos)}) > 1:
            differing.add(name)
    references = {name: {x for form in forms if form for x in form[1]} for name, forms in raw.items()}
    changed = True
    while changed:
        changed = False
        for name, used in references.items():
            if name not in differing and used & differing:
                differing.add(name)
                changed = True
    return differing | TIME_MACROS


def build_macro_uses(code, directives_found, names):
    """[(file, line, name)] where project code or a project macro body names a macro in `names`.

    The name a #define or #undef defines is not a use (a project may define _GNU_SOURCE)."""
    uses = [(f, l, t) for f, l, t in code if t in names]
    for file, line, name, rest in directives_found:
        if name == 'define':
            uses += [(file, line, t) for t in rest[1:] if t in names]
    return uses


def first_difference(streams):
    """First difference of project-origin token streams; `streams` is [(config, stream)].

    The first configuration is the baseline. Returns None when every stream equals
    it, else {'config', 'baseline', 'index', 'file', 'line', 'token', 'other_file',
    'other_line', 'other_token'} (the baseline token; other_* of the differing
    configuration; None at the end of a stream; tokens cut to 40 characters)."""
    if not streams:
        return None
    base_name, base = streams[0]
    for name, other in streams[1:]:
        limit = min(len(base), len(other))
        index = next((k for k in range(limit) if (base[k][0], base[k][2]) != (other[k][0], other[k][2])), None)
        if index is None and len(base) == len(other):
            continue
        if index is None:
            index = limit
        here = base[index] if index < len(base) else (None, None, None)
        there = other[index] if index < len(other) else (None, None, None)
        return {'config': name, 'baseline': base_name, 'index': index, 'file': here[0], 'line': here[1],
                'token': None if here[2] is None else here[2][:40], 'other_file': there[0], 'other_line': there[1],
                'other_token': None if there[2] is None else there[2][:40]}
    return None


def parse_depfile(text):
    """Prerequisites of a Make dependency file written by -MD (one target)."""
    text = re.sub(r'\\\r?\n', ' ', text)
    paths = []
    for rule in text.splitlines():
        if not rule.strip():
            continue
        colon = re.search(r':(\s|$)', rule)
        if colon is None:
            raise ValueError('dependency file rule without a target')
        body, current, i = rule[colon.end():], [], 0
        while i < len(body):
            c = body[i]
            if c == '\\' and i+1 < len(body) and body[i+1] in ' #\\':
                current.append(body[i+1])
                i += 2
            elif c == '$' and body.startswith('$$', i):
                current.append('$')
                i += 2
            elif c.isspace():
                if current:
                    paths.append(''.join(current))
                current = []
                i += 1
            else:
                current.append(c)
                i += 1
        if current:
            paths.append(''.join(current))
    return paths


_DROP_WITH_VALUE = {'-o', '-MF', '-MT', '-MQ'}
_DROP_ALONE = {'-c', '-E', '-S', '-M', '-MM', '-MD', '-MMD', '-MP', '-MG', '-dD', '-dM', '-fdirectives-only'}


def _strip(argv):
    result, skip = [], False
    for arg in argv:
        if skip:
            skip = False
            continue
        if arg in _DROP_WITH_VALUE:
            skip = True
            continue
        if arg in _DROP_ALONE or any(arg.startswith(p) and arg != p for p in _DROP_WITH_VALUE):
            continue
        result.append(arg)
    return result


def preprocess_argv(argv, extra, source=None, replace=None):
    """The compile command `argv` with output, dependency and compile-only options dropped,
    the argument equal to `source` replaced by `replace` (when given), and `extra` appended."""
    result = _strip(argv)
    if replace is not None:
        if source not in result:
            raise ValueError('compile command does not name its source file')
        result = [replace if arg == source else arg for arg in result]
    return result + list(extra)


def dependency_pass(depfile):
    """Extra arguments of the full preprocessing pass: macro definitions kept, dependencies written."""
    return ['-E', '-dD', '-MD', '-MF', depfile, '-MT', 'unit']


DIRECTIVES_PASS = ('-E', '-fdirectives-only')


MACROS_PASS = ('-E', '-dM')


def dependency_problems(dependencies, unit, project_dir, headers, framework_headers,
                        system_prefixes=('/usr/', '/opt/foundation/')):
    """Findings for the compiler dependencies of one translation unit (paths absolute, in /src).

    Under the project's paths a dependency must be the unit itself or a header declared
    in project.json (never review/, specs/, fuzz corpora or regressions: those are no
    declared header). Elsewhere under /src only exported framework headers may be read;
    outside /src only the system prefixes."""
    root = posixpath.normpath('/src/'+project_dir)
    problems = []
    for raw in dependencies:
        path = normal_path(raw)
        if not path.startswith('/'):
            problems.append({'file': raw, 'problem': 'relative dependency'})
            continue
        if path == posixpath.normpath(unit if unit.startswith('/') else '/src/'+unit):
            continue
        inside_project = path.startswith(root+'/') if root != '/src' else False
        rel = path[len(root)+1:] if path.startswith(root+'/') else None
        if rel is not None and (inside_project or rel.startswith(PROJECT_PATHS)):
            if rel not in headers or not rel.startswith('include/'):
                problems.append({'file': rel, 'problem': 'project dependency is not a declared header'})
        elif path.startswith('/src/'):
            if path[len('/src/'):] not in framework_headers:
                problems.append({'file': path[len('/src/'):], 'problem': 'dependency is not a framework header'})
        elif not path.startswith(tuple(system_prefixes)):
            problems.append({'file': path, 'problem': 'dependency outside the source and system directories'})
    return problems
