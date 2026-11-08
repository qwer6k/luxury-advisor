import { useEffect, useState } from 'react'
import type { Bootstrap, Candidate, ClientMemory, ClientProfile, ClientSummary, DraftInput, Run, Scenario } from './types'
import ThemeStudio, { MaterialScene } from './ThemeStudio'
import { useVisualTheme } from './themes'
import ClientStudio, { MemoryContext } from './ClientStudio'
import { request } from './api'
import ReplyReview from './ReplyReview'
import { ClientBasicsFields, emptyBackground, STAGE_NAMES } from './ClientBasics'

const SCENARIOS: { id: Scenario; title: string; description: string; icon: string }[] = [
  { id: 'greeting', title: '生日与节日', description: '把祝福送到心上', icon: '✧' },
  { id: 'recommendation', title: '产品推荐', description: '从偏好找到契合', icon: '◇' },
  { id: 'post_purchase', title: '购后关怀', description: '让关心延续日常', icon: '♡' },
  { id: 'reactivation', title: '久违问候', description: '自然地重新联系', icon: '↗' },
  { id: 'invitation', title: '活动邀请', description: '为相聚留一份余地', icon: '▧' },
  { id: 'price_objection', title: '价格沟通', description: '理解顾虑，真诚回应', icon: '≋' },
]
const scenarioName = (value: Scenario) => SCENARIOS.find(s => s.id === value)?.title ?? value
const DETAIL_NAMES: Record<string, string> = {
  occasion: '祝福场合', date_confirmation: '日期确认', budget_cny: '预算（元）',
  purchase_elapsed: '购买时间', last_visit_elapsed: '距上次到店', last_contact_elapsed: '距上次联系',
  advisor_intent: '沟通目的', event_name: '活动名称', event_date: '活动日期',
  event_time: '活动时间', location: '活动地点', format: '活动内容', rsvp: '回复方式', background: '补充背景',
}
const emptyInput = (): DraftInput => ({ scenario: 'greeting', client: { preferred_name: '', relationship: '', preferences: [], notes: [], lifecycle_stage: 'new', background: emptyBackground() }, conversation_history: [], product_ids: [], scenario_details: {} })
const splitList = (text: string) => text.split(/[,，、\n]/).map(v => v.trim()).filter(Boolean)
const dateTime = (value: string) => new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short', timeZone: 'Asia/Shanghai' }).format(new Date(value))

function CandidateCards({ candidates, allowCopy = true }: { candidates: Candidate[]; allowCopy?: boolean }) {
  const [copied, setCopied] = useState<number | null>(null)
  const [error, setError] = useState('')
  async function copy(index: number) {
    try {
      await navigator.clipboard.writeText(candidates[index].message)
      setCopied(index)
      setTimeout(() => setCopied(null), 1800)
    } catch { setError('复制未成功，可直接选中文字复制。') }
  }
  return <div className="candidate-list">
    {candidates.map((candidate, index) => <article className="candidate-card" key={index}>
      <div className="candidate-top"><span className="candidate-number">0{index + 1}</span><span>{candidate.strategy}</span></div>
      <p>{candidate.message}</p>
      <div className="candidate-bottom"><span>{candidate.message.length} 字</span><button className="copy-button" disabled={!allowCopy} onClick={() => void copy(index)}>{copied === index ? '✓ 已复制' : '⧉ 复制消息'}</button></div>
    </article>)}
    <span className="sr-only" role="status">{copied !== null ? `已复制第 ${copied + 1} 条消息` : ''}</span>
    {error && <p className="error" role="alert">{error}</p>}
  </div>
}

