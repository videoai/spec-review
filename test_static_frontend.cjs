const assert=require('node:assert/strict');
global.crypto=require('node:crypto').webcrypto;
const Core=require('./review-core.js');
(async()=>{
 const backup={format:'onvif-spec-review',version:1,repository:'org/repo',pr:877,notes:{['a'.repeat(64)]:{['b'.repeat(64)]:{text:'Note',path:'A.xml'}}},reviewed:{['c'.repeat(64)]:true},draft:{summary:{text:'Summary'},files:{'A.xml':{text:'File note'}}}};
 assert.equal(Core.validateBackup(backup,'org/repo',877).notes,1);
 assert.throws(()=>Core.validateBackup(backup,'other/repo',877),/different/);
 assert.throws(()=>Core.validateBackup({...backup,reviewed:{bad:true}},'org/repo',877),/identifier/);
 const pr={number:877,left:'a'.repeat(40),right:'b'.repeat(40)};
 const docs={documents:[{path:'A.xml',changes:[{heading:'Scope',left:'Old',right:'New',note:{text:'Chunk feedback'},anchor:{subjectType:'LINE',side:'RIGHT',line:7}},{heading:'Uncommented',left:'Uncommented secret',right:'Text'}]}]};
 const preview=await Core.preview('org/repo',pr,docs,backup.draft,text=>text);
 assert.equal(preview.files[0].body,'Chunk feedback');
 assert.equal(preview.files.length,1);assert.equal(preview.files[0].location,'Proposed line 7');assert.match(preview.files[0].url,/#diff-[a-f0-9]{64}R7$/);
 assert.match(preview.markdown,/Chunk feedback/);assert.match(preview.markdown,/Summary/);assert.match(preview.body,/### A.xml\n\nFile note/);assert.deepEqual(Core.normalizeDraft(Core.normalizeDraft(backup.draft)),Core.normalizeDraft(backup.draft));assert.ok(!preview.markdown.includes('Uncommented secret'));
 assert.ok(!('canSubmit' in preview));
 await assert.rejects(Core.preview('org/repo',pr,{documents:[]},Core.empty().draft,text=>text),/Add a PR summary/);
 console.log('Static backup validation and copy/paste review export checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
