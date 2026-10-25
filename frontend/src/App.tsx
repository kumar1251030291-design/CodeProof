import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import Editor from '@monaco-editor/react'
import { Allotment } from 'allotment'
import 'allotment/dist/style.css'
import {
  Bot, ChevronDown, ChevronLeft, ChevronRight, CircleHelp, Clock3, Code2,
  PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Play,
  Send, Sparkles, Terminal, Check, X, FileCode2, Braces, Lightbulb, RefreshCw, LogIn, LogOut,
} from 'lucide-react'
import {
  ApiError, fetchCurrentUser, fetchHealth, fetchCandidateAssessment, fetchCandidateAttempt,
  withTimeout,
  requestCandidateAssistance, saveCandidateResponse, submitCandidateAttempt,
  type ApplicationRole, type CurrentUserResponse, type CandidateAssessmentRecord,
  type CandidateAssistantTurn, type CandidateAttemptRecord, type CandidateQuestionRecord,
} from './services/api'
import { accessVerificationFailure } from './services/request'
import { supabase, supabaseConfigError } from './services/supabase'
import type { Session } from '@supabase/supabase-js'
import { DashboardExperience } from './pages/DashboardExperience'
import './App.css'

type ResultTab = 'Test Cases' | 'Output' | 'Terminal'
type Language = 'python' | 'c'
type BackendStatus = 'checking' | 'connected' | 'offline'
type ChatMessage = { role: 'assistant' | 'user'; text: string }
type AuthMode = 'sign-in' | 'sign-up'
type IdentityStatus = 'idle' | 'loading' | 'authorized' | 'pending_access' | 'unavailable' | 'expired'

const starterCode: Record<Language, string> = {
  python: `class Solution:\n    def twoSum(self, nums: list[int], target: int) -> list[int]:\n        # Add your solution here\n        pass\n`,
  c: `#include <stdio.h>\n\nint main(void) {\n    // Read the input and implement your Two Sum solution here.\n    // Return or print the indices of the two numbers that add up to the target.\n\n    return 0;\n}\n`,
}
const prompts = ['Explain the problem', 'Give me a hint', 'Review my approach']

function authErrorMessage(error: unknown) {
  const message = error instanceof Error ? error.message : ''
  const normalized = message.toLowerCase()
  if (normalized.includes('invalid login credentials')) return 'That email and password combination was not recognized.'
  if (normalized.includes('already registered')) return 'An account with this email already exists. Try signing in.'
  if (normalized.includes('email not confirmed')) return 'Please confirm your email using the link we sent you.'
  if (normalized.includes('password') && normalized.includes('weak')) return 'Choose a stronger password and try again.'
  if (normalized.includes('fetch') || normalized.includes('network')) return 'Could not reach the authentication service. Check your connection and try again.'
  return message || 'Authentication failed. Please try again.'
}

function candidateAssistantErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 503) return 'Candidate AI assistance is not configured on this backend yet.'
    if (error.status === 429) return 'AI assistance is rate limited. Please wait a moment and try again.'
    if (error.status === 504) return 'The AI assistant took too long to respond. Please try again.'
    if (error.status === 502) return 'The AI provider could not return a usable answer. Please try again.'
    if (error.status === 413 || error.status === 422) return 'That message or shared code is too large. Shorten it and try again.'
    if (error.status === 409) return 'AI assistance is available only while this attempt is active.'
    if (error.status === 401) return 'Your sign-in session needs to be refreshed before using AI assistance.'
    return error.message
  }
  return 'Could not reach the AI assistant. Check your connection and try again.'
}

