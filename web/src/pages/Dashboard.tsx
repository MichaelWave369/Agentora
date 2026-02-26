import { useEffect, useState } from 'react'
import { api } from '../api/client'
import TemplateGallery from '../components/TemplateGallery'
export default function Dashboard(){
  const [templates,setTemplates]=useState<any[]>([])
  const [runs,setRuns]=useState<any[]>([])
  useEffect(()=>{api('/api/teams/templates').then(d=>setTemplates(d.templates||[]));api('/api/runs').then(setRuns)},[])
  return <><h2>Dashboard</h2><TemplateGallery templates={templates}/><div className='card'><h3>Recent Runs</h3>{runs.map((r:any)=><p key={r.id}>#{r.id} {r.status}</p>)}</div></>
}
