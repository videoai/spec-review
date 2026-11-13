const $ = id => document.getElementById(id);
function desktopBridge(){return window.webkit?.messageHandlers?.desktop||window.chrome?.webview;}
let feedback=null,feedbackLoading=false,feedbackRequest=0,pendingImport=null;
let prCatalog=[],selectedLabel='';
let reviewDraft={summary:{},files:{}},preparedReview=null;
let activePr = null, overview = null, reviewId = '', reviewPath = '', notes = {}, noteRows = [];
let changes = [], current = -1, busy = false, saving = 0, storageKey = '', remembered = {}, historyNotes = {};
const toolbarObserver=new ResizeObserver(() => {const toolbar=document.querySelector('.toolbar');if(toolbar)document.documentElement.style.setProperty('--toolbar-height',toolbar.getBoundingClientRect().height+'px');});toolbarObserver.observe(document.querySelector('.toolbar'));

async function api(url, payload) {
  if(window.reviewBackend)return window.reviewBackend(url,payload);
  const response = await fetch(url, payload === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  const result = await response.json();
  if (!response.ok) throw Error(githubMessage(result.error || 'Request failed',result.retryAt));
  return result;
}
function githubMessage(message,retryAt){if(!retryAt)return message;const minutes=Math.max(0,Math.ceil((retryAt*1000-Date.now())/60000));return `GitHub rate limit reached. Retry after ${new Date(retryAt*1000).toLocaleString()} (about ${minutes} min).`;}
function githubNotice(meta){if(!meta)return;if(meta.stale){$('githubStatus').textContent='Using cached GitHub data. '+githubMessage(meta.warning||'GitHub is unavailable.',meta.retryAt);}else if(!$('githubStatus').textContent.startsWith('Using cached GitHub data.')){$('githubStatus').textContent=meta.cached?'Cached GitHub data · '+new Date(meta.fetchedAt*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):'';}}
function plain(markup) { const div=document.createElement('div'); div.innerHTML=markup; return div.textContent.trim(); }
function readStored() { if(window.DESKTOP_REVIEW)return window.DESKTOP_PREFERENCES||{};try { return JSON.parse(localStorage.getItem(storageKey)||'{}'); } catch { return {}; } }
function remember() {
  if (!storageKey) return;
  remembered={...remembered,pr:activePr?.number||null,path:reviewPath,only:$('only').checked,hideReviewed:$('hideReviewed').checked,label:selectedLabel,block:changes[current]?.dataset.key||null};
  if(window.DESKTOP_REVIEW){api('/api/desktop/preferences',remembered).catch(()=>{$('error').textContent='Could not save your review position. Notes are saved separately.';});return;}
  try { localStorage.setItem(storageKey,JSON.stringify(remembered)); } catch { /* Review works when browser storage is unavailable. */ }
}
function dirty() { return !!document.querySelector('.note-area[data-suggestion-changed="true"]')||[...document.querySelectorAll('.note-area textarea, #draftNoteDialog[open] textarea')].some(el=>el.value!==el.defaultValue); }
function askDiscard(){return new Promise(resolve=>{const dialog=$('draftDialog');let decided=false;const finish=value=>{if(decided)return;decided=true;dialog.close();resolve(value);};$('keepDraft').onclick=()=>finish(false);$('discardDraft').onclick=()=>finish(true);dialog.oncancel=event=>{event.preventDefault();finish(false);};dialog.showModal();$('keepDraft').focus();});}
async function mayLeave() {
  if(saving){$('error').textContent='A note or reviewed mark is still saving. Please wait.';return false;}
  return !dirty() || await askDiscard();
}
window.addEventListener('beforeunload',event=>{if(dirty()||saving){event.preventDefault();event.returnValue='';}});
function controls() {
  $('pr').disabled=busy||saving>0;
  $('refreshFeedback').disabled=feedbackLoading||busy||saving>0||!activePr;
  $('prLabel').disabled=busy||saving>0;
  $('resetReview').disabled=busy||saving>0||!activePr;
  for(const id of ['prSummary','previewReview','backupReview','importReview','resumeReview','showFeedback'])$(id).disabled=busy||saving>0||!activePr;
  $('noteHistory').disabled=busy||saving>0||!activePr;
  $('undoReset').hidden=!activePr?.canUndo;
  $('undoReset').disabled=busy||saving>0;
  $('fetchLatest').disabled=busy||saving>0;
  $('prDoc').disabled=busy||saving>0||!activePr?.files.length;
  $('exportNotes').disabled=busy||!overview;
  $('exportPdf').disabled=busy||saving>0||!reviewId||!noteRows.length;
  $('reviewNext').disabled=busy||saving>0||current<0||!changes.length||noteRows.filter(row=>row.status!=='same').every(row=>row.reviewed);
}
function updateSummaryRow(row) {
  const found=overview?.documents.find(doc=>doc.path===reviewPath)?.changes.find(change=>change.reviewKey===row.reviewKey);
  if(found){found.reviewed=row.reviewed;found.note=notes[row.id]||null;}
  progress();
}
function firstUnreviewed(summary) {
  for(const doc of summary?.documents||[]){if(doc.error)continue;const row=doc.changes.find(row=>!row.reviewed);if(row)return {path:doc.path,key:row.reviewKey};}
  return null;
}
function completionText(summary,path) {
  if(!summary)return '';
  const docs=summary.documents,errors=docs.some(doc=>doc.error);
  if(!firstUnreviewed(summary))return errors?'Review incomplete — some files could not be rendered.':'All changes reviewed in this PR.';
  const doc=docs.find(doc=>doc.path===path);
  return doc&&!doc.error&&doc.changes.every(row=>row.reviewed)?'This file is reviewed. Continue with the next unreviewed change.':'';
}
async function resumeReview(){
  const target=firstUnreviewed(overview);if(!target){progress();return;}
  if(target.path!==reviewPath)await compare(target.path,target.key);
  else{filter(false);const index=changes.findIndex(el=>el.dataset.key===target.key);if(index>=0)jump(index,false);}
}
function progress() {
  $('noteCount').textContent=Object.keys(notes).length+' change notes'+(reviewDraft.summary?.text?' · PR summary':'');
  $('prSummary').textContent=reviewDraft.summary?.text?'Edit PR summary…':'PR summary…';
  const all=overview?.documents.flatMap(doc=>doc.changes)||[], errors=overview?.documents.filter(doc=>doc.error)||[];
  const complete=overview?.documents.filter(doc=>!doc.error&&doc.changes.every(change=>change.reviewed)).length||0;
  $('prProgress').textContent=overview?`PR: ${all.filter(row=>row.reviewed).length}/${all.length} reviewed · ${complete}/${overview.documents.length} files${errors.length?' · incomplete':''}`:'';
  const banner=$('completionBanner'),message=completionText(overview,reviewPath);banner.replaceChildren();banner.hidden=!message;if(message){banner.append(document.createTextNode(message));if(firstUnreviewed(overview)){const button=document.createElement('button');button.textContent='Resume review';button.onclick=()=>$('resumeReview').click();banner.append(button);}}
  for(const option of $('prDoc').options){const doc=overview?.documents.find(doc=>doc.path===option.value);if(doc)option.textContent=(doc.fileStatus==='deleted'?'Deleted · ':doc.fileStatus==='added'?'Added · ':'')+doc.path+(doc.error?' · could not render':` · ${doc.changes.filter(c=>c.reviewed).length}/${doc.changes.length}`);}
}
function filter(persist=true) {
  const selected=changes[current];
  document.querySelectorAll('.row').forEach(el=>{el.classList.toggle('hidden',(el.dataset.status==='same'&&$('only').checked)||($('hideReviewed').checked&&el.classList.contains('reviewed')));el.classList.remove('current');});
  changes=[...document.querySelectorAll('.row:not(.same):not(.hidden)')];current=selected?changes.indexOf(selected):-1;
  if(current>=0)changes[current].classList.add('current');
  for(const id of ['first','prev','next','last'])$(id).disabled=!changes.length;
  const total=noteRows.filter(row=>row.status!=='same');
  $('reviewProgress').textContent=activePr?`File: ${total.filter(row=>row.reviewed).length}/${total.length}`:'';
  $('status').textContent=total.length&&total.every(row=>row.reviewed)?(firstUnreviewed(overview)?'File reviewed':overview?.documents.some(doc=>doc.error)?'Incomplete':'All reviewed'):current>=0?`${current+1} / ${changes.length}`:'';
  progress();controls();if(persist)remember();
}
function jump(index, smooth=true) {
  if(index<0||index>=changes.length)return;
  changes[current]?.classList.remove('current');current=index;changes[current].classList.add('current');
  changes[current].scrollIntoView({behavior:smooth?'smooth':'instant',block:'start'});
  $('status').textContent=`${current+1} / ${changes.length}`;controls();remember();
}
function move(step) { if(changes.length)jump(current<0?(step<0?changes.length-1:0):(current+step+changes.length)%changes.length); }
function advance(el) {
  const all=[...document.querySelectorAll('.row:not(.same)')],index=all.indexOf(el);
  const next=[...all.slice(index+1),...all.slice(0,index)].find(row=>!row.classList.contains('reviewed')&&!row.classList.contains('hidden'));
  if(next)jump(changes.indexOf(next));else $('status').textContent=firstUnreviewed(overview)?'File reviewed':overview?.documents.some(doc=>doc.error)?'Incomplete':'All reviewed';
}
async function mark(row,el,value) {
  await api('/api/reviewed',{pr:activePr.number,key:row.reviewKey,reviewed:value});row.reviewed=value;
  el.classList.toggle('reviewed',value);el.querySelector('.review-control input').checked=value;
  updateSummaryRow(row);filter();if(value)advance(el);
}
function attachActions(el,row) {
  const bar=document.createElement('div');bar.className='review-bar';el.append(bar);
  if(row.status!=='same'){
    const control=document.createElement('div');control.className='review-control';
    const label=document.createElement('label'),box=document.createElement('input'),status=document.createElement('span');
    box.type='checkbox';box.checked=row.reviewed;status.setAttribute('role','status');label.append(box,document.createTextNode('Reviewed'));control.append(label,status);bar.append(control);
    box.onchange=async()=>{const value=box.checked;if(value&&dirty()){box.checked=row.reviewed;status.textContent='Save or cancel the open note first.';return;}saving++;controls();box.disabled=true;status.textContent='Saving…';try{await mark(row,el,value);status.textContent='';}catch(e){box.checked=row.reviewed;status.textContent='Not saved: '+e.message;}finally{saving--;controls();box.disabled=false;}};
  }
  const area=document.createElement('div');area.className='note-area';bar.append(area);
  function view(){delete area.dataset.suggestionChanged;area.classList.remove('editing');area.classList.toggle('no-note',!notes[row.id]);area.replaceChildren();const button=document.createElement('button');button.textContent=notes[row.id]?'Edit note':'＋ Add note';button.onclick=edit;area.append(button);if(notes[row.id]){const text=document.createElement('div');text.className='note-text';text.setAttribute('role','note');text.setAttribute('aria-label','Saved review note');text.textContent=notes[row.id].text;appendSuggestion(text,notes[row.id]);area.append(text);}}
  function edit(){
    area.classList.add('editing');area.replaceChildren();const input=document.createElement('textarea');input.setAttribute('aria-label','Local review note');input.maxLength=20000;input.defaultValue=notes[row.id]?.text||'';input.value=input.defaultValue;
    const actions=document.createElement('div');actions.className='note-actions';const save=document.createElement('button'),cancel=document.createElement('button'),status=document.createElement('span');save.textContent='Save note';cancel.textContent='Cancel';status.setAttribute('role','status');
    cancel.onclick=async()=>{const edited=[...area.querySelectorAll('textarea')].some(field=>field.value!==field.defaultValue)||area.dataset.suggestionChanged==='true';if(!edited||await askDiscard())view();};
    let suggested=null;
    const suggestionPanel=document.createElement('div');suggestionPanel.className='suggestion-editor';
    const suggest=document.createElement('button');suggest.type='button';suggest.textContent=notes[row.id]?.suggestion?'Edit suggested change':'Suggest a change…';
    async function showSuggestion(replacement){
      suggest.disabled=true;save.disabled=true;status.textContent='Finding source lines…';
      try{
        const target=await api('/api/suggestion?'+new URLSearchParams({pr:activePr.number,left:activePr.left,right:activePr.right,path:reviewPath,block:row.id}));
        if(!area.contains(suggestionPanel))return;
        if(!target.available){status.textContent=target.reason;suggest.disabled=false;return;}
        const help=document.createElement('p');help.textContent='Suggested replacement · '+reviewPath+' · proposed lines '+target.startLine+'–'+target.line+'. Edit the source markup below; '+(window.WEB_REVIEW?'save this suggestion and use Finish review to submit it.':window.REVIEW_STATIC?'copy the suggestion into a GitHub inline comment when finishing your review.':'the PR author can apply it on GitHub.');
        const source=document.createElement('textarea');source.setAttribute('aria-label','Suggested source replacement');source.maxLength=20000;source.defaultValue=replacement??target.original;source.value=source.defaultValue;
        const remove=document.createElement('button');remove.type='button';remove.textContent='Remove suggestion';remove.onclick=()=>{suggested=null;suggestionPanel.replaceChildren();suggest.disabled=false;area.dataset.suggestionChanged='true';};
        suggested={input:source,target};suggestionPanel.replaceChildren(help,source,remove);area.dataset.suggestionChanged=notes[row.id]?.suggestion&&replacement===notes[row.id].suggestion.text?'false':'true';status.textContent='';source.focus();
      }catch(e){status.textContent='Could not open suggestion: '+e.message;suggest.disabled=false;}
      finally{save.disabled=false;}
    }
    suggest.onclick=()=>showSuggestion(notes[row.id]?.suggestion?.text);
    async function persist(text,clearSuggestion=false){
      saving++;controls();for(const button of actions.querySelectorAll('button'))button.disabled=true;status.textContent='Saving…';input.disabled=true;
      try{
        const payload={pr:activePr.number,review:reviewId,block:row.id,path:reviewPath,context:plain(row.right||row.left).slice(0,2000),versions:{left:activePr.left,right:activePr.right,base:activePr.base,head:activePr.head},text,suggestion:!clearSuggestion&&suggested?{text:suggested.input.value}:null};
        const result=await api('/api/notes',payload);if(text.trim()||payload.suggestion)notes[row.id]=result.note||payload;else delete notes[row.id];
        updateSummaryRow(row);view();
        if((text.trim()||payload.suggestion)&&row.reviewKey){try{await mark(row,el,true);}catch(e){const error=document.createElement('p');error.setAttribute('role','alert');error.textContent='Note saved, but could not mark reviewed: '+e.message;area.append(error);}}
      }catch(e){status.textContent='Not saved: '+e.message;input.disabled=false;for(const button of actions.querySelectorAll('button'))button.disabled=false;if(suggested)suggest.disabled=true;}finally{saving--;controls();}
    }
    save.onclick=()=>persist(input.value);actions.append(save,cancel,suggest);
    if(notes[row.id]){const remove=document.createElement('button');remove.textContent='Delete note';remove.onclick=()=>persist('',true);actions.append(remove);}
    actions.append(status);area.append(input,suggestionPanel,actions);input.focus();if(notes[row.id]?.suggestion)showSuggestion(notes[row.id].suggestion.text);
  }
  view();
}
function labels(){if(!activePr)return;for(const [side,label] of [['left',`${activePr.base} (common ancestor) · ${activePr.left.slice(0,8)}`],['right',`${activePr.head} · ${activePr.right.slice(0,8)}`]]){$(side+'Title').textContent=(side==='left'?'Base · ':'Proposed · ')+label;$(side+'Title').title=activePr[side];}}
async function compare(path,restoreKey=null){
  $('error').textContent='';$('status').textContent='Comparing…';
  const params=new URLSearchParams({left:activePr.left,right:activePr.right,path,pr:activePr.number});
  const data=await api('/api/compare?'+params), saved=await api('/api/notes?'+new URLSearchParams({pr:activePr.number,review:data.review}));
  reviewId=data.review;reviewPath=path;notes=saved.notes;noteRows=data.rows;$('path').value=path;$('prDoc').value=path;
  const doc=overview?.documents.find(doc=>doc.path===path);if(doc){for(const row of doc.changes){row.note=notes[row.id]||null;row.reviewed=noteRows.find(r=>r.reviewKey===row.reviewKey)?.reviewed||false;}}
  const fragment=document.createDocumentFragment(),counts={changed:0,added:0,removed:0};
  for(const row of noteRows){const el=document.createElement('div');el.className='row '+row.status;el.classList.toggle('reviewed',row.reviewed);el.dataset.status=row.status;el.dataset.key=row.reviewKey||row.id;for(const side of ['left','right']){const cell=document.createElement('div');cell.className='cell';cell.innerHTML=row[side];el.append(cell);}if(row.status!=='same'||notes[row.id])attachActions(el,row);fragment.append(el);if(row.status!=='same')counts[row.status]++;}
  $('rows').className='file-mode-'+data.mode;$('rows').replaceChildren(fragment);changes=[];current=-1;labels();$('summary').textContent=`${data.fileStatus==='deleted'?'Deleted file · ':data.fileStatus==='added'?'Added file · ':''}${data.mode==='image'?'Image comparison':data.mode==='binary'?'Binary comparison':counts.changed+counts.added+counts.removed?`${counts.changed} modified · ${counts.added} added · ${counts.removed} removed`:'No content differences'}`;filter(false);history.replaceState(null,'','?'+params);
  const index=restoreKey?changes.findIndex(el=>el.dataset.key===restoreKey):-1;
  if(index>=0)jump(index,false);else{remember();document.querySelector('main').scrollIntoView({behavior:'instant',block:'start'});}renderFeedback();
}
function clearReview(persist=false){feedback=null;feedbackLoading=false;feedbackRequest++;$('githubFeedback').hidden=true;reviewDraft={summary:{},files:{}};activePr=null;overview=null;reviewId='';reviewPath='';notes={};noteRows=[];changes=[];current=-1;$('pr').value='';$('prDoc').replaceChildren(new Option('Select a pull request first',''));$('leftTitle').textContent='Base';$('rightTitle').textContent='Proposed';$('rows').replaceChildren();$('summary').textContent='Select a pull request to begin';$('error').textContent='';filter(false);controls();if(persist){history.replaceState(null,'',location.pathname);remember();}}
function labelMatches(pr,label){return !label||(pr.labels||[]).includes(label);}
function renderPrList(){const selected=activePr?.number||$('pr').value;const filtered=prCatalog.filter(pr=>labelMatches(pr,selectedLabel));$('pr').replaceChildren(new Option(filtered.length?'Choose an open pull request…':'No PRs with this label',''));for(const pr of filtered)$('pr').add(new Option(`#${pr.number} · ${pr.title}`,pr.number));if(filtered.some(pr=>String(pr.number)===String(selected)))$('pr').value=selected;$('prInfo').textContent=`${filtered.length} of ${prCatalog.length} open PRs${selectedLabel?' · '+selectedLabel:''}`;}
async function loadPullRequests(force=false){if(force)$('githubStatus').textContent='';const data=await api('/api/prs'+(force?'?refresh=1':''));githubNotice(data.github);prCatalog=data.prs;const labels=[...new Set(prCatalog.flatMap(pr=>pr.labels||[]))].sort((a,b)=>a.localeCompare(b));$('prLabel').replaceChildren(new Option('All labels',''));for(const label of labels)$('prLabel').add(new Option(label,label));if(selectedLabel&&!labels.includes(selectedLabel))selectedLabel='';$('prLabel').value=selectedLabel;renderPrList();}
$('prLabel').onchange=async()=>{const label=$('prLabel').value;const hidesCurrent=activePr&&!labelMatches(prCatalog.find(pr=>pr.number===activePr.number)||{},label);if(hidesCurrent&&!await mayLeave()){$('prLabel').value=selectedLabel;return;}selectedLabel=label;if(hidesCurrent)clearReview(true);renderPrList();remember();};
async function selectPr(number,path='',restoreKey=null,force=false){
  if(!number){clearReview(true);return;}
  feedback=null;feedbackRequest++;feedbackLoading=false;$('githubFeedback').hidden=true;
  // Clear old content immediately so a failed load cannot be mistaken for the chosen PR.
  $('rows').replaceChildren();$('error').textContent='';$('prInfo').textContent='Loading PR #'+number+'…';overview=null;activePr=null;notes={};noteRows=[];changes=[];current=-1;$('summary').textContent='Loading PR #'+number+'…';filter(false);controls();
  $('fetchInfo').textContent=window.DESKTOP_REVIEW?'Opening PR #'+number+' · downloading history if needed…':$('fetchInfo').textContent;
  activePr=await api('/api/pr?number='+encodeURIComponent(number)+(force?'&refresh=1':''));activePr.canUndo=(await api('/api/reset-status?pr='+activePr.number)).canUndo;reviewDraft=await api('/api/draft?pr='+activePr.number);githubNotice(activePr.github);labels();
  overview=await api('/api/review-summary?'+new URLSearchParams({pr:activePr.number,left:activePr.left,right:activePr.right}));
  $('prInfo').textContent=`#${activePr.number} · ${activePr.files.length} changed files`;
  $('prDoc').replaceChildren();for(const file of activePr.files)$('prDoc').add(new Option(file,file));
  if(activePr.files.length)await compare(activePr.files.includes(path)?path:activePr.files[0],restoreKey);
  else{reviewPath='';notes={};noteRows=[];changes=[];current=-1;$('prDoc').add(new Option('No changed files',''));$('summary').textContent='This PR has no changed files';filter();}
  if(window.DESKTOP_REVIEW){$('repoUpdate').hidden=true;const cached=activePr.cache;if(cached)$('fetchInfo').textContent=(cached.offline?'Offline · downloaded ':'Downloaded ')+new Date(cached.downloadedAt*1000).toLocaleString();}
  loadFeedback();
  const errors=overview.documents.filter(doc=>doc.error);if(errors.length)$('error').textContent=`Could not render ${errors.length} file(s); PR review is incomplete. See the file selector or export for details.`;
}
$('pr').onchange=async()=>{
  const number=$('pr').value, previous=activePr?.number||'';
  if(!await mayLeave()){$('pr').value=previous;return;}
  busy=true;controls();try{await selectPr(number);}catch(e){$('error').textContent=e.message;$('status').textContent='PR could not be loaded';}finally{busy=false;controls();}
};
$('prDoc').onchange=async()=>{
  const path=$('prDoc').value;if(!await mayLeave()){$('prDoc').value=reviewPath;return;}
  busy=true;controls();try{await compare(path);}catch(e){$('error').textContent=e.message;$('prDoc').value=reviewPath;}finally{busy=false;controls();}
};
function snapshot(){return overview?.documents.flatMap(doc=>doc.changes.map(row=>({key:row.reviewKey,context:doc.path+'|'+row.heading,reviewed:row.reviewed})))||[];}
function updateMessage(before,after){
  const prior=new Map(before.map(row=>[row.key,row])),now=new Set(after.map(row=>row.key));
  const removed=before.filter(row=>!now.has(row.key)), affected=new Set(removed.filter(row=>row.reviewed).map(row=>row.context));
  const incoming=after.filter(row=>!prior.has(row.key)),recheck=incoming.filter(row=>!row.reviewed&&affected.has(row.context)).length;
  return `${incoming.length-recheck} new · ${after.filter(row=>row.reviewed).length} reviewed retained · ${recheck} need another look · ${removed.length} earlier changes replaced or removed`;
}
$('fetchLatest').onclick=async()=>{
  if(window.DESKTOP_REVIEW){await refreshDesktop();return;}
  if(!await mayLeave())return;const number=activePr?.number||'',path=reviewPath,block=changes[current]?.dataset.key,prior=snapshot();busy=true;controls();$('fetchInfo').textContent=window.REVIEW_STATIC?'Checking published comparisons…':'Fetching origin…';
  try{await api('/api/fetch',{});await loadPullRequests(true);if(number&&[...$('pr').options].some(option=>option.value===String(number))){$('pr').value=number;await selectPr(number,path,block);$('fetchInfo').textContent=(activePr.github?.stale?'Showing cached comparison. ':'')+updateMessage(prior,snapshot());}else{clearReview(true);$('fetchInfo').textContent=number?'Fetched latest. The selected PR is no longer open.':'Fetched latest. Choose a PR to begin.';}
    if(!window.REVIEW_STATIC&&activePr?.github?.stale)throw Error('Git fetch succeeded, but GitHub metadata is still cached. '+githubMessage(activePr.github.warning,activePr.github.retryAt));remembered.lastRefresh=new Date().toISOString();$('lastRefresh').textContent=window.REVIEW_STATIC?'Comparisons built: '+new Date((await api('/api/context')).builtAt).toLocaleString():'Last refreshed: '+new Date(remembered.lastRefresh).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});if(window.REVIEW_STATIC)$('fetchInfo').textContent+=' · Published snapshots; PR updates appear after the next build.';remember();
  }catch(e){$('fetchInfo').textContent='Refresh incomplete: '+e.message;}finally{busy=false;controls();}
};
function download(text,name,mime='text/markdown'){if(desktopBridge()){desktopBridge().postMessage({action:'save',text,name});return;}const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([text],{type:mime}));link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);}
function exportReview(){
  const draft=ReviewCore.normalizeDraft(reviewDraft);
  const commented=overview.documents.map(doc=>({...doc,changes:doc.changes.filter(row=>row.note?.text?.trim()||row.note?.suggestion)})).filter(doc=>doc.changes.length);
  const count=commented.reduce((total,doc)=>total+doc.changes.length,0);
  const lines=[`# PR #${activePr.number}: ${activePr.title} — Review notes`,'',`Base: ${activePr.base} (common ancestor) · ${activePr.left.slice(0,8)} (${activePr.left})`,`Proposed: ${activePr.head} · ${activePr.right.slice(0,8)} (${activePr.right})`,`${count} commented change${count===1?'':'s'}`,''];
  if(draft.summary?.text?.trim())lines.push('## PR summary','',draft.summary.text,'');
  if(!count&&!commented.length&&!draft.summary?.text?.trim())lines.push('No comments in the current PR comparison.');
  for(const doc of commented){lines.push('## '+doc.path,'');for(const row of doc.changes){lines.push(`### ${row.heading} (${row.status})`,'','Before:',...plain(row.left).split('\n').map(line=>'> '+line),'','After:',...plain(row.right).split('\n').map(line=>'> '+line),'','Note:',row.note.text,'',...(row.note.suggestion?['```suggestion',row.note.suggestion.text,'```','']:[]));}}
  download(lines.join('\n'),`pr-${activePr.number}-notes.md`);
}
function escapeHtml(value){return String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));}
function pdfHtml(pr,path,rows,savedNotes,draft={}){
  draft=ReviewCore.normalizeDraft(draft);
  const esc=escapeHtml,title=`PR ${pr.number} - ${path.split('/').pop().replace(/\.xml$/i,'')} - comparison`;
  const base=`Base: ${pr.base} (common ancestor) · ${pr.left.slice(0,8)}`,head=`Proposed: ${pr.head} · ${pr.right.slice(0,8)}`;
  const extraNotes=(draft.summary?.text?'<section class="saved-note"><strong>PR summary</strong><div>'+esc(draft.summary.text)+'</div></section>':'');
  const blocks=rows.map(row=>{const note=savedNotes[row.id];return `<tbody class="comparison-block ${esc(row.status)}"><tr><td>${row.left?.replace(/loading="lazy"/g,'loading="eager"')||'<span class="absent">—</span>'}</td><td>${row.right?.replace(/loading="lazy"/g,'loading="eager"')||'<span class="absent">—</span>'}</td></tr>${note?`<tr><td colspan="2" class="saved-note"><strong>Review note</strong><div>${esc(note.text)}</div>${note.suggestion?'<strong>Suggested source replacement</strong><pre>'+esc(note.suggestion.text)+'</pre>':''}</td></tr>`:''}</tbody>`;}).join('');
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${esc(title)}</title><style>
  @page{size:A4 landscape;margin:13mm 12mm}*{box-sizing:border-box}body{margin:24px;color:#24352f;font:11pt/1.5 Georgia,serif;background:white}.print-controls{display:flex;gap:16px;align-items:center;margin:0 0 24px;font:14px system-ui}.print-controls button{padding:10px 16px;background:#22644b;color:white;border:0;border-radius:5px;cursor:pointer}.print-controls p{margin:0;color:#617269}.report-title{font:600 22pt/1.2 system-ui;margin:0 0 8px}.report-meta{font:10pt/1.5 system-ui;overflow-wrap:anywhere;margin:0 0 18px}.report-meta p{margin:4px 0}table.comparison{border-collapse:collapse;table-layout:fixed;width:100%}.comparison>thead{display:table-header-group}.comparison>thead>tr>th{width:50%;text-align:left;padding:8px 12px;background:#eaf0eb;border:1px solid #ccd8ce;font:600 10pt/1.5 system-ui;overflow-wrap:anywhere}.comparison-block{break-inside:avoid;page-break-inside:avoid}.comparison-block>tr>td{width:50%;vertical-align:top;padding:5px 12px;border-left:1px solid #d9e1dc;border-right:1px solid #d9e1dc;overflow-wrap:anywhere}.comparison-block.changed>tr>td{border-left:2px solid #d5ad55}.comparison-block.added>tr>td:last-child{background:#f0faf2}.comparison-block.removed>tr>td:first-child{background:#fff5f1}.comparison-block>tr>td.saved-note{background:#f2f6f1;border:1px solid #ccd8ce;font:10pt/1.5 system-ui;padding:8px 12px}.saved-note div{white-space:pre-wrap}h1,h2,h3,h4,h5{font-family:system-ui;line-height:1.3;color:#1c4738;break-after:avoid;margin:14px 0 8px}h1{font-size:20pt}h2{font-size:17pt}h3{font-size:14pt}h4,h5{font-size:12pt}p{margin:5px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f4f2;padding:8px;font:8pt/1.45 monospace}code{font:8pt monospace;background:#f0f3f0}.image-comparison{margin:8px 0}.image-comparison img{display:block;max-width:100%;height:auto;max-height:160mm;object-fit:contain}.image-comparison figcaption{font:8pt/1.5 system-ui;overflow-wrap:anywhere}.binary-info{font:10pt/1.6 system-ui;overflow-wrap:anywhere}.docbook-variablelist dt{font-weight:bold;margin:8px 0 3px}.docbook-variablelist dd{margin:0 0 10px 14px;padding-left:8px;border-left:2px solid #dce7df}.docbook-table th{border:1px solid #ccd8ce;padding:5px;text-align:left}.docbook-table caption{text-align:left;font-weight:bold}.docbook-image{max-width:100%;height:auto;max-height:145mm;object-fit:contain}.docbook-image.inline-image{max-height:1.5em;vertical-align:middle}.docbook-figure{margin:10px 0}.docbook-figure figcaption{font:9pt system-ui}td table{table-layout:fixed;border-collapse:collapse;width:100%;font-size:9pt}td table td{border:1px solid #ccd8ce;padding:5px;vertical-align:top;overflow-wrap:anywhere}td table thead{background:#eaf0eb;font-weight:bold}del{background:#ffd6ce;color:#8c3025;text-decoration:line-through}ins{background:#c6ebce;color:#17592b;text-decoration:underline}.absent{color:#8a978f}.xref,a{color:#286951}.image-note{color:#728176;font-style:italic}ul,ol{padding-left:20px}thead,td,ins,del{-webkit-print-color-adjust:exact;print-color-adjust:exact}@media print{body{margin:0;font-size:9pt}.print-controls{display:none}a{color:inherit;text-decoration:none}.report-title{font-size:17pt}}
  </style></head><body><div class="print-controls"><button id="printNow">Print / Save as PDF</button><button id="printBack">Back to review</button><p>Choose Save as PDF in the print dialog. Landscape layout · full selected file · saved notes included.</p></div><h1 class="report-title">PR #${esc(pr.number)}: ${esc(pr.title)}</h1><div class="report-meta"><p><strong>File:</strong> ${esc(path)}</p><p><strong>Base commit:</strong> ${esc(pr.left)}<br><strong>Proposed commit:</strong> ${esc(pr.right)}</p><p>Red strike-through = removed. Green underline = added. All content is included regardless of the review filters.</p></div>${extraNotes}<table class="comparison"><thead><tr><th>${esc(base)}</th><th>${esc(head)}</th></tr></thead>${blocks}</table></body></html>`;
}
$('exportPdf').onclick=()=>{
  if(!activePr||!noteRows.length)return;
  if(dirty()||saving){$('error').textContent='Save or cancel the open note before exporting the PDF.';return;}
  const key=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
  try{const snapshot={pr:activePr,path:reviewPath,rows:noteRows,notes,draft:reviewDraft};sessionStorage.setItem('xml-review-print:'+key,JSON.stringify(snapshot));for(const old of Object.keys(sessionStorage).filter(key=>key.startsWith('xml-review-print:')))if(old!=='xml-review-print:'+key)sessionStorage.removeItem(old);location.assign(location.pathname+'?print='+key);}catch(e){$('error').textContent='Could not open the print view: '+e.message;}
};
$('exportNotes').onclick=()=>{if(overview)exportReview();};
function editDraftNote(){if(!activePr||saving||busy)return;const dialog=$('draftNoteDialog'),input=$('draftNoteText'),record=reviewDraft.summary;$('draftNoteTitle').textContent='PR #'+activePr.number+' summary';$('draftNoteHelp').textContent='Overall feedback for this PR. For feedback about a whole file, include its filename here. Saved locally until you submit the review.';input.defaultValue=record?.text||'';input.value=input.defaultValue;$('draftNoteStatus').textContent='';$('deleteDraftNote').hidden=!record?.text;input.setAttribute('aria-label','PR summary');let editing=false;const close=async()=>{if(editing)return;if(input.value!==input.defaultValue&&!await askDiscard())return;input.value=input.defaultValue='';dialog.close();};$('cancelDraftNote').onclick=close;dialog.oncancel=event=>{event.preventDefault();close();};async function persist(text){editing=true;saving++;controls();for(const id of ['saveDraftNote','cancelDraftNote','deleteDraftNote'])$(id).disabled=true;input.disabled=true;$('draftNoteStatus').textContent='Saving…';try{const result=await api('/api/draft',{pr:activePr.number,scope:'summary',text,versions:{left:activePr.left,right:activePr.right,base:activePr.base,head:activePr.head}});reviewDraft=result.draft;input.value=input.defaultValue='';dialog.close();progress();if($('notesDialog').open)$('noteHistory').onclick();}catch(e){$('draftNoteStatus').textContent='Not saved: '+e.message;}finally{editing=false;saving--;controls();input.disabled=false;for(const id of ['saveDraftNote','cancelDraftNote','deleteDraftNote'])$(id).disabled=false;}}$('saveDraftNote').onclick=()=>persist(input.value);$('deleteDraftNote').onclick=()=>persist('');dialog.showModal();input.focus();}
$('prSummary').onclick=()=>editDraftNote();
function copyText(text,status){if(desktopBridge()){desktopBridge().postMessage({action:'copy',text});status.textContent='Copied.';return Promise.resolve();}return navigator.clipboard.writeText(text).then(()=>{status.textContent='Copied. Paste into GitHub, then submit there.';}).catch(()=>{status.textContent='Clipboard unavailable. Select the preview text to copy, or export the Markdown file.';});}
function previewCopyControls(){$('copyReview').disabled=!preparedReview;$('downloadPreview').disabled=!preparedReview;$('openReviewGithub').hidden=!preparedReview;}
$('previewReview').onclick=async()=>{if(!activePr||busy||saving)return;if(dirty()){$('error').textContent='Save or cancel the open note before previewing the review.';return;}const dialog=$('reviewPreview');preparedReview=null;$('previewContents').textContent='Preparing saved notes…';$('previewDestination').textContent='';$('previewStatus').textContent='';previewCopyControls();dialog.showModal();try{const data=await api('/api/review-preview',{pr:activePr.number,left:activePr.left,right:activePr.right});preparedReview=data;$('previewDestination').textContent=`PR #${data.pr} · ${data.repo} · reviewed commit ${data.right.slice(0,8)} · ${data.files.length} file / chunk notes`;
const root=$('previewContents');root.replaceChildren();const heading=document.createElement('h3');heading.textContent='PR review summary';const summary=document.createElement('pre');summary.textContent=data.displayBody||data.body;root.append(heading,summary);for(const file of data.files){const title=document.createElement('h3');title.textContent=file.path+' · '+file.heading;const location=document.createElement('p');location.textContent=file.location;location.hidden=file.kind==='file';const text=document.createElement('pre');text.textContent=file.displayBody||file.body;const actions=document.createElement('div');actions.className='note-actions';const copy=document.createElement('button');copy.textContent='Copy comment';copy.onclick=()=>copyText(file.displayBody||file.body,$('previewStatus'));const link=document.createElement('a');link.textContent='Open GitHub location';link.href=file.url;link.target='_blank';link.rel='noreferrer';actions.append(copy,link);root.append(title,location,text,actions);}$('openReviewGithub').href=data.url+'/files';if(data.incomplete.length)$('previewStatus').textContent='Some files could not be rendered: '+data.incomplete.join(', ');previewCopyControls();}catch(e){$('previewContents').textContent=e.message;}};
$('closePreview').onclick=()=>$('reviewPreview').close();
$('copyReview').onclick=()=>{if(preparedReview)copyText(preparedReview.markdown,$('previewStatus'));};
$('downloadPreview').onclick=()=>{if(preparedReview)download(preparedReview.markdown,`pr-${preparedReview.pr}-review-preview.md`);};
function confirmReviewReset(undo){return new Promise(resolve=>{const dialog=$('resetDialog');$('resetTitle').textContent=undo?'Undo reset / import for PR #'+activePr.number+'?':'Reset review for PR #'+activePr.number+'?';$('resetDescription').textContent=undo?'Restore notes and Reviewed marks from before the last reset or import. This replaces any notes or marks added since then.':"Clear the PR summary, change notes, and Reviewed marks for this PR, across all documents and saved revisions, including any open draft. Other PRs are unaffected. You can undo the most recent reset.";$('confirmReset').textContent=undo?'Undo reset / import':'Reset review';let done=false;const finish=value=>{if(done)return;done=true;dialog.close();resolve(value);};$('cancelReset').onclick=()=>finish(false);$('confirmReset').onclick=()=>finish(true);dialog.oncancel=event=>{event.preventDefault();finish(false);};dialog.showModal();$('cancelReset').focus();});}
async function resetCurrentReview(undo=false){if(!activePr||busy||saving)return;if(!await confirmReviewReset(undo))return;busy=true;controls();$('error').textContent='';try{const result=await api(undo?'/api/undo-reset':'/api/reset',{pr:activePr.number});activePr.canUndo=result.canUndo;historyNotes={};reviewDraft=await api('/api/draft?pr='+activePr.number);overview=await api('/api/review-summary?'+new URLSearchParams({pr:activePr.number,left:activePr.left,right:activePr.right}));if(reviewPath)await compare(reviewPath);else{notes={};noteRows=[];filter();}$('fetchInfo').textContent=undo?'Previous review restored.':'Notes and Reviewed marks cleared for PR #'+activePr.number+'.';}catch(e){$('error').textContent='Could not '+(undo?'undo reset':'reset review')+': '+e.message;}finally{busy=false;controls();}}
$('resetReview').onclick=()=>resetCurrentReview();$('undoReset').onclick=()=>resetCurrentReview(true);
$('noteHistory').onclick=async()=>{
  if(!$('notesDialog').open)$('notesDialog').showModal();noteActions.append($('prSummary'));$('historyList').textContent='Loading…';
  try{const data=await api('/api/note-history'+(activePr?'?pr='+activePr.number:''));historyNotes=data.reviews;const root=$('historyList');
    // Keep the shared controls mounted while replacing the list.
    noteActions.append($('prSummary'));root.replaceChildren();
    reviewDraft=await api('/api/draft?pr='+activePr.number);progress();
    const section=document.createElement('section'),head=document.createElement('div'),heading=document.createElement('h3'),text=document.createElement('div'),edit=$('prSummary');
    head.className='saved-note-heading';heading.textContent='PR summary';edit.textContent=reviewDraft.summary?.text?'Edit summary':'Add summary';edit.setAttribute('aria-label',edit.textContent);edit.onclick=()=>editDraftNote();
    text.className='note-text';text.textContent=reviewDraft.summary?.text||'No PR summary yet.';head.append(heading,edit);section.append(head,text);root.append(section);
    for(const [id,blocks] of Object.entries(historyNotes)){if(!Object.keys(blocks).length)continue;const section=document.createElement('section'),title=document.createElement('h3');title.textContent=(activePr?'PR #'+activePr.number+' · ':'')+(id===reviewId?'Current comparison':'Earlier comparison · '+id.slice(0,8));section.append(title);for(const note of Object.values(blocks)){const meta=document.createElement('p');meta.textContent=note.path+' · '+(note.versions?.left?.slice(0,8)||'unknown base')+' → '+(note.versions?.right?.slice(0,8)||'unknown revision');const quote=document.createElement('blockquote');quote.textContent=note.context;const text=document.createElement('div');text.className='note-text';text.textContent=note.text;appendSuggestion(text,note);section.append(meta,quote,text);}root.append(section);}
    if(!root.children.length)root.textContent=activePr?'No saved notes for PR #'+activePr.number+'.':'Select a PR to see its saved notes.';
  }catch(e){$('historyList').textContent=e.message;}
};
$('closeNotes').onclick=()=>$('notesDialog').close();
for(const id of ['only','hideReviewed'])$(id).onchange=()=>{if(dirty()&&$('hideReviewed').checked){$('hideReviewed').checked=false;$('error').textContent='Save or cancel the open note before hiding reviewed changes.';}filter();};
$('home').onclick=()=>document.querySelector('header').scrollIntoView({behavior:'smooth',block:'start'});
$('reviewNext').onclick=async()=>{if(current<0||!changes[current])return;if(dirty()){$('error').textContent='Save or cancel your note first; saving it also marks the change reviewed.';return;}const el=changes[current],row=noteRows.find(row=>row.reviewKey===el.dataset.key);if(!row)return;saving++;controls();try{await mark(row,el,true);}catch(e){$('error').textContent='Could not save reviewed mark: '+e.message;}finally{saving--;controls();}};
$('first').onclick=()=>jump(0);$('last').onclick=()=>jump(changes.length-1);$('next').onclick=()=>move(1);$('prev').onclick=()=>move(-1);
$('resumeReview').onclick=async()=>{if(!await mayLeave())return;busy=true;controls();try{await resumeReview();}catch(e){$('error').textContent=e.message;}finally{busy=false;controls();}};
$('backupReview').onclick=async()=>{if(!activePr||!await mayLeave())return;busy=true;controls();try{const backup=await api('/api/backup?pr='+activePr.number);download(JSON.stringify(backup,null,2),`pr-${activePr.number}-review-backup.json`,'application/json');}catch(e){$('error').textContent=e.message;}finally{busy=false;controls();}};
$('importReview').onclick=async()=>{if(activePr&&await mayLeave()){$('backupFile').value='';$('backupFile').click();}};
$('backupFile').onchange=async()=>{
  const file=$('backupFile').files[0];if(!file||!activePr)return;
  busy=true;controls();try{
    if(file.size>10*1024*1024)throw Error('Backup must be at most 10 MB.');
    const backup=JSON.parse(await file.text());const pr=activePr.number;
    const counts=await api('/api/import-backup',{pr,backup});pendingImport={pr,backup};
    $('importDescription').textContent=`PR #${counts.pr}: ${counts.notes} change notes, ${counts.summary||counts.fileNotes?'a PR summary':'no PR summary'}, and ${counts.reviewed} reviewed marks. Backup created: ${backup.exportedAt||'unknown'}.`;
    $('importStatus').textContent='';$('importDialog').showModal();
  }catch(e){pendingImport=null;$('error').textContent='Import failed: '+e.message;}finally{busy=false;controls();}
};
$('cancelImport').onclick=()=>{pendingImport=null;$('importDialog').close();};
$('importDialog').oncancel=event=>{if(saving)event.preventDefault();else pendingImport=null;};
$('confirmImport').onclick=async()=>{
  if(!pendingImport||saving)return;saving++;controls();$('confirmImport').disabled=true;$('cancelImport').disabled=true;$('importStatus').textContent='Importing…';
  try{await api('/api/import-backup',{...pendingImport,confirm:true});const pr=pendingImport.pr;pendingImport=null;$('importDialog').close();await selectPr(pr);}
  catch(e){$('importStatus').textContent='Import failed: '+e.message;$('error').textContent='Import failed: '+e.message;}
  finally{saving--;controls();$('confirmImport').disabled=false;$('cancelImport').disabled=false;}
};
function feedbackGroups(data,path){return {file:(data?.items||[]).filter(item=>item.kind==='file'&&item.path===path),pr:(data?.items||[]).filter(item=>item.kind!=='file')};}
function renderFeedback(){
  const panel=$('githubFeedback');panel.hidden=!activePr;if(!activePr)return;
  const groups=feedbackGroups(feedback,reviewPath),root=$('feedbackList');root.replaceChildren();
  $('feedbackTitle').textContent=`GitHub feedback · ${groups.file.length} for this file · ${groups.pr.length} PR comments / reviews`;
  $('refreshFeedback').disabled=feedbackLoading||busy||saving>0;
  $('feedbackStatus').textContent=feedbackLoading?'Loading GitHub feedback…':feedback?(feedback.warnings.length?'Feedback may be incomplete: '+feedback.warnings.join('; '):feedback.cached?'Cached feedback':'Feedback loaded')+(feedback.fetchedAt?' · '+new Date(feedback.fetchedAt*1000).toLocaleString():''):'';
  for(const [title,items] of [['This file',groups.file],['PR discussion and reviews',groups.pr]]){
    const heading=document.createElement('h3');heading.textContent=title;root.append(heading);
    if(!items.length){const empty=document.createElement('p');empty.textContent=feedbackLoading?'Loading…':feedback?.warnings.length?'Feedback unavailable or incomplete.':'No feedback.';root.append(empty);}
    for(const item of items){const article=document.createElement('article'),meta=document.createElement('strong'),text=document.createElement('pre');
      meta.textContent=item.author+(item.state?' · '+item.state.replaceAll('_',' ').toLowerCase():'')+(item.line?' · '+(item.side==='LEFT'?'base':'proposed')+' line '+item.line:item.originalLine?' · original line '+item.originalLine:'')+(item.outdated?' · outdated location':'')+(item.replyTo?' · reply to #'+item.replyTo:'')+(item.created?' · '+new Date(item.created).toLocaleString():'');
      text.textContent=item.body||'(Review submitted without a summary.)';article.append(meta,text);
      if(/^https:\/\/github\.com\//.test(item.url)){const link=document.createElement('a');link.href=item.url;link.target='_blank';link.rel='noreferrer';link.textContent='View on GitHub';article.append(link);}root.append(article);
    }
  }
}
async function loadFeedback(force=false){
  if(!activePr)return;const pr=activePr.number,request=++feedbackRequest;feedbackLoading=true;renderFeedback();
  try{const result=await api('/api/feedback?'+new URLSearchParams({pr,refresh:force?'1':'0'}));if(request===feedbackRequest&&activePr?.number===pr)feedback=result;}
  catch(e){if(request===feedbackRequest&&activePr?.number===pr)feedback={items:feedback?.items||[],warnings:[e.message]};}
  finally{if(request===feedbackRequest&&activePr?.number===pr){feedbackLoading=false;renderFeedback();}}
}
$('refreshFeedback').onclick=()=>loadFeedback(true);
$('showFeedback').onclick=()=>{$('githubFeedback').open=true;$('githubFeedback').scrollIntoView({block:'start',behavior:'instant'});};
const prStatus=document.createElement('div');prStatus.className='pr-status';for(const id of ['prInfo','lastRefresh','fetchInfo','githubStatus'])prStatus.append($(id));document.querySelector('.pr-controls').append(prStatus);
// Two compact rows; secondary actions live in a disclosure menu.
const toolbar=document.querySelector('.toolbar');
for(const [className,ids] of [['toolbar-nav',['home','first','prev','reviewNext','next','last','status']],['toolbar-meta',['only','hideReviewed','reviewProgress','prProgress']]]){const group=document.createElement('div');group.className=className;for(const id of ids){const el=$(id);group.append(el.type==='checkbox'?el.parentElement:el);}toolbar.append(group);}
const more=document.createElement('details');more.className='toolbar-more';more.id='reviewOptions';
const moreLabel=document.createElement('summary');moreLabel.textContent='More ⋯';moreLabel.setAttribute('aria-label','Review options');
const menu=document.createElement('div');menu.className='toolbar-menu';for(const id of ['summary','noteCount','resumeReview','backupReview','importReview','showFeedback','prSummary','previewReview','noteHistory','exportNotes','exportPdf','resetReview','undoReset','legend'])menu.append($(id));more.append(moreLabel,menu);document.querySelector('.toolbar-nav').append(more);more.addEventListener('toggle',()=>{if(more.open)menu.style.maxHeight=Math.max(120,innerHeight-moreLabel.getBoundingClientRect().bottom-20)+'px';});
for(const id of ['resumeReview','backupReview','importReview','showFeedback','prSummary','previewReview','noteHistory','exportNotes','exportPdf','resetReview','undoReset'])$(id).addEventListener('click',()=>{more.open=false;});
document.addEventListener('click',event=>{if(!more.contains(event.target))more.open=false;});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&more.open){more.open=false;moreLabel.focus();}});
(async()=>{
  const printKey=new URLSearchParams(location.search).get('print');
  if(printKey){toolbarObserver.disconnect();try{const snapshot=JSON.parse(sessionStorage.getItem('xml-review-print:'+printKey)||'null');if(!snapshot)throw Error('Print view expired. Return to the review and export again.');document.open();document.write(pdfHtml(snapshot.pr,snapshot.path,snapshot.rows,snapshot.notes,snapshot.draft));document.close();document.getElementById('printNow').onclick=()=>desktopBridge()?desktopBridge().postMessage({action:'print'}):window.print();document.getElementById('printBack').onclick=()=>history.back();}catch(e){document.body.textContent=e.message;const back=document.createElement('a');back.href=location.pathname;back.textContent=' Back to review';document.body.append(back);}return;}
  busy=true;clearReview();controls();
  try{const context=await api('/api/context');if(context.desktop){window.DESKTOP_REVIEW=true;setupRepositoryPicker(context);window.DESKTOP_PREFERENCES=context.preferences||{};document.body.classList.add('desktop');document.querySelector('header p').textContent='Review changes. Keep notes. Submit to GitHub.';}if(context.webAuth){window.WEB_REVIEW=true;document.body.classList.add('web-review');setupWebReview();}if(context.static){$('fetchLatest').textContent='Check for updates';$('lastRefresh').textContent='Comparisons built: '+new Date(context.builtAt).toLocaleString();document.querySelector('header p').textContent='Review public PRs. Notes are saved in this browser; back them up to keep a copy.';}storageKey='xml-review-v1:'+context.id;remembered=readStored();selectedLabel=remembered.label||'';$('only').checked=!!remembered.only;$('hideReviewed').checked=!!remembered.hideReviewed;
    if(!window.REVIEW_STATIC&&remembered.lastRefresh)$('lastRefresh').textContent='Last refreshed: '+new Date(remembered.lastRefresh).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
    const q=new URLSearchParams(location.search),number=q.has('pr')?q.get('pr'):remembered.pr,path=q.get('path')||remembered.path;
    const restoreKey=String(number)===String(remembered.pr)&&path===remembered.path?remembered.block:null;
    await loadPullRequests(!!context.desktop);if(context.migration?.copied)$('fetchInfo').textContent='Copied '+context.migration.copied+' existing review files into app storage.';if(context.migration?.warnings?.length){const warning=document.createElement('p');warning.setAttribute('role','alert');warning.style.color='#963c30';warning.textContent=context.migration.warnings.join(' ');document.querySelector('.pr-status').append(warning);}if(number){if(prCatalog.some(pr=>String(pr.number)===String(number))&&![...$('pr').options].some(option=>option.value===String(number))){selectedLabel='';$('prLabel').value='';renderPrList();}$('pr').value=number;if($('pr').value)await selectPr(number,path);else $('prInfo').textContent='The previous PR is no longer open. Choose another PR.';}
  }catch(e){$('error').textContent=e.message;}finally{busy=false;controls();}
  if(window.WEB_REVIEW&&new URLSearchParams(location.search).get('finish')==='1'){
    const next=new URL(location.href);next.searchParams.delete('finish');history.replaceState(null,'',next);$('previewReview').click();
  }
})();

