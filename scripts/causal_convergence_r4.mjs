// Offline fixed-fixture study. No Agentora runtime, model, database or network.
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';

export const SOURCE_REVISION='acac3a4ea792f2b979b11f8dcccc1b298596ea0e';
export const SOURCE_BLOB='07b7142b86886cb44817e8bedf0a0f0338115962';

export async function loadPinnedBelt(checkout) {
  const path=resolve(checkout,'src/causal-belt.mjs');
  const bytes=await readFile(path);
  const blob=createHash('sha1').update('blob '+bytes.length+'\0').update(bytes).digest('hex');
  if(blob!==SOURCE_BLOB)throw Error('Pinned Altermath source mismatch');
  // Import the exact verified bytes, not a mutable path after checking it.
  // The pinned module imports only node:crypto.
  const belt=await import('data:text/javascript;base64,'+bytes.toString('base64'));
  if(belt.CAUSAL_VERSION!=='Altermath.CausalBelt.R1')throw Error('Unexpected belt version');
  return belt;
}

export function fixture(x,y,z,gear='sum') {
  const pockets={root:{fields:{}},'root/network':{fields:{latency:x}},
    'root/render':{fields:{frame:y,refinedFrame:z}}};
  const grants={root:{delegate:['root/network','root/render'],compose:[gear],finish:['result']},
    'root/network':{observe:['latency'],execute:['double'],return:['root']},
    'root/render':{observe:['frame','refinedFrame'],refine:['refinedFrame'],return:['root']}};
  const score=[
    {id:'delegate_net',op:'DELEGATE',pocket:'root',deps:[],child:'root/network',allocation:7},
    {id:'delegate_render',op:'DELEGATE',pocket:'root',deps:[],child:'root/render',allocation:7},
    {id:'net_read',op:'OBSERVE',pocket:'root/network',deps:['delegate_net'],field:'latency'},
    {id:'net_double',op:'EXECUTE',pocket:'root/network',deps:['net_read'],gear:'double',source:'net_read'},
    {id:'net_return',op:'RETURN',pocket:'root/network',deps:['net_double'],source:'net_double'},
    {id:'render_read',op:'OBSERVE',pocket:'root/render',deps:['delegate_render'],field:'frame'},
    {id:'render_detail',op:'REFINE',pocket:'root/render',deps:['render_read'],field:'refinedFrame',source:'render_read'},
    {id:'render_return',op:'RETURN',pocket:'root/render',deps:['render_detail'],source:'render_detail'},
    {id:'compose',op:'COMPOSE',pocket:'root',deps:['net_return','render_return'],gear,sources:['net_return','render_return']},
    {id:'finish',op:'FINISH',pocket:'root',deps:['compose'],source:'compose'}];
  return {score,pockets,grants,fuel:40};
}

// Independent conventional DAG evaluator: repeatedly scan unresolved tasks,
// execute a ready frontier using only earlier outputs, and count unit stages.
// It is NOT a policy engine and intentionally does not compare authorization.
export function baseline(tasks) {
  const remaining=new Map(tasks.map(t=>[t.id,t]));
  if(remaining.size!==tasks.length)throw Error('Duplicate task');
  const values=new Map(),frontiers=[];
  while(remaining.size) {
    const ready=[...remaining.values()].filter(t=>t.deps.every(d=>values.has(d)))
      .sort((a,b)=>a.id<b.id?-1:a.id>b.id?1:0);
    if(!ready.length)throw Error('Unresolvable dependencies');
    const computed=ready.map(t=>[t.id,t.compute(...t.deps.map(d=>values.get(d)))]);
    frontiers.push(ready.map(t=>t.id));
    for(const [id,value] of computed){values.set(id,value);remaining.delete(id);}
  }
  return {result:values.get('finish'),frontiers,events:tasks.length};
}

