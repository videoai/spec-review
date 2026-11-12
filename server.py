#!/usr/bin/env python3
"""Local, read-only Git DocBook comparison server. Python standard library only."""
import time, math, functools, posixpath
import hashlib, tempfile, datetime
import os, shutil, urllib.request, urllib.error
import argparse, difflib, html, json, re, subprocess, threading, webbrowser, xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse, parse_qs, urlencode, unquote

def default_repo():
    folder = Path(__file__).resolve().parent
    try:
        return Path(subprocess.check_output(['git', '-C', str(folder), 'rev-parse', '--show-toplevel'], stderr=subprocess.PIPE).decode().strip())
    except (OSError, subprocess.CalledProcessError):
        return folder

REPO = default_repo()
def git(*args):
    return subprocess.check_output(['git','-C',str(REPO),*args], stderr=subprocess.PIPE, timeout=30)
def source(ref, path):
    p=PurePosixPath(path)
    if p.is_absolute() or '..' in p.parts: raise ValueError('Use a repository-relative document path')
    if ref=='WORKTREE':
        file=(REPO/path).resolve()
        if not file.is_relative_to(REPO.resolve()): raise ValueError('Path outside repository')
        return file.read_bytes()
    sha=git('rev-parse','--verify',ref+'^{commit}').decode().strip()
    return git('show',sha+':'+path)
def name(e): return e.tag.split('}')[-1]
def esc(s): return html.escape(s or '')
def load(data,asset_resolver=None,rich=True):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper(): raise ValueError('DTD/entity declarations are not supported')
    root=ET.fromstring(data)
    def normalize(e, preserve=False):
        preserve = preserve or name(e) in ('programlisting', 'screen')
        if not preserve and e.text: e.text = re.sub(r"\s+", " ", e.text)
        for c in e:
            normalize(c, preserve)
            if not preserve and c.tail: c.tail = re.sub(r"\s+", " ", c.tail)
    normalize(root)
    labels={}
    for e in root.iter():
        id=e.get('{http://www.w3.org/XML/1998/namespace}id')
        if id: labels[id]=next((''.join(c.itertext()) for c in e if name(c)=='title'),id)
    def inner(e):
        return esc(e.text)+''.join(render(c)+esc(c.tail) for c in e)
    def number(value,default=1):
        try: return max(1,int(value))
        except (TypeError,ValueError): return default
    def cals(group,caption=''):
        specs=[c for c in group if name(c)=='colspec']; columns={};current=1
        for spec in specs:
            current=number(spec.get('colnum'),current);columns[spec.get('colname',f'col{current}')]=current-1;current+=1
        count=number(group.get('cols'),max(current-1,1)); spans={c.get('spanname'):(c.get('namest'),c.get('nameend')) for c in group if name(c)=='spanspec'}
        output=['<table class="docbook-table">'+caption]
        if specs:
            widths={};position=1
            for spec in specs:
                position=number(spec.get('colnum'),position);widths[position-1]=spec.get('colwidth','1*');position+=1
            weights=[]
            for column in range(count):
                match=re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)?\*',widths.get(column,'1*'))
                weights.append(float(match.group(1) or 1) if match else None)
            output.append('<colgroup>')
            for column in range(count):
                raw=widths.get(column,'');style=''
                if all(value is not None for value in weights) and sum(weights)>0:style=f'width:{100*weights[column]/sum(weights):.4f}%'
                elif re.fullmatch(r'[0-9]+(?:\.[0-9]+)?(?:mm|cm|in|pt|px|%)',raw):style='width:'+raw
                output.append('<col'+(' style="'+style+'"' if style else '')+'>')
            output.append('</colgroup>')
        sections=[c for c in group if name(c) in ('thead','tbody','tfoot')]
        if not sections: sections=[group]
        for section in sections:
            tag=name(section) if section is not group else 'tbody';output.append('<'+tag+'>');occupied={}
            for index,row in enumerate(c for c in section if name(c)=='row'):
                output.append('<tr>');cursor=0
                for cell in row:
                    if name(cell) not in ('entry','entrytbl'): continue
                    start_name,end_name=spans.get(cell.get('spanname'),(cell.get('namest'),cell.get('nameend')))
                    while occupied.get(cursor,0)>index: cursor+=1
                    start=columns.get(start_name,columns.get(cell.get('colname'),cursor));start=max(cursor,start)
                    while cursor<start:
                        if occupied.get(cursor,0)<=index: output.append('<td></td>')
                        cursor+=1
                    end=max(start,columns.get(end_name,start));colspan=end-start+1;rowspan=max(0,int(cell.get('morerows','0')))+1 if cell.get('morerows','0').isdigit() else 1
                    # morerows=0 denotes no extra rows, unlike other positive counts.
                    if cell.get('morerows')=='0':rowspan=1
                    tagcell='th' if tag=='thead' else 'td';attrs=(f' colspan="{colspan}"' if colspan>1 else '')+(f' rowspan="{rowspan}"' if rowspan>1 else '')
                    output.append('<'+tagcell+attrs+'>'+(cals(cell) if name(cell)=='entrytbl' else inner(cell))+'</'+tagcell+'>')
                    for column in range(start,end+1):occupied[column]=index+rowspan
                    cursor=end+1
                while cursor<count:
                    if occupied.get(cursor,0)<=index:output.append('<td></td>')
                    cursor+=1
                output.append('</tr>')
            output.append('</'+tag+'>')
        return ''.join(output)+'</table>'
    def image(e,inline=False):
        fileref=e.get('fileref','');asset=asset_resolver(fileref) if asset_resolver else None
        if not asset:return '<span class="image-note">[Image: '+esc(fileref)+']</span>'
        return '<a class="docbook-image-link" href="'+esc(asset['url'])+'" target="_blank" rel="noreferrer"><img class="docbook-image'+(' inline-image' if inline else '')+'" data-asset-id="'+esc(asset['blob'])+'" src="'+esc(asset['url'])+'" alt="'+esc(fileref)+'" loading="lazy"></a>'
    def media(e):
        candidates=[c for c in e.iter() if name(c)=='imagedata'];chosen=None
        if asset_resolver:
            chosen=next((c for c in candidates if asset_resolver(c.get('fileref',''))),None)
        if chosen is None:chosen=candidates[0] if candidates else None
        if chosen is None:return inner(e)
        inline=name(e)=='inlinemediaobject'
        return ('<span class="docbook-inline-media">' if inline else '<div class="docbook-media">')+image(chosen,inline)+('</span>' if inline else '</div>')
    def render(e):
        n=name(e)
        if rich:
            if n in ('variablelist',):
                title=next((c for c in e if name(c)=='title'),None)
                return ('<div class="variable-title">'+inner(title)+'</div>' if title is not None else '')+'<dl class="docbook-variablelist">'+''.join(render(c) for c in e if name(c)!='title')+'</dl>'
            if n=='varlistentry':
                return ''.join('<dt>'+inner(c)+'</dt>' for c in e if name(c)=='term')+'<dd>'+''.join(inner(c) for c in e if name(c)=='listitem')+'</dd>'
            if n in ('table','informaltable'):
                title=next((c for c in e if name(c)=='title'),None);caption='<caption>'+inner(title)+'</caption>' if title is not None else ''
                groups=[c for c in e if name(c)=='tgroup']
                return ''.join(cals(group,caption if i==0 else '') for i,group in enumerate(groups)) if groups else cals(e,caption)
            if n in ('colspec','spanspec'):return ''
            if n in ('mediaobject','inlinemediaobject'):return media(e)
            if n=='imagedata':return image(e)
            if n in ('figure','informalfigure'):
                title=next((c for c in e if name(c)=='title'),None)
                return '<figure class="docbook-figure">'+''.join(render(c) for c in e if name(c)!='title')+('<figcaption>'+inner(title)+'</figcaption>' if title is not None else '')+'</figure>'
        if n=='xref': return '<span class="xref">'+esc(labels.get(e.get('linkend'),e.get('linkend','Reference')))+'</span>'
        if n=='imagedata': return '<span class="image-note">[Image: '+esc(e.get('fileref'))+']</span>'
        content=esc(e.text)+''.join(render(c)+esc(c.tail) for c in e)
        tags={'para':'p','simpara':'p','code':'code','literal':'code','programlisting':'pre','screen':'pre','emphasis':'em','itemizedlist':'ul','orderedlist':'ol','listitem':'li','table':'table','informaltable':'table','thead':'thead','tbody':'tbody','row':'tr','entry':'td','title':'strong','subscript':'sub','superscript':'sup','blockquote':'blockquote'}
        if n=='link':
            url=e.get('{http://www.w3.org/1999/xlink}href','')
            if url.startswith(('https://','http://')): return '<a href="'+esc(url)+'" target="_blank" rel="noreferrer">'+content+'</a>'
        tag=tags.get(n)
        return '<'+tag+'>'+content+'</'+tag+'>' if tag else content
    blocks=[]
    def walk(e,level=0,section='front',numbers=()):
        n=name(e)
        if n in ('book','info','chapter','section','appendix','legalnotice'):
            if n in ('chapter','section','appendix'):
                level+=1; section=e.get('{http://www.w3.org/XML/1998/namespace}id',section)
            count=0
            for c in e:
                if name(c) in ('chapter','section','appendix'): count+=1; nums=numbers+(count,)
                else: nums=numbers
                if name(c)=='title':
                    title=''.join(c.itertext()).strip(); prefix='.'.join(map(str,numbers))+' ' if numbers else ''
                    blocks.append({'key':section+':title','html':f'<h{min(level+1,5)}>'+esc(prefix+title)+f'</h{min(level+1,5)}>','section':title,'kind':'title'})
                elif name(c)=='titleabbrev' or (name(c)=='mediaobject' and (not rich or n=='info')): continue
                else: walk(c,level,section,nums)
        else:
            value=render(e)
            if value.strip(): blocks.append({'key':section+':'+n,'html':value,'section':section,'kind':n})
    walk(root)
    return blocks