export default function App() {
  const { theme, selectTheme } = useVisualTheme()
  const [studioOpen, setStudioOpen] = useState(false)
  const [data, setData] = useState<Bootstrap | null>(null)
  const [page, setPage] = useState<'workbench' | 'clients' | 'evidence' | 'method'>('workbench')
  const [clients, setClients] = useState<ClientSummary[]>([])
  const [activeProfile, setActiveProfile] = useState<ClientProfile | null>(null)
  const [memoryPreview, setMemoryPreview] = useState<ClientMemory | null>(null)
  const [profileError, setProfileError] = useState('')
  const [profileLoading, setProfileLoading] = useState(false)
  const [profileRefresh, setProfileRefresh] = useState(0)
  const [tab, setTab] = useState<'cases' | 'runs'>('cases')
  const [input, setInput] = useState<DraftInput>(emptyInput)
  const [preferenceText, setPreferenceText] = useState('')
  const [notesText, setNotesText] = useState('')
  const [historyText, setHistoryText] = useState('')
  const [detailsText, setDetailsText] = useState('')
  const [source, setSource] = useState('')
  const [result, setResult] = useState<Run | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [selectedRun, setSelectedRun] = useState<Run | null>(null)
  const [filter, setFilter] = useState<Scenario | 'all'>('all')
  const [busy, setBusy] = useState(false)
  const [loadingRun, setLoadingRun] = useState(false)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [recordsError, setRecordsError] = useState('')

  function populateInput(value: DraftInput, label = '') {
    if (busy) return
    setInput(structuredClone(value))
    setPreferenceText(value.client.preferences.join('，'))
    setNotesText(value.client.notes.join('，'))
    setHistoryText(value.conversation_history.map(m => `${m.speaker === 'client' ? '客户' : '顾问'}：${m.text}`).join('\n'))
    setDetailsText(Object.entries(value.scenario_details).map(([key, val]) => `${DETAIL_NAMES[key] ?? key}：${val}`).join('\n'))
    setSource(label); setResult(null); setError(''); setPage('workbench')
  }
  function loadInput(value: DraftInput, label = '') {
    if (busy || profileLoading) return
    if (value.client_id && data?.capabilities?.client_memory) { void selectClient(value.client_id, value); return }
    setActiveProfile(null); setProfileError(''); setMemoryPreview(null)
    populateInput({ ...value, client_id: undefined, client_revision: undefined }, label)
  }
  async function refreshClients() {
    setClients(await request<ClientSummary[]>('/api/clients'))
  }
  function useProfile(profile: ClientProfile, base?: DraftInput) {
    if (busy) return
    const value = base ?? { ...emptyInput(), scenario: input.scenario }
    setActiveProfile(profile); setProfileError(''); setMemoryPreview(null)
    populateInput({ ...value, client_id: profile.id, client_revision: profile.revision,
      client: { ...value.client, preferred_name: profile.preferred_name, relationship: profile.relationship, preferences: [], lifecycle_stage: profile.lifecycle_stage ?? 'unknown', background: profile.background ?? emptyBackground() },
    })
  }
  async function selectClient(id: string, base?: DraftInput) {
    if (busy || profileLoading) return
    if (!id) { setActiveProfile(null); setProfileError(''); setMemoryPreview(null); populateInput({ ...emptyInput(), scenario: input.scenario }); return }
    setProfileLoading(true); setProfileError('')
    try { useProfile(await request<ClientProfile>(`/api/clients/${id}`), base) }
    catch (reason) { setProfileError(reason instanceof Error ? reason.message : '档案加载失败。') }
    finally { setProfileLoading(false) }
  }
  async function refreshSelectedProfile() {
    if (!input.client_id || busy || profileLoading) return
    setProfileLoading(true); setProfileError('')
    try {
      const profile = await request<ClientProfile>(`/api/clients/${input.client_id}`)
      setActiveProfile(profile)
      setInput(value => ({ ...value, client_revision: profile.revision, client: { ...value.client, preferred_name: profile.preferred_name, relationship: profile.relationship, lifecycle_stage: profile.lifecycle_stage ?? 'unknown', background: profile.background ?? emptyBackground() } }))
      setResult(null); setProfileRefresh(value => value + 1)
    } catch (reason) { setProfileError(reason instanceof Error ? reason.message : '档案刷新失败。') }
    finally { setProfileLoading(false) }
  }
  async function refreshRuns() {
    try { setRuns(await request<Run[]>('/api/runs')); setRecordsError('') }
    catch { setRecordsError('运行记录加载失败，请点击刷新重试。') }
  }
  useEffect(() => {
    void request<Bootstrap>('/api/bootstrap').then(value => {
      setData(value)
      if (value.capabilities?.client_memory) void refreshClients().catch(() => setProfileError('客户列表加载失败，请稍后刷新。'))
      const initial = value.cases.find(c => c.case_id === 'D003') ?? value.cases[0]
      if (initial) loadInput(initial.input, initial.case_id)
    }).catch(() => setLoadError('工作台加载失败，请确认后端正在运行，然后刷新页面。'))
    void refreshRuns()
  }, [])
  useEffect(() => {
    if (!input.client_id) { setMemoryPreview(null); return }
    const controller = new AbortController()
    setMemoryPreview(null); setProfileError('')
    void request<ClientMemory>(`/api/clients/${input.client_id}/memory?scenario=${input.scenario}&revision=${input.client_revision}`, { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setMemoryPreview(value) }).catch(reason => { if (!controller.signal.aborted) setProfileError(reason instanceof Error ? reason.message : '客户资料读取失败。') })
    return () => controller.abort()
  }, [input.client_id, input.client_revision, input.scenario, profileRefresh])
  async function generate(event: React.FormEvent) {
    event.preventDefault(); setError('')
    if (!input.client.preferred_name.trim()) { setError('请填写客户称呼。'); return }
    if (input.client_id && (!memoryPreview || profileError || profileLoading)) { setError('请先核实并刷新客户档案，再准备消息。'); return }
    const history: DraftInput['conversation_history'] = []
    for (const line of historyText.split('\n').map(v => v.trim()).filter(Boolean)) {
      const match = line.match(/^(客户|顾问)[：:]\s*(.+)$/)
      if (!match) { setError('请让每行对话以“客户：”或“顾问：”开头，并填写消息内容。'); return }
      history.push({ speaker: match[1] === '客户' ? 'client' : 'advisor', text: match[2] })
    }
    const payload: DraftInput = {
      ...input, client: { ...input.client, preferences: splitList(preferenceText), notes: splitList(notesText) },
      conversation_history: history, scenario_details: detailsText.trim() ? { background: detailsText.trim() } : {},
    }
    setBusy(true); setResult(null)
    try {
      setResult(await request<Run>('/api/draft', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }))
    } catch (reason) { setError(reason instanceof Error ? reason.message : '生成失败，请重试。') }
    finally { setBusy(false); void refreshRuns() }
  }
  async function openRun(id: string) {
    setLoadingRun(true); setError('')
    try { setSelectedRun(await request<Run>(`/api/runs/${id}`)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '记录读取失败。') }
    finally { setLoadingRun(false) }
  }
  const generated = runs.filter(run => run.status === 'generated')
  const covered = new Set(generated.map(run => run.scenario)).size
  const displayedCases = data?.cases.filter(c => filter === 'all' || c.input.scenario === filter) ?? []
  const displayedRuns = runs.filter(run => filter === 'all' || run.scenario === filter)

  if (!data) return <div className="loading-screen"><span className="brand-word">XUYU</span><p role="status">{loadError || '正在准备顾问工作台…'}</p>{loadError && <button className="primary" onClick={() => location.reload()}>重新加载</button>}</div>

  return <div className="app-shell" data-theme={theme.id}>
    <aside className="sidebar">
      <a className="brand" href="#" aria-label="序隅工作台首页" onClick={e => { e.preventDefault(); setPage('workbench') }}><span className="brand-word">XUYU<span className="brand-dot">.</span></span><span className="brand-cn">序 隅</span></a>
      <span className="sidebar-caption">CLIENT ADVISOR STUDIO</span>
      <nav aria-label="主导航">
        <button className={page === 'workbench' ? 'nav-item active' : 'nav-item'} onClick={() => { setPage('workbench'); setError('') }}><span>▤</span>话术工作台<span className="nav-arrow">↗</span></button>
        {data.capabilities?.client_memory && <button className={page === 'clients' ? 'nav-item active' : 'nav-item'} disabled={busy} onClick={() => { setPage('clients'); setError(''); void refreshClients().catch(() => setProfileError('客户列表加载失败。')) }}><span>◎</span>客户档案</button>}
        <button className={page === 'evidence' ? 'nav-item active' : 'nav-item'} onClick={() => { setPage('evidence'); setError(''); void refreshRuns() }}><span>▦</span>验证与记录</button>
        <button className={page === 'method' ? 'nav-item active' : 'nav-item'} onClick={() => { setPage('method'); setError('') }}><span>◇</span>品牌与方法</button>
      </nav>
      <div className="sidebar-note"><span className="small-star">✧</span><p>好的对话，<br />从理解对方开始。</p><span>{theme.english}</span></div>
      <button className="sidebar-theme" onClick={() => setStudioOpen(true)}><span className="sidebar-theme-mark" aria-hidden="true">◈</span><span><small>当下的气质</small><strong>{theme.name}</strong></span><span aria-hidden="true">↗</span></button>
      <div className="sidebar-bottom"><span className="status-dot" />虚构品牌 · 演示资料<span>v{data.version}</span></div>
    </aside>

    <main className="main">
      <header className="topbar"><span className="topbar-label">序隅 · 客户关系工作室</span><div className="topbar-actions"><button className="style-trigger" aria-haspopup="dialog" onClick={() => setStudioOpen(true)}><span className="theme-trigger-swatch" aria-hidden="true" />风格陈列室<span className="current-theme"> / {theme.name}</span><span aria-hidden="true">↗</span></button><span className="service-status"><i className={data.api_configured ? 'status-dot' : 'status-dot muted'} />{data.api_configured ? '创作服务已配置' : '创作服务待配置'}</span><span className="advisor-avatar" aria-hidden="true">序</span></div></header>
      <div className="page-content">
        {page === 'workbench' ? <section className="atmosphere-hero" aria-labelledby="workbench-title"><div className="hero-copy"><div className="hero-edition"><span className="eyebrow">{theme.english}</span><span className="edition-number">VOL. {theme.number}</span></div><h1 id="workbench-title">{theme.headline[0]}<br />{theme.headline[1]}</h1><p>从客户的真实偏好出发，<br className="mobile-break" />为每次对话找到合适的表达。</p><div className="hero-caption"><span className="caption-line" /><span>{theme.note}</span></div></div><div className="hero-art"><MaterialScene variant={theme.id} /><div className="hero-material"><span>{theme.name}</span><small>{theme.material}</small></div></div></section> : <div className="page-heading"><div><span className="eyebrow">{page === 'clients' ? 'KNOW THE PERSON' : page === 'evidence' ? 'EVERY WORD, TRACEABLE' : 'OUR POINT OF VIEW'}</span><h1>{page === 'clients' ? '把了解，积累成有温度的服务。' : page === 'evidence' ? '让每一次生成，有据可循。' : '有分寸的表达，有依据的关心。'}</h1><p>{page === 'clients' ? '从新客户的第一次相识，到长期往来的细致理解，记录有依据的资料，尊重每一次新的选择。' : page === 'evidence' ? '查看开发案例与实际运行结果，保留成功、失败和版本信息。' : '序隅是一家虚构的现代奢侈皮具品牌。以下设定是工具的共同依据。'}</p></div><span className="page-number">{page === 'clients' ? '02' : page === 'evidence' ? '03' : '04'} / STUDIO</span></div>}

        {page === 'clients' && <ClientStudio clients={clients} onChange={refreshClients} onUse={profile => { useProfile(profile); void refreshClients() }} />}

        {page === 'workbench' && <>
          {data.capabilities?.client_memory && <section className="client-binding"><div className="client-binding-row"><label htmlFor="active-client">为哪位客户准备对话<select id="active-client" value={input.client_id ?? ''} disabled={busy || profileLoading} onChange={event => void selectClient(event.target.value)}><option value="">新客 / 临时沟通 · 不建档</option>{clients.map(item => <option value={item.id} key={item.id}>{item.preferred_name} · {item.contact_status === 'paused' ? '暂停主动沟通' : STAGE_NAMES[item.lifecycle_stage ?? 'unknown'] + ' · 修订 ' + item.revision}</option>)}</select></label><div><button className="text-button" disabled={busy || profileLoading} onClick={() => void selectClient('')}>新客沟通 ↗</button>{input.client_id && <button className="text-button" disabled={busy || profileLoading} onClick={() => void refreshSelectedProfile()}>刷新已选档案</button>}<button className="text-button" disabled={busy || profileLoading} onClick={() => setPage('clients')}>管理客户档案 ↗</button></div></div>{profileLoading && <p className="field-hint" role="status">正在读取客户档案…</p>}{profileError && <p className="error" role="alert">{profileError}</p>}{memoryPreview && <MemoryContext memory={memoryPreview} preview />}{!input.client_id && <p className="field-hint">新客户无需历史记录，可以直接填写称呼和需求；也可先建立档案。选择档案后会自动参考适用资料，切换客户会清空本次输入。</p>}</section>}
          <section className="scenario-section" aria-labelledby="scenario-heading"><div className="section-label"><h2 id="scenario-heading"><span className="section-index">01</span>选择沟通场景</h2><span>六种时刻，同样用心</span></div><div className="scenario-grid">{SCENARIOS.map(scenario => <button type="button" disabled={busy} key={scenario.id} aria-pressed={input.scenario === scenario.id} className={input.scenario === scenario.id ? 'scenario active' : 'scenario'} onClick={() => { setInput({ ...input, scenario: scenario.id, scenario_details: {} }); setDetailsText(''); setSource(''); setResult(null) }}><span className="scenario-icon">{scenario.icon}</span><strong>{scenario.title}</strong><small>{scenario.description}</small></button>)}</div></section>
          <div className="workspace">
            <form className="panel input-panel" onChange={() => { if (result) setResult(null) }} onSubmit={event => void generate(event)}>
              <div className="panel-heading"><div><h2>了解这一次对话</h2><p>提供已确认的信息，让表达更贴近客户。</p></div><span className="step-label">INPUT</span></div>
              <fieldset disabled={busy}><div className="example-toolbar"><label htmlFor="example">从开发案例开始</label><select id="example" value={source} onChange={event => { const item = data.cases.find(c => c.case_id === event.target.value); if (item) loadInput(item.input, item.case_id) }}><option value="">自定义输入</option>{data.cases.map(item => <option key={item.case_id} value={item.case_id}>{item.case_id} · {scenarioName(item.input.scenario)} · {item.input.client.preferred_name}</option>)}</select></div>
              <div className="form-body">{input.client_id && <p className="field-hint">称呼与关系来自客户档案，偏好及既往沟通会自动参考；本次输入不自动写回档案。</p>}<div className="field-row"><label>客户称呼 <span className="required">*</span><input required readOnly={!!input.client_id} maxLength={40} value={input.client.preferred_name} placeholder="如：周女士" onChange={e => setInput({ ...input, client: { ...input.client, preferred_name: e.target.value } })} /></label><label>客户关系<input readOnly={!!input.client_id} maxLength={200} value={input.client.relationship} placeholder="如：首次产品咨询" onChange={e => setInput({ ...input, client: { ...input.client, relationship: e.target.value } })} /></label></div>
              {!input.client_id && data.capabilities?.client_background && <details className="client-background-editor"><summary>客户基础资料 <span>新客也可以从这里开始 · 选填</span></summary><ClientBasicsFields stage={input.client.lifecycle_stage ?? 'unknown'} background={input.client.background ?? emptyBackground()} onStage={value => setInput({ ...input, client: { ...input.client, lifecycle_stage: value } })} onBackground={value => setInput({ ...input, client: { ...input.client, background: value } })} /></details>}
              {!input.client_id && <label>偏好与习惯<input value={preferenceText} maxLength={600} placeholder="如：低调、灰色、日常通勤" onChange={e => setPreferenceText(e.target.value)} /></label>}
              <label>历史对话 <span className="optional">选填</span><textarea rows={3} value={historyText} placeholder={'客户：想找一个通勤用的灰色肩包。\n顾问：您平时更在意容量还是轻便？'} onChange={e => setHistoryText(e.target.value)} /><span className="field-hint">每行一条，以“客户：”或“顾问：”开头。</span></label>
              <label>本次沟通背景<textarea rows={3} maxLength={2000} value={detailsText} placeholder="如活动安排、祝福场合、购买时间等已确认的信息" onChange={e => setDetailsText(e.target.value)} /></label>
              <div className="product-heading"><span>相关产品</span><span className="optional">按需选择</span></div><div className="product-grid">{data.products.map(product => <label key={product.id} className={input.product_ids.includes(product.id) ? 'product selected' : 'product'}><input type="checkbox" checked={input.product_ids.includes(product.id)} onChange={e => setInput({ ...input, product_ids: e.target.checked ? [...input.product_ids, product.id] : input.product_ids.filter(id => id !== product.id) })} /><span><strong>{product.name}</strong><small>¥{product.price_cny.toLocaleString('zh-CN')} · {product.material}</small></span></label>)}</div>
              <label>其他需要注意的信息 <span className="optional">选填</span><input value={notesText} maxLength={600} placeholder="如：不喜欢被催促，称呼请用小岚" onChange={e => setNotesText(e.target.value)} /></label></div>
              </fieldset>
              <div className="generate-footer">{error && <p className="error" role="alert">{error}</p>}<button className="primary generate-button" type="submit" disabled={busy || !data.api_configured || profileLoading || (!!input.client_id && (!memoryPreview || !!profileError || activeProfile?.contact_status === 'paused'))}>{busy ? <><span className="spinner" />正在斟酌表达…</> : <>生成 3 条候选消息 <span>↗</span></>}</button><p>生成后由顾问选择与确认，再发送给客户。</p></div>
            </form>
            <section className="panel output-panel" aria-labelledby="output-heading"><div className="panel-heading"><div><h2 id="output-heading">为这次对话，准备三种表达</h2><p>选择最符合你与客户关系的一条。</p></div><span className="step-label">DRAFTS</span></div><div className="output-body" aria-live="polite" aria-busy={busy}>{result?.candidates?.length ? <><div className="result-meta"><span className="success-chip">✓ 结构校验通过</span><span>{(result.elapsed_ms / 1000).toFixed(1)} 秒 · {result.attempt_count} 次调用</span></div><CandidateCards candidates={result.candidates} allowCopy={!result.quality_review?.copy_blocked} /><ReplyReview run={result} />{result.client_memory && <MemoryContext memory={result.client_memory} />}<p className="review-note">尚未人工复核，请确认事实、语气与客户偏好。</p><button className="text-button" onClick={() => { setPage('evidence'); setTab('runs'); void openRun(result.run_id) }}>查看本次运行记录 ↗</button></> : <div className="empty-state"><div className={busy ? 'empty-orbit animating' : 'empty-orbit'}><span>✧</span></div><h3>{busy ? '为这一次对话，细细斟酌。' : '三种表达，同一份心意。'}</h3><p>{busy ? '正在结合品牌规范、已知事实和历史对话起草消息。' : '补充左侧信息并生成，候选消息将在这里呈现。'}</p><div className="empty-principles"><span>有依据</span><span>有温度</span><span>有分寸</span></div></div>}</div><div className="output-footnote"><span>◇</span><p>只使用已知事实，不擅自承诺折扣、库存或售后服务。</p></div></section>
          </div>
        </>}

        {page === 'evidence' && <>
          {data.capabilities?.review_samples && <section className="sample-review-entry"><div><h2>回复审稿样本集</h2><p>48 组虚构对照 · 96 份候选 · 等待你的判断与修改。独立于真实生成记录。</p></div><a className="primary" href="/review/" target="_blank" rel="noreferrer">开始审稿 ↗</a></section>}
          <div className="stat-grid"><div><span>开发案例</span><strong>{data.cases.length}<small>个</small></strong></div><div><span>真实生成记录</span><strong>{runs.length}<small>次</small></strong></div><div><span>已生成场景</span><strong>{covered}<small>/ 6</small></strong></div><div><span>已保存候选消息</span><strong>{runs.reduce((sum, run) => sum + run.candidate_count, 0)}<small>条</small></strong></div></div>
          <section className="panel evidence-panel"><div className="evidence-toolbar"><div className="tabs"><button className={tab === 'cases' ? 'active' : ''} onClick={() => setTab('cases')}>开发案例</button><button className={tab === 'runs' ? 'active' : ''} onClick={() => setTab('runs')}>运行记录</button></div><div className="evidence-actions"><select aria-label="筛选场景" value={filter} onChange={e => setFilter(e.target.value as Scenario | 'all')}><option value="all">全部场景</option>{SCENARIOS.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</select><button className="text-button" onClick={() => void refreshRuns()}>刷新</button></div></div>
          {recordsError && <p className="error" role="alert">{recordsError}</p>}{error && <p className="error" role="alert">{error}</p>}
          {tab === 'cases' ? <><p className="table-note">以下为开发与调试输入。正式 50 例及人工抽检请见正式审稿页。</p><div className="table-scroll"><table><thead><tr><th>案例</th><th>场景 / 客户</th><th>验证重点</th><th>操作</th></tr></thead><tbody>{displayedCases.map(item => <tr key={item.case_id}><td className="mono">{item.case_id}</td><td>{scenarioName(item.input.scenario)}<small>{item.input.client.preferred_name}</small></td><td>{item.purpose}</td><td><button className="text-button nowrap" onClick={() => loadInput(item.input, item.case_id)}>加载案例 ↗</button></td></tr>)}</tbody></table></div></> : <><p className="table-note">“结构校验通过”仅表示输出格式合规；自然度、事实依据和品牌表达尚需评估。</p><div className="table-scroll"><table><thead><tr><th>时间 / 来源</th><th>场景 / 客户</th><th>生成状态</th><th>耗时</th><th>操作</th></tr></thead><tbody>{displayedRuns.map(run => <tr key={run.run_id}><td>{dateTime(run.created_at)}<small>{run.case_id ?? '工作台输入'}</small></td><td>{scenarioName(run.scenario)}<small>{run.client_name}</small></td><td><span className={run.status === 'generated' ? 'success-chip' : 'failure-chip'}>{run.status === 'generated' ? '结构校验通过' : '生成失败'}</span>{run.quality_status === 'needs_review' && <small>有待核对项</small>}</td><td>{(run.elapsed_ms / 1000).toFixed(1)} 秒</td><td><button className="text-button nowrap" disabled={loadingRun} onClick={() => void openRun(run.run_id)}>查看记录 ↗</button></td></tr>)}</tbody></table></div>{!displayedRuns.length && <p className="table-note">当前筛选下还没有运行记录。</p>}</>}
          </section>
          {tab === 'runs' && selectedRun && <section className="panel run-detail"><div className="panel-heading"><div><h2>运行详情 · {selectedRun.client_name}</h2><p>{scenarioName(selectedRun.scenario)} · {dateTime(selectedRun.created_at)}</p></div><button className="text-button" onClick={() => setSelectedRun(null)}>收起 ×</button></div><div className="run-meta"><span>模型：{selectedRun.model ?? '未返回'}</span><span>工具：v{selectedRun.tool_version}</span><span>提示词：{selectedRun.prompt_version}</span><span>调用：{selectedRun.attempt_count} 次</span><span>输入 / 输出：{selectedRun.usage?.input_tokens ?? 0} / {selectedRun.usage?.output_tokens ?? 0} tokens</span></div><div className="run-detail-body">{selectedRun.candidates?.length ? <CandidateCards candidates={selectedRun.candidates} allowCopy={selectedRun.profile_check !== 'changed_during_generation' && !selectedRun.quality_review?.copy_blocked} /> : <p>本次未获得通过结构校验的候选，失败记录已保留。</p>}{selectedRun.profile_check === 'changed_during_generation' && <p className="error">客户档案在生成期间有更新；请刷新档案后重新准备消息。</p>}{selectedRun.comparison_mode === 'frozen_snapshot_replay' && <p className="review-note">固定历史输入回放，用于比较写法，不代表当前客户沟通。</p>}<ReplyReview run={selectedRun} />{selectedRun.client_memory && <MemoryContext memory={selectedRun.client_memory} />}<p className="review-note">本页展示原始运行记录；正式 AI 初评与人工反馈在独立审稿页保存。</p>{selectedRun.input && <button className="text-button" onClick={() => loadInput(selectedRun.input!, '')}>将原始输入载入工作台 ↗</button>}</div></section>}
        </>}

        {page === 'method' && <div className="method-grid"><section className="panel method-intro"><span className="eyebrow">THE HOUSE OF XUYU</span><h2>日常有序，<br />相处有隅。</h2><p>{data.brand.category}。以日常使用与个人审美为出发点，陪伴每一段有分寸的客户关系。</p><div className="voice-tags">{data.brand.voice.map(voice => <span key={voice}>{voice}</span>)}</div><small>品牌、产品、价格与客户资料均为虚构。</small></section><section className="panel method-rules"><h2>顾问表达原则</h2><ol>{data.brand.writing_guidelines.map(rule => <li key={rule}>{rule}</li>)}</ol></section><section className="panel method-rules"><h2>业务承诺边界</h2><ul>{data.brand.business_rules.map(rule => <li key={rule}>{rule}</li>)}</ul></section><section className="panel method-rules"><h2>生成与验证流程</h2><div className="flow-steps">{['确认本次诉求与沟通边界', '取舍个人线索与产品事实', '按场景准备三种表达角度', '检查明显问题，必要时改写一次', '顾问复核后选择发送'].map((step, index) => <div key={step}><span>0{index + 1}</span>{step}</div>)}</div><p className="review-note">当前检查覆盖格式与部分明显表达问题，不代表内容质量验收。正式测试与逐条初评独立保存，请到正式审稿页查看；人工结果与 AI 初评分开记录。</p></section></div>}
        <footer className="page-footer"><span>XUYU · MADE FOR MEANINGFUL CONNECTIONS</span><span>虚构品牌与资料 · {data.brand.version}</span></footer>
      </div>
    </main>
    <ThemeStudio open={studioOpen} theme={theme} onSelect={selectTheme} onClose={() => setStudioOpen(false)} />
  </div>
}
