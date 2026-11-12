"""Offline integration check of an actual frozen desktop service. Never posts to GitHub."""
import argparse,http.cookiejar,json,os,subprocess,tempfile,urllib.error,urllib.request
from pathlib import Path
from urllib.parse import urlencode

def smoke(package):
    windows=os.name=='nt'
    git=package/('tools/git/cmd/git.exe' if windows else 'Contents/Resources/tools/git')
    resources=package if windows else package/'Contents/Resources'
    executable=resources/('backend/spec-review-service.exe' if windows else 'backend/spec-review-service')
    with tempfile.TemporaryDirectory(prefix='review-smoke-') as temp:
        temp=Path(temp);fixture=temp/'fixture';fixture.mkdir();support=temp/'support';cache=support/'repositories/videoai-test-specs.git'
        def git_run(folder,*args):return subprocess.check_output([str(git),'-C',str(folder),*args],stderr=subprocess.PIPE,text=True).strip()
        git_run(fixture,'init','-q');git_run(fixture,'config','user.name','CI test');git_run(fixture,'config','user.email','ci@example.invalid');git_run(fixture,'config','core.autocrlf','false')
        xml=fixture/'Demo.xml';xml.write_text('<book>\n<title>Demo</title>\n<chapter>\n<title>Timeout</title>\n<para>Use a 30-second timeout.</para>\n</chapter>\n</book>\n',encoding='utf-8')
        git_run(fixture,'add','.');git_run(fixture,'commit','-qm','Base');left=git_run(fixture,'rev-parse','HEAD')
        xml.write_text(xml.read_text().replace('30-second','300-second'),encoding='utf-8');git_run(fixture,'add','.');git_run(fixture,'commit','-qm','Proposed');right=git_run(fixture,'rev-parse','HEAD')
        cache.parent.mkdir(parents=True);subprocess.run([str(git),'init','--bare',str(cache)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        git_run(cache,'fetch',str(fixture),'HEAD');git_run(cache,'remote','add','origin','https://github.com/videoai/test-specs.git')
        reviews=support/'reviews/videoai-test-specs';reviews.mkdir(parents=True)
        (reviews/'xml-review-draft-pr-2.json').write_text(json.dumps({'summary':{'text':'Overall feedback.'},'files':{'Demo.xml':{'text':'Legacy file feedback.'}}}),encoding='utf-8')
        tools=[resources/'tools/gh/bin',resources/'tools/git/cmd'] if windows else [resources/'tools']
        env=dict(os.environ,XML_REVIEW_APP_SUPPORT=str(support),XML_REVIEW_GITHUB_REPO='videoai/test-specs',PATH=os.pathsep.join(map(str,tools))+os.pathsep+os.environ.get('PATH',''))
        if windows:
            env['GIT_EXEC_PATH']=str(resources/'tools/git/mingw64/libexec/git-core');env['GIT_TEMPLATE_DIR']=str(resources/'tools/git/mingw64/share/git-core/templates')
        log=temp/'service.log'
        with log.open('w') as stderr:
            child=subprocess.Popen([str(executable)],stdout=subprocess.PIPE,stderr=stderr,text=True,env=env)
            try:
                while True:
                    line=child.stdout.readline()
                    if not line:raise RuntimeError('Service stopped: '+log.read_text())
                    if line.startswith('SPEC_REVIEW_READY '):url=json.loads(line[18:])['url'];break
                base=url.split('/?')[0]
                try:urllib.request.urlopen(base+'/api/context');raise AssertionError('Unauthenticated access allowed')
                except urllib.error.HTTPError as error:assert error.code==403
                client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()));client.open(url).read()
                def api(path,data=None,origin=None):
                    request=urllib.request.Request(base+path,data=None if data is None else json.dumps(data).encode(),headers={} if data is None else {'Content-Type':'application/json','Origin':origin or base})
                    return json.load(client.open(request,timeout=30))
                assert api('/api/context')['repo']=='videoai/test-specs'
                html=client.open(base+'/').read().decode();assert 'fileNote' not in html.split('</style>')[-1]
                query={'pr':2,'left':left,'right':right,'path':'Demo.xml'};comparison=api('/api/compare?'+urlencode(query));row=next(row for row in comparison['rows'] if row['status']=='changed')
                target=api('/api/suggestion?'+urlencode(dict(query,block=row['id'])));assert target['available']
                payload={'pr':2,'review':comparison['review'],'block':row['id'],'path':'Demo.xml','versions':{'left':left,'right':right},'text':'Use a shorter timeout.','suggestion':{'text':target['original'].replace('300-second','45-second')}}
                try:api('/api/notes',payload,origin='https://example.invalid');raise AssertionError('Cross-origin write allowed')
                except urllib.error.HTTPError as error:assert error.code==400
                api('/api/notes',payload)
                preview=api('/api/review-preview',{'pr':2,'left':left,'right':right});assert len(preview['files'])==1;assert 'Legacy file feedback.' in preview['body'];assert '```suggestion' in preview['files'][0]['body'];assert '45-second' in preview['files'][0]['body']
                backup=api('/api/backup?pr=2');assert backup['draft']['files']=={}
                api('/api/reset',{'pr':2});assert not api('/api/note-history?pr=2')['reviews']
                api('/api/import-backup',{'pr':2,'backup':backup,'confirm':True});assert api('/api/note-history?pr=2')['reviews']
                print('Packaged backend: private session, origin checks, XML comparison, suggestion, summary migration, backup/import passed. No GitHub requests made.')
            finally:child.terminate();child.wait(timeout=15)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--package',required=True,type=Path);args=parser.parse_args();smoke(args.package.resolve())