function App() {
  const [pathname, setPathname] = useState(() => window.location.pathname)
  const navigate = useCallback((path: string) => {
    window.history.pushState({}, '', path)
    setPathname(window.location.pathname)
    window.scrollTo(0, 0)
  }, [])
  useEffect(() => {
    const onPopState = () => setPathname(window.location.pathname)
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])
  const assessmentMatch = pathname.match(/^\/candidate\/assessment\/([^/]+)(?:\/([^/]+))?\/?$/)
  const [language, setLanguage] = useState<Language>('python')
  const [codeByLanguage, setCodeByLanguage] = useState<Record<Language, string>>(starterCode)
  const [seconds, setSeconds] = useState(34 * 60 + 18)
  const [activeTab, setActiveTab] = useState<ResultTab>('Test Cases')
  const [hasRun, setHasRun] = useState(false)
  const [chatInput, setChatInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'assistant', text: "Hi there! I'm your CodeProof assistant. I can help you think through the problem, explain a concept, or review your approach. What would you like to work on?" },
  ])
  const [showLeft, setShowLeft] = useState(true)
  const [showRight, setShowRight] = useState(true)
  const [submitOpen, setSubmitOpen] = useState(false)
  const [backendStatus, setBackendStatus] = useState<BackendStatus>('checking')
  const [session, setSession] = useState<Session | null>(null)
  const [authLoading, setAuthLoading] = useState(true)
  const [authSubmitting, setAuthSubmitting] = useState(false)
  const [authDialogOpen, setAuthDialogOpen] = useState(false)
  const [authMode, setAuthMode] = useState<AuthMode>('sign-in')
  const [authEmail, setAuthEmail] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [authError, setAuthError] = useState('')
  const [authNotice, setAuthNotice] = useState('')
  const [identity, setIdentity] = useState<CurrentUserResponse | null>(null)
  const [identityStatus, setIdentityStatus] = useState<IdentityStatus>('idle')
  const [identityError, setIdentityError] = useState('')
  const identityRequest = useRef<{ token: string; promise: Promise<void> } | null>(null)
  const identitySequence = useRef(0)
  const initialHealthCheckDone = useRef(false)

  const loadIdentity = useCallback((nextSession: Session | null, force = false): Promise<void> => {
    if (!nextSession) {
      identitySequence.current += 1
      identityRequest.current = null
      setIdentity(null)
      setIdentityStatus('idle')
      setIdentityError('')
      return Promise.resolve()
    }
    const token = nextSession.access_token
    if (!force && identityRequest.current?.token === token) return identityRequest.current.promise

    const sequence = ++identitySequence.current
    setIdentity(null)
    setIdentityError('')
    setIdentityStatus('loading')
    const request = (async () => {
      try {
        let result: CurrentUserResponse
        try {
          result = await fetchCurrentUser(token)
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 401 || !supabase) throw error
          const refreshed = await withTimeout(
            supabase.auth.refreshSession(),
            10_000,
            'Supabase session refresh timed out. Check your connection and retry verification.',
          )
          if (refreshed.error || !refreshed.data.session) {
            if (sequence === identitySequence.current) {
              setIdentityStatus('expired')
              setIdentityError('Your sign-in session expired. Sign out and sign in again to continue.')
            }
            return
          }
          setSession(refreshed.data.session)
          result = await fetchCurrentUser(refreshed.data.session.access_token)
        }
        if (sequence !== identitySequence.current) return
        setIdentity(result)
        setIdentityStatus(result.access_state)
      } catch (error) {
        if (sequence !== identitySequence.current) return
        setIdentity(null)
        const failure = accessVerificationFailure(error)
        setIdentityStatus(failure.status)
        setIdentityError(failure.message)
      }
    })()
    identityRequest.current = { token, promise: request }
    return request
  }, [])

  useEffect(() => {
    if (pathname.startsWith('/auth/')) {
      setAuthMode(new URLSearchParams(window.location.search).get('mode') === 'sign-up' ? 'sign-up' : 'sign-in')
      setAuthError('')
      setAuthNotice('')
    }
  }, [pathname])

  useEffect(() => {
    if (!assessmentMatch) return
    const timer = window.setInterval(() => setSeconds(value => Math.max(0, value - 1)), 1000)
    return () => window.clearInterval(timer)
  }, [pathname])

  const checkBackend = useCallback(async () => {
    setBackendStatus('checking')
    try {
      const health = await fetchHealth()
      setBackendStatus(health.status === 'healthy' ? 'connected' : 'offline')
    } catch {
      setBackendStatus('offline')
    }
  }, [])

  useEffect(() => {
    if (initialHealthCheckDone.current) return
    initialHealthCheckDone.current = true
    void checkBackend()
  }, [checkBackend])

  useEffect(() => {
    if (!supabase) {
      setAuthLoading(false)
      return
    }
    let active = true
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      if (!active) return
      setSession(nextSession)
      setAuthLoading(false)
      if (nextSession) setAuthDialogOpen(false)
      void loadIdentity(nextSession)
    })
    void supabase.auth.getSession().then(({ data, error }) => {
      if (!active) return
      setSession(data.session)
      setAuthLoading(false)
      void loadIdentity(data.session)
      if (error) setAuthError('Could not restore your session. Please try signing in again.')
    }).catch(() => {
      if (active) {
        setAuthLoading(false)
        setAuthError('Could not restore your session. Please try signing in again.')
      }
    })
    return () => {
      active = false
      subscription.unsubscribe()
    }
  }, [loadIdentity])

  const submitAuth = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setAuthError('')
    setAuthNotice('')
    if (!supabase) {
      setAuthError(supabaseConfigError ?? 'Supabase Auth is not configured.')
      return
    }
    setAuthSubmitting(true)
    try {
      const result = authMode === 'sign-in'
        ? await supabase.auth.signInWithPassword({ email: authEmail.trim(), password: authPassword })
        : await supabase.auth.signUp({ email: authEmail.trim(), password: authPassword })
      if (result.error) throw result.error
      if (authMode === 'sign-up' && !result.data.session) {
        setAuthNotice('Account created. Check your email for a confirmation link, then sign in.')
        setAuthPassword('')
      } else {
        setAuthDialogOpen(false)
        setAuthPassword('')
      }
    } catch (error) {
      setAuthError(authErrorMessage(error))
    } finally {
      setAuthSubmitting(false)
    }
  }

  const signOut = async () => {
    if (!supabase) return
    setAuthError('')
    try {
      const { error } = await supabase.auth.signOut()
      if (error) throw error
    } catch (error) {
      setAuthError(authErrorMessage(error))
      setAuthDialogOpen(true)
    }
  }

  const authMatch = pathname.match(/^\/auth\/(candidate|evaluator)\/?$/)
  const dashboardMatch = pathname.match(/^\/(candidate|evaluator)(?:\/.*)?\/?$/)

  useEffect(() => {
    if (!authMatch || !session || identityStatus !== 'authorized') return
    const requestedRole = authMatch[1] as ApplicationRole
    if (identity?.roles.includes(requestedRole)) navigate(`/${requestedRole}/dashboard`)
  }, [authMatch?.[1], identity, identityStatus, navigate, session])

  const retryIdentity = () => void loadIdentity(session, true)

  const time = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
  const code = codeByLanguage[language]
  const setCode = (value: string) => setCodeByLanguage(current => ({ ...current, [language]: value }))
  const sendMessage = (text = chatInput) => {
    const trimmed = text.trim()
    if (!trimmed) return
    setMessages(current => [...current, { role: 'user', text: trimmed }, {
      role: 'assistant',
      text: 'Demo response: Try keeping track of numbers you have already seen in a hash map. For each number, check whether its complement (target âˆ’ number) is already present. This keeps the approach linear while you reason through the edge cases.',
    }])
    setChatInput('')
  }

  const submitChat = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    sendMessage()
  }

  if (pathname === '/' || pathname === '') {
    return <LandingPage navigate={navigate} session={session} authLoading={authLoading} onSignOut={() => void signOut()} backendStatus={backendStatus} checkBackend={() => void checkBackend()} />
  }
  if (authMatch) {
    return <AuthPage role={authMatch[1] as 'candidate' | 'evaluator'} navigate={navigate} session={session} authLoading={authLoading} mode={authMode} setMode={setAuthMode} email={authEmail} setEmail={setAuthEmail} password={authPassword} setPassword={setAuthPassword} error={authError} notice={authNotice} submitting={authSubmitting} submit={submitAuth} onSignOut={() => void signOut()} backendStatus={backendStatus} checkBackend={() => void checkBackend()} identity={identity} identityStatus={identityStatus} identityError={identityError} onRetry={retryIdentity} />
  }
  if (dashboardMatch && !assessmentMatch) {
    const role = dashboardMatch[1] as ApplicationRole
    if (authLoading) return <AccessStatePage title="Restoring your session" message="Checking your sign-in sessionâ€¦" navigate={navigate} onSignOut={() => void signOut()} backendStatus={backendStatus} checkBackend={() => void checkBackend()} />
    if (!session) return <AuthPage role={role} navigate={navigate} session={session} authLoading={authLoading} mode={authMode} setMode={setAuthMode} email={authEmail} setEmail={setAuthEmail} password={authPassword} setPassword={setAuthPassword} error={authError} notice={authNotice} submitting={authSubmitting} submit={submitAuth} onSignOut={() => void signOut()} backendStatus={backendStatus} checkBackend={() => void checkBackend()} identity={identity} identityStatus={identityStatus} identityError={identityError} onRetry={retryIdentity} />
    if (identityStatus !== 'authorized' || !identity?.roles.includes(role)) return <IdentityAccessPage role={role} status={identityStatus} identity={identity} error={identityError} navigate={navigate} onRetry={retryIdentity} onSignOut={() => void signOut()} backendStatus={backendStatus} checkBackend={() => void checkBackend()} />
    return <DashboardExperience role={role} pathname={pathname} hasSession={true} authLoading={false} email={session.user.email} accessToken={session.access_token} navigate={navigate} onSignOut={() => void signOut()} backendStatus={backendStatus} checkBackend={() => void checkBackend()} />
  }
  if (assessmentMatch) {
    if (!session) return <AuthPage role="candidate" navigate={navigate} session={session} authLoading={authLoading} mode={authMode} setMode={setAuthMode} email={authEmail} setEmail={setAuthEmail} password={authPassword} setPassword={setAuthPassword} error={authError} notice={authNotice} submitting={authSubmitting} submit={submitAuth} onSignOut={() => void signOut()} backendStatus={backendStatus} checkBackend={() => void checkBackend()} identity={identity} identityStatus={identityStatus} identityError={identityError} onRetry={retryIdentity} />
    if (identityStatus !== 'authorized' || !identity?.roles.includes('candidate')) return <IdentityAccessPage role="candidate" status={identityStatus} identity={identity} error={identityError} navigate={navigate} onRetry={retryIdentity} onSignOut={() => void signOut()} backendStatus={backendStatus} checkBackend={() => void checkBackend()} />
    if (decodeURIComponent(assessmentMatch[1]) !== 'demo') {
      if (!assessmentMatch[2]) return <AssessmentUnavailable assessmentId={decodeURIComponent(assessmentMatch[1])} navigate={navigate} session={session} onSignOut={() => void signOut()} backendStatus={backendStatus} checkBackend={() => void checkBackend()} />
      return <LiveCandidateWorkspace key={decodeURIComponent(assessmentMatch[2])} assessmentId={decodeURIComponent(assessmentMatch[1])} attemptId={decodeURIComponent(assessmentMatch[2])} accessToken={session.access_token} onSignOut={() => void signOut()} backendStatus={backendStatus} checkBackend={() => void checkBackend()} navigate={navigate} />
    }
  }
  if (!authMatch && !dashboardMatch && !assessmentMatch) return <LandingPage navigate={navigate} session={session} authLoading={authLoading} onSignOut={() => void signOut()} backendStatus={backendStatus} checkBackend={() => void checkBackend()} />

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark"><Code2 size={18} /></span><span>Code<span className="brand-accent">Proof</span></span></div>
        <div className="top-divider" />
        <button className="assessment-name" type="button"><span className="assessment-dot" />Two Sum Â· Demo preview <ChevronDown size={14} /></button>
        <div className="topbar-spacer" />
        <button
          type="button"
          className={`backend-status ${backendStatus}`}
          onClick={() => void checkBackend()}
          disabled={backendStatus === 'checking'}
          aria-label={`Backend ${backendStatus}. ${backendStatus === 'checking' ? 'Health check in progress' : 'Click to retry health check'}`}
          title={backendStatus === 'checking' ? 'Checking backend connection' : 'Click to check backend connection again'}
        >
          <span className="backend-status-dot" aria-hidden="true" />
          {backendStatus === 'checking' ? 'Checking' : backendStatus === 'connected' ? 'Connected' : 'Offline'}
          {backendStatus !== 'checking' && <RefreshCw size={11} aria-hidden="true" />}
        </button>
        {session?.user.email ? <div className="auth-header-actions"><span className="auth-email" title={session.user.email}>{session.user.email}</span><button type="button" className="auth-trigger auth-signout" onClick={() => void signOut()} aria-label="Sign out"><LogOut size={14} /><span>Sign out</span></button></div> : <button type="button" className="auth-trigger" onClick={() => { setAuthError(''); setAuthNotice(''); setAuthDialogOpen(true) }} disabled={authLoading} aria-label={authLoading ? 'Restoring session' : 'Sign in'}><LogIn size={14} /><span>{authLoading ? 'Restoringâ€¦' : 'Sign in'}</span></button>}
        <div className="timer"><Clock3 size={15} /><span>{time}</span><span className="timer-label">remaining</span></div>
        <div className="save-state"><span className="save-dot" />Saved</div>
        <button className="submit-button" onClick={() => setSubmitOpen(true)} type="button">Submit assessment <ChevronRight size={15} /></button>
      </header>

      <div className="workspace-toolbar">
        <div className="toolbar-group">
          <button className="icon-button" aria-label={showLeft ? 'Hide problem panel' : 'Show problem panel'} onClick={() => setShowLeft(!showLeft)}>{showLeft ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}</button>
          <span className="crumb">Assessment <ChevronRight size={13} /> <b>Two Sum</b></span>
        </div>
        <div className="toolbar-center"><span className="live-dot" />Demo workspace Â· no assessment loaded</div>
        <div className="toolbar-group toolbar-end"><button className="icon-button" aria-label={showRight ? 'Hide assistant panel' : 'Show assistant panel'} onClick={() => setShowRight(!showRight)}>{showRight ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}</button><button className="icon-button" aria-label="Help"><CircleHelp size={16} /></button></div>
      </div>

      <div className="workspace">
        <Allotment key={`${showLeft}-${showRight}`}>
          {showLeft && <Allotment.Pane minSize={245} preferredSize="25%"><ProblemPanel language={language} /></Allotment.Pane>}
          <Allotment.Pane minSize={360} preferredSize="51%"><EditorPanel language={language} setLanguage={setLanguage} code={code} setCode={setCode} activeTab={activeTab} setActiveTab={setActiveTab} hasRun={hasRun} onRun={() => { setHasRun(true); setActiveTab('Test Cases') }} /></Allotment.Pane>
          {showRight && <Allotment.Pane minSize={260} preferredSize="24%"><AssistantPanel messages={messages} input={chatInput} setInput={setChatInput} onSend={sendMessage} onSubmit={submitChat} /></Allotment.Pane>}
        </Allotment>
      </div>

      {submitOpen && <div className="modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setSubmitOpen(false) }}><section className="submit-dialog" role="dialog" aria-modal="true" aria-labelledby="submit-title"><div className="dialog-icon"><Check size={21} /></div><button className="dialog-close icon-button" aria-label="Close dialog" onClick={() => setSubmitOpen(false)}><X size={17} /></button><h2 id="submit-title">Ready to submit?</h2><p>This is a demo assessment. Your code will stay in this browser and nothing will be sent.</p><div className="dialog-summary"><span>Assessment</span><b>Two Sum</b><span>Time remaining</span><b>{time}</b></div><div className="dialog-actions"><button className="secondary-button" onClick={() => setSubmitOpen(false)}>Keep working</button><button className="submit-button" onClick={() => setSubmitOpen(false)}>Finish demo <ChevronRight size={15} /></button></div></section></div>}
      {authDialogOpen && <div className="modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !authSubmitting) setAuthDialogOpen(false) }}><section className="submit-dialog auth-dialog" role="dialog" aria-modal="true" aria-labelledby="auth-title"><div className="dialog-icon"><Code2 size={20} /></div><button className="dialog-close icon-button" aria-label="Close sign-in dialog" onClick={() => setAuthDialogOpen(false)} disabled={authSubmitting}><X size={17} /></button><h2 id="auth-title">{authMode === 'sign-in' ? 'Welcome back' : 'Create your account'}</h2><p>Sign in to CodeProof with your email and password. Authentication is handled by Supabase.</p>{!supabase && <p className="auth-config-error" role="alert">{supabaseConfigError}</p>}{authError && <p className="auth-error" role="alert">{authError}</p>}{authNotice && <p className="auth-notice" role="status">{authNotice}</p>}<form className="auth-form" onSubmit={event => void submitAuth(event)}><label htmlFor="auth-email">Email</label><input id="auth-email" type="email" autoComplete="email" required value={authEmail} onChange={event => setAuthEmail(event.target.value)} disabled={!supabase || authSubmitting} /><label htmlFor="auth-password">Password</label><input id="auth-password" type="password" autoComplete={authMode === 'sign-up' ? 'new-password' : 'current-password'} minLength={6} required value={authPassword} onChange={event => setAuthPassword(event.target.value)} disabled={!supabase || authSubmitting} /><button className="submit-button auth-submit" type="submit" disabled={!supabase || authSubmitting}>{authSubmitting ? 'Please waitâ€¦' : authMode === 'sign-in' ? 'Sign in' : 'Create account'}</button></form><div className="auth-mode-switch">{authMode === 'sign-in' ? 'New to CodeProof?' : 'Already have an account?'} <button type="button" disabled={authSubmitting} onClick={() => { setAuthMode(authMode === 'sign-in' ? 'sign-up' : 'sign-in'); setAuthError(''); setAuthNotice('') }}>{authMode === 'sign-in' ? 'Create an account' : 'Sign in'}</button></div></section></div>}
    </main>
  )
}

