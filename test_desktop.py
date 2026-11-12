import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import desktop_service as d

class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.preview={'id':'preview','repo':'onvif/specs','pr':877,'left':'a'*40,'right':'b'*40,'incomplete':[],'body':'Summary','url':'https://github.com/onvif/specs/pull/877','files':[{'path':'doc/Test.xml','body':'Chunk','anchor':{'subjectType':'LINE','line':12,'side':'RIGHT'}},{'path':'doc/Test.xml','body':'File note','anchor':{'subjectType':'FILE'}}]}
        self.data=dict(self.preview,confirm=True)
        def api(endpoint,**kw):return {'id':10} if endpoint=='user' else {'state':'open','head':{'sha':'b'*40},'base':{'sha':'c'*40}}
        for name,value in [('prepare_review',lambda data:self.preview),('github_api',api),('git',lambda *args:('a'*40).encode()),('notes_path',lambda:Path(self.temp.name)/'notes.json')]:
            p=patch.object(d.server,name,value);p.start();self.addCleanup(p.stop)
        d.server.API_INFO.value={}
    def writes(self,endpoint,payload):
        if endpoint.endswith('/reviews'):return {'id':44,'node_id':'node44','html_url':'https://github.com/onvif/specs/pull/877#review44'}
        return {'html_url':'https://github.com/onvif/specs/pull/877#review44'}
    def test_threads_and_idempotency(self):
        with patch.object(d,'github_write',side_effect=self.writes) as write:
            result=d.submit_review(self.data);self.assertIn('review44',result['url']);self.assertEqual(write.call_count,4)
            self.assertNotIn('event',write.call_args_list[0].args[1])
            self.assertEqual(write.call_args_list[1].args[1]['variables']['input']['line'],12)
            self.assertEqual(write.call_args_list[2].args[1]['variables']['input']['subjectType'],'FILE')
            self.assertEqual(write.call_args_list[-1].args[1]['event'],'COMMENT')
            d.submit_review(self.data);self.assertEqual(write.call_count,4)
    def test_playground_submission_uses_only_test_repository_and_range(self):
        from types import SimpleNamespace
        self.preview['repo']='videoai/test-specs'
        self.preview['files'][0]['anchor'].update(startLine=10,startSide='RIGHT')
        with patch.object(d,'WORKSPACE',SimpleNamespace(repository='videoai/test-specs')),patch.object(d,'github_write',side_effect=self.writes) as write:
            d.submit_review(self.data)
        endpoints=[call.args[0] for call in write.call_args_list]
        self.assertTrue(all(endpoint=='graphql' or endpoint.startswith('repos/videoai/test-specs/') for endpoint in endpoints))
        thread=write.call_args_list[1].args[1]['variables']['input'];self.assertEqual(thread['startLine'],10);self.assertEqual(thread['line'],12)
    def test_repository_mismatch_blocked_before_writes(self):
        from types import SimpleNamespace
        with patch.object(d,'WORKSPACE',SimpleNamespace(repository='videoai/test-specs')),patch.object(d,'github_write') as write:
            with self.assertRaisesRegex(ValueError,'Unsupported review repository'):d.submit_review(self.data)
            write.assert_not_called()
    def test_failure_cannot_repeat(self):
        with patch.object(d,'github_write',side_effect=OSError('Timeout')) as write:
            with self.assertRaisesRegex(ValueError,'pending review'):d.submit_review(self.data)
            with self.assertRaisesRegex(ValueError,'earlier attempt'):d.submit_review(self.data)
            self.assertEqual(write.call_count,1)
    def test_explicit_confirmation(self):
        with self.assertRaisesRegex(ValueError,'Confirm'):d.submit_review(dict(self.data,confirm=False))
    def test_changed_notes(self):
        with self.assertRaisesRegex(ValueError,'Notes changed'):d.submit_review(dict(self.data,id='old'))
    def test_repo_fixed(self):
        self.preview['repo']='other/repo'
        with self.assertRaisesRegex(ValueError,'Unsupported review repository'):d.submit_review(self.data)
    def test_changed_head(self):
        self.preview['right']='d'*40
        with self.assertRaisesRegex(ValueError,'PR changed'):d.submit_review(self.data)
    def test_stale_metadata(self):
        d.server.API_INFO.value={'stale':True}
        with self.assertRaisesRegex(ValueError,'unavailable'):d.submit_review(self.data)
    def test_incomplete(self):
        self.preview['incomplete']=['doc/bad.xml']
        with self.assertRaisesRegex(ValueError,'could not be checked'):d.submit_review(self.data)

class CookieTests(unittest.TestCase):
    def test_private_cookie(self):
        h=object.__new__(d.Handler)
        for cookie,expected in [('',False),('review_session=wrong',False),('review_session='+d.SESSION,True)]:
            h.headers={'Cookie':cookie};self.assertEqual(h.valid(),expected)

if __name__=='__main__':unittest.main()
