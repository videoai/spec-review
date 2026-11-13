import {DurableObject} from 'cloudflare:workers';
import {REPOSITORY,UPSTREAM,random,digest,seal,unseal,makeReview} from './core.mjs';
const SESSION='__Host-review_session',FLOW='__Host-review_flow';
const headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'};
function json(value,status=200,extra={}){return new Response(JSON.stringify(value),{status,headers:{...headers,'Content-Type':'application/json',...extra}});}
function cookie(name,value,age){return `${name}=${value}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=${age}`;}
function cookies(request){return Object.fromEntries((request.headers.get('Cookie')||'').split(';').map(part=>part.trim().split('=')));}
function redirect(url,extra={}){return new Response(null,{status:302,headers:{...headers,Location:url,...extra}});}
async function session(request,env){return unseal(cookies(request)[SESSION],env.SESSION_KEY);}
async function github(path,token,options={}){
 const response=await fetch('https://api.github.com/'+path,{...options,redirect:'error',headers:{'User-Agent':'ONVIF-Spec-Review-test','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28',Authorization:'Bearer '+token,...options.headers}});
 if(!response.ok)throw Error('GitHub returned '+response.status+'. Check your app installation, PR access and pending reviews on GitHub.');
 return response.status===204?{}:response.json();
}
async function snapshot(number){
 const index=await fetch(UPSTREAM+'site.json',{cache:'no-store',redirect:'error'});if(!index.ok)throw Error('Published test comparisons are unavailable.');const manifest=await index.json();
 if(manifest.repository!==REPOSITORY)throw Error('Invalid published test repository.');
 const entry=manifest.prs.find(p=>p.number===number);
 if(!entry||entry.error||!/^data\/pr-\d+-[a-f0-9]{16}\.json$/.test(entry.data))throw Error('The test PR is not in the published comparison.');
 const response=await fetch(UPSTREAM+entry.data,{redirect:'error'});if(!response.ok)throw Error('Published test comparison is unavailable.');
 const value=await response.json();return {...value,repository:manifest.repository};
}
function sameOrigin(request,url){if(request.headers.get('Origin')!==url.origin)throw Error('Cross-origin writes are not allowed.');}
export default {async fetch(request,env){
 const url=new URL(request.url),path=url.pathname;
 try{
  if(path==='/web-config.json')return json({auth:true,repository:REPOSITORY,configured:!!(env.GITHUB_CLIENT_ID&&env.GITHUB_CLIENT_SECRET&&env.SESSION_KEY)});
  if(path==='/api/web/auth'&&request.method==='GET'){
   const user=await session(request,env);return json({signedIn:!!user,login:user?.login||'',csrf:user?.csrf||'',configured:!!(env.GITHUB_CLIENT_ID&&env.GITHUB_CLIENT_SECRET&&env.SESSION_KEY)});
  }
  if(path==='/auth/login'&&request.method==='GET'){
   if(!env.GITHUB_CLIENT_ID||!env.GITHUB_CLIENT_SECRET)throw Error('GitHub App registration is not configured yet.');
   const state=random(),verifier=random(),back=url.searchParams.get('return')||'/';
   const flow={state,verifier,back:back.startsWith('/?')?back:'/',expires:Date.now()+600000};
   const auth=new URL('https://github.com/login/oauth/authorize');auth.search=new URLSearchParams({client_id:env.GITHUB_CLIENT_ID,redirect_uri:url.origin+'/auth/callback',state,code_challenge:await digest(verifier),code_challenge_method:'S256',allow_signup:'false'});
   return redirect(auth.href,{'Set-Cookie':cookie(FLOW,await seal(flow,env.SESSION_KEY),600)});
  }
  if(path==='/auth/callback'&&request.method==='GET'){
   const flow=await unseal(cookies(request)[FLOW],env.SESSION_KEY);
   if(!flow||flow.state!==url.searchParams.get('state')||!url.searchParams.get('code'))throw Error('Sign-in expired or was cancelled. Start again from the review page.');
   const exchange=await fetch('https://github.com/login/oauth/access_token',{method:'POST',redirect:'error',headers:{Accept:'application/json','Content-Type':'application/json'},body:JSON.stringify({client_id:env.GITHUB_CLIENT_ID,client_secret:env.GITHUB_CLIENT_SECRET,code:url.searchParams.get('code'),code_verifier:flow.verifier,redirect_uri:url.origin+'/auth/callback'})});
   const grant=await exchange.json();if(!exchange.ok||!grant.access_token||grant.error)throw Error('GitHub sign-in could not be completed.');
   const identity=await github('user',grant.access_token);
   const age=Math.min(3600,Math.max(1,Number(grant.expires_in)||3600));
   const user={id:identity.id,login:identity.login,token:grant.access_token,csrf:random(),expires:Date.now()+age*1000};
   const response=redirect(url.origin+flow.back);response.headers.append('Set-Cookie',cookie(SESSION,await seal(user,env.SESSION_KEY),age));response.headers.append('Set-Cookie',cookie(FLOW,'',0));return response;
  }
  if(path.startsWith('/api/web/')&&request.method==='POST'){
   sameOrigin(request,url);if(!request.headers.get('Content-Type')?.startsWith('application/json'))throw Error('Send JSON.');
   const user=await session(request,env);if(!user)return json({error:'Sign in with GitHub first.'},401);
   if(request.headers.get('X-Review-CSRF')!==user.csrf)throw Error('Session changed. Sign in again.');
   if(path==='/api/web/logout')return json({signedOut:true},200,{'Set-Cookie':cookie(SESSION,'',0)});
   if(path==='/api/web/submit'){
    const raw=await request.text();if(raw.length>250000)throw Error('Review is too large.');const input=JSON.parse(raw);
    if(input.confirm!==true)throw Error('Confirm submission before posting.');
    if(input.repo!==REPOSITORY||!Number.isSafeInteger(input.pr)||input.pr<1)throw Error('Only videoai/test-specs submissions are allowed.');
    const data=await snapshot(input.pr),body=makeReview(input,data);
    const live=await github(`repos/${REPOSITORY}/pulls/${input.pr}`,user.token);
    if(live.state!=='open'||live.head.sha!==data.pr.right||live.head.repo.full_name!==REPOSITORY)throw Error('The PR changed or closed. Check for a new published comparison before submitting.');
    const comparison=await github(`repos/${REPOSITORY}/compare/${live.base.sha}...${live.head.sha}`,user.token);
    if(comparison.merge_base_commit.sha!==data.pr.left)throw Error('The PR base changed. Check for a new published comparison.');
    const identifier=await digest(JSON.stringify([user.id,input.pr,body]));
    return env.SUBMISSIONS.get(env.SUBMISSIONS.idFromName(identifier)).fetch(new Request('https://internal/submit',{method:'POST',body:JSON.stringify({token:user.token,number:input.pr,body})}));
   }
   return json({error:'Unknown operation.'},404);
  }
  if(request.method!=='GET'&&request.method!=='HEAD')return json({error:'Method not allowed.'},405);
  if(!/^\/(?:|index\.html|app\.js|pages\.js|review-core\.js|site\.json|data\/pr-\d+-[a-f0-9]{16}\.json|assets\/[a-f0-9]{64}\.(?:png|jpg|gif|webp|svg))$/.test(path))return json({error:'Not found.'},404);
  const upstream=await fetch(UPSTREAM+(path==='/'?'index.html':path.slice(1)),{redirect:'error',cache:'no-store'});
  const response=new Response(upstream.body,upstream);response.headers.set('Cache-Control','no-cache');response.headers.set('Referrer-Policy','no-referrer');return response;
 }catch(error){return json({error:error.message||'Request failed.'},400);}
}};

export class Submission extends DurableObject {
 async fetch(request){
  return this.ctx.blockConcurrencyWhile(async()=>{
   const prior=await this.ctx.storage.get('attempt');
   if(prior?.result)return json(prior.result);
   if(prior)return json({error:'This review was already attempted. Check the PR on GitHub before trying another review; automatic retry is disabled.'},409);
   const {token,number,body}=await request.json();
   // Durable journal records no tokens or note text. A single atomic review request creates all threads.
   await this.ctx.storage.put('attempt',{time:Date.now()});await this.ctx.storage.setAlarm(Date.now()+30*86400000);
   try{
    const created=await github(`repos/${REPOSITORY}/pulls/${number}/reviews`,token,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const result={url:created.html_url,id:created.id};await this.ctx.storage.put('attempt',{result});return json(result);
   }catch{return json({error:'Submission was not confirmed. Check the PR on GitHub before retrying. No automatic retry was made.'},409);}
  });
 }
 async alarm(){await this.ctx.storage.deleteAll();}
}