type AppRole = 'candidate' | 'evaluator'

function SiteHeader({ navigate, session, onSignOut, backendStatus, checkBackend }: { navigate: (path: string) => void; session: Session | null; onSignOut: () => void; backendStatus: BackendStatus; checkBackend: () => void }) {
  return <header className="site-header"><button className="site-brand" onClick={() => navigate('/')} type="button"><span className="brand-mark"><Code2 size={18} /></span><span>Code<span className="brand-accent">Proof</span></span></button><nav aria-label="Main navigation" className="site-nav"><a href="#how-it-works">How it works</a><a href="#features">Features</a></nav><div className="site-header-actions"><BackendIndicator status={backendStatus} onRetry={checkBackend} />{session ? <><span className="site-user" title={session.user.email ?? undefined}>{session.user.email ?? 'Signed in'}</span><button className="site-button subtle" onClick={onSignOut} type="button">Sign out</button></> : <button className="site-button subtle" onClick={() => navigate('/auth/candidate')} type="button">Sign in</button>}</div></header>
}

function BackendIndicator({ status, onRetry }: { status: BackendStatus; onRetry: () => void }) {
  return <button type="button" className={`backend-status ${status}`} onClick={onRetry} disabled={status === 'checking'} aria-label={`Backend ${status}. Click to retry`} title="Backend health check"><span className="backend-status-dot" aria-hidden="true" />{status === 'checking' ? 'Checking' : status === 'connected' ? 'Connected' : 'Offline'}{status !== 'checking' && <RefreshCw size={11} aria-hidden="true" />}</button>
}

