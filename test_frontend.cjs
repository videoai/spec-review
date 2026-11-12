// Pure review logic tests; no browser or external packages required.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(__dirname+'/app.js','utf8');
function fn(name, next) { return source.slice(source.indexOf('function '+name+'('), source.indexOf(next, source.indexOf('function '+name+'('))); }
const context = { plain: text => text.replace(/<[^>]+>/g,''), download:(text,name)=>{context.exported={text,name};} };
vm.createContext(context);
vm.runInContext(fn('updateMessage',"$('fetchLatest').onclick"),context);
const old=[{key:'same',context:'A|scope',reviewed:true},{key:'old',context:'B|scope',reviewed:true}];
const next=[{key:'same',context:'A|scope',reviewed:true},{key:'changed',context:'B|scope',reviewed:false},{key:'new',context:'C|scope',reviewed:false}];
assert.match(context.updateMessage(old,next),/1 new · 1 reviewed retained · 1 need another look · 1 earlier changes replaced or removed/);
assert.match(context.updateMessage(old,old),/0 new · 2 reviewed retained · 0 need another look/);
context.activePr={number:877,title:'Review title',base:'main',head:'feature',left:'12345678full',right:'abcdef12full'};
context.reviewDraft={summary:{},files:{}};
context.overview={documents:[{path:'doc/A.xml',changes:[{heading:'Scope',status:'changed',reviewed:true,left:'<p>Old</p>',right:'<p>New</p>',note:{text:'My note'}}]},{path:'doc/B.xml',changes:[{heading:'Details',status:'added',reviewed:false,left:'',right:'Added text',note:null}]}]};
vm.runInContext(fn('exportReview','function escapeHtml'),context);
context.exportReview();
assert.equal(context.exported.name,'pr-877-notes.md');
for (const text of ['PR #877','main (common ancestor) · 12345678','feature · abcdef12','1 commented change','doc/A.xml','### Scope','My note','Before:','After:']) assert.ok(context.exported.text.includes(text),text);
assert.ok(!context.exported.text.includes('doc/B.xml'));
assert.ok(!context.exported.text.includes('Added text'));
console.log('Refresh classification and commented-only PR notes export checks passed.');

vm.runInContext(fn('escapeHtml',"$('exportPdf').onclick"),context);
const printed=context.pdfHtml(context.activePr,'doc/A.xml',[{id:'block',status:'changed',left:'<p>Old</p>',right:'<p>New</p>'}],{block:{text:'Check <script>bad()</script> & wording'}});
for(const text of ['size:A4 landscape','display:table-header-group','Review note','&lt;script&gt;bad()&lt;/script&gt;','doc/A.xml','12345678full','abcdef12full','<p>Old</p>','<p>New</p>'])assert.ok(printed.includes(text),text);
assert.ok(!printed.includes('<script>bad()'));
console.log('Print layout metadata, complete comparison, and note escaping checks passed.');
vm.runInContext(fn('labelMatches','function renderPrList'),context);
assert.equal(context.labelMatches({labels:['WG_ai']},'WG_ai'),true);
assert.equal(context.labelMatches({labels:['WG_media']},'WG_ai'),false);
assert.equal(context.labelMatches({},''),true);
console.log('PR label filtering checks passed.');

context.reviewDraft={summary:{text:'Overall PR feedback'},files:{'doc/B.xml':{text:'File feedback'}}};
context.exportReview();
for(const text of ['Overall PR feedback','doc/B.xml','File feedback'])assert.ok(context.exported.text.includes(text));
assert.ok(!context.exported.text.includes('Added text'));
console.log('PR summary and file-note export checks passed.');

vm.runInContext(fn('firstUnreviewed','async function resumeReview'),context);
const review={documents:[{path:'done.xml',changes:[{reviewKey:'done',reviewed:true}]},{path:'failed.xml',error:'Invalid XML',changes:[]},{path:'next.yaml',changes:[{reviewKey:'first',reviewed:false},{reviewKey:'later',reviewed:false}]}]};
assert.equal(context.firstUnreviewed(review).path,'next.yaml');
assert.equal(context.firstUnreviewed(review).key,'first');
assert.match(context.completionText(review,'done.xml'),/This file is reviewed/);
review.documents[2].changes.forEach(row=>row.reviewed=true);
assert.equal(context.firstUnreviewed(review),null);
assert.match(context.completionText(review,'done.xml'),/incomplete/);
review.documents.splice(1,1);
assert.match(context.completionText(review,'done.xml'),/All changes reviewed/);
assert.equal(context.completionText({documents:[]},''),'All changes reviewed in this PR.');
vm.runInContext(fn('feedbackGroups','function renderFeedback'),context);
const groups=context.feedbackGroups({items:[{kind:'file',path:'A',body:'For A'},{kind:'file',path:'B',body:'For B'},{kind:'review'},{kind:'conversation'}]},'A');
assert.equal(groups.file.length,1);assert.equal(groups.file[0].body,'For A');assert.equal(groups.pr.length,2);
console.log('Resume across files, completion, incomplete renders, and GitHub feedback scoping checks passed.');