def words(markup):
    parts=re.split(r'(<[^>]+>)',markup)
    tokens=[]; slots=[]
    for i,p in enumerate(parts):
        if p.startswith('<'): continue
        pieces=re.findall(r'\s+|[^\s]+',p); parts[i]=pieces
        for j,t in enumerate(pieces):
            if not t.isspace(): tokens.append(t); slots.append((i,j))
    return parts,tokens,slots

def highlight(a,b):
    pa,ta,sa=words(a); pb,tb,sb=words(b)
    for op,i,j,k,l in difflib.SequenceMatcher(None,ta,tb,autojunk=False).get_opcodes():
        if op=='equal': continue
        for parts,slots,start,end,tag in ((pa,sa,i,j,'del'),(pb,sb,k,l,'ins')):
            for x,y in slots[start:end]: parts[x][y]=f'<{tag}>'+parts[x][y]+f'</{tag}>'
    return tuple(''.join(''.join(p) if isinstance(p,list) else p for p in parts) for parts in (pa,pb))
def compare(a,b):
    rows=[]
    def add(x,y):
        status='same' if x and y and x['html']==y['html'] and x.get('displayHtml',x['html'])==y.get('displayHtml',y['html']) else 'changed' if x and y else 'added' if y else 'removed'
        old_left=x['html'] if x else ''; old_right=y['html'] if y else ''
        left=x.get('displayHtml',x['html']) if x else ''; right=y.get('displayHtml',y['html']) if y else ''
        if status=='changed' and old_left==old_right and left!=right:old_left,old_right=left,right
        if status=='changed':
            left,right=highlight(left,right);old_left,old_right=highlight(old_left,old_right)
        row={'left':left,'right':right,'status':status,'heading':(y or x)['section']}
        if any(block and 'displayHtml' in block for block in (x,y)):
            row['_identity']={'left':old_left,'right':old_right,'status':status,'heading':row['heading']}
            row['reviewLeft']=old_left;row['reviewRight']=old_right
        rows.append(row)
    # Section IDs anchor alignment; a second pass aligns blocks within each run.
    for op,i,j,k,l in difflib.SequenceMatcher(None,[(x['key'],x['html']) for x in a],[(x['key'],x['html']) for x in b],autojunk=False).get_opcodes():
        if op=='equal':
            for x,y in zip(a[i:j],b[k:l]): add(x,y)
        else:
            aa=a[i:j]; bb=b[k:l]
            for op2,u,v,w,z in difflib.SequenceMatcher(None,[x['html'] for x in aa],[x['html'] for x in bb],autojunk=False).get_opcodes():
                if op2=='equal':
                    for x,y in zip(aa[u:v],bb[w:z]): add(x,y)
                else:
                    for t in range(max(v-u,z-w)): add(aa[u+t] if u+t<v else None,bb[w+t] if w+t<z else None)
    return rows
