import { useEffect, useState } from 'react';import { api } from '../api/client'
export default function Analytics(){const [o,setO]=useState<any>({});useEffect(()=>{api('/api/analytics/overview').then(setO)},[]);return <div><h2>Analytics</h2><pre>{JSON.stringify(o,null,2)}</pre></div>}
