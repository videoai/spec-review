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
            server.save_draft({'pr':877,'scope':'file','path':'doc/A.xml','text':'File feedback'})
            server.save_draft({'pr':878,'scope':'summary','text':'Other PR'})
            self.assertEqual(server.read_draft(877)['summary']['text'],'PR feedback')
            server.reset_review({'pr':877})
            self.assertEqual(server.read_draft(877),{'summary':{},'files':{}})
            self.assertEqual(server.read_draft(878)['summary']['text'],'Other PR')
            server.reset_review({'pr':877},undo=True)
            self.assertEqual(server.read_draft(877)['files']['doc/A.xml']['text'],'File feedback')
            with self.assertRaises(ValueError):server.save_draft({'pr':877,'scope':'file','path':'../outside','text':'No'})
    def test_review_preview_only_includes_commented_files(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'notes_path',return_value=Path(folder)/'notes.json'),patch.object(server,'github_repo',return_value='org/repo'),patch.object(server,'review_summary',return_value=self.review_fixture()),patch.object(server,'github_token',return_value=None):
            server.save_draft({'pr':877,'scope':'summary','text':'PR feedback'})
            server.save_draft({'pr':877,'scope':'file','path':'doc/A.xml','text':'File feedback'})
            preview=server.prepare_review({'pr':877,'left':'a'*40,'right':'b'*40})
            self.assertIn('PR feedback',preview['body'])
            self.assertEqual([f['path'] for f in preview['files']],['doc/A.xml'])
            self.assertIn('File feedback',preview['files'][0]['body'])
            self.assertIn('Change feedback',preview['files'][0]['body'])
            self.assertNotIn('Ignored old',preview['markdown'])
            self.assertFalse(preview['canSubmit'])
    def test_submit_prepares_file_threads_then_comment_review_once(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'notes_path',return_value=Path(folder)/'notes.json'),patch.object(server,'github_repo',return_value='org/repo'),patch.object(server,'review_summary',return_value=self.review_fixture()),patch.object(server,'github_token',return_value='test-token'),patch.object(server,'github_api',return_value={'state':'open','head':{'sha':'b'*40},'base':{'sha':'a'*40}}),patch.object(server,'git',return_value=('a'*40+'\n').encode()),patch.object(server,'github_write') as write:
            server.API_INFO.value={'stale':False}
            preview=server.prepare_review({'pr':877,'left':'a'*40,'right':'b'*40})
            url='https://github.com/org/repo/pull/877#pullrequestreview-12'
            write.side_effect=[{'id':12,'node_id':'review-node','html_url':url},{'data':{'addPullRequestReviewThread':{'thread':{'id':'thread'}}}},{'html_url':url}]
            result=server.submit_review({'pr':877,'id':preview['id'],'confirm':True})
            self.assertTrue(result['submitted']);self.assertEqual(write.call_count,3)
            calls=write.call_args_list
            self.assertNotIn('event',calls[0].args[1])
            self.assertEqual(calls[1].args[1]['variables']['input']['subjectType'],'FILE')
            self.assertNotIn('line',calls[1].args[1]['variables']['input'])
            self.assertEqual(calls[2].args[1]['event'],'COMMENT')
            self.assertTrue(server.submit_review({'pr':877,'id':preview['id'],'confirm':True})['alreadySubmitted'])
            self.assertEqual(write.call_count,3)
    def test_submission_rejects_stale_head_without_posting(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'notes_path',return_value=Path(folder)/'notes.json'),patch.object(server,'github_repo',return_value='org/repo'),patch.object(server,'review_summary',return_value=self.review_fixture()),patch.object(server,'github_token',return_value='test-token'),patch.object(server,'github_api',return_value={'state':'open','head':{'sha':'c'*40},'base':{'sha':'a'*40}}),patch.object(server,'github_write') as write:
            server.API_INFO.value={'stale':False};preview=server.prepare_review({'pr':877,'left':'a'*40,'right':'b'*40})
            with self.assertRaisesRegex(ValueError,'changed or closed'):server.submit_review({'pr':877,'id':preview['id'],'confirm':True})
            write.assert_not_called()
    def test_submission_requires_confirmation_and_blocks_uncertain_retries(self):
        with patch.object(server,'github_write') as write:
            with self.assertRaisesRegex(ValueError,'Confirm'):server.submit_review({'pr':877})
            write.assert_not_called()
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'notes_path',return_value=Path(folder)/'notes.json'),patch.object(server,'github_repo',return_value='org/repo'),patch.object(server,'review_summary',return_value=self.review_fixture()),patch.object(server,'github_token',return_value='test-token'),patch.object(server,'github_api',return_value={'state':'open','head':{'sha':'b'*40},'base':{'sha':'a'*40}}),patch.object(server,'git',return_value=('a'*40+'\n').encode()),patch.object(server,'github_write',side_effect=TimeoutError('Unknown result')) as write:
            server.API_INFO.value={'stale':False};preview=server.prepare_review({'pr':877,'left':'a'*40,'right':'b'*40})
            with self.assertRaisesRegex(ValueError,'Submission incomplete'):server.submit_review({'pr':877,'id':preview['id'],'confirm':True})
            with self.assertRaisesRegex(ValueError,'already started'):server.submit_review({'pr':877,'id':preview['id'],'confirm':True})
            self.assertEqual(write.call_count,1)
    def test_reflow_ignored(self):
        self.assertEqual(server.compare(self.book('<para>Two\n words</para>'),self.book('<para>Two words</para>'))[1]['status'],'same')
if __name__=='__main__': unittest.main()