def github_repo():
    remote=git('remote','get-url','origin').decode().strip()
    match=re.fullmatch(r'(?:git@github.com:|https://github.com/|ssh://git@github.com/)([\w.-]+/[\w.-]+?)(?:\.git)?',remote)
    if not match: raise ValueError('PR browsing requires a GitHub origin remote.')
    return match.group(1)

API_LOCK=threading.Lock()
API_INFO=threading.local()
CACHE_SECONDS=600

class GitHubError(ValueError):
    def __init__(self,message,retry_at=None):
        super().__init__(message); self.retry_at=retry_at

def api_cache_path():
    location=Path(git('rev-parse','--git-path','xml-review-github-cache.json').decode().strip())
    return location if location.is_absolute() else REPO/location

def github_token():
    token=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if token: return token
    if shutil.which('gh'):
        try: return subprocess.check_output(['gh','auth','token','--hostname','github.com'],stderr=subprocess.PIPE,timeout=10).decode().strip()
        except subprocess.SubprocessError: pass
    return None

def github_error(error):
    headers=error.headers or {}; reset=None
    try:
        if headers.get('Retry-After'): reset=time.time()+float(headers['Retry-After'])
        elif headers.get('X-RateLimit-Remaining')=='0': reset=float(headers['X-RateLimit-Reset'])
    except (ValueError,KeyError): pass
    try: message=json.loads(error.read()).get('message','')
    except Exception: message=''
    limited=reset is not None or 'rate limit' in message.lower()
    if limited:
        reset=reset or time.time()+60
        wait=max(1,math.ceil((reset-time.time())/60))
        utc=datetime.datetime.fromtimestamp(reset,datetime.timezone.utc).isoformat()
        return GitHubError(f'GitHub rate limit reached. Retry in about {wait} minute(s), after {utc}. Signing in with gh auth login normally raises the limit from 60 to 5,000 requests/hour.',reset)
    return GitHubError(f'GitHub returned {error.code}: {message or "Access denied"}. Check repository permissions or sign in with gh auth login.')

def write_api_cache(file,cache):
    fd,tmp=tempfile.mkstemp(dir=file.parent,prefix='.xml-review-github-cache-')
    try:
        with os.fdopen(fd,'w') as stream: json.dump(cache,stream)
        os.replace(tmp,file)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def github_api(endpoint,force=False):
    token=github_token()
    identity=hashlib.sha256((token or 'anonymous').encode()).hexdigest()
    key=identity+':'+endpoint
    with API_LOCK:
        file=api_cache_path()
        try: cache=json.loads(file.read_text()) if file.exists() else {}
        except (ValueError,OSError): cache={}
        now=time.time(); entry=cache.get(key); blocked=cache.get('blocked:'+identity,{})
        def cached(stale=False,warning=None):
            API_INFO.value={'cached':True,'stale':stale,'fetchedAt':entry['time'],'warning':warning,'retryAt':blocked.get('until')}
            return entry['data']
        if blocked.get('until',0)>now:
            if entry: return cached(True,blocked['message'])
            raise GitHubError(blocked['message'],blocked['until'])
        if entry and not force and now-entry['time']<CACHE_SECONDS: return cached()
        headers={'Accept':'application/vnd.github+json','User-Agent':'Spec-Review'}
        if token: headers['Authorization']='Bearer '+token
        if entry and entry.get('etag'): headers['If-None-Match']=entry['etag']
        try:
            try:
                with urllib.request.urlopen(urllib.request.Request('https://api.github.com/'+endpoint,headers=headers),timeout=30) as response:
                    data=json.load(response); etag=response.headers.get('ETag')
            except urllib.error.HTTPError as error:
                if error.code==304 and entry:
                    data=entry['data']; etag=entry.get('etag')
                else: raise github_error(error) from None
            cache[key]={'data':data,'time':now,'etag':etag}; cache.pop('blocked:'+identity,None)
            listing=re.match(r'^(repos/[^/]+/[^/]+/pulls)\?',endpoint)
            if listing and isinstance(data,list):
                for item in data:
                    if item.get('number') and item.get('base',{}).get('sha') and item.get('head',{}).get('sha'):
                        cache[identity+':'+listing.group(1)+'/'+str(item['number'])]={'data':item,'time':now,'etag':None}
            write_api_cache(file,cache)
            API_INFO.value={'cached':False,'stale':False,'fetchedAt':now}
            return data
        except (GitHubError,urllib.error.URLError,TimeoutError) as error:
            if isinstance(error,GitHubError) and error.retry_at:
                blocked={'until':error.retry_at,'message':str(error)};cache['blocked:'+identity]=blocked;write_api_cache(file,cache)
            if entry: return cached(True,str(error))
            raise

def list_prs(force=False):
    repo=github_repo(); result=[]; page=1
    while True:
        batch=github_api(f'repos/{repo}/pulls?state=open&per_page=100&page={page}',force=force)
        for pr in batch:
            if pr['head'].get('repo') and pr['head']['repo']['full_name'].lower()==repo.lower():
                result.append({'number':pr['number'],'title':pr['title'],'head':pr['head']['ref'],'base':pr['base']['ref'],'labels':[label['name'] for label in pr.get('labels',[])]})
        if len(batch)<100: break
        page+=1
    return {'repo':repo,'prs':result,'github':getattr(API_INFO,'value',{})}

