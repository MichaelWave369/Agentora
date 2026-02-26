import { useEffect, useState } from 'react'
import { api } from '../api/client'
import TemplateGallery from '../components/TemplateGallery'

export default function Dashboard(){
  const [templates,setTemplates]=useState<any[]>([])
  const [runs,setRuns]=useState<any[]>([])
  useEffect(()=>{api('/api/teams/templates').then(d=>setTemplates(d.templates||[]));api('/api/runs').then(setRuns)},[])
  const tryNow = async ()=>{
    await api('/api/band/create_track',{method:'POST',body:JSON.stringify({team_id:1,genre:'hiphop-electronic',bpm:118,prompt:'Write and perform a song about local AI freedom'})})
    alert('MicTek Rebellion loaded. Go to Band mode!')
  }
  return <><h2>Dashboard</h2><div className='hero-actions'><button className='try-now' onClick={tryNow}>🚀 Try It Now: MicTek Rebellion</button></div><TemplateGallery templates={templates}/><div className='card'><h3>Recent Runs</h3>{runs.map((r:any)=><p key={r.id}>#{r.id} {r.status}</p>)}</div></>
}
