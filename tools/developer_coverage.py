"""Advisory coverage inspection using the existing qualified LLVM tools."""
from pathlib import Path
from evidence import GateError, atomic_json, file_hash, read_json, passed


def collect(root,runner,result,test):
    import json
    raw=runner.run_dir/'selected.profraw'
    runner.restore('selected.profraw',raw)
    merged=runner.run(['llvm-profdata','merge','-sparse','/work/selected.profraw','-o','/work/selected.profdata'],label='developer-coverage-merge')
    exported=runner.run(['llvm-cov','export','/work/developer-build/'+test['target'],
                         '-instr-profile=/work/selected.profdata'],label='developer-coverage-export')
    result['evidence_paths'] += [merged['evidence_path'],exported['evidence_path']]
    if not passed(merged) or not passed(exported):
        raise GateError('matching selected coverage export incomplete')
    rows=[]
    for package in json.loads(exported['output'])['data']:
        for item in package['files']:
            filename=item['filename']
            if not filename.startswith(('/src/','/fixture/')):continue
            relative=filename.removeprefix('/src/') if filename.startswith('/src/') else 'demo/'+filename.removeprefix('/fixture/')
            uncovered=sorted({s[0] for s in item.get('segments',[]) if s[3] and not s[2] and not (len(s)>5 and s[5])})
            branches=[{'line':b[0],'column':b[1],'true_count':b[4],'false_count':b[5]}
                      for b in item.get('branches',[]) if not b[4] or not b[5]]
            rows.append({'path':relative,'summary':item['summary'],
                         'uncovered_segment_start_lines':uncovered[:64],
                         'uncovered_branches':branches[:64],
                         'locations_truncated':len(uncovered)>64 or len(branches)>64})
    if not rows:raise GateError('selected coverage contains no identified first-party source')
    data={'status':'PASS','source_identity':result['source_identity'],
          'demo_source_identity':result.get('demo_source_identity'),
          'profile':'coverage','binary_sha256':result['result']['test_result']['binary_sha256'],
          'test_id':test['id'],'files':rows,'scope':'selected-test-only','acceptance':False,
          'raw_sha256':file_hash(raw),'evidence_paths':[merged['evidence_path'],exported['evidence_path']]}
    atomic_json(runner.run_dir/'coverage.json',data)
    return {'path':str(runner.run_dir/'coverage.json'),'sha256':file_hash(runner.run_dir/'coverage.json')}


def view(root,manifest,directory,current_identity):
    if manifest['profile']!='coverage' or manifest['source_identity']!=current_identity:
        raise GateError('coverage profile or current source identity mismatch')
    path=directory.parent/'coverage.json'
    if path.is_symlink() or not path.is_file():raise GateError('matching selected coverage unavailable')
    parent=read_json(directory.parent/'result.json')
    data=read_json(path)
    if (parent.get('coverage',{}).get('sha256')!=file_hash(path) or data['source_identity']!=current_identity or
            data['binary_sha256']!=manifest['binary']['sha256'] or data['profile']!='coverage' or
            data['test_id']!=manifest['test']['id'] or data['acceptance'] is not False):
        raise GateError('coverage source/binary/profile/test binding rejected')
    if manifest['demo_files']:
        workspace=manifest['request'].get('demo_workspace','')
        path=root/workspace/'candidate.c'
        if not workspace or path.is_symlink() or file_hash(path)!=data['demo_source_identity']:
            raise GateError('coverage demo input is stale or missing')
    return data