def resolve_pr(number,force=False):
    if not str(number).isdigit(): raise ValueError('Invalid PR number')
    repo=github_repo(); pr=github_api(f'repos/{repo}/pulls/{int(number)}',force=force)
    if not pr['head'].get('repo') or pr['head']['repo']['full_name'].lower()!=repo.lower():
        raise ValueError('Only PRs from this repository are supported.')
    base=pr['base']['sha']; head=pr['head']['sha']
    try:
        for sha in (base,head): git('cat-file','-e',sha+'^{commit}')
        ancestor=git('merge-base',base,head).decode().strip()
    except subprocess.CalledProcessError:
        raise ValueError('PR commits or history are missing locally. Run git fetch origin (and git fetch --unshallow for a shallow clone), then try again.') from None
    files=git('diff','--name-only','-z',ancestor,head).decode().split('\0')
    return {'number':pr['number'],'title':pr['title'],'left':ancestor,'right':head,'base':pr['base']['ref'],'head':pr['head']['ref'],'files':[f for f in files if f],'github':getattr(API_INFO,'value',{})}

def version_label(ref):
    if ref=='WORKTREE':
        branch=git('symbolic-ref','--quiet','--short','HEAD').decode().strip() if git('rev-parse','--abbrev-ref','HEAD').decode().strip()!='HEAD' else 'detached HEAD'
        sha=git('rev-parse','--short=8','HEAD').decode().strip()
        return f'{branch} · {sha} + working copy'
    sha=git('rev-parse','--verify',ref+'^{commit}').decode().strip()
    short=git('rev-parse','--short=8',sha).decode().strip()
    if ref=='HEAD':
        branch=git('rev-parse','--abbrev-ref','HEAD').decode().strip()
        return f'{branch} (HEAD) · {short}'
    if not re.fullmatch('[a-fA-F0-9]{7,40}',ref): return f'{ref} · {short}'
    branches=git('for-each-ref','--format=%(refname:short)','--points-at',sha,'refs/heads','refs/remotes').decode().splitlines()
    branches=[b for b in branches if b!='origin']
    if branches: return ' / '.join(branches[:3])+f' · {short}'
    branches=git('for-each-ref','--format=%(refname:short)','--contains',sha,'refs/heads','refs/remotes').decode().splitlines()
    branches=[b for b in branches if b!='origin']
    return (('in '+ ' / '.join(branches[:3])+' · ') if branches else 'Commit · ')+short

FETCH_LOCK=threading.Lock()
def fetch_latest():
    github_repo()  # Only fetch the configured GitHub origin.
    if not FETCH_LOCK.acquire(blocking=False): raise ValueError('A fetch is already running. Try again shortly.')
    try:
        env=dict(os.environ,GIT_TERMINAL_PROMPT='0')
        result=subprocess.run(['git','-C',str(REPO),'fetch','--no-tags','origin'],capture_output=True,timeout=120,env=env)
        if result.returncode: raise ValueError('Fetch failed. Check repository access in your terminal with git fetch origin.')
        return {'fetched':True}
    except subprocess.TimeoutExpired:
        raise ValueError('Fetch timed out. Try git fetch origin in your terminal.') from None
    finally: FETCH_LOCK.release()

NOTES_LOCK=threading.Lock()
def notes_path():
    location=Path(git('rev-parse','--git-path','xml-review-notes.json').decode().strip())
    return location if location.is_absolute() else REPO/location

def pr_number(value):
    if value is None or value=='': return None
    if not str(value).isdigit() or int(value)<1: raise ValueError('Invalid PR number')
    return str(int(value))

def scoped_notes_path(pr=None):
    number=pr_number(pr)
    file=notes_path()
    if not number: raise ValueError('Select a PR before saving notes')
    return file.with_name('xml-review-notes-pr-'+number+'.json')

def read_notes(pr=None):
    if not pr_number(pr): return {}
    file=scoped_notes_path(pr)
    return json.loads(file.read_text()) if file.exists() else {}

def save_note(data):
    review=data.get('review',''); block=data.get('block',''); text=data.get('text','')
    if not all(re.fullmatch(r'[a-f0-9]{64}',v) for v in (review,block)): raise ValueError('Invalid note location')
    if not isinstance(text,str) or len(text)>20000: raise ValueError('Notes must be at most 20,000 characters')
    with NOTES_LOCK:
        number=pr_number(data.get('pr'))
        notes=read_notes(number); entry=notes.setdefault(review,{})
        if text.strip():
            entry[block]={'text':text,'context':str(data.get('context',''))[:2000],'path':str(data.get('path',''))[:500], 'pr':number,'versions':data.get('versions',{}),'updated':datetime.datetime.now(datetime.timezone.utc).isoformat()}
        else: entry.pop(block,None)
        file=scoped_notes_path(number)
        fd,tmp=tempfile.mkstemp(dir=file.parent,prefix='.xml-review-notes-')
        try:
            with os.fdopen(fd,'w') as stream: json.dump(notes,stream,indent=2)
            os.replace(tmp,file)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    return {'saved':True}

def draft_path(pr):
    number=pr_number(pr)
    if not number:raise ValueError('Select a PR first')
    return notes_path().with_name('xml-review-draft-pr-'+number+'.json')

def read_draft(pr):
    file=draft_path(pr)
    return json.loads(file.read_text()) if file.exists() else {'summary':{},'files':{}}

def save_draft(data):
    number=pr_number(data.get('pr'));scope=data.get('scope');text=data.get('text','')
    if scope not in ('summary','file') or not isinstance(text,str) or len(text)>20000:raise ValueError('Invalid draft note; maximum 20,000 characters')
    path=data.get('path','')
    if scope=='file' and (not path or PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts):raise ValueError('Invalid file note path')
    with NOTES_LOCK:
        draft=read_draft(number);note={'text':text,'versions':data.get('versions',{}),'updated':datetime.datetime.now(datetime.timezone.utc).isoformat()}
        if scope=='summary':draft['summary']=note if text.strip() else {}
        elif text.strip():draft['files'][path]=note
        else:draft['files'].pop(path,None)
        write_api_cache(draft_path(number),draft)
    return {'saved':True,'draft':draft}

REVIEWED_LOCK=threading.Lock()
def reviewed_path(pr=None):
    number=pr_number(pr)
    return notes_path().with_name('xml-review-reviewed-pr-'+number+'.json' if number else 'xml-review-reviewed.json')

def read_reviewed(pr=None):
    file=reviewed_path(pr)
    if pr_number(pr) and not file.exists(): file=reviewed_path()
    return json.loads(file.read_text()) if file.exists() else {}

