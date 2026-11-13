#!/usr/bin/env python3
"""One-time local GitHub App manifest setup. Never prints generated credentials."""
import html,json,os,secrets,subprocess,tempfile,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlparse
ROOT=Path(__file__).resolve().parent
HOST='http://127.0.0.1:8977'
WORKER='https://spec-review-test.spec-tools.workers.dev'
STATE=secrets.token_urlsafe(32)
MANIFEST={'name':'VideoAI Spec Review Test','url':WORKER,'redirect_url':HOST+'/callback','callback_urls':[WORKER+'/auth/callback'],'hook_attributes':{'url':WORKER+'/github/webhook','active':False},'public':False,'default_permissions':{'pull_requests':'write','contents':'read'},'default_events':[],'setup_url':WORKER,'request_oauth_on_install':False}
DONE=False
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def page(self,body,status=200):
  self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action https://github.com; base-uri 'none'; frame-ancestors 'none'");self.end_headers();self.wfile.write(('<html><meta charset="utf-8"><style>body{font:18px/1.6 system-ui;max-width:760px;margin:60px auto;color:#164536}button{font:inherit;padding:12px 18px}a{color:#164536}</style>'+body).encode())
 def do_GET(self):
  global DONE
  if self.headers.get('Host')!='127.0.0.1:8977':self.page('Invalid host',400);return
  q=parse_qs(urlparse(self.path).query);path=urlparse(self.path).path
  if path=='/':
   manifest=html.escape(json.dumps(MANIFEST),quote=True)
   self.page('<h1>Set up test GitHub sign-in</h1><p>This creates a private GitHub App owned by <strong>videoai</strong>, requesting <strong>Pull requests: read/write</strong> and <strong>Contents: read</strong>. After creation, install it on <strong>Only select repositories → test-specs</strong>.</p><p>The generated client secret will be sent directly to your Cloudflare Worker. It is never shown or committed.</p><form method="post" action="https://github.com/settings/apps/new?state='+STATE+'"><input type="hidden" name="manifest" value="'+manifest+'"><button>Continue to GitHub registration</button></form>');return
  if path!='/callback' or DONE or q.get('state',[''])[0]!=STATE or not q.get('code',[''])[0]:self.page('Invalid or expired setup callback.',400);return
  DONE=True
  try:
   code=q['code'][0]
   if not code.isalnum() or len(code)>200:raise ValueError('Invalid registration code')
   request=urllib.request.Request('https://api.github.com/app-manifests/'+code+'/conversions',method='POST',headers={'Accept':'application/vnd.github+json','User-Agent':'Spec-Review-setup'})
   with urllib.request.urlopen(request,timeout=30) as response:data=json.load(response)
   if data.get('owner',{}).get('login','').lower()!='videoai':raise ValueError('Create the app while signed in as videoai.')
   if data.get('permissions',{})!={'metadata':'read','contents':'read','pull_requests':'write'}:raise ValueError('Unexpected app permissions; inspect the app registration.')
   payload={'GITHUB_CLIENT_ID':data['client_id'],'GITHUB_CLIENT_SECRET':data['client_secret']}
   descriptor,name=tempfile.mkstemp(prefix='spec-review-github-',suffix='.json')
   try:
    with os.fdopen(descriptor,'w') as file:json.dump(payload,file)
    subprocess.run(['npx','wrangler','secret','bulk',name],cwd=ROOT,check=True,timeout=120)
   finally:Path(name).unlink(missing_ok=True)
   slug=data['slug'];install='https://github.com/apps/'+slug+'/installations/new'
   (ROOT/'app-registration.json').write_text(json.dumps({'slug':slug,'clientId':data['client_id'],'url':data['html_url']},indent=2))
   print('App configured. Install only on videoai/test-specs: '+install,flush=True)
   self.page('<h1>GitHub App configured</h1><p>The client secret is now stored in Cloudflare.</p><p><a href="'+html.escape(install,quote=True)+'">Install the GitHub App</a> and choose <strong>Only select repositories → test-specs</strong>.</p><p>Then open <a href="'+WORKER+'">the test review website</a> and choose <strong>Sign in with GitHub</strong>.</p>')
  except Exception:
   print('Registration could not be completed. Inspect the GitHub App and retry setup without sharing any generated secret.',flush=True)
   self.page('Setup could not be completed. Return to the setup instructions; do not share any generated secret.',400)
if __name__=='__main__':
 print('Open '+HOST+' to register the test GitHub App.',flush=True)
 ThreadingHTTPServer(('127.0.0.1',8977),Handler).serve_forever()