// Keep frequent review actions visible; maintenance belongs in its own dialog.
function actionDialog(id,title,buttons){
 const dialog=document.createElement('dialog');dialog.id=id;
 const head=document.createElement('div');head.className='dialog-head';
 const heading=document.createElement('h2');heading.textContent=title;
 const close=document.createElement('button');close.textContent='Close';close.onclick=()=>dialog.close();head.append(heading,close);dialog.append(head);
 const actions=document.createElement('div');actions.className='dialog-actions';
 for(const name of buttons)actions.append($(name));dialog.append(actions);document.body.append(dialog);return dialog;
}
const exportDialog=actionDialog('exportDialog','Export review',['exportNotes','exportPdf']);
const dataDialog=actionDialog('reviewDataDialog','Local review data',['backupReview','importReview','resetReview','undoReset']);
const help=document.createElement('p');help.textContent='Backups include notes and reviewed marks. Nothing here changes GitHub.';dataDialog.insertBefore(help,dataDialog.lastChild);
const noteActions=document.createElement('div');noteActions.className='note-actions';noteActions.hidden=true;noteActions.append($('prSummary'));$('notesDialog').insertBefore(noteActions,$('historyList'));
$('noteHistory').textContent='Notes';$('previewReview').textContent='Finish review…';$('reviewPreview').querySelector('h2').textContent='Finish review';
const meta=document.querySelector('.toolbar-meta');meta.append($('noteHistory'),$('previewReview'));
const compactMenu=document.querySelector('.toolbar-menu');
const exportAction=document.createElement('button');exportAction.textContent='Export…';exportAction.onclick=()=>{more.open=false;exportDialog.showModal();};
const dataAction=document.createElement('button');dataAction.textContent='Backup & restore…';dataAction.onclick=()=>{more.open=false;dataDialog.showModal();};
toolbar.append($('summary'),$('noteCount'),$('legend'));
compactMenu.replaceChildren($('resumeReview'),$('showFeedback'),exportAction,dataAction);
$('summary').hidden=true;$('noteCount').hidden=true;$('legend').hidden=true;
// Retain status elements for existing progress updates without a large menu.
toolbar.append($('summary'),$('noteCount'),$('legend'));
const oldPreview=$('previewReview').onclick;
$('previewReview').onclick=async()=>{$('webReviewActions')?.remove();await oldPreview();if(window.DESKTOP_REVIEW&&preparedReview)await desktopPreview();else if(window.WEB_REVIEW&&preparedReview)await webPreview();};
function renderLoginStatus(status,message){
 const url='https://github.com/login/device';
 const index=message.indexOf(url);
 if(index<0){status.textContent=message;return;}
 const link=document.createElement('a');link.href=url;link.textContent=url;link.target='_blank';link.rel='noopener noreferrer';
 status.replaceChildren(document.createTextNode(message.slice(0,index)),link,document.createTextNode(message.slice(index+url.length)));
 const code=message.match(/\b[A-Z0-9]{4}-[A-Z0-9]{4}\b/)?.[0];
 if(code){
  const copy=document.createElement('button');copy.type='button';copy.textContent='Copy code';copy.setAttribute('aria-label','Copy GitHub sign-in code');copy.style.marginLeft='10px';copy.style.padding='6px 10px';
  const feedback=document.createElement('span');feedback.setAttribute('role','status');feedback.style.marginLeft='8px';
  copy.onclick=async()=>{try{if(desktopBridge())desktopBridge().postMessage({action:'copy',text:code});else await navigator.clipboard.writeText(code);feedback.textContent='Code copied';}catch{feedback.textContent='Could not copy. Select the code and copy it manually.';}};
  status.append(copy,feedback);
 }
}
async function desktopPreview(){
 let box=$('desktopSubmit');if(!box){box=document.createElement('section');box.id='desktopSubmit';$('previewStatus').before(box);}
 box.replaceChildren();box.textContent='Checking GitHub sign-in…';
 let auth;try{auth=await api('/api/desktop/auth');}catch(e){box.textContent='Could not check GitHub sign-in: '+e.message;return;}box.replaceChildren();const status=document.createElement('p');status.textContent=auth.login?'Signed in as '+auth.login:'Sign in with GitHub to submit directly. GitHub CLI permissions may cover other repositories; this app submits only to the selected repository.';box.append(status);
 if(!auth.login){if(auth.message)renderLoginStatus(status,auth.message);const login=document.createElement('button');login.textContent='Sign in with GitHub…';login.onclick=async()=>{login.disabled=true;try{const result=await api('/api/desktop/login',{});renderLoginStatus(status,result.message);const timer=setInterval(async()=>{if(!$('reviewPreview').open){clearInterval(timer);return;}const state=await api('/api/desktop/auth');if(state.message)renderLoginStatus(status,state.message);if(state.login){clearInterval(timer);desktopPreview();}},2500);}catch(e){status.textContent=e.message;login.disabled=false;}};box.append(login);return;}
 const label=document.createElement('label');label.className='submit-confirm';const check=document.createElement('input');check.type='checkbox';label.append(check,document.createTextNode('Post this summary and these comments to '+preparedReview.repo+' PR #'+preparedReview.pr+'.'));
 const submit=document.createElement('button');submit.className='primary';submit.textContent='Submit review to GitHub';submit.disabled=true;check.onchange=()=>submit.disabled=!check.checked;
 submit.onclick=async()=>{submit.disabled=true;check.disabled=true;$('closePreview').disabled=true;status.textContent='Submitting review…';try{const result=await api('/api/desktop/submit',{pr:preparedReview.pr,left:preparedReview.left,right:preparedReview.right,id:preparedReview.id,confirm:true});status.textContent='Review submitted.';const link=document.createElement('a');link.href=result.url;link.target='_blank';link.textContent='View on GitHub';box.append(link);}catch(e){status.textContent=e.message;}finally{$('closePreview').disabled=false;}};box.append(label,submit);
}