function LandingPage({ navigate, session, authLoading, onSignOut, backendStatus, checkBackend }: { navigate: (path: string) => void; session: Session | null; authLoading: boolean; onSignOut: () => void; backendStatus: BackendStatus; checkBackend: () => void }) {
  return <div className="marketing-shell"><SiteHeader navigate={navigate} session={session} onSignOut={onSignOut} backendStatus={backendStatus} checkBackend={checkBackend} /><main className="marketing-page"><section className="hero-section"><div className="hero-copy"><div className="eyebrow"><span className="eyebrow-dot" />CODING ASSESSMENT FOR THE AI ERA</div><h1>Measure how people <em>think</em>, not just what they can prompt.</h1><p className="hero-lede">CodeProof helps teams understand real coding ability in an AI-assisted world, with structured assessments, thoughtful questions, and evidence-backed results.</p><div className="hero-actions"><button className="role-button candidate-role" onClick={() => navigate('/auth/candidate')} type="button">Continue as Candidate <ChevronRight size={16} /></button><button className="role-button evaluator-role" onClick={() => navigate('/auth/evaluator')} type="button">Continue as Evaluator <ChevronRight size={16} /></button></div><div className="hero-signin">{session ? <>Signed in as {session.user.email ?? 'your account'} Â· <button onClick={onSignOut} type="button">Sign out</button></> : <>Already have an account? <button onClick={() => navigate('/auth/candidate')} type="button" disabled={authLoading}>Sign in</button><span>Â·</span><button onClick={() => navigate('/auth/candidate?mode=sign-up')} type="button" disabled={authLoading}>Create account</button></>}</div></div><div className="hero-visual" aria-label="Illustration of a coding assessment workspace"><div className="visual-glow" /><div className="visual-window"><div className="visual-window-bar"><span /><span /><span /><b>CodeProof / assessment</b></div><div className="visual-window-content"><div className="visual-problem"><small>QUESTION 01</small><strong>Two Sum</strong><span>Find the pair that reaches the target.</span><i>Evidence over guesswork</i></div><div className="visual-editor"><div className="visual-editor-tab"><span>Py</span> solution.py</div><pre><code><span className="code-purple">def</span> two_sum(nums, target):<br />  seen = {'{}'}<br />  <span className="code-purple">for</span> i, n <span className="code-purple">in</span> enumerate(nums):<br />    need = target - n<br />    <span className="code-purple">if</span> need <span className="code-purple">in</span> seen:<br />      <span className="code-green">return</span> seen[need], i</code></pre><div className="visual-check"><Check size={13} /> Reasoning captured</div></div></div><div className="visual-caption"><span className="visual-dot" /> A clearer view of coding ability</div></div></div></section><section className="how-section" id="how-it-works"><div className="section-kicker">HOW CODEPROOF WORKS</div><h2>From a focused question to a confident decision.</h2><div className="steps-grid"><article><span>01</span><h3>Build with intention</h3><p>Evaluators configure questions, language options, timing, and test parameters for the skills they need to assess.</p></article><article><span>02</span><h3>Let candidates show their work</h3><p>Candidates solve practical coding problems in a purpose-built workspace designed for clear, focused assessment.</p></article><article><span>03</span><h3>Review the evidence</h3><p>Use candidate work and structured reports to make decisions with more context than a final answer alone.</p></article></div></section><section className="features-section" id="features"><div><div className="section-kicker">BUILT FOR BOTH SIDES</div><h2>Assessment that works beyond the answer.</h2></div><div className="feature-grid"><FeatureCard icon="âŒ˜" title="Configurable coding assessments" detail="Build multi-question assessments around your role, skill level, timing, and test parameters." /><FeatureCard icon="âœ¦" title="AI-assisted question drafting" detail="Help evaluators draft and refine question ideas. AI generation is not connected in this preview." /><FeatureCard icon="â—Ž" title="Public practice tests" detail="Give candidates a place to explore practice assessments and build confidence." /><FeatureCard icon="â†—" title="Evidence-based evaluation" detail="Review the candidateâ€™s process and work in context instead of relying on a single signal." /><FeatureCard icon="â–¤" title="Clear result reports" detail="Bring assessment outcomes into a structured report for consistent review and discussion." /><FeatureCard icon="âŒ" title="Python and C workspace" detail="A focused Monaco-powered editor with language-specific coding environments." /></div></section><section className="closing-cta"><div><div className="section-kicker">START WITH THE RIGHT EXPERIENCE</div><h2>Ready to see what CodeProof can do?</h2></div><div className="closing-actions"><button className="role-button candidate-role" onClick={() => navigate('/auth/candidate')} type="button">Iâ€™m a Candidate <ChevronRight size={15} /></button><button className="role-button evaluator-role" onClick={() => navigate('/auth/evaluator')} type="button">Iâ€™m an Evaluator <ChevronRight size={15} /></button></div></section><footer className="site-footer"><span>Â© CodeProof</span><span>Thoughtful assessment for a changing world of work.</span></footer></main></div>
}

function FeatureCard({ icon, title, detail }: { icon: string; title: string; detail: string }) {
  return <article className="feature-card"><span className="feature-icon" aria-hidden="true">{icon}</span><h3>{title}</h3><p>{detail}</p></article>
}

function AuthPage({ role, navigate, session, authLoading, mode, setMode, email, setEmail, password, setPassword, error, notice, submitting, submit, onSignOut, backendStatus, checkBackend, identity, identityStatus, identityError, onRetry }: { role: AppRole; navigate: (path: string) => void; session: Session | null; authLoading: boolean; mode: AuthMode; setMode: (mode: AuthMode) => void; email: string; setEmail: (email: string) => void; password: string; setPassword: (password: string) => void; error: string; notice: string; submitting: boolean; submit: (event: FormEvent<HTMLFormElement>) => void; onSignOut: () => void; backendStatus: BackendStatus; checkBackend: () => void; identity: CurrentUserResponse | null; identityStatus: IdentityStatus; identityError: string; onRetry: () => void }) {
  const roleLabel = role === 'candidate' ? 'Candidate' : 'Evaluator'
  return <div className="marketing-shell"><SiteHeader navigate={navigate} session={session} onSignOut={onSignOut} backendStatus={backendStatus} checkBackend={checkBackend} /><main className="auth-page"><button className="back-link" type="button" onClick={() => navigate('/')}><ChevronLeft size={15} /> Back to CodeProof</button><section className="auth-card"><div className="auth-role-tag"><Code2 size={14} /> {roleLabel} access</div><h1>{session ? 'Verifying CodeProof access' : mode === 'sign-in' ? `Sign in as a ${roleLabel.toLowerCase()}` : `Create a ${roleLabel.toLowerCase()} account`}</h1>{authLoading ? <p className="auth-page-copy">Restoring your session…</p> : session ? <><p className="auth-page-copy">Signed in as <strong>{session.user.email ?? 'your account'}</strong>. Access is checked against your verified profile and database-assigned roles.</p><IdentityStatusMessage status={identityStatus} identity={identity} role={role} error={identityError} /><div className="identity-actions">{(identityStatus === 'unavailable' || identityStatus === 'expired') && <button className="site-button subtle" type="button" onClick={onRetry}>Retry verification</button>}<button className="auth-text-button" onClick={onSignOut} type="button">Sign out</button></div></> : <><p className="auth-page-copy">Use your email and password. Your selected experience sets the sign-in context only; it does not grant a platform role.</p>{error && <p className="auth-error" role="alert">{error}</p>}{notice && <p className="auth-notice" role="status">{notice}</p>}{!supabase && <p className="auth-config-error" role="alert">{supabaseConfigError}</p>}<form className="auth-form auth-page-form" onSubmit={event => submit(event)}><label htmlFor="page-auth-email">Email</label><input id="page-auth-email" type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} disabled={!supabase || submitting} /><label htmlFor="page-auth-password">Password</label><input id="page-auth-password" type="password" autoComplete={mode === 'sign-up' ? 'new-password' : 'current-password'} minLength={6} required value={password} onChange={event => setPassword(event.target.value)} disabled={!supabase || submitting} /><button type="submit" className="role-button candidate-role auth-page-submit" disabled={!supabase || submitting}>{submitting ? 'Please wait…' : mode === 'sign-in' ? 'Sign in' : 'Create account'} <ChevronRight size={15} /></button></form><div className="auth-mode-switch">{mode === 'sign-in' ? 'New to CodeProof?' : 'Already have an account?'} <button type="button" disabled={submitting} onClick={() => setMode(mode === 'sign-in' ? 'sign-up' : 'sign-in')}>{mode === 'sign-in' ? 'Create an account' : 'Sign in'}</button></div></>}</section><p className="auth-footnote">Your account’s permissions are verified by CodeProof, not by this selection.</p></main></div>
}

function IdentityStatusMessage({ status, identity, role, error }: { status: IdentityStatus; identity: CurrentUserResponse | null; role: ApplicationRole; error: string }) {
  if (status === 'loading' || status === 'idle') return <div className="pending-access" role="status"><span className="pending-access-dot" />Checking your verified access…</div>
  if (status === 'unavailable') return <p className="auth-error" role="alert">Could not verify access because the CodeProof backend is unavailable. {error}</p>
  if (status === 'expired') return <p className="auth-error" role="alert">Your session could not be verified. {error}</p>
  if (identity?.roles.includes(role)) return <div className="pending-access" role="status"><span className="pending-access-dot" />Access verified. Opening your dashboard…</div>
  if (!identity?.roles.length) return <div className="pending-access" role="status"><span className="pending-access-dot" />Your account has no assigned role yet. Access is pending administrator review.</div>
  return <div className="pending-access" role="status"><span className="pending-access-dot" />Your account does not have {role} access. Assigned roles: {identity.roles.join(', ')}.</div>
}

