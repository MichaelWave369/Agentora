import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'

export default function CosmosMode(){
  const [worlds,setWorlds]=useState<any[]>([])
  const [selectedWorld,setSelectedWorld]=useState<any>(null)
  const [timelines,setTimelines]=useState<any[]>([])
  const [archive,setArchive]=useState<any>(null)
  const [name,setName]=useState('My Eternal Cosmos')
  const [seed,setSeed]=useState('A family dream that became a universe')
  const [branch,setBranch]=useState('What if I moved to Chico in 2025?')
  const [warmth,setWarmth]=useState(70)

  const loadWorlds = async ()=>{
    const d = await api('/api/cosmos/worlds')
    setWorlds(d.items||[])
  }
  const loadTimelines = async (id:number)=>{
    const t = await api(`/api/cosmos/world/${id}/timelines`)
    setTimelines(t.items||[])
  }

  useEffect(()=>{loadWorlds()},[])

  const createWorld = async ()=>{
    const w = await api('/api/cosmos/worlds',{method:'POST',body:JSON.stringify({name,seed_prompt:seed,warmth})})
    setSelectedWorld(w)
    await loadWorlds()
    await loadTimelines(w.id)
  }

  const branchTimeline = async ()=>{
    if(!selectedWorld) return
    await api('/api/cosmos/branch',{method:'POST',body:JSON.stringify({world_id:selectedWorld.id,parent_timeline_id:0,title:`Branch ${timelines.length+1}`,branch_prompt:branch})})
    await loadTimelines(selectedWorld.id)
  }

  const reflect = async ()=>{
    if(!selectedWorld) return
    const r = await api(`/api/cosmos/reflection/${selectedWorld.id}?warmth=${warmth}`,{method:'POST'})
    alert(`${r.message}\n${r.oracle}`)
  }

  const searchArchive = async ()=> setArchive(await api('/api/cosmos/archive?query=family'))

  const mapPoints = useMemo(()=>{
    try{return JSON.parse(selectedWorld?.map_json || '[]')}catch{return []}
  },[selectedWorld])

  return <div>
    <h2>🌌 Cosmos</h2>
    <div className='card cosmos-card'>
      <h4>Plant Your First Cosmos</h4>
      <input value={name} onChange={e=>setName(e.target.value)} placeholder='Cosmos name'/>
      <input value={seed} onChange={e=>setSeed(e.target.value)} placeholder='Seed prompt'/>
      <label>Warmth / Hopefulness {warmth}%</label>
      <input type='range' min='0' max='100' value={warmth} onChange={e=>setWarmth(Number(e.target.value))}/>
      <button onClick={createWorld}>Create New Cosmos</button>
      <p className='microcopy'>This branch feels hopeful… and rooted in your family tree.</p>
    </div>

    <div className='card cosmos-map'>
      <h4>Galaxy Map</h4>
      <div className='galaxy-canvas'>
        {mapPoints.map((p:any)=><div key={p.id} className='star-node' style={{left:`${p.x}%`,top:`${p.y}%`}}>{p.label}</div>)}
      </div>
      <small>Zoom/pan style kept lightweight for offline performance.</small>
    </div>

    <div className='card'>
      <h4>Timeline Branching</h4>
      <select onChange={e=>{const w = worlds.find(x=>x.id===Number(e.target.value));setSelectedWorld(w); if(w){loadTimelines(w.id)}}} value={selectedWorld?.id || ''}>
        <option value=''>Select cosmos</option>
        {worlds.map(w=><option key={w.id} value={w.id}>{w.name}</option>)}
      </select>
      <input value={branch} onChange={e=>setBranch(e.target.value)} placeholder='Branch timeline prompt'/>
      <button onClick={branchTimeline}>Branch Timeline</button>
      <button onClick={reflect}>Cosmic Reflection</button>
      {selectedWorld && <a href={`/api/cosmos/world/${selectedWorld.id}/eternal-seed.zip`}><button>Export Eternal Seed</button></a>}
      <button onClick={async()=>{if(selectedWorld){await api(`/api/cosmos/world/${selectedWorld.id}/collapse`,{method:'POST'});loadTimelines(selectedWorld.id)}}}>Collapse All Timelines</button>
      <div className='timeline-strip'>{timelines.map(t=><span key={t.id} className={`timeline-pill ${t.status}`}>{t.title}</span>)}</div>
    </div>

    <div className='card'>
      <h4>Eternal Archive</h4>
      <button onClick={searchArchive}>Search Archive</button>
      {archive && <pre>{JSON.stringify(archive,null,2)}</pre>}
    </div>
  </div>
}
