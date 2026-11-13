import {test} from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {makeReview,seal,unseal,REPOSITORY} from './core.mjs';
globalThis.crypto??=webcrypto;
const left='a'.repeat(40),right='b'.repeat(40);
function fixture(){
 const target={available:true,right,path:'Demo.xml',startLine:2,line:4,original:'<para>\nOld\n</para>'};
 const snapshot={repository:REPOSITORY,pr:{number:2,left,right},comparisons:{'Demo.xml':{review:'review',rows:[{id:'block',status:'changed',anchor:{subjectType:'LINE',side:'RIGHT',line:3}}],suggestions:{block:target},suggestionSource:'<book>\n<para>\nOld\n</para>\n</book>'}}};
 const input={repo:REPOSITORY,pr:2,left,right,summary:'',notes:[{path:'Demo.xml',review:'review',block:'block',text:'Check timeout',suggestion:{...target,text:'<para>New</para>'}}]};return {input,snapshot};
}
test('suggestions become exact multiline review threads, with no approval event',()=>{const {input,snapshot}=fixture(),body=makeReview(input,snapshot);assert.equal(body.event,'COMMENT');assert.equal(body.commit_id,right);assert.equal(body.comments[0].start_line,2);assert.equal(body.comments[0].line,4);assert.equal(body.comments[0].body,'Check timeout\n\n```suggestion\n<para>New</para>\n```');});
test('suggestion-only feedback is included',()=>{const {input,snapshot}=fixture();input.notes[0].text='';assert.equal(makeReview(input,snapshot).comments.length,1);});
test('ONVIF and arbitrary repositories are refused',()=>{for(const repo of ['onvif/specs','other/repo']){const {input,snapshot}=fixture();input.repo=repo;assert.throws(()=>makeReview(input,snapshot),/restricted/);}});
test('stale comparisons and forged source locations are refused or ignored',()=>{const {input,snapshot}=fixture();input.right='c'.repeat(40);assert.throws(()=>makeReview(input,snapshot),/comparison changed/);input.right=right;input.notes[0].suggestion.line=1000;assert.throws(()=>makeReview(input,snapshot),/source changed/);});
test('broken XML and injected code fences are refused',()=>{for(const text of ['<para>Broken','```suggestion\nfoo','<!DOCTYPE book><para/>']){const {input,snapshot}=fixture();input.notes[0].suggestion.text=text;assert.throws(()=>makeReview(input,snapshot),/invalid|Invalid|DTD/);}});
test('duplicate or missing blocks do not create reviews',()=>{const {input,snapshot}=fixture();input.notes.push(input.notes[0]);assert.throws(()=>makeReview(input,snapshot),/duplicated/);input.notes=[{...input.notes[0],block:'missing'}];assert.throws(()=>makeReview(input,snapshot),/missing/);});
test('non-inline comments remain in the summary rather than a misleading file thread',()=>{const {input,snapshot}=fixture();input.notes[0].suggestion=null;snapshot.comparisons['Demo.xml'].rows[0].anchor={subjectType:'FILE'};const body=makeReview(input,snapshot);assert.deepEqual(body.comments,[]);assert.match(body.body,/### Demo.xml\n\nCheck timeout/);});
test('session encryption authenticates cookies and rejects expired/wrong-key values',async()=>{const secret='test secret '.repeat(4),value={token:'sensitive-test-token',expires:Date.now()+10000};const encrypted=await seal(value,secret);assert.ok(!encrypted.includes(value.token));assert.deepEqual(await unseal(encrypted,secret),value);assert.equal(await unseal(encrypted,'wrong'.repeat(10)),null);assert.equal(await unseal(await seal({...value,expires:0},secret),secret),null);assert.equal(await unseal(encrypted+'x',secret),null);});