function IdentityAccessPage({ role, status, identity, error, navigate, onRetry, onSignOut, backendStatus, checkBackend }: { role: ApplicationRole; status: IdentityStatus; identity: CurrentUserResponse | null; error: string; navigate: (path: string) => void; onRetry: () => void; onSignOut: () => void; backendStatus: BackendStatus; checkBackend: () => void }) {
  const title = status === 'loading' || status === 'idle' ? 'Checking your access' : status === 'unavailable' ? 'Access check unavailable' : status === 'expired' ? 'Sign-in needs attention' : 'Access pending'
  return <div className="marketing-shell"><SiteHeader navigate={navigate} session={null} onSignOut={onSignOut} backendStatus={backendStatus} checkBackend={checkBackend} /><main className="unavailable-page"><section className="unavailable-card"><div className="auth-role-tag"><Code2 size={14} /> VERIFIED ACCOUNT ACCESS</div><h1>{title}</h1><IdentityStatusMessage status={status} identity={identity} role={role} error={error} />{status === 'unavailable' || status === 'expired' ? <button className="site-button subtle auth-home-button" type="button" onClick={onRetry}>Retry verification</button> : null}{identity?.roles.some(assigned => assigned !== role) && <button className="role-button candidate-role" type="button" onClick={() => navigate(`/${identity.roles[0]}/dashboard`)}>Open your assigned dashboard <ChevronRight size={15} /></button>}<button className="auth-text-button" onClick={onSignOut} type="button">Sign out</button></section></main></div>
}
function AccessStatePage({ title, message, navigate, onSignOut, backendStatus, checkBackend }: { title: string; message: string; navigate: (path: string) => void; onSignOut: () => void; backendStatus: BackendStatus; checkBackend: () => void }) {
  return <div className="marketing-shell"><SiteHeader navigate={navigate} session={null} onSignOut={onSignOut} backendStatus={backendStatus} checkBackend={checkBackend} /><main className="unavailable-page"><section className="unavailable-card"><div className="auth-role-tag"><Code2 size={14} /> ACCOUNT ACCESS</div><h1>{title}</h1><p className="auth-page-copy">{message}</p></section></main></div>
}

function AssessmentUnavailable({ assessmentId, navigate, session, onSignOut, backendStatus, checkBackend }: { assessmentId: string; navigate: (path: string) => void; session: Session; onSignOut: () => void; backendStatus: BackendStatus; checkBackend: () => void }) {
  return <div className="marketing-shell"><SiteHeader navigate={navigate} session={session} onSignOut={onSignOut} backendStatus={backendStatus} checkBackend={checkBackend} /><main className="unavailable-page"><div className="unavailable-card"><div className="auth-role-tag"><Code2 size={14} /> CANDIDATE ASSESSMENT</div><h1>Assessment not connected</h1><p>Assessment <code>{assessmentId}</code> has no active attempt in this route. Open the assessment details, review the instructions, and start or resume a persisted attempt. Real assessments never load the Two Sum demo data.</p><button className="role-button candidate-role" onClick={() => navigate('/candidate/dashboard')} type="button">Back to candidate space <ChevronRight size={15} /></button></div></main></div>
}

function PanelHeading({ icon, title, trailing }: { icon: React.ReactNode; title: string; trailing?: React.ReactNode }) {
  return <div className="panel-heading"><div className="panel-heading-title">{icon}<span>{title}</span></div>{trailing}</div>
}

function WorkspaceFact({ label, value }: { label: string; value: string }) {
  return <div className="workspace-detail-fact"><span>{label}</span><b>{value}</b></div>
}

function ProblemPanel({ language, assessment, question, questionIndex = 0, questionCount = 0, onSelectQuestion }: {
  language: Language; assessment?: CandidateAssessmentRecord; question?: CandidateQuestionRecord;
  questionIndex?: number; questionCount?: number; onSelectQuestion?: (index: number) => void
}) {
  if (assessment && question) return <section className="problem-panel panel-column"><PanelHeading icon={<FileCode2 size={15} />} title="Problem" trailing={questionCount > 1 ? <label className="problem-question-select"><span>Question</span><select value={questionIndex} onChange={event => onSelectQuestion?.(Number(event.target.value))}>{assessment.questions?.map((item, index) => <option key={item.id} value={index}>{index + 1}. {item.title}</option>)}</select></label> : undefined} />
    <div className="problem-scroll"><div className="problem-title-row"><h1>{question.title}</h1><span className="difficulty">{question.difficulty}</span></div><p className="problem-lede">{question.prompt}</p><div className="section-label">ASSESSMENT INSTRUCTIONS</div><p className="problem-copy">{assessment.instructions || 'Follow the question requirements and save your response before submitting.'}</p><div className="section-label">PROBLEM</div><p className="problem-copy">{question.problem_statement || question.prompt}</p>{question.examples && <><div className="example-heading">Examples</div><pre className="candidate-example-text">{question.examples}</pre></>}{question.public_examples.map((example, index) => <div className="example-block" key={index}><div><b>Public example {index + 1} · Input</b><code>{example.input_data || '(empty)'}</code></div><div><b>Expected output</b><code>{example.expected_output || '(empty)'}</code></div></div>)}{question.question_type === 'multiple-choice' && question.answer_options.length > 0 && <div className="question-subsection"><div className="section-label">ANSWER OPTIONS</div><ul className="constraints">{question.answer_options.map((option, index) => <li key={index}>{option}</li>)}</ul></div>}<div className="detail-facts"><WorkspaceFact label="Points" value={String(question.points)} /><WorkspaceFact label="Time limit" value={`${Math.ceil(question.time_limit_seconds / 60)} min`} /><WorkspaceFact label="Languages" value={(question.allowed_languages.length ? question.allowed_languages : assessment.allowed_languages).join(', ')} /><WorkspaceFact label="Assessment" value={assessment.title} /></div></div><div className="panel-footer"><span><Check size={13} /> Responses save to your attempt</span><span>{language === 'python' ? 'Python' : 'C'}</span></div></section>
  return <section className="problem-panel panel-column"><PanelHeading icon={<FileCode2 size={15} />} title="Problem" trailing={<button className="quiet-icon" aria-label="Collapse problem"><ChevronLeft size={15} /></button>} />
    <div className="problem-scroll"><div className="problem-title-row"><h1>Two Sum</h1><span className="difficulty">Easy</span></div><p className="problem-lede">Find the two numbers that add up to the target.</p>
      <div className="section-label">DESCRIPTION</div><p className="problem-copy">Given an array of integers <code>nums</code> and an integer <code>target</code>, return the indices of the two numbers such that they add up to <code>target</code>.</p><p className="problem-copy">You may assume that each input would have <strong>exactly one solution</strong>, and you may not use the same element twice.</p><p className="problem-copy">You can return the answer in any order.</p>
      <div className="example-heading">Example 1</div><div className="example-block"><div><b>Input</b><code>nums = [2, 7, 11, 15], target = 9</code></div><div><b>Output</b><code>[0, 1]</code></div><div><b>Explanation</b><code>nums[0] + nums[1] == 9</code></div></div>
      <div className="example-heading">Example 2</div><div className="example-block"><div><b>Input</b><code>nums = [3, 2, 4], target = 6</code></div><div><b>Output</b><code>[1, 2]</code></div></div>
      <div className="section-label constraints-label">CONSTRAINTS</div><ul className="constraints"><li>2 â‰¤ nums.length â‰¤ 10<sup>4</sup></li><li>âˆ’10<sup>9</sup> â‰¤ nums[i] â‰¤ 10<sup>9</sup></li><li>âˆ’10<sup>9</sup> â‰¤ target â‰¤ 10<sup>9</sup></li><li>Only one valid answer exists.</li></ul>
      <div className="instructions-card"><div className="instructions-title"><Lightbulb size={15} /> Assessment instructions</div><p>Write a solution in the editor. Use <b>Run code</b> to review mock test results before submitting.</p></div>
    </div>
    <div className="panel-footer"><span><Check size={13} /> All changes saved</span><span>{language === 'python' ? 'Python 3' : 'C'}</span></div>
  </section>
}

