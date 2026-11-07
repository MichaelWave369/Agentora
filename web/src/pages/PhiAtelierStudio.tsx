import { useEffect, useRef, useState } from 'react'
const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8088'
import './PhiAtelierStudio.css'

type Job = { prompt_id: string; workflow_digest: string; status: string; image_ready: boolean; positive_prompt?: string; negative_prompt?: string; seed?: number }
type Plan = { workflow_digest: string; status: string; workflow: Record<string, unknown> }
type Criterion = 'subject_clarity'|'composition'|'symbolic_coherence'|'material_light'|'originality'
type Scores = Record<Criterion, number>
type Revision = { review_digest: string; revised_prompt: string; parent_job_id: string|null; requested_changes: string; observations: string; rubric: Scores }
type VisionObservations = {
  visible_subjects: string
  composition_observations: string
  lighting_color_observations: string
  prompt_alignment: string
  possible_issues: string
  specific_suggestions: string
  uncertainties: string
}
type VisionReport = {
  job_id: string
  image_sha256: string
  model: string
  origin: string
  review_status: string
  new_render_queued: boolean
  visual_quality_verified: boolean
  observations: VisionObservations
}
const criteria: { id: Criterion; label: string }[] = [
  {id:'subject_clarity',label:'Subject clarity'}, {id:'composition',label:'Composition'},
  {id:'symbolic_coherence',label:'Symbolic coherence'}, {id:'material_light',label:'Lighting and materials'},
  {id:'originality',label:'Originality'},
]
const initialScores: Scores = {subject_clarity:3,composition:3,symbolic_coherence:3,material_light:3,originality:3}

async function request<T>(path: string, body?: object, secret = ''): Promise<T> {
  const response = await fetch(API + path, {
    method: body ? 'POST' : 'GET',
    headers: {
      ...(body ? {'Content-Type':'application/json'} : {}),
      ...(secret ? {'X-Atelier-Operator-Key':secret} : {}),
    },
    ...(body ? {body: JSON.stringify(body)} : {}),
  })
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(typeof data?.detail === 'string' ? data.detail : 'Local API returned HTTP ' + response.status)
  }
  return data as T
}

