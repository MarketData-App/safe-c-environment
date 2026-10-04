"""Frozen broader experiment. Misses do not change the qualification denominator."""
from evidence import read_json, file_hash, passed, GateError

def run_benchmark(q):
    manifest=read_json(q.root/'safety/benchmark-manifest.json')
    rows=[];evidence=[];complete=True
    support='/src/third_party/originals/arichardson/juliet-test-suite-c/testcasesupport'
    for item in manifest['cases']:
        row={'id':item['id'],'weakness':item['weakness'],'detector':item['detector'],'bad':'NOT_RUN','good':'NOT_RUN','findings':[],'miss':False,'false_positive':False,'evidence_paths':[]}
        if file_hash(q.root/item['source'])!=item['sha256']:raise GateError('frozen benchmark input changed')
        results={}
        for variant,define in [('bad','OMITGOOD'),('good','OMITBAD')]:
            output='/work/benchmark/'+item['id']+'_'+variant
            q.runner.run(['mkdir','-p','/work/benchmark'],label='benchmark-directory')
            # Juliet's Unix ALLOCA macro needs its platform declaration. This
            # benchmark-only header supplies it without changing any case.
            args=['gcc' if item['detector']=='gcc-analyzer' else 'clang','-std=c17','-O0','-g','-include','alloca.h','-I'+support,'-DINCLUDEMAIN','-D'+define,'/src/'+item['source'],support+'/io.c',support+'/std_thread.c','-pthread','-lm','-o',output]
            if item['detector']=='gcc-analyzer':args += ['-fanalyzer','-Wanalyzer-too-complex','-Wanalyzer-symbol-too-complex']
            else:args += ['-fsanitize=address,undefined','-fno-sanitize-recover=all']
            build=q.runner.run(args,timeout=45,label=item['id']+'-'+variant+'-build');row['evidence_paths'].append(build['evidence_path'])
            if not passed(build):
                row[variant]='BUILD_FAILURE';results[variant]=build;continue
            run=q.runner.run([output],timeout=10,label=item['id']+'-'+variant+'-run');row['evidence_paths'].append(run['evidence_path'])
            result=build if item['detector']=='gcc-analyzer' else run
            finding=item['expected'] in result['output']
            if result['failure']:
                row[variant]='INFRASTRUCTURE_FAILURE';complete=False
            elif item['detector']!='gcc-analyzer' and result['exit_code']!=0 and not finding:
                row[variant]='WRONG_DIAGNOSTIC'
            else:row[variant]='FINDING' if finding else 'CLEAN'
            if finding:row['findings'].append({'variant':variant,'class':item['expected'],'evidence':result['evidence_path'],'designated':True})
            elif 'LeakSanitizer: detected memory leaks' in result['output']:
                row['findings'].append({'variant':variant,'class':'detected memory leaks','evidence':result['evidence_path'],'designated':False})
            results[variant]=result
        row['miss']=row['bad']=='CLEAN';row['false_positive']=row['good']=='FINDING'
        # Invalid fixtures remain in all 20 rows; a complete observation of a
        # build failure is a dataset result, not a dropped denominator.
        rows.append(row);print(item['id']+': bad '+row['bad']+', good '+row['good'],flush=True)
    return {'execution_status':'PASS' if complete and len(rows)==len(manifest['cases']) else 'FAIL','dataset_version':manifest['dataset_version'],'dataset_manifest_sha256':file_hash(q.root/'safety/benchmark-manifest.json'),'total_pairs':len(rows),'bad_findings':sum(row['bad']=='FINDING' for row in rows),'misses':sum(row['miss'] for row in rows),'good_false_positives':sum(row['false_positive'] for row in rows),'good_other_findings':sum(row['good']=='WRONG_DIAGNOSTIC' for row in rows),'good_clean':sum(row['good']=='CLEAN' for row in rows),'build_failures':sum(row['bad']=='BUILD_FAILURE' or row['good']=='BUILD_FAILURE' for row in rows),'cases':rows,'limitations':'Juliet 1.3; selected good labels may avoid a bad input and contain other genuine defects. Designated-class alarms on good labels are reported as benchmark false positives without certifying those controls. Other findings remain separate. Execution completeness does not imply a detection threshold.'}