function EditorPanel({ language, setLanguage, code, setCode, activeTab, setActiveTab, hasRun, onRun, isAttempt = false, onSaveResponse, savingResponse = false, responseNotice = '', executionStatus = 'not_started', allowedLanguages = ['python', 'c'], showLanguageSelector = true }: {
  language: Language; setLanguage: (language: Language) => void; code: string; setCode: (code: string) => void;
  activeTab: ResultTab; setActiveTab: (tab: ResultTab) => void; hasRun: boolean; onRun: () => void;
  isAttempt?: boolean; onSaveResponse?: () => void; savingResponse?: boolean; responseNotice?: string; executionStatus?: string;
  allowedLanguages?: Language[]; showLanguageSelector?: boolean
}) {
  const languageName = language === 'python' ? 'Python' : 'C'
  const fileName = showLanguageSelector ? (language === 'python' ? 'solution.py' : 'solution.c') : 'response.txt'
  const editorLanguage = showLanguageSelector ? language : 'plaintext'
  const executionLabel: Record<string, string> = { not_started: 'Run unavailable', running: 'Server-side execution is running', completed: 'Execution completed', manual_review: 'Evaluator review required', unavailable: 'Execution unavailable', failed: 'Execution failed', compile_error: 'Compilation failed', runtime_error: 'Runtime error', timeout: 'Time limit exceeded', resource_limit: 'Resource limit reached' }
  const executionDescription = executionStatus === 'running' ? 'The isolated runner is processing this submission. The server will report its result when testing finishes.' : executionStatus === 'completed' ? 'Server-side test execution completed. Result visibility follows the assessment settings.' : executionStatus === 'unavailable' ? 'Your responses are saved. The isolated runner is unavailable, so no score was produced.' : executionStatus === 'failed' ? 'Your responses are saved, but execution could not be completed.' : 'Run Code is disabled in the live workspace. Supported programming answers are tested only after submission when isolated execution is enabled.'
  return <section className="editor-column"><Allotment vertical defaultSizes={[68, 32]}>
    <Allotment.Pane minSize={210}><div className="editor-pane panel-column"><PanelHeading icon={<Braces size={15} />} title={isAttempt ? 'Candidate response' : 'Code editor'} trailing={<div className="editor-actions">{showLanguageSelector ? <><label className="language-select-label" htmlFor="editor-language">Language</label><select id="editor-language" className="language-select" value={language} onChange={event => setLanguage(event.target.value as Language)}>{allowedLanguages.map(item => <option key={item} value={item}>{item === 'python' ? 'Python' : 'C'}</option>)}</select></> : <span className="language-select-label">Text response</span>}<button className="quiet-icon" aria-label="Editor options"><ChevronDown size={15} /></button></div>} />
      <div className="file-tab"><div className="file-tab-active"><span className={`python-icon ${language === 'c' ? 'c-icon' : ''}`}>{language === 'python' ? 'Py' : 'C'}</span><span>{fileName}</span><span className="modified-dot" /></div><div className="editor-tools"><span className="code-status">UTF-8</span><span className="code-status">Spaces: 4</span></div></div>
      <div className="monaco-wrap"><Editor height="100%" language={editorLanguage} theme="vs-dark" value={code} onChange={value => setCode(value ?? '')} options={{ readOnly: isAttempt && !onSaveResponse, minimap: { enabled: false }, fontSize: 13, lineHeight: 22, fontFamily: 'JetBrains Mono, Consolas, monospace', padding: { top: 14, bottom: 14 }, scrollBeyondLastLine: false, automaticLayout: true, tabSize: 4, renderLineHighlight: 'all', overviewRulerBorder: false, scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8 }, suggestOnTriggerCharacters: true }} /></div>
      <div className="statusbar"><span><Braces size={12} /> {languageName}</span><span>Ln 2, Col 9</span><span>Spaces: 4</span><span>UTF-8</span><span className="status-spacer"/><span><Check size={12} /> Ready</span></div>
    </div></Allotment.Pane>
    <Allotment.Pane minSize={150}><div className="results-pane panel-column"><div className="results-heading"><div className="result-tabs">{(['Test Cases', 'Output', 'Terminal'] as ResultTab[]).map(tab => <button key={tab} className={`result-tab ${activeTab === tab ? 'active' : ''}`} onClick={() => setActiveTab(tab)}>{tab === 'Terminal' && <Terminal size={13} />}{tab}{tab === 'Test Cases' && !isAttempt && <span className="tab-count">{hasRun ? '3' : '0'}</span>}</button>)}</div>{isAttempt ? <><button className="run-button" disabled title="Code execution is not available"><Play size={13} /> Run unavailable</button><button className="run-button save-response-button" onClick={onSaveResponse} disabled={savingResponse}>{savingResponse ? 'Saving…' : 'Save response'}</button></> : <button className="run-button" onClick={onRun}><Play size={13} fill="currentColor" /> Run code (demo)</button>}</div>
      <div className="results-content">{isAttempt ? <div className="output-empty"><b>{executionLabel[executionStatus] ?? 'Execution status'}</b><p>{executionDescription}</p>{responseNotice && <small role="status">{responseNotice}</small>}</div> : activeTab === 'Test Cases' ? <TestResults hasRun={hasRun} languageName={languageName} /> : activeTab === 'Output' ? <OutputContent hasRun={hasRun} languageName={languageName} /> : <TerminalContent hasRun={hasRun} languageName={languageName} />}</div>
    </div></Allotment.Pane>
  </Allotment></section>
}

function TestResults({ hasRun, languageName }: { hasRun: boolean; languageName: string }) {
  if (!hasRun) return <div className="empty-results"><div className="empty-icon"><Play size={16} /></div><b>Ready when you are</b><span>Run the demo to see sample test results here.</span><small>Results are simulated and your code is never executed.</small></div>
  return <div className="test-results"><div className="mock-notice"><Sparkles size={13} /> MOCK RESULTS Â· {languageName} Â· Code was not executed</div><div className="test-case-grid"><div className="test-summary"><span className="pass-icon"><Check size={14} /></span><div><b>3 / 3 sample cases passed</b><small>Demo result Â· simulated Â· no execution</small></div></div><span className="mock-badge">SIMULATED</span></div>{[['Case 1', '[2, 7, 11, 15], target = 9', '[0, 1]'], ['Case 2', '[3, 2, 4], target = 6', '[1, 2]'], ['Case 3', '[3, 3], target = 6', '[0, 1]']].map(([name, input, output]) => <div className="case-row" key={name}><span className="case-check"><Check size={12} /></span><b>{name}</b><span className="case-detail">Input: {input}</span><span className="case-output">Expected: {output}</span></div>)}</div>
}

function OutputContent({ hasRun, languageName }: { hasRun: boolean; languageName: string }) {
  return <div className="output-view"><div className="mock-notice"><Sparkles size={13} /> MOCK OUTPUT Â· {languageName} Â· Code was not executed</div>{hasRun ? <pre>{`Demo preview for ${languageName}.\n3 sample cases shown.\n\nThis is simulated output. Your code was not run.`}</pre> : <div className="output-empty">Output will appear here after you run the demo.</div>}</div>
}

function TerminalContent({ hasRun, languageName }: { hasRun: boolean; languageName: string }) {
  return <div className="terminal-view"><div className="terminal-label"><Terminal size={13} /> DEMO TERMINAL Â· {languageName}</div><pre>{hasRun ? `> ${languageName} selected\n> code was not executed\n> sample results simulated\n> ready for your next step` : `> ${languageName} selected\n> Run demo to view simulated output`}</pre><div className="terminal-prompt"><span>â€º</span> <i>Demo terminal is read-only</i></div></div>
}

function AssistantPanel({ messages, input, setInput, onSend, onSubmit }: { messages: ChatMessage[]; input: string; setInput: (value: string) => void; onSend: (text?: string) => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void }) {
  return <section className="assistant-panel panel-column"><PanelHeading icon={<Bot size={15} />} title="AI assistant" trailing={<span className="demo-pill"><span/>Demo</span>} />
    <div className="chat-scroll"><div className="assistant-intro"><div className="assistant-avatar"><Sparkles size={18} /></div><h2>Your coding companion</h2><p>Ask for a hint or talk through your approach. Demo responses are provided locally.</p></div>
      <div className="chat-messages">{messages.map((message, index) => <div className={`message ${message.role}`} key={`${index}-${message.role}`}><div className="message-avatar">{message.role === 'assistant' ? <Sparkles size={13} /> : 'Y'}</div><div className="message-body"><div className="message-author">{message.role === 'assistant' ? 'CodeProof AI' : 'You'}{message.role === 'assistant' && index > 0 && <span>DEMO</span>}</div><p>{message.text}</p></div></div>)}</div>
      {messages.length === 1 && <div className="suggestions"><span>TRY ASKING</span>{prompts.map(prompt => <button key={prompt} onClick={() => onSend(prompt)}>{prompt}<ChevronRight size={13} /></button>)}</div>}
    </div>
    <form className="chat-composer" onSubmit={onSubmit}><textarea aria-label="Message the AI assistant" placeholder="Ask a question..." rows={2} value={input} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); onSend() } }} /><div className="composer-footer"><span><Sparkles size={12} /> Demo assistant Â· No API</span><button className="send-button" type="submit" disabled={!input.trim()} aria-label="Send message"><Send size={14} /></button></div></form>
    <div className="assistant-footnote">AI can make mistakes. Review suggestions carefully.</div>
  </section>
}