export default function PhiAtelierStudio() {
  const [prompt,setPrompt] = useState('An original recursive glass city dreaming of its future, anchored by a clear human-scale focal point')
  const [negative,setNegative] = useState('watermark, broken anatomy, unwanted lettering')
  const [ratio,setRatio] = useState<'16:9'|'3:4'|'1:1'>('16:9')
  const [seed,setSeed] = useState(369)
  const [steps,setSteps] = useState(24)
  const [cfg,setCfg] = useState(7)
  const [draft,setDraft] = useState<Plan|null>(null)
  const [key,setKey] = useState('')
  const [approved,setApproved] = useState(false)
  const [jobs,setJobs] = useState<Job[]>([])
  const [images,setImages] = useState<Record<string,string>>({})
  const [imageTypes,setImageTypes] = useState<Record<string,string>>({})
  const imageUrls = useRef<Record<string,string>>({})
  const [compare,setCompare] = useState<string[]>([])
  const [target,setTarget] = useState<string|null>(null)
  const [scores,setScores] = useState<Scores>({...initialScores})
  const [notes,setNotes] = useState('')
  const [changes,setChanges] = useState('')
  const [reviews,setReviews] = useState<Revision[]>([])
  const [visionReports,setVisionReports] = useState<Record<string,VisionReport>>({})
  const [visionConsent,setVisionConsent] = useState(false)
  const [message,setMessage] = useState('')
  const [error,setError] = useState('')
  const [busy,setBusy] = useState(false)
  useEffect(() => () => { Object.values(imageUrls.current).forEach(URL.revokeObjectURL) }, [])
  const invalidate = () => { setDraft(null); setApproved(false) }
  const input = () => ({positive_prompt:prompt,negative_prompt:negative,aspect_ratio:ratio,seed,steps,cfg})
  const act = async (operation: () => Promise<void>) => {
    setBusy(true); setError(''); setMessage('')
    try { await operation() } catch(e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  const preview = () => act(async () => {
    const data = await request<{plan:Plan}>('/api/atelier/render-plan',input())
    setDraft(data.plan); setApproved(false)
    setMessage('Review the exact workflow and digest before approving a local render.')
  })
  const list = () => act(async () => {
    const data = await request<{items:Job[]}>('/api/atelier/studio/jobs',undefined,key)
    setJobs(data.items)
    setMessage('Showing this Agentora process only. Restarting the backend clears its job ledger.')
  })
  const submit = () => act(async () => {
    if (!draft || !approved) throw new Error('Review and approve the current draft first.')
    const data = await request<{job:Job}>('/api/atelier/render/submit',{
      ...input(),workflow_digest:draft.workflow_digest,approve_gpu_render:true,
    },key)
    setJobs(old => [data.job,...old.filter(x=>x.prompt_id!==data.job.prompt_id)])
    setApproved(false)
    setMessage('Queued one job. Use Check status to monitor it.')
  })
  const status = (id:string) => act(async () => {
    const data = await request<{job:Job}>('/api/atelier/render/'+encodeURIComponent(id)+'/status',undefined,key)
    setJobs(old=>old.map(x=>x.prompt_id===id?data.job:x))
    setMessage('Observed job status: '+data.job.status)
  })
  const image = (id:string) => act(async () => {
    const res = await fetch(API+'/api/atelier/render/'+encodeURIComponent(id)+'/image',{
      headers:{'X-Atelier-Operator-Key':key},
    })
    if (!res.ok) throw new Error('Private image retrieval failed (HTTP '+res.status+')')
    const blob = await res.blob()
    if (!['image/png','image/jpeg','image/webp'].includes(blob.type)) throw new Error('Unsupported image type')
    const url = URL.createObjectURL(blob)
    if (imageUrls.current[id]) URL.revokeObjectURL(imageUrls.current[id])
    imageUrls.current[id]=url; setImages(old=>({...old,[id]:url})); setImageTypes(old=>({...old,[id]:blob.type}))
    setMessage('Image loaded privately in this browser tab.')
  })
  const cancel = (id:string) => act(async () => {
    const data = await request<{job:Job}>('/api/atelier/render/'+encodeURIComponent(id)+'/cancel',{confirm_cancel:true},key)
    setJobs(old=>old.map(x=>x.prompt_id===id?data.job:x))
    setMessage('Cancellation requested, not yet verified.')
  })
  const revise = () => act(async () => {
    const data = await request<{revision:Revision}>('/api/atelier/studio/revision',{
      original_prompt:jobs.find(job=>job.prompt_id===target)?.positive_prompt||prompt,scores,observations:notes,requested_changes:changes,parent_job_id:target,
    })
    setReviews(old=>[data.revision,...old])
    setPrompt(data.revision.revised_prompt)
    setSeed(n=>n===4294967295?0:n+1)
    invalidate()
    setMessage('New draft prepared. No GPU work was started. Preview and approve again to render.')
  })
  const reviewVision = (id: string) => act(async () => {
    if (!visionConsent) throw new Error('Approve exactly one local vision-model call first.')
    const data = await request<{report:VisionReport}>(
      '/api/atelier/studio/vision/'+encodeURIComponent(id),
      {confirm_local_model_call:true},key)
    setVisionReports(old=>({...old,[id]:data.report}))
    setVisionConsent(false)
    setMessage('Local model supplied a fallible critique. Review its observations before reusing suggestions. No new render was queued.')
  })
  const useVisionNotes = (id: string) => {
    const report=visionReports[id]
    if (!report) return
    setChanges(report.observations.specific_suggestions.slice(0,700))
    setNotes(('Model-only observations: '+report.observations.possible_issues+' Uncertainty: '+report.observations.uncertainties).slice(0,1000))
    setTarget(id)
    setMessage('Copied AI suggestions into editable human-review fields; nothing was rendered or accepted automatically.')
  }

  const exportReviews = () => {
    if (!reviews.length) return
    const blob = new Blob([JSON.stringify({schema_version:'phi.atelier.feedback.v1',reviews},null,2)],{type:'application/json'})
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = 'phi-atelier-feedback.json'; link.click()
    URL.revokeObjectURL(url)
  }
  const toggleCompare = (id:string) => setCompare(current=>
    current.includes(id)?current.filter(x=>x!==id):[...current.slice(-1),id])

  return <div className="atelier">
    <header className="atelier-hero">
      <div><p className="atelier-kicker">PHI369 LABS · LOCAL CREATIVE WORKSPACE</p>
        <h2>ΦAtelier · Artist's Studio</h2>
        <p>Compose → approve → render → compare → critique → revise.</p></div>
      <span>LOCAL · EXPLICIT APPROVAL</span>
    </header>
    <p className="atelier-hint">This is a private, manual workstation workflow. The operator key stays in this tab's memory, not in saved reviews. Rendering is disabled unless configured on the local server.</p>
    {error && <p role="alert" className="atelier-error">{error}</p>}
    {message && <p role="status" className="atelier-notice">{message}</p>}

    <section className="atelier-panel">
      <h3>01 · Composition</h3>
      <label htmlFor="atelier-prompt">Image direction</label>
      <textarea id="atelier-prompt" rows={4} maxLength={3000} value={prompt} onChange={e=>{setPrompt(e.target.value);invalidate()}} />
      <label htmlFor="atelier-negative">Avoid</label>
      <textarea id="atelier-negative" rows={2} maxLength={850} value={negative} onChange={e=>{setNegative(e.target.value);invalidate()}} />
      <div className="atelier-fields">
        <label>Aspect
          <select value={ratio} onChange={e=>{setRatio(e.target.value as '16:9'|'3:4'|'1:1');invalidate()}}>
            <option value="16:9">Landscape 16:9</option><option value="3:4">Portrait 3:4</option><option value="1:1">Square 1:1</option>
          </select>
        </label>
        <label>Seed<input type="number" min="0" max="4294967295" value={seed} onChange={e=>{setSeed(Number(e.target.value));invalidate()}} /></label>
        <label>Steps<input type="number" min="8" max="40" value={steps} onChange={e=>{setSteps(Number(e.target.value));invalidate()}} /></label>
        <label>Guidance<input type="number" min="1" max="12" step="0.5" value={cfg} onChange={e=>{setCfg(Number(e.target.value));invalidate()}} /></label>
      </div>
      <button disabled={busy} onClick={preview}>Preview exact ComfyUI workflow</button>
      {draft && <div className="atelier-draft">
        <strong>{draft.status}</strong>
        <p>Digest <code>{draft.workflow_digest}</code></p>
        <details><summary>Inspect graph</summary><pre>{JSON.stringify(draft.workflow,null,2)}</pre></details>
      </div>}
    </section>

    <section className="atelier-panel">
      <h3>02 · Approve one GPU job</h3>
      <label htmlFor="atelier-key">Local operator key (not stored)</label>
      <input id="atelier-key" type="password" autoComplete="off" value={key} onChange={e=>setKey(e.target.value)} />
      <label className="atelier-check"><input type="checkbox" checked={approved} disabled={!draft} onChange={e=>setApproved(e.target.checked)} /> I reviewed this exact graph and approve one local GPU render</label>
      <div className="atelier-actions">
        <button disabled={busy||!draft||!approved||!key} onClick={submit}>Submit one render</button>
        <button className="atelier-secondary" disabled={busy||!key} onClick={list}>Refresh local gallery</button>
      </div>
    </section>

    <section className="atelier-panel">
      <h3>03 · Gallery and side-by-side comparison</h3>
      <p className="atelier-hint">Image previews are loaded only when requested. They are not uploaded or automatically saved to a shared gallery.</p>
      {jobs.length===0 && <p>No jobs in this process. Preview and approve a render to start.</p>}
      <div className="atelier-grid">
        {jobs.map(job=><article className="atelier-tile" key={job.prompt_id}>
          <div className="atelier-thumb">{images[job.prompt_id]
            ? <img src={images[job.prompt_id]} alt={'Artwork render '+job.prompt_id} />
            : <span>PREVIEW NOT LOADED</span>}</div>
          <strong>{job.status}</strong>
          <small>{job.prompt_id}</small>
          <div className="atelier-actions">
            <button disabled={busy} className="atelier-secondary" onClick={()=>status(job.prompt_id)}>Check status</button>
            <button disabled={busy||!job.image_ready} onClick={()=>image(job.prompt_id)}>View image</button>
            {images[job.prompt_id]&&<a className="atelier-download" download={'PhiAtelier-'+job.prompt_id+(imageTypes[job.prompt_id]==='image/jpeg'?'.jpg':imageTypes[job.prompt_id]==='image/webp'?'.webp':'.png')} href={images[job.prompt_id]}>Save local copy</a>}
            {(job.status==='queued'||job.status==='running')&&<button disabled={busy} className="atelier-secondary" onClick={()=>cancel(job.prompt_id)}>Request cancel</button>}
          </div>
          <label className="atelier-check"><input type="checkbox" checked={compare.includes(job.prompt_id)} onChange={()=>toggleCompare(job.prompt_id)} /> Compare</label>
          <button className="atelier-secondary" onClick={()=>{setTarget(job.prompt_id);setVisionConsent(false)}}>Review this result</button>
          {job.image_ready && <button className="atelier-secondary" onClick={()=>{setTarget(job.prompt_id);setVisionConsent(false)}}>Select for vision critique</button>}
        </article>)}
      </div>
      {compare.length===2&&<div className="atelier-compare" aria-label="Side-by-side comparison">
        {compare.map(id=><figure key={id}>
          {images[id]?<img src={images[id]} alt={'Comparison render '+id} />:<p>Load this image above to compare.</p>}
          <figcaption>{id}</figcaption>
        </figure>)}
      </div>}
    </section>

    <section className="atelier-panel">
      <h3>04 · Human critique and revision</h3>
      <p className="atelier-hint">{target?'Reviewing '+target:'No render selected. You can review the concept alone.'} Ratings are your observations, not AI-verified artistic quality.{target&&jobs.find(job=>job.prompt_id===target)?.positive_prompt&&<span className="atelier-target"><strong>Original job prompt:</strong> {jobs.find(job=>job.prompt_id===target)?.positive_prompt}</span>}</p>
      {target && jobs.some(job=>job.prompt_id===target && job.image_ready) && <div className="atelier-vision">
        <h4>Optional · Local model vision critique</h4>
        <p className="atelier-hint">Sends the selected completed image only to a local Ollama vision model. This costs GPU resources. Its conclusions can be inaccurate and will not update prompts or render automatically.</p>
        <label className="atelier-check"><input type="checkbox" checked={visionConsent} onChange={e=>setVisionConsent(e.target.checked)} />
          I approve one local vision analysis of this rendered image</label>
        <button disabled={busy||!key||!visionConsent} onClick={()=>reviewVision(target)}>Analyze selected image once</button>
        {visionReports[target] && <div className="atelier-vision-result">
          <strong>Local model observations (not verified)</strong>
          <p className="atelier-hint">Model: {visionReports[target].model} · Image: {visionReports[target].image_sha256.slice(0,25)}… · New render queued: no</p>
          <dl>
            <dt>Visible subjects</dt><dd>{visionReports[target].observations.visible_subjects}</dd>
            <dt>Composition</dt><dd>{visionReports[target].observations.composition_observations}</dd>
            <dt>Light and color</dt><dd>{visionReports[target].observations.lighting_color_observations}</dd>
            <dt>Prompt alignment</dt><dd>{visionReports[target].observations.prompt_alignment}</dd>
            <dt>Possible issues</dt><dd>{visionReports[target].observations.possible_issues}</dd>
            <dt>Suggestions</dt><dd>{visionReports[target].observations.specific_suggestions}</dd>
            <dt>Uncertainties</dt><dd>{visionReports[target].observations.uncertainties}</dd>
          </dl>
          <button className="atelier-secondary" onClick={()=>useVisionNotes(target)}>Copy suggestions into editable human review</button>
        </div>}
      </div>}
      <div className="atelier-fields">
        {criteria.map(item=><label key={item.id}>{item.label}
          <select value={scores[item.id]} onChange={e=>setScores(old=>({...old,[item.id]:Number(e.target.value)}))}>
            {[1,2,3,4,5].map(n=><option key={n} value={n}>{n} / 5</option>)}
          </select>
        </label>)}
      </div>
      <label htmlFor="atelier-notes">What worked and what didn't?</label>
      <textarea id="atelier-notes" rows={3} maxLength={1000} value={notes} onChange={e=>setNotes(e.target.value)} />
      <label htmlFor="atelier-changes">Requested changes for the next draft</label>
      <textarea id="atelier-changes" rows={3} maxLength={700} value={changes} onChange={e=>setChanges(e.target.value)} />
      <div className="atelier-actions">
        <button disabled={busy||!changes.trim()} onClick={revise}>Create revised prompt (no render)</button>
        <button disabled={!reviews.length} className="atelier-secondary" onClick={exportReviews}>Export feedback JSON</button>
      </div>
      <p className="atelier-hint">{reviews.length} local browser review receipts. Export if you want to retain them after closing this tab.</p>
    </section>
  </div>
}
