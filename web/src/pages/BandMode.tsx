import { useState } from 'react'
import { api, API } from '../api/client'
export default function BandMode(){
  const [track,setTrack]=useState<any>(null)
  const [dna,setDna]=useState(50)
  const create=async()=>{const t=await api('/api/band/create_track',{method:'POST',body:JSON.stringify({team_id:1,genre:'synthwave+hiphop',genre_dna:dna,bpm:112,prompt:'Write and perform a song about local AI freedom'})});setTrack(t)}
  return <div><h2>Band</h2><label>Genre DNA: {dna}%</label><input type='range' min='0' max='100' value={dna} onChange={e=>setDna(Number(e.target.value))}/><button onClick={create}>Create Track</button>{track&&<div className='card'><a href={`${API}/api/band/track/${track.track_job_id}/master.wav`}>master.wav</a> · <a href={`${API}/api/band/track/${track.track_job_id}/export-project.zip`}>Export Full Project</a></div>}</div>
}
