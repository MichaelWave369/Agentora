import { PropsWithChildren } from 'react'
import Nav from './Nav'
export default function AppShell({children}:PropsWithChildren){
  return <div className='shell'><aside><h1>Agentora</h1><div className='badge'>LOCALHOST ONLY</div><Nav/></aside><main>{children}</main></div>
}
