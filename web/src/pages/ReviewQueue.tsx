import { useEffect, useState } from 'react'

/** R2.2 read-only public GitHub view; it never grants merge authority. */
const REPO = 'MichaelWave369/Agentora'
const API = 'https://api.github.com/repos/' + REPO
const WORKFLOW = 'https://github.com/' + REPO + '/actions/workflows/devloop-r22-review-queue.yml'
const REQUIRED = ['backend (3.12)', 'backend (3.13)', 'web']
const HOLDS = ['hold', 'do-not-merge', 'needs-review', 'security-review']
const APPROVAL_LABELS = ['phi-automerge', 'phi-solo-automerge', 'phi-code-automerge']

type Pull = {
  number: number; title: string; html_url: string; draft: boolean; state: string
  changed_files?: number; user?: { login: string }
  head?: { sha: string; repo?: { full_name: string } }
  base?: { ref: string; repo?: { full_name: string } }
  labels?: { name: string }[]
}
type Changed = {
  filename: string; status: string; additions: number
  deletions: number; patch?: string
}
type Check = {
  name: string; status: string; conclusion: string | null
  app?: { slug: string }
}
type CheckResponse = { total_count: number; check_runs: Check[] }
type Ruleset = {
  id: number; target?: string; enforcement?: string
  conditions?: { ref_name?: { include?: string[] } }
  rules?: { type: string; parameters?: { required_status_checks?: { context: string }[] } }[]
}
type Inspection = {
  headSha: string; lane: string; risk: string; status: string
  nextAction: string; checks: { name: string; state: string }[]
  overallCI: string; mainRules: string; filenames: string[]
}

async function readPublic<T>(path: string): Promise<T> {
  const response = await fetch(API + path, {
    method: 'GET', headers: { Accept: 'application/vnd.github+json' }
  })
  if (!response.ok) {
    throw new Error(response.status === 403
      ? 'GitHub API rate limit or access restriction'
      : 'GitHub HTTP ' + response.status)
  }
  return response.json() as Promise<T>
}

async function hasRequiredRules(): Promise<boolean> {
  const list = await readPublic<Ruleset[]>('/rulesets?includes_parents=true')
  if (!Array.isArray(list) || list.length >= 100) return false
  const contexts = new Set<string>()
  for (const r of list) {
    if (r.enforcement !== 'active') continue
    const d = await readPublic<Ruleset>('/rulesets/' + r.id)
    const includes = d.conditions?.ref_name?.include || []
    if (d.target !== 'branch' || d.enforcement !== 'active' ||
        !includes.some(s => ['~DEFAULT_BRANCH', 'main', 'refs/heads/main'].includes(s))) continue
    for (const rule of d.rules || []) {
      if (rule.type !== 'required_status_checks') continue
      for (const entry of rule.parameters?.required_status_checks || []) {
        contexts.add(entry.context)
      }
    }
  }
  return REQUIRED.every(s => contexts.has(s))
}

function checkEvidence(data: CheckResponse) {
  const names = REQUIRED.map(name => {
    let state = 'GREEN'
    const entries = data?.check_runs?.filter(c => c.name === name) || []
    if (!entries.length) state = 'MISSING'
    else if (entries.some(c => c.app?.slug !== 'github-actions')) state = 'UNVERIFIED'
    else if (entries.some(c => c.status !== 'completed')) state = 'PENDING'
    else if (entries.some(c => c.conclusion !== 'success')) state = 'FAILED'
    return { name, state }
  })
  if (!data || !Number.isInteger(data.total_count) || data.total_count >= 100 ||
      !Array.isArray(data.check_runs) || data.check_runs.length !== data.total_count) {
    return { overall: 'UNVERIFIED', names: REQUIRED.map(name => ({ name, state: 'UNVERIFIED' })) }
  }
  const statuses = names.map(n => n.state)
  const overall = statuses.every(s => s === 'GREEN') ? 'GREEN'
    : statuses.includes('UNVERIFIED') ? 'UNVERIFIED'
    : statuses.includes('FAILED') ? 'FAILED'
    : statuses.includes('PENDING') ? 'PENDING' : 'MISSING'
  return { overall, names }
}

