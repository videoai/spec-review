import {REPOSITORY} from './core.mjs';
export async function github(path,token,options={},send=fetch){
 const response=await send('https://api.github.com/'+path,{...options,redirect:'manual',headers:{'User-Agent':'ONVIF-Spec-Review-test','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28',Authorization:'Bearer '+token,...options.headers}});
 if(!response.ok){
  let detail;try{detail=await response.json();}catch{}
  const message=typeof detail?.message==='string'?detail.message.slice(0,500):'Request rejected.';
  const error=Error('GitHub returned '+response.status+': '+message);
  error.status=response.status;error.rejected=[400,401,403,404,405,406,409,410,415,422,429].includes(response.status);throw error;
 }
 return response.status===204?{}:response.json();
}
export function canRetry(prior,installedAt){
 if(!prior||prior.rejected)return true;
 // Legacy attempts omitted error details. The app could not have written before its first installation.
 const created=Date.parse(installedAt||'');
 return !!prior.time&&!prior.status&&Number.isFinite(created)&&created>prior.time;
}
