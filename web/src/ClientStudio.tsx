import { useEffect, useRef, useState } from 'react'
import { jsonBody, request } from './api'
import type { ClientFact, ClientMemory, ClientProfile, ClientSummary, FactKind, FactScope, LifecycleStage } from './types'
import { ClientBasicsFields, ClientBasicsSummary, emptyBackground, STAGE_NAMES } from './ClientBasics'

export const SCENE_NAMES: Record<FactScope, string> = { all: '所有场景', greeting: '生日与节日', recommendation: '产品推荐', post_purchase: '购后关怀', reactivation: '久违问候', invitation: '活动邀请', price_objection: '价格沟通' }
const KIND_NAMES: Record<FactKind, string> = { preference: '审美与使用偏好', style: '表达风格', constraint: '沟通边界', experience: '已确认经历', intent: '阶段性需求' }
const date = (value: string) => new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'medium' }).format(new Date(value))
const factState = (fact: ClientFact) => fact.status !== 'confirmed' ? ({ pending: '待核实', superseded: '已被更新', retired: '已停用' }[fact.status]) : fact.valid_until && new Date(fact.valid_until).getTime() <= Date.now() ? '已过期' : new Date(fact.observed_at).getTime() > Date.now() ? '待生效' : '已确认'
const emptyFact = () => ({ kind: 'preference' as FactKind, topic: '', value: '', scope: 'all' as FactScope, source: '', status: 'confirmed', observed: '', expires: '', replaces_fact_id: '' })

export function MemoryContext({ memory, preview = false }: { memory: ClientMemory; preview?: boolean }) {
  return <details className="memory-context"><summary><span aria-hidden="true">◎</span><span>{preview ? '将参考' : '本次参考'}{memory.preferred_name}的档案 <small>修订 {memory.revision} · {memory.facts.length} 条偏好资料 / {memory.interactions.length} 条沟通</small></span></summary><div className="memory-context-body"><ClientBasicsSummary stage={memory.lifecycle_stage} background={memory.background} /><p>仅参考已确认、未过期且适用于当前场景的记录。</p>{!memory.facts.length && !memory.interactions.length && <p>尚无适用偏好与沟通记录；会从已知信息出发，不虚构熟悉感。</p>}{memory.facts.map(fact => <div className="memory-evidence" key={fact.id}><strong>{fact.topic}<small>{SCENE_NAMES[fact.scope]}</small></strong><p>{fact.value}</p><span>依据：{fact.source} · {date(fact.observed_at)}</span></div>)}{memory.interactions.map(item => <div className="memory-evidence" key={item.id}><strong>{item.speaker === 'client' ? '客户' : '顾问'} · {date(item.occurred_at)}</strong><p>{item.text}</p><span>{item.source}</span></div>)}</div></details>
}