def save_reviewed(data):
    key=data.get('key',''); value=data.get('reviewed')
    if not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{64}',key) or not isinstance(value,bool):
        raise ValueError('Invalid reviewed state')
    with REVIEWED_LOCK:
        state=read_reviewed(data.get('pr'))
        if value: state[key]=True
        else: state.pop(key,None)
        file=reviewed_path(data.get('pr')); fd,tmp=tempfile.mkstemp(dir=file.parent,prefix='.xml-review-reviewed-')
        try:
            with os.fdopen(fd,'w') as stream: json.dump(state,stream,indent=2)
            os.replace(tmp,file)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    return {'saved':True}

def reset_backup_path(pr):
    number=pr_number(pr)
    if not number: raise ValueError('Select a PR before resetting')
    return notes_path().with_name('xml-review-reset-pr-'+number+'.json')

def reset_review(data,undo=False):
    number=pr_number(data.get('pr')); backup_file=reset_backup_path(number)
    with NOTES_LOCK, REVIEWED_LOCK:
        if undo:
            if not backup_file.exists(): raise ValueError('No reset to undo for this PR')
            backup=json.loads(backup_file.read_text())
            write_api_cache(scoped_notes_path(number),backup['notes'])
            write_api_cache(draft_path(number),backup.get('draft',{'summary':{},'files':{}}))
            write_api_cache(reviewed_path(number),backup['reviewed'])
            backup_file.unlink()
        else:
            backup={'notes':read_notes(number),'reviewed':read_reviewed(number),'draft':read_draft(number)}
            write_api_cache(backup_file,backup)
            try:
                write_api_cache(scoped_notes_path(number),{})
                write_api_cache(draft_path(number),{'summary':{},'files':{}})
                write_api_cache(reviewed_path(number),{})
            except Exception:
                write_api_cache(scoped_notes_path(number),backup['notes'])
                write_api_cache(draft_path(number),backup['draft'])
                write_api_cache(reviewed_path(number),backup['reviewed'])
                raise
    return {'saved':True,'canUndo':not undo}

def review_keys(path,rows):
    occurrences={}
    for row in rows:
        if row['status']=='same': continue
        # Exact before/after content and section context, independent of commit or row index.
        content=json.dumps([path,row.get('reviewHeading',row['heading']),row['status'],row.get('reviewLeft',row['left']),row.get('reviewRight',row['right'])],sort_keys=True)
        occurrence=occurrences.get(content,0); occurrences[content]=occurrence+1
        row['reviewKey']=hashlib.sha256(json.dumps([content,occurrence]).encode()).hexdigest()

def file_bytes(ref,path):
    try: return source(ref,path)
    except (FileNotFoundError,subprocess.CalledProcessError):
        if ref!='WORKTREE':
            sha=git('rev-parse','--verify',ref+'^{commit}').decode().strip()
            if not git('ls-tree',sha,'--',path).strip(): return None
        elif not (REPO/path).exists(): return None
        raise

def image_mime(data):
    if not data: return None
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if data.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if data.startswith((b'GIF87a',b'GIF89a')): return 'image/gif'
    if data[:4]==b'RIFF' and data[8:12]==b'WEBP': return 'image/webp'
    if b'<svg' in data[:2000] and b'<!DOCTYPE' not in data.upper() and b'<!ENTITY' not in data.upper():
        try:
            if name(ET.fromstring(data))=='svg': return 'image/svg+xml'
        except ET.ParseError: pass
    return None

def text_content(data):
    if data is None: return ''
    if b'\0' in data: return None
    try: return data.decode('utf-8-sig')
    except UnicodeDecodeError: return None

def source_rows(a,b):
    left=a.splitlines(keepends=True);right=b.splitlines(keepends=True);rows=[]
    def label(start,lines):
        if not lines: return 'No lines'
        return 'Line '+str(start+1) if len(lines)==1 else f'Lines {start+1}–{start+len(lines)}'
    def render(lines,start):
        if not lines: return ''
        return '<div class="source-range">'+label(start,lines)+'</div><pre class="source-code">'+esc(''.join(lines))+'</pre>'
    for op,i,j,k,l in difflib.SequenceMatcher(None,left,right,autojunk=False).get_opcodes():
        # Bound large deletions/additions into reviewable chunks, including whole deleted files.
        for offset in range(0,max(j-i,l-k),35):
            aa=left[i+offset:min(j,i+offset+35)] if i+offset<j else []
            bb=right[k+offset:min(l,k+offset+35)] if k+offset<l else []
            status='same' if op=='equal' else 'changed' if aa and bb else 'added' if bb else 'removed'
            lh,rh=render(aa,i+offset),render(bb,k+offset)
            if status=='changed': lh,rh=highlight(lh,rh)
            rows.append({'left':lh,'right':rh,'status':status,'heading':label(i+offset,aa)+' → '+label(k+offset,bb),'reviewHeading':'Source change','reviewLeft':''.join(aa),'reviewRight':''.join(bb)})
    return rows

def media_row(left,right,path,a,b,image=False):
    def fingerprint(data): return hashlib.sha256(data).hexdigest() if data is not None else ''
    def render(ref,data):
        if data is None: return ''
        digest=fingerprint(data)
        info=f'{len(data):,} bytes · SHA256 {digest}'
        if image:
            url='/api/asset?'+urlencode({'ref':ref,'path':path})
            return '<figure class="image-comparison"><a href="'+esc(url)+'" target="_blank" rel="noreferrer"><img src="'+esc(url)+'" alt="'+esc(path)+'" loading="lazy"></a><figcaption>'+esc(path)+'<br>'+info+'</figcaption></figure>'
        return '<div class="binary-info"><strong>Binary file</strong><p>'+esc(path)+'</p><p>'+info+'</p></div>'
    status='same' if a==b else 'added' if a is None else 'removed' if b is None else 'changed'
    return [{'left':render(left,a),'right':render(right,b),'status':status,'heading':'Image comparison' if image else 'Binary file comparison','reviewHeading':'Image comparison' if image else 'Binary file comparison','reviewLeft':fingerprint(a),'reviewRight':fingerprint(b)}]