function LiveAssistantPanel({ messages, input, setInput, onSend, onHint, pending, error, canShareCode, includeCode, setIncludeCode, active }: {
  messages: ChatMessage[]; input: string; setInput: (value: string) => void;
  onSend: (text: string, includeCode: boolean) => void; onHint: () => void;
  pending: boolean; error: string; canShareCode: boolean; includeCode: boolean;
  setIncludeCode: (value: boolean) => void; active: boolean;
}) {
  const send = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSend(input, includeCode)
  }
  return <section className="assistant-panel panel-column live-assistant-panel" aria-label="Candidate AI assistant">
    <PanelHeading icon={<Bot size={15} />} title="AI assistant" trailing={<span className="assistant-live-pill"><span />Gemini</span>} />
    <div className="chat-scroll">
      <div className="assistant-intro"><div className="assistant-avatar"><Sparkles size={18} /></div><h2>Learn as you solve</h2><p>Ask about concepts, request a hint, or get help understanding an error.</p></div>
      <div className="chat-messages" aria-live="polite">{messages.map((message, index) => <div className={`message ${message.role}`} key={`${index}-${message.role}-${message.text.slice(0, 16)}`}><div className="message-avatar">{message.role === 'assistant' ? <Sparkles size={13} /> : 'Y'}</div><div className="message-body"><div className="message-author">{message.role === 'assistant' ? 'CodeProof AI · Advice' : 'You'}</div><p>{message.text}</p></div></div>)}{pending && <div className="assistant-wait" role="status"><span className="loader-dot" />Preparing an AI response…</div>}</div>
      {messages.length === 1 && <div className="suggestions"><span>TRY ASKING</span>{['Explain this problem in simpler terms', 'Give me a small hint', 'How should I debug this error?'].map(prompt => <button key={prompt} type="button" disabled={!active || pending} onClick={() => prompt === 'Give me a small hint' ? onHint() : onSend(prompt, false)}>{prompt}<ChevronRight size={13} /></button>)}</div>}
    </div>
    {error && <div className="assistant-error" role="alert">{error}</div>}
    <form className="chat-composer live-chat-composer" onSubmit={send}>
      <textarea aria-label="Ask the candidate AI assistant" placeholder="Ask for an explanation or hint…" rows={2} maxLength={1_600} value={input} onChange={event => setInput(event.target.value)} disabled={!active || pending} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); onSend(input, includeCode) } }} />
      {canShareCode && <label className="share-code-option"><input type="checkbox" checked={includeCode} onChange={event => setIncludeCode(event.target.checked)} disabled={!active || pending} />Include my current editor code with this message</label>}
      <div className="composer-footer"><span><Sparkles size={12} /> Advice only · not saved with your answer</span><button className="send-button" type="submit" disabled={!input.trim() || !active || pending} aria-label="Send message to AI assistant">{pending ? <span className="assistant-spinner" /> : <Send size={14} />}</button></div>
    </form>
    <div className="assistant-footnote">Unverified suggestions · chat is not stored with this attempt</div>
  </section>
}

