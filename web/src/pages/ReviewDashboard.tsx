import { useEffect, useState } from 'react'

/**
 * R2.3 client-side public GitHub evidence viewer.
 * Workflow status is NOT a verified merge or execution receipt.
 * Exact merge/handoff verification happens only in the read-only Actions report.
 */
const REPO = 'MichaelWave369/Agentora'
const ROOT = 'https://api.github.com/repos/' + REPO
const ACTIONS = 'https://github.com/' + REPO + '/actions/workflows/'
const DASHBOARD_WORKFLOW = ACTIONS + 'devloop-r23-dashboard.yml'

const WORKFLOWS = [
  { key: 'merge', file: 'devloop-automerge.yml', title: 'Merge decision runs' },
  { key: 'handoff', file: 'devloop-r2-handoff.yml', title: 'Post-merge handoff runs' },
  { key: 'queue', file: 'devloop-r22-review-queue.yml', title: 'Review queue snapshots' }
] as const
type Category = typeof WORKFLOWS[number]['key']

type PublicPR = {
  number: number; title: string; html_url: string; draft: boolean
  head?: { sha: string }; labels?: { name: string }[]
}
type WorkflowRun = {
  id: number; name: string; html_url: string; created_at: string
  status: string; conclusion: string | null; event: string
}
type WorkflowResponse = { workflow_runs: WorkflowRun[]; total_count: number }

type View = {
  fetchedAt: string; openPRs: PublicPR[]
  runs: Record<Category, WorkflowRun[]>
  prListPartial: boolean; runListPartial: boolean
}

async function readPublic<T>(path: string): Promise<T> {
  const response = await fetch(ROOT + path, {
    method: 'GET',
    headers: { Accept: 'application/vnd.github+json' }
  })
  if (!response.ok) {
    throw new Error(response.status === 403
      ? 'GitHub rate limit or access restriction'
      : 'GitHub HTTP ' + response.status)
  }
  return response.json() as Promise<T>
}

function formatUTC(value: string) {
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? 'Unknown time' : d.toLocaleString()
}

