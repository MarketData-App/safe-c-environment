"""Tool adapters. Actual target-scoped CMake profiles are the qualification path."""
from pathlib import Path
import json
import re
import shlex
from evidence import GateError, passed, read_json, file_hash, atomic_json
from policy import build_audit, lit_accounting

PROFILE_FLAGS = {'asan':'-fsanitize=address,undefined','ubsan':'-fsanitize=undefined',
 'integer':'-fsanitize=undefined,unsigned-integer-overflow,implicit-integer-conversion',
 'msan':'-fsanitize=memory','tsan':'-fsanitize=thread',
 'fuzz':'-fsanitize=address,undefined,fuzzer-no-link','coverage':'-fcoverage-mapping'}
INFRA = ['tests/integration/demo.c','fuzz/parser_good.c','tests/integration/hardening.c','tests/integration/runtime-demo.c','foundation/src/sc-foundation.c','foundation/tests/contracts.c','foundation/tests/dependency-identity.c','foundation/tests/recipes.c']

def designated_runtime_result(result,expected):
    if type(result.get('exit_code')) is not int or result['failure'] is not None or result['exit_code']==0 or expected not in result['output']:
        raise GateError('runtime infrastructure failure cannot qualify a designated finding')
    return True

class Qualifier:
    def __init__(self, root, runner):
        self.root, self.runner = root, runner
        self.fixtures = {x['id']:x for x in read_json(root/'safety/fixtures.json')['cases']}
        self.builds = {}
        self.build_sessions = {}

    def build(self, profile, *, case='NONE', variant='both', compiler=None, opt=0, foundation_case='NONE', guards=(), foundation_mutant='NONE'):
        cc = compiler or ('gcc' if profile=='gcc-analyzer' else 'clang')
        key = f'{profile}-{cc}-O{opt}-{case}-{variant}'
        if foundation_case != 'NONE':
            if foundation_case not in {'F01', 'F02', 'F03', 'F14', 'F17', 'F18', 'F19'}:
                raise GateError('unknown foundation runtime case')
            key += '-' + foundation_case
        if any(g not in {'NDEBUG', 'G_DISABLE_ASSERT', 'G_DISABLE_CHECKS'} for g in guards) or len(set(guards)) != len(guards):
            raise GateError('unknown/duplicate first-party guard variant')
        if guards:key += '-' + '-'.join(guards)
        if foundation_mutant != 'NONE':
            if foundation_mutant not in read_json(self.root/'safety/foundation-mutants.json')['mutants']:raise GateError('uninventoried foundation mutation')
            key += '-mutant-' + foundation_mutant
        # Build trees live in the session container's /work; a build from a disposed
        # session is gone and is redone in the current one.
        if key in self.builds and self.build_sessions.get('build/'+key) is not None and self.build_sessions['build/'+key]==self.session_id():
            return self.builds[key]
        relative='build/'+key
        config=self.runner.run(['cmake','-S','/src','-B','/work/'+relative,'-G','Ninja',
            '-DCMAKE_C_COMPILER='+cc,'-DSAFETY_PROFILE='+profile,'-DSAFETY_CASE='+case,
            '-DSAFETY_VARIANT='+variant,'-DCMAKE_C_FLAGS=-O'+str(opt),
            '-DFOUNDATION_CASE='+foundation_case, '-DFOUNDATION_MUTANT='+foundation_mutant, '-DFOUNDATION_DISABLED_GUARDS='+';'.join(guards)],timeout=60,label=key+'-configure')
        result={'directory':relative,'configure':config,'build':None,'audit':None,'commands':[],'links':None}
        self.build_sessions[relative]=self.session_id()
        if passed(config):
            compile_result=self.runner.run(['cmake','--build','/work/'+relative,'--parallel','2','--verbose'],timeout=90,label=key+'-build')
            result['build']=compile_result
            try:
                database=read_json(self.runner.fetch(relative+'/compile_commands.json'))
                sources=INFRA.copy()
                if profile == 'fuzz':sources.append('foundation/tests/stateful-fuzzer.c')
                if foundation_case != 'NONE':sources.append('safety/qualification/foundation/' + foundation_case + '.c')
                if case in self.fixtures:
                    f=self.fixtures[case]
                    sources+=f['bad_sources'] if variant=='bad' else f['good_sources'] if variant=='good' else f['bad_sources']+f['good_sources']
                result['commands']=database
                audited=database
                if foundation_mutant != 'NONE':
                    receipt=read_json(self.runner.fetch(relative+'/foundation-mutation/mutation.json'))
                    actual=self.runner.fetch(relative+'/foundation-mutation/sc-foundation-mutant.c')
                    expected_recipe=read_json(self.root/'safety/foundation-mutants.json')
                    generated='/work/'+relative+'/foundation-mutation/sc-foundation-mutant.c'
                    if (receipt['status']!='PASS' or receipt['mutant']!=foundation_mutant or
                        receipt['source_sha256']!=file_hash(self.root/'foundation/src/sc-foundation.c') or
                        receipt['recipe_sha256']!=file_hash(self.root/expected_recipe['recipe']) or
                        receipt['generated_source']!=generated or receipt['generated_sha256']!=file_hash(actual)):
                        raise GateError('generated mutation identity mismatch')
                    if sum(row['file']==generated for row in database)!=1:raise GateError('mutation object omitted/duplicated')
                    audited=[dict(row,file='/src/foundation/src/sc-foundation.c') if row['file']==generated else row for row in database]
                    result['mutation']=receipt
                result['audit']=build_audit(audited,sources,profile)
                links=self.runner.run(['ninja','-C','/work/'+relative,'-t','commands'],label=key+'-link-audit')
                result['links']=links
                if passed(compile_result) and profile in PROFILE_FLAGS:
                    actual=[shlex.split(line) for line in links['output'].splitlines() if ' -o ' in line and ' -c ' not in line]
                    if not actual or any(PROFILE_FLAGS[profile] not in row for row in actual):
                        raise GateError('final link instrumentation missing')
            except (GateError,ValueError) as exc:
                result['audit']={'status':'FAIL','reason':str(exc)}
        self.builds[key]=result
        return result

    def session_id(self):
        session=self.runner.session
        return session['container_id'] if self.runner.alive and session else None

    @staticmethod
    def built(build):
        return passed(build['configure']) and build['build'] is not None and passed(build['build']) and build['audit'] and build['audit']['status']=='PASS'

    def executable(self, build, target, args=(), *, label=None, env=None):
        binary=build['directory']+'/'+target
        owner=self.build_sessions.get(build['directory'])
        if owner is not None and owner!=self.session_id():
            raise GateError('build belongs to a disposed session container; rebuild it')
        path=self.runner.fetch(binary)
        before=file_hash(path)
        result=self.runner.run(['/work/'+binary,*args],timeout=10,env=env,label=label or target)
        result['binary_sha256']=before
        after=file_hash(self.runner.fetch(binary)) if self.runner.alive else None
        result['binary_unchanged']=before==after
        atomic_json(Path(result['evidence_path']),result)
        return result

    def qualify_case(self, cid):
        self.runner.refresh()
        f=self.fixtures[cid]; det=f['required_detector']
        row={'id':cid,'status':'FAIL','classification':'NOT_RUN','detector':det,'bad':'BLOCKED','control':'BLOCKED','baseline':'BLOCKED','matching_diagnostic':None,'evidence_paths':[],'repetitions':0}
        baseline=self.build('ordinary',case=cid)
        row['evidence_paths'] += [r['evidence_path'] for r in [baseline['configure'],baseline['build']] if r]
        if not self.built(baseline):
            row.update(classification='FIXTURE_INVALID');return row
        row['baseline']='PASS'
        if det in ['csa','tidy','ast']:
            build=self.build('strict',case=cid)
        elif det in ['warnings','gcc-analyzer']:
            build=None
        elif det=='functional':
            build=self.build('asan',case=cid)
        else:
            build=self.build(det,case=cid)
        if build is not None:
            row['evidence_paths'] += [r['evidence_path'] for r in [build['configure'],build['build']] if r]
            if not self.built(build):
                row['classification']='TOOL_FAILURE';return row
        bad_results=[]; good_results=[]
        for variant in ['bad','good']:
            results=[]
            count=f['required_repetitions'] if variant=='bad' else 1
            for repetition in range(count):
                label=cid+'-'+variant+'-'+str(repetition)
                if det in ['warnings','gcc-analyzer']:
                    b=self.build(det,case=cid,variant=variant,compiler='gcc' if det=='gcc-analyzer' else 'clang')
                    result=b['build'] or b['configure']
                    row['evidence_paths'] += [b['configure']['evidence_path']]
                elif det=='csa':
                    result=self.runner.run(['clang','--analyze','-std=c17','-Xanalyzer','-analyzer-output=text','-Xanalyzer','-analyzer-checker=core,unix','/src/'+f[variant+'_sources'][0]],label=label)
                elif det=='tidy':
                    result=self.runner.run(['clang-tidy','--config-file=/src/.clang-tidy','/src/'+f[variant+'_sources'][0],'--','-std=c17'],label=label)
                elif det=='ast':
                    raw=self.runner.run(['clang','-std=c17','-Xclang','-ast-dump=json','-fsyntax-only','/src/'+f[variant+'_sources'][0]],label=label+'-ast')
                    row['evidence_paths'].append(raw['evidence_path'])
                    result=dict(raw)
                    if passed(raw):
                        tree=json.loads(raw['output']);banned=ast_banned_calls(tree)
                        result['exit_code']=1 if banned else 0
                        sites=ast_call_sites(tree)
                        result['output']='\n'.join('AST/API policy banned callee: '+name+' in '+function+' /src/'+f[variant+'_sources'][0]+(' macro expansion' if macro else ' direct call') for name,function,macro in sites) if banned else 'AST/API policy clean'
                        if cid=='C28' and variant=='bad' and not (any(x[2] for x in sites) and any(not x[2] for x in sites)):
                            result['failure']='MISSING_RAW_OR_MACRO_POLICY_PROBE'
                        result['evidence_path']=str(Path(raw['evidence_path']).with_name(label+'-policy.json'))
                        atomic_json(Path(result['evidence_path']),result)
                else:
                    args=['/src/'+f['trigger_input'],'-runs=1'] if det=='fuzz' else []
                    result=self.executable(build,cid+'_'+variant,args,label=label)
                results.append(result);row['evidence_paths'].append(result['evidence_path'])
            if variant=='bad':bad_results=results
            else:good_results=results
        row['repetitions']=len(bad_results)
        # Runtime failure class and location are required; startup failures are never detections.
        expected=f['expected_rule_or_class']
        matches=[]
        for result in bad_results:
            diagnostics = '\n'.join(line for line in result['output'].splitlines() if re.match(r'^/src/.*:[0-9]+(?::[0-9]+)?: (?:error|warning):', line)) if det in ['warnings','gcc-analyzer'] else result['output']
            ok = result['failure'] is None and expected in diagnostics
            if det not in ['csa','ast']:
                ok = ok and result['exit_code'] != 0
            if det in ['asan','ubsan','integer','msan','tsan','fuzz']:
                try:designated_runtime_result(result,expected)
                except GateError:ok=False
                ok = ok and result.get('binary_unchanged',False) and ('/src/' in result['output'])
                if det=='msan':ok=ok and 'Uninitialized value was created' in result['output']
                if det=='tsan':ok=ok and 'Previous' in result['output'] and 'worker' in result['output']
                if det not in ['ubsan','integer']:ok=ok and f['expected_source_function'] in result['output']
            if ok:
                log=f'checks/{cid}-{len(matches)}.log'
                write=self.runner.run(['python3','-c','import pathlib,sys; p=pathlib.Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(sys.argv[2])','/work/'+log,result['output']],label=cid+'-captured-log')
                check=self.runner.run(['FileCheck','/src/safety/lit/'+cid+'.check','--input-file=/work/'+log],label=cid+'-FileCheck')
                row['evidence_paths'].append(check['evidence_path']);ok=passed(write) and passed(check)
            matches.append(ok)
        controls=[]
        for result in good_results:
            clean=passed(result) and (not re.search(r'^/src/.*:[0-9]+(?::[0-9]+)?: (?:error|warning):', result['output'], re.M) if det in ['warnings','gcc-analyzer'] else expected not in result['output'])
            if det=='csa':clean=clean and 'warning:' not in result['output']
            controls.append(clean)
        row['bad']='PASS' if all(matches) and matches else 'FAIL'
        row['control']='PASS' if all(controls) and controls else 'FAIL'
        if row['bad']=='PASS':
            row['matching_diagnostic']=expected
            row['classification']='DETECTED_EXPECTED' if row['control']=='PASS' else 'CONTROL_FAILED'
        elif any(r['failure']=='TIMEOUT' for r in bad_results):row['classification']='TIMEOUT'
        elif any('CHECK failed' in r['output'] or 'can not mmap' in r['output'] or 'FATAL:' in r['output'] for r in bad_results):row['classification']='TOOL_FAILURE'
        elif any(r['exit_code']!=0 for r in bad_results):row['classification']='WRONG_DIAGNOSTIC'
        else:row['classification']='MISSED'
        row['status']='PASS' if row['classification']=='DETECTED_EXPECTED' else 'FAIL'
        return row

    def lit(self, rows=None):
        import sys
        distribution=self.runner.lock['lit_distribution']
        wheel=self.root/distribution['retained_path']
        if file_hash(wheel)!=distribution['sha256']:
            raise GateError('lit wheel integrity mismatch')
        sys.path.insert(0,str(wheel))
        import lit_bridge
        from lit.main import main
        self.runner.start()
        lit_bridge.Q=self
        output_dir=self.runner.run_dir/'lit'
        output_dir.mkdir(parents=True,exist_ok=True)
        lit_bridge.OUTPUT=str(output_dir.resolve())
        out=output_dir/'results.json'
        saved=sys.argv
        sys.argv=['lit',str(self.root/'safety/lit'),'--workers=1','--output='+str(out),'--max-time=900']
        code=0
        try:
            main()
        except SystemExit as exc:
            code=exc.code or 0
        finally:
            sys.argv=saved
        cases=[]
        try:
            value=read_json(out)
            for row in value['tests']:
                try:cases.append(json.loads(row['output']))
                except (ValueError,KeyError):pass
            lit_accounting(value,list(self.fixtures))
            status='PASS' if code==0 else 'FAIL'
        except (GateError,KeyError,ValueError) as exc:
            value=read_json(out) if out.exists() else {'error':str(exc)}
            value['accounting_error']=str(exc);status='FAIL'
        return {'status':status,'results':value,'case_rows':sorted(cases,key=lambda r:r['id']),'evidence_paths':[str(out)]}


