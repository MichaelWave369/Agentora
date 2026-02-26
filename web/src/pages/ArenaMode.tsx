import { useState } from 'react'
import { api } from '../api/client'

export default function ArenaMode(){
  const [match,setMatch]=useState<any>(null)
  const start=async()=>{const m=await api('/api/arena/match',{method:'POST',body:JSON.stringify({topic:'Should AI be local-first?'})});setMatch(m)}
  const peace=()=>alert('Peace Button: force synthesis round (scaffold)')
  return <div><h2>Arena</h2><button onClick={start}>Start Match</button><button onClick={peace}>🕊 Peace Button</button>{match&&<div className='card'><p>Match #{match.match_id}</p><button onClick={()=>api('/api/studio/turn-verdict-into-anthem',{method:'POST',body:JSON.stringify({match_id:match.match_id,team_id:1})})}>Turn Verdict into Anthem</button><button onClick={()=>api('/api/studio/narrate-highlights',{method:'POST',body:JSON.stringify({summary:'epic debate'})})}>Narrate Highlights</button></div>}</div>
}
