"""Data transfer rejects incomplete/changed images before Docker receives them."""
from pathlib import Path
import gzip
import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader,module_from_spec
from contextlib import redirect_stdout

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from evidence import GateError
from image_transfer import inspect_archive,stream_copy,verified,export


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory=Path(self.temporary.name)
        self.configs=[json.dumps({'architecture':'amd64','os':'linux',
            'config':{'User':'65534:65534'},'created':n,
            'rootfs':{'type':'layers','diff_ids':['sha256:'+'a'*64]}}).encode() for n in [1,2]]
        self.ids=['sha256:'+hashlib.sha256(p).hexdigest() for p in self.configs]

    def archive(self,*,rows=2,change=False,missing_layer=False):
        path=self.directory/'images.tar'
        manifest=[]
        with tarfile.open(path,'w') as archive:
            def add(name,data):
                info=tarfile.TarInfo(name);info.size=len(data)
                archive.addfile(info,io.BytesIO(data))
            for n in range(rows):
                name=self.ids[n][7:]+'.json'
                add(name,self.configs[n]+(b' ' if change and n==0 else b''))
                manifest.append({'Config':name,'RepoTags':None,'Layers':['shared-layer.tar']})
            if not missing_layer:add('shared-layer.tar',b'finite layer fixture')
            add('manifest.json',json.dumps(manifest).encode())
        return path

    def test_shared_layer_control(self):
        value=inspect_archive(self.archive(),self.ids)
        self.assertEqual(value['image_ids'],sorted(self.ids))

    def test_missing_image_rejected(self):
        with self.assertRaises(GateError):inspect_archive(self.archive(rows=1),self.ids)

    def test_changed_config_rejected(self):
        with self.assertRaises(GateError):inspect_archive(self.archive(change=True),self.ids)

    def test_missing_layer_rejected(self):
        with self.assertRaises(GateError):inspect_archive(self.archive(missing_layer=True),self.ids)

    def test_compressed_digest_and_cleanup(self):
        raw=self.archive();compressed=self.directory/'images.tar.gz'
        with gzip.open(compressed,'wb') as stream:stream.write(raw.read_bytes())
        digest=hashlib.sha256(compressed.read_bytes()).hexdigest()
        with verified(compressed,digest,self.ids) as (expanded,value):
            self.assertEqual(expanded.read_bytes(),raw.read_bytes())
            self.assertEqual(value['image_ids'],sorted(self.ids))
            held=expanded
        self.assertFalse(held.exists())
        with self.assertRaises(GateError):
            with verified(compressed,'0'*64,self.ids):self.fail('changed input accepted')

    def test_byte_boundary(self):
        for size in [0,1,8]:
            output=io.BytesIO();count,_=stream_copy(io.BytesIO(b'x'*size),output,maximum=8)
            self.assertEqual(count,size);self.assertEqual(output.getvalue(),b'x'*size)
        with self.assertRaises(GateError):stream_copy(io.BytesIO(b'x'*9),io.BytesIO(),maximum=8)

    def test_empty_archive_rejected(self):
        path=self.directory/'empty';path.write_bytes(b'')
        with self.assertRaises(GateError):
            with verified(path,'0'*64,self.ids):self.fail('empty input accepted')

    def test_export_parent_traversal_rejected_before_creation(self):
        root=self.directory/'source';root.mkdir()
        sibling=self.directory/'sibling';sibling.mkdir()
        destination=sibling/'..'/'source'/'export'
        with mock.patch('image_transfer.shutil.disk_usage',return_value=SimpleNamespace(free=12*1024**3)):
            with self.assertRaisesRegex(GateError,'new external transfer directory required'):
                export(root,destination,self.directory/'receipts')
        self.assertFalse((root/'export').exists())

    def observer(self,output):
        script=Path(__file__).resolve().parents[2]/'ci/runner-request'
        loader=SourceFileLoader('test_runner_request',str(script))
        module=module_from_spec(spec_from_loader(loader.name,loader));loader.exec_module(module)
        metadata={'exit_code':0,'failure':None,'output':json.dumps({'ID':'finite-metadata-fixture'})}
        context={'exit_code':0,'failure':None,'output':json.dumps([{'Name':'default','Endpoints':{'docker':{'Host':'unix:///var/run/docker.sock'}}}])}
        def fake(argv,**kw):return context if argv[1:3]==['context','inspect'] else metadata
        with mock.patch.object(sys,'argv',['runner-request','--output',str(output)]),mock.patch.object(module,'bounded',side_effect=fake),redirect_stdout(io.StringIO()):
            return module.main()

    def test_request_new_output_control(self):
        output=self.directory/'request.json'
        self.assertEqual(self.observer(output),0)
        value=json.loads(output.read_text())
        self.assertEqual(value['status'],'REQUEST_RECORDED')
        self.assertFalse(value['native_execution_authorized'])

    def test_request_existing_output_preserved(self):
        output=self.directory/'request.json';output.write_bytes(b'owned evidence')
        self.assertEqual(self.observer(output),1)
        self.assertEqual(output.read_bytes(),b'owned evidence')

    def test_request_linked_output_preserved(self):
        target=self.directory/'owned.json';target.write_bytes(b'owned evidence')
        output=self.directory/'request.json';output.symlink_to(target)
        self.assertEqual(self.observer(output),1)
        self.assertEqual(target.read_bytes(),b'owned evidence')

    def test_request_linked_parent_rejected(self):
        target=self.directory/'owned';target.mkdir()
        link=self.directory/'linked';link.symlink_to(target,target_is_directory=True)
        self.assertEqual(self.observer(link/'request.json'),1)
        self.assertFalse((target/'request.json').exists())

    def oci_archive(self,*,alter=False,additional=False):
        payloads={};roots=[];rows=[]
        def descriptor(value,media):
            data=json.dumps(value).encode();digest='sha256:'+hashlib.sha256(data).hexdigest()
            payloads['blobs/sha256/'+digest[7:]]=data
            return {'digest':digest,'size':len(data),'mediaType':media}
        layer=b'finite shared layer';digest='sha256:'+hashlib.sha256(layer).hexdigest()
        name='blobs/sha256/'+digest[7:];payloads[name]=layer
        layer_description={'digest':digest,'size':len(layer),'mediaType':'application/vnd.oci.image.layer.v1.tar'}
        for config in self.configs:
            c=descriptor(json.loads(config),'application/vnd.oci.image.config.v1+json')
            m=descriptor({'schemaVersion':2,'config':c,'layers':[layer_description]},'application/vnd.oci.image.manifest.v1+json')
            m['platform']={'architecture':'amd64','os':'linux'}
            empty=descriptor({},'application/vnd.oci.image.config.v1+json')
            evidence=descriptor({'predicateType':'finite-test-data'},'application/vnd.in-toto+json')
            a=descriptor({'schemaVersion':2,'config':empty,'layers':[evidence]},'application/vnd.oci.image.manifest.v1+json')
            a.update(platform={'architecture':'unknown','os':'unknown'},annotations={
                'vnd.docker.reference.type':'attestation-manifest','vnd.docker.reference.digest':m['digest']})
            index=descriptor({'schemaVersion':2,'manifests':[m,a]},'application/vnd.oci.image.index.v1+json')
            roots.append(index)
            rows.append({'Config':'blobs/sha256/'+c['digest'][7:],'RepoTags':None,'Layers':[name]})
        expected=[r['digest'] for r in roots]
        if additional:roots.append(dict(roots[0]))
        payloads['manifest.json']=json.dumps(rows).encode()
        payloads['index.json']=json.dumps({'schemaVersion':2,'manifests':roots}).encode()
        payloads['oci-layout']=json.dumps({'imageLayoutVersion':'1.0.0'}).encode()
        if alter:payloads[name]=b'changed shared layer'
        path=self.directory/'oci.tar'
        with tarfile.open(path,'w') as archive:
            for name,data in payloads.items():
                info=tarfile.TarInfo(name);info.size=len(data);archive.addfile(info,io.BytesIO(data))
        return path,expected

    def test_oci_index_and_attestation_control(self):
        path,expected=self.oci_archive();value=inspect_archive(path,expected)
        self.assertEqual(value['image_ids'],sorted(expected))
        self.assertEqual(value['config_ids'],sorted(self.ids))

    def test_oci_changed_layer_rejected(self):
        path,expected=self.oci_archive(alter=True)
        with self.assertRaises(GateError):inspect_archive(path,expected)

    def test_oci_additional_root_rejected(self):
        path,expected=self.oci_archive(additional=True)
        with self.assertRaises(GateError):inspect_archive(path,expected)
