import json, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import server
from desktop_workspace import Workspace,REMOTE

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.checkout=self.root/'legacy';self.checkout.mkdir()
        self.run_git(self.checkout,'init','-q')
        self.run_git(self.checkout,'remote','add','origin',REMOTE)
        (self.checkout/'doc').mkdir();(self.checkout/'doc/Test.xml').write_text('<book><title>Test</title><para>Before.</para></book>')
        self.run_git(self.checkout,'add','.');self.run_git(self.checkout,'-c','user.name=Test','-c','user.email=test@example.com','commit','-qm','Base')
        self.base=self.run_git(self.checkout,'rev-parse','HEAD').strip()
        (self.checkout/'doc/Test.xml').write_text('<book><title>Test</title><para>After.</para></book>')
        self.run_git(self.checkout,'add','.');self.run_git(self.checkout,'-c','user.name=Test','-c','user.email=test@example.com','commit','-qm','Proposed')
        self.head=self.run_git(self.checkout,'rev-parse','HEAD').strip()
        self.workspace=Workspace(self.root/'app',legacy=[self.checkout]);self.workspace.initialize()
        self.pr={'number':877,'state':'open','title':'Test PR','base':{'sha':self.base,'ref':'main'},'head':{'sha':self.head,'ref':'feature','repo':{'full_name':'onvif/specs'}},'labels':[{'name':'WG_ai'}]}
        for name,value in [('REPO',self.workspace.repo),('STATE_DIR',self.workspace.reviews),('API_CACHE_DIR',self.workspace.metadata)]:
            p=patch.object(server,name,value);p.start();self.addCleanup(p.stop)
        server.API_INFO.value={'cached':False,'fetchedAt':1}
    def run_git(self,repo,*args):return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.PIPE,text=True)
    def download(self):
        # Local fixture transport exercises the actual fetch without external requests.
        self.run_git(self.workspace.repo,'remote','set-url','origin',str(self.checkout))
        with patch.object(server,'github_api',return_value=self.pr):return self.workspace.resolve_pr(877)
    def test_first_selected_pr_downloads_full_history_and_content(self):
        self.assertEqual(self.run_git(self.workspace.repo,'rev-parse','--is-bare-repository').strip(),'true')
        self.assertFalse((self.workspace.repo/'doc').exists())
        result=self.download();self.assertEqual(result['left'],self.base);self.assertEqual(result['right'],self.head)
        self.assertEqual(result['files'],['doc/Test.xml'])
        self.assertIn(b'After.',server.source(self.head,'doc/Test.xml'))
        self.assertIn(self.head,self.run_git(self.workspace.repo,'for-each-ref','--format=%(objectname)','refs/review'))
    def test_offline_reopens_downloaded_revision(self):
        online=self.download()
        with patch.object(server,'github_api',side_effect=OSError('Offline')):
            offline=self.workspace.resolve_pr(877)
        self.assertEqual(offline['right'],online['right']);self.assertTrue(offline['cache']['offline']);self.assertTrue(offline['github']['stale'])
        comparison=server.comparison(offline['left'],offline['right'],'doc/Test.xml',877)
        self.assertTrue(any(row['status']=='changed' for row in comparison['rows']))
    def test_uncached_pr_offline_explains_download_required(self):
        with patch.object(server,'github_api',side_effect=OSError('Offline')):
            with self.assertRaisesRegex(ValueError,'not been downloaded'):self.workspace.resolve_pr(877)
    def test_new_commits_checked_without_fetching_or_replacing_snapshot(self):
        self.download();old=self.workspace.manifest_path(877).read_bytes()
        self.pr['head']['sha']='d'*40
        with patch.object(server,'github_api',return_value=self.pr),patch.object(self.workspace,'fetch') as fetch:
            result=self.workspace.check_update(877,self.head)
        self.assertTrue(result['available']);fetch.assert_not_called();self.assertEqual(self.workspace.manifest_path(877).read_bytes(),old)
    def test_download_failure_preserves_original_revision(self):
        self.download();self.pr['head']['sha']='d'*40
        with patch.object(server,'github_api',return_value=self.pr),patch.object(self.workspace,'fetch',side_effect=ValueError('Offline')):
            result=self.workspace.resolve_pr(877,force=True)
        self.assertEqual(result['right'],self.head);self.assertTrue(result['cache']['offline'])
    def test_migration_and_cache_rebuild_preserve_notes_and_submission_journal(self):
        originals={}
        for kind in ('notes','draft','reviewed','reset','submissions'):
            name='xml-review-'+kind+'-pr-877.json';content=json.dumps({'saved':kind},indent=2).encode();originals[name]=content
            (self.checkout/'.git'/name).write_bytes(content)
        # A fresh app copies all exact bytes, including reviewed marks and submission safety.
        w=Workspace(self.root/'fresh',legacy=[self.checkout]);w.initialize()
        self.assertEqual(w.migration['copied'],5)
        for name,content in originals.items():self.assertEqual((w.reviews/name).read_bytes(),content);self.assertEqual((self.checkout/'.git'/name).read_bytes(),content)
        target=w.reviews/'xml-review-notes-pr-877.json';target.write_text('{"new":"app note"}')
        shutil.rmtree(w.repo);again=Workspace(w.root,legacy=[self.checkout]);again.initialize()
        self.assertEqual(target.read_text(),'{"new":"app note"}');self.assertEqual(again.migration['copied'],0)
        self.assertEqual(server.notes_path().parent,self.workspace.reviews)
    def test_migration_never_overwrites_app_review(self):
        name='xml-review-notes-pr-877.json';(self.checkout/'.git'/name).write_text('{"old":1}')
        w=Workspace(self.root/'fresh',legacy=[self.checkout]);w.reviews.mkdir(parents=True);(w.reviews/name).write_text('{"new":2}');w.initialize()
        self.assertEqual(json.loads((w.reviews/name).read_text()),{'new':2})
    def test_invalid_legacy_json_retains_original_and_warns(self):
        source=self.checkout/'.git/xml-review-notes-pr-877.json';source.write_text('broken')
        w=Workspace(self.root/'fresh',legacy=[self.checkout]);w.initialize()
        self.assertTrue(w.migration['warnings']);self.assertEqual(source.read_text(),'broken');self.assertFalse((w.reviews/source.name).exists())
    def test_wrong_origin_rejected(self):
        self.run_git(self.workspace.repo,'remote','set-url','origin','https://example.com/wrong.git')
        with self.assertRaisesRegex(ValueError,'unexpected remote'):self.workspace.initialize()
    def test_catalog_fallback_includes_downloaded_pr_and_labels(self):
        self.download()
        with patch.object(self.workspace,'original_list',side_effect=OSError('Offline')):
            result=self.workspace.catalog(True)
        self.assertEqual(result['prs'][0]['labels'],['WG_ai']);self.assertTrue(result['github']['stale'])

if __name__=='__main__':unittest.main()
