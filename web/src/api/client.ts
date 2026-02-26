const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
export async function api(path: string, init?: RequestInit){
  const r = await fetch(`${API}${path}`, { headers:{'Content-Type':'application/json'}, ...init })
  return r.json()
}
export { API }