export default function ReviewDashboard() {
  const [view, setView] = useState<View | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = async () => {
    setBusy(true)
    setError(null)
    // A refresh never presents stale data as a new successful read.
    setView(null)
    try {
      const [openPRs, ...workflowResponses] = await Promise.all([
        readPublic<PublicPR[]>('/pulls?state=open&per_page=100'),
        ...WORKFLOWS.map(w =>
          readPublic<WorkflowResponse>('/actions/workflows/' + w.file + '/runs?per_page=12'))
      ])
      if (!Array.isArray(openPRs) || workflowResponses.length !== WORKFLOWS.length ||
          workflowResponses.some(r => !Array.isArray(r.workflow_runs))) {
        throw new Error('Incomplete GitHub response')
      }
      const runs = {
        merge: workflowResponses[0].workflow_runs,
        handoff: workflowResponses[1].workflow_runs,
        queue: workflowResponses[2].workflow_runs
      }
      setView({
        fetchedAt: new Date().toISOString(),
        openPRs,
        runs,
        prListPartial: openPRs.length >= 100,
        runListPartial: workflowResponses.some(r => r.total_count > r.workflow_runs.length)
      })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Evidence fetch unavailable')
    } finally {
      setBusy(false)
    }
  }
  useEffect(() => { void refresh() }, [])

  return <section className="review-dashboard">
    <header>
      <h2>Φ Solo Sovereign Review Dashboard</h2>
      <p>One read-only view of open PRs and recent GitHub Actions activity. A green workflow
        is not proof a PR merged. The browser-only audit report cross-checks actual merge
        records and retained receipts.</p>
      <div className="review-head">
        <a href={DASHBOARD_WORKFLOW} target="_blank" rel="noreferrer">
          Open full evidence report in GitHub Actions
        </a>
        <button type="button" disabled={busy} onClick={() => void refresh()}>
          {busy ? 'Reading GitHub…' : 'Refresh dashboard'}
        </button>
      </div>
    </header>

    <div className="card">
      <h3>Browser-only audit</h3>
      <p>In GitHub Actions, choose <strong>Run workflow</strong>, then open the run's
        <strong> Summary</strong>. It verifies retained merge-decision receipts against
        GitHub's actual PR records, reviews post-merge handoffs, and includes today's
        review queue. The JSON report is saved as an artifact.</p>
      <p className="review-caution">This page cannot apply labels, approve or merge PRs,
        trigger another job, or launch the next task. Authorization stays in GitHub.</p>
    </div>

    {error && <div className="card" role="alert">
      <strong>Evidence unavailable: {error}</strong>
      <p>No status is implied while GitHub is unavailable or rate-limited.</p>
    </div>}
    {busy && <p role="status">Reading live public GitHub metadata…</p>}

    {view && <>
      <p>Captured {formatUTC(view.fetchedAt)} · GitHub public read-only API</p>
      {(view.prListPartial || view.runListPartial) && <p role="alert">
        Bounded sample only. Additional PRs or historical workflow runs may exist.
        Use the Actions audit to inspect the scoped report.
      </p>}
      <div className="review-metrics">
        <div><small>Open PRs observed</small><strong>{view.openPRs.length}{view.prListPartial ? '+' : ''}</strong></div>
        <div><small>Merge runs sampled</small><strong>{view.runs.merge.length}</strong></div>
        <div><small>Handoff runs sampled</small><strong>{view.runs.handoff.length}</strong></div>
        <div><small>Queue reports sampled</small><strong>{view.runs.queue.length}</strong></div>
      </div>
      <div className="card">
        <div className="review-head">
          <h3>Open PRs</h3>
          <a href={'https://github.com/' + REPO + '/pulls'} target="_blank" rel="noreferrer">
            View all on GitHub
          </a>
        </div>
        {view.openPRs.length === 0 && <p>There are no open PRs in this snapshot.</p>}
        {view.openPRs.map(pr => <div className="review-entry" key={pr.number}>
          <div>
            <strong>#{pr.number} · {pr.title}</strong>
            <p>{pr.draft ? 'Draft · ' : ''}Head {pr.head?.sha?.slice(0, 12) || 'UNVERIFIED'} ·
              {' '}{(pr.labels || []).map(l => l.name).join(', ') || 'No labels'}</p>
          </div>
          <a href={pr.html_url} target="_blank" rel="noreferrer">Review PR</a>
        </div>)}
        <p><a href={'https://github.com/' + REPO + '/pulls'} target="_blank" rel="noreferrer">
          Review exact diffs on GitHub
        </a></p>
        <p><a href={'https://github.com/' + REPO + '/blob/main/docs/DEVELOPMENT_LOOP_R22_REVIEW_QUEUE.md'}
          target="_blank" rel="noreferrer">Owner authorization runbook</a></p>
      </div>

      {WORKFLOWS.map(w => <div className="card" key={w.key}>
        <div className="review-head">
          <h3>{w.title}</h3>
          <a href={ACTIONS + w.file} target="_blank" rel="noreferrer">All runs</a>
        </div>
        <p>Workflow status only. Open a run to verify its receipt; never infer a merge
          or an executed handoff from the workflow outcome alone.</p>
        {view.runs[w.key].length === 0 && <p>No recent runs in this sample.</p>}
        <div className="review-run-history">
          {view.runs[w.key].map(run => <div className="review-run" key={run.id}>
            <div>
              <strong>Run #{run.id}</strong>
              <p>{formatUTC(run.created_at)} · {run.event}</p>
            </div>
            <span>{run.status === 'completed'
              ? (run.conclusion || 'UNKNOWN').toUpperCase() : 'IN PROGRESS'}</span>
            <a href={run.html_url} target="_blank" rel="noreferrer">Inspect run</a>
          </div>)}
        </div>
      </div>)}
    </>}
  </section>
}
