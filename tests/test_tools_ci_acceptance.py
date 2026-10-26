"""Pure evidence/isolation tests; no native launch, CI dispatch or credential read."""
import hashlib
import ast
import importlib.util
import io
import json
import os
import re
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
import zipfile

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'tools-ci-acceptance.py'
if not SCRIPT.is_file():
    SCRIPT = HERE.parent / 'scripts/tools-ci-acceptance.py'
spec = importlib.util.spec_from_file_location('bogo_tools_ci_acceptance', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.environment = {'GITHUB_ACTIONS':'true', 'RUNNER_ENVIRONMENT':'github-hosted',
            'GITHUB_REPOSITORY':m.REPOSITORY, 'RUNNER_OS':'Windows',
            'GITHUB_SHA':'a'*40, 'RUNNER_TEMP':str(self.root),
            'GITHUB_RUN_ID':'40378182320','GITHUB_RUN_ATTEMPT':'1'}

    def tearDown(self):
        self.temp.cleanup()

    def test_fresh_hosted_context(self):
        self.assertEqual(m.hosted_context(self.environment,'Windows'), self.root)
        self.assertEqual(m.owned_root(self.root/'bogo-tools-acceptance',self.root),self.root/'bogo-tools-acceptance')

    def test_owner_or_wrong_host_context_refused(self):
        for key, value in [('GITHUB_ACTIONS','false'),('RUNNER_ENVIRONMENT','self-hosted'),
            ('GITHUB_REPOSITORY','unrelated/repo'),('RUNNER_OS','macOS'),
            ('GITHUB_SHA','main'),('RUNNER_TEMP','relative')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                m.hosted_context(dict(self.environment,**{key:value}),'Windows')
        with self.assertRaises(ValueError):m.hosted_context(self.environment,'Linux')

    def test_owned_root_cannot_escape_or_use_symlink(self):
        for value in [self.root/'different',self.root/'child/bogo-tools-acceptance',Path('bogo-tools-acceptance')]:
            with self.subTest(path=value), self.assertRaises(ValueError):m.owned_root(value,self.root)
        if os.name != 'nt':
            (self.root/'bogo-tools-acceptance').symlink_to(self.root,target_is_directory=True)
            with self.assertRaises(ValueError):m.owned_root(self.root/'bogo-tools-acceptance',self.root)

    def test_credentials_and_library_injection_removed_home_untouched(self):
        value={'HOME':'/fresh-vm-user','USERPROFILE':'C:\\Users\\runner','PATH':'/bin','SystemRoot':'C:\\Windows',
            'GH_TOKEN':'credential','GITHUB_TOKEN':'credential','ACTIONS_RUNTIME_TOKEN':'credential',
            'SOME_PASSWORD':'credential','AWS_ACCESS_KEY_ID':'credential','SSH_AUTH_SOCK':'credential',
            'AZURE_CLIENT_ID':'credential','DYLD_INSERT_LIBRARIES':'hook','INPUT_TOKEN':'credential'}
        self.assertEqual(m.clean_environment(value),{k:value[k] for k in ('HOME','USERPROFILE','PATH','SystemRoot')})

    def test_exact_asset_pin_and_api_digest_required(self):
        pin=m.PINS['windows'];ident,name,size,sha=pin
        asset={'id':ident,'name':name,'size':size,'digest':'sha256:'+sha,'state':'uploaded',
            'url':f'https://api.github.com/repos/{m.REPOSITORY}/releases/assets/{ident}'}
        self.assertEqual(m.validate_asset(asset,pin,m.RELEASE_ID)['sha256'],sha)
        for key,value in [('id',ident+1),('name','renamed.zip'),('size',size+1),('digest','sha256:'+'0'*64),('state','new'),('url','https://example.com/file')]:
            with self.subTest(key=key), self.assertRaises(ValueError):m.validate_asset(dict(asset,**{key:value}),pin,m.RELEASE_ID)

    def test_redirect_strips_bearer_and_refuses_other_hosts(self):
        request=urllib.request.Request('https://api.github.com/repos/'+m.REPOSITORY+'/releases/assets/1',headers={'Authorization':'Bearer synthetic-test-value'})
        result=m.Redirects().redirect_request(request,None,302,'Found',{},'https://release-assets.githubusercontent.com/example')
        self.assertIsNone(result.get_header('Authorization'))
        for target in ['http://github.com/file','https://example.com/file','https://github.com.evil.invalid/file']:
            with self.subTest(url=target),self.assertRaises(ValueError):m.Redirects().redirect_request(request,None,302,'Found',{},target)

    def test_no_redirect_for_authenticated_loopback_health(self):
        with self.assertRaises(ValueError):m.NoRedirect().redirect_request(None,None,302,'',{},'https://example.com/')

    def test_credential_cannot_leave_repository_api(self):
        for url in ['https://github.com/repo','https://api.github.com/repos/other/repository/releases/1','http://api.github.com/repos/'+m.REPOSITORY+'/releases/1',
                    'https://api.github.com/repos/'+m.REPOSITORY+'/releases/1',
                    f'https://api.github.com/repos/{m.REPOSITORY}/releases/{m.RELEASE_ID}?other=true']:
            with self.subTest(url=url),self.assertRaises(ValueError):m.request_url(url,'synthetic')

    def test_draft_request_is_get_only_and_only_exact_endpoint(self):
        with patch.object(m.urllib.request,'build_opener') as opener:
            m.request_url(f'https://api.github.com/repos/{m.REPOSITORY}/releases/{m.RELEASE_ID}','synthetic')
            request=opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_method(),'GET')
            self.assertEqual(request.get_header('Authorization'),'Bearer synthetic')

    def test_http_diagnostic_retains_actual_status_message_not_headers_or_secrets(self):
        raw=json.dumps({'message':'Exact server message synthetic-secret Bearer not-a-real-token',
            'documentation_url':'https://docs.github.com/rest/releases?private=value',
            'ignored':'synthetic-secret','headers':{'Authorization':'Bearer synthetic-secret'}}).encode()
        error=urllib.error.HTTPError('https://api.github.com/test',403,'Forbidden',{'X-Private':'synthetic-secret'},io.BytesIO(raw))
        value=m.safe_http_diagnostic(error,'synthetic-secret')
        self.assertEqual(value['status'],403)
        self.assertEqual(value['message'],'Exact server message [redacted] Bearer [redacted]')
        self.assertEqual(value['documentationUrl'],'https://docs.github.com/rest/releases')
        self.assertNotIn('synthetic-secret',json.dumps(value));self.assertNotIn('headers',value)
        large=urllib.error.HTTPError('https://api.github.com/test',403,'Forbidden',{},io.BytesIO(b'x'*8193))
        bounded=m.safe_http_diagnostic(large)
        self.assertTrue(bounded['bodyTruncated']);self.assertEqual(bounded['message'],'HTTP Error 403: Forbidden')
        absent=urllib.error.HTTPError('https://api.github.com/test',403,'Forbidden',{},None)
        self.assertEqual(m.safe_http_diagnostic(absent)['message'],'HTTP Error 403: Forbidden')

    def test_fetch_role_cannot_execute_accept_or_missing_role(self):
        for role in ('fetch',None,'unknown'):
            environment={} if role is None else {'BOGO_ACCEPTANCE_PHASE':role}
            with self.subTest(role=role),patch.dict(m.os.environ,environment,clear=True),self.assertRaises(ValueError):
                m.accept(self.root,'windows')
        m.require_phase({'BOGO_ACCEPTANCE_PHASE':'gui'},'gui')
        m.require_phase({'BOGO_ACCEPTANCE_PHASE':'fetch'},'fetch')

    def receipt(self,target='windows'):
        pins={'source':m.PINS['source'],target:m.PINS[target],target+'-update':m.PINS[target+'-update'],'envelope':m.ENVELOPE_PIN}
        assets={key:{'id':p[0],'name':p[1],'bytes':p[2],'sha256':p[3],'releaseId':m.RELEASE_ID} for key,p in pins.items()}
        assets['sourceBinding']={'repository':m.SOURCE_REPO,'commit':m.SOURCE_COMMIT,'byteExactFiles':438}
        url,size,sha=m.OLD_WINDOWS if target=='windows' else m.OLD_MACOS
        assets['prior']={'bytes':size,'sha256':sha,'url':url,'version':'4.6.21'}
        return {'repository':m.REPOSITORY,'releaseId':m.RELEASE_ID,'draft':True,'platform':target,
            'workflowSha':self.environment['GITHUB_SHA'],'assets':assets,'tokenPersisted':False,
            'fetchRole':'fetch-only','workflowRunId':self.environment['GITHUB_RUN_ID'],'workflowAttempt':'1'}

    def test_transfer_same_workflow_receipt_and_all_pins_required(self):
        for target in ('windows','macos'):
            receipt=self.receipt(target)
            self.assertEqual(len(m.validate_receipt(receipt,target,self.environment)),5)
            for key,bad in [('workflowRunId','2'),('workflowAttempt','2'),('workflowSha','b'*40),
                            ('platform','other'),('draft',False),('tokenPersisted',True),('fetchRole','gui')]:
                with self.subTest(target=target,key=key),self.assertRaises(ValueError):
                    m.validate_receipt(dict(receipt,**{key:bad}),target,self.environment)
            for mutate in ('source-pin','prior-pin','source-git','extra-field'):
                value=json.loads(json.dumps(receipt))
                if mutate=='source-pin':value['assets']['source']['sha256']='0'*64
                elif mutate=='prior-pin':value['assets']['prior']['version']='4.6.23'
                elif mutate=='source-git':value['assets']['sourceBinding']['byteExactFiles']=437
                else:value['unexpectedPrivateData']='must not transfer'
                with self.subTest(mutate=mutate),self.assertRaises(ValueError):m.validate_receipt(value,target,self.environment)

    def test_transferred_root_excludes_work_profiles_and_extra_files(self):
        receipt=self.receipt();assets=self.root/'assets';assets.mkdir();output=self.root/'output';output.mkdir()
        m.write_json(self.root/'receipt.json',receipt);m.write_json(output/'fetch-proof.json',receipt)
        for name in m.validate_receipt(receipt,'windows',self.environment):(assets/name).write_bytes(b'layout-only, bytes are separately rehashed by accept')
        self.assertEqual(m.transferred_inputs(self.root,'windows',self.environment),receipt)
        (self.root/'profile').mkdir()
        with self.assertRaises(ValueError):m.transferred_inputs(self.root,'windows',self.environment)
        (self.root/'profile').rmdir();(output/'private-session.json').write_text('{}')
        with self.assertRaises(ValueError):m.transferred_inputs(self.root,'windows',self.environment)
        (output/'private-session.json').unlink();m.write_json(output/'fetch-proof.json',dict(receipt,draft=False))
        with self.assertRaises(ValueError):m.transferred_inputs(self.root,'windows',self.environment)

    def test_workflow_separates_privileged_fetch_and_readonly_gui_vms(self):
        workflow=HERE/'tools-ci-acceptance.yml'
        if not workflow.is_file():workflow=HERE.parent/'.github/workflows/bogo-tools-acceptance.yml'
        source=workflow.read_text()
        fetch,gui=source.split('\n  fetch:\n',1)[1].split('\n  accept:\n',1)
        self.assertIn('contents: write',fetch);self.assertNotIn('contents: write',gui)
        self.assertIn('contents: read',gui);self.assertIn('needs: fetch',gui)
        self.assertIn('BOGO_ACCEPTANCE_PHASE: fetch',fetch);self.assertIn('BOGO_ACCEPTANCE_PHASE: gui',gui)
        self.assertNotIn('scripts/tools-ci-acceptance.py accept',fetch)
        self.assertNotIn('GH_TOKEN:',gui);self.assertNotIn('scripts/tools-ci-acceptance.py fetch',gui)
        self.assertIn('compression-level: 0',fetch)
        self.assertIn('actions/download-artifact@37930b1c2abaa49bbe596cd826c3c89aef350131',gui)
        self.assertNotIn('github-token:',gui);self.assertNotIn('run-id:',gui)

    def test_download_is_stream_checked_and_failed_partial_removed(self):
        payload=b'actual frozen payload';sha=hashlib.sha256(payload).hexdigest()
        with patch.object(m,'request_url',return_value=io.BytesIO(payload)):
            m.download('https://github.com/test',self.root/'good',len(payload),sha)
        self.assertEqual((self.root/'good').read_bytes(),payload)
        for size,digest in [(len(payload)-1,sha),(len(payload)+1,sha),(len(payload),'0'*64)]:
            with self.subTest(size=size,digest=digest),patch.object(m,'request_url',return_value=io.BytesIO(payload)),self.assertRaises(ValueError):
                m.download('https://github.com/test',self.root/'bad',size,digest)
            self.assertFalse((self.root/'bad').exists())
        with self.assertRaises(ValueError):m.download('https://github.com/test',self.root/'good',len(payload),sha)

    def test_public_git_blob_hash(self):
        self.assertEqual(m.git_blob(b'hello\n'),'ce013625030ba8dba906f756967f9e9ca394464a')

    def test_signed_envelope_is_exact_pinned_asset(self):
        self.assertEqual(m.ENVELOPE_PIN,(679016269,'Bogo-Tools-4.6.23-candidate-update-envelope.json',2374,'e7d424e0d6e5797b25f388a6322cf26f3e98d2bbc88cde53d474cc92520d4f48'))
        self.assertEqual(m.VERSION,'4.6.23')
        self.assertEqual(m.SOURCE_COMMIT,'f328c97865951603f49dd06eb7960122e4035662')
        self.assertEqual(m.PUBLIC_KEY,'JjeL9t/8GSrh2XZ25gawQyI475nXr/rU0li4CoEnfos=')
        for pin in [*m.PINS.values(),m.ENVELOPE_PIN]:
            self.assertEqual(len(pin[3]),64);self.assertGreater(pin[2],0)

    def test_real_manifest_fragment_ignores_cp1252_default_and_accepts_utf8_bom(self):
        # Exact raw row from the frozen SOURCE-MANIFEST.json (full manifest SHA
        # d0db864e227cbfa464bc2bcf2f3bb5878103b296e491c832165681b4d9bf2c41).
        fragment='''    {
      "path": "release-tools/KIO-Control-4.4.4-검증보고.md",
      "bytes": 6708,
      "sha256": "256a754b5b3505707ac684a781dbe8a3235de865af23e4a76430eec15f04b7d8",
      "source": "release-tools/KIO-Control-4.4.4-검증보고.md",
      "sourceSHA256": "256a754b5b3505707ac684a781dbe8a3235de865af23e4a76430eec15f04b7d8"
    }'''.encode('utf-8')
        self.assertEqual(hashlib.sha256(fragment).hexdigest(),'57695bfe7c1871fb7fac72a4e602855a9f33ca6df3936ada57c4f7cf4459a49b')
        with self.assertRaises(UnicodeDecodeError):fragment.decode('cp1252')
        path=self.root/'SOURCE-MANIFEST.json';original=Path.open
        def ansi_open(current,mode='r',buffering=-1,encoding=None,errors=None,newline=None):
            if 'b' not in mode and encoding in (None,'locale'):encoding='cp1252'
            return original(current,mode,buffering,encoding,errors,newline)
        for body in (fragment,b'\xef\xbb\xbf'+fragment):
            path.write_bytes(body)
            with patch.object(Path,'open',ansi_open):
                with self.assertRaises(UnicodeDecodeError):path.read_text()
                value=m.read_json_utf8(path)
            self.assertEqual(value['path'],'release-tools/KIO-Control-4.4.4-검증보고.md')

    def test_every_known_text_read_and_write_declares_utf8(self):
        tree=ast.parse(SCRIPT.read_text(encoding='utf-8'));checked=0
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in ('read_text','write_text'):
                values=[k.value for k in node.keywords if k.arg=='encoding']
                self.assertEqual(len(values),1,'Implicit locale text I/O at line '+str(node.lineno))
                self.assertIsInstance(values[0],ast.Constant)
                self.assertIn(values[0].value,('utf-8','utf-8-sig'));checked+=1
        self.assertGreater(checked,5)

    def test_only_actual_postpackaging_mac_executable_pin_accepted(self):
        current='3719dff4c53deedb85db9e3c7691e856201f7b111c93fed1f7a24eac180a273a'
        historical='e1afd018ddc5915349611b0e899c7de40df0230b3b49bbb380a07e19a944c731'
        self.assertEqual(m.EXE_SHA['macos'],current);self.assertEqual(m.EXE_BYTES['macos'],3666928)
        self.assertEqual(m.executable_metadata(current,3666928,'macos'),{'sha256':current,'bytes':3666928})
        for sha,size in [(historical,3666928),(current,3666927),('0'*64,3666928)]:
            with self.subTest(sha=sha,size=size),self.assertRaises(ValueError) as caught:m.executable_metadata(sha,size,'macos')
            self.assertIn('actual sha256='+sha,str(caught.exception));self.assertIn('actual',str(caught.exception))
            self.assertIn('bytes='+str(size),str(caught.exception));self.assertNotIn(str(self.root),str(caught.exception))

    def test_designated_requirement_uses_actual_frozen_stdout_not_executable_stderr(self):
        # Exact stdout/stderr captured read-only from the frozen signed bundle.
        stdout='designated => identifier "local.galaxycontrol.portable" and certificate leaf = H"72287f8a5048cd206db014ead6723c75cd459379"\n'
        stderr='Executable=/Volumes/KIO_SSD/KIO/Build/Bogo-Tools-20261026/4.6.23/stage/Bogo Tools.app/Contents/MacOS/KIOControl\n'
        value=m.designated_requirement(0,stdout)
        self.assertEqual(value,{'identifier':'local.galaxycontrol.portable','certificateLeafSha1':'72287f8a5048cd206db014ead6723c75cd459379','sourceStream':'stdout'})
        for code,body in [(1,stdout),(0,''),(0,stderr),(0,stdout.replace('local.galaxycontrol.portable','other.identifier')),
                          (0,stdout.replace('72287f8a5048cd206db014ead6723c75cd459379','0'*40)),
                          (0,stdout+stdout),(0,stdout.rstrip()+' or true\n'),(0,'x'*16385)]:
            with self.subTest(code=code,body=body[:60]),self.assertRaises(ValueError):m.designated_requirement(code,body)

    def test_platform_matrix_is_closed_identical_and_default_all(self):
        workflow=HERE/'tools-ci-acceptance.yml'
        if not workflow.is_file():workflow=HERE.parent/'.github/workflows/bogo-tools-acceptance.yml'
        source=workflow.read_text(encoding='utf-8')
        matrices=re.findall(r'^        include: (.+)$',source,re.M)
        self.assertEqual(len(matrices),2);self.assertEqual(matrices[0],matrices[1])
        cases=[json.loads(x) for x in re.findall(r"'(\[.*?\])'",matrices[0])]
        self.assertEqual([[r['platform'] for r in case] for case in cases],[['windows'],['macos'],['windows','macos']])
        self.assertEqual({r['runner'] for case in cases for r in case},{'windows-2022','macos-15-intel'})
        self.assertIn('default: all',source);self.assertEqual(source.count('"Invalid platform choice"'),2)
        self.assertNotIn('fromJSON(inputs.platform)',source)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)

    def tearDown(self):self.temp.cleanup()

    def archive(self,entries):
        path=self.root/('archive-'+str(len(list(self.root.iterdir())))+'.zip')
        with zipfile.ZipFile(path,'w') as z:
            for name,data,mode in entries:
                info=zipfile.ZipInfo(name);info.external_attr=mode<<16;z.writestr(info,data)
        return path

    def test_zip_path_components_are_bounded(self):
        self.assertEqual(str(m.member_path('Bogo Tools.app/Contents/Info.plist')),'Bogo Tools.app/Contents/Info.plist')
        for path in ['','/absolute','../escape','a/../escape','./a','a//b','a\\b','C:/file','a/./b','a\0b']:
            with self.subTest(path=path),self.assertRaises(ValueError):m.member_path(path)

    def test_extract_actual_file_and_link_structure(self):
        entries=[('root/file',b'preserved bytes',stat.S_IFREG|0o644)]
        # Windows ordinary hosted users need no symlink privilege for the core tests.
        if os.name!='nt':entries += [('root/current',b'file',stat.S_IFLNK|0o777)]
        archive=self.archive(entries);out=m.extract(archive,self.root/'out','root')
        self.assertEqual((out/'root/file').read_bytes(),b'preserved bytes')
        if os.name!='nt':self.assertEqual((out/'root/current').read_bytes(),b'preserved bytes')
        with self.assertRaises(ValueError):m.extract(archive,out,'root')

    def test_real_external_ancestor_alias_is_outside_zip_boundary(self):
        real=self.root/'real-parent';real.mkdir();alias=self.root/'external-alias'
        if os.name=='nt':
            # A directory junction is the ordinary Windows alias and requires no
            # developer-mode symlink permission. No app or downloaded code runs.
            ps=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
            subprocess.run([str(ps),'-NoProfile','-NonInteractive','-Command',
                '[void](New-Item -ItemType Junction -Path $env:BOGO_TEST_ALIAS -Target $env:BOGO_TEST_TARGET -ErrorAction Stop)'],
                env=dict(os.environ,BOGO_TEST_ALIAS=str(alias),BOGO_TEST_TARGET=str(real)),capture_output=True,check=True,timeout=30)
        else:alias.symlink_to(real,target_is_directory=True)
        self.assertTrue(os.path.samefile(alias,real))
        archive=self.archive([('root/file',b'outside alias is allowed; ZIP links remain forbidden',stat.S_IFREG|0o644)])
        m.extract(archive,alias/'out','root')
        self.assertEqual((real/'out/root/file').read_bytes(),b'outside alias is allowed; ZIP links remain forbidden')
        destination=alias/'out'
        with self.assertRaises(ValueError):m.extract(archive,destination,'root')
        if os.name!='nt':
            direct=self.root/'direct-target';direct.symlink_to(real/'not-created',target_is_directory=True)
            with self.assertRaises(ValueError):m.extract(archive,direct,'root')

    def test_wrong_root_and_duplicate_case_rejected(self):
        for entries in [[('other/file',b'x',0)], [('root/A',b'a',0),('root/a',b'b',0)]]:
            archive=self.archive(entries)
            with self.assertRaises(ValueError):m.extract(archive,self.root/('out-'+archive.stem),'root')

    def test_symlink_escape_and_descendant_write_refused(self):
        # These fail before symlink creation, also on ordinary Windows users.
        for entries in [
            [('root/link',b'../../escape',stat.S_IFLNK|0o777)],
            [('root/link',b'dir',stat.S_IFLNK|0o777),('root/link/file',b'bad',0)],
            [('root/link/file',b'bad',0),('root/link',b'dir',stat.S_IFLNK|0o777)],
        ]:
            archive=self.archive(entries)
            with self.assertRaises(ValueError):m.extract(archive,self.root/('out-'+archive.stem),'root')

    def test_sfx_requires_actual_embedded_payload_size_hash_and_magic(self):
        payload=b'PK'+b'frozen update archive'*100;sha=hashlib.sha256(payload).hexdigest()
        launcher=self.root/'portable.exe';launcher.write_bytes(b'MZ'+b'prefix'*40+payload+struct.pack('<Q8s',len(payload),b'KIOTOOLS'))
        result=m.portable_payload(launcher,self.root/'embedded.zip',len(payload),sha)
        self.assertEqual(result,{'bytes':len(payload),'sha256':sha})
        self.assertEqual((self.root/'embedded.zip').read_bytes(),payload)
        for label,size,expected in [('wrong-size',len(payload)+1,sha),('wrong-sha',len(payload),'0'*64)]:
            with self.subTest(label=label),self.assertRaises(ValueError):m.portable_payload(launcher,self.root/label,size,expected)
        launcher.write_bytes(b'MZ'+payload+struct.pack('<Q8s',len(payload),b'BADMAGIC'))
        with self.assertRaises(ValueError):m.portable_payload(launcher,self.root/'badmagic',len(payload),sha)

    def test_source_binding_requires_every_actual_file_and_git_bytes(self):
        # Production requires all 438 real entries. This deliberately short tree
        # must fail before any archive can be accepted as complete source.
        archive=self.archive([('file',b'body',0)])
        commit={'sha':m.SOURCE_COMMIT,'tree':{'sha':'a'*40}}
        tree={'truncated':False,'tree':[{'path':'source/file','type':'blob','mode':'100644','sha':m.git_blob(b'body')}]}
        with patch.object(m,'api',side_effect=[commit,tree]),self.assertRaises(ValueError):m.source_binding(archive)
        with patch.object(m,'api',return_value=dict(commit,sha='b'*40)),self.assertRaises(ValueError):m.source_binding(archive)

    def test_source_binding_checks_all_438_bodies_not_just_names(self):
        entries=[('file-'+str(n),('body-'+str(n)).encode(),0) for n in range(438)]
        archive=self.archive(entries)
        commit={'sha':m.SOURCE_COMMIT,'tree':{'sha':'a'*40}}
        rows=[{'path':'source/'+name,'type':'blob','mode':'100644','sha':m.git_blob(body)} for name,body,_ in entries]
        tree={'truncated':False,'tree':rows}
        with patch.object(m,'api',side_effect=[commit,tree]):
            self.assertEqual(m.source_binding(archive)['byteExactFiles'],438)
        rows[-1]=dict(rows[-1],sha='0'*40)
        with patch.object(m,'api',side_effect=[commit,tree]),self.assertRaises(ValueError):m.source_binding(archive)
        with patch.object(m,'api',side_effect=[commit,dict(tree,truncated=True)]),self.assertRaises(ValueError):m.source_binding(archive)

    def test_both_mac_member_bodies_and_both_outer_pins_required(self):
        body=b'measured final signed executable fixture';sha=hashlib.sha256(body).hexdigest()
        pins={}
        for key,member in [('macos','Bogo Tools.app/Contents/MacOS/KIOControl'),
                           ('macos-update','KIO-Control-Mac/Bogo Tools.app/Contents/MacOS/KIOControl')]:
            path=self.root/(key+'.zip')
            with zipfile.ZipFile(path,'w') as z:z.writestr(member,body)
            pins[key]=(1,path.name,path.stat().st_size,hashlib.sha256(path.read_bytes()).hexdigest())
        with patch.dict(m.PINS,pins),patch.dict(m.EXE_SHA,{'macos':sha}),patch.dict(m.EXE_BYTES,{'macos':len(body)}):
            result=m.macos_archive_executable_members(self.root)
            self.assertTrue(result['bothFrozenOuterZipsVerified']);self.assertTrue(result['exactPostpackagingMembers'])
            self.assertEqual([r['sha256'] for r in result['members']],[sha,sha])
            # An internally consistent but wrong member hash is never accepted.
            with patch.dict(m.EXE_SHA,{'macos':'0'*64}),self.assertRaises(ValueError):m.macos_archive_executable_members(self.root)
            with (self.root/'macos-update.zip').open('ab') as f:f.write(b'tampered outer archive')
            with self.assertRaises(ValueError):m.macos_archive_executable_members(self.root)

    def test_exact_tree_difference_reports_changed_missing_added_without_waiver(self):
        expected=self.root/'expected';actual=self.root/'actual';expected.mkdir();actual.mkdir()
        for root in (expected,actual):(root/'same.exe').write_bytes(b'same public code')
        (expected/'changed.exe').write_bytes(b'expected signed code');(actual/'changed.exe').write_bytes(b'changed code')
        (expected/'missing.dll').write_bytes(b'missing signed code');(actual/'added.tmp').write_bytes(b'unknown runtime file')
        left,right=m.inventory(expected),m.inventory(actual)
        result=m.tree_difference(left,right,expected,actual)
        self.assertFalse(result['matches']);self.assertEqual((result['missingCount'],result['addedCount'],result['changedCount']),(1,1,1))
        rows={r['path']:r for r in result['differences']}
        self.assertEqual(rows['changed.exe']['expectedSha256'],hashlib.sha256(b'expected signed code').hexdigest())
        self.assertEqual(rows['changed.exe']['actualSha256'],hashlib.sha256(b'changed code').hexdigest())
        self.assertEqual(rows['changed.exe']['actualBytes'],len(b'changed code'))
        self.assertEqual(rows['added.tmp']['kind'],'added');self.assertEqual(rows['missing.dll']['kind'],'missing')
        text=json.dumps(result)
        self.assertNotIn('unknown runtime file',text);self.assertNotIn(str(self.root),text)
        self.assertTrue(m.tree_difference(left,left,expected,expected)['matches'])

    def test_tree_diagnostic_bound_never_hides_a_failure_or_traverses_profile(self):
        actual=self.root/'actual';actual.mkdir()
        for n in range(205):(actual/('added-'+str(n))).write_bytes(b'public fixture')
        result=m.tree_difference({},m.inventory(actual),self.root,actual)
        self.assertFalse(result['matches']);self.assertEqual(result['addedCount'],205)
        self.assertTrue(result['truncated']);self.assertEqual(len(result['differences']),200)
        with self.assertRaises(ValueError):m.tree_difference({}, {'../profile/session.json':'0'*64},self.root,actual)
        with self.assertRaises(ValueError):m.tree_difference({}, {},self.root,actual,limit=201)


if __name__=='__main__':unittest.main()
