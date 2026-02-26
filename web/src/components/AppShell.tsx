import { PropsWithChildren, useEffect, useState } from 'react'
import Nav from './Nav'

export default function AppShell({children}:PropsWithChildren){
  const [theme,setTheme]=useState<'clean'|'noir'>('clean')
  useEffect(()=>{document.body.dataset.theme=theme},[theme])
  useEffect(()=>{if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(()=>{})}},[])
  return <div className='shell'><aside><h1>Agentora</h1><div className='badge'>LOCALHOST ONLY</div><button onClick={()=>setTheme(theme==='clean'?'noir':'clean')}>Soul & Together Switch: {theme==='clean'?'OFF':'ON'}</button><Nav/></aside><main>{children}</main></div>
}
