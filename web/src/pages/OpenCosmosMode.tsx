import { useEffect, useState } from 'react'
import { api } from '../api/client'

export default function OpenCosmosMode(){
  const [worlds,setWorlds]=useState<any[]>([])
  const [shares,setShares]=useState<any[]>([])
  const [network,setNetwork]=useState<any[]>([])
  const [selectedWorld,setSelectedWorld]=useState('')
  const [packageName,setPackageName]=useState('')
  const [privacy,setPrivacy]=useState('private')
  const [wisdomOnly,setWisdomOnly]=useState(true)
  const [msg,setMsg]=useState('')

  const refresh = async ()=>{
    const w = await api('/api/cosmos/worlds')
    setWorlds(w.items||[])
    const s = await api('/api/open-cosmos/shares')
    setShares(s.items||[])
    const n = await api('/api/open-cosmos/network')
    setNetwork(n.items||[])
  }
  useEffect(()=>{refresh()},[])

  const doShare = async ()=>{
    const out = await api('/api/open-cosmos/share',{method:'POST',body:JSON.stringify({world_id:Number(selectedWorld),visibility:privacy,wisdom_mode:wisdomOnly?'anonymized':'full_public',contributors:[{name:'Family Host',role:'guardian'}]})})
    setMsg(out.message)
    setPackageName(out.package_name)
    refresh()
  }

  const doImport = async ()=>{
    const out = await api('/api/open-cosmos/import',{method:'POST',body:JSON.stringify({package_name:packageName,keep_timelines:[]})})
    setMsg(out.message)
    refresh()
  }

  return <div>
    <h2>📖🌌 Open Cosmos</h2>
    <div className='card open-cosmos-card'>
      <h4>Safe Sharing & Merging</h4>
      <select value={selectedWorld} onChange={e=>setSelectedWorld(e.target.value)}>
        <option value=''>Select cosmos to share</option>
        {worlds.map(w=><option key={w.id} value={w.id}>{w.name}</option>)}
      </select>
      <label>Privacy</label>
      <select value={privacy} onChange={e=>setPrivacy(e.target.value)}>
        <option value='private'>Keep this cosmos private</option>
        <option value='anonymized'>Share anonymized wisdom only</option>
        <option value='public_with_credits'>Full public with credits</option>
      </select>
      <label><input type='checkbox' checked={wisdomOnly} onChange={e=>setWisdomOnly(e.target.checked)}/> Global Wisdom Archive (opt-in)</label>
      <button onClick={doShare}>Share Cosmos (.agentora)</button>
      {packageName && <a href={`/api/open-cosmos/download/${packageName}`}><button>Download Package</button></a>}
      <input value={packageName} onChange={e=>setPackageName(e.target.value)} placeholder='Import package name .agentora'/>
      <button onClick={doImport}>Import & Merge</button>
      {msg && <p className='microcopy'>{msg}</p>}
    </div>

    <div className='card'>
      <h4>Living Legacy Network</h4>
      <div className='open-grid'>{network.map((n:any,i:number)=><div key={i} className='network-card'><b>{n.thumbnail} {n.title}</b><small>{n.package}</small><small>Credits: {(n.credits||[]).map((c:any)=>c.name).join(', ')}</small></div>)}</div>
    </div>

    <div className='card'>
      <h4>Version History & Revocation</h4>
      {shares.map((s:any)=><div key={s.id} className='version-item'>
        <b>{s.package_name}</b> · {s.visibility} · revoked: {String(s.revoked)}
        <button onClick={async()=>{await api(`/api/open-cosmos/revoke/${s.id}`,{method:'POST'});refresh()}}>Revoke</button>
      </div>)}
    </div>
  </div>
}
