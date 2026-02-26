import { PropsWithChildren, useEffect, useState } from 'react'
import Nav from './Nav'

export default function AppShell({children}:PropsWithChildren){
  const [theme,setTheme]=useState<'dark'|'light'>('dark')
  useEffect(()=>{document.body.dataset.theme=theme},[theme])
  useEffect(()=>{
    if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(()=>{})}
    const onKey=(e:KeyboardEvent)=>{
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){alert('Command palette (v0.2 scaffold)')}
    }
    window.addEventListener('keydown', onKey)
    return ()=>window.removeEventListener('keydown', onKey)
  },[])
  return <div className='shell'><aside><h1>Agentora</h1><div className='badge'>LOCALHOST ONLY</div><button onClick={()=>setTheme(theme==='dark'?'light':'dark')}>Theme</button><Nav/></aside><main>{children}</main></div>
}
