export default function YamlEditor({value,onChange}:{value:string,onChange:(v:string)=>void}){return <textarea value={value} onChange={e=>onChange(e.target.value)} rows={18}/>}