function classify(p: Pull, files: Changed[]) {
  const manual = { lane: 'MANUAL', risk: 'Unclassified or outside trusted automated policy',
                   label: null as string | null }
  if (p.state !== 'open' || p.draft || p.base?.ref !== 'main' ||
      p.base?.repo?.full_name !== REPO || p.head?.repo?.full_name !== REPO ||
      p.changed_files !== files.length || !files.length || files.length > 10) return manual
  const docs = files.every(f => {
    if (!['modified', 'added'].includes(f.status) || f.filename.length > 240) return false
    if (f.filename === 'README.md') return true
    const parts = f.filename.split('/')
    return parts.length >= 2 && parts[0] === 'docs' && f.filename.endsWith('.md') &&
      parts.every(part => part !== '' && part !== '.' && part !== '..')
  })
  if (docs) return { lane: 'DOCS', risk: 'Documentation only, not a security review',
                     label: 'phi-automerge' }

  const allowed = ['web/src/components/Nav.tsx', 'web/src/components/TemplateGallery.tsx']
  const small = files.length <= 2 && files.every(f =>
    allowed.includes(f.filename) && f.status === 'modified' &&
    typeof f.patch === 'string' && f.patch.startsWith('@@') &&
    f.patch.length <= 12000 && Number.isInteger(f.additions) &&
    Number.isInteger(f.deletions) && f.additions >= 0 && f.deletions >= 0)
  const added = files.reduce((n, f) => n + f.additions, 0)
  const removed = files.reduce((n, f) => n + f.deletions, 0)
  if (!small || new Set(files.map(f => f.filename)).size !== files.length ||
      added > 75 || removed > 40 || added + removed > 100) return manual
  if (files.length === 1 && files[0].filename === 'web/src/components/Nav.tsx' &&
      p.user?.login === 'MichaelWave369' &&
      added <= 10 && removed <= 10 && added + removed <= 16) {
    return { lane: 'SOLO', risk: 'Tiny owner UI, no independent code review',
             label: 'phi-solo-automerge' }
  }
  return { lane: 'REVIEWED CODE', risk: 'Small UI, separate human review required',
           label: 'phi-code-automerge' }
}

