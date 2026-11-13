import {test} from 'node:test';
import assert from 'node:assert/strict';
import {github,canRetry} from './github.mjs';
test('GitHub rejection status is retained, without leaking tokens',async()=>{
 for(const status of [403,422,500])await assert.rejects(github('endpoint','secret-token',{},async()=>Response.json({message:'Not accessible'},{status})),e=>e.status===status&&e.rejected===(status!==500)&&!e.message.includes('secret-token'));
});
test('only proven rejections and pre-installation legacy attempts can be retried',()=>{
 const created='2026-11-13T16:00:00Z',time=Date.parse(created);
 assert.equal(canRetry({time:time-1000},created),true);
 assert.equal(canRetry({time:time+1000},created),false);
 assert.equal(canRetry({time:time-1000,status:'started'},created),false);
 assert.equal(canRetry({time,status:'rejected',rejected:true},created),true);
 assert.equal(canRetry({time:time-1000},null),false);
});
