import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server
import build_site

class StaticBuildTests(unittest.TestCase):
    def test_static_export_keeps_ids_and_assets_but_never_local_notes_or_marks(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'REPO',Path(folder)):
            server.git('init');server.git('config','user.name','Test');server.git('config','user.email','test@example.invalid');server.git('remote','add','origin','https://github.com/org/repo.git')
            xml=Path(folder)/'A.xml';xml.write_text('<book><chapter><title>Scope</title><para>Old.</para></chapter></book>')
            server.git('add','.');server.git('commit','-m','Base');left=server.git('rev-parse','HEAD').decode().strip()
            xml.write_text('<book><chapter><title>Scope</title><para>New.</para><mediaobject><imageobject><imagedata fileref="diagram.svg"/></imageobject></mediaobject></chapter></book>')
            (Path(folder)/'diagram.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" onload="steal()"><script>steal()</script><rect width="10" height="10"/></svg>')
            server.git('add','.');server.git('commit','-m','Proposed');right=server.git('rev-parse','HEAD').decode().strip()
            comparison=server.comparison(left,right,'A.xml',877)
            changed=next(row for row in comparison['rows'] if row['status']!='same')
            server.save_note({'pr':877,'review':comparison['review'],'block':changed['id'],'text':'PRIVATE REVIEW NOTE','path':'A.xml'})
            server.save_draft({'pr':877,'scope':'summary','text':'PRIVATE SUMMARY'})
            server.save_reviewed({'key':changed['reviewKey'],'reviewed':True})
            pr={'number':877,'title':'Public PR','left':left,'right':right,'base':'main','head':'feature','files':['A.xml']}
            out=Path(folder)/'site'
            with patch.object(server,'resolve_pr',return_value=pr):result=build_site.build_site(out,[{'number':877,'title':'Public PR','labels':['WG_ai']}])
            self.assertEqual(result['errors'],[])
            manifest=json.loads((out/'site.json').read_text());payload=json.loads((out/manifest['prs'][0]['data']).read_text());doc=payload['comparisons']['A.xml']
            self.assertEqual(doc['review'],comparison['review']);self.assertEqual([row['id'] for row in doc['rows']],[row['id'] for row in comparison['rows']])
            self.assertFalse(any(row['reviewed'] for row in doc['rows']))
            public=''.join(file.read_text(errors='replace') for file in (out/'data').iterdir())
            self.assertNotIn('PRIVATE REVIEW',public);self.assertNotIn('PRIVATE SUMMARY',public)
            self.assertIn('./assets/',doc['rows'][-1]['right']);self.assertNotIn('/api/asset',doc['rows'][-1]['right'])
            svg=next((out/'assets').glob('*.svg')).read_text();self.assertNotIn('steal',svg);self.assertIn('rect',svg)
            html=(out/'index.html').read_text();self.assertIn('./pages.js',html);self.assertIn('Content-Security-Policy',html);self.assertNotIn('submitPreview',html)
    def test_svg_removes_active_content_external_resources_and_keeps_fragment_gradients(self):
        data=b'<svg xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g"/></defs><rect style="fill:url(#g)"/><use href="https://evil.invalid/a.svg"/><foreignObject><p>Bad</p></foreignObject><style>@import "https://evil.invalid";</style></svg>'
        output=build_site.safe_svg(data).decode()
        self.assertIn('url(#g)',output);self.assertNotIn('evil.invalid',output);self.assertNotIn('foreignObject',output)
    def test_nonempty_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'keep').write_text('Keep')
            with self.assertRaisesRegex(ValueError,'empty'):build_site.build_site(folder,[])
            self.assertEqual((Path(folder)/'keep').read_text(),'Keep')

if __name__=='__main__':unittest.main()