export default function ReviewQueue() {
  const [prs, setPrs] = useState<Pull[]>([])
  const [loading, setLoading] = useState(false)
  const [inspecting, setInspecting] = useState(false)
  const [selected, setSelected] = useState<number | null>(null)
  const [details, setDetails] = useState<Inspection | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [truncated, setTruncated] = useState(false)
  const [lastRead, setLastRead] = useState<string | null>(null)

  const reload = async () => {
    setLoading(true)
    setError(null)
    setSelected(null)
    setDetails(null)
    try {
      const list = await readPublic<Pull[]>('/pulls?state=open&per_page=100&sort=updated&direction=desc')
      if (!Array.isArray(list)) throw new Error('Invalid PR list')
      setPrs(list)
      setTruncated(list.length === 100)
      setLastRead(new Date().toLocaleString())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'GitHub unavailable')
      setPrs([])
    } finally { setLoading(false) }
  }
  useEffect(() => { void reload() }, [])

  const inspect = async (number: number) => {
    setSelected(number)
    setDetails(null)
    setError(null)
    setInspecting(true)
    try {
      const p = await readPublic<Pull>('/pulls/' + number)
      const sha = p.head?.sha || ''
      const count = p.changed_files
      const files = Number.isInteger(count) && typeof count === 'number' && count >= 1 && count <= 10
        ? await readPublic<Changed[]>('/pulls/' + number + '/files?per_page=100')
        : []
      const [checks, rules] = await Promise.all([
        /^[a-f0-9]{40}$/.test(sha)
          ? readPublic<CheckResponse>('/commits/' + sha + '/check-runs?per_page=100')
          : Promise.resolve({ total_count: 0, check_runs: [] }),
        hasRequiredRules().catch(() => false)
      ])
      const check = checkEvidence(checks)
      const category = classify(p, files)
      const labels = new Set((p.labels || []).map(l => l.name.toLowerCase()))
      const conflicting = APPROVAL_LABELS.filter(label => labels.has(label)).length > 1 ||
        HOLDS.some(label => labels.has(label))
      let status = 'OWNER REVIEW REQUIRED'
      let next = 'Inspect exact diff and SHA, then personally apply ' + category.label
      if (category.lane === 'MANUAL') {
        status = 'MANUAL REVIEW'
        next = 'Outside the automated lanes. Review and merge manually.'
      } else if (conflicting) {
        status = 'HELD'
        next = 'Resolve hold or conflicting labels. Reinspect before authorizing.'
      } else if (!rules) {
        status = 'RULES UNVERIFIED'
        next = 'Verify the three required main-branch checks on GitHub.'
      } else if (check.overall !== 'GREEN') {
        status = 'CI ' + check.overall
        next = 'Wait for or fix CI. Do not authorize a merge yet.'
      } else if (category.lane === 'REVIEWED CODE') {
        status = 'INDEPENDENT REVIEW REQUIRED'
        next = 'Obtain a current-SHA GitHub approval from a trusted collaborator.'
      } else if (category.label && labels.has(category.label)) {
        status = 'LABEL PRESENT'
        next = 'Inspect governance Actions and receipt. Never blindly reapply a label.'
      }
      setDetails({
        headSha: sha, lane: category.lane, risk: category.risk,
        status, nextAction: next, checks: check.names, overallCI: check.overall,
        mainRules: rules ? 'VERIFIED' : 'UNVERIFIED',
        filenames: Array.isArray(files) ? files.map(f => f.filename) : []
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Inspection unavailable')
    } finally { setInspecting(false) }
  }

  return <section className="review-queue">
    <h2>Φ Solo Sovereign Review Queue</h2>
    <p>Live read-only GitHub evidence. This page never labels, approves, dispatches,
      executes code or merges PRs. A candidate is not permission to ship.</p>
    <div className="card">
      <h3>Browser-only GitHub Actions queue</h3>
      <p>Without a local Agentora server, open the workflow, select <strong>Run workflow</strong>,
        then view the resulting <strong>Summary</strong>. Its JSON snapshot is attached as an artifact.</p>
      <a href={WORKFLOW} target="_blank" rel="noreferrer">Open queue workflow</a>
    </div>
    <div className="card">
      <div className="review-head">
        <h3>Open pull requests</h3>
        <button type="button" disabled={loading} onClick={() => void reload()}>
          {loading ? 'Reading…' : 'Refresh'}
        </button>
      </div>
      <p>Public GitHub API · no saved credentials · {lastRead || 'Not yet refreshed'}</p>
      {truncated && <p role="alert">100 PRs shown. The queue may be incomplete; use the Actions report.</p>}
      {error && <p role="alert">{error}. Unverified evidence cannot justify approval.</p>}
      {!loading && !error && prs.length === 0 && <p>No open PRs right now.</p>}
      {prs.map(pr => <div key={pr.number} className="review-entry">
        <div>
          <strong>#{pr.number}: {pr.title}</strong>
          <p>{pr.draft ? 'DRAFT · ' : ''}{pr.user?.login || 'Unknown author'} ·
            {' '}{pr.head?.sha?.slice(0, 12) || 'Unknown SHA'}</p>
        </div>
        <div className="review-entry-actions">
          <button type="button" disabled={inspecting} onClick={() => void inspect(pr.number)}>
            Inspect evidence
          </button>
          <a href={pr.html_url} target="_blank" rel="noreferrer">Open PR</a>
        </div>
      </div>)}
    </div>
    {selected !== null && <div className="card" aria-live="polite">
      <h3>PR #{selected} · Exact-head inspection</h3>
      {inspecting && <p>Reading files, CI and branch protections…</p>}
      {details && !inspecting && <>
        <div className="review-metrics">
          <div><small>Queue status</small><strong>{details.status}</strong></div>
          <div><small>Candidate lane</small><strong>{details.lane}</strong></div>
          <div><small>Required CI</small><strong>{details.overallCI}</strong></div>
          <div><small>Branch rules</small><strong>{details.mainRules}</strong></div>
        </div>
        <p><strong>Scope:</strong> {details.risk}</p>
        <p><strong>Exact SHA:</strong> <code>{details.headSha}</code></p>
        <p><strong>Files:</strong> {details.filenames.join(', ') || 'Unavailable or outside bounded scope'}</p>
        <ul>{details.checks.map(c => <li key={c.name}>{c.name}: {c.state}</li>)}</ul>
        <p><strong>Next step:</strong> {details.nextAction}</p>
        <p><a href={'https://github.com/' + REPO + '/pull/' + selected + '/files'}
          target="_blank" rel="noreferrer">Review the diff on GitHub</a></p>
        <p className="review-caution">Advisory only. Check live GitHub state and review every change.
          Only your separate owner-applied label can authorize the trusted merge workflow.</p>
      </>}
    </div>}
  </section>
}
