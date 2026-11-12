import io
import json
import tempfile
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import server

class ReviewTests(unittest.TestCase):
    def book(self,paras):
        return server.load(('<book><chapter xml:id="scope"><title>Scope</title>'+paras+'</chapter></book>').encode())
    def test_insert_does_not_shift_following_paragraphs(self):
        a=self.book('<para>First paragraph.</para><para>Last paragraph.</para>')
        b=self.book('<para>New paragraph.</para><para>First paragraph.</para><para>Last paragraph.</para>')
        self.assertEqual([r['status'] for r in server.compare(a,b)],['same','added','same','same'])
    def test_inline_markup_preserved(self):
        a,b=server.highlight('<p>Use <code>old</code> value.</p>','<p>Use <code>new</code> value.</p>')
        self.assertIn('<code><del>old</del></code>',a)
        self.assertIn('<code><ins>new</ins></code>',b)
    def test_repository_example(self):
        server.REPO=Path(os.environ.get('XML_REVIEW_TEST_REPO', server.default_repo()))
        if not (server.REPO/'doc/Agentic.xml').exists(): self.skipTest('Agentic.xml is not in this checkout')
        refs=server.git('for-each-ref','--format=%(refname:short)').decode().splitlines()
        if 'origin/AI/introducing_sosaobservation' not in refs: self.skipTest('Example branch has not been fetched')
        a=server.load(server.source('WORKTREE','doc/Agentic.xml'))
        b=server.load(server.source('origin/AI/introducing_sosaobservation','doc/Agentic.xml'))
        rows=server.compare(a,b)
        self.assertGreater(len(rows),100)
        self.assertTrue(any(r['status']!='same' for r in rows))
        self.assertTrue(all(r['status']=='same' for r in server.compare(a,a)))
        print('Example:',len(rows),'blocks;',sum(r['status']!='same' for r in rows),'changed')
    def test_escape_and_entities(self):
        self.assertIn('&lt;script&gt;',self.book('<para>&lt;script&gt;</para>')[1]['html'])
        with self.assertRaises(ValueError): server.load(b'<!DOCTYPE book><book/>')
    def test_pr_forks_excluded(self):
        def pr(repo):
            return {'number':1,'title':'Test','head':{'repo':{'full_name':repo},'ref':'feature'},'base':{'ref':'main'}}
        with patch.object(server,'github_repo',return_value='onvif/specs'), patch.object(server,'github_api',return_value=[pr('onvif/specs'),pr('other/specs')]):
            self.assertEqual(len(server.list_prs()['prs']),1)
    def test_pr_merge_base_includes_all_changed_files(self):
        pr={'number':877,'title':'Test','head':{'repo':{'full_name':'onvif/specs'},'ref':'feature','sha':'headsha'},'base':{'ref':'main','sha':'basesha'}}
        def git(*args):
            if args[0]=='merge-base': return b'ancestor\n'
            if args[0]=='diff': return b'doc/Agentic.xml\0README.md\0'
            return b''
        with patch.object(server,'github_repo',return_value='onvif/specs'), patch.object(server,'github_api',return_value=pr), patch.object(server,'git',side_effect=git):
            result=server.resolve_pr(877)
            self.assertEqual(result['left'],'ancestor')
            self.assertEqual(result['right'],'headsha')
            self.assertEqual(result['files'],['doc/Agentic.xml','README.md'])
    def test_notes_persist_edit_delete_and_isolate_reviews(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server,'notes_path',return_value=Path(folder)/'notes.json'):
            data={'pr':877,'review':'a'*64,'block':'b'*64,'text':'Review this <example>','context':'Paragraph','path':'doc/Agentic.xml'}
            server.save_note(data)
            self.assertEqual(server.read_notes(877)['a'*64]['b'*64]['text'],data['text'])
            server.save_note(dict(data,text='Updated'))
            self.assertEqual(server.read_notes(877)['a'*64]['b'*64]['text'],'Updated')
            server.save_note(dict(data,review='c'*64,text='Other review'))
            server.save_note(dict(data,text=''))
            self.assertEqual(server.read_notes(877)['a'*64],{})
            self.assertEqual(server.read_notes(877)['c'*64]['b'*64]['text'],'Other review')
            with self.assertRaises(ValueError): server.save_note(dict(data,review='../unsafe'))
    def test_fetch_only_updates_origin(self):
        result=type('Result',(),{'returncode':0})()
        with patch.object(server,'github_repo',return_value='onvif/specs'), patch.object(server.subprocess,'run',return_value=result) as run:
            self.assertTrue(server.fetch_latest()['fetched'])
            self.assertEqual(run.call_args.args[0],['git','-C',str(server.REPO),'fetch','--no-tags','origin'])
            self.assertEqual(run.call_args.kwargs['env']['GIT_TERMINAL_PROMPT'],'0')
    def test_fetch_failure_releases_lock(self):
        with patch.object(server,'github_repo',return_value='onvif/specs'), patch.object(server.subprocess,'run',side_effect=server.subprocess.TimeoutExpired('git',120)):
            with self.assertRaises(ValueError): server.fetch_latest()
            self.assertFalse(server.FETCH_LOCK.locked())
    def test_reviewed_marks_persist_and_can_be_cleared(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server,'reviewed_path',return_value=Path(folder)/'reviewed.json'):
            key='a'*64
            server.save_reviewed({'key':key,'reviewed':True})
            self.assertTrue(server.read_reviewed()[key])
            server.save_reviewed({'key':key,'reviewed':False})
            self.assertNotIn(key,server.read_reviewed())
            with self.assertRaises(ValueError): server.save_reviewed({'key':key,'reviewed':'true'})
    def test_review_identity_survives_relocation_but_not_content_change(self):
        row={'heading':'scope','status':'changed','left':'<p>Before</p>','right':'<p>After</p>'}
        a=[dict(row)];b=[{'status':'same'},dict(row)]
        server.review_keys('doc/Test.xml',a);server.review_keys('doc/Test.xml',b)
        self.assertEqual(a[0]['reviewKey'],b[1]['reviewKey'])
        b[1]['right']='<p>New version</p>';server.review_keys('doc/Test.xml',b)
        self.assertNotEqual(a[0]['reviewKey'],b[1]['reviewKey'])
        c=[dict(row)];server.review_keys('doc/Other.xml',c)
        self.assertNotEqual(a[0]['reviewKey'],c[0]['reviewKey'])
        duplicates=[dict(row),dict(row)];server.review_keys('doc/Test.xml',duplicates)
        self.assertNotEqual(duplicates[0]['reviewKey'],duplicates[1]['reviewKey'])
    def test_notes_are_separate_for_each_pr(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server,'notes_path',return_value=Path(folder)/'notes.json'):
            data={'review':'a'*64,'block':'b'*64,'text':'PR one','pr':877}
            server.save_note(data)
            server.save_note(dict(data,pr=878,text='PR two'))
            self.assertEqual(server.read_notes(877)['a'*64]['b'*64]['text'],'PR one')
            self.assertEqual(server.read_notes(878)['a'*64]['b'*64]['text'],'PR two')
            self.assertEqual(server.read_notes(),{})
            with self.assertRaises(ValueError): server.save_note(dict(data,pr=None))
            with self.assertRaises(ValueError): server.save_note(dict(data,pr='../unsafe'))
    def test_pr_summary_counts_all_documents_and_reports_errors(self):
        def fake_git(*args):
            return b'doc/A.xml\0doc/B.xml\0doc/Bad.xml\0' if args[0]=='diff' else b'commit\n'
        def comparison(left,right,path,pr=None):
            if path.endswith('Bad.xml'): raise ValueError('Invalid XML')
            return {'review':'a'*64,'rows':[{'id':'id','reviewKey':path,'heading':'Section','status':'changed','reviewed':path.endswith('A.xml'),'left':'Before','right':'After'}]}
        with patch.object(server,'git',side_effect=fake_git), patch.object(server,'comparison',side_effect=comparison), patch.object(server,'read_notes',return_value={}):
            summary=server.review_summary('left','right',877)
        self.assertEqual(len(summary['documents']),3)
        self.assertTrue(summary['documents'][0]['changes'][0]['reviewed'])
        self.assertFalse(summary['documents'][1]['changes'][0]['reviewed'])
        self.assertIn('error',summary['documents'][2])
    def test_github_disk_cache_and_explicit_refresh(self):
        class Response:
            headers={'ETag':'test-etag'}
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return b'{"value":1}'
        with tempfile.TemporaryDirectory() as folder, patch.object(server,'api_cache_path',return_value=Path(folder)/'cache.json'), patch.object(server,'github_token',return_value=None), patch.object(server.urllib.request,'urlopen',return_value=Response()) as request:
            self.assertEqual(server.github_api('repos/org/repo/pulls/1'),{'value':1})
            self.assertEqual(server.github_api('repos/org/repo/pulls/1'),{'value':1})
            self.assertEqual(request.call_count,1)
            self.assertTrue(server.API_INFO.value['cached'])
            server.github_api('repos/org/repo/pulls/1',force=True)
            self.assertEqual(request.call_count,2)
    def test_rate_limit_reset_and_cached_fallback(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server,'api_cache_path',return_value=Path(folder)/'cache.json'), patch.object(server,'github_token',return_value=None), patch.object(server.time,'time',return_value=1000):
            identity=server.hashlib.sha256(b'anonymous').hexdigest()
            file=Path(folder)/'cache.json';file.write_text(json.dumps({identity+':repos/org/repo/pulls/1':{'data':{'cached':True},'time':1}}))
            error=server.urllib.error.HTTPError('https://api.github.com/test',403,'Forbidden',{'X-RateLimit-Remaining':'0','X-RateLimit-Reset':'1300'},io.BytesIO(b'{"message":"API rate limit exceeded"}'))
            with patch.object(server.urllib.request,'urlopen',side_effect=error) as request:
                self.assertEqual(server.github_api('repos/org/repo/pulls/1'),{'cached':True})
                self.assertTrue(server.API_INFO.value['stale'])
                self.assertEqual(server.API_INFO.value['retryAt'],1300)
                self.assertEqual(server.github_api('repos/org/repo/pulls/1',force=True),{'cached':True})
                with self.assertRaises(server.GitHubError) as raised: server.github_api('repos/org/repo/pulls/2')
                self.assertEqual(raised.exception.retry_at,1300)
                self.assertEqual(request.call_count,1)
    def test_cached_pr_list_seeds_details_without_another_request(self):
        pr={'number':877,'head':{'sha':'head'},'base':{'sha':'base'}}
        class Response:
            headers={}
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return json.dumps([pr]).encode()
        with tempfile.TemporaryDirectory() as folder, patch.object(server,'api_cache_path',return_value=Path(folder)/'cache.json'), patch.object(server,'github_token',return_value=None), patch.object(server.urllib.request,'urlopen',return_value=Response()) as request:
            server.github_api('repos/org/repo/pulls?state=open')
            self.assertEqual(server.github_api('repos/org/repo/pulls/877'),pr)
            self.assertEqual(request.call_count,1)
    def test_non_rate_limit_403_does_not_invent_reset(self):
        error=server.urllib.error.HTTPError('https://api.github.com/test',403,'Forbidden',{'X-RateLimit-Remaining':'40'},io.BytesIO(b'{"message":"Resource not accessible"}'))
        parsed=server.github_error(error)
        self.assertIsNone(parsed.retry_at)
        self.assertIn('Resource not accessible',str(parsed))
    def test_secondary_rate_limit_retry_after(self):
        error=server.urllib.error.HTTPError('https://api.github.com/test',429,'Limit',{'Retry-After':'90'},io.BytesIO(b'{"message":"Secondary rate limit"}'))
        with patch.object(server.time,'time',return_value=1000): self.assertEqual(server.github_error(error).retry_at,1090)
    def test_reset_and_undo_are_isolated_to_selected_pr(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server,'notes_path',return_value=Path(folder)/'notes.json'):
            note={'pr':877,'review':'a'*64,'block':'b'*64,'text':'Keep me'}
            server.save_note(note);server.save_note(dict(note,pr=878,text='Other PR'))
            server.save_reviewed({'pr':877,'key':'c'*64,'reviewed':True})
            server.save_reviewed({'pr':878,'key':'c'*64,'reviewed':True})
            server.reset_review({'pr':877})
            self.assertEqual(server.read_notes(877),{})
            self.assertEqual(server.read_reviewed(877),{})
            self.assertEqual(server.read_notes(878)['a'*64]['b'*64]['text'],'Other PR')
            self.assertTrue(server.read_reviewed(878)['c'*64])
            server.reset_review({'pr':877},undo=True)
            self.assertEqual(server.read_notes(877)['a'*64]['b'*64]['text'],'Keep me')
            self.assertTrue(server.read_reviewed(877)['c'*64])
            self.assertFalse(server.reset_backup_path(877).exists())
    def test_pr_labels_are_returned_from_cached_metadata(self):
        pr={'number':877,'title':'Test','head':{'repo':{'full_name':'onvif/specs'},'ref':'feature'},'base':{'ref':'main'},'labels':[{'name':'WG_ai'}]}
        with patch.object(server,'github_repo',return_value='onvif/specs'),patch.object(server,'github_api',return_value=[pr]):
            self.assertEqual(server.list_prs()['prs'][0]['labels'],['WG_ai'])
    def compare_files(self,path,left,right):
        with patch.object(server,'file_bytes',side_effect=lambda ref,path:left if ref=='before' else right),patch.object(server,'version_label',side_effect=lambda ref:ref),patch.object(server,'read_reviewed',return_value={}):
            return server.comparison('before','after',path,877)
    def test_source_views_escape_markup_and_split_large_deletions(self):
        result=self.compare_files('index.html',b'<script>old()</script>\n',b'<script>new()</script>\n')
        self.assertEqual(result['mode'],'source')
        self.assertIn('&lt;script&gt;',result['rows'][0]['left'])
        self.assertNotIn('<script>',result['rows'][0]['left'])
        deleted=self.compare_files('removed.yaml',('value: old\n'*90).encode(),None)
        self.assertEqual(deleted['fileStatus'],'deleted')
        self.assertEqual(len(deleted['rows']),3)
        self.assertTrue(all(row['status']=='removed' for row in deleted['rows']))
    def test_source_review_keys_ignore_line_number_shifts(self):
        a=server.source_rows('first\nold\n','first\nnew\n');b=server.source_rows('inserted\nfirst\nold\n','inserted\nfirst\nnew\n')
        server.review_keys('file.yaml',a);server.review_keys('file.yaml',b)
        self.assertEqual(next(row['reviewKey'] for row in a if row['status']=='changed'),next(row['reviewKey'] for row in b if row['status']=='changed'))
    def test_images_and_binary_views(self):
        image=self.compare_files('diagram.png',b'\x89PNG\r\n\x1a\nold',b'\x89PNG\r\n\x1a\nnew')
        self.assertEqual(image['mode'],'image')
        self.assertIn('/api/asset?',image['rows'][0]['right'])
        self.assertEqual(len(image['rows']),1)
        binary=self.compare_files('file.bin',b'\0old',b'\0new')
        self.assertEqual(binary['mode'],'binary')
        self.assertIn('Binary file',binary['rows'][0]['right'])
    def test_empty_added_file_still_has_reviewable_change(self):
        result=self.compare_files('empty.txt',None,b'')
        self.assertEqual(result['fileStatus'],'added')
        self.assertEqual(result['rows'][0]['status'],'added')
    def test_docbook_identity_is_preserved(self):
        left=b'<book><chapter xml:id="scope"><title>Scope</title><para>Old.</para></chapter></book>'
        right=left.replace(b'Old.',b'New.')
        result=self.compare_files('doc/Test.xml',left,right)
        expected=server.compare(server.load(left),server.load(right))
        review=server.hashlib.sha256(json.dumps(['doc/Test.xml',server.load(left),server.load(right)],sort_keys=True).encode()).hexdigest()
        self.assertEqual(result['review'],review)
        for index,row in enumerate(expected):
            identity=server.hashlib.sha256(json.dumps([index,row],sort_keys=True).encode()).hexdigest()
            self.assertEqual(result['rows'][index]['id'],identity)
    def test_variablelists_keep_terms_and_nested_definitions(self):
        xml=b'<book><chapter><title>Test</title><variablelist><varlistentry><term>Input</term><term>Alias</term><listitem><para>Description.</para><variablelist><varlistentry><term>Child</term><listitem><para>Nested.</para></listitem></varlistentry></variablelist></listitem></varlistentry></variablelist></chapter></book>'
        markup=server.load(xml)[1]['html']
        self.assertIn('<dt>Input</dt><dt>Alias</dt><dd>',markup)
        self.assertIn('<dt>Child</dt><dd><p>Nested.</p></dd>',markup)
        self.assertNotIn('<li>',markup)
    def test_cals_horizontal_vertical_and_named_spans(self):
        xml=b'<book><chapter><title>Test</title><table><title>Parameters</title><tgroup cols="3"><colspec colname="a"/><colspec colname="b"/><colspec colname="c"/><spanspec spanname="pair" namest="a" nameend="b"/><thead><row><entry namest="a" nameend="c">Heading</entry></row></thead><tbody><row><entry spanname="pair" morerows="1">Merged</entry><entry>C1</entry></row><row><entry>C2</entry></row></tbody></tgroup></table></chapter></book>'
        markup=server.load(xml)[1]['html']
        self.assertIn('<caption>Parameters</caption>',markup)
        self.assertIn('<colgroup>',markup)
        self.assertIn('<th colspan="3">Heading</th>',markup)
        self.assertIn('<td colspan="2" rowspan="2">Merged</td>',markup)
        self.assertIn('<tr><td>C2</td></tr>',markup)
    def test_cals_structure_only_change_is_reviewable(self):
        a=b'<book><chapter><title>Test</title><informaltable><tgroup cols="2"><colspec colname="a"/><colspec colname="b"/><tbody><row><entry>Text</entry></row></tbody></tgroup></informaltable></chapter></book>'
        b=a.replace(b'<entry>Text',b'<entry namest="a" nameend="b">Text')
        result=self.compare_files('doc/Test.xml',a,b)
        self.assertEqual(result['rows'][1]['status'],'changed')
        self.assertIn('colspan="2"',result['rows'][1]['right'])
    def test_embedded_image_uses_revision_and_stable_blob_identifier(self):
        xml=b'<book><chapter><title>Test</title><figure><title>Diagram</title><mediaobject><imageobject><imagedata fileref="media/diagram.svg"/></imageobject></mediaobject></figure></chapter></book>'
        blob='a'*40
        with patch.object(server,'resolve_image',return_value={'blob':blob,'url':'/api/asset?blob='+blob}) as resolve:
            canonical,display=server.rich_blocks(xml,'commit-sha','doc/Test.xml')
        self.assertIn('[Image: media/diagram.svg]',canonical[1]['html'])
        self.assertIn('<img ',display[1]['displayHtml'])
        self.assertIn('<figcaption>Diagram</figcaption>',display[1]['displayHtml'])
        self.assertEqual(resolve.call_args.args[1:3],('commit-sha','doc/Test.xml'))
    def test_svg_mime_and_external_image_paths(self):
        self.assertEqual(server.image_mime(b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="2" height="2"/></svg>'),'image/svg+xml')
        self.assertIsNone(server.image_mime(b'<!DOCTYPE svg><svg/>'))
        for path in ('https://example.com/a.png','/etc/a.png','../../outside.png'):
            self.assertIsNone(server.resolve_image('test','sha','doc/Test.xml',path))
    def test_rich_definition_layout_preserves_existing_note_identity(self):
        xml=b'<book><chapter><title>Test</title><variablelist><varlistentry><term>Input</term><listitem><para>Old.</para></listitem></varlistentry></variablelist></chapter></book>'
        other=xml.replace(b'Old.',b'New.')
        canonical=server.compare(server.load(xml,rich=False),server.load(other,rich=False))
        result=self.compare_files('doc/Test.xml',xml,other)
        expected=server.hashlib.sha256(json.dumps([1,canonical[1]],sort_keys=True).encode()).hexdigest()
        self.assertEqual(result['rows'][1]['id'],expected)
        self.assertIn('<dt>',result['rows'][1]['right'])
    def test_embedded_image_changes_are_detected_without_xml_changes(self):
        xml=b'<book><chapter><title>Test</title><figure><mediaobject><imageobject><imagedata fileref="media/image.png"/></imageobject></mediaobject></figure></chapter></book>'
        def image(repo,ref,path,fileref):
            blob=('a' if ref=='before' else 'b')*40
            return {'blob':blob,'url':'/api/asset?blob='+blob}
        with patch.object(server,'resolve_image',side_effect=image):
            result=self.compare_files('doc/Test.xml',xml,xml)
        self.assertEqual(result['rows'][1]['status'],'changed')
        self.assertIn('a'*40,result['rows'][1]['left'])
        self.assertIn('b'*40,result['rows'][1]['right'])
    def test_media_chooses_supported_alternative(self):
        xml=b'<book><chapter><title>Test</title><mediaobject><imageobject><imagedata fileref="image.eps"/></imageobject><imageobject><imagedata fileref="image.png"/></imageobject></mediaobject></chapter></book>'
        def image(path):return {'blob':'a'*40,'url':'/image.png'} if path.endswith('.png') else None
        markup=server.load(xml,asset_resolver=image)[1]['html']
        self.assertIn('src="/image.png"',markup)
        self.assertNotIn('[Image:',markup)
    def review_fixture(self):
        return {'left':'a'*40,'right':'b'*40,'documents':[{'path':'doc/A.xml','changes':[{'heading':'Scope','left':'<p>Old</p>','right':'<p>New</p>','note':{'text':'Change feedback'}}]},{'path':'doc/B.xml','changes':[{'heading':'Other','left':'Ignored old','right':'Ignored new','note':None}]}]}
    def test_summary_and_file_notes_persist_and_reset_per_pr(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'notes_path',return_value=Path(folder)/'notes.json'):
            server.save_draft({'pr':877,'scope':'summary','text':'PR feedback'})
            server.write_api_cache(server.draft_path(877),{'summary':server.read_draft(877)['summary'],'files':{'doc/A.xml':{'text':'File feedback'}}})
            server.save_draft({'pr':878,'scope':'summary','text':'Other PR'})
            self.assertEqual(server.read_draft(877)['summary']['text'],'PR feedback\n\n### doc/A.xml\n\nFile feedback')
            server.reset_review({'pr':877})
            self.assertEqual(server.read_draft(877),{'summary':{},'files':{}})
            self.assertEqual(server.read_draft(878)['summary']['text'],'Other PR')
            server.reset_review({'pr':877},undo=True)
            self.assertIn('File feedback',server.read_draft(877)['summary']['text']);self.assertEqual(server.read_draft(877)['files'],{})
            with self.assertRaises(ValueError):server.save_draft({'pr':877,'scope':'file','path':'../outside','text':'No'})
    def test_review_preview_only_includes_commented_files(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'notes_path',return_value=Path(folder)/'notes.json'),patch.object(server,'github_repo',return_value='org/repo'),patch.object(server,'review_summary',return_value=self.review_fixture()),patch.object(server,'github_token',return_value=None):
            server.save_draft({'pr':877,'scope':'summary','text':'PR feedback'})
            server.write_api_cache(server.draft_path(877),{'summary':server.read_draft(877)['summary'],'files':{'doc/A.xml':{'text':'File feedback'}}})
            preview=server.prepare_review({'pr':877,'left':'a'*40,'right':'b'*40})
            self.assertIn('PR feedback',preview['body'])
            self.assertEqual([f['path'] for f in preview['files']],['doc/A.xml'])
            self.assertEqual([f['kind'] for f in preview['files']],['chunk'])
            self.assertIn('### doc/A.xml\n\nFile feedback',preview['body'])
            self.assertIn('Change feedback',preview['files'][0]['body'])
            self.assertNotIn('Change feedback',preview['body'])
            self.assertNotIn('File feedback',preview['files'][0]['body'])
            self.assertNotIn('Ignored old',preview['markdown'])
            self.assertNotIn('canSubmit',preview)
    def test_reflow_ignored(self):
        self.assertEqual(server.compare(self.book('<para>Two\n words</para>'),self.book('<para>Two words</para>'))[1]['status'],'same')
    def test_file_feedback_folds_once_without_losing_content_or_metadata(self):
        legacy={'summary':{'text':'Overall feedback','versions':{'right':'b'*40}},'files':{'old.xml':{'text':'Please check terminology.'},'other.xml':{'text':'Please check timeouts.'}}}
        merged=server.normalize_draft(legacy)
        self.assertEqual(merged['files'],{})
        self.assertIn('### old.xml\n\nPlease check terminology.',merged['summary']['text'])
        self.assertIn('### other.xml\n\nPlease check timeouts.',merged['summary']['text'])
        self.assertEqual(merged['summary']['versions'],legacy['summary']['versions'])
        self.assertEqual(server.normalize_draft(merged),merged)
        self.assertEqual(len(legacy['files']),2)
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'notes_path',return_value=Path(folder)/'notes.json'):
            server.write_api_cache(server.draft_path(877),legacy)
            self.assertEqual(server.read_draft(877),merged)
            server.save_draft({'pr':877,'scope':'summary','text':merged['summary']['text']+'\nEdited.'})
            self.assertEqual(server.read_draft(877)['summary']['text'].count('Please check terminology.'),1)
            with self.assertRaisesRegex(ValueError,'Use the PR summary'):server.save_draft({'pr':877,'scope':'file','path':'A.xml','text':'New file note'})

class ChunkThreadTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.repo=Path(self.folder.name);self.patch=patch.object(server,'REPO',self.repo);self.patch.start();self.addCleanup(self.patch.stop)
        server.git('init');server.git('config','user.name','Review Test');server.git('config','user.email','test@example.invalid')
    def commits(self,path,before,after):
        file=self.repo/path;file.parent.mkdir(parents=True,exist_ok=True)
        if before is not None:file.write_text(before)
        server.git('add','.');server.git('commit','--allow-empty','-m','Base');left=server.git('rev-parse','HEAD').decode().strip()
        if after is None:file.unlink()
        else:file.write_text(after)
        server.git('add','-A');server.git('commit','--allow-empty','-m','Proposed');right=server.git('rev-parse','HEAD').decode().strip()
        return left,right
    def doc(self,left,right,path):return server.review_summary(left,right,877)['documents'][0]
    def test_xml_chunks_anchor_to_distinct_source_lines_without_changing_note_ids(self):
        old='<book>\n<title>Review</title>\n<chapter xml:id="scope">\n<title>Scope</title>\n<para>Old é one.</para>\n<para>Unchanged.</para>\n<para>Old two.</para>\n</chapter>\n</book>\n'
        left,right=self.commits('A.xml',old,old.replace('Old','New'))
        before=server.comparison(left,right,'A.xml',877)
        doc=self.doc(left,right,'A.xml');anchors=server.chunk_anchors(left,right,doc)
        self.assertEqual(anchors,[{'subjectType':'LINE','side':'RIGHT','line':5},{'subjectType':'LINE','side':'RIGHT','line':7}])
        self.assertEqual(server.comparison(left,right,'A.xml',877),before)
        self.assertNotIn('source',server.load(old.encode())[0])
    def test_numbering_only_change_falls_back_to_independent_file_thread(self):
        old='<book>\n<chapter xml:id="scope">\n<title>Scope</title>\n<para>Same.</para>\n</chapter>\n</book>\n'
        new=old.replace('<chapter xml:id="scope">','<chapter xml:id="intro"><title>Intro</title><para>New.</para></chapter>\n<chapter xml:id="scope">')
        left,right=self.commits('A.xml',old,new);doc=self.doc(left,right,'A.xml');anchors=server.chunk_anchors(left,right,doc)
        index=next(i for i,row in enumerate(doc['changes']) if row['heading']=='Scope')
        self.assertEqual(anchors[index]['subjectType'],'FILE')
        self.assertIn('no changed source line',anchors[index]['reason'])
    def test_added_source_and_removed_source_choose_correct_side(self):
        left,right=self.commits('A.yaml',None,'value: new\n')
        self.assertEqual(server.chunk_anchors(left,right,self.doc(left,right,'A.yaml')),[{'subjectType':'LINE','side':'RIGHT','line':1}])
        # Reuse current head as a new base, then remove the file.
        (self.repo/'A.yaml').unlink();server.git('add','-A');server.git('commit','-m','Remove');removed=server.git('rev-parse','HEAD').decode().strip()
        self.assertEqual(server.chunk_anchors(right,removed,self.doc(right,removed,'A.yaml')),[{'subjectType':'LINE','side':'LEFT','line':1}])
    def test_long_source_chunks_use_their_own_line_ranges(self):
        left,right=self.commits('A.yaml',''.join('old '+str(i)+'\n' for i in range(80)),''.join('new '+str(i)+'\n' for i in range(80)))
        anchors=server.chunk_anchors(left,right,self.doc(left,right,'A.yaml'))
        self.assertEqual([anchor['line'] for anchor in anchors],[1,36,71])
    def test_separate_chunk_exports_and_file_note_have_line_or_file_target(self):
        left,right=self.commits('A.yaml','old 1\nsame\nold 2\n','new 1\nsame\nnew 2\n')
        comparison=server.comparison(left,right,'A.yaml',877)
        for i,row in enumerate(row for row in comparison['rows'] if row['status']!='same'):
            server.save_note({'pr':877,'review':comparison['review'],'block':row['id'],'text':'Chunk '+str(i),'path':'A.yaml'})
        server.write_api_cache(server.draft_path(877),{'summary':{},'files':{'A.yaml':{'text':'Whole file'}}})
        with patch.object(server,'github_repo',return_value='org/repo'),patch.object(server,'github_token',return_value='test-token'),patch.object(server,'github_api',return_value={'state':'open','base':{'sha':left},'head':{'sha':right}}):
            preview=server.prepare_review({'pr':877,'left':left,'right':right})
            self.assertEqual(len(preview['files']),2)
            self.assertIn('### A.yaml\n\nWhole file',preview['body'])
            self.assertEqual([comment['kind'] for comment in preview['files']],['chunk','chunk'])
            self.assertIn('Chunk 0',preview['files'][0]['body']);self.assertNotIn('Chunk 1',preview['files'][0]['body'])
            for index,comment in enumerate(preview['files']):
                self.assertEqual(comment['displayBody'],'Chunk '+str(index))
                self.assertNotIn('Before:',comment['body']);self.assertNotIn('After:',comment['body']);self.assertNotIn('## ',comment['body'])
            self.assertIn('Proposed line 1',preview['markdown']);self.assertIn('Proposed line 3',preview['markdown'])
            markers=[comment['body'].split('<!-- onvif-file-note:')[1] for comment in preview['files']]
            self.assertEqual(len(set(markers)),2)
    def test_patch_zero_length_sides_are_not_commentable(self):
        ranges=server.diff_line_ranges('@@ -0,0 +1,2 @@\n@@ -7 +8,0 @@')
        self.assertEqual(ranges,{'LEFT':[(7,7)],'RIGHT':[(1,2)]})

class BackupFeedbackTests(unittest.TestCase):
    def backup(self):
        return {'format':'onvif-spec-review','version':1,'repository':'org/repo','pr':877,
                'notes':{'a'*64:{'b'*64:{'text':'Block note','path':'doc/A.xml','context':'Before/after','versions':{'left':'a'*40,'right':'b'*40},'pr':'877'}}},
                'draft':{'summary':{'text':'Summary'},'files':{'doc/A.xml':{'text':'File feedback'}}},'reviewed':{'c'*64:True}}
    def test_backup_preview_restore_and_undo_preserve_other_prs(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'notes_path',return_value=Path(folder)/'notes.json'),patch.object(server,'github_repo',return_value='org/repo'):
            server.save_draft({'pr':877,'scope':'summary','text':'Original'})
            server.save_draft({'pr':878,'scope':'summary','text':'Other PR'})
            data={'pr':877,'backup':self.backup()}
            self.assertEqual(server.import_backup(data)['notes'],1)
            self.assertEqual(server.read_draft(877)['summary']['text'],'Original')
            server.import_backup({**data,'confirm':True})
            exported=server.review_backup(877)
            for key in ['notes','reviewed']:self.assertEqual(exported[key],data['backup'][key])
            self.assertEqual(exported['draft'],server.normalize_draft(data['backup']['draft']))
            self.assertEqual(server.read_draft(878)['summary']['text'],'Other PR')
            server.reset_review({'pr':877},undo=True)
            self.assertEqual(server.read_draft(877)['summary']['text'],'Original')
            self.assertEqual(server.read_reviewed(877),{})
    def test_invalid_backups_never_write(self):
        import copy
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'notes_path',return_value=Path(folder)/'notes.json'),patch.object(server,'github_repo',return_value='org/repo'),patch.object(server,'write_api_cache') as write:
            bad=[]
            for field,value in [('version',2),('repository','other/repo'),('pr',878),('reviewed',{'c'*64:'yes'}),('notes',[]),('draft',{'summary':{},'files':{'../outside':{'text':'No'}}})]:
                backup=copy.deepcopy(self.backup());backup[field]=value;bad.append(backup)
            backup=copy.deepcopy(self.backup());backup['notes']['a'*64]['b'*64]['text']='x'*20001;bad.append(backup)
            backup=copy.deepcopy(self.backup());backup['draft']['summary']['versions']={'left':{'unexpected':'object'}};bad.append(backup)
            for backup in bad:
                with self.assertRaises(ValueError):server.import_backup({'pr':877,'backup':backup,'confirm':True})
            write.assert_not_called()
    def test_import_rolls_back_failed_write(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'notes_path',return_value=Path(folder)/'notes.json'),patch.object(server,'github_repo',return_value='org/repo'):
            server.save_draft({'pr':877,'scope':'summary','text':'Keep me'})
            real=server.write_api_cache;failed=False
            def write(file,value):
                nonlocal failed
                if file==server.draft_path(877) and not failed:failed=True;raise OSError('Disk failed')
                real(file,value)
            with patch.object(server,'write_api_cache',side_effect=write):
                with self.assertRaises(OSError):server.import_backup({'pr':877,'backup':self.backup(),'confirm':True})
            self.assertEqual(server.read_draft(877)['summary']['text'],'Keep me')
            self.assertEqual(server.read_notes(877),{})
    def test_feedback_paginates_and_keeps_replies_outdated_locations_and_reviews(self):
        calls=[]
        def api(endpoint,force=False):
            calls.append((endpoint,force));server.API_INFO.value={'cached':True,'fetchedAt':123}
            if '/issues/' in endpoint:
                return [{'id':n,'body':'Discussion','user':{'login':'alice'},'created_at':'2026-01-01'} for n in range(100)] if endpoint.endswith('&page=1') else [{'id':101,'body':'Last page'}]
            if '/reviews?' in endpoint:return [{'id':201,'body':'','state':'APPROVED'},{'id':202,'body':'Private draft','state':'PENDING'}]
            return [{'id':301,'body':'<script>unsafe()</script>','path':'doc/A.xml','original_line':12,'line':None,'side':'RIGHT','in_reply_to_id':300},
                    {'id':302,'body':'File-level','path':'doc/A.xml','subject_type':'file','line':None}]
        with patch.object(server,'github_repo',return_value='org/repo'),patch.object(server,'github_api',side_effect=api):
            result=server.github_feedback(877,True)
        self.assertEqual(len(result['items']),104)
        self.assertEqual(len(calls),4)
        self.assertTrue(all(force for endpoint,force in calls))
        reply=next(i for i in result['items'] if i['id']=='301')
        self.assertTrue(reply['outdated']);self.assertEqual(reply['replyTo'],300)
        self.assertFalse(next(i for i in result['items'] if i['id']=='302')['outdated'])
        self.assertEqual(result['warnings'],[])
    def test_feedback_partial_failure_and_stale_cache_are_explicit(self):
        def api(endpoint,force=False):
            if '/reviews?' in endpoint:raise ValueError('Rate limited')
            server.API_INFO.value={'stale':True,'cached':True,'fetchedAt':123,'warning':'Offline'}
            return [{'id':1,'body':'Cached comment'}] if '/issues/' in endpoint else []
        with patch.object(server,'github_repo',return_value='org/repo'),patch.object(server,'github_api',side_effect=api):result=server.github_feedback(877)
        self.assertEqual(len(result['items']),1)
        self.assertIn('Offline',result['warnings'])
        self.assertTrue(any('Rate limited' in warning for warning in result['warnings']))

if __name__=='__main__': unittest.main()
