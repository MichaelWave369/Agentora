import { Link } from 'react-router-dom'
export default function Nav(){
  const items=[['/','dashboard'],['/studio-mode','studio'],['/band-mode','band'],['/arena-mode','arena'],['/agents','agents'],['/teams','teams'],['/marketplace','marketplace'],['/studio','run studio'],['/runs','runs'],['/analytics','analytics'],['/settings','settings']]
  return <nav>{items.map(i=><Link key={i[0]} to={i[0]}>{i[1]}</Link>)}</nav>
}
