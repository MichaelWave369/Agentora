import { Link } from 'react-router-dom'
export default function Nav(){
  const items=['/','/agents','/teams','/studio','/runs','/settings']
  return <nav>{items.map(i=><Link key={i} to={i}>{i==='/'?'dashboard':i.slice(1)}</Link>)}</nav>
}