function LiveCandidateWorkspace({ assessmentId, attemptId, accessToken, onSignOut, backendStatus, checkBackend, navigate }: {
  assessmentId: string; attemptId: string; accessToken: string; onSignOut: () => void;
  backendStatus: BackendStatus; checkBackend: () => void; navigate: (path: string) => void
}) {
  const [assessment, setAssessment] = useState<CandidateAssessmentRecord | null>(null)
  const [attempt, setAttempt] = useState<CandidateAttemptRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [activeQuestionIndex, setActiveQuestionIndex] = useState(0)
  const [languagesByQuestion, setLanguagesByQuestion] = useState<Record<string, Language>>({})
  const [codeByQuestion, setCodeByQuestion] = useState<Record<string, string>>({})
  const [savedResponses, setSavedResponses] = useState<Record<string, string>>({})
  const [activeTab, setActiveTab] = useState<ResultTab>('Output')
  const [saving, setSaving] = useState(false)
  const [saveNotice, setSaveNotice] = useState('')
  const [executionStatus, setExecutionStatus] = useState('not_started')
  const [submitOpen, setSubmitOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [now, setNow] = useState(Date.now())
  const [showLeft, setShowLeft] = useState(true)
  const [showRight, setShowRight] = useState(true)
  const [chatInput, setChatInput] = useState('')
  const [assistantPending, setAssistantPending] = useState(false)
  const [assistantError, setAssistantError] = useState('')
  const [shareCode, setShareCode] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'assistant', text: 'Ask for an explanation, a graduated hint, or help understanding an error. AI advice is separate from your saved response and is not verified.' },
  ])

  useEffect(() => {
    let active = true
    setLoading(true); setError('')
    fetchCandidateAttempt(accessToken, attemptId).then(async attemptValue => {
        if (!active) return
        if (attemptValue.assessment_id !== assessmentId) {
          setError('This attempt does not belong to the requested assessment.')
          return
        }
        setAttempt(attemptValue)
        setExecutionStatus(attemptValue.execution_status)
        const responseCodes: Record<string, string> = {}
        const responseLanguages: Record<string, Language> = {}
        const responseValues: Record<string, string> = {}
        for (const response of attemptValue.responses) {
          responseCodes[response.question_id] = response.response_text
          responseValues[response.question_id] = response.response_text
          if (response.programming_language === 'python' || response.programming_language === 'c') responseLanguages[response.question_id] = response.programming_language
        }
        setCodeByQuestion(responseCodes); setSavedResponses(responseValues); setLanguagesByQuestion(responseLanguages)
        if (attemptValue.status !== 'in_progress' || new Date(attemptValue.deadline_at).getTime() <= Date.now()) return
        const assessmentValue = await fetchCandidateAssessment(accessToken, assessmentId)
        if (active) setAssessment(assessmentValue)
      })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'The attempt could not be loaded.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [accessToken, assessmentId, attemptId])

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const questions = assessment?.questions ?? []
  const question = questions[activeQuestionIndex]
  const allowedLanguages = question?.allowed_languages?.length ? question.allowed_languages.filter((item): item is Language => item === 'python' || item === 'c') : (assessment?.allowed_languages.filter((item): item is Language => item === 'python' || item === 'c') ?? ['python'])
  const language = question ? languagesByQuestion[question.id] ?? (question.default_language === 'c' ? 'c' : 'python') : 'python'
  const isCodeQuestion = question?.question_type === 'programming' || question?.question_type === 'debugging'
  const savedCode = question ? codeByQuestion[question.id] ?? savedResponses[question.id] ?? '' : ''
  const code = question ? savedCode || liveStarterCode(language) : ''
  const remainingSeconds = attempt ? Math.max(0, Math.ceil((new Date(attempt.deadline_at).getTime() - now) / 1000)) : 0
  const timer = `${String(Math.floor(remainingSeconds / 60)).padStart(2, '0')}:${String(remainingSeconds % 60).padStart(2, '0')}`
  const isReadOnly = attempt?.status !== 'in_progress' || remainingSeconds <= 0
  useEffect(() => {
    setShareCode(false)
    setAssistantError('')
  }, [question?.id])
  const writeCode = (value: string) => { if (question) { setCodeByQuestion(current => ({ ...current, [question.id]: value })); setSaveNotice('Unsaved changes') } }
  const chooseLanguage = (next: Language) => { if (question) setLanguagesByQuestion(current => ({ ...current, [question.id]: next })) }
  const saveQuestionResponse = async (item: CandidateQuestionRecord, text: string, selectedLanguage: Language) => {
    const response = await saveCandidateResponse(accessToken, attemptId, item.id, text, item.question_type === 'programming' || item.question_type === 'debugging' ? selectedLanguage : null)
    setSavedResponses(current => ({ ...current, [item.id]: response.response_text }))
  }
  const saveActiveResponse = async () => {
    if (!question || isReadOnly) return
    setSaving(true); setSaveNotice('')
    try { await saveQuestionResponse(question, code, language); setSaveNotice('Response saved to this attempt.') }
    catch (reason) { setSaveNotice(reason instanceof Error ? reason.message : 'Response could not be saved.') }
    finally { setSaving(false) }
  }
  const finalizeAttempt = async () => {
    if (!attempt || isReadOnly) return
    setSubmitting(true); setError('')
    try {
      for (const item of questions) {
        const text = item.id === question?.id ? code : codeByQuestion[item.id] ?? savedResponses[item.id] ?? ''
        if (text || savedResponses[item.id] !== undefined) {
          const selected = languagesByQuestion[item.id] ?? (item.default_language === 'c' ? 'c' : 'python')
          await saveQuestionResponse(item, text, selected)
        }
      }
      setSaveNotice('Submitting responses to the server…')
      const statusPoll = window.setInterval(() => {
        void fetchCandidateAttempt(accessToken, attemptId).then(current => {
          setExecutionStatus(current.execution_status)
          if (current.execution_status === 'running') setSaveNotice('Isolated server-side scoring is running…')
        }).catch(() => undefined)
      }, 800)
      let submitted: CandidateAttemptRecord
      try { submitted = await submitCandidateAttempt(accessToken, attemptId) }
      finally { window.clearInterval(statusPoll) }
      setExecutionStatus(submitted.execution_status)
      setAttempt(submitted); setSubmitOpen(false); setSaveNotice('Attempt submitted and recorded.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The attempt could not be submitted.') }
    finally { setSubmitting(false) }
  }
  const sendAssistantMessage = async (text: string, includeCode = false) => {
    const message = text.trim()
    if (!message || assistantPending || !question || !attempt || isReadOnly) return
    setAssistantError('')
    setAssistantPending(true)
    const history: CandidateAssistantTurn[] = messages.slice(1).slice(-8).map(item => ({ role: item.role, text: item.text }))
    try {
      const response = await requestCandidateAssistance(accessToken, {
        assessment_id: assessmentId,
        attempt_id: attemptId,
        question_id: question.id,
        message,
        history,
        include_code: includeCode,
        ...(includeCode ? { code } : {}),
      })
      const userMessage: ChatMessage = { role: 'user', text: message }
      const assistantMessage: ChatMessage = { role: 'assistant', text: response.message }
      setMessages(current => [...current, userMessage, assistantMessage].slice(-20))
      setChatInput('')
      setShareCode(false)
    } catch (reason) {
      setAssistantError(candidateAssistantErrorMessage(reason))
    } finally {
      setAssistantPending(false)
    }
  }

  if (loading) return <div className="unavailable-page"><section className="unavailable-card" role="status"><span className="loader-dot" /> Loading your attempt…</section></div>
  if (attempt && (attempt.status !== 'in_progress' || remainingSeconds <= 0)) return <div className="unavailable-page"><section className="unavailable-card"><div className="auth-role-tag"><Code2 size={14} /> CANDIDATE ATTEMPT</div><h1>{attempt.status === 'submitted' ? 'Attempt submitted' : 'Attempt expired'}</h1><p>{attempt.status !== 'submitted' ? 'The server-enforced attempt deadline has passed. Responses can no longer be changed.' : attempt.execution_status === 'completed' ? attempt.score !== null && attempt.score !== undefined && attempt.max_score !== null && attempt.max_score !== undefined ? `Server-side scoring completed. Your visible result is ${attempt.score} / ${attempt.max_score}.` : 'Server-side scoring completed. Results are hidden by this assessment’s settings.' : attempt.execution_status === 'manual_review' ? 'Your responses were recorded. Some questions require evaluator review; a complete score is not available yet.' : attempt.execution_status === 'unavailable' ? 'Your responses were recorded, but the isolated execution service is unavailable. No score was produced.' : 'Your responses were recorded, but scoring did not complete. No score is available.'}</p>{attempt.status === 'submitted' && attempt.responses.some(response => ['compile_error', 'runtime_error', 'timeout', 'resource_limit'].includes(response.execution_status)) && <p className="attempt-execution-status" role="status">Question execution: {attempt.responses.filter(response => ['compile_error', 'runtime_error', 'timeout', 'resource_limit'].includes(response.execution_status)).map(response => `Question ${Math.max(1, questions.findIndex(item => item.id === response.question_id) + 1)} — ${response.execution_status.replace('_', ' ')}`).join('; ')}.</p>}<button className="role-button candidate-role" onClick={() => navigate('/candidate/history')}>View attempt history <ChevronRight size={15} /></button></section></div>
  if (error || !assessment || !attempt || !question) return <div className="unavailable-page"><section className="unavailable-card"><h1>Attempt unavailable</h1><p role="alert">{error || 'This assessment has no candidate-visible questions.'}</p><button className="role-button candidate-role" onClick={() => navigate('/candidate/history')}>Back to history <ChevronRight size={15} /></button></section></div>

  return <main className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark"><Code2 size={18} /></span><span>Code<span className="brand-accent">Proof</span></span></div><div className="top-divider" /><div className="assessment-name"><span className="assessment-dot" />{assessment.title}</div><div className="topbar-spacer" /><button type="button" className={`backend-status ${backendStatus}`} onClick={checkBackend}><span className="backend-status-dot" />{backendStatus === 'connected' ? 'Connected' : backendStatus === 'checking' ? 'Checking' : 'Offline'}</button><button type="button" className="auth-trigger auth-signout" onClick={onSignOut}><LogOut size={14} /><span>Sign out</span></button><div className="timer"><Clock3 size={15} /><span>{timer}</span><span className="timer-label">remaining</span></div><div className="save-state"><span className="save-dot" />{saveNotice === 'Unsaved changes' ? 'Unsaved' : 'Attempt'}</div><button className="submit-button" onClick={() => setSubmitOpen(true)} type="button">Submit assessment <ChevronRight size={15} /></button></header>
    <div className="workspace-toolbar"><div className="toolbar-group"><button className="icon-button" aria-label={showLeft ? 'Hide problem panel' : 'Show problem panel'} onClick={() => setShowLeft(!showLeft)}>{showLeft ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}</button><span className="crumb">Assessment <ChevronRight size={13} /><b>{assessment.title}</b></span></div><div className="toolbar-center"><span className="live-dot" />Attempt {attempt.attempt_number} · run unavailable · scoring when enabled</div><div className="toolbar-group toolbar-end"><button className="icon-button" aria-label={showRight ? 'Hide assistant panel' : 'Show assistant panel'} onClick={() => setShowRight(!showRight)}>{showRight ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}</button><button className="icon-button" aria-label="Help"><CircleHelp size={16} /></button></div></div>
    <div className="workspace"><Allotment key={`${showLeft}-${showRight}`}>
      {showLeft && <Allotment.Pane minSize={245} preferredSize="25%"><ProblemPanel language={language} assessment={assessment} question={question} questionIndex={activeQuestionIndex} questionCount={questions.length} onSelectQuestion={setActiveQuestionIndex} /></Allotment.Pane>}
      <Allotment.Pane minSize={360} preferredSize="51%"><EditorPanel language={language} setLanguage={chooseLanguage} code={code} setCode={writeCode} activeTab={activeTab} setActiveTab={setActiveTab} hasRun={false} onRun={() => undefined} isAttempt onSaveResponse={() => void saveActiveResponse()} savingResponse={saving} responseNotice={saveNotice} executionStatus={executionStatus} allowedLanguages={allowedLanguages} showLanguageSelector={isCodeQuestion} /></Allotment.Pane>
      {showRight && <Allotment.Pane minSize={260} preferredSize="24%"><LiveAssistantPanel messages={messages} input={chatInput} setInput={setChatInput} onSend={(text, includeCode) => void sendAssistantMessage(text, includeCode)} onHint={() => void sendAssistantMessage('Please give me one small, graduated hint without giving away the full solution.', false)} pending={assistantPending} error={assistantError} canShareCode={isCodeQuestion} includeCode={shareCode} setIncludeCode={setShareCode} active={!isReadOnly} /></Allotment.Pane>}
    </Allotment></div>
    {submitOpen && <div className="modal-backdrop" role="presentation"><section className="submit-dialog" role="dialog" aria-modal="true" aria-labelledby="submit-title"><div className="dialog-icon"><Check size={21} /></div><button className="dialog-close icon-button" aria-label="Close dialog" onClick={() => setSubmitOpen(false)}><X size={17} /></button><h2 id="submit-title">Submit this attempt?</h2><p>Your saved responses will be finalized. If isolated execution is enabled, supported programming questions will be tested and scored on the server; the browser never executes code.</p>{error && <p className="auth-error" role="alert">{error}</p>}<div className="dialog-summary"><span>Assessment</span><b>{assessment.title}</b><span>Time remaining</span><b>{timer}</b></div><div className="dialog-actions"><button className="secondary-button" disabled={submitting} onClick={() => setSubmitOpen(false)}>Keep working</button><button className="submit-button" disabled={submitting} onClick={() => void finalizeAttempt()}>{submitting ? 'Submitting responses…' : 'Submit attempt'} <ChevronRight size={15} /></button></div></section></div>}
  </main>
}

function liveStarterCode(language: Language) {
  return language === 'python'
    ? '# Write your solution for this question.\n'
    : '#include <stdio.h>\n\nint main(void) {\n    /* Write your solution for this question. */\n    return 0;\n}\n'
}

export default App
