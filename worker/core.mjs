import {SaxesParser} from 'saxes';
export const REPOSITORY='videoai/test-specs';
export const UPSTREAM='https://videoai.github.io/spec-review/test/';
const enc=new TextEncoder();
export function requireTestRepository(value){if(value!==REPOSITORY)throw Error('Submission is restricted to videoai/test-specs.');}
export const random=()=>base64(crypto.getRandomValues(new Uint8Array(32)));
export function base64(bytes){return btoa(String.fromCharCode(...bytes)).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');}
export function unbase64(value){return Uint8Array.from(atob(value.replaceAll('-','+').replaceAll('_','/')),c=>c.charCodeAt(0));}
export async function digest(value){return base64(new Uint8Array(await crypto.subtle.digest('SHA-256',enc.encode(value))));}
async function key(secret){if(!secret||secret.length<32)throw Error('Sign-in is not configured.');return crypto.subtle.importKey('raw',await crypto.subtle.digest('SHA-256',enc.encode(secret)),'AES-GCM',false,['encrypt','decrypt']);}
export async function seal(value,secret){const iv=crypto.getRandomValues(new Uint8Array(12));const data=await crypto.subtle.encrypt({name:'AES-GCM',iv},await key(secret),enc.encode(JSON.stringify(value)));return base64(iv)+'.'+base64(new Uint8Array(data));}
export async function unseal(value,secret){try{if(!value||value.length>6000)return null;const [iv,data]=value.split('.');const bytes=await crypto.subtle.decrypt({name:'AES-GCM',iv:unbase64(iv)},await key(secret),unbase64(data));const result=JSON.parse(new TextDecoder().decode(bytes));return result.expires>Date.now()?result:null;}catch{return null;}}
export function makeReview(input,snapshot){
 requireTestRepository(input.repo);requireTestRepository(snapshot.repository);
 const pr=snapshot.pr;
 if(!Number.isSafeInteger(input.pr)||input.pr!==pr.number||input.right!==pr.right||input.left!==pr.left)throw Error('The published comparison changed. Reload the PR before submitting.');
 if(typeof input.summary!=='string'||input.summary.length>58000||!Array.isArray(input.notes)||input.notes.length>100)throw Error('Invalid review draft (maximum 100 comments per submission).');
 const comments=[],general=[],seen=new Set();
 for(const note of input.notes){
  if(!note||typeof note.text!=='string'||note.text.length>20000||typeof note.path!=='string')throw Error('Invalid review note.');
  const doc=snapshot.comparisons[note.path],row=doc?.rows?.find(r=>r.id===note.block&&r.status!=='same');
  if(!row||doc.review!==note.review||seen.has(note.path+'|'+note.block))throw Error('A change is missing, duplicated or outdated. Reload the PR.');
  seen.add(note.path+'|'+note.block);let anchor=row.anchor,body=note.text.trim();
  if(note.suggestion){
   const target=doc.suggestions?.[note.block],replacement=note.suggestion.text;
   if(!target?.available||target.right!==pr.right||typeof replacement!=='string'||replacement.length>20000||replacement===target.original||/^\s*`{3,}/m.test(replacement))throw Error('Invalid or outdated suggested change. Edit and save it again.');
   if(['original','right','startLine','line'].some(key=>note.suggestion[key]!==target[key]))throw Error('The suggestion source changed. Edit and save it again.');
   if(note.path.toLowerCase().endsWith('.xml')){
    if(typeof doc.suggestionSource!=='string')throw Error('XML source is unavailable.');
    const lines=doc.suggestionSource.replace(/^\uFEFF/,'').replace(/\r\n?/g,'\n').split('\n');
    const xml=[...lines.slice(0,target.startLine-1),replacement,...lines.slice(target.line)].join('\n');
    if(/<!DOCTYPE|<!ENTITY/i.test(xml))throw Error('DTD/entity declarations are not supported.');
    try{new SaxesParser({xmlns:true}).write(xml).close();}catch{throw Error('The suggested replacement would make the XML invalid.');}
   }
   anchor={subjectType:'LINE',side:'RIGHT',line:target.line,...(target.startLine!==target.line?{startLine:target.startLine,startSide:'RIGHT'}:{})};
   body=[body,'','```suggestion',replacement,'```'].join('\n').trim();
  }
  if(!body)continue;
  if(anchor?.subjectType==='LINE'){
   const comment={path:note.path,body,line:anchor.line,side:anchor.side};
   if(anchor.startLine){comment.start_line=anchor.startLine;comment.start_side=anchor.startSide;}
   comments.push(comment);
  }else general.push('### '+note.path+'\n\n'+body);
 }
 if(!comments.length&&!general.length&&!input.summary.trim())throw Error('Add a summary, note or suggestion first.');
 const body=[input.summary.trim(),...general,'Reviewed with ONVIF Spec Review at `'+pr.right.slice(0,8)+'`.'].filter(Boolean).join('\n\n');
 if(body.length>65000)throw Error('Review summary is too long.');
 return {commit_id:pr.right,event:'COMMENT',body,comments};
}
