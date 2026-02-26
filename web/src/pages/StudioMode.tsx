import { useEffect, useState } from 'react'
import { api, API } from '../api/client'

export default function StudioMode(){
  const [personas,setPersonas]=useState<any[]>([])
  const [song,setSong]=useState<any>(null)
  const [listening,setListening]=useState(false)
  const [singing,setSinging]=useState(false)
  const [voiceStatus,setVoiceStatus]=useState<any>(null)
  useEffect(()=>{api('/api/studio/personas').then(setPersonas);api('/api/voice/status').then(setVoiceStatus)},[])
  const sing=async()=>{setSinging(true);const teams=await api('/api/teams');if(!teams.length){setSinging(false);return;}const s=await api('/api/studio/sing',{method:'POST',body:JSON.stringify({team_id:teams[0].id,prompt:'Turn verdict into anthem'})});setSong(s);setSinging(false)}
  return <div><h2>Studio</h2>{voiceStatus && !voiceStatus.piper_configured && <div className='banner'>Install voice pack? (one command): <code>{voiceStatus.install_command}</code></div>}<button className={`mic ${listening?'listening':''} ${singing?'singing':''}`} onClick={()=>setListening(!listening)}>🎤 <span className='tiny-wave'>▁▃▅▃▁</span></button><button onClick={sing}>✨ Sing</button><div className='card'><h4>Personas</h4>{personas.map(p=><p key={p.id}>{p.name} — {p.style}</p>)}</div>{song&&<div className='card'><a href={`${API}/api/studio/song/${song.song_job_id}/master.wav`}>Download master.wav</a> · <a href={`${API}/api/studio/song/${song.song_job_id}/waveform.json`}>waveform.json</a> · <a href={`${API}/api/studio/song/${song.song_job_id}/export-project.zip`}>Export Full Project</a></div>}</div>
}