def ast_banned_calls(node):
    result=set()
    def walk(value, in_call=False):
        if isinstance(value,dict):
            now=in_call or value.get('kind')=='CallExpr'
            if now and value.get('kind')=='DeclRefExpr':
                name=value.get('referencedDecl',{}).get('name')
                if name in {'gets','strcpy','strcat','sprintf','atoi','system','popen','alloca'}:result.add(name)
            if value.get('kind') in {'NoSanitizeAttr','AsmStmt','GCCAsmStmt'}:result.add(value['kind'])
            for child in value.get('inner',[]):walk(child,now)
        elif isinstance(value,list):
            for child in value:walk(child,in_call)
    walk(node)
    return sorted(result)

# Project code is auditable C. The AST project rules are allowlists, not denylists:
# a reserved identifier the project declares, a __builtin_ it calls, or an attribute
# kind on a project declaration is refused unless it is on the short allowlist below.
# A declaration, reference or attribute in a system or GLib header is exempt; only
# project-origin source locations are checked.

# Reserved identifiers (__* or _<uppercase>*) a project may declare or define. The
# language reserves them for the implementation; a project that defines one can reach
# the sanitizer, libc or linker runtime. The allowlist is empty.
PROJECT_ALLOWED_RESERVED_DECLS = frozenset()