// Checking GitHub never replaces an open comparison. Loading updates is explicit.
const repoUpdate=document.createElement('section');repoUpdate.id='repoUpdate';repoUpdate.hidden=true;repoUpdate.setAttribute('role','status');
const updateText=document.createElement('span'),loadUpdate=document.createElement('button');loadUpdate.textContent='Load updated version';repoUpdate.append(updateText,loadUpdate);document.querySelector('main').before(repoUpdate);
async function checkDesktopUpdate(){
 if(!activePr)return;
 const number=activePr.number,right=activePr.right;
 const result=await api('/api/desktop/update?'+new URLSearchParams({pr:number,right}));
 if(activePr?.number!==number||activePr?.right!==right)return;
 githubNotice(result.github);
 if(result.available||result.closed){updateText.textContent=result.closed?'This PR is now closed on GitHub. You can continue reviewing this downloaded version.':result.message;loadUpdate.hidden=!!result.closed;repoUpdate.hidden=false;}
 else{$('fetchInfo').textContent=result.message?.startsWith('Could not')?result.message:'Up to date · checked '+new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});repoUpdate.hidden=true;}
}
async function refreshDesktop(){
 if(busy||saving)return;busy=true;controls();$('fetchInfo').textContent='Checking GitHub for updates…';
 try{await loadPullRequests(true);if(activePr)await checkDesktopUpdate();else $('fetchInfo').textContent='PR list refreshed. Choose a PR to download.';}
 catch(e){$('fetchInfo').textContent='Could not refresh GitHub: '+e.message+'. Downloaded reviews remain available.';}
 finally{busy=false;controls();}
}
loadUpdate.onclick=async()=>{
 if(!activePr||busy||saving||!await mayLeave())return;
 const number=activePr.number,path=reviewPath,prior=snapshot(),block=changes[current]?.dataset.key;
 busy=true;controls();loadUpdate.disabled=true;
 try{await selectPr(number,path,block,true);$('fetchInfo').textContent=(activePr.github?.stale?'Using downloaded revision. ':'')+updateMessage(prior,snapshot());}
 catch(e){$('error').textContent='Could not load the update: '+e.message;}
 finally{busy=false;controls();loadUpdate.disabled=false;}
};
setInterval(async()=>{
 if(!window.DESKTOP_REVIEW)return;
 try{const status=await api('/api/desktop/status');if(status.busy)$('fetchInfo').textContent=status.message;}catch{/* Startup/restart: the current comparison remains visible. */}
},1500);
setInterval(()=>{if(window.DESKTOP_REVIEW&&activePr&&!busy&&!saving&&!document.hidden)checkDesktopUpdate().catch(()=>{});},300000);