@functools.lru_cache(maxsize=1024)
def resolve_image(repo,ref,document,fileref):
    parsed=urlparse(fileref)
    if parsed.scheme or parsed.netloc or fileref.startswith('/') or not parsed.path:return None
    path=posixpath.normpath(str(PurePosixPath(document).parent/unquote(parsed.path)))
    if path=='..' or path.startswith('../') or path.startswith('/'):return None
    try:
        sha=git('rev-parse','--verify',ref+'^{commit}').decode().strip()
        blob=git('rev-parse','--verify',sha+':'+path).decode().strip()
        data=git('cat-file','blob',blob)
        if not image_mime(data):return None
        return {'blob':blob,'url':'/api/asset?'+urlencode({'blob':blob})}
    except subprocess.SubprocessError:return None

def rich_blocks(data,ref,path):
    if data is None:return [],[]
    canonical=load(data,rich=False)
    rendered=load(data,asset_resolver=lambda fileref:resolve_image(str(REPO),ref,path,fileref))
    # Block keys plus occurrence connect richer presentation with the previous identities.
    buckets={}
    for block in canonical:buckets.setdefault(block['key'],[]).append(block)
    enriched=[]
    for display in rendered:
        queue=buckets.get(display['key'],[]);block=queue.pop(0) if queue else display
        value=dict(block,displayHtml=display['html'])
        assets=re.findall(r'data-asset-id="([a-f0-9]+)"',display['html'])
        if assets:value['html']+='<!-- assets:'+','.join(assets)+' -->'
        enriched.append(value)
    return canonical,enriched

def comparison(left,right,path,pr=None):
    raw_a,raw_b=file_bytes(left,path),file_bytes(right,path)
    if raw_a is None and raw_b is None: raise ValueError('File does not exist in either version.')
    present=raw_b if raw_b is not None else raw_a
    mode='source';a=text_content(raw_a);b=text_content(raw_b)
    is_book=False
    if path.lower().endswith('.xml') and b'<!DOCTYPE' not in present.upper() and b'<!ENTITY' not in present.upper():
        try: is_book=name(ET.fromstring(present)) in ('book','article')
        except ET.ParseError: pass
    if is_book:
        mode='docbook';aa,display_a=rich_blocks(raw_a,left,path);bb,display_b=rich_blocks(raw_b,right,path)
        rows=compare(display_a,display_b)
        # Retain identities of existing formatted XML reviews and notes.
        review=hashlib.sha256(json.dumps([path,aa,bb],sort_keys=True).encode()).hexdigest()
    else:
        if path.lower().endswith('.svg') and a is not None and b is not None:
            rows=source_rows(a,b)
        elif all(data is None or image_mime(data) for data in (raw_a,raw_b)):
            mode='image';rows=media_row(left,right,path,raw_a,raw_b,image=True)
        elif a is not None and b is not None:
            rows=source_rows(a,b)
        else:
            mode='binary';rows=media_row(left,right,path,raw_a,raw_b)
        review=hashlib.sha256(json.dumps([path,mode,hashlib.sha256(raw_a).hexdigest() if raw_a is not None else None,hashlib.sha256(raw_b).hexdigest() if raw_b is not None else None]).encode()).hexdigest()
    if not rows and (raw_a is None or raw_b is None): rows=[{'left':'<p>Empty file</p>' if raw_a is not None else '', 'right':'<p>Empty file</p>' if raw_b is not None else '', 'status':'added' if raw_a is None else 'removed','heading':'Empty file added' if raw_a is None else 'Empty file deleted'}]
    for i,row in enumerate(rows):
        canonical_row=row.pop('_identity',None)
        identity=[i,path,row.get('reviewLeft'),row.get('reviewRight')] if mode=='image' else [i,canonical_row if canonical_row is not None else row]
        row['id']=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    review_keys(path,rows)
    with REVIEWED_LOCK: reviewed=read_reviewed(pr)
    for row in rows: row['reviewed']=bool(reviewed.get(row.get('reviewKey','')))
    return {'rows':rows,'review':review,'mode':mode,'fileStatus':'added' if raw_a is None else 'deleted' if raw_b is None else 'modified','labels':{'left':version_label(left),'right':version_label(right)}}

def review_summary(left,right,pr=None):
    # Resolve revisions once so progress/export represents one consistent snapshot.
    left=git('rev-parse','--verify',left+'^{commit}').decode().strip()
    right=git('rev-parse','--verify',right+'^{commit}').decode().strip()
    files=[f for f in git('diff','--name-only','-z',left,right).decode().split('\0') if f]
    documents=[]
    with NOTES_LOCK: all_notes=read_notes(pr)
    for path in files:
        try:
            result=comparison(left,right,path,pr)
            notes=all_notes.get(result['review'],{})
            changes=[]
            for row in result['rows']:
                if row['status']=='same': continue
                changes.append({key:row[key] for key in ('id','reviewKey','heading','status','reviewed','left','right')})
                changes[-1]['note']=notes.get(row['id'])
            documents.append({'path':path,'review':result['review'],'changes':changes,'mode':result.get('mode','docbook'),'fileStatus':result.get('fileStatus','modified')})
        except Exception as e:
            documents.append({'path':path,'error':str(e),'changes':[]})
    return {'left':left,'right':right,'documents':documents}

SUBMIT_LOCK=threading.Lock()
def submission_path(pr):return draft_path(pr).with_name('xml-review-submissions-pr-'+pr_number(pr)+'.json')
def preview_path(pr):return draft_path(pr).with_name('xml-review-preview-pr-'+pr_number(pr)+'.json')

def readable(markup):return html.unescape(re.sub(r'<[^>]+>','',markup)).strip()
def quoted(value):return '\n'.join('> '+line for line in value.splitlines())

