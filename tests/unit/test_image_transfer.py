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

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from evidence import GateError
from image_transfer import inspect_archive,stream_copy,verified


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
