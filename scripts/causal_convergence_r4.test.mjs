import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {baseline, loadPinnedBelt, study} from './causal_convergence_r4.mjs';

test('ordinary DAG refuses cycles and duplicate IDs',()=>{
  assert.throws(()=>baseline([{id:'a',deps:['a'],compute:()=>0}]),/Unresolvable/);
  assert.throws(()=>baseline([{id:'a',deps:[],compute:()=>0},{id:'a',deps:[],compute:()=>1}]),/Duplicate/);
});
test('modified upstream is rejected before import',async()=>{
  const root=await mkdtemp(join(tmpdir(),'causal-r4-'));
  try{
    await mkdir(join(root,'src'));
    await writeFile(join(root,'src','causal-belt.mjs'),'throw Error("must not execute");');
    await assert.rejects(loadPinnedBelt(root),/Pinned Altermath source mismatch/);
  }finally{await rm(root,{recursive:true,force:true});}
});
test('real pinned upstream matches all fixtures and refuses all controls',async()=>{
  assert(process.env.ALTERMATH_CHECKOUT,'Pinned checkout required; no mock fallback');
  const belt=await loadPinnedBelt(process.env.ALTERMATH_CHECKOUT);
  const r=study(belt);
  assert.equal(r.authority,'NONE');
  assert.deepEqual(r.comparisons.map(x=>x.result),[44,0,-7,-4,6]);
  assert(r.comparisons.every(x=>x.parity&&x.events===10&&x.unit_dependency_depth===6&&
    x.maximum_ready_width===2&&x.fuel_consumed===11&&x.fuel_remaining===29));
  assert.equal(r.negative_controls.length,5);
  assert(r.negative_controls.every(x=>x.refused));
  assert.deepEqual(r,study(belt));
});
