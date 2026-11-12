/* Static Pages adapter: comparisons are public build artifacts; drafts stay in IndexedDB. */
window.REVIEW_STATIC=true;
(()=>{
  let manifest=null;const bundles=new Map();let database;
  async function loadManifest(force=false){
    if(!manifest||force){const response=await fetch('./site.json',{cache:'no-store'});if(!response.ok)throw Error('Published comparison index is unavailable. Try again after the build finishes.');const next=await response.json();if(next.format!=='onvif-spec-review-site'||next.version!==1)throw Error('Unsupported comparison site.');if(manifest?.builtAt!==next.builtAt)bundles.clear();manifest=next;}
    return manifest;
  }
  function db(){
    if(!database)database=new Promise((resolve,reject)=>{const request=indexedDB.open('onvif-spec-review',1);request.onupgradeneeded=()=>request.result.createObjectStore('reviews');request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(Error('Browser storage is unavailable. Allow site data or use the local tool.'));});
    return database;
  }
  async function state(pr,mutate){
    const connection=await db(),site=await loadManifest(),key=site.repository.toLowerCase()+':'+pr;
    return new Promise((resolve,reject)=>{
      const tx=connection.transaction('reviews',mutate?'readwrite':'readonly'),store=tx.objectStore('reviews'),request=store.get(key);let value;
      request.onsuccess=()=>{try{value=request.result||ReviewCore.empty();value.draft=ReviewCore.normalizeDraft(value.draft);if(mutate){mutate(value);store.put(value,key);}}catch(error){tx.abort();reject(error);}};
      tx.oncomplete=()=>resolve(value);tx.onerror=()=>reject(Error('Could not save browser review data. Back up your review and check available storage.'));tx.onabort=()=>reject(Error('Review storage transaction was cancelled.'));
    });
  }
  async function bundle(pr){
    const site=await loadManifest(),entry=site.prs.find(item=>String(item.number)===String(pr));if(!entry)throw Error('PR is not in this published build. Check for updates.');
    if(entry.error)throw Error(entry.error);
    if(!bundles.has(String(pr))){const response=await fetch(entry.data);if(!response.ok)throw Error('This comparison is unavailable. Check for updates.');bundles.set(String(pr),await response.json());}
    return bundles.get(String(pr));
  }
  function comparison(data,path,saved){
    const doc=data.comparisons[path];if(!doc)throw Error('File is not in this comparison.');if(doc.error)throw Error(doc.error);
    const result=ReviewCore.clone(doc);for(const row of result.rows)row.reviewed=!!saved.reviewed[row.reviewKey];return result;
  }
  function overview(data,saved){return {left:data.pr.left,right:data.pr.right,documents:data.pr.files.map(path=>{const doc=data.comparisons[path];if(doc.error)return {path,error:doc.error,changes:[]};return {path,review:doc.review,mode:doc.mode,fileStatus:doc.fileStatus,changes:comparison(data,path,saved).rows.filter(row=>row.status!=='same').map(row=>({...row,note:saved.notes[doc.review]?.[row.id]||null}))};})};}
  async function feedback(pr,force){
    const site=await loadManifest(),cacheKey='onvif-feedback:'+site.repository+':'+pr;let cached;
    try{cached=JSON.parse(sessionStorage.getItem(cacheKey)||'null');}catch{}
    if(!force&&cached&&Date.now()-cached.time<600000)return {...cached.value,cached:true};
    const items=[],warnings=[],repo=site.repository;
    for(const [kind,endpoint] of [['conversation',`issues/${pr}/comments`],['review',`pulls/${pr}/reviews`],['file',`pulls/${pr}/comments`]]){
      try{for(let page=1;page<=100;page++){
        const response=await fetch(`https://api.github.com/repos/${repo}/${endpoint}?per_page=100&page=${page}`,{headers:{Accept:'application/vnd.github+json'}});
        if(!response.ok){const reset=Number(response.headers.get('x-ratelimit-reset')),retry=Number(response.headers.get('retry-after'));throw Error(response.status===403||response.status===429?'GitHub rate limit or access restriction.'+(reset?' Retry after '+new Date(reset*1000).toLocaleString()+'.':retry?' Retry in '+retry+' seconds.':''):'GitHub returned '+response.status+'.');}
        const batch=await response.json();for(const entry of batch){if(kind==='review'&&entry.state==='PENDING')continue;if(!entry.body?.trim()&&kind!=='review')continue;items.push({id:String(entry.id),kind,author:entry.user?.login||'Deleted user',body:entry.body||'',url:entry.html_url||'',created:entry.submitted_at||entry.created_at||'',path:entry.path,line:entry.line,originalLine:entry.original_line,side:entry.side,replyTo:entry.in_reply_to_id,state:entry.state,outdated:kind==='file'&&entry.subject_type!=='file'&&entry.line==null});}
        if(batch.length<100)break;if(page===100)warnings.push('Feedback truncated after 10,000 '+kind+' entries.');
      }}catch(error){warnings.push(kind+': '+error.message);}
    }
    if(warnings.length&&cached)return {...cached.value,cached:true,warnings};
    const value={pr:Number(pr),items:items.sort((a,b)=>a.created.localeCompare(b.created)),warnings,cached:false,fetchedAt:Date.now()/1000};
    if(!warnings.length)try{sessionStorage.setItem(cacheKey,JSON.stringify({time:Date.now(),value}));}catch{}
    return value;
  }
  window.reviewBackend=async(url,payload)=>{
    const request=new URL(url,location.href),q=request.searchParams,route=request.pathname,pr=payload?.pr||q.get('pr'),site=await loadManifest();
    if(route==='/api/context')return {id:'pages:'+site.repository,repo:site.repository,static:true,builtAt:site.builtAt};
    if(route==='/api/fetch'){await loadManifest(true);return {fetched:true};}
    if(route==='/api/prs')return {repo:site.repository,prs:manifest.prs,github:{}};
    if(route==='/api/pr')return (await bundle(q.get('number'))).pr;
    if(route==='/api/feedback')return feedback(pr,q.get('refresh')==='1');
    const saved=await state(pr);
    if(route==='/api/reset-status')return {canUndo:!!saved.undo};
    if(route==='/api/draft'&&!payload)return saved.draft;
    if(route==='/api/notes'&&!payload)return {notes:saved.notes[q.get('review')]||{}};
    if(route==='/api/note-history')return {reviews:saved.notes};
    if(route==='/api/compare')return comparison(await bundle(pr),q.get('path'),saved);
    if(route==='/api/review-summary')return overview(await bundle(pr),saved);
    if(route==='/api/review-preview'){const data=await bundle(pr);return ReviewCore.preview(site.repository,data.pr,overview(data,saved),saved.draft,plain);}
    if(route==='/api/backup')return {format:'onvif-spec-review',version:1,repository:site.repository,pr:Number(pr),exportedAt:new Date().toISOString(),notes:saved.notes,draft:saved.draft,reviewed:saved.reviewed};
    if(route==='/api/import-backup'){
      const counts=ReviewCore.validateBackup(payload.backup,site.repository,pr);if(payload.confirm!==true)return counts;
      await state(pr,value=>{value.undo=ReviewCore.clone({notes:value.notes,draft:value.draft,reviewed:value.reviewed});for(const key of ['notes','draft','reviewed'])value[key]=ReviewCore.clone(payload.backup[key]);});return {...counts,saved:true,canUndo:true};
    }
    if(route==='/api/reset'||route==='/api/undo-reset'){
      const value=await state(pr,value=>{if(route==='/api/undo-reset'){if(!value.undo)throw Error('No reset or import to undo.');Object.assign(value,value.undo,{undo:null});}else{value.undo=ReviewCore.clone({notes:value.notes,draft:value.draft,reviewed:value.reviewed});Object.assign(value,{notes:{},draft:{summary:{},files:{}},reviewed:{}});}});return {saved:true,canUndo:!!value.undo};
    }
    if(route==='/api/reviewed'){await state(pr,value=>{if(payload.reviewed)value.reviewed[payload.key]=true;else delete value.reviewed[payload.key];});return {saved:true};}
    if(route==='/api/notes'){await state(pr,value=>{const blocks=value.notes[payload.review]||{};if(payload.text.trim())blocks[payload.block]={text:payload.text,path:payload.path,context:payload.context,pr:String(pr),versions:payload.versions,updated:new Date().toISOString()};else delete blocks[payload.block];value.notes[payload.review]=blocks;});return {saved:true};}
    if(route==='/api/draft'){if(payload.scope!=='summary')throw Error('Use the PR summary for overall or file-wide feedback.');const value=await state(pr,value=>{const record={text:payload.text,versions:payload.versions,updated:new Date().toISOString()};value.draft={summary:payload.text.trim()?record:{},files:{}};});return {saved:true,draft:value.draft};}
    throw Error('Unsupported static review operation.');
  };
})();
