import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {seal} from './core.mjs';
const source=(await readFile(new URL('./index.mjs',import.meta.url),'utf8'))
 .replace("import {DurableObject} from 'cloudflare:workers';",'class DurableObject {}')
 .replace("'./core.mjs'",JSON.stringify(new URL('./core.mjs',import.meta.url).href))
 .replace("'./github.mjs'",JSON.stringify(new URL('./github.mjs',import.meta.url).href));
const {default:worker}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const origin='https://review.example',secret='fixture secret '.repeat(4);
test('repository selector routes use separate published snapshots and only test supports submission',async()=>{
 const original=globalThis.fetch;const requested=[];
 globalThis.fetch=async url=>{requested.push(String(url));return Response.json({ok:true});};
 try{
  const testConfig=await (await worker.fetch(new Request(origin+'/web-config.json'),{})).json();assert.equal(testConfig.repository,'videoai/test-specs');assert.equal(testConfig.submitAllowed,true);
  const onvifConfig=await (await worker.fetch(new Request(origin+'/onvif/web-config.json'),{})).json();assert.equal(onvifConfig.repository,'onvif/specs');assert.equal(onvifConfig.submitAllowed,false);
  await worker.fetch(new Request(origin+'/site.json'),{});await worker.fetch(new Request(origin+'/onvif/site.json'),{});
  assert.deepEqual(requested,['https://videoai.github.io/spec-review/test/site.json','https://videoai.github.io/spec-review/site.json']);
 }finally{globalThis.fetch=original;}
});
test('public signed-in reviewers need no collaborator installation enumeration; ONVIF writes remain blocked',async()=>{
 const original=globalThis.fetch,requests=[],right='b'.repeat(40),left='a'.repeat(40);let submitted;
 const snapshot={pr:{number:3,left,right},comparisons:{}};
 globalThis.fetch=async url=>{
  requests.push(String(url));
  if(String(url).endsWith('/test/site.json'))return Response.json({repository:'videoai/test-specs',prs:[{number:3,data:'data/pr-3-0123456789abcdef.json'}]});
  if(String(url).includes('/data/'))return Response.json(snapshot);
  if(String(url).includes('/pulls/3'))return Response.json({state:'open',base:{sha:left},head:{sha:right,repo:{full_name:'videoai/test-specs'}}});
  if(String(url).includes('/compare/'))return Response.json({merge_base_commit:{sha:left}});
  throw Error('Unexpected request: '+url);
 };
 const cookie=await seal({id:99,login:'public-reviewer',token:'fixture-token',csrf:'fixture-csrf',expires:Date.now()+60000},secret);
 const env={SESSION_KEY:secret,SUBMISSIONS:{idFromName:value=>value,get:()=>({fetch:async request=>{submitted=await request.json();return Response.json({url:'https://github.com/videoai/test-specs/pull/3#review'});}})}};
 const send=repo=>worker.fetch(new Request(origin+'/api/web/submit',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json','X-Review-CSRF':'fixture-csrf',Cookie:'__Host-review_session='+cookie},body:JSON.stringify({repo,pr:3,left,right,summary:'Hello Everyone',notes:[],confirm:true})}),env);
 try{
  const rejected=await send('onvif/specs');assert.equal(rejected.status,400);assert.equal(requests.length,0);
  const accepted=await send('videoai/test-specs');assert.equal(accepted.status,200);assert.match(submitted.body.body,/Hello Everyone/);
  assert.equal(requests.some(url=>url.includes('user/installations')),false);assert.equal(submitted.token,'fixture-token');
 }finally{globalThis.fetch=original;}
});