def prepare_review(data):
    number=pr_number(data.get('pr'));repo=github_repo();left=data.get('left','');right=data.get('right','')
    if not all(re.fullmatch('[a-f0-9]{40,64}',sha) for sha in (left,right)):raise ValueError('Select a committed PR comparison first')
    summary=review_summary(left,right,number)
    with NOTES_LOCK:draft=read_draft(number)
    body=draft.get('summary',{}).get('text','').strip();comments=[]
    for doc in summary['documents']:
        parts=[];file_note=draft.get('files',{}).get(doc['path'],{}).get('text','').strip()
        if file_note:parts.extend(['## File note',file_note,''])
        for change in doc['changes']:
            note=change.get('note')
            if not note or not note.get('text','').strip():continue
            parts.extend(['## '+change['heading'],'','Before:',quoted(readable(change['left'])),'','After:',quoted(readable(change['right'])),'','Note:',note['text'],''])
        if parts:comments.append({'path':doc['path'],'body':'\n'.join(parts).strip()})
    # A file note can still be posted for a file that the renderer could not interpret.
    body=(body+'\n\n' if body else '')+f'Reviewed with ONVIF Spec Review at `{right[:8]}`.'
    if not comments and not draft.get('summary',{}).get('text','').strip():raise ValueError('Add a PR summary, file note, or change note first')
    if any(len(comment['body'])>60000 for comment in comments) or len(body)>60000:raise ValueError('A review comment is too large for GitHub; shorten the notes before submitting')
    content={'repo':repo,'pr':int(number),'left':left,'right':right,'body':body,'files':comments}
    digest=hashlib.sha256(json.dumps(content,sort_keys=True).encode()).hexdigest()
    content['id']=digest;content['displayBody']=body;content['body']+='\n\n<!-- onvif-spec-review:'+digest+' -->'
    for comment in content['files']:
        comment['displayBody']=comment['body']
        comment['body']+='\n\n<!-- onvif-file-note:'+hashlib.sha256((digest+comment['path']).encode()).hexdigest()+' -->'
    content['url']='https://github.com/'+repo+'/pull/'+number
    content['canSubmit']=bool(github_token());content['incomplete']=[doc['path'] for doc in summary['documents'] if doc.get('error')]
    lines=['# Review for '+repo+' PR #'+number,'','Base commit: '+left,'Proposed commit: '+right,'',content['displayBody'],'']
    for comment in comments:lines.extend(['# '+comment['path'],'',comment['displayBody'],''])
    content['markdown']='\n'.join(lines)
    with NOTES_LOCK:write_api_cache(preview_path(number),content)
    return content

def github_write(endpoint,payload):
    token=github_token()
    if not token:raise ValueError('Sign in with gh auth login or set GH_TOKEN to submit a review')
    headers={'Accept':'application/vnd.github+json','User-Agent':'ONVIF-Spec-Review','Authorization':'Bearer '+token,'Content-Type':'application/json'}
    request=urllib.request.Request('https://api.github.com/'+endpoint,data=json.dumps(payload).encode(),headers=headers,method='POST')
    try:
        with urllib.request.urlopen(request,timeout=30) as response:result=json.load(response)
    except urllib.error.HTTPError as error:raise github_error(error) from None
    if result.get('errors'):raise ValueError('GitHub: '+'; '.join(str(error.get('message','Review request failed')) for error in result['errors']))
    return result

