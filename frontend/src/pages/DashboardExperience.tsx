import { useEffect, useState, type FormEvent } from 'react'
import {
  ArrowDown, ArrowLeft, ArrowRight, ArrowUp, BookOpen, Bot, BriefcaseBusiness,
  Check, ChevronRight, ClipboardList, Code2, Copy, FileDown, FilePlus2, FileText,
  History, LayoutDashboard, LockKeyhole, LogOut, Plus, Search, Settings2, Trash2, Save,
  UserRound,
} from 'lucide-react'
import {
  archiveAssessment, createAssessmentDraft, deleteAssessmentDraft,
  fetchAssessment, fetchOwnedAssessments, fetchAssessmentResults, fetchCandidateAttemptReport,
  fetchEvaluatorAttemptReport, saveManualQuestionReview, publishAssessment, rotateAssessmentAccessCode,
  updateAssessmentDraft, fetchCandidateAssessment, fetchCandidateAssessments,
  fetchCandidateAttempts, startCandidateAttempt, verifyCandidateAccessCode,
  generateAssessmentQuestionDrafts,
  generateFollowUpInterview, fetchFollowUpInterview, saveFollowUpAnswer, submitFollowUpInterview,
  fetchEvaluatorFollowUpInterview, addEvaluatorFollowUpQuestion, reviewFollowUpInterview,
  type AssessmentDraftPayload, type AssessmentRecord, type AssessmentSummaryRecord,
  type CandidateAssessmentRecord, type CandidateAttemptRecord, type AssessmentResultsRecord,
  type EvaluationQuestionResultRecord, type AssessmentQuestionType,
  type FollowUpInterviewRecord,
} from '../services/api'
import './DashboardExperience.css'
import './EvaluatorResults.css'

type Role = 'candidate' | 'evaluator'
type AccessMode = 'open' | 'restricted'
type QuestionKind = 'programming' | 'debugging' | 'explanation' | 'multiple-choice'
type Difficulty = 'easy' | 'medium' | 'hard'
type CreationMode = 'ai' | 'manual'
type RouteProps = {
  role: Role
  pathname: string
  navigate: (path: string) => void
  onSignOut: () => void
  email?: string
  hasSession: boolean
  authLoading: boolean
  backendStatus: string
  checkBackend: () => void
  accessToken?: string
}

type TestCaseDraft = { input: string; expectedOutput: string; visibility: 'public' | 'hidden' }
type QuestionDraft = {
  id: string
  serverId?: string
  title: string
  prompt: string
  kind: QuestionKind
  difficulty: Difficulty
  points: string
  answerOptions: string
  correctAnswer: string
  allowedLanguages: string[]
  timeLimitSeconds: string
  problem: string
  examples: string
  testCases: TestCaseDraft[]
}

const candidateLinks = [
  { label: 'Dashboard', path: '/candidate/dashboard', icon: LayoutDashboard },
  { label: 'Tests', path: '/candidate/tests', icon: Code2 },
  { label: 'History', path: '/candidate/history', icon: History },
  { label: 'My Progress', path: '/candidate/progress', icon: BookOpen },
  { label: 'Profile', path: '/candidate/profile', icon: UserRound },
]
const evaluatorLinks = [
  { label: 'Dashboard', path: '/evaluator/dashboard', icon: LayoutDashboard },
  { label: 'Create Test', path: '/evaluator/create-test', icon: FilePlus2 },
  { label: 'Tests / Test Data', path: '/evaluator/tests', icon: ClipboardList },
  { label: 'History', path: '/evaluator/history', icon: History },
  { label: 'Results & Reports', path: '/evaluator/reports', icon: FileText },
  { label: 'Profile', path: '/evaluator/profile', icon: UserRound },
]

export function DashboardExperience(props: RouteProps) {
  const { role, pathname } = props
  const navItems = role === 'candidate' ? candidateLinks : evaluatorLinks
  const section = sectionForPath(role, pathname)
  const title = pageTitle(role, section)
  return <div className="dashboard-app">
    <aside className="dashboard-sidebar">
      <button className="dashboard-logo" type="button" onClick={() => props.navigate('/')}><span><Code2 size={17} /></span><b>Code<span>Proof</span></b></button>
      <div className="sidebar-role"><span>{role === 'candidate' ? <UserRound size={14} /> : <BriefcaseBusiness size={14} />}</span>{role === 'candidate' ? 'Candidate space' : 'Evaluator space'}</div>
      <nav className="dashboard-nav" aria-label={`${role} navigation`}>
        {navItems.map(item => {
          const Icon = item.icon
          const active = item.path === pathname || (role === 'candidate' && item.label === 'Tests' && pathname.startsWith('/candidate/tests')) || (item.label === 'Tests / Test Data' && pathname.startsWith('/evaluator/tests'))
          return <button key={item.path} type="button" className={`dashboard-nav-item${active ? ' active' : ''}`} aria-current={active ? 'page' : undefined} onClick={() => props.navigate(item.path)}><Icon size={16} /><span>{item.label}</span>{active && <ChevronRight size={14} className="nav-current" />}</button>
        })}
      </nav>
      <div className="sidebar-bottom"><div className="sidebar-user"><span className="sidebar-avatar"><UserRound size={15} /></span><div><b>{props.email || 'CodeProof account'}</b><small>{role === 'candidate' ? 'Candidate access' : 'Evaluator access'}</small></div></div><button type="button" className="dashboard-nav-item signout-item" onClick={props.onSignOut}><LogOut size={15} /><span>Sign out</span></button></div>
    </aside>
    <div className="dashboard-main-wrap">
      <header className="dashboard-topbar"><button type="button" className="mobile-logo" onClick={() => props.navigate('/')}><span className="dashboard-logo-icon"><Code2 size={16} /></span>Code<span>Proof</span></button><div className="dashboard-breadcrumb">{role === 'candidate' ? 'Candidate' : 'Evaluator'} <ChevronRight size={13} /> <b>{title}</b></div><div className="dashboard-top-actions"><button type="button" className={`backend-status ${props.backendStatus}`} onClick={props.checkBackend} disabled={props.backendStatus === 'checking'} title="Retry backend health check"><span className="backend-status-dot" />{props.backendStatus === 'checking' ? 'Checking' : props.backendStatus === 'connected' ? 'Connected' : 'Offline'}</button><span className="top-user-email">{props.email}</span><button type="button" className="mobile-signout" onClick={props.onSignOut}>Sign out</button></div></header>
      <main className="dashboard-content">
        {!props.authLoading && !props.hasSession ? <div className="dashboard-access-state"><div className="dashboard-empty-icon"><LockKeyhole size={20} /></div><h1>Sign in to continue</h1><p>This dashboard is available after you authenticate. Your selected experience does not grant a platform role.</p><button className="dash-primary" type="button" onClick={() => props.navigate(`/auth/${role}`)}>Sign in as {role === 'candidate' ? 'Candidate' : 'Evaluator'} <ArrowRight size={15} /></button></div> : props.authLoading ? <div className="dashboard-access-state"><span className="loader-dot" /> Restoring your session…</div> : <>
          {section === 'create' ? <CreateTestPage {...props} /> : <DashboardSection {...props} section={section} />}
        </>}
      </main>
    </div>
  </div>
}

function sectionForPath(role: Role, pathname: string) {
  if (pathname === `/${role}/dashboard` || pathname === `/${role}`) return 'dashboard'
  if (role === 'candidate') {
    if (pathname.startsWith('/candidate/tests/')) return pathname.endsWith('/instructions') ? 'instructions' : 'test-detail'
    if (pathname.startsWith('/candidate/tests')) return 'tests'
    if (pathname.startsWith('/candidate/history')) return 'history'
    if (pathname.startsWith('/candidate/progress')) return 'progress'
    if (pathname.startsWith('/candidate/profile')) return 'profile'
  } else {
    if (pathname.startsWith('/evaluator/create-test')) return 'create'
    if (pathname.startsWith('/evaluator/tests')) return 'tests'
    if (pathname.startsWith('/evaluator/history')) return 'history'
    if (pathname.startsWith('/evaluator/reports')) return 'reports'
    if (pathname.startsWith('/evaluator/profile')) return 'profile'
  }
  return 'dashboard'
}

function pageTitle(role: Role, section: string) {
  const titles: Record<string, string> = {
    dashboard: 'Dashboard', tests: role === 'candidate' ? 'Tests' : 'Tests / Test Data', history: 'History', progress: 'My Progress', profile: 'Profile',
    reports: 'Results & Reports', create: 'Create Test', 'test-detail': 'Test details', instructions: 'Before you begin',
  }
  return titles[section] ?? 'Dashboard'
}

function DashboardSection({ role, section, navigate, email, accessToken }: RouteProps & { section: string }) {
  if (role === 'candidate' && section === 'tests') return <CandidateTests accessToken={accessToken} navigate={navigate} />
  if (role === 'candidate' && section === 'test-detail') return <CandidateTestDetails accessToken={accessToken} pathname={window.location.pathname} navigate={navigate} />
  if (role === 'candidate' && section === 'instructions') return <CandidateInstructions accessToken={accessToken} pathname={window.location.pathname} navigate={navigate} />
  if (role === 'candidate' && section === 'history') return <CandidateHistory accessToken={accessToken} navigate={navigate} />
  if (role === 'candidate' && section === 'progress') return <EmptyState icon={<BookOpen size={18} />} eyebrow="MY PROGRESS" title="Progress data is not connected yet" detail="Your skill progress and assessment summaries will appear here when real candidate data is available." />
  if (section === 'profile') return <ProfilePage email={email} role={role} />
  if (role === 'evaluator' && section === 'tests') return <EvaluatorAssessmentList accessToken={accessToken} navigate={navigate} />
  if (role === 'evaluator' && section === 'history') return <EmptyState icon={<History size={18} />} eyebrow="EVALUATOR HISTORY" title="No history is available" detail="Assessment changes and activity history are not connected to this frontend yet." />
  if (role === 'evaluator' && section === 'reports') return <EvaluatorResultsPage accessToken={accessToken} />
  if (role === 'candidate') return <CandidateDashboard navigate={navigate} />
  return <EvaluatorDashboard navigate={navigate} />
}

