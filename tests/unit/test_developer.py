"""Developer metadata boundaries; native execution uses the protected runner."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from evidence import read_json, GateError
from schema_check import validate
from developer import admission
from developer_lsp import position, scalar_position, uri
from developer_gdb import parse
from developer_state import pack, restore
from developer_bundle import relative_path,diagnose
from developer_report import feedback,qualification
from developer_workspace import descriptor
import copy
import tempfile

ROOT = Path(__file__).resolve().parents[2]


class DeveloperInputTests(unittest.TestCase):
    def test_current_comparison_refuses_changed_regression_contract(self):
        with tempfile.TemporaryDirectory(dir='/work') as temporary:
            root=Path(temporary);control=root/'foundation/tests/control.c'
            control.parent.mkdir(parents=True);control.write_bytes(b'frozen control')
            from evidence import file_hash
            manifest={'run_id':'a'*32,'finding_id':'DEV-RUN-'+'a'*32,'source_identity':'b'*64,
                'profile':'debug','observed':{'status':'FAIL'},'evidence_paths':[],
                'original_replay_available':True,'test':{'id':'foundation.recipes'},'request':{},
                'source_files':{'foundation/tests/control.c':{'sha256':file_hash(control)}}}
            result=diagnose(root,manifest,root/'bundle')
            comparison=result['current_candidate_comparison']
            self.assertTrue(comparison['available'])
            self.assertEqual(comparison['original_run_id'],manifest['run_id'])
            self.assertIn(comparison['command'],result['follow_up'])
            control.write_bytes(b'changed expectation')
            changed=diagnose(root,manifest,root/'bundle')['current_candidate_comparison']
            self.assertFalse(changed['available'])
            control.unlink()
            self.assertFalse(diagnose(root,manifest,root/'bundle')['current_candidate_comparison']['available'])

    def test_debugger_outcome_contradictions_are_rejected(self):
        debug={'debug_session_status':'PASS','inspection_requirements_met':True,'complete_capture':True,
               'frames':[{'frame':{'func':'control'}}],'stop':{'reason':'breakpoint-hit','bkptno':'1'},
               'breakpoint':{'number':'1'},'errors':[],'timed_out':False,'recipe':'breakpoint',
               'inferior_outcome':{'status':'FAILED','exit_code':7}}
        value={'scope':'partial_feedback','acceptance':False,'status':'PASS','result':{'debugger':debug}}
        self.assertTrue(feedback(value))
        for key,replacement in [('debug_session_status','FAIL'),('complete_capture',False),
                                ('inspection_requirements_met',False),('timed_out',True),
                                ('stop',{'reason':'exited-normally'}),('breakpoint',{'number':'2'}),
                                ('inferior_outcome',{'status':'PASSED','exit_code':7})]:
            changed=copy.deepcopy(value);changed['result']['debugger'][key]=replacement
            with self.assertRaises(GateError):feedback(changed)

    def test_workspace_registration_is_exact_and_typed(self):
        with tempfile.TemporaryDirectory(dir='/work') as temporary:
            workspace=Path(temporary);(workspace/'candidate.c').write_bytes(b'candidate')
            context,files=descriptor(ROOT,workspace)
            self.assertEqual(context['primary'],'candidate.c');self.assertEqual(set(files),{'candidate.c'})
            (workspace/'unregistered.c').write_bytes(b'extra')
            with self.assertRaises(GateError):descriptor(ROOT,workspace)

    def test_developer_inventory_rejects_missing_controls_and_duplicate_rows(self):
        inventory=read_json(ROOT/'safety/developer-fixtures.json')
        value={'source_identity':'source','image_id':'image','status':'BLOCKED',
               'cases':[{'id':r['id'],'status':'BLOCKED','control':'BLOCKED',
                         'subchecks':[{'name':n,'status':'BLOCKED','control':'BLOCKED','evidence_paths':[],
                                       'reason':'not executed'} for n in r['subchecks']]} for r in inventory['cases']],
               'pipeline_variants':[{'parent':r['parent'],'name':r['name'],'variant':v,'status':'BLOCKED',
                                    'control':'BLOCKED','evidence_paths':[],'reason':'not executed'}
                                    for r in inventory['pipeline_subcases'] for v in r['variants']]}
        self.assertTrue(qualification(value,inventory,'source','image'))
        missing=copy.deepcopy(value);del missing['cases'][0]['subchecks'][0]['control']
        with self.assertRaises(GateError):qualification(missing,inventory,'source','image')
        duplicate=copy.deepcopy(value);duplicate['cases'][0]['subchecks'].append(copy.deepcopy(duplicate['cases'][0]['subchecks'][0]))
        with self.assertRaises(GateError):qualification(duplicate,inventory,'source','image')
        incomplete=copy.deepcopy(value);incomplete['status']='PASS'
        with self.assertRaises(GateError):qualification(incomplete,inventory,'source','image')
        masked=copy.deepcopy(value);masked['cases'][0]['subchecks'][0]['status']='FAIL'
        with self.assertRaises(GateError):qualification(masked,inventory,'source','image')
        unknown=copy.deepcopy(value);unknown['pipeline_variants'][0]['status']='UNKNOWN'
        with self.assertRaises(GateError):qualification(unknown,inventory,'source','image')

    def test_bundle_paths_and_required_retained_byte_fields(self):
        self.assertEqual(str(relative_path('foundation/include/sc-foundation.h')),'foundation/include/sc-foundation.h')
        for name in ['', '../escape.c','/tmp/outside.c','foundation/../escape.c','x\ny.c']:
            with self.assertRaises(GateError):relative_path(name)
        schema=read_json(ROOT/'schemas/developer-bundle.json')
        self.assertIn('source_files',schema['required'])
        self.assertIn('demo_files',schema['required'])
        self.assertFalse(schema['additionalProperties'])
    def test_mi_nested_records_and_duplicate_token_fields(self):
        row=parse('7^done,stack=[frame={level="0",func="example",args=[{name="count",value="16"}]}]')
        self.assertEqual(row['token'],7)
        self.assertEqual(row['fields']['stack'][0]['frame']['args'][0]['value'],'16')
        self.assertEqual(parse('*stopped,reason="exited",exit-code="01"')['fields']['exit-code'],'01')
        for bad in ['7^done,value="1",value="2"','unframed inferior text','^done,value={name="x"','^done,value="x"trailing']:
            with self.assertRaises(GateError):parse(bad)

    def test_state_roundtrip_rejects_changed_archive_and_namespace(self):
        with tempfile.TemporaryDirectory(dir='/work') as temporary:
            root=Path(temporary);build=root/'build';build.mkdir()
            (build/'entry.o').write_bytes(b'object bytes')
            stamp=1791220000123456789
            __import__('os').utime(build/'entry.o',ns=(stamp,stamp))
            limits=read_json(ROOT/'safety/developer-policy.json')['limits']
            pack(build,root/'packed','context',limits,{'source.c':'fingerprint'})
            result=restore(root/'restored',root/'packed','context',limits)
            self.assertEqual((root/'restored/entry.o').read_bytes(),b'object bytes')
            self.assertEqual((root/'restored/entry.o').stat().st_mtime_ns,stamp)
            self.assertEqual(result['source_files'],{'source.c':'fingerprint'})
            with self.assertRaises(GateError):restore(root/'wrong',root/'packed','other',limits)
            archive=root/'packed'/result['archives'][0]['path']
            archive.write_bytes(archive.read_bytes()+b'changed')
            with self.assertRaises(GateError):restore(root/'tampered',root/'packed','context',limits)

    def test_pinned_debian_version_paths_are_accepted(self):
        lock = read_json(ROOT / 'developer.lock.json')
        self.assertTrue(any('~' in row['path'] for row in lock['inputs']))
        validate(ROOT, 'developer-lock', lock)

    def test_admission_rejects_same_worktree_profile_and_releases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with admission(root,'debug'):
                with self.assertRaises(GateError):
                    with admission(root,'debug'):
                        self.fail('duplicate worktree/profile admitted')
                with admission(root,'clang-O0'):
                    pass
            with admission(root,'debug'):
                pass

    def test_unicode_positions_roundtrip_and_reject_split_scalars(self):
        text='/* café 😀 */ symbol\r\nnext'
        column=text.split('\r\n')[0].index('symbol')+1
        self.assertEqual(position(text,1,column,'utf-8')['character'],17)
        self.assertEqual(position(text,1,column,'utf-16')['character'],14)
        self.assertEqual(position(text,1,column,'utf-32')['character'],13)
        for encoding in ['utf-8','utf-16','utf-32']:
            self.assertEqual(scalar_position(text,position(text,1,column,encoding),encoding),
                             {'line':1,'column':column})
        for line,col in [(0,1),(1,0),(-1,1),(2147483647,1),(1,2147483647)]:
            with self.assertRaises(GateError):position(text,line,col,'utf-8')
        with self.assertRaises(GateError):scalar_position(text,{'line':0,'character':9},'utf-16')
        self.assertIn('%20',uri(Path('/src/path with space/µ.c')))
        self.assertIn('%C2%B5',uri(Path('/src/path with space/µ.c')))
