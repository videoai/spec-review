"""Private loopback backend for the Mac application; never publishes credentials."""
import hashlib, http.cookies, json, os, secrets, subprocess, threading, urllib.request
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode
import server
from desktop_workspace import Workspace

WORKSPACE=None

SESSION=secrets.token_urlsafe(32)
SUBMIT_LOCK=threading.Lock()
LOGIN=None
LOGIN_MESSAGE=''

def github_write(endpoint,payload):
    token=server.github_token()
    if not token:raise ValueError('Sign in to GitHub first')
    request=urllib.request.Request('https://api.github.com/'+endpoint,data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/vnd.github+json','User-Agent':'ONVIF-Spec-Review'},method='POST')
    with urllib.request.urlopen(request,timeout=30) as response:result=json.load(response)
    if result.get('errors'):raise ValueError('; '.join(item['message'] for item in result['errors']))
    return result

def submit_review(data):
    if data.get('confirm') is not True:raise ValueError('Confirm the review before submitting')
    with SUBMIT_LOCK:
        preview=server.prepare_review(data)
        if preview['repo'] not in server.SUPPORTED_REPOSITORIES or (WORKSPACE is not None and preview['repo']!=WORKSPACE.repository):raise ValueError('Unsupported review repository')
        repo=preview['repo']
        if preview['id']!=data.get('id'):raise ValueError('Notes changed. Reopen Finish review.')
        if preview['incomplete']:raise ValueError('Some files could not be checked. Resolve these errors before submitting.')
        user=server.github_api('user',force=True)
        if getattr(server.API_INFO,'value',{}).get('stale'):raise ValueError('GitHub is unavailable. Try again later.')
        remote=server.github_api('repos/'+repo+'/pulls/'+str(preview['pr']),force=True)
        if getattr(server.API_INFO,'value',{}).get('stale'):raise ValueError('GitHub is unavailable. Try again later.')
        if remote.get('state')!='open' or remote['head']['sha']!=preview['right']:raise ValueError('PR changed. Refresh and review again.')
        base=server.git('merge-base',remote['base']['sha'],remote['head']['sha']).decode().strip()
        if base!=preview['left']:raise ValueError('PR base changed. Refresh and review again.')
        path=server.notes_path().with_name('xml-review-submissions-pr-'+str(preview['pr'])+'.json')
        journal=json.loads(path.read_text()) if path.exists() else {}
        key=str(user['id'])+':'+preview['id'];entry=journal.get(key)
        if entry:
            if entry['state']=='submitted':return {'url':entry['url']}
            raise ValueError('An earlier attempt needs checking on GitHub. Automatic retries are blocked to avoid duplicate comments: '+entry['url'])
        entry={'state':'starting','url':preview['url']};journal[key]=entry
        def save():server.write_api_cache(path,journal)
        save()
        try:
            review=github_write('repos/'+repo+'/pulls/'+str(preview['pr'])+'/reviews',{'commit_id':preview['right'],'body':preview['body']})
            entry.update(state='pending',url=review.get('html_url') or preview['url'],reviewId=review['id']);save()
            mutation='mutation($input:AddPullRequestReviewThreadInput!){addPullRequestReviewThread(input:$input){thread{id}}}'
            for comment in preview['files']:
                anchor=comment['anchor'];fields={key:anchor[key] for key in ('subjectType','line','side','startLine','startSide') if key in anchor}
                github_write('graphql',{'query':mutation,'variables':{'input':dict(fields,pullRequestReviewId=review['node_id'],path=comment['path'],body=comment['body'])}})
            result=github_write('repos/'+repo+'/pulls/'+str(preview['pr'])+'/reviews/'+str(review['id'])+'/events',{'event':'COMMENT','body':preview['body']})
            entry.update(state='submitted',url=result.get('html_url') or entry['url']);save();return {'url':entry['url']}
        except Exception:
            entry['state']='needs-attention';save()
            raise ValueError('Submission did not complete. Check for a pending review at '+entry['url']+'. Automatic retries are blocked.') from None

class Handler(server.Handler):
    def log_message(self,*args):pass # Never log session URLs or credentials.
    def valid(self):
        cookie=http.cookies.SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except http.cookies.CookieError:return False
        return secrets.compare_digest(cookie.get('review_session').value if cookie.get('review_session') else '',SESSION)
    def result(self,data,code=200):
        self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(json.dumps(data).encode())
    def do_GET(self):
        url=urlparse(self.path);query=parse_qs(url.query)
        if url.path=='/' and secrets.compare_digest(query.get('desktop_session',[''])[0],SESSION):
            self.send_response(303);self.send_header('Set-Cookie','review_session='+SESSION+'; HttpOnly; SameSite=Strict; Path=/');self.send_header('Location','/?'+urlencode({key:query[key][0] for key in ('pr','path','left','right') if key in query}));self.end_headers();return
        if not self.valid():self.result({'error':'Private app session required'},403);return
        if url.path=='/api/context':
            self.result({'desktop':True,'repo':server.github_repo(),'id':'desktop-'+WORKSPACE.repository.replace('/','-'),'repositories':list(server.SUPPORTED_REPOSITORIES),'preferences':WORKSPACE.read(WORKSPACE.reviews/'preferences.json'),'migration':WORKSPACE.migration});return
        if url.path=='/api/desktop/status':self.result(WORKSPACE.status);return
        if url.path=='/api/desktop/update':
            try:self.result(WORKSPACE.check_update(query.get('pr',[''])[0],query.get('right',[''])[0]))
            except Exception as error:self.result({'available':False,'message':'Could not check GitHub: '+str(error)+'. Your current comparison is unchanged.'})
            return
        if url.path=='/api/desktop/auth':
            try:
                user=server.github_api('user',force=True) if server.github_token() else {}
                if getattr(server.API_INFO,'value',{}).get('stale'):user={}
                self.result({'login':user.get('login'),'message':LOGIN_MESSAGE})
            except Exception:self.result({'login':None,'message':LOGIN_MESSAGE})
            return
        super().do_GET()
    def do_POST(self):
        global LOGIN,LOGIN_MESSAGE
        if not self.valid():self.result({'error':'Private app session required'},403);return
        if not self.path.startswith('/api/desktop/'):super().do_POST();return
        try:
            if self.headers.get('Origin')!='http://'+self.headers.get('Host',''):raise ValueError('Origin mismatch')
            if self.headers.get('Content-Type')!='application/json':raise ValueError('JSON required')
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=100000:raise ValueError('Invalid request size')
            data=json.loads(self.rfile.read(size))
            if self.path=='/api/desktop/preferences':
                allowed=('pr','path','only','hideReviewed','label','block','lastRefresh')
                clean={key:data[key] for key in allowed if key in data and isinstance(data[key],(str,int,bool,type(None)))}
                with WORKSPACE.lock:WORKSPACE.write(WORKSPACE.reviews/'preferences.json',clean)
                self.result({'saved':True});return
            if self.path=='/api/desktop/submit':self.result(submit_review(data));return
            if self.path=='/api/desktop/login':
                if LOGIN is None or LOGIN.poll() is not None:
                    LOGIN_MESSAGE='Starting GitHub sign in…'
                    LOGIN=subprocess.Popen(['gh','auth','login','--hostname','github.com','--git-protocol','https','--web','--skip-ssh-key'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=dict(os.environ,GH_BROWSER='/usr/bin/open'))
                    def read_login():
                        global LOGIN_MESSAGE
                        for line in LOGIN.stdout:
                            # Only expose a device code, never arbitrary credential output.
                            import re
                            match=re.search(r'\b[A-Z0-9]{4}-[A-Z0-9]{4}\b',line)
                            if match:LOGIN_MESSAGE='Enter code '+match.group()+' at https://github.com/login/device';LOGIN.stdin.write('\n');LOGIN.stdin.flush()
                        LOGIN.wait()
                        if LOGIN.returncode:LOGIN_MESSAGE='Sign in did not complete. Try again.'
                    threading.Thread(target=read_login,daemon=True).start()
                self.result({'message':LOGIN_MESSAGE});return
            self.result({'error':'Unknown action'},404)
        except Exception as error:self.result({'error':str(error)},400)

if __name__=='__main__':
    import signal, time
    signal.signal(signal.SIGTERM,lambda *_:exit(0))
    parent=os.getppid()
    def watch_parent():
        while True:
            time.sleep(2)
            if os.getppid()!=parent:os._exit(0)
    threading.Thread(target=watch_parent,daemon=True).start()
    WORKSPACE=Workspace(root=os.environ.get('XML_REVIEW_APP_SUPPORT'),repository=os.environ.get('XML_REVIEW_GITHUB_REPO','onvif/specs'),report=lambda message:print('SPEC_REVIEW_STATUS '+json.dumps({'message':message}),flush=True))
    WORKSPACE.initialize()
    WORKSPACE.activate()
    httpd=server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    print('SPEC_REVIEW_READY '+json.dumps({'url':'http://127.0.0.1:'+str(httpd.server_port)+'/?desktop_session='+SESSION}),flush=True)
    try:httpd.serve_forever()
    finally:
        httpd.server_close()
        if LOGIN and LOGIN.poll() is None:LOGIN.terminate()