export default function ClientStudio({ clients, onChange, onUse }: { clients: ClientSummary[]; onChange: () => Promise<void>; onUse: (profile: ClientProfile) => void }) {
  const [profile, setProfile] = useState<ClientProfile | null>(null)
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newRelationship, setNewRelationship] = useState('')
  const [newStage, setNewStage] = useState<LifecycleStage>('new')
  const [newBackground, setNewBackground] = useState(emptyBackground)
  const [name, setName] = useState('')
  const [relationship, setRelationship] = useState('')
  const [stage, setStage] = useState<LifecycleStage>('unknown')
  const [background, setBackground] = useState(emptyBackground)
  const [contactStatus, setContactStatus] = useState<'allowed' | 'paused'>('allowed')
  const [fact, setFact] = useState(emptyFact)
  const [showHistory, setShowHistory] = useState(false)
  const [interaction, setInteraction] = useState({ speaker: 'client', text: '', source: '虚构微信沟通', scenario: '', occurred: '' })
  const factValue = useRef<HTMLTextAreaElement>(null)
  const requestId = useRef(0)
  useEffect(() => () => { requestId.current += 1 }, [])

  function display(value: ClientProfile) {
    setProfile(value); setName(value.preferred_name); setRelationship(value.relationship); setContactStatus(value.contact_status); setStage(value.lifecycle_stage ?? 'unknown'); setBackground(value.background ?? emptyBackground())
  }
  async function open(id: string) {
    const current = ++requestId.current
    setBusy(true); setError(''); setNotice(''); setCreateOpen(false)
    try { const value = await request<ClientProfile>(`/api/clients/${id}`); if (current === requestId.current) { display(value); setFact(emptyFact()); setInteraction({ speaker: 'client', text: '', source: '虚构微信沟通', scenario: '', occurred: '' }) } }
    catch (reason) { if (current === requestId.current) setError(reason instanceof Error ? reason.message : '档案加载失败。') }
    finally { if (current === requestId.current) setBusy(false) }
  }
  async function mutate(action: () => Promise<ClientProfile>, message: string) {
    setBusy(true); setError(''); setNotice('')
    try { display(await action()); await onChange(); setNotice(message); return true }
    catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败，请重试。'); return false }
    finally { setBusy(false) }
  }
  async function create(event: React.FormEvent) {
    event.preventDefault()
    const saved = await mutate(() => request<ClientProfile>('/api/clients', jsonBody('POST', { preferred_name: newName.trim(), relationship: newRelationship.trim(), lifecycle_stage: newStage, background: newBackground, fictional: true })), '已建立客户档案，可以逐步补充了解。')
    if (saved) { setCreateOpen(false); setNewName(''); setNewRelationship(''); setNewStage('new'); setNewBackground(emptyBackground()); setFact(emptyFact()); setInteraction({ speaker: 'client', text: '', source: '虚构微信沟通', scenario: '', occurred: '' }) }
  }
  async function seed() {
    setBusy(true); setError('')
    try { await request('/api/clients/seed-demo', { method: 'POST' }); await onChange(); setNotice('已载入三位虚构客户；重复载入不会覆盖已有修改。') }
    catch (reason) { setError(reason instanceof Error ? reason.message : '载入失败。') }
    finally { setBusy(false) }
  }
  async function saveFact(event: React.FormEvent) {
    event.preventDefault(); if (!profile) return
    const body = { expected_revision: profile.revision, kind: fact.kind, topic: fact.topic, value: fact.value, scope: fact.scope, source: fact.source, status: fact.status,
      ...(fact.observed ? { observed_at: `${fact.observed}T00:00:00+08:00` } : {}),
      ...(fact.expires ? { valid_until: `${fact.expires}T23:59:59+08:00` } : {}),
      ...(fact.replaces_fact_id ? { replaces_fact_id: fact.replaces_fact_id } : {}),
    }
    if (await mutate(() => request(`/api/clients/${profile.id}/facts`, jsonBody('POST', body)), fact.status === 'pending' ? '已保留待核实资料，尚不会用于生成。' : '已保存资料；同主题、同场景的旧记录会保留在历史中。')) setFact(emptyFact())
  }
  function correct(item: ClientFact) {
    setFact({ kind: item.kind, topic: item.topic, value: item.value, scope: item.scope, source: '', status: 'confirmed', observed: '', expires: '', replaces_fact_id: item.id })
    factValue.current?.focus()
  }
  async function saveInteraction(event: React.FormEvent) {
    event.preventDefault(); if (!profile) return
    if (await mutate(() => request(`/api/clients/${profile.id}/interactions`, jsonBody('POST', { expected_revision: profile.revision, speaker: interaction.speaker, text: interaction.text, source: interaction.source, scenario: interaction.scenario || null, ...(interaction.occurred ? { occurred_at: `${interaction.occurred}T00:00:00+08:00` } : {}) })), '已记录真实发生的虚构沟通；不会自动把这段话转成已确认偏好。')) setInteraction({ ...interaction, text: '' })
  }
  const visible = clients.filter(item => `${item.preferred_name} ${item.relationship}`.includes(query))
  const facts = profile?.facts.filter(item => showHistory || ['已确认', '待核实', '待生效'].includes(factState(item))) ?? []

  return <div className="client-studio">
    <aside className="panel client-directory"><div className="client-directory-heading"><h2>一人一份了解</h2><button className="text-button" onClick={() => setCreateOpen(value => !value)} disabled={busy}>{createOpen ? '收起' : '＋ 新建'}</button></div><label className="client-search"><span className="sr-only">搜索客户</span><input value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索称呼或关系" /></label>
      <div className="client-directory-list">{visible.map(item => <button key={item.id} disabled={busy} className={`client-directory-item${profile?.id === item.id ? ' active' : ''}`} onClick={() => void open(item.id)}><span className="client-initial" aria-hidden="true">{item.preferred_name.slice(0, 1)}</span><span><strong>{item.preferred_name}</strong><small>{item.relationship || '尚未填写关系说明'}</small><span>{STAGE_NAMES[item.lifecycle_stage ?? 'unknown']} · {item.fact_count ?? 0} 条偏好资料 · {item.contact_status === 'paused' ? '暂停主动沟通' : '修订 ' + item.revision}</span></span><i aria-hidden="true">↗</i></button>)}</div>
      {!clients.length && <div className="client-directory-empty"><span aria-hidden="true">◎</span><p>每一段关系，都从一次认真了解开始。</p></div>}
      <div className="client-demo"><p>演示只使用虚构资料。可载入三位风格不同的客户，体验资料积累与联系边界。</p><button className="text-button" disabled={busy} onClick={() => void seed()}>载入虚构客户示例 ↗</button></div>
    </aside>
    <div className="client-profile-area">{error && <div className="error" role="alert">{error}{profile && <button className="text-button" disabled={busy} onClick={() => void open(profile.id)}>刷新当前档案</button>}</div>}<p className="client-notice" role="status">{notice}</p>
      {createOpen ? <section className="panel new-client-panel"><div className="panel-heading"><div><span className="eyebrow">THE FIRST CONVERSATION</span><h2>从第一次相识开始。</h2><p>只填称呼也可以建档，其他了解可以慢慢补充。</p></div><span className="step-label">WELCOME</span></div><form className="new-client-form" onSubmit={event => void create(event)}><fieldset disabled={busy}><div className="field-row"><label>新客户称呼<input required maxLength={40} value={newName} onChange={e => setNewName(e.target.value)} placeholder="如：林女士" /></label><label>关系说明<input maxLength={200} value={newRelationship} onChange={e => setNewRelationship(e.target.value)} placeholder="如：首次到店咨询" /></label></div><ClientBasicsFields stage={newStage} background={newBackground} onStage={setNewStage} onBackground={setNewBackground} /></fieldset><div className="profile-form-actions"><button className="primary" disabled={busy}>建立虚构档案 ↗</button><button className="text-button" type="button" disabled={busy} onClick={() => setCreateOpen(false)}>取消</button></div><p className="field-hint">演示中仅填写虚构客户资料。没有历史对话的新客户，也可以直接准备沟通。</p></form></section> : !profile ? <section className="panel client-welcome"><span className="eyebrow">A RELATIONSHIP, OVER TIME</span><h2>让每一次倾听，<br />成为下一次的体贴。</h2><p>新客户从称呼与本次需求开始；长期往来逐步积累偏好与沟通记录。选择或建立一位客户，了解会随关系一同生长。</p><div><span>有依据地记住</span><span>有分寸地使用</span><span>随时纠正更新</span></div></section> : <>
        <section className="panel client-profile-header"><div><span className="eyebrow">PRIVATE CLIENT JOURNAL</span><h2>{profile.preferred_name}</h2><p>{profile.relationship || '关系仍在慢慢建立。'}</p><ClientBasicsSummary stage={profile.lifecycle_stage} background={profile.background} /><span className={profile.contact_status === 'paused' ? 'failure-chip' : 'success-chip'}>{profile.contact_status === 'paused' ? '暂停主动沟通' : '可准备沟通'} · 修订 {profile.revision}</span></div><button className="primary" disabled={busy} onClick={() => onUse(profile)}>为这位客户准备对话 ↗</button></section>
        <details className="panel profile-settings"><summary>基础资料、关系与联系意愿</summary><form onSubmit={event => { event.preventDefault(); void mutate(() => request(`/api/clients/${profile.id}`, jsonBody('PATCH', { preferred_name: name, relationship, lifecycle_stage: stage, background, contact_status: contactStatus, expected_revision: profile.revision, fictional: true })), '已更新基础资料、关系与联系意愿。') }}><div className="field-row"><label>档案称呼<input required maxLength={40} value={name} onChange={e => setName(e.target.value)} /></label><label>联系意愿<select value={contactStatus} onChange={e => setContactStatus(e.target.value as 'allowed' | 'paused')}><option value="allowed">可准备沟通</option><option value="paused">暂停主动沟通</option></select></label></div><label>关系说明<input maxLength={200} value={relationship} onChange={e => setRelationship(e.target.value)} /></label><ClientBasicsFields stage={stage} background={background} onStage={setStage} onBackground={setBackground} /><button className="primary" disabled={busy}>保存基本资料</button></form></details>
        <div className="profile-columns"><section className="panel fact-journal"><div className="panel-heading"><div><h2>记住的偏好与分寸</h2><p>客户的表态可以改变，资料也应随之更新。</p></div><span className="step-label">UNDERSTAND</span></div><label className="show-history"><input type="checkbox" checked={showHistory} onChange={e => setShowHistory(e.target.checked)} />显示被更新、停用与过期的资料</label><div className="fact-list">{!facts.length && <p className="profile-empty">尚无适用资料，可以从一次明确的客户表态开始。</p>}{facts.map(item => <article className={`client-fact${factState(item) === '已确认' ? '' : ' inactive'}`} key={item.id}><div className="fact-title"><strong>{item.topic}</strong><span>{factState(item)}</span></div><p>{item.value}</p><div className="fact-tags"><span>{KIND_NAMES[item.kind]}</span><span>{SCENE_NAMES[item.scope]}</span><span>{date(item.observed_at)}{item.valid_until ? ` · 至 ${date(item.valid_until)}` : ''}</span></div><details><summary>查看依据</summary><p>{item.source}</p><span className="fact-record-id">记录 {item.id.slice(0, 8)}</span></details><div className="fact-actions">{item.status === 'pending' && <button disabled={busy} className="text-button" onClick={() => void mutate(() => request(`/api/clients/${profile.id}/facts/${item.id}/confirm`, jsonBody('POST', { expected_revision: profile.revision })), '资料已确认，将在适用场景参与生成。')}>确认资料</button>}<button className="text-button" disabled={busy} onClick={() => correct(item)}>更正</button>{['pending', 'confirmed'].includes(item.status) && <button className="text-button" disabled={busy} onClick={() => void mutate(() => request(`/api/clients/${profile.id}/facts/${item.id}/retire`, jsonBody('POST', { expected_revision: profile.revision })), '已停用这条资料，后续生成不再参考。')}>停用</button>}</div></article>)}</div>
          <form className="profile-form" onSubmit={event => void saveFact(event)}><h3>{fact.replaces_fact_id ? '更正这份了解' : '补充一份了解'}</h3><div className="field-row"><label>资料类别<select value={fact.kind} onChange={e => setFact({ ...fact, kind: e.target.value as FactKind })}>{Object.entries(KIND_NAMES).map(([id, title]) => <option value={id} key={id}>{title}</option>)}</select></label><label>适用场景<select value={fact.scope} onChange={e => setFact({ ...fact, scope: e.target.value as FactScope })}>{Object.entries(SCENE_NAMES).map(([id, title]) => <option value={id} key={id}>{title}</option>)}</select></label></div><label>资料主题<input required maxLength={60} value={fact.topic} onChange={e => setFact({ ...fact, topic: e.target.value })} placeholder="如：表达风格、日常配色" /></label><label>具体了解<textarea ref={factValue} required maxLength={500} rows={2} value={fact.value} onChange={e => setFact({ ...fact, value: e.target.value })} placeholder="如：喜欢直白简短的祝福，不喜欢古诗" /></label><label>信息依据<textarea required maxLength={1000} rows={2} value={fact.source} onChange={e => setFact({ ...fact, source: e.target.value })} placeholder="记录客户原话或顾问核实的依据" /></label><div className="field-row"><label>获知日期 <small>留空为现在</small><input type="date" value={fact.observed} onChange={e => setFact({ ...fact, observed: e.target.value })} /></label><label>失效日期 <small>选填</small><input type="date" value={fact.expires} onChange={e => setFact({ ...fact, expires: e.target.value })} /></label></div><label>确认状态<select value={fact.status} onChange={e => setFact({ ...fact, status: e.target.value })}><option value="confirmed">顾问已核实，可用于生成</option><option value="pending">待核实，暂不用于生成</option></select></label><div className="profile-form-actions"><button className="primary" disabled={busy}>保存资料</button>{fact.replaces_fact_id && <button className="text-button" type="button" onClick={() => setFact(emptyFact())}>取消更正</button>}</div></form>
        </section>
        <section className="panel interaction-journal"><div className="panel-heading"><div><h2>相处的时间线</h2><p>保留实际发生的沟通，不把草稿当成经历。</p></div><span className="step-label">REMEMBER</span></div><ol className="interaction-list">{!profile.interactions.some(item => item.status === 'active') && <li className="profile-empty">还没有沟通记录。</li>}{profile.interactions.filter(item => item.status === 'active').map(item => <li key={item.id}><div><strong>{item.speaker === 'client' ? '客户' : '顾问'}</strong><span>{date(item.occurred_at)}</span></div><p>{item.text}</p><small>{item.source} · {item.scenario ? SCENE_NAMES[item.scenario] : '通用沟通'}</small><button className="text-button" disabled={busy} onClick={() => void mutate(() => request(`/api/clients/${profile.id}/interactions/${item.id}/retire`, jsonBody('POST', { expected_revision: profile.revision })), '已移出使用范围，后续生成不再参考这次沟通。')}>移出使用范围</button></li>)}</ol><form className="profile-form" onSubmit={event => void saveInteraction(event)}><h3>记录一次沟通</h3><div className="field-row"><label>发言人<select value={interaction.speaker} onChange={e => setInteraction({ ...interaction, speaker: e.target.value })}><option value="client">客户</option><option value="advisor">顾问</option></select></label><label>沟通场景<select value={interaction.scenario} onChange={e => setInteraction({ ...interaction, scenario: e.target.value })}><option value="">通用沟通</option>{Object.entries(SCENE_NAMES).filter(([id]) => id !== 'all').map(([id, title]) => <option value={id} key={id}>{title}</option>)}</select></label></div><label>沟通内容<textarea required maxLength={2000} rows={3} value={interaction.text} onChange={e => setInteraction({ ...interaction, text: e.target.value })} placeholder="记录客户或顾问已实际说过的话" /></label><div className="field-row"><label>记录来源<input required maxLength={120} value={interaction.source} onChange={e => setInteraction({ ...interaction, source: e.target.value })} /></label><label>沟通日期 <small>留空为现在</small><input type="date" value={interaction.occurred} onChange={e => setInteraction({ ...interaction, occurred: e.target.value })} /></label></div><button className="primary" disabled={busy}>保存沟通记录</button><p className="field-hint">这段对话会参与适用场景的起草；重要偏好请另外核实并保存为资料。</p></form><details className="profile-audit"><summary>查看修订记录</summary><ol>{profile.events.map(item => <li key={item.id}><span>修订 {item.revision}</span><strong>{{ created: '建立档案', fictional_demo_imported: '载入虚构示例', profile_updated: '更新基本资料', fact_added: '补充资料', fact_confirmed: '确认资料', fact_retired: '停用资料', interaction_recorded: '记录沟通', interaction_retired: '停用沟通记录' }[item.action] || '更新档案'}</strong><small>{date(item.created_at)}</small></li>)}</ol></details></section></div>
      </>}
    </div>
  </div>
}
