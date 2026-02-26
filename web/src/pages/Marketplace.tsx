import { useEffect, useState } from 'react'
import { api } from '../api/client'

export default function Marketplace(){
  const [items,setItems]=useState<any[]>([])
  useEffect(()=>{api('/api/marketplace/templates').then(d=>setItems(d.templates||[]))},[])
  const install = async (x:any)=>{await api('/api/marketplace/install',{method:'POST',body:JSON.stringify({name:x.name,version:x.version})});alert('installed')}
  return <div><h2>Marketplace</h2>{items.map(i=><div key={i.name} className='card'><h4>{i.name} v{i.version}</h4><p>{i.description}</p><button onClick={()=>install(i)}>Install</button>{i.update_available&&<span>Update available</span>}</div>)}</div>
}