function setupRepositoryPicker(context){
 const label=document.createElement('label');label.id='repositoryControl';label.append(document.createTextNode('Repository'));
 const select=document.createElement('select');select.setAttribute('aria-label','Review repository');
 for(const repo of context.repositories||[context.repo])select.add(new Option(repo==='videoai/test-specs'?repo+' · playground':repo,repo));select.value=context.repo;
 label.append(select);const container=document.createElement('div');container.className='repository-controls';container.append(label);document.querySelector('.pr-controls').before(container);
 select.onchange=async()=>{const selected=select.value;if(busy||saving||!await mayLeave()){select.value=context.repo;return;}if(!desktopBridge()){select.value=context.repo;return;}
  busy=true;controls();select.disabled=true;$('fetchInfo').textContent='Opening '+selected+'…';desktopBridge().postMessage({action:'repository',text:selected});};
}

function appendSuggestion(root,note){
 if(!note.suggestion)return;
 const label=document.createElement('strong');label.textContent='Suggested source replacement';
 const source=document.createElement('pre');source.textContent=note.suggestion.text||'(Delete these source lines)';root.append(label,source);
}

// The hosted test viewer uses same-origin, HttpOnly sessions. GitHub tokens never enter JavaScript.
async function webSignIn(finish=false){
 if(!await mayLeave())return;const query=new URLSearchParams(location.search);if(finish)query.set('finish','1');
 location.assign('/auth/login?return='+encodeURIComponent('/?'+query));
}

