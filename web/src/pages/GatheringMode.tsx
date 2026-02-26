import { useEffect, useState } from 'react'
import { api } from '../api/client'

export default function GatheringMode(){
  const [devices,setDevices]=useState<any[]>([])
  const [session,setSession]=useState<any>(null)
  const [roomCode,setRoomCode]=useState('')
  const [name,setName]=useState('Guest')
  const [templates,setTemplates]=useState<any[]>([])
  const [warmth,setWarmth]=useState(60)

  useEffect(()=>{api('/api/gathering/discover').then(d=>setDevices(d.devices||[])); api('/api/gathering/templates').then(d=>setTemplates(d.templates||[]))},[])
  const create = async ()=>{const s=await api('/api/gathering/session/create',{method:'POST',body:JSON.stringify({host_name:'Host',mode:'studio'})});setSession(s);setRoomCode(s.room_code)}
  const join = async ()=>{const s=await api('/api/gathering/session/join',{method:'POST',body:JSON.stringify({room_code:roomCode,name})});setSession(s)}

  return <div><h2>🏠 Gathering</h2>
    <div className='card'><h4>Living-room Table</h4><label>Warmth {warmth}%</label><input type='range' min='0' max='100' value={warmth} onChange={e=>setWarmth(Number(e.target.value))}/><div className='round-table'>{devices.map((d,i)=><div key={i} className='avatar' style={{left:`${20+i*22}%`}}>{d.avatar}<small>{d.name}</small></div>)}</div>{!devices.length && <p>No other devices found — solo mode still works great!</p>}</div>
    <div className='card'><button onClick={create}>Create Gathering Session</button><input value={roomCode} onChange={e=>setRoomCode(e.target.value)} placeholder='4-digit room code'/><input value={name} onChange={e=>setName(e.target.value)} placeholder='your name'/><button onClick={join}>Join</button>{session&&<p>Invite Code: <b>{session.invite_code}</b></p>}</div>
    <div className='card'><h4>Mutual Aid & Community Crews</h4>{templates.map((t,i)=><p key={i}>{t.name} — {t.description}</p>)}</div>
  </div>
}
