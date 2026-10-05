"""Build the real adapter with ClusterFuzzLite's supplied toolchain interface."""
from pathlib import Path
import hashlib,json,os,re,shlex,subprocess,sys

def main():
    variant=os.environ.get('SAFETY_QUALIFICATION_VARIANT','').removeprefix('foundation-')
    if variant not in {'good','bad','noop','omitted'}:raise ValueError('typed_foundation_fuzz_variant_required')
    out=Path(os.environ['OUT']);work=Path(os.environ['WORK'])
    if not all(p.is_relative_to('/work/adapter') and '..' not in p.parts for p in [out,work]):raise ValueError('owned_adapter_directories_required')
    out.mkdir(parents=True,exist_ok=True);work.mkdir(parents=True,exist_ok=True)
    lock=json.loads(Path('/src/foundation.lock.json').read_text());profile=lock['profiles']['fuzz'];prefix=Path(profile['prefix'])
    for name,expected in profile['files'].items():
        path=prefix/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('locked_fuzz_sdk_changed')
    flags=shlex.split(os.environ['CFLAGS'])
    for required in ['-fsanitize=address,undefined,fuzzer-no-link','-fno-sanitize-recover=all']:
        if required not in flags:raise ValueError('adapter_instrumentation_missing')
    safety_policy=Path('/src/cmake/Safety.cmake')
    matched=re.search(r'target_compile_options\(\$\{target\} PRIVATE (-Wall.*?)\)',safety_policy.read_text(),re.S)
    if matched is None:raise ValueError('production_warning_policy_missing')
    flags += shlex.split(matched.group(1))
    source='/src/foundation/src/sc-foundation.c'
    if variant=='bad':
        subprocess.run(['python3','/src/container/foundation-mutant.py','text-cap','/work/build/foundation-cfl-mutation'],check=True,timeout=10)
        source='/work/build/foundation-cfl-mutation/sc-foundation-mutant.c'
    harness='/src/foundation/tests/stateful-fuzzer.c'
    if variant=='noop':
        harness=str(work/'noop-harness.c')
        Path(harness).write_text('#include <stdint.h>\n#include <stddef.h>\nint LLVMFuzzerTestOneInput(const uint8_t *, size_t);\nint LLVMFuzzerTestOneInput(const uint8_t *p,size_t n) { (void)p;(void)n;return 0; }\n')
    shared=['-std=c17','-I/src/foundation/include','-I/src/foundation/tests','-isystem',str(prefix/'include/glib-2.0'),'-isystem',str(prefix/'lib/glib-2.0/include'),'-DGLIB_VERSION_MIN_REQUIRED=GLIB_VERSION_2_70','-DGLIB_VERSION_MAX_ALLOWED=GLIB_VERSION_2_70']
    records=[]
    for name,path in [('foundation',source),('harness',harness),('identity','/src/foundation/tests/dependency-identity.c')]:
        output=work/(name+'.o');argv=[os.environ['CC'],*flags,*shared,'-c',path,'-o',str(output)]
        subprocess.run(argv,check=True,timeout=30)
        records.append({'source':path,'source_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),'object':str(output),'object_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'command':argv})
    objects=[str(work/(name+'.o')) for name in ['foundation','harness','identity'] if variant!='omitted' or name!='foundation']
    argv=[os.environ['CXX'],*shlex.split(os.environ['CXXFLAGS']),*objects,str(prefix/'lib/libglib-2.0.so'),'-Wl,-rpath,'+str(prefix/'lib'),'-ldl',*shlex.split(os.environ['LIB_FUZZING_ENGINE']),'-o',str(out/'foundation_fuzzer')]
    subprocess.run(argv,check=True,timeout=30)
    receipt={'safety_policy_sha256':hashlib.sha256(safety_policy.read_bytes()).hexdigest(),'variant':variant,'profile':'fuzz','objects':records,'link_command':argv,'binary_sha256':hashlib.sha256((out/'foundation_fuzzer').read_bytes()).hexdigest(),'sdk_libraries':{name:profile['files'][name] for name in ['lib/libglib-2.0.so.0','lib/libpcre2-8.so.0']}}
    (out/'adapter-build.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'case_id':'foundation-cfl-'+variant,'verdict':'BUILT','file_path':str(out/'adapter-build.json')}));return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'verdict':'BLOCKED','error_type':type(error).__name__}));raise SystemExit(2)