def submit_review(data):
    number=pr_number(data.get('pr'))
    if data.get('confirm') is not True:raise ValueError('Confirm the review preview before submitting')
    if not SUBMIT_LOCK.acquire(blocking=False):raise ValueError('A review submission is already in progress')
    try:
        preview=json.loads(preview_path(number).read_text())
        if data.get('id')!=preview['id']:raise ValueError('Preview changed; open it again before submitting')
        # Rebuild from saved drafts so edits in another tab invalidate old previews.
        current=prepare_review({'pr':number,'left':preview['left'],'right':preview['right']})
        if current['id']!=preview['id']:raise ValueError('Notes changed since preview; reopen the preview')
        if not github_token():raise ValueError('Sign in with gh auth login or set GH_TOKEN to submit')
        remote=github_api(f'repos/{preview["repo"]}/pulls/{number}',force=True)
        if getattr(API_INFO,'value',{}).get('stale'):raise ValueError('Cannot submit using stale GitHub metadata; refresh after GitHub becomes available')
        if remote.get('state')!='open' or remote['head']['sha']!=preview['right']:raise ValueError('The PR changed or closed. Refresh and review the latest version before submitting')
        try:ancestor=git('merge-base',remote['base']['sha'],remote['head']['sha']).decode().strip()
        except subprocess.SubprocessError:raise ValueError('Fetch latest before submitting; current PR history is not available locally') from None
        if ancestor!=preview['left']:raise ValueError('The PR base changed; refresh before submitting')
        file=submission_path(number)
        journal=json.loads(file.read_text()) if file.exists() else {};entry=journal.get(preview['id'])
        if entry:
            if entry.get('state')=='submitted':return {'submitted':True,'url':entry['url'],'alreadySubmitted':True}
            raise ValueError('This submission was already started. Check the PR and any pending GitHub review before trying again; automatic retries are blocked to avoid duplicate comments.')
        entry={'state':'starting','url':preview['url']};journal[preview['id']]=entry;write_api_cache(file,journal)
        try:
            review=github_write(f'repos/{preview["repo"]}/pulls/{number}/reviews',{'commit_id':preview['right'],'body':preview['body']})
            entry.update(state='pending',review_id=review['id'],review_node_id=review['node_id'],url=review.get('html_url') or preview['url']);write_api_cache(file,journal)
            mutation='mutation($input:AddPullRequestReviewThreadInput!){addPullRequestReviewThread(input:$input){thread{id}}}'
            for comment in preview['files']:
                entry['state']='adding-file-comment';entry['path']=comment['path'];write_api_cache(file,journal)
                github_write('graphql',{'query':mutation,'variables':{'input':{'pullRequestReviewId':review['node_id'],'path':comment['path'],'subjectType':'FILE','body':comment['body']}}})
            entry['state']='submitting';write_api_cache(file,journal)
            result=github_write(f'repos/{preview["repo"]}/pulls/{number}/reviews/{review["id"]}/events',{'event':'COMMENT','body':preview['body']})
            entry.update(state='submitted',url=result.get('html_url') or entry['url']);write_api_cache(file,journal)
            return {'submitted':True,'url':entry['url']}
        except Exception as error:
            entry.update(state='needs-attention',error=str(error));write_api_cache(file,journal)
            raise ValueError('Submission incomplete: '+str(error)+'. Check '+entry['url']+' for a pending or submitted review. The tool will not automatically repeat the submission.') from None
    finally:SUBMIT_LOCK.release()

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            if self.path not in ('/api/notes','/api/fetch','/api/reviewed','/api/reset','/api/undo-reset','/api/draft','/api/review-preview','/api/submit-review'): self.send_error(404); return
            origin=self.headers.get('Origin')
            if origin and origin!='http://'+self.headers.get('Host',''): raise ValueError('Origin mismatch')
            if self.headers.get('Content-Type')!='application/json': raise ValueError('JSON required')
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=100000: raise ValueError('Invalid note size')
            payload=json.loads(self.rfile.read(size))
            if self.path=='/api/draft':result=save_draft(payload)
            elif self.path=='/api/review-preview':result=prepare_review(payload)
            elif self.path=='/api/submit-review':result=submit_review(payload)
            elif self.path in ('/api/reset','/api/undo-reset'):result=reset_review(payload,undo=self.path=='/api/undo-reset')
            elif self.path=='/api/fetch':result=fetch_latest()
            elif self.path=='/api/reviewed':result=save_reviewed(payload)
            else:result=save_note(payload)
            code=200
        except Exception as e: result={'error':str(e)}; code=400
        self.send_response(code); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps(result).encode())
    def do_GET(self):
        u=urlparse(self.path); q=parse_qs(u.query)
        try:
            if u.path=='/api/refs':
                refs=git('for-each-ref','--format=%(refname:short)','refs/heads','refs/remotes').decode().splitlines()
                data={'refs':['WORKTREE','HEAD']+refs,'repo':str(REPO),'labels':{}}
                tips=git('for-each-ref','--format=%(refname:short) %(objectname:short=8)','refs/heads','refs/remotes').decode().splitlines()
                data['labels']={line.rsplit(' ',1)[0]:line.rsplit(' ',1)[0]+' · '+line.rsplit(' ',1)[1] for line in tips}
                data['labels'].update({ref:version_label(ref) for ref in ('WORKTREE','HEAD')})
            elif u.path=='/api/draft':
                with NOTES_LOCK:data=read_draft(q.get('pr',[None])[0])
            elif u.path=='/api/reset-status':
                data={'canUndo':reset_backup_path(q.get('pr',[None])[0]).exists()}
            elif u.path=='/api/note-history':
                with NOTES_LOCK: data={'reviews':read_notes(q.get('pr',[None])[0])}
            elif u.path=='/api/notes':
                with NOTES_LOCK: data={'notes':read_notes(q.get('pr',[None])[0]).get(q.get('review',[''])[0],{})}
            elif u.path=='/api/context':
                data={'id':hashlib.sha256(str(REPO).encode()).hexdigest(),'repo':github_repo()}
            elif u.path=='/api/review-summary':
                data=review_summary(q.get('left',[''])[0],q.get('right',[''])[0],q.get('pr',[None])[0])
            elif u.path=='/api/prs':
                data=list_prs(force=q.get('refresh',['0'])[0]=='1')
            elif u.path=='/api/pr':
                data=resolve_pr(q.get('number',[''])[0],force=q.get('refresh',['0'])[0]=='1')
            elif u.path=='/api/files':
                files=set()
                for ref in (q.get('left',['WORKTREE'])[0],q.get('right',['HEAD'])[0]):
                    if ref=='WORKTREE':
                        for file in REPO.rglob('*.xml'):
                            if '.git' not in file.relative_to(REPO).parts and file.resolve().is_relative_to(REPO):
                                files.add(file.relative_to(REPO).as_posix())
                    else:
                        sha=git('rev-parse','--verify',ref+'^{commit}').decode().strip()
                        files.update(path for path in git('ls-tree','-r','--name-only',sha).decode().splitlines() if path.lower().endswith('.xml'))
                data={'files':sorted(files)}
            elif u.path=='/api/compare':
                get=lambda k,d:q.get(k,[d])[0]
                path=get('path','doc/Agentic.xml'); left=get('left','WORKTREE'); right=get('right','origin/AI/introducing_sosaobservation')
                data=comparison(left,right,path,q.get('pr',[None])[0])
            elif u.path=='/api/asset':
                blob=q.get('blob',[''])[0]
                if blob:
                    if not re.fullmatch(r'[a-f0-9]{40,64}',blob):raise ValueError('Invalid image identifier')
                    payload=git('cat-file','blob',blob)
                else:payload=source(q.get('ref',[''])[0],q.get('path',[''])[0])
                mime=image_mime(payload)
                if not mime:raise ValueError('Unsupported image preview')
                self.send_response(200);self.send_header('Content-Type',mime);self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'");self.send_header('Cache-Control','private, max-age=600');self.end_headers();self.wfile.write(payload);return
            elif u.path=='/app.js':
                payload=Path(__file__).with_name('app.js').read_bytes(); self.send_response(200); self.send_header('Content-Type','text/javascript; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(payload); return
            elif u.path=='/':
                payload=Path(__file__).with_name('index.html').read_bytes(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(payload); return
            else: self.send_error(404); return
            payload=json.dumps(data).encode(); self.send_response(200)
        except Exception as e:
            payload=json.dumps({'error':str(e) if not isinstance(e,subprocess.CalledProcessError) else e.stderr.decode(errors='replace'),'retryAt':getattr(e,'retry_at',None)}).encode(); self.send_response(429 if isinstance(e,GitHubError) and e.retry_at else 400)
        self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(payload)
if __name__=='__main__':
    p=argparse.ArgumentParser(description='Review formatted DocBook differences in a local Git repository.')
    p.add_argument('--repo',type=Path,default=REPO)
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--open',action='store_true',help='Open the viewer in your default browser')
    p.add_argument('--no-open',action='store_false',dest='open',help='Start without opening a browser (overrides --open)')
    args=p.parse_args(); REPO=args.repo.resolve()
    try:
        git('rev-parse','--git-dir')
        httpd=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    except (OSError, subprocess.SubprocessError) as e:
        p.exit(1, f'Cannot start XML Review: {e}\nTry --repo /path/to/specs or --port 8766.\n')
    url=f'http://127.0.0.1:{httpd.server_port}'
    print(f'XML Review: {url}\nRepository: {REPO}\nPress Ctrl+C to stop.',flush=True)
    if args.open:
        threading.Thread(target=webbrowser.open,args=(url,),daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nXML Review stopped.')
    finally:
        httpd.server_close()
