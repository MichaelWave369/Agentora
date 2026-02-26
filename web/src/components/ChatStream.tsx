export default function ChatStream({messages}:{messages:any[]}){return <div className='card'><h3>Live Stream</h3>{messages.map((m,i)=><p key={i}><b>{m.role}</b>: {m.content}</p>)}</div>}