# __builtin_ functions a project may call. Every other __builtin_ (object_size,
# dynamic_object_size, constant_p, ... which depend on the optimization level, and
# the codegen/runtime ones) is refused. va_* and offsetof back the <stdarg.h> and
# <stddef.h> macros; the overflow builtins and trap/unreachable/expect are ordinary.
PROJECT_ALLOWED_BUILTINS = frozenset({
    '__builtin_va_start', '__builtin_va_end', '__builtin_va_arg', '__builtin_va_copy',
    '__builtin_offsetof', '__builtin_expect', '__builtin_expect_with_probability',
    '__builtin_unreachable', '__builtin_trap',
    '__builtin_add_overflow', '__builtin_sub_overflow', '__builtin_mul_overflow',
    '__builtin_add_overflow_p', '__builtin_sub_overflow_p', '__builtin_mul_overflow_p'})

# Attribute kinds a project declaration may carry. Linkage and placement attributes
# (AsmLabel, Alias, WeakRef, IFunc, Weak, Constructor, Destructor, Section, Used,
# Visibility-as-export) and the instrumentation attributes are not here, so they are
# refused. Clang-inserted implicit attributes are skipped before this check.
PROJECT_ALLOWED_ATTRIBUTES = frozenset({
    'CleanupAttr', 'FormatAttr', 'FormatArgAttr', 'NonNullAttr', 'ReturnsNonNullAttr',
    'WarnUnusedResultAttr', 'UnusedAttr', 'MaybeUnusedAttr', 'AlignedAttr', 'NoReturnAttr',
    'C11NoReturnAttr', 'CXX11NoReturnAttr', 'ConstAttr', 'PureAttr', 'DeprecatedAttr',
    'FallThroughAttr', 'SentinelAttr', 'RestrictAttr', 'MallocAttr', 'AllocSizeAttr',
    'AllocAlignAttr', 'PackedAttr', 'ColdAttr', 'HotAttr', 'NoThrowAttr', 'NoInlineAttr',
    'AlwaysInlineAttr', 'FlattenAttr', 'MayAliasAttr', 'CountedByAttr', 'ModeAttr',
    'TransparentUnionAttr', 'EnumExtensibilityAttr', 'FlagEnumAttr', 'NonStringAttr',
    'ReturnsTwiceAttr'})