function EvaluatorResultsPage({ accessToken }: { accessToken?: string }) {
  const [assessments, setAssessments] = useState<AssessmentSummaryRecord[]>([])
  const [assessmentId, setAssessmentId] = useState('')
  const [results, setResults] = useState<AssessmentResultsRecord | null>(null)
  const [selectedAttemptId, setSelectedAttemptId] = useState('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [loadingAssessments, setLoadingAssessments] = useState(true)
  const [loadingResults, setLoadingResults] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [followUp, setFollowUp] = useState<FollowUpInterviewRecord | null>(null)
  const [followUpPrompt, setFollowUpPrompt] = useState('')
  const [followUpNotes, setFollowUpNotes] = useState('')
  const [followUpScore, setFollowUpScore] = useState('')

  useEffect(() => {
    if (!accessToken) { setLoadingAssessments(false); return }
    let active = true
    fetchOwnedAssessments(accessToken).then(({ assessments: owned }) => {
      if (!active) return
      setAssessments(owned)
      setAssessmentId(current => current || owned[0]?.id || '')
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Could not load your assessments.') })
      .finally(() => { if (active) setLoadingAssessments(false) })
    return () => { active = false }
  }, [accessToken])

  useEffect(() => {
    if (!accessToken || !assessmentId) { setResults(null); return }
    let active = true
    setLoadingResults(true); setError(''); setNotice(''); setSelectedAttemptId('')
    fetchAssessmentResults(accessToken, assessmentId, offset).then(value => {
      if (active) { setResults(value); setSelectedAttemptId(value.attempts[0]?.attempt_id ?? '') }
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Could not load assessment results.') })
      .finally(() => { if (active) setLoadingResults(false) })
    return () => { active = false }
  }, [accessToken, assessmentId, offset])

  const filteredAttempts = (results?.attempts ?? []).filter(attempt => {
    const term = search.trim().toLowerCase()
    return !term || (attempt.candidate_display_name ?? '').toLowerCase().includes(term)
      || attempt.candidate_id.toLowerCase().includes(term)
      || attempt.status.includes(term)
  })
  const selectedAttempt = results?.attempts.find(item => item.attempt_id === selectedAttemptId) ?? null
  useEffect(() => {
    if (!accessToken || !assessmentId || !selectedAttemptId) return
    let active = true
    fetchEvaluatorFollowUpInterview(accessToken, assessmentId, selectedAttemptId).then(value => { if (active) { setFollowUp(value); setFollowUpNotes(value.review_notes ?? ''); setFollowUpScore(value.review_score === null ? '' : String(value.review_score)) } }).catch(() => { if (active) setFollowUp(null) })
    return () => { active = false }
  }, [accessToken, assessmentId, selectedAttemptId])
  const saveReview = async (question: EvaluationQuestionResultRecord, score: number, feedback: string) => {
    if (!accessToken || !assessmentId || !selectedAttempt) return
    setNotice(''); setError('')
    try {
      const updated = await saveManualQuestionReview(accessToken, assessmentId, selectedAttempt.attempt_id, question.question_id, { score, feedback })
      setResults(current => current ? { ...current, attempts: current.attempts.map(item => item.attempt_id === updated.attempt_id ? updated : item) } : current)
      setNotice('Review saved. The backend recalculated the score and review status.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save this review.') }
  }

  return <section className="dashboard-page evaluator-results-page">
    <DashboardPageHeading eyebrow="EVALUATOR WORKSPACE" title="Results & Reports" detail="Review candidate attempts for assessments you own. Grades and final scores are verified and calculated by the backend." />
    {error && <div className="results-alert error" role="alert">{error}</div>}
    {notice && <div className="results-alert success" role="status">{notice}</div>}
    {loadingAssessments ? <div className="dash-panel results-empty"><span className="loader-dot" /> Loading your assessments…</div>
      : assessments.length === 0 ? <div className="large-empty"><span className="large-empty-icon"><FileText size={20} /></span><b>No owned assessments yet</b><p>Create or publish an assessment to review candidate attempts here.</p></div>
      : <>
        <div className="dash-panel results-toolbar"><label htmlFor="results-assessment">Assessment</label><select id="results-assessment" value={assessmentId} onChange={event => { setOffset(0); setAssessmentId(event.target.value) }}>{assessments.map(item => <option key={item.id} value={item.id}>{item.title} · {item.status}</option>)}</select><label htmlFor="results-search">Search this page</label><input id="results-search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Candidate name, ID, or status" /></div>
        {loadingResults ? <div className="dash-panel results-empty"><span className="loader-dot" /> Loading submissions…</div> : results && <>
          <div className="results-layout">
            <section className="dash-panel results-attempts"><div className="results-panel-heading"><div><h2>Candidate attempts</h2><p>{results.total} total · showing {results.attempts.length} on this page</p></div></div>
              {filteredAttempts.length ? filteredAttempts.map(attempt => <button type="button" key={attempt.attempt_id} onClick={() => setSelectedAttemptId(attempt.attempt_id)} className={`results-attempt-item${attempt.attempt_id === selectedAttemptId ? ' selected' : ''}`}>
                <span className="attempt-avatar">{(attempt.candidate_display_name || attempt.candidate_id).slice(0, 1).toUpperCase()}</span><span className="attempt-main"><b>{attempt.candidate_display_name || `Candidate ${attempt.candidate_id.slice(0, 8)}`}</b><small>Attempt {attempt.attempt_number} · {attempt.status.replace('_', ' ')}</small><small>{new Date(attempt.submitted_at || attempt.started_at).toLocaleString()}</small></span><span className={`review-badge ${attempt.review_status}`}>{attempt.review_status.replace('_', ' ')}</span>
                <span className="attempt-score">{attempt.final_score !== null ? `${attempt.final_score}/${attempt.max_score ?? '—'}` : attempt.score !== null ? `${attempt.score}/${attempt.max_score ?? '—'} auto` : '—'}</span>
              </button>) : <div className="results-inline-empty">No attempts match this search.</div>}
              <div className="results-pagination"><button type="button" className="dash-secondary" disabled={offset <= 0 || loadingResults} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button><button type="button" className="dash-secondary" disabled={!results || offset + results.attempts.length >= results.total || loadingResults} onClick={() => setOffset(offset + 50)}>Next</button></div>
            </section>
            <section className="dash-panel results-detail"><div className="results-panel-heading"><div><h2>Submission review</h2><p>{selectedAttempt ? `Attempt ${selectedAttempt.attempt_number} · started ${new Date(selectedAttempt.started_at).toLocaleString()}` : 'Select a candidate attempt to inspect answers.'}</p></div>{selectedAttempt && <ReportDownloadButton accessToken={accessToken} kind="evaluator" attemptId={selectedAttempt.attempt_id} assessmentId={assessmentId} />}</div>
              {!selectedAttempt ? <div className="results-inline-empty">No submission selected.</div> : <>
                <div className="score-summary"><span><small>Automatic</small><b>{selectedAttempt.score ?? '—'} / {selectedAttempt.max_score ?? '—'}</b></span><span><small>Manual</small><b>{selectedAttempt.manual_score ?? 'Pending'}</b></span><span><small>Final</small><b>{selectedAttempt.final_score ?? 'Pending'}</b></span><span><small>Review</small><b className={`review-badge ${selectedAttempt.review_status}`}>{selectedAttempt.review_status.replace('_', ' ')}</b></span></div>
                <div className="results-question-list">{selectedAttempt.responses.map((question, index) => <ManualGradeCard key={question.question_id} index={index + 1} question={question} onSave={(score, feedback) => saveReview(question, score, feedback)} />)}</div>
                <section className="follow-up-panel evaluator-follow-up"><h3>Technical follow-up interview</h3>{followUp ? <><p>Status: <b>{followUp.status.replace('_', ' ')}</b>{followUp.submitted_at && ` · submitted ${new Date(followUp.submitted_at).toLocaleString()}`}</p>{followUp.questions.map((item, index) => <div className="follow-up-question" key={item.id}><p><b>{index + 1}. {item.prompt}</b> <small>{item.origin === 'ai' ? 'AI generated' : `Evaluator authored${item.created_at ? ` · ${new Date(item.created_at).toLocaleString()}` : ''}`}</small></p><pre>{item.answer.trim() || 'Unanswered'}</pre></div>)}<form className="manual-grade-form" onSubmit={async event => { event.preventDefault(); if (!accessToken) return; try { setFollowUp(await reviewFollowUpInterview(accessToken, assessmentId, selectedAttempt.attempt_id, followUpNotes, followUpScore === '' ? null : Number(followUpScore))); setNotice('Interview review saved.') } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save interview review.') } }}><label>Private evaluator notes<textarea maxLength={10000} rows={3} value={followUpNotes} onChange={event => setFollowUpNotes(event.target.value)} /></label><label>Separate interview score (optional, 0–100)<input type="number" min="0" max="100" value={followUpScore} onChange={event => setFollowUpScore(event.target.value)} /></label><button className="dash-primary" type="submit" disabled={followUp.status !== 'submitted'}><Save size={14} /> Save interview review</button></form><form className="manual-grade-form" onSubmit={async event => { event.preventDefault(); if (!accessToken || !followUpPrompt.trim()) return; try { setFollowUp(await addEvaluatorFollowUpQuestion(accessToken, assessmentId, selectedAttempt.attempt_id, followUpPrompt)); setFollowUpPrompt(''); setNotice('Additional question sent to the candidate.') } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not add question.') } }}><label>Add a candidate question<textarea maxLength={4000} rows={2} value={followUpPrompt} onChange={event => setFollowUpPrompt(event.target.value)} /></label><button className="dash-secondary" type="submit" disabled={!followUpPrompt.trim()}>Add question</button></form></> : <p>Interview questions have not been generated for this submission yet.</p>}</section>
              </>}
            </section>
          </div>
        </>}
      </>}
  </section>
}

function ManualGradeCard({ index, question, onSave }: { index: number; question: EvaluationQuestionResultRecord; onSave: (score: number, feedback: string) => Promise<void> }) {
  const [score, setScore] = useState(question.manual_score === null ? '' : String(question.manual_score))
  const [feedback, setFeedback] = useState(question.manual_feedback ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { setScore(question.manual_score === null ? '' : String(question.manual_score)); setFeedback(question.manual_feedback ?? '') }, [question.manual_score, question.manual_feedback])
  const save = async (event: FormEvent) => {
    event.preventDefault()
    const value = Number(score)
    if (!Number.isInteger(value) || value < 0 || value > question.max_points) { setError(`Enter a whole number from 0 to ${question.max_points}.`); return }
    setSaving(true); setError('')
    try { await onSave(value, feedback) } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save review.') }
    finally { setSaving(false) }
  }
  return <article className="results-question-card"><header><span className="question-index">{String(index).padStart(2, '0')}</span><div><h3>{question.question_title}</h3><small>{question.question_type.replace('-', ' ')} · {question.max_points} points</small></div><span className={`question-status ${question.review_eligible ? (question.manual_score === null ? 'pending' : 'graded') : 'automatic'}`}>{question.review_eligible ? (question.manual_score === null ? 'Needs review' : 'Reviewed') : question.execution_status.replace('_', ' ')}</span></header>
    <div className="review-prompt"><b>Question prompt</b><p>{question.question_prompt}</p><small className="rubric-empty-note">No separate rubric is configured for this question; use its prompt and your assessment criteria.</small></div>
    <div className="candidate-answer"><b>Candidate answer{question.programming_language ? ` · ${question.programming_language}` : ''}</b><pre>{question.response_text?.trim() || 'No answer was submitted.'}</pre></div>
    {question.execution_details && question.execution_details.length > 0 && <details className="execution-summary"><summary>Automatic execution details ({question.passed_test_cases ?? 0}/{question.total_test_cases ?? 0} cases passed)</summary><pre>{question.execution_details.map((item, itemIndex) => `Case ${itemIndex + 1}: ${String(item.status ?? 'unknown')}`).join('\n')}</pre></details>}
    {question.review_eligible && <form className="manual-grade-form" onSubmit={save}><label>Score <span>out of {question.max_points}</span><input type="number" min="0" max={question.max_points} step="1" value={score} onChange={event => setScore(event.target.value)} required /></label><label>Candidate feedback <span>optional</span><textarea value={feedback} onChange={event => setFeedback(event.target.value)} maxLength={10000} rows={3} placeholder="Share actionable feedback with the candidate when results are enabled." /></label>{error && <p className="manual-grade-error" role="alert">{error}</p>}<button className="dash-primary" type="submit" disabled={saving}><Save size={14} />{saving ? 'Saving review…' : question.manual_score === null ? 'Save grade' : 'Update grade'}</button></form>}
  </article>
}

function ReportDownloadButton({ accessToken, kind, attemptId, assessmentId }: { accessToken?: string; kind: 'candidate' | 'evaluator'; attemptId: string; assessmentId?: string }) {
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState('')
  const download = async () => {
    if (!accessToken || downloading) return
    setDownloading(true); setError('')
    try {
      const report = kind === 'candidate'
        ? await fetchCandidateAttemptReport(accessToken, attemptId)
        : await fetchEvaluatorAttemptReport(accessToken, assessmentId ?? '', attemptId)
      const url = URL.createObjectURL(report.blob)
      const link = document.createElement('a')
      link.href = url; link.download = report.filename; link.style.display = 'none'
      document.body.appendChild(link); link.click(); link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Report could not be downloaded.')
    } finally { setDownloading(false) }
  }
  return <span className="report-download-control"><button type="button" className="dash-secondary report-download-button" onClick={() => void download()} disabled={!accessToken || downloading} aria-label="Download PDF report">
    <FileDown size={14} />{downloading ? 'Preparing PDF…' : 'Download PDF'}
  </button>{error && <small className="report-download-error" role="alert">{error}</small>}</span>
}

function DashboardPageHeading({ eyebrow, title, detail, action }: { eyebrow: string; title: string; detail: string; action?: React.ReactNode }) {
  return <div className="dash-page-heading"><div><div className="dash-eyebrow">{eyebrow}</div><h1>{title}</h1><p>{detail}</p></div>{action}</div>
}

function DetailFact({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><b>{value}</b></div>
}

function CandidateDashboard({ navigate }: { navigate: (path: string) => void }) {
  return <><DashboardPageHeading eyebrow="CANDIDATE SPACE" title="Your coding journey" detail="Find an assessment or review your recent activity." /><div className="dash-card-grid"><button className="dash-feature-card" onClick={() => navigate('/candidate/tests')}><span className="dash-feature-icon"><Search size={18} /></span><b>Explore tests</b><p>Browse open assessments or enter a restricted test code.</p><span className="dash-card-link">View tests <ArrowRight size={13} /></span></button><button className="dash-feature-card" onClick={() => navigate('/candidate/history')}><span className="dash-feature-icon"><History size={18} /></span><b>Assessment history</b><p>Review your previous attempts and available results.</p><span className="dash-card-link">View history <ArrowRight size={13} /></span></button><button className="dash-feature-card" onClick={() => navigate('/candidate/progress')}><span className="dash-feature-icon"><BookOpen size={18} /></span><b>My progress</b><p>See your skills and progress summaries as they become available.</p><span className="dash-card-link">View progress <ArrowRight size={13} /></span></button></div><div className="dash-callout"><div><div className="dash-eyebrow">PUBLIC PRACTICE</div><h2>Looking for a place to start?</h2><p>Published open assessments are available in Tests; restricted assessments require a code from their evaluator.</p></div><button className="dash-secondary" onClick={() => navigate('/candidate/tests')}>Explore tests <ArrowRight size={14} /></button></div></>
}

function CandidateTests({ accessToken, navigate }: { accessToken?: string; navigate: (path: string) => void }) {
  const [accessCode, setAccessCode] = useState('')
  const [message, setMessage] = useState('')
  const [checkingCode, setCheckingCode] = useState(false)
  const [assessments, setAssessments] = useState<CandidateAssessmentRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const load = async () => {
    if (!accessToken) { setError('A verified candidate session is required to load tests.'); setLoading(false); return }
    setLoading(true); setError('')
    try { setAssessments((await fetchCandidateAssessments(accessToken)).assessments) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Tests could not be loaded.') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [accessToken])
  const onSubmitCode = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!accessToken || !accessCode.trim()) { setMessage('Enter the code shared by your evaluator.'); return }
    setCheckingCode(true); setMessage('')
    try {
      const result = await verifyCandidateAccessCode(accessToken, accessCode.trim())
      navigate(`/candidate/tests/${result.assessment.id}`)
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : 'Access code invalid or assessment unavailable.') }
    finally { setCheckingCode(false) }
  }
  return <><DashboardPageHeading eyebrow="ASSESSMENT LIBRARY" title="Tests" detail="Discover published open assessments or use a code for a restricted assessment." /><div className="dash-card-grid tests-top-grid"><section className="dash-panel access-code-panel"><span className="dash-feature-icon"><LockKeyhole size={18} /></span><div><h2>Have an access code?</h2><p>Enter the unique code shared by your evaluator to receive time-limited access.</p></div><form className="access-code-form dash-access-form" onSubmit={onSubmitCode}><label htmlFor="candidate-access-code">Assessment access code</label><div><input id="candidate-access-code" value={accessCode} onChange={event => setAccessCode(event.target.value)} placeholder="Enter code" autoComplete="off" disabled={checkingCode} /><button className="dash-primary" type="submit" disabled={checkingCode || !accessToken}>{checkingCode ? 'Checking?' : 'Check code'} <ArrowRight size={14} /></button></div>{message && <p className="form-feedback" role="alert">{message}</p>}<small>Code checks are rate limited. Invalid codes and unavailable assessments receive the same response.</small></form></section><section className="dash-panel open-test-panel"><span className="dash-feature-icon"><Search size={18} /></span><div><div className="dash-eyebrow">OPEN TESTS</div><h2>Published assessments</h2><p>Available open assessments from CodeProof.</p></div><div className="dashboard-empty">{loading ? <span>Loading available tests?</span> : error ? <span>{error}</span> : <span>{assessments.length ? `${assessments.length} available` : 'No open assessments are available yet.'}</span>}</div></section></div><section className="dash-panel list-empty-panel"><div className="dash-list-head"><div><h2>Available tests</h2><p>Only published open assessments within their availability window are listed.</p></div><button className="dash-text-button" onClick={() => void load()} disabled={loading}>Refresh</button></div>{error && <p className="auth-error" role="alert">{error}</p>}{loading ? <div className="large-empty" role="status"><span className="loader-dot" /> Loading assessments?</div> : assessments.length ? <div className="candidate-assessment-list">{assessments.map(item => <article className="dash-panel candidate-assessment-card" key={item.id}><div><div className="dash-eyebrow">{item.difficulty.toUpperCase()} ? OPEN</div><h3>{item.title}</h3><p>{item.description || 'No description provided.'}</p><small>{item.question_count} questions ? {Math.ceil(item.duration_seconds / 60)} minutes ? {item.allowed_languages.join(', ')}</small></div><button className="dash-primary" onClick={() => navigate(`/candidate/tests/${item.id}`)}>View details <ArrowRight size={14} /></button></article>)}</div> : <div className="large-empty"><span className="large-empty-icon"><Code2 size={20} /></span><b>No open tests available</b><p>Published open assessments will appear here when they are available to your account.</p></div>}<button className="dash-text-button" onClick={() => navigate('/candidate/dashboard')}><ArrowLeft size={13} /> Back to dashboard</button><div className="workspace-preview-callout"><div><b>Workspace preview</b><p>The Two Sum editor preview is separate from real assessments. It does not run or submit code.</p></div><button type="button" className="dash-secondary" onClick={() => navigate('/candidate/tests/demo')}>View preview details <ArrowRight size={13} /></button></div></section></>
}

function CandidateTestDetails({ accessToken, pathname, navigate }: { accessToken?: string; pathname: string; navigate: (path: string) => void }) {
  const testId = pathname.split('/')[3] ?? ''
  const workspacePreview = decodeURIComponent(testId) === 'demo'
  const [assessment, setAssessment] = useState<CandidateAssessmentRecord | null>(null)
  const [loading, setLoading] = useState(!workspacePreview)
  const [error, setError] = useState('')
  useEffect(() => {
    if (workspacePreview) return
    if (!accessToken) { setLoading(false); setError('A verified candidate session is required.'); return }
    let active = true; setLoading(true); setError('')
    fetchCandidateAssessment(accessToken, decodeURIComponent(testId)).then(value => { if (active) setAssessment(value) })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Assessment details are unavailable.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [accessToken, testId, workspacePreview])
  if (loading) return <section className="dash-panel large-empty-page" role="status"><span className="loader-dot" /> Loading assessment details?</section>
  if (!workspacePreview && (error || !assessment)) return <><button className="dash-back-button" onClick={() => navigate('/candidate/tests')}><ArrowLeft size={14} /> Back to tests</button><section className="dash-panel large-empty-page"><b>Assessment unavailable</b><p role="alert">{error || 'This assessment could not be loaded.'}</p><p>Restricted assessments require a valid access-code grant. The assessment may also be outside its availability window.</p></section></>
  const value = assessment
  return <><button className="dash-back-button" onClick={() => navigate('/candidate/tests')}><ArrowLeft size={14} /> Back to tests</button><DashboardPageHeading eyebrow={workspacePreview ? 'LOCAL WORKSPACE PREVIEW' : 'PUBLISHED ASSESSMENT'} title={workspacePreview ? 'Two Sum editor preview' : value!.title} detail={workspacePreview ? 'This opens the existing local Monaco workspace for interface preview only.' : value!.description || 'Assessment description not provided.'} /><div className="detail-grid"><section className="dash-panel"><div className="dash-eyebrow">{workspacePreview ? 'DEMO ONLY ? NOT PUBLISHED' : 'CANDIDATE DETAILS'}</div><h2>{workspacePreview ? 'Sample editor experience' : 'Assessment information'}</h2><p className="detail-description">{workspacePreview ? 'The workspace contains a bundled Two Sum example. It is not an available test.' : value!.instructions || 'No additional instructions were provided.'}</p><div className="detail-facts"><DetailFact label="Difficulty" value={workspacePreview ? 'Easy (preview)' : value!.difficulty} /><DetailFact label="Duration" value={workspacePreview ? 'Unavailable' : `${Math.ceil(value!.duration_seconds / 60)} minutes`} /><DetailFact label="Allowed languages" value={workspacePreview ? 'Python and C editor preview' : value!.allowed_languages.join(', ')} /><DetailFact label="Questions" value={workspacePreview ? 'Sample content only' : String(value!.question_count)} /><DetailFact label="Access" value={workspacePreview ? 'Not a published assessment' : 'Published and available'} /></div>{!workspacePreview && value!.questions?.map((question, index) => <div className="candidate-question-summary" key={question.id}><b>{index + 1}. {question.title}</b><p>{question.prompt}</p><small>{question.points} points ? {question.question_type}</small></div>)}</section><section className="dash-panel detail-start-card"><span className="dash-feature-icon"><Code2 size={18} /></span><h2>{workspacePreview ? 'Open the workspace preview' : 'Start this test'}</h2><p>{workspacePreview ? 'Review the notice before opening the local sample editor. No real attempt will start.' : 'Review the instructions and confirm before starting or resuming your persisted attempt.'}</p><button className="dash-primary" onClick={() => navigate(`/candidate/tests/${encodeURIComponent(testId)}/instructions`)}>{workspacePreview ? 'View preview instructions' : 'Review instructions'} <ArrowRight size={14} /></button></section></div>{workspacePreview && <div className="not-connected-banner"><LockKeyhole size={15} /> Preview only. This is not a real published assessment.</div>}</>
}

function CandidateInstructions({ accessToken, pathname, navigate }: { accessToken?: string; pathname: string; navigate: (path: string) => void }) {
  const testId = pathname.split('/')[3] ?? ''
  const [confirmed, setConfirmed] = useState(false)
  const [assessment, setAssessment] = useState<CandidateAssessmentRecord | null>(null)
  const [loading, setLoading] = useState(decodeURIComponent(testId) !== 'demo')
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const workspacePreview = decodeURIComponent(testId) === 'demo'
  useEffect(() => {
    if (workspacePreview) return
    if (!accessToken) { setLoading(false); setError('A verified candidate session is required.'); return }
    let active = true; setLoading(true); setError('')
    fetchCandidateAssessment(accessToken, decodeURIComponent(testId)).then(value => { if (active) setAssessment(value) })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Assessment instructions are unavailable.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [accessToken, testId, workspacePreview])
  const begin = async () => {
    if (workspacePreview) { navigate('/candidate/assessment/demo'); return }
    if (!accessToken) return
    setStarting(true); setError('')
    try {
      const attempt = await startCandidateAttempt(accessToken, decodeURIComponent(testId))
      navigate(`/candidate/assessment/${encodeURIComponent(testId)}/${attempt.id}`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The attempt could not be started.') }
    finally { setStarting(false) }
  }
  if (loading) return <section className="dash-panel large-empty-page" role="status"><span className="loader-dot" /> Loading instructions?</section>
  if (!workspacePreview && (error && !assessment)) return <section className="dash-panel large-empty-page"><b>Assessment unavailable</b><p role="alert">{error}</p><button className="dash-secondary" onClick={() => navigate('/candidate/tests')}>Back to tests</button></section>
  return <><button className="dash-back-button" onClick={() => navigate(`/candidate/tests/${encodeURIComponent(testId)}`)}><ArrowLeft size={14} /> Back to details</button><DashboardPageHeading eyebrow="BEFORE YOU BEGIN" title={workspacePreview ? 'Workspace preview notice' : assessment!.title} detail="Review the candidate guidance and confirm before opening the workspace." /><section className="instruction-card dash-panel"><div className="dash-eyebrow">{workspacePreview ? 'LOCAL DEMO' : 'ASSESSMENT INSTRUCTIONS'}</div><h2>{workspacePreview ? 'This is not a real assessment' : 'Read before starting'}</h2><p>{workspacePreview ? 'The local Two Sum editor is a UI preview. Its Run Code and assistant are demos; submission sends nothing.' : assessment!.instructions || assessment!.description || 'No additional candidate instructions were provided.'}</p>{!workspacePreview && <div className="detail-facts"><DetailFact label="Duration" value={`${Math.ceil(assessment!.duration_seconds / 60)} minutes`} /><DetailFact label="Questions" value={String(assessment!.question_count)} /><DetailFact label="Languages" value={assessment!.allowed_languages.join(', ')} /></div>}<label className="instruction-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} /> {workspacePreview ? 'I understand this opens a local workspace preview.' : 'I have read the instructions and am ready to begin.'}</label>{error && <p className="auth-error" role="alert">{error}</p>}<button className="dash-primary" type="button" disabled={!confirmed || starting || (!workspacePreview && !accessToken)} onClick={() => void begin()}>{starting ? 'Starting?' : workspacePreview ? 'Open workspace preview' : 'Start or resume attempt'} <ArrowRight size={14} /></button>{workspacePreview && <p className="action-unavailable">This opens only the local Two Sum demo, not a published assessment.</p>}</section></>
}

function CandidateHistory({ accessToken, navigate }: { accessToken?: string; navigate: (path: string) => void }) {
  const [attempts, setAttempts] = useState<CandidateAttemptRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!accessToken) { setError('A verified candidate session is required.'); setLoading(false); return }
    let active = true
    fetchCandidateAttempts(accessToken).then(result => { if (active) setAttempts(result.attempts) })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Attempt history could not be loaded.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [accessToken])
  return <><DashboardPageHeading eyebrow="YOUR ACTIVITY" title="Assessment history" detail="Only your own persisted attempts and saved responses are shown here." />{error && <p className="auth-error" role="alert">{error}</p>}{loading ? <section className="dash-panel large-empty-page" role="status"><span className="loader-dot" /> Loading attempt history…</section> : attempts.length ? <div className="candidate-assessment-list">{attempts.map(attempt => <article className="dash-panel candidate-assessment-card" key={attempt.id}><div><div className="dash-eyebrow">{attempt.status.toUpperCase()} · ATTEMPT {attempt.attempt_number}</div><h3>{attempt.assessment_title}</h3><p>Started {new Date(attempt.started_at).toLocaleString()} · {attempt.responses.length} response(s) saved</p></div><div className="candidate-attempt-actions">{attempt.status === 'in_progress' ? <button className="dash-primary" onClick={() => navigate(`/candidate/assessment/${attempt.assessment_id}/${attempt.id}`)}>Resume attempt <ArrowRight size={14} /></button> : <ReportDownloadButton accessToken={accessToken} kind="candidate" attemptId={attempt.id} />}</div>{attempt.status === 'submitted' && <CandidateFollowUp accessToken={accessToken} attempt={attempt} />}</article>)}</div> : <section className="dash-panel large-empty-page"><span className="large-empty-icon"><History size={20} /></span><b>No attempts yet</b><p>Your started and submitted assessment attempts will appear here.</p></section>}</>
}

function CandidateFollowUp({ accessToken, attempt }: { accessToken?: string; attempt: CandidateAttemptRecord }) {
  const [interview, setInterview] = useState<FollowUpInterviewRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  useEffect(() => {
    if (!accessToken) return
    let active = true
    fetchFollowUpInterview(accessToken, attempt.id).then(value => { if (active) setInterview(value) }).catch(() => undefined).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [accessToken, attempt.id])
  const generate = async () => {
    if (!accessToken) return
    setPending(true); setError(''); setNotice('')
    try { setInterview(await generateFollowUpInterview(accessToken, attempt.id)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Questions could not be generated. Try again.') }
    finally { setPending(false) }
  }
  const save = async (id: string, answer: string) => {
    if (!accessToken) return
    await saveFollowUpAnswer(accessToken, attempt.id, id, answer)
    setNotice('Answer saved.')
  }
  const submit = async () => {
    if (!accessToken) return
    setPending(true); setError(''); setNotice('')
    try { setInterview(await submitFollowUpInterview(accessToken, attempt.id)); setNotice('Interview submitted. Your coding assessment result is unchanged.') }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Interview could not be submitted.') }
    finally { setPending(false) }
  }
  return <section className="follow-up-panel" aria-label="Technical follow-up interview">
    <h3>Technical follow-up interview</h3><p>Separate from your coding assessment score.</p>
    {loading ? <p role="status">Loading interview…</p> : !interview ? <><p>Answer a few questions about your submitted solution. You can return here later.</p><button className="dash-primary" disabled={pending || !accessToken} onClick={() => void generate()}>{pending ? 'Preparing questions…' : 'Start follow-up interview'}</button></> : <>
      <p>Interview status: <b>{interview.status.replace('_', ' ')}</b> · {interview.questions.filter(question => question.answer.trim()).length}/{interview.questions.length} answered</p>
      {interview.questions.map((question, index) => <FollowUpAnswer key={question.id} question={question} index={index + 1} onSave={save} disabled={pending || interview.status === 'submitted' || interview.status === 'reviewed'} />)}
      {interview.status !== 'submitted' && interview.status !== 'reviewed' && <button className="dash-primary" disabled={pending || interview.questions.some(question => !question.answer.trim())} onClick={() => void submit()}>{pending ? 'Submitting…' : 'Submit interview'}</button>}
    </>}
    {error && <p className="auth-error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
  </section>
}

function FollowUpAnswer({ question, index, onSave, disabled }: { question: FollowUpInterviewRecord['questions'][number]; index: number; onSave: (id: string, answer: string) => Promise<void>; disabled: boolean }) {
  const [answer, setAnswer] = useState(question.answer)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  return <div className="follow-up-question"><p><b>{index}. {question.prompt}</b> <small>{question.origin === 'ai' ? 'AI generated' : 'Evaluator question'}</small></p><label>Answer<textarea rows={3} maxLength={20000} value={answer} disabled={disabled || question.answer_locked} onChange={event => setAnswer(event.target.value)} /></label>{!disabled && !question.answer_locked && <button className="dash-secondary" disabled={saving} onClick={() => { setSaving(true); setError(''); void onSave(question.id, answer).catch(reason => setError(reason instanceof Error ? reason.message : 'Could not save answer.')).finally(() => setSaving(false)) }}>{saving ? 'Saving…' : 'Save answer'}</button>}{error && <p role="alert">{error}</p>}</div>
}

function EvaluatorDashboard({ navigate }: { navigate: (path: string) => void }) {
  return <><DashboardPageHeading eyebrow="EVALUATOR SPACE" title="Assessment overview" detail="Create, organize, and review coding assessments." action={<button className="dash-primary" onClick={() => navigate('/evaluator/create-test')}><Plus size={15} /> Create test</button>} /><div className="dash-card-grid"><button className="dash-feature-card" onClick={() => navigate('/evaluator/create-test')}><span className="dash-feature-icon"><FilePlus2 size={18} /></span><b>Create an assessment</b><p>Build a multi-question assessment manually or prepare an AI-assisted draft.</p><span className="dash-card-link">Start building <ArrowRight size={13} /></span></button><button className="dash-feature-card" onClick={() => navigate('/evaluator/tests')}><span className="dash-feature-icon"><ClipboardList size={18} /></span><b>Tests and test data</b><p>Manage question drafts and their public or hidden test cases.</p><span className="dash-card-link">Open tests <ArrowRight size={13} /></span></button><button className="dash-feature-card" onClick={() => navigate('/evaluator/reports')}><span className="dash-feature-icon"><FileText size={18} /></span><b>Results and reports</b><p>Review candidate outcomes when authorized result data is available.</p><span className="dash-card-link">Open reports <ArrowRight size={13} /></span></button></div><section className="dash-panel overview-empty-panel"><div className="dash-list-head"><div><h2>Your assessments</h2><p>Open Tests / Test Data to load your owner-scoped assessment records.</p></div><span className="not-connected-tag">NOT CONNECTED</span></div><div className="large-empty"><span className="large-empty-icon"><ClipboardList size={20} /></span><b>No assessment data</b><p>No assessments are stored for this evaluator yet, or the list is available from Tests / Test Data.</p></div></section></>
}

function EmptyState({ icon, eyebrow, title, detail }: { icon: React.ReactNode; eyebrow: string; title: string; detail: string }) {
  return <><DashboardPageHeading eyebrow={eyebrow} title={title} detail={detail} /><section className="dash-panel large-empty-page"><span className="large-empty-icon">{icon}</span><b>No connected data</b><p>This page will display real CodeProof data when its authorized backend endpoint is available.</p><span className="not-connected-tag">NOT CONNECTED</span></section></>
}

function ProfilePage({ email, role }: { email?: string; role: Role }) {
  return <><DashboardPageHeading eyebrow="ACCOUNT" title="Profile" detail="Basic account details from your current authenticated session." /><section className="dash-panel profile-panel"><span className="profile-avatar"><UserRound size={22} /></span><div><div className="dash-eyebrow">SUPABASE AUTH ACCOUNT</div><h2>{email || 'Email unavailable'}</h2><p>{role === 'candidate' ? 'Candidate access is verified by the CodeProof backend.' : 'Evaluator access is verified by the CodeProof backend.'}</p></div><span className="not-connected-tag">PROFILE API NOT CONNECTED</span></section></>
}

function recordToQuestion(record: AssessmentRecord['questions'][number]): QuestionDraft {
  return {
    id: record.id,
    serverId: record.id,
    title: record.title,
    prompt: record.prompt,
    kind: record.question_type,
    difficulty: record.difficulty,
    points: String(record.points),
    answerOptions: record.answer_options.join('\n'),
    correctAnswer: record.correct_answer ?? '',
    allowedLanguages: record.allowed_languages,
    timeLimitSeconds: String(record.time_limit_seconds),
    problem: record.problem_statement,
    examples: record.examples,
    testCases: record.test_cases.map(testCase => ({ input: testCase.input_data, expectedOutput: testCase.expected_output, visibility: testCase.visibility })),
  }
}

function recordToEditor(record: AssessmentRecord) {
  return {
    title: record.title,
    description: record.description,
    instructions: record.instructions,
    difficulty: record.difficulty,
    duration: String(Math.round(record.duration_seconds / 60)),
    languages: record.allowed_languages,
    accessMode: record.access_mode,
    questions: record.questions.map(recordToQuestion),
  }
}

function draftPayload(values: {
  title: string; description: string; instructions: string; difficulty: Difficulty; duration: string;
  languages: string[]; accessMode: AccessMode; questions: QuestionDraft[];
}): AssessmentDraftPayload {
  return {
    title: values.title.trim(),
    description: values.description,
    instructions: values.instructions,
    difficulty: values.difficulty,
    duration_seconds: Math.max(60, Number(values.duration || 60) * 60),
    allowed_languages: values.languages,
    access_mode: values.accessMode,
    purpose: 'hiring',
    max_attempts: null,
    starts_at: null,
    ends_at: null,
    show_results_after_submission: false,
    questions: values.questions.map((question, index) => ({
      ...(question.serverId ? { id: question.serverId } : {}),
      title: question.title.trim(),
      prompt: question.prompt.trim() || question.problem.trim() || question.title.trim(),
      question_type: question.kind,
      difficulty: question.difficulty,
      points: Math.max(0, Number(question.points || 0)),
      default_language: (question.allowedLanguages[0] || values.languages[0] || 'python') as 'python' | 'c',
      allowed_languages: question.allowedLanguages,
      time_limit_seconds: Math.max(60, Number(question.timeLimitSeconds || Number(values.duration || 60) * 60)),
      display_order: index,
      problem_statement: question.problem,
      examples: question.examples,
      answer_options: question.answerOptions.split('\n').map(item => item.trim()).filter(Boolean),
      correct_answer: question.correctAnswer || null,
      test_cases: question.testCases.map((testCase, caseIndex) => ({ input_data: testCase.input, expected_output: testCase.expectedOutput, visibility: testCase.visibility, display_order: caseIndex })),
    })),
  }
}

function toLocalDateTime(value: string) {
  const date = new Date(value)
  const offset = date.getTimezoneOffset() * 60000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function EvaluatorAssessmentList({ accessToken, navigate }: { accessToken?: string; navigate: (path: string) => void }) {
  const [assessments, setAssessments] = useState<AssessmentSummaryRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState('')
  const load = async () => {
    if (!accessToken) { setError('A verified sign-in session is required to load your assessments.'); setLoading(false); return }
    setLoading(true); setError('')
    try { setAssessments((await fetchOwnedAssessments(accessToken)).assessments) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load assessments.') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [accessToken])
  const perform = async (item: AssessmentSummaryRecord, action: 'delete' | 'archive' | 'publish') => {
    if (!accessToken) return
    setBusyId(item.id); setError('')
    try {
      if (action === 'delete') await deleteAssessmentDraft(accessToken, item.id)
      if (action === 'archive') await archiveAssessment(accessToken, item.id)
      if (action === 'publish') await publishAssessment(accessToken, item.id)
      await load()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The requested action failed.') }
    finally { setBusyId('') }
  }
  return <><DashboardPageHeading eyebrow="TESTS & TEST DATA" title="Your assessments" detail="Assessment records shown here are loaded from your owner-scoped backend account." action={<button className="dash-primary" onClick={() => navigate('/evaluator/create-test')}><Plus size={15} /> Create test</button>} />
    {error && <p className="auth-error" role="alert">{error} <button type="button" className="dash-text-button" onClick={() => void load()}>Retry</button></p>}
    {loading ? <section className="dash-panel large-empty-page" role="status"><span className="loader-dot" /> Loading your assessments…</section> : assessments.length === 0 ? <section className="dash-panel large-empty-page"><span className="large-empty-icon"><ClipboardList size={20} /></span><b>No assessments yet</b><p>Saved drafts and published assessments will appear here. No sample records are shown.</p><button className="dash-primary" onClick={() => navigate('/evaluator/create-test')}><Plus size={14} /> Create assessment</button></section> : <div className="assessment-list">{assessments.map(item => <article className="dash-panel assessment-list-card" key={item.id}><div><div className="dash-eyebrow">{item.status.toUpperCase()} · {item.access_mode.toUpperCase()}</div><h2>{item.title}</h2><p>{item.description || 'No description provided.'}</p><small>{item.question_count} question(s) · {Math.round(item.duration_seconds / 60)} minutes · {item.allowed_languages.join(', ')}</small></div><div className="assessment-list-actions"><button className="dash-secondary" onClick={() => navigate(`/evaluator/create-test/${item.id}`)}>{item.status === 'draft' ? 'Edit draft' : 'View details'}</button>{item.status === 'draft' ? <><button className="dash-secondary" disabled={busyId === item.id} onClick={() => void perform(item, 'publish')}>Publish</button><button className="dash-text-button" disabled={busyId === item.id} onClick={() => void perform(item, 'delete')}><Trash2 size={13} /> Delete draft</button></> : item.status !== 'archived' && <button className="dash-secondary" disabled={busyId === item.id} onClick={() => void perform(item, 'archive')}>Archive</button>}</div></article>)}</div>}
  </>
}

function makeQuestion(): QuestionDraft {
  return { id: crypto.randomUUID(), title: '', prompt: '', kind: 'programming', difficulty: 'medium', points: '10', answerOptions: '', correctAnswer: '', allowedLanguages: [], timeLimitSeconds: '', problem: '', examples: '', testCases: [{ input: '', expectedOutput: '', visibility: 'hidden' }] }
}

function CreateTestPage({ accessToken, pathname, navigate, backendStatus }: RouteProps) {
  const [mode, setMode] = useState<CreationMode | null>(null)
  const [reviewing, setReviewing] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [instructions, setInstructions] = useState('')
  const [difficulty, setDifficulty] = useState<Difficulty>('medium')
  const [duration, setDuration] = useState('60')
  const [languages, setLanguages] = useState<string[]>(['python'])
  const [accessMode, setAccessMode] = useState<AccessMode>('open')
  const [aiPrompt, setAiPrompt] = useState('')
  const [jobRole, setJobRole] = useState('')
  const [skills, setSkills] = useState('')
  const [questionCount, setQuestionCount] = useState('3')
  const [difficultyMix, setDifficultyMix] = useState('')
  const [experienceLevel, setExperienceLevel] = useState('mid-level')
  const [questionTypes, setQuestionTypes] = useState<QuestionKind[]>(['programming'])
  const [learningObjectives, setLearningObjectives] = useState('')
  const [generating, setGenerating] = useState(false)
  const [questions, setQuestions] = useState<QuestionDraft[]>([])
  const [purpose, setPurpose] = useState<'hiring' | 'practice'>('hiring')
  const [maxAttempts, setMaxAttempts] = useState('')
  const [startsAt, setStartsAt] = useState('')
  const [endsAt, setEndsAt] = useState('')
  const [showResults, setShowResults] = useState(false)
  const [assessmentId, setAssessmentId] = useState<string | null>(null)
  const [assessmentStatus, setAssessmentStatus] = useState('draft')
  const [loadingAssessment, setLoadingAssessment] = useState(false)
  const [saving, setSaving] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [apiError, setApiError] = useState('')
  const [apiNotice, setApiNotice] = useState('')
  const [oneTimeCode, setOneTimeCode] = useState('')
  const routeAssessmentId = pathname.match(/^\/evaluator\/create-test\/([^/]+)$/)?.[1]
  const backendReady = backendStatus === 'connected'

  useEffect(() => {
    if (!routeAssessmentId || !accessToken) return
    let active = true
    setLoadingAssessment(true); setApiError('')
    fetchAssessment(accessToken, decodeURIComponent(routeAssessmentId)).then(record => {
      if (!active) return
      const draft = recordToEditor(record)
      setAssessmentId(record.id); setAssessmentStatus(record.status); setTitle(draft.title); setDescription(draft.description)
      setInstructions(draft.instructions); setDifficulty(draft.difficulty); setDuration(draft.duration)
      setLanguages(draft.languages); setAccessMode(draft.accessMode); setQuestions(draft.questions)
      setPurpose(record.purpose === 'practice' ? 'practice' : 'hiring'); setMaxAttempts(record.max_attempts ? String(record.max_attempts) : '')
      setStartsAt(record.starts_at ? toLocalDateTime(record.starts_at) : ''); setEndsAt(record.ends_at ? toLocalDateTime(record.ends_at) : '')
      setShowResults(record.show_results_after_submission); setMode('manual'); setApiNotice('Assessment loaded from the backend.')
    }).catch(reason => { if (active) setApiError(reason instanceof Error ? reason.message : 'Could not load the assessment.') })
      .finally(() => { if (active) setLoadingAssessment(false) })
    return () => { active = false }
  }, [routeAssessmentId, accessToken])

  const addQuestion = () => setQuestions(current => [...current, makeQuestion()])
  const updateQuestion = (id: string, update: Partial<QuestionDraft>) => setQuestions(current => current.map(question => question.id === id ? { ...question, ...update } : question))
  const duplicateQuestion = (question: QuestionDraft) => setQuestions(current => {
    const index = current.findIndex(item => item.id === question.id)
    const { serverId: _serverId, ...source } = question
    const copy = { ...source, id: crypto.randomUUID(), testCases: question.testCases.map(testCase => ({ ...testCase })) }
    return [...current.slice(0, index + 1), copy, ...current.slice(index + 1)]
  })
  const moveQuestion = (index: number, offset: number) => setQuestions(current => {
    const target = index + offset
    if (target < 0 || target >= current.length) return current
    const next = [...current]
    ;[next[index], next[target]] = [next[target], next[index]]
    return next
  })
  const removeQuestion = (id: string) => setQuestions(current => current.filter(question => question.id !== id))
  const updateTestCase = (questionId: string, index: number, update: Partial<TestCaseDraft>) => setQuestions(current => current.map(question => question.id !== questionId ? question : { ...question, testCases: question.testCases.map((testCase, caseIndex) => caseIndex === index ? { ...testCase, ...update } : testCase) }))
  const addTestCase = (questionId: string) => setQuestions(current => current.map(question => question.id === questionId ? { ...question, testCases: [...question.testCases, { input: '', expectedOutput: '', visibility: 'hidden' }] } : question))
  const removeTestCase = (questionId: string, index: number) => setQuestions(current => current.map(question => question.id === questionId ? { ...question, testCases: question.testCases.filter((_, caseIndex) => caseIndex !== index) } : question))
  const toggleLanguage = (language: string) => setLanguages(current => current.includes(language) ? current.filter(item => item !== language) : [...current, language])
  const toggleQuestionType = (kind: QuestionKind) => setQuestionTypes(current => current.includes(kind) ? current.filter(item => item !== kind) : [...current, kind])

  const generateDraft = async () => {
    if (!accessToken) { setApiError('Sign in with a verified evaluator session before generating a draft.'); return }
    if (!aiPrompt.trim()) { setApiError('Describe the assessment topic or request first.'); return }
    if (!Number.isInteger(Number(questionCount)) || Number(questionCount) < 1 || Number(questionCount) > 8) { setApiError('Choose between 1 and 8 questions.'); return }
    if (!Number.isInteger(Number(duration)) || Number(duration) < 1 || Number(duration) > 1440) { setApiError('Choose an assessment duration between 1 and 1,440 minutes.'); return }
    if (!languages.length) { setApiError('Select at least one programming language.'); return }
    if (!questionTypes.length) { setApiError('Select at least one question type.'); return }
    if (questions.length && !window.confirm('Replace the current unsaved question draft with newly generated suggestions?')) return
    setGenerating(true); setApiError(''); setApiNotice('')
    try {
      const generated = await generateAssessmentQuestionDrafts(accessToken, {
        topic: aiPrompt.trim(), purpose, experience_level: experienceLevel,
        difficulty, programming_languages: languages as Array<'python' | 'c'>,
        question_count: Number(questionCount), question_types: questionTypes as AssessmentQuestionType[],
        duration_seconds: Number(duration) * 60,
        ...(jobRole.trim() ? { job_role: jobRole.trim() } : {}),
        ...(skills.trim() ? { skills: skills.trim() } : {}),
        ...(difficultyMix.trim() ? { difficulty_mix: difficultyMix.trim() } : {}),
        ...(learningObjectives.trim() ? { learning_objectives: learningObjectives.trim() } : {}),
      })
      setQuestions(generated.questions.map(question => ({
        id: crypto.randomUUID(), title: question.title, prompt: question.prompt,
        kind: question.question_type, difficulty: question.difficulty, points: String(question.points),
        answerOptions: question.answer_options.join('\n'), correctAnswer: question.correct_answer ?? '',
        allowedLanguages: question.allowed_languages, timeLimitSeconds: String(question.time_limit_seconds),
        problem: question.problem_statement, examples: question.examples,
        testCases: question.test_cases.map(testCase => ({ input: testCase.input_data, expectedOutput: testCase.expected_output, visibility: 'public' })),
      })))
      if (!title.trim()) setTitle(generated.title)
      if (!description.trim()) setDescription(generated.description)
      if (!instructions.trim()) setInstructions(generated.instructions)
      setApiNotice('AI suggestions loaded as an unsaved draft. Review correctness, ambiguity, difficulty, answer keys, and public test cases before saving or publishing.')
    } catch (reason) {
      setApiError(reason instanceof Error ? reason.message : 'AI draft generation failed. You can continue building manually.')
    } finally { setGenerating(false) }
  }

  const payload = () => {
    const base = draftPayload({ title, description, instructions, difficulty, duration, languages, accessMode, questions })
    base.purpose = purpose
    base.max_attempts = maxAttempts.trim() ? Number(maxAttempts) : null
    base.starts_at = startsAt ? new Date(startsAt).toISOString() : null
    base.ends_at = endsAt ? new Date(endsAt).toISOString() : null
    base.show_results_after_submission = showResults
    return base
  }
  const acceptRecord = (record: AssessmentRecord) => {
    const draft = recordToEditor(record)
    setAssessmentId(record.id); setAssessmentStatus(record.status); setQuestions(draft.questions)
    if (record.access_code) setOneTimeCode(record.access_code)
    setApiNotice(record.access_code ? 'Saved. Copy this restricted access code now; it is shown only once.' : 'Saved to your evaluator account.')
  }
  const saveDraft = async () => {
    if (!accessToken) { setApiError('Sign in with a verified evaluator account to save drafts.'); return null }
    if (!backendReady) { setApiError('The CodeProof backend is not connected. Retry the connection check before saving.'); return null }
    setSaving(true); setApiError(''); setApiNotice('')
    try {
      const record = assessmentId
        ? await updateAssessmentDraft(accessToken, assessmentId, payload())
        : await createAssessmentDraft(accessToken, payload())
      acceptRecord(record)
      if (!assessmentId) navigate(`/evaluator/create-test/${record.id}`)
      return record
    } catch (reason) {
      setApiError(reason instanceof Error ? reason.message : 'Draft could not be saved.')
      return null
    } finally { setSaving(false) }
  }
  const publishDraft = async () => {
    setPublishing(true); setApiError(''); setApiNotice('')
    try {
      const saved = await saveDraft()
      if (!saved) return
      const published = await publishAssessment(accessToken!, saved.id)
      setAssessmentStatus(published.status); setAssessmentId(published.id)
      if (published.access_code || saved.access_code) setOneTimeCode(published.access_code ?? saved.access_code ?? '')
      setApiNotice(published.access_code ? 'Published. Copy this restricted access code now; it is shown only once.' : 'Assessment published.')
    } catch (reason) { setApiError(reason instanceof Error ? reason.message : 'Assessment could not be published.') }
    finally { setPublishing(false) }
  }
  const rotateCode = async () => {
    if (!accessToken || !assessmentId) return
    setSaving(true); setApiError(''); setApiNotice('')
    try { const result = await rotateAssessmentAccessCode(accessToken, assessmentId); setOneTimeCode(result.access_code); setApiNotice('New access code generated. Copy it now; it will not be shown again.') }
    catch (reason) { setApiError(reason instanceof Error ? reason.message : 'Code could not be rotated.') }
    finally { setSaving(false) }
  }
  const publishReady = Boolean(title.trim() && description.trim() && instructions.trim() && languages.length && questions.length && questions.every(question => question.title.trim() && (question.prompt.trim() || question.problem.trim()) && (question.kind !== 'programming' || question.problem.trim())))

  if (loadingAssessment) return <section className="dash-panel large-empty-page" role="status"><span className="loader-dot" /> Loading assessment…</section>
  if (routeAssessmentId && apiError && !assessmentId) return <section className="dash-panel large-empty-page"><b>Assessment could not be loaded</b><p role="alert">{apiError}</p><button className="dash-secondary" onClick={() => navigate('/evaluator/tests')}>Back to tests</button></section>

  if (!mode) return <><DashboardPageHeading eyebrow="NEW ASSESSMENT" title="How would you like to create it?" detail="Choose a starting point. Both options use the same editable assessment builder and review flow." /><div className="creation-mode-grid"><button className="creation-mode-card" onClick={() => setMode('ai')}><span className="dash-feature-icon"><Bot size={19} /></span><h2>Create with AI</h2><p>Generate editable question suggestions from your assessment requirements, then review every detail.</p><span className="mode-status">Suggestions remain an unsaved draft</span><span className="dash-card-link">Open AI-assisted builder <ArrowRight size={13} /></span></button><button className="creation-mode-card" onClick={() => { setMode('manual'); setQuestions(current => current.length ? current : [makeQuestion()]) }}><span className="dash-feature-icon"><Settings2 size={19} /></span><h2>Build manually</h2><p>Set assessment details and compose questions, examples, and hidden test cases yourself.</p><span className="mode-status">Editable local draft</span><span className="dash-card-link">Open manual builder <ArrowRight size={13} /></span></button></div></>

  if (reviewing) return <><button type="button" className="dash-back-button" onClick={() => setReviewing(false)}><ArrowLeft size={14} /> Back to editor</button><DashboardPageHeading eyebrow="FINAL REVIEW" title={title.trim() || 'Untitled assessment'} detail={assessmentStatus === 'published' ? 'This assessment is published. Changes are locked until editing is supported for published assessments.' : assessmentId ? 'Review the saved draft before publishing.' : 'Review your unsaved draft before saving or publishing.'} /><div className="review-grid"><section className="dash-panel"><div className="dash-eyebrow">ASSESSMENT OVERVIEW</div><h2>{title.trim() || 'Untitled assessment'}</h2><p>{description || 'No description provided.'}</p><div className="detail-facts"><DetailFact label="Difficulty" value={difficulty} /><DetailFact label="Duration" value={`${duration || '—'} minutes`} /><DetailFact label="Languages" value={languages.length ? languages.join(', ') : 'None selected'} /><DetailFact label="Access" value={accessMode === 'open' ? 'Open · discoverable' : 'Restricted · code required'} /><DetailFact label="Questions" value={String(questions.length)} /><DetailFact label="Purpose" value={purpose} /></div><h3>Candidate instructions</h3><p>{instructions || 'No candidate instructions provided.'}</p></section><section className="dash-panel"><div className="dash-eyebrow">QUESTION REVIEW</div>{questions.length ? questions.map((question, index) => <article className="review-question" key={question.id}><b>{index + 1}. {question.title || 'Untitled question'}</b><span>{question.kind} · {question.difficulty} · {question.points || '0'} points</span><p>{question.prompt || question.problem || 'No prompt provided.'}</p><small>{question.testCases.length} configured test case(s), including hidden test data kept separate from candidate content.</small></article>) : <p>No questions have been added.</p>}</section></div><div className="draft-action-row"><span className="local-draft-pill">{assessmentId ? assessmentStatus.toUpperCase() : "UNSAVED DRAFT"}</span><button className="dash-secondary" onClick={() => setReviewing(false)}>Edit assessment</button><button className="dash-secondary" disabled={!accessToken || !backendReady || saving || publishing || assessmentStatus !== "draft"} onClick={() => void saveDraft()}>{saving ? "Saving..." : "Save Draft"}</button><button className="dash-primary" disabled={!accessToken || !backendReady || saving || publishing || !publishReady || assessmentStatus !== "draft"} onClick={() => void publishDraft()}>{publishing ? "Publishing..." : "Publish"}</button></div></>

  return <><div className="create-heading-row"><div><button type="button" className="dash-back-button" onClick={() => { setMode(null); setReviewing(false) }}><ArrowLeft size={14} /> Choose another mode</button><DashboardPageHeading eyebrow={mode === 'ai' ? 'AI-ASSISTED CREATION' : 'MANUAL QUESTION BUILDER'} title={assessmentId ? "Edit assessment" : "Create test"} detail={assessmentId ? 'Edit and save your owner-scoped assessment draft, then publish after review.' : 'Edit the assessment settings and questions, then save a backend draft or review it before publication.'} /></div><button className="dash-secondary review-button" onClick={() => setReviewing(true)}><Check size={14} /> Review assessment</button></div>{apiError && <p className="auth-error" role="alert">{apiError}</p>}{apiNotice && <p className="auth-notice" role="status">{apiNotice}</p>}{oneTimeCode && <section className="dash-panel access-code-result"><b>Restricted access code (copy it now)</b><code>{oneTimeCode}</code><p>The server stores only a hash and will not show this code again. You can rotate it later.</p>{assessmentId && <button className="dash-secondary" disabled={!accessToken || !backendReady || saving} onClick={() => void rotateCode()}>Rotate code</button>}</section>}{!accessToken ? <p className="not-connected-banner">Sign in with a verified evaluator session to save or publish this draft. Unsaved edits remain local to this page.</p> : !backendReady && <p className="not-connected-banner">The backend is {backendStatus}. Save and publish controls become available after the connection check succeeds.</p>}
    <div className={`create-test-layout${mode === 'ai' ? ' with-ai' : ''}`}>
      {mode === 'ai' && <aside className="ai-builder-panel dash-panel"><div className="ai-panel-heading"><span className="dash-feature-icon"><Bot size={17} /></span><div><b>AI draft assistant</b><small>Suggestions only · never saved automatically</small></div></div><div className="ai-chat-welcome">Describe what you need. The backend validates the returned content, but generated questions and public examples still need your review.</div><label>Assessment topic / request<textarea rows={4} maxLength={500} value={aiPrompt} onChange={event => setAiPrompt(event.target.value)} placeholder="e.g. Design a practical assessment about data structures and API fundamentals…" /></label><label>Job role<input maxLength={120} value={jobRole} onChange={event => setJobRole(event.target.value)} placeholder="e.g. Backend Engineer" /></label><label>Skills to assess<input maxLength={2000} value={skills} onChange={event => setSkills(event.target.value)} placeholder="e.g. data structures, API design" /></label><label>Target experience level<input maxLength={80} value={experienceLevel} onChange={event => setExperienceLevel(event.target.value)} placeholder="e.g. mid-level" /></label><label>Assessment purpose<select value={purpose} onChange={event => setPurpose(event.target.value as 'hiring' | 'practice')}><option value="hiring">Hiring</option><option value="practice">Practice</option></select></label><fieldset className="ai-language-list"><legend>Question types</legend>{(['programming', 'debugging', 'explanation', 'multiple-choice'] as QuestionKind[]).map(kind => <label key={kind}><input type="checkbox" checked={questionTypes.includes(kind)} onChange={() => toggleQuestionType(kind)} /> {kind === 'multiple-choice' ? 'Multiple choice' : kind === 'explanation' ? 'Code explanation' : kind[0].toUpperCase() + kind.slice(1)}</label>)}</fieldset><label>Question count<input type="number" min="1" max="8" value={questionCount} onChange={event => setQuestionCount(event.target.value)} /></label><label>Overall difficulty<select value={difficulty} onChange={event => setDifficulty(event.target.value as Difficulty)}><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option></select></label><label>Difficulty distribution<input maxLength={300} value={difficultyMix} onChange={event => setDifficultyMix(event.target.value)} placeholder="e.g. 1 easy, 2 medium" /></label><label>Duration (minutes)<input type="number" min="1" max="1440" value={duration} onChange={event => setDuration(event.target.value)} /></label><fieldset className="ai-language-list"><legend>Allowed languages</legend><label><input type="checkbox" checked={languages.includes('python')} onChange={() => toggleLanguage('python')} /> Python</label><label><input type="checkbox" checked={languages.includes('c')} onChange={() => toggleLanguage('c')} /> C</label></fieldset><label>Learning objectives (optional)<textarea rows={3} maxLength={2000} value={learningObjectives} onChange={event => setLearningObjectives(event.target.value)} placeholder="What should candidates demonstrate?" /></label><button type="button" className="dash-primary ai-generate" disabled={generating || !accessToken} onClick={() => void generateDraft()}>{generating ? 'Generating…' : 'Generate Draft'} <ArrowRight size={14} /></button>{!accessToken && <p className="ai-not-connected" role="status">Sign in with a verified evaluator session to generate.</p>}<div className="ai-output-expectations"><b>Review each suggestion before saving:</b><span>Title, description, candidate instructions</span><span>Questions, points, answer keys, public examples</span><span>Public test cases are unverified suggestions; no hidden cases are generated</span></div></aside>}
      <div className="create-test-editor">
        <section className="dash-panel assessment-settings"><div className="editor-section-heading"><div><div className="dash-eyebrow">ASSESSMENT SETTINGS</div><h2>Test overview</h2></div><span className="local-draft-pill">{assessmentId ? assessmentStatus.toUpperCase() : 'UNSAVED DRAFT'}</span></div><div className="form-grid"><label className="field-span-2">Test title<input value={title} onChange={event => setTitle(event.target.value)} placeholder="e.g. Backend Engineer Coding Assessment" /></label><label className="field-span-2">Description<textarea rows={3} value={description} onChange={event => setDescription(event.target.value)} placeholder="Describe the purpose and scope of this assessment" /></label><label className="field-span-2">Candidate instructions<textarea rows={3} value={instructions} onChange={event => setInstructions(event.target.value)} placeholder="Explain expectations, allowed resources, and submission guidance" /></label><label>Purpose<select value={purpose} onChange={event => setPurpose(event.target.value as 'hiring' | 'practice')}><option value="hiring">Hiring</option><option value="practice">Practice</option></select></label><label>Maximum attempts (optional)<input type="number" min="1" value={maxAttempts} onChange={event => setMaxAttempts(event.target.value)} placeholder="Unlimited" /></label><label>Available from (optional)<input type="datetime-local" value={startsAt} onChange={event => setStartsAt(event.target.value)} /></label><label>Available until (optional)<input type="datetime-local" value={endsAt} onChange={event => setEndsAt(event.target.value)} /></label><label>Difficulty<select value={difficulty} onChange={event => setDifficulty(event.target.value as Difficulty)}><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option></select></label><label>Duration (minutes)<input type="number" min="1" value={duration} onChange={event => setDuration(event.target.value)} /></label><label className="field-span-2"><span><input type="checkbox" checked={showResults} onChange={event => setShowResults(event.target.checked)} /> Allow candidates to see results after submission</span></label><fieldset className="language-fieldset"><legend>Allowed programming languages</legend><label><input type="checkbox" checked={languages.includes('python')} onChange={() => toggleLanguage('python')} /> Python</label><label><input type="checkbox" checked={languages.includes('c')} onChange={() => toggleLanguage('c')} /> C</label></fieldset><fieldset className="access-mode-fieldset"><legend>Candidate access</legend><label><input type="radio" name="access-mode" checked={accessMode === 'open'} onChange={() => setAccessMode('open')} /> <span><b>Open</b><small>Discoverable without an access code.</small></span></label><label><input type="radio" name="access-mode" checked={accessMode === 'restricted'} onChange={() => setAccessMode('restricted')} /> <span><b>Restricted</b><small>Requires a unique code shared by the evaluator.</small></span></label>{accessMode === 'restricted' && <p className="access-code-note"><LockKeyhole size={13} /> A unique code is generated when a restricted draft is saved. The raw code is shown once.</p>}</fieldset></div></section>
        <section className="question-builder-section"><div className="question-builder-heading"><div><div className="dash-eyebrow">QUESTION BUILDER</div><h2>Questions <span>{questions.length}</span></h2><p>Reorder, duplicate, and edit each question. Hidden test cases are evaluator-only and separate from examples.</p></div><button className="dash-primary" type="button" onClick={addQuestion}><Plus size={14} /> Add question</button></div>{questions.length === 0 ? <div className="question-empty dash-panel"><b>No questions added</b><p>Add your first question to this assessment.</p><button className="dash-secondary" onClick={addQuestion}><Plus size={14} /> Add question</button></div> : questions.map((question, index) => <QuestionCard key={question.id} question={question} index={index} total={questions.length} update={updateQuestion} duplicate={duplicateQuestion} move={moveQuestion} remove={removeQuestion} updateTestCase={updateTestCase} addTestCase={addTestCase} removeTestCase={removeTestCase} />)}</section>
        <div className="editor-bottom-actions"><span>{assessmentId ? `Backend draft: ${assessmentStatus}` : "Unsaved local draft"}</span><button className="dash-secondary" disabled={!accessToken || !backendReady || saving || publishing || assessmentStatus !== "draft"} onClick={() => void saveDraft()}>{saving ? "Saving..." : "Save Draft"}</button><button className="dash-primary" onClick={() => setReviewing(true)}><Check size={14} /> Review</button></div>
      </div>
    </div>
  </>
}

function QuestionCard({ question, index, total, update, duplicate, move, remove, updateTestCase, addTestCase, removeTestCase }: { question: QuestionDraft; index: number; total: number; update: (id: string, update: Partial<QuestionDraft>) => void; duplicate: (question: QuestionDraft) => void; move: (index: number, offset: number) => void; remove: (id: string) => void; updateTestCase: (questionId: string, index: number, update: Partial<TestCaseDraft>) => void; addTestCase: (questionId: string) => void; removeTestCase: (questionId: string, index: number) => void }) {
  return <article className="question-card dash-panel"><div className="question-card-head"><div className="question-number">{String(index + 1).padStart(2, '0')}</div><div className="question-head-title"><b>{question.title || `Question ${index + 1}`}</b><small>Editable question draft</small></div><div className="question-card-tools"><button type="button" aria-label={`Move question ${index + 1} up`} disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp size={14} /></button><button type="button" aria-label={`Move question ${index + 1} down`} disabled={index === total - 1} onClick={() => move(index, 1)}><ArrowDown size={14} /></button><button type="button" aria-label={`Duplicate question ${index + 1}`} onClick={() => duplicate(question)}><Copy size={14} /></button><button type="button" aria-label={`Delete question ${index + 1}`} onClick={() => remove(question.id)}><Trash2 size={14} /></button></div></div><div className="form-grid question-meta-grid"><label className="field-span-2">Question title<input value={question.title} onChange={event => update(question.id, { title: event.target.value })} placeholder="Give this question a title" /></label><label>Question type<select value={question.kind} onChange={event => update(question.id, { kind: event.target.value as QuestionKind })}><option value="programming">Programming</option><option value="debugging">Debugging</option><option value="explanation">Code explanation</option><option value="multiple-choice">Multiple choice</option></select></label><label>Difficulty<select value={question.difficulty} onChange={event => update(question.id, { difficulty: event.target.value as Difficulty })}><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option></select></label><label>Points<input type="number" min="0" value={question.points} onChange={event => update(question.id, { points: event.target.value })} /></label><label>Time limit (seconds)<input type="number" min="60" value={question.timeLimitSeconds} onChange={event => update(question.id, { timeLimitSeconds: event.target.value })} placeholder="Assessment duration" /></label><fieldset className="language-fieldset"><legend>Question languages</legend><label><input type="checkbox" checked={question.allowedLanguages.includes("python")} onChange={event => update(question.id, { allowedLanguages: event.target.checked ? [...question.allowedLanguages, "python"] : question.allowedLanguages.filter(item => item !== "python") })} /> Python</label><label><input type="checkbox" checked={question.allowedLanguages.includes("c")} onChange={event => update(question.id, { allowedLanguages: event.target.checked ? [...question.allowedLanguages, "c"] : question.allowedLanguages.filter(item => item !== "c") })} /> C</label><small>Leave empty to use all assessment languages.</small></fieldset><label className="field-span-2">Question prompt<textarea rows={2} value={question.prompt} onChange={event => update(question.id, { prompt: event.target.value })} placeholder="What should the candidate do or explain?" /></label></div>{question.kind === 'multiple-choice' && <div className="question-subsection"><div className="question-subsection-title"><Check size={14} /><b>Answer options</b><span>Evaluator-only answer key</span></div><label>Options, one per line<textarea rows={4} value={question.answerOptions} onChange={event => update(question.id, { answerOptions: event.target.value })} placeholder="Option A`nOption B`nOption C" /></label><label>Correct answer<input value={question.correctAnswer} onChange={event => update(question.id, { correctAnswer: event.target.value })} placeholder="Enter the correct option" /></label></div>}{(question.kind === 'programming' || question.kind === 'debugging') && <><div className="question-subsection"><div className="question-subsection-title"><Code2 size={14} /><b>Candidate-facing problem</b><span>Visible to candidates</span></div><label>Problem statement<textarea rows={4} value={question.problem} onChange={event => update(question.id, { problem: event.target.value })} placeholder="Write the problem statement candidates will see" /></label><label>Examples and candidate-visible content<textarea rows={3} value={question.examples} onChange={event => update(question.id, { examples: event.target.value })} placeholder={'Example 1\nInput: …\nOutput: …'} /></label></div><div className="question-subsection hidden-test-section"><div className="question-subsection-title"><LockKeyhole size={14} /><b>Test cases</b><span>Evaluator configuration · hidden cases are never shown to candidates</span></div>{question.testCases.map((testCase, caseIndex) => <div className="test-case-editor" key={`${question.id}-${caseIndex}`}><div className="test-case-editor-head"><b>Case {caseIndex + 1}</b><label>Visibility<select value={testCase.visibility} onChange={event => updateTestCase(question.id, caseIndex, { visibility: event.target.value as TestCaseDraft['visibility'] })}><option value="hidden">Hidden</option><option value="public">Public example</option></select></label><button type="button" aria-label={`Remove test case ${caseIndex + 1}`} onClick={() => removeTestCase(question.id, caseIndex)} disabled={question.testCases.length === 1}><Trash2 size={13} /></button></div><div className="form-grid"><label>Input data<textarea rows={2} value={testCase.input} onChange={event => updateTestCase(question.id, caseIndex, { input: event.target.value })} placeholder="Test input (text)" /></label><label>Expected output<textarea rows={2} value={testCase.expectedOutput} onChange={event => updateTestCase(question.id, caseIndex, { expectedOutput: event.target.value })} placeholder="Expected output (text)" /></label></div></div>)}<button type="button" className="dash-text-button add-test-case" onClick={() => addTestCase(question.id)}><Plus size={13} /> Add test case</button></div></>}</article>
}
