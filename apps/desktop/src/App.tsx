import { useEffect, useRef, useState } from 'react';
import {
  AudioLines, BookOpen, Check, ChevronRight, CircleHelp, File, FileSpreadsheet, FileText,
  GraduationCap, Headphones, LayoutDashboard, LockKeyhole, Plus, Search,
  Send, Settings, Shield, Sparkles, Trash2, UploadCloud, WifiOff, X,
} from 'lucide-react';
import { api } from './api';
import {LiveSuggestion, type LiveSuggestionEvent} from './features/live/LiveSuggestion';
import type { AnswerResponse, DocumentRecord, Feedback, LiveEvent, PracticeQuestion, Session, SessionReport } from './types';

type Page = 'overview' | 'knowledge' | 'practice' | 'live' | 'settings';
const NAV: { id: Page; label: string; icon: typeof BookOpen }[] = [
  {id:'overview', label:'Overview', icon: LayoutDashboard},
  {id:'knowledge', label:'Knowledge Base', icon: BookOpen},
  {id:'practice', label:'Practice Interview', icon: GraduationCap},
  {id:'live', label:'Live Interview', icon: Headphones},
  {id:'settings', label:'Settings', icon: Settings},
];
function SourceTag({source}: {source: AnswerResponse['source']}) {
  if (!source) return null;
  return <div className="source-tag"><FileText size={14} /><span>{source.document_name}</span><span className="source-separator">/</span><span>{source.location}</span></div>;
}
function EmptyState({icon: Icon, title, body}: {icon: typeof BookOpen; title: string; body: string}) {
  return <div className="empty-state"><div className="empty-icon"><Icon size={25}/></div><h3>{title}</h3><p>{body}</p></div>;
}

