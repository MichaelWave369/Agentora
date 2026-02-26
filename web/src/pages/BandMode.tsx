import { useState } from 'react'
import { api, API } from '../api/client'
export default function BandMode(){
  const [track,setTrack]=useState<any>(null)
  const create=async()=>{const t=await api('/api/band/create_track',{method:'POST',body:JSON.stringify({team_id:1,genre:'synthwave',bpm:112})});setTrack(t)}
  return <div><h2>Band</h2><button onClick={create}>Create Track</button>{track&&<div className='card'><a href={`${API}/api/band/track/${track.track_job_id}/master.wav`}>master.wav</a></div>}</div>
}