# Run-time symbol lookup lets project code bypass the AST name rules.
PROJECT_BANNED_CALLS = frozenset({'dlsym', 'dlvsym', 'dlopen', 'dlmopen',
                                  # Process exits that skip the sanitizer and leak reports.
                                  '_exit', '_Exit', 'quick_exit'})
# A project definition of an allocator replaces the sanitizer's interceptors.
PROJECT_RESERVED_DEFINITIONS = frozenset({'malloc', 'calloc', 'realloc', 'free', 'aligned_alloc',
                                          'posix_memalign', 'memalign', 'valloc', 'pvalloc',
                                          'reallocarray'})

# Project code may not reach the sanitizer, profile or coverage runtimes: their hooks
# (*_default_options, death callbacks, suppressions) can turn a detected defect into a
# passing run. These prefixes are also the pre-check text list.
RUNTIME_INTERFACE_PREFIXES = ('__asan_', '__lsan_', '__msan_', '__tsan_', '__ubsan_', '__hwasan_', '__dfsan_',
                              '__sanitizer_', '__llvm_profile', '__gcov')
# The only libFuzzer entry a harness may name; the init/counter hooks switch off fuzzing.
FUZZER_ENTRY = 'LLVMFuzzerTestOneInput'

_DECL_KINDS = frozenset({'FunctionDecl', 'VarDecl', 'ParmVarDecl', 'FieldDecl', 'TypedefDecl', 'RecordDecl',
                         'EnumDecl', 'EnumConstantDecl'})


