import { useEffect,useState } from 'react';import { api } from '../api/client'
export default function Agents(){const [agents,setAgents]=useState<any[]>([]);useEffect(()=>{api('/api/agents').then(setAgents)},[]);return <div><h2>Agents</h2>{agents.map(a=><div className='card' key={a.id}>{a.name} · {a.model}</div>)}</div>}
