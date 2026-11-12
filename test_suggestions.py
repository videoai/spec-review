import json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import server
from desktop_workspace import Workspace

class SuggestionsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.repo=self.root/'repo';self.repo.mkdir();self.git('init','-q');self.git('remote','add','origin','https://github.com/videoai/test-specs.git')
        self.base_text='''<book>
<title>Demo</title>
<chapter>
<title>Timeouts</title>
<para>
The client shall retry after 5 seconds.
</para>
<para>Legacy guidance.</para>
</chapter>
</book>
'''
        (self.repo/'Demo.xml').write_text(self.base_text);self.git('add','.');self.git('-c','user.name=Test','-c','user.email=test@example.com','commit','-qm','Base');self.left=self.git('rev-parse','HEAD').strip()
        (self.repo/'Demo.xml').write_text(self.base_text.replace('5 seconds','300 seconds').replace('<para>Legacy guidance.</para>\n',''))
        self.git('add','.');self.git('-c','user.name=Test','-c','user.email=test@example.com','commit','-qm','Change');self.right=self.git('rev-parse','HEAD').strip()
        self.state=self.root/'reviews';self.state.mkdir()
        for name,value in [('REPO',self.repo),('STATE_DIR',self.state)]:
            p=patch.object(server,name,value);p.start();self.addCleanup(p.stop)
        self.result=server.comparison(self.left,self.right,'Demo.xml',1)
        self.row=next(row for row in self.result['rows'] if '300' in row['right'])
        self.data={'pr':1,'left':self.left,'right':self.right,'path':'Demo.xml','block':self.row['id'],'review':self.result['review']}
    def git(self,*args):return subprocess.check_output(['git','-C',str(self.repo),*args],stderr=subprocess.PIPE,text=True)
    def target(self):return server.suggestion_target(self.data)
    def save(self):
        target=self.target();replacement=target['original'].replace('300 seconds','45 seconds')
        payload=dict(self.data,versions={'left':self.left,'right':self.right},text='',suggestion={'text':replacement})
        return server.save_note(payload),replacement
    def test_maps_rendered_block_to_exact_xml_lines(self):
        target=self.target();self.assertTrue(target['available']);self.assertEqual(target['startLine'],5);self.assertEqual(target['line'],7)
        self.assertEqual(target['original'],'<para>\nThe client shall retry after 300 seconds.\n</para>')
    def test_suggestion_only_saves_previews_and_survives_backup(self):
        result,replacement=self.save();self.assertEqual(result['note']['suggestion']['text'],replacement)
        preview=server.prepare_review({'pr':1,'left':self.left,'right':self.right});self.assertEqual(preview['repo'],'videoai/test-specs')
        self.assertEqual(len(preview['files']),1);comment=preview['files'][0]
        self.assertIn('```suggestion\n'+replacement+'\n```',comment['body'])
        self.assertEqual(comment['anchor'],{'subjectType':'LINE','side':'RIGHT','line':7,'startLine':5,'startSide':'RIGHT'})
        backup=server.review_backup(1);self.assertEqual(server.validate_backup(backup,1)['notes'],1)
        server.import_backup({'pr':1,'backup':backup,'confirm':True})
        self.assertEqual(server.read_notes(1)[self.result['review']][self.row['id']]['suggestion']['text'],replacement)
    def test_invalid_xml_rejected_without_saving(self):
        with self.assertRaisesRegex(ValueError,'XML invalid'):server.validated_suggestion(self.data,{'text':'<para>Unclosed'})
        self.assertFalse(server.scoped_notes_path(1).exists())
    def test_unmodified_source_rejected(self):
        with self.assertRaisesRegex(ValueError,'Edit the suggested source'):server.validated_suggestion(self.data,{'text':self.target()['original']})
    def test_stale_source_location_rejected(self):
        target=self.target();target.update(text=target['original'].replace('300','45'),startLine=4)
        with self.assertRaisesRegex(ValueError,'source changed'):server.validated_suggestion(self.data,target)
    def test_removed_block_has_no_suggestion(self):
        row=next(row for row in self.result['rows'] if row['status']=='removed')
        result=server.suggestion_target(dict(self.data,block=row['id']));self.assertFalse(result['available']);self.assertIn('removed block',result['reason'])
    def test_delete_xml_block_suggestion(self):
        result=server.validated_suggestion(self.data,{'text':''});self.assertEqual(result['text'],'')
    def test_markdown_fences_rejected(self):
        with self.assertRaisesRegex(ValueError,'code fences'):server.validated_suggestion(self.data,{'text':'```suggestion\nbad\n```'})
    def test_suggestion_does_not_change_existing_note_identifiers(self):
        before=[(row['id'],row.get('reviewKey')) for row in self.result['rows']]
        self.target();self.save()
        after=server.comparison(self.left,self.right,'Demo.xml',1)
        self.assertEqual(before,[(row['id'],row.get('reviewKey')) for row in after['rows']])
    def test_repository_storage_isolation(self):
        production=Workspace(self.root/'app',legacy=[]);test=Workspace(self.root/'app',repository='videoai/test-specs')
        self.assertNotEqual(production.reviews,test.reviews);self.assertNotEqual(production.repo,test.repo);self.assertEqual(test.legacy,[])
        test.initialize();self.assertEqual(test.git('remote','get-url','origin').decode().strip(),'https://github.com/videoai/test-specs.git')
    def test_unapproved_repository_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unsupported'):Workspace(self.root/'app',repository='other/project')

if __name__=='__main__':unittest.main()
