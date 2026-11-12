"""App-owned repository cache and durable review storage for onvif/specs."""
import configparser, json, os, re, shutil, subprocess, sys, threading, time
from pathlib import Path
import server

REMOTE='https://github.com/onvif/specs.git'
STATE_PATTERNS=re.compile(r'xml-review-(?:notes|draft|reviewed|reset|submissions)-pr-[1-9][0-9]*\.json$')

def default_app_root(platform=None,environ=None,home=None):
    platform=platform or sys.platform;environ=os.environ if environ is None else environ;home=Path.home() if home is None else Path(home)
    if platform=='win32':return Path(environ.get('LOCALAPPDATA') or home/'AppData/Local')/'ONVIF Spec Review'
    if platform=='darwin':return home/'Library/Application Support/ONVIF Spec Review'
    return Path(environ.get('XDG_DATA_HOME') or home/'.local/share')/'onvif-spec-review'

class Workspace:
    def __init__(self,root=None,legacy=None,report=None,repository='onvif/specs'):
        if repository not in server.SUPPORTED_REPOSITORIES:raise ValueError('Unsupported review repository')
        self.repository=repository
        self.remote='https://github.com/'+repository+'.git'
        slug=repository.replace('/','-')
        self.report=report or (lambda message:None)
        self.root=Path(root) if root else default_app_root()
        self.repo=self.root/('repositories/'+slug+'.git')
        self.reviews=self.root/('reviews/'+slug)
        self.metadata=self.root/('cache/'+slug)
        self.legacy=legacy if legacy is not None else [Path(os.environ.get('XML_REVIEW_REPO',str(Path.home()/'Documents/GitHub/specs'))),self.root/'specs']
        if repository!='onvif/specs' and legacy is None:self.legacy=[]
        self.status={'busy':False,'message':''};self.lock=threading.RLock();self.migration={'copied':0,'warnings':[]}
        self.original_list=server.list_prs
    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.repo),*args],stderr=subprocess.PIPE,timeout=30)
    def write(self,path,data):server.write_api_cache(path,data)
    def read(self,path,default=None):
        try:return json.loads(path.read_text())
        except (OSError,ValueError):return {} if default is None else default
    def initialize(self):
        for folder in (self.reviews,self.metadata,self.repo.parent):folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.report('Copying existing review notes into app storage…')
        self.migrate()
        if not self.repo.exists():
            self.status={'busy':True,'message':'Preparing the app repository cache…'}
            temporary=self.repo.with_name(self.repo.name+'.initializing')
            # A prior interrupted init contains no user files or review data.
            if temporary.exists():shutil.rmtree(temporary)
            subprocess.run(['git','init','--bare',str(temporary)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            subprocess.run(['git','-C',str(temporary),'remote','add','origin',self.remote],check=True,stderr=subprocess.PIPE)
            temporary.rename(self.repo)
        remote=self.git('remote','get-url','origin').decode().strip()
        if remote!=self.remote:raise ValueError('The app cache has an unexpected remote. Expected '+self.repository+'.')
        if self.git('rev-parse','--is-bare-repository').strip()!=b'true':raise ValueError('The app cache must be a bare repository.')
        self.status={'busy':False,'message':'Repository cache ready. Select a PR to download its comparison.'}
    def migrate(self):
        record_path=self.reviews/'migration.json';record=self.read(record_path,{'sources':[]})
        for checkout in self.legacy:
            checkout=Path(checkout).expanduser().resolve();name=str(checkout)
            if name in record['sources'] or not checkout.is_dir():continue
            try:
                # Read only the old metadata; do not launch Git inside a user's checkout.
                gitdir=checkout/'.git'
                if gitdir.is_file():
                    pointer=gitdir.read_text().strip()
                    if not pointer.startswith('gitdir: '):continue
                    gitdir=(checkout/pointer[8:]).resolve()
                common=gitdir
                if (gitdir/'commondir').is_file():common=(gitdir/(gitdir/'commondir').read_text().strip()).resolve()
                config=configparser.RawConfigParser(strict=False);config.read(common/'config')
                remote=config.get('remote "origin"','url',fallback='').strip()
                if not re.fullmatch(r'(?:git@github.com:|https://github.com/|ssh://git@github.com/)onvif/specs(?:\.git)?',remote,re.I):continue
                location=gitdir/'xml-review-notes.json'
                for source in location.parent.iterdir():
                    if not STATE_PATTERNS.fullmatch(source.name) or not source.is_file():continue
                    target=self.reviews/source.name
                    if target.exists():continue
                    if source.stat().st_size>server.BACKUP_LIMIT:raise ValueError('An existing review file exceeds the import limit: '+source.name)
                    payload=source.read_bytes()
                    if not isinstance(json.loads(payload),dict):raise ValueError('Invalid review data: '+source.name)
                    # Exclusive creation: rerunning never overwrites work saved in the app.
                    try:
                        with target.open('xb') as stream:stream.write(payload)
                        self.migration['copied']+=1
                    except FileExistsError:pass
                record['sources'].append(name);self.write(record_path,record)
            except (OSError,ValueError,configparser.Error,subprocess.SubprocessError) as error:
                self.migration['warnings'].append('Some notes could not be copied from '+name+'. Originals are unchanged. Restart to retry, or import a review backup from the old viewer.')
    def activate(self):
        server.REPO=self.repo
        server.STATE_DIR=self.reviews
        server.API_CACHE_DIR=self.metadata
        server.list_prs=self.catalog
        server.resolve_pr=self.resolve_pr
    def manifest_path(self,number):
        number=server.pr_number(number)
        if not number:raise ValueError('Select a PR')
        return self.metadata/('pr-'+number+'.json')
    def available(self,value):
        value=value.get('comparison',value)
        try:
            for key in ('left','right'):self.git('cat-file','-e',value[key]+'^{commit}')
            return True
        except (KeyError,subprocess.SubprocessError):return False
    def list_prs(self,force=False):
        try:return self.original_list(force=force)
        except Exception as error:
            catalog=self.read(self.metadata/'catalog.json',{})
            prs=catalog.get('prs',[])
            if not prs:
                prs=[value['catalog'] for file in self.metadata.glob('pr-*.json') if (value:=self.read(file)).get('catalog') and self.available(value)]
            if not prs:raise ValueError('Cannot reach GitHub and no PRs are cached yet. Connect to the internet and Refresh.') from None
            return {'repo':self.repository,'prs':prs,'github':{'stale':True,'cached':True,'fetchedAt':catalog.get('time',time.time()),'warning':'Offline or GitHub unavailable. Showing cached PRs. '+str(error)}}
    def catalog(self,force=False):
        result=self.list_prs(force)
        if not result.get('github',{}).get('stale'):self.write(self.metadata/'catalog.json',dict(result,time=time.time()))
        return result
    def fetch(self,number,base,head):
        if not all(re.fullmatch('[a-f0-9]{40,64}',sha) for sha in (base,head)):raise ValueError('GitHub returned an invalid commit')
        self.status={'busy':True,'message':'Downloading PR #'+str(number)+' history…'}
        # Fetch complete objects for these histories, rather than a shallow/partial cache:
        # comparisons and their images remain readable offline after the download.
        command=['git','-C',str(self.repo),'fetch','--no-tags','--progress','origin',base,head]
        with subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,env=dict(os.environ,GIT_TERMINAL_PROMPT='0')) as task:
            def timeout():
                if task.poll() is None:task.kill()
            timer=threading.Timer(180,timeout);timer.start()
            try:
                tail=[];buffer=b''
                while True:
                    data=task.stderr.read(1)
                    if not data:break
                    if data in (b'\r',b'\n'):
                        line=buffer.decode(errors='replace').strip();buffer=b''
                        if line:
                            tail.append(line);tail=tail[-4:]
                            # Only Git progress is surfaced, never arbitrary auth output.
                            if re.search(r'(Receiving objects|Resolving deltas|Counting objects|Compressing objects):',line):self.status={'busy':True,'message':'PR #'+str(number)+' · '+line.removeprefix('remote: ')}
                    else:buffer+=data
                if task.wait():raise ValueError('Could not download this PR. Check your connection and try Refresh.')
            finally:timer.cancel()
        for side,sha in [('base',base),('head',head)]:self.git('update-ref','refs/review/pr/'+str(number)+'/'+side+'/'+sha,sha)
    def cached(self,number,warning):
        value=self.read(self.manifest_path(number))
        if not self.available(value):raise ValueError('This PR has not been downloaded yet. Connect to the internet and Refresh.')
        result=dict(value['comparison']);result['github']={'stale':True,'cached':True,'fetchedAt':value['time'],'warning':warning+' Showing the last downloaded revision.'}
        result['cache']={'downloadedAt':value['time'],'offline':True};return result
    def resolve_pr(self,number,force=False):
        number=server.pr_number(number)
        if not number:raise ValueError('Select a PR')
        with self.lock:
            try:
                pr=server.github_api('repos/'+self.repository+'/pulls/'+number,force=force)
                meta=dict(getattr(server.API_INFO,'value',{}))
                if not pr['head'].get('repo') or pr['head']['repo']['full_name'].lower()!=self.repository:raise ValueError('Only PRs from '+self.repository+' are supported.')
                base=pr['base']['sha'];head=pr['head']['sha']
                try:
                    for sha in (base,head):self.git('cat-file','-e',sha+'^{commit}')
                    self.git('merge-base',base,head)
                except subprocess.SubprocessError:self.fetch(number,base,head)
                ancestor=self.git('merge-base',base,head).decode().strip()
                files=[path for path in self.git('diff','--name-only','-z',ancestor,head).decode().split('\0') if path]
                result={'number':int(number),'title':pr['title'],'left':ancestor,'right':head,'base':pr['base']['ref'],'head':pr['head']['ref'],'files':files,'github':meta}
                for side,sha in [('base',base),('head',head)]:self.git('update-ref','refs/review/pr/'+number+'/'+side+'/'+sha,sha)
                previous=self.read(self.manifest_path(number));stamp=previous.get('time',time.time()) if previous.get('baseSha')==base and previous.get('comparison',{}).get('right')==head else time.time()
                self.write(self.manifest_path(number),{'time':stamp,'baseSha':base,'comparison':result,'catalog':{'number':int(number),'title':pr['title'],'base':pr['base']['ref'],'head':pr['head']['ref'],'labels':[label['name'] for label in pr.get('labels',[])]}})
                result['cache']={'downloadedAt':stamp,'offline':bool(meta.get('stale'))};return result
            except Exception as error:return self.cached(number,str(error))
            finally:self.status={'busy':False,'message':''}
    def check_update(self,number,right):
        number=server.pr_number(number)
        pr=server.github_api('repos/'+self.repository+'/pulls/'+number,force=True)
        meta=dict(getattr(server.API_INFO,'value',{}))
        if meta.get('stale'):return {'available':False,'github':meta,'message':'Could not check for updates. Your current comparison is unchanged.'}
        stored=self.read(self.manifest_path(number));base=pr['base']['sha']
        return {'available':pr['head']['sha']!=right or stored.get('baseSha')!=base,'closed':pr.get('state')!='open','github':meta,'head':pr['head']['sha'],'message':'PR updated on GitHub. Load the new version when you are ready.'}
