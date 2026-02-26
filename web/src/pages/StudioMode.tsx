import { useEffect, useState } from 'react'
import { api, API } from '../api/client'

export default function StudioMode(){
  const [personas,setPersonas]=useState<any[]>([])
  const [song,setSong]=useState<any>(null)
  useEffect(()=>{api('/api/studio/personas').then(setPersonas)},[])
  const sing=async()=>{const teams=await api('/api/teams');if(!teams.length) return; const s=await api('/api/studio/sing',{method:'POST',body:JSON.stringify({team_id:teams[0].id,prompt:'Turn verdict into anthem'})});setSong(s)}
  return <div><h2>Studio</h2><button onClick={sing}>✨ Sing</button><div className='card'><h4>Personas</h4>{personas.map(p=><p key={p.id}>{p.name} — {p.style}</p>)}</div>{song&&<div className='card'><a href={`${API}/api/studio/song/${song.song_job_id}/master.wav`}>Download master.wav</a><a href={`${API}/api/studio/song/${song.song_job_id}/waveform.json`}>waveform.json</a></div>}</div>
}