def _is_reserved(name):
    return bool(name) and (name.startswith('__') or (len(name) >= 2 and name[0] == '_' and name[1].isupper()))


def ast_banned_attributes(node):
    """Sorted kinds of attribute nodes a project declaration may not carry (allowlist complement).

    Kept for the project rules; an attribute from a system/GLib header or a
    Clang-inserted implicit attribute is exempt. `node` is a subtree already known
    to be project origin."""
    result = set()
    stack = [node]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            kind = value.get('kind', '')
            if kind.endswith('Attr') and not value.get('implicit') and kind not in PROJECT_ALLOWED_ATTRIBUTES:
                result.add(kind)
            stack.extend(value.get('inner', []))
        elif isinstance(value, list):
            stack.extend(value)
    return sorted(result)


def ast_project_findings(node, origin_prefixes=None):
    """Sorted (rule, name) findings of the allowlist project rules in a Clang JSON AST.

    A source location counts as project origin when its file is under one of
    `origin_prefixes` (a tuple of absolute path prefixes); with no prefixes, the
    file name is ignored and every location is treated as project origin (the
    conservative default for a single-unit scan). Rules:
    - reserved-declaration: a project declaration or definition of a reserved
      identifier that is not in PROJECT_ALLOWED_RESERVED_DECLS;
    - runtime-interface: a declaration of, or reference to, a name with a
      RUNTIME_INTERFACE_PREFIXES prefix;
    - fuzzer-entry: a project `LLVMFuzzer*` name other than LLVMFuzzerTestOneInput;
    - project-builtin: a call of a __builtin_ not in PROJECT_ALLOWED_BUILTINS;
    - banned-call: a call of a PROJECT_BANNED_CALLS function (dlsym, dlopen, _exit, ...);
    - allocator-definition: a project definition of malloc, free or another allocator;
    - fuzzer-main: a definition of main in a fuzz harness (under fuzz/project/);
    - project-attribute: an attribute kind on a project declaration not in
      PROJECT_ALLOWED_ATTRIBUTES.
    """
    result = set()
    prefixes = tuple(origin_prefixes) if origin_prefixes is not None else None
    fuzz_prefixes = tuple(p for p in (prefixes or ()) if p.endswith('fuzz/project/'))

    def origin(file):
        return prefixes is None or (isinstance(file, str) and file.startswith(prefixes))

    def classify_name(name):
        if not name:
            return
        if name.startswith(RUNTIME_INTERFACE_PREFIXES):
            result.add(('runtime-interface', name))
        if name.startswith('LLVMFuzzer') and name != FUZZER_ENTRY:
            result.add(('fuzzer-entry', name))

    # Clang's JSON omits a loc 'file' when it is unchanged from the previously printed
    # location in pre-order. A single running current file reproduces that, so every
    # node is attributed to its real source file. referencedDecl locs are cross
    # references with their own file and are read independently.
    state = {'file': None}

    def visit(location):
        """Advance the running file over one printed location (Clang print order:
        spellingLoc, then expansionLoc, for a macro location); return the file of
        its expansion part."""
        if not isinstance(location, dict):
            return None
        if 'spellingLoc' in location or 'expansionLoc' in location:
            visit(location.get('spellingLoc'))
            return visit(location.get('expansionLoc'))
        if 'file' in location:
            state['file'] = location['file']
        return state['file'] if location else None

    def walk(value):
        if isinstance(value, list):
            for child in value:
                walk(child)
            return
        if not isinstance(value, dict):
            return
        # Every printed location updates the running file in print order: loc, then
        # range.begin, then range.end. The node belongs to the expansion file of its
        # loc (or of range.begin when it has no loc).
        own = visit(value.get('loc')) if value.get('loc') else None
        begin = visit(value.get('range', {}).get('begin'))
        visit(value.get('range', {}).get('end'))
        current = own if value.get('loc') else begin if value.get('range', {}).get('begin') else state['file']
        kind = value.get('kind', '')
        here = origin(current)
        # Clang creates an implicit FunctionDecl for a builtin at its first use; such a
        # compiler-made declaration is no project declaration (calls are checked below).
        if (here and kind in _DECL_KINDS and isinstance(value.get('name'), str)
                and not value.get('isImplicit') and not value['name'].startswith('__builtin_')):
            name = value['name']
            classify_name(name)
            if (_is_reserved(name) and name not in PROJECT_ALLOWED_RESERVED_DECLS
                    and not name.startswith(RUNTIME_INTERFACE_PREFIXES)
                    and not (name.startswith('LLVMFuzzer') and name != FUZZER_ENTRY)):
                result.add(('reserved-declaration', name))
        defines = kind == 'FunctionDecl' and any(c.get('kind') == 'CompoundStmt' for c in value.get('inner', [])
                                                 if isinstance(c, dict))
        if here and defines and value.get('name') in PROJECT_RESERVED_DEFINITIONS:
            result.add(('allocator-definition', value['name']))
        if (here and defines and value.get('name') == 'main' and isinstance(current, str)
                and fuzz_prefixes and current.startswith(fuzz_prefixes)):
            # A harness may not replace the libFuzzer driver.
            result.add(('fuzzer-main', 'main'))
        if (here and kind.endswith('Attr') and not value.get('implicit')
                and kind not in PROJECT_ALLOWED_ATTRIBUTES):
            result.add(('project-attribute', kind))
        if kind == 'DeclRefExpr':
            declaration = value.get('referencedDecl', {}) or {}
            name = declaration.get('name', '')
            # A reference site is project origin by its own location. A reserved name
            # the project declared is refused at its declaration.
            if here:
                classify_name(name)
                if name.startswith('__builtin_') and name not in PROJECT_ALLOWED_BUILTINS:
                    result.add(('project-builtin', name))
                if name in PROJECT_BANNED_CALLS:
                    result.add(('banned-call', name))
        for child in value.get('inner', []):
            walk(child)

    walk(node)
    return sorted(result)


