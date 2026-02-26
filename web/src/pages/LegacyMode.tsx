import { useEffect, useState } from 'react'
import { api } from '../api/client'

export default function LegacyMode(){
  const [tree,setTree]=useState<any>({nodes:[],edges:[]})
  const [souls,setSouls]=useState<any[]>([])
  const [agentId,setAgentId]=useState('1')
  const [childName,setChildName]=useState('Historian')

  const load=()=>{
    api('/api/legacy/tree').then(setTree)
    api('/api/legacy/souls').then(d=>setSouls(d.items||[]))
  }
  useEffect(()=>{load()},[])

  const nurture=async()=>{await api('/api/legacy/nurture',{method:'POST',body:JSON.stringify({agent_id:Number(agentId),dimension:'empathetic',delta:2,note:'family praise'})});load()}
  const reflect=async()=>{await api(`/api/legacy/reflect/${Number(agentId)}`,{method:'POST'});load()}
  const spawn=async()=>{await api('/api/legacy/child',{method:'POST',body:JSON.stringify({parent_ids:[Number(agentId)],child_name:childName,specialization:'family stories'})});load()}

  return <div>
    <h2>🌳 Legacy</h2>
    <div className='card legacy-tree'>
      <h4>Agent Family Tree</h4>
      <p>Persistent soul files, evolution points, and lineage.</p>
      <div className='tree-canvas'>{tree.nodes.map((n:any,i:number)=><div key={n.id} className='tree-node' style={{left:`${5+(i%5)*18}%`,top:`${20+Math.floor(i/5)*28}%`}} title={`This agent has sung ${n.avatar_stage*7} songs with the family ❤️`}>
        <b>{n.name}</b><small>{n.role}</small><small>Stage {n.avatar_stage}</small>
      </div>)}</div>
    </div>
    <div className='card'>
      <h4>Nurture & Reflection</h4>
      <input value={agentId} onChange={e=>setAgentId(e.target.value)} placeholder='Agent ID'/>
      <button onClick={nurture}>Praise (+Empathy)</button>
      <button onClick={reflect}>Daily Reflection</button>
      <input value={childName} onChange={e=>setChildName(e.target.value)} placeholder='Child Name'/>
      <button onClick={spawn}>Fork Child Agent</button>
      <a href={`/api/legacy/heirloom/${Number(agentId)}.zip`}><button>Export Heirloom</button></a>
    </div>
    <div className='card'>
      <h4>Soul Timeline</h4>
      {souls.map((s:any)=><details key={s.agent_id}><summary>{s.agent_name} • EP {s.evolution_points}</summary><pre>{JSON.stringify(s.timeline.slice(-3),null,2)}</pre></details>)}
    </div>
  </div>
}