export function ordinaryFixture(x,y,z,gear) {
  const task=(id,deps,compute)=>({id,deps,compute});
  const combine=gear==='minimum'?Math.min:gear==='maximum'?Math.max:(a,b)=>a+b;
  return [
    task('delegate_net',[],()=>null),task('delegate_render',[],()=>null),
    task('net_read',['delegate_net'],()=>x),task('net_double',['net_read'],v=>v+v),
    task('net_return',['net_double'],v=>v),
    task('render_read',['delegate_render'],()=>y),
    task('render_detail',['render_read'],()=>z),
    task('render_return',['render_detail'],v=>v),
    task('compose',['net_return','render_return'],combine),task('finish',['compose'],v=>v)];
}

const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);

export function compare(belt,x,y,z,gear='sum') {
  const input=fixture(x,y,z,gear);
  const actual=belt.runCausalScore(input);
  const conventional=baseline(ordinaryFixture(x,y,z,gear));
  const reordered=belt.runCausalScore({...input,score:[...input.score].reverse()});
  const expectedFuel=input.score.reduce((sum,e)=>sum+(e.op==='REFINE'?2:1),0);
  const receiptValid=belt.verifyCausalReceipts(actual.receipts);
  const matches=actual.result===conventional.result&&same(actual.frontiers,conventional.frontiers)
    &&actual.events===conventional.events&&actual.fuelConsumed===expectedFuel
    &&actual.rootFuelRemaining===input.fuel-expectedFuel&&receiptValid
    &&same(actual,reordered);
  if(!matches)throw Error('Differential or accounting mismatch');
  return {result:actual.result,baseline_result:conventional.result,events:actual.events,
    unit_dependency_depth:actual.frontiers.length,maximum_ready_width:Math.max(...actual.frontiers.map(f=>f.length)),
    fuel_consumed:actual.fuelConsumed,fuel_remaining:actual.rootFuelRemaining,
    receipt_chain_valid:receiptValid,receipt_head:actual.receiptHead,parity:matches};
}

export function study(belt) {
  const cases=[[16,9,12,'sum'],[0,5,0,'sum'],[-8,2,9,'sum'],[3,8,-4,'minimum'],[3,8,-4,'maximum']];
  const observations=cases.map(([x,y,z,g])=>({case:g+':'+[x,y,z].join(','),...compare(belt,x,y,z,g)}));
  const negatives=[
    ['revoked-grant',f=>{f.grants['root/network'].execute=[];}],
    ['budget-exhausted',f=>{f.fuel=2;}],
    ['cycle',f=>{f.score[0].deps=['finish'];}],
    ['cross-pocket-input',f=>{const t=f.score.find(e=>e.id==='net_double');t.source='render_read';t.deps=['net_read','render_read'];}]
  ].map(([name,mutate])=>{
    const f=fixture(16,9,12);mutate(f);
    let refused=false;
    try{belt.runCausalScore(f);}catch(e){if(!String(e.message).startsWith('CAUSAL_REFUSE:'))throw e;refused=true;}
    if(!refused)throw Error('Unexpected acceptance: '+name);
    return {case:name,refused};
  });
  const receipts=belt.runCausalScore(fixture(16,9,12)).receipts;
  const altered=structuredClone(receipts);altered[0].fuelRemaining++;
  if(belt.verifyCausalReceipts(altered))throw Error('Tampered receipt accepted');
  negatives.push({case:'tampered-receipt',refused:true});
  return {schema:'agentora.convergence-r4.v1',authority:'NONE',mode:'SYNTHETIC_OFFLINE',
    upstream_revision:SOURCE_REVISION,upstream_blob:SOURCE_BLOB,
    comparisons:observations,negative_controls:negatives,
    limitations:['Fixed fixtures, not general scheduler equivalence.',
      'Baseline compares results and dependency frontiers, not authorization semantics.',
      'Unit depth is not wall time; both evaluators execute sequentially.',
      'Fuel is synthetic; no measured CPU, GPU, memory, inference or speedup.']};
}

if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href){
  if(process.argv.length!==3)throw Error('Usage: node scripts/causal_convergence_r4.mjs <trusted Altermath checkout>');
  const belt=await loadPinnedBelt(process.argv[2]);
  console.log(JSON.stringify(study(belt),null,2));
}