def ast_call_sites(node):
    sites=[]
    def callee(value):
        if value.get('kind')=='DeclRefExpr':return value.get('referencedDecl',{}).get('name')
        for child in value.get('inner',[]):
            name=callee(child)
            if name:return name
    def walk(value,function=''):
        if not isinstance(value,dict):return
        if value.get('kind')=='FunctionDecl':function=value.get('name','')
        if value.get('kind')=='CallExpr' and value.get('inner'):
            name=callee(value['inner'][0])
            if name in {'gets','strcpy','strcat','sprintf','atoi','system','popen','alloca'}:
                begin=value.get('range',{}).get('begin',{})
                sites.append((name,function,'expansionLoc' in begin))
        for child in value.get('inner',[]):walk(child,function)
    walk(node)
    return sites


def ast_foundation_uses(node, policy, source, inventory):
    """Extend the existing AST gate with actual first-party expressions.

    Header declarations/inline definitions do not grant API permission. Exact
    boundary paths must also exist in the protected source-to-target inventory;
    ownership and input pointer validity remain documented caller conventions.
    """
    expected = policy['boundary_inventory'].get(source)
    declared = inventory.get(source, {})
    boundary = (source in policy['boundaries'] and expected is not None and
                all(declared.get(key) == value for key, value in expected.items()))
    allowed = set(policy['approved_glib_functions'])
    forbidden = set(policy['forbidden_glib_functions'])
    raw = set(policy['raw_memory_functions'])
    restricted = set(policy['restricted_types'])
    cleanup = set()
    for name in policy['approved_cleanup_types']:
        cleanup.update({'glib_autoptr_cleanup_' + name, 'glib_autoptr_clear_' + name})
    cleanup.update({'g_autoptr_cleanup_generic_gfree', 'g_clear_pointer', 'g_steal_pointer'})
    findings = []

    def record(rule, function, name, value):
        location = value.get('range', {}).get('begin', value.get('loc', {}))
        findings.append({'rule': rule, 'function': function, 'name': name,
                         'macro': 'expansionLoc' in location, 'source': source})

    def reference(value):
        if value.get('kind') == 'DeclRefExpr':
            return value.get('referencedDecl', {})
        for child in value.get('inner', []):
            found = reference(child)
            if found:
                return found
        return {}

    def walk(value, function):
        kind = value.get('kind')
        if kind in {'NoSanitizeAttr', 'AsmStmt', 'GCCAsmStmt'}:
            record('suppression-or-inline-assembly', function, kind, value)
        if kind == 'DeclRefExpr':
            declaration = value.get('referencedDecl', {})
            name = declaration.get('name', '')
            if declaration.get('kind') == 'FunctionDecl':
                if name in forbidden:
                    record('forbidden-glib-api', function, name, value)
                elif not boundary and name in raw:
                    record('raw-memory-api', function, name, value)
                elif not boundary and name.startswith(('g_', 'glib_')) and name not in allowed | cleanup:
                    record('unapproved-glib-api', function, name, value)
        if not boundary and kind in {'VarDecl', 'ParmVarDecl', 'MemberExpr', 'DeclRefExpr'}:
            type_name = value.get('type', {}).get('qualType', '')
            if any(re.search(r'\b' + re.escape(name) + r'\b', type_name) for name in restricted):
                record('restricted-mutable-type', function, type_name, value)
        if not boundary and kind == 'ArraySubscriptExpr':
            record('raw-indexing', function, kind, value)
        if not boundary and kind == 'CallExpr' and value.get('inner'):
            declaration = reference(value['inner'][0])
            if declaration.get('kind') != 'FunctionDecl':
                record('unknown-call-indirection', function, declaration.get('name', ''), value)
            elif declaration.get('name') == 'g_free' and len(value['inner']) > 1:
                argument_type = value['inner'][1].get('type', {}).get('qualType', '')
                # Peel implicit pointer conversions to retain the owned type.
                argument = value['inner'][1]
                while argument.get('kind') == 'ImplicitCastExpr' and argument.get('inner'):
                    argument = argument['inner'][0]
                    argument_type = argument.get('type', {}).get('qualType', argument_type)
                if not re.fullmatch(r'(?:gchar|char)\s*\*', argument_type):
                    record('incompatible-owned-cleanup', function, argument_type, value)
        for child in value.get('inner', []):
            walk(child, function)

    for declaration in node.get('inner', []):
        if declaration.get('kind') != 'FunctionDecl':
            continue
        location = declaration.get('loc', {})
        actual = location.get('expansionLoc', location)
        if 'includedFrom' in actual:
            continue
        for body in declaration.get('inner', []):
            if body.get('kind') in {'NoSanitizeAttr', 'AsmStmt', 'GCCAsmStmt'}:
                walk(body,declaration.get('name',''))
            if body.get('kind') == 'CompoundStmt':
                walk(body, declaration.get('name', ''))
    unique = {(row['rule'], row['function'], row['name'], row['macro']): row for row in findings}
    return [unique[key] for key in sorted(unique)]