export default function App() {
  const [page, setPage] = useState<Page>('overview');
  const [connected, setConnected] = useState(false);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const refresh = async () => { try { const result = await api.documents(); setDocuments(result.documents); setConnected(true); } catch { setConnected(false); } };
  useEffect(() => { void api.health().then(() => setConnected(true)).catch(() => setConnected(false)); void refresh(); }, []);
  const navigate = (to: Page) => {setPage(to); setError(''); setNotice('');};
  const showError = (err: unknown) => setError(err instanceof Error ? err.message : 'Error desconocido');
  const onUpload = async (file: File) => {
    setError(''); setNotice('');
    try { const result = await api.upload(file); setNotice(`${result.name}: ${result.entry_count} entradas indexadas.`); await refresh(); }
    catch(err) { showError(err); }
  };
  return <div className="app-layout">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><AudioLines size={23}/></div><div><b>Interview<span>Copilot</span></b><small>YOUR AI INTERVIEW WORKSPACE</small></div></div>
      <div className="workspace-label">WORKSPACE</div>
      <nav className="sidebar-nav">{NAV.map(item => <button key={item.id} type="button" className={`nav-link ${page === item.id ? 'active' : ''}`} onClick={() => navigate(item.id)}><item.icon size={18}/><span>{item.label}</span>{page === item.id && <ChevronRight size={16} className="nav-arrow"/>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="privacy-tile"><Shield size={18}/><div><strong>Private by design</strong><span>Documents stored locally</span></div></div><div className="profile"><div className="avatar">IC</div><div><strong>Personal workspace</strong><span>Version 0.1.2 · Local preview</span></div></div></div>
    </aside>
    <main className="main-area">
      <div className="topbar"><div className="breadcrumb">WORKSPACE <ChevronRight size={13}/> <strong>{NAV.find(n=>n.id===page)?.label}</strong></div><div className={`status ${connected ? 'online':'offline'}`}>{connected ? <Check size={14}/> : <WifiOff size={14}/>} {connected ? 'API connected' : 'API offline'}</div></div>
      {error && <div role="alert" className="alert error"><CircleHelp size={17}/>{error}<button onClick={()=>setError('')} aria-label="Cerrar"><X size={16}/></button></div>}
      {notice && <div role="status" className="alert success"><Check size={17}/>{notice}<button onClick={()=>setNotice('')} aria-label="Cerrar"><X size={16}/></button></div>}
      <div className="content">
        {page === 'overview' && <Overview docs={documents} navigate={navigate}/>}
        {page === 'knowledge' && <Knowledge docs={documents} onUpload={onUpload} refresh={refresh} showError={showError} onNotice={setNotice}/>}
        {page === 'practice' && <Practice showError={showError}/>}
        {page === 'live' && <Live showError={showError}/>}
        {page === 'settings' && <SettingsPage />}
      </div>
    </main>
  </div>;
}

function Overview({docs,navigate}: {docs: DocumentRecord[]; navigate: (p:Page)=>void}) {
  return <>
    <div className="eyebrow"><span className="eyebrow-dot"/> YOUR PERSONAL AI ASSISTANT</div>
    <h1>Get ready for your <em>next big opportunity.</em></h1>
    <p className="page-description">Your knowledge, your answers, your interview preparation. Everything in one workspace.</p>
    <div className="stats"><div className="stat"><div>Knowledge documents</div><strong>{docs.length.toString().padStart(2,'0')}</strong><span>Local library</span></div><div className="stat"><div>Indexed knowledge entries</div><strong>{docs.reduce((acc,d)=>acc+d.entry_count,0)}</strong><span>Ready for retrieval</span></div><div className="stat"><div>Available interview modes</div><strong>02</strong><span>Practice + Live audio</span></div></div>
    <h2 className="section-heading">Your workspace <span>Choose where to start</span></h2>
    <div className="feature-grid">
      <button className="feature-card" onClick={()=>navigate('practice')}><span className="feature-icon violet"><GraduationCap size={24}/></span><span className="feature-kicker">LEARN & IMPROVE</span><strong>Practice Interview</strong><span>Practice questions from your own files and compare your answers with trusted references.</span><span className="feature-cta">Start practicing <ChevronRight size={17}/></span></button>
      <button className="feature-card" onClick={()=>navigate('live')}><span className="feature-icon cyan"><Headphones size={24}/></span><span className="feature-kicker">ON-DEMAND ASSISTANCE</span><strong>Live Interview</strong><span>Capture Windows system audio with consent, transcribe questions and retrieve documented answers.</span><span className="feature-cta">Open live mode <ChevronRight size={17}/></span></button>
    </div>
    <div className="onboarding"><div className="onboarding-icon"><UploadCloud size={23}/></div><div><strong>Build your personal knowledge base</strong><p>Upload XLSX, DOCX, PDF, TXT or Markdown to retrieve source-backed answers.</p></div><button className="btn secondary" onClick={()=>navigate('knowledge')}>Add documents <Plus size={16}/></button></div>
  </>;
}

function Knowledge({docs,onUpload,refresh,showError,onNotice}: {docs: DocumentRecord[]; onUpload: (file:File)=>Promise<void>; refresh:()=>Promise<void>; showError:(err:unknown)=>void; onNotice:(s:string)=>void}) {
  const picker = useRef<HTMLInputElement>(null);
  const [busy,setBusy] = useState(false);
  const [query,setQuery] = useState('');
  const [answer,setAnswer] = useState<AnswerResponse|null>(null);
  const [loading,setLoading] = useState(false);
  const select = async (file?: File) => { if (!file) return; setBusy(true); try {await onUpload(file);} finally {setBusy(false);} };
  const ask = async () => { if (query.trim().length < 3) return; setLoading(true); try {setAnswer(await api.answer(query.trim()));} catch(err) {showError(err);} finally {setLoading(false);} };
  const remove = async (id: string) => { if (!window.confirm('¿Eliminar este documento y su índice?')) return; try {await api.deleteDocument(id);onNotice('Documento eliminado.');await refresh();} catch(err) {showError(err);} };
  return <><div className="page-header"><div><div className="eyebrow">KNOWLEDGE MANAGEMENT</div><h1>Knowledge Base</h1><p className="page-description">Your source of truth for every interview answer.</p></div><button className="btn primary" onClick={()=>picker.current?.click()} disabled={busy}><Plus size={17}/> Add documents</button></div>
    <input className="visually-hidden" ref={picker} type="file" accept=".xlsx,.docx,.pdf,.txt,.md" onChange={e=>{void select(e.target.files?.[0]);e.target.value='';}}/>
    <div className="upload-zone" onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();void select(e.dataTransfer.files?.[0]);}} onClick={()=>picker.current?.click()} role="button" tabIndex={0} onKeyDown={e=>{if(e.key==='Enter') picker.current?.click();}}><div className="upload-icon"><UploadCloud size={27}/></div><strong>{busy ? 'Importando documento...' : 'Arrastra un documento o haz clic para elegirlo'}</strong><span>Excel (.xlsx), Word (.docx), PDF, TXT y Markdown · Máximo 20 MB</span></div>
    <div className="panel"><div className="panel-title"><h2>Imported documents <span className="counter">{docs.length}</span></h2><span className="hint">Stored locally</span></div>{docs.length ? <div className="document-list">{docs.map(doc=><div className="document-row" key={doc.id}><div className="doc-icon">{doc.extension==='.xlsx'?<FileSpreadsheet size={22}/>:<File size={22}/>}</div><div className="doc-details"><strong>{doc.name}</strong><span>{doc.entry_count} entries · {doc.extension.toUpperCase().slice(1)}</span></div><button title="Eliminar documento" className="icon-btn" onClick={()=>void remove(doc.id)}><Trash2 size={17}/></button></div>)}</div>:<EmptyState icon={BookOpen} title="No documents yet" body="Upload your first file to start building the knowledge base."/>}</div>
    <div className="panel query-panel"><div className="panel-title"><h2>Test your knowledge base</h2><span className="hint">Source-grounded retrieval</span></div><div className="ask-row"><Search size={19}/><input value={query} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')void ask();}} placeholder="What is refresh token rotation?"/><button className="btn primary" disabled={loading||query.trim().length<3} onClick={()=>void ask()}>{loading?'Searching...':'Ask'} <Send size={16}/></button></div>{answer && <AnswerCard answer={answer}/>}</div>
  </>;
}
function AnswerCard({answer}: {answer:AnswerResponse}) {
  if (answer.status!=='found') return <div className="answer-box no-evidence"><CircleHelp size={17}/> No se encontró información suficiente en tus archivos. No generamos una respuesta sin evidencia.</div>;
  return <div className="answer-box"><div className="answer-heading"><Sparkles size={17}/> {answer.match_type==='document_excerpt'?'Document excerpt':'Answer from your files'} <span className="tiny-pill">{answer.match_type?.replaceAll('_',' ')}</span></div><p>{answer.answer}</p><SourceTag source={answer.source}/></div>;
}
function Practice({showError}: {showError:(e:unknown)=>void}) {
  const [session,setSession] = useState<Session|null>(null);
  const [question,setQuestion] = useState<PracticeQuestion|null>(null);
  const [draft,setDraft] = useState('');
  const [feedback,setFeedback] = useState<Feedback|null>(null);
  const [busy,setBusy] = useState(false);
  const [report,setReport] = useState<SessionReport|null>(null);

  const start = async () => {
    setBusy(true);
    try {
      const newSession=await api.createSession('practice');
      setSession(newSession);setDraft('');setFeedback(null);setReport(null);
      setQuestion(await api.nextQuestion(newSession.id));
    } catch(err) {showError(err);} finally {setBusy(false);}
  };
  const next = async () => {
    if(!session)return;
    setBusy(true);
    try {setQuestion(await api.nextQuestion(session.id));setDraft('');setFeedback(null);}
    catch(err) {
      // The knowledge base may be exhausted. Keep the completed answers available for reporting.
      setQuestion(null);setFeedback(null);
      if(!(err instanceof Error && err.message.includes('No unused Q&A')))showError(err);
    } finally {setBusy(false);}
  };
  const evaluate = async () => {
    if(!session || !draft.trim())return;
    setBusy(true);
    try {setFeedback(await api.evaluate(session.id,draft.trim()));}
    catch(err){showError(err);}finally{setBusy(false);}
  };
  const finish = async () => {
    if(!session)return;
    setBusy(true);
    try {setReport(await api.finishSession(session.id));setQuestion(null);setFeedback(null);}
    catch(err){showError(err);}finally{setBusy(false);}
  };
  return <>
    <div className="page-header"><div><div className="eyebrow">INTERVIEW TRAINING</div><h1>Practice Interview</h1><p className="page-description">Answer questions from your knowledge base and review your session.</p></div><span className="page-icon violet"><GraduationCap size={23}/></span></div>
    {!session && <div className="hero-panel"><span className="feature-icon violet"><GraduationCap size={27}/></span><h2>Train with your own answers.</h2><p>Practice with the approved Q&A pairs in your files. Get feedback after each answer and a session report at the end.</p><button className="btn primary" disabled={busy} onClick={()=>void start()}>Start practice session <ChevronRight size={18}/></button></div>}
    {session && !report && <div className="practice-layout">
      <div className="panel">
        <div className="panel-title"><h2>Interview question</h2><span className="tiny-pill">Practice session</span></div>
        {question ? <>
          <div className="question-box">{question.question}<div className="question-origin">From {question.document_name}</div></div>
          <label className="field-label" htmlFor="practice-answer">Your answer</label>
          <textarea id="practice-answer" rows={7} placeholder="Explain the concept in your own words..." value={draft} disabled={Boolean(feedback)} onChange={e=>setDraft(e.target.value)}/>
          <div className="action-row">
            {!feedback ? <button className="btn primary" disabled={busy||!draft.trim()} onClick={()=>void evaluate()}>Submit answer <Send size={16}/></button> : <>
              <button className="btn secondary" disabled={busy} onClick={()=>void finish()}>Finish & view report</button>
              <button className="btn primary" disabled={busy} onClick={()=>void next()}>Next question <ChevronRight size={17}/></button>
            </>}
          </div>
        </> : <>
          <EmptyState icon={Check} title="No more questions" body="Finish the session to review the answers you completed."/>
          <div className="action-row"><button className="btn primary" disabled={busy} onClick={()=>void finish()}>View session report</button></div>
        </>}
      </div>
      {feedback && <div className="panel feedback-panel">
        <div className="panel-title"><h2>Review your answer</h2><span className="tiny-pill">Basic comparison</span></div>
        <div className="feedback-score">{feedback.score}% <span>Keyword coverage only</span></div>
        <p className="small-muted">{feedback.feedback}</p>
        <h3>Reference answer</h3><p>{feedback.expected_answer}</p><SourceTag source={feedback.source}/>
        {feedback.missing_concepts.length>0 && <><h3>Terms to revisit</h3><div className="chips">{feedback.missing_concepts.map(word=><span className="chip" key={word}>{word}</span>)}</div></>}
      </div>}
    </div>}
    {session && report && <div className="panel session-report">
      <div className="panel-title"><h2>Session report</h2><span className="tiny-pill">Completed</span></div>
      <div className="feedback-score">{report.coverage_score===null?'Not scored':`${report.coverage_score}%`} <span>Average keyword coverage across {report.answered_questions} answer(s)</span></div>
      <p className="small-muted">{report.warning}</p>
      <h3>Concepts to review</h3>
      {report.areas_to_improve.length ? <div className="chips">{report.areas_to_improve.map(concept=><span className="chip" key={concept}>{concept}</span>)}</div>:<p className="small-muted">No missing terms detected in your submitted responses.</p>}
      <h3>Suggested next steps</h3>
      {report.recommendations.map((item,index)=><p key={index}>{item}</p>)}
      <h3>Question results</h3>
      <div className="review-list">{report.questions.map((item,index)=><div className="review-item" key={index}><strong>{item.question}</strong><span>{item.coverage_score}% keyword coverage · {item.source.document_name} · {item.source.location}</span></div>)}</div>
      <div className="action-row"><button className="btn primary" onClick={()=>{setSession(null);setQuestion(null);setFeedback(null);setReport(null);}}>New practice session</button></div>
    </div>}
  </>;
}
/** Live Mode receives read-only transcription and retrieval events from the isolated capture window. */
function Live({showError}: {showError:(e:unknown)=>void}) {
  const [question,setQuestion] = useState('');
  const [answer,setAnswer] = useState<AnswerResponse|null>(null);
  const [busy,setBusy] = useState(false);
  const [captureOpen,setCaptureOpen] = useState(false);
  const [events,setEvents] = useState<LiveEvent[]>([]);
  const [partial,setPartial] = useState('');
  const [frames,setFrames] = useState(0);
  const [captureBusy,setCaptureBusy] = useState(false);

  useEffect(() => {
    const bridge = window.copilotDesktop;
    if (!bridge) return;
    let mounted = true;
    const receive = (packet: LiveEvent) => {
      if (!mounted) return;
      if (packet.type === 'partial') {setPartial(packet.text); return;}
      if (packet.type === 'metrics') {setFrames(packet.frames); return;}
      if (packet.type === 'final') setPartial('');
      if (packet.type === 'status' && packet.text === 'Captura detenida.') setCaptureOpen(false);
      setEvents(prev => [...prev,packet].slice(-80));
    };
    const unsubscribe = bridge.onLiveEvent(receive);
    void bridge.getLiveState().then(state => {
      if (!mounted) return;
      setCaptureOpen(state.open);
      setEvents(state.events);
    }).catch(showError);
    return () => {mounted = false;unsubscribe();};
  }, []);

  const openCapture = async () => {
    const bridge = window.copilotDesktop;
    if (!bridge) return;
    setCaptureBusy(true);
    try {
      const opened = await bridge.openLiveCapture();
      if (!opened) throw new Error('La captura Live requiere ejecutar la aplicación con npm run dev.');
      setCaptureOpen(true);
    } catch(error) {showError(error);} finally {setCaptureBusy(false);}
  };
  const closeCapture = async () => {
    const bridge = window.copilotDesktop;
    if (!bridge) return;
    setCaptureBusy(true);
    try {await bridge.closeLiveCapture();setCaptureOpen(false);} catch(error) {showError(error);} finally {setCaptureBusy(false);}
  };
  const search = async () => {
    if (question.trim().length < 3) return;
    setBusy(true);
    try {setAnswer(await api.answer(question.trim()));}
    catch (error) {showError(error);}
    finally {setBusy(false);}
  };
  const suggestions = events.filter((event): event is LiveSuggestionEvent => event.type === 'suggestion' || event.type === 'generated_suggestion').slice(-20).reverse();
  const transcript = events.filter((event): event is Extract<LiveEvent,{type:'final'}> => event.type === 'final').slice(-20).reverse();
  const mostRecentStatus = [...events].reverse().find(event => event.type === 'status' || event.type === 'error');
  return <>
    <div className="page-header"><div><div className="eyebrow">LIVE INTERVIEW · LOCAL</div><h1>Live Interview</h1>
      <p className="page-description">Captura audio con consentimiento y prioriza documentos locales. Si Ollama está habilitado, puede sugerir respuestas de IA sin respaldo documental.</p>
    </div><span className="page-icon"><Headphones size={22}/></span></div>
    <div className="panel live-control-panel">
      <div className="panel-title"><h2>Audio del sistema</h2><span className="hint">Electron → STT local → Q&A</span></div>
      <p className="small-muted">La captura escucha toda la salida de audio de Windows. Se abrirá una ventana aislada para seleccionar idioma, autorizar e iniciar. Ninguna grabación se guarda.</p>
      <div className="live-actions">
        <button className="btn primary" disabled={captureBusy || !window.copilotDesktop} onClick={()=>void openCapture()}>
          <Headphones size={17}/>{captureOpen ? 'Mostrar controles de audio' : 'Preparar captura Live'}
        </button>
        <button className="btn secondary" disabled={!captureOpen || captureBusy} onClick={()=>void closeCapture()}>Detener y cerrar captura</button>
        <span className="live-frames">PCM: {frames} tramas</span>
      </div>
      <p className="small-muted" role="status">{mostRecentStatus?.type === 'status' || mostRecentStatus?.type === 'error' ? mostRecentStatus.text : 'La captura está detenida.'}</p>
    </div>
    <div className="live-results">
      <section className="panel live-suggestions"><div className="panel-title"><h2>Preguntas y respuestas</h2><span className="hint">Documentos o sugerencias de IA identificadas</span></div>
        {suggestions.length ? suggestions.map((item,index) => <LiveSuggestion item={item} key={`${item.type}-${item.question_id ?? item.question}-${index}`}/>) : <p className="small-muted">Las preguntas detectadas aparecerán aquí cuando se reciba audio.</p>}
      </section>
      <section className="panel live-transcript"><div className="panel-title"><h2>Transcripción</h2><span className="hint">STT local · Live</span></div>
        {partial && <p className="live-partial">{partial}</p>}
        {transcript.length ? transcript.map((item,index) => <p className="live-transcript-line" key={index}>{item.text}</p>) : <p className="small-muted">Esperando voz…</p>}
      </section>
    </div>
    <div className="panel query-panel"><div className="panel-title"><h2>Consulta por texto</h2><span className="hint">Alternativa manual</span></div>
      <label className="field-label" htmlFor="live-question">Pregunta</label>
      <textarea id="live-question" rows={3} maxLength={3000} value={question}
        onChange={event=>setQuestion(event.target.value)} placeholder="Escribe una pregunta..."/>
      <div className="action-row"><button className="btn primary" disabled={busy||question.trim().length<3} onClick={()=>void search()}>
        {busy?'Consultando...':'Consultar'} <Search size={16}/></button></div>
      {answer && <AnswerCard answer={answer}/>}
    </div>
  </>;
}
function SettingsPage() {
  const [state,setState] = useState<{available:boolean;protected:boolean;alwaysOnTop:boolean}|null>(null);
  const [note,setNote] = useState('');
  useEffect(()=>{void window.copilotDesktop?.getWindowState().then(setState);},[]);
  const toggle = async (field:'protected'|'alwaysOnTop') => {
    if(!state||!window.copilotDesktop)return;
    try {const next=field==='protected'?await window.copilotDesktop.setContentProtection(!state.protected):await window.copilotDesktop.setAlwaysOnTop(!state.alwaysOnTop);setState({...state,[field]:next});setNote('Window setting updated. Test it with your actual screen sharing software.');}catch{setNote('Could not change window setting.');}
  };
  return <><div className="page-header"><div><div className="eyebrow">APPLICATION PREFERENCES</div><h1>Settings</h1><p className="page-description">Desktop behavior and privacy controls.</p></div><span className="page-icon"><Settings size={22}/></span></div><div className="panel"><div className="panel-title"><h2>Window & privacy</h2><LockKeyhole size={18}/></div><div className="setting-row"><div><strong>Capture exclusion (Windows)</strong><p>Requests that compatible screen-capture software exclude this window. Not guaranteed for all capture methods.</p></div><button className={`toggle ${state?.protected?'enabled':''}`} aria-pressed={Boolean(state?.protected)} disabled={!state?.available} onClick={()=>void toggle('protected')}><span/></button></div><div className="setting-row"><div><strong>Always on top</strong><p>Keep this window above other applications for convenient access.</p></div><button className={`toggle ${state?.alwaysOnTop?'enabled':''}`} aria-pressed={Boolean(state?.alwaysOnTop)} disabled={!state?.available} onClick={()=>void toggle('alwaysOnTop')}><span/></button></div><p className="small-muted">{state?.available ? 'Native window controls available in Electron.' : 'Open the app in Electron (not the browser) to configure Windows window behavior.'}</p>{note && <p className="small-muted">{note}</p>}</div><div className="callout"><Shield size={21}/><div><strong>Use responsibly</strong><span>Capture exclusion does not guarantee invisibility. Follow the rules and consent requirements of each interview and conferencing platform.</span></div></div></>;
}