async function setupWebReview(){
 const bar=document.createElement('section');bar.className='repository-controls';bar.setAttribute('aria-label','Test GitHub connection');
 const status=document.createElement('span'),signIn=document.createElement('button'),signOut=document.createElement('button');
 signIn.textContent='Sign in with GitHub';signOut.textContent='Sign out';signOut.hidden=true;
 bar.append(status,signIn,signOut);document.querySelector('.pr-controls').before(bar);
 signIn.onclick=()=>webSignIn();
 signOut.onclick=async()=>{try{await api('/api/web/logout',{});await update();}catch(e){status.textContent=e.message;}};
 async function update(){try{const auth=await api('/api/web/auth');status.textContent=auth.signedIn?'Test repository · signed in as '+auth.login+' ':auth.configured?'Test repository · videoai/test-specs ':'Test GitHub connection is being configured. ';signIn.hidden=auth.signedIn;signIn.disabled=!auth.configured;signOut.hidden=!auth.signedIn;}catch(e){status.textContent=e.message;signIn.disabled=true;}}
 await update();
}
async function webPreview(){
 const root=$('previewContents');$('webReviewActions')?.remove();const box=document.createElement('section'),status=document.createElement('p');box.id='webReviewActions';box.className='web-review-actions';root.before(box);status.setAttribute('role','status');status.hidden=true;box.append(status);
 const auth=await api('/api/web/auth');
 if(!auth.signedIn){
  status.hidden=false;status.textContent=auth.configured?'Sign in to submit this review. Your saved notes stay in this browser.':'The test GitHub App registration is not configured yet.';
  const signIn=document.createElement('button');signIn.className='primary';signIn.textContent='Sign in with GitHub';signIn.disabled=!auth.configured;signIn.onclick=()=>webSignIn(true);box.append(signIn);return;
 }
 const payload={repo:'videoai/test-specs',pr:preparedReview.pr,left:preparedReview.left,right:preparedReview.right,summary:ReviewCore.normalizeDraft(reviewDraft).summary.text||'',notes:overview.documents.flatMap(doc=>(doc.changes||[]).filter(row=>row.note?.text?.trim()||row.note?.suggestion).map(row=>({path:doc.path,review:doc.review,block:row.id,text:row.note.text||'',suggestion:row.note.suggestion||null}))),confirm:true};
 if(preparedReview.repo!=='videoai/test-specs'||preparedReview.incomplete.length){status.hidden=false;status.textContent='Only complete reviews of videoai/test-specs can be submitted here.';return;}
 const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';label.style.cssText='display:flex;align-items:center;gap:8px;text-transform:none;letter-spacing:0';check.style.width='auto';label.append(check,document.createTextNode('Submit comments as '+auth.login+' to videoai/test-specs PR #'+payload.pr));
 const submit=document.createElement('button');submit.className='primary';submit.textContent='Submit review to GitHub';submit.disabled=true;check.onchange=()=>submit.disabled=!check.checked;
 submit.onclick=async()=>{submit.disabled=true;check.disabled=true;$('closePreview').disabled=true;status.hidden=false;status.textContent='Submitting test review…';try{const result=await api('/api/web/submit',payload);status.textContent='Review submitted. ';const link=document.createElement('a');link.href=result.url;link.target='_blank';link.rel='noreferrer';link.textContent='View on GitHub';status.append(link);}catch(e){status.textContent=e.message;}finally{$('closePreview').disabled=false;}};
 box.append(label,submit);
}
