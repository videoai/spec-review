/* Shared copy/paste review export. No GitHub write requests or credentials. */
const ReviewCore=(()=>{
  const clone=value=>JSON.parse(JSON.stringify(value));
  const empty=()=>({notes:{},draft:{summary:{},files:{}},reviewed:{},undo:null});
  const quote=value=>value.split('\n').map(line=>'> '+line).join('\n');
  function normalizeDraft(draft={}){
    const summary={...(draft.summary||{})},parts=[summary.text?.trim()||''];
    for(const [path,note] of Object.entries(draft.files||{}))if(note.text?.trim())parts.push('### '+path+'\n\n'+note.text.trim());
    const text=parts.filter(Boolean).join('\n\n');return {summary:text?{...summary,text}:{},files:{}};
  }
  function validateSuggestion(value,target,xmlSource,parseXml){
    if(!target?.available)throw Error(target?.reason||'No source range is available. Check for a newer published comparison.');
    if(!value||typeof value.text!=='string'||value.text.length>20000)throw Error('Invalid suggested source replacement.');
    if(value.text===target.original)throw Error('Edit the suggested source before saving it.');
    if(/^\s*`{3,}/m.test(value.text))throw Error('A suggested replacement cannot contain Markdown code fences.');
    if(target.path.toLowerCase().endsWith('.xml')){
      if(typeof xmlSource!=='string'||!parseXml)throw Error('XML source is unavailable. Check for a newer published comparison.');
      const lines=xmlSource.replace(/^\uFEFF/,'').replace(/\r\n?/g,'\n').split('\n');
      const modified=[...lines.slice(0,target.startLine-1),value.text,...lines.slice(target.line)].join('\n');
      if(/<!DOCTYPE|<!ENTITY/i.test(modified))throw Error('DTD/entity declarations are not supported.');
      const error=parseXml(modified);if(error)throw Error('The suggested replacement would make the XML invalid: '+error);
    }
    return {...target,text:value.text};
  }
  async function locationURL(repo,pr,path,anchor){
    const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(path));
    const hash=[...new Uint8Array(bytes)].map(value=>value.toString(16).padStart(2,'0')).join('');
    return `https://github.com/${repo}/pull/${pr}/files#diff-${hash}`+(anchor?.subjectType==='LINE'?(anchor.startLine?(anchor.side==='RIGHT'?'R':'L')+anchor.startLine+'-':'')+(anchor.side==='RIGHT'?'R':'L')+anchor.line:'');
  }
  async function preview(repo,pr,overview,draft,plain){
    draft=normalizeDraft(draft);
    const body=(draft.summary?.text?.trim()?draft.summary.text.trim()+'\n\n':'')+'Reviewed with ONVIF Spec Review at `'+pr.right.slice(0,8)+'`.';
    const files=[];
    for(const doc of overview.documents){
      for(const row of doc.changes){
        if(!row.note?.text?.trim()&&!row.note?.suggestion)continue;
        const suggestion=row.note.suggestion;
        const anchor=suggestion?{subjectType:'LINE',side:'RIGHT',line:suggestion.line,...(suggestion.startLine!==suggestion.line?{startLine:suggestion.startLine,startSide:'RIGHT'}:{})}:row.anchor||{subjectType:'FILE',reason:'No reliable changed source line for this chunk.'};
        files.push({path:doc.path,kind:'chunk',heading:row.heading,anchor,body:suggestion?[row.note.text||'','','```suggestion',suggestion.text,'```'].join('\n').trim():anchor.subjectType==='LINE'?row.note.text:['## '+row.heading,'',row.note.text,'','Before:',quote(plain(row.left)),'','After:',quote(plain(row.right))].join('\n')});
      }
    }
    if(!files.length&&!draft.summary?.text?.trim())throw Error('Add a PR summary, change note, or suggestion first.');
    for(const comment of files){const a=comment.anchor;comment.location=a.subjectType==='LINE'?(a.side==='RIGHT'?'Proposed':'Base')+' '+(a.startLine?'lines '+a.startLine+'–'+a.line:'line '+a.line):comment.kind==='file'?'File note':'Chunk thread on file · '+a.reason;comment.url=await locationURL(repo,pr.number,comment.path,a);}
    const url=`https://github.com/${repo}/pull/${pr.number}`;
    const lines=[`# Review for ${repo} PR #${pr.number}`,'','Base commit: '+pr.left,'Proposed commit: '+pr.right,'',body,''];
    for(const comment of files)lines.push('# '+comment.path+' · '+comment.location,'',comment.body,'');
    return {repo,pr:pr.number,left:pr.left,right:pr.right,body,files,url,markdown:lines.join('\n'),incomplete:overview.documents.filter(doc=>doc.error).map(doc=>doc.path)};
  }
  function validateBackup(backup,repo,pr){
    const object=value=>{if(!value||typeof value!=='object'||Array.isArray(value))throw Error('Invalid backup data.');return value;};
    object(backup);
    if(backup.format!=='onvif-spec-review'||backup.version!==1)throw Error('Unsupported review backup.');
    if(typeof backup.repository!=='string'||backup.repository.toLowerCase()!==repo.toLowerCase()||Number(backup.pr)!==Number(pr))throw Error('Backup belongs to a different repository or PR.');
    const key=value=>{if(!/^[a-f0-9]{64}$/.test(value))throw Error('Invalid backup identifier.');};
    const path=value=>{if(typeof value!=='string'||!value||value.length>500||value.startsWith('/')||value.split('/').includes('..'))throw Error('Invalid backup file path.');};
    const note=(value,block=false,maxLength=20000)=>{object(value);if(typeof value.text!=='string'||value.text.length>maxLength)throw Error('Invalid backup note.');if(value.updated!==undefined&&typeof value.updated!=='string')throw Error('Invalid note timestamp.');if(Object.values(object(value.versions||{})).some(v=>typeof v!=='string'))throw Error('Invalid note versions.');if(value.suggestion){const v=object(value.suggestion);if(typeof v.text!=='string'||v.text.length>20000||typeof v.original!=='string'||v.original.length>20000||!(/^[a-f0-9]{40,64}$/).test(v.right)||![v.startLine,v.line].every(n=>Number.isInteger(n)&&n>0)||v.startLine>v.line)throw Error('Invalid backup suggestion.');}if(block){path(value.path);if(typeof (value.context||'')!=='string'||(value.context||'').length>2000)throw Error('Invalid note context.');}};
    for(const [review,blocks] of Object.entries(object(backup.notes))){key(review);for(const [block,value] of Object.entries(object(blocks))){key(block);note(value,true);}}
    for(const [id,value] of Object.entries(object(backup.reviewed))){key(id);if(typeof value!=='boolean')throw Error('Invalid reviewed mark.');}
    const draft=object(backup.draft);object(draft.summary);if(Object.keys(draft.summary).length)note(draft.summary,false,10*1024*1024);
    for(const [file,value] of Object.entries(object(draft.files))){path(file);note(value);}
    return {pr:Number(pr),notes:Object.values(backup.notes).reduce((n,v)=>n+Object.keys(v).length,0),fileNotes:Object.keys(draft.files).length,summary:!!draft.summary.text,reviewed:Object.values(backup.reviewed).filter(Boolean).length};
  }
  return {clone,empty,normalizeDraft,preview,validateBackup,validateSuggestion,locationURL};
})();
if(typeof module!=='undefined')module.exports=ReviewCore;
