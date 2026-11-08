import type { ClientBackground, LifecycleStage } from './types'

export const STAGE_NAMES: Record<LifecycleStage, string> = { unknown: '关系待了解', new: '新客户', developing: '持续了解', established: '长期往来' }
const GENDER_NAMES: Record<ClientBackground['gender'], string> = { unknown: '尚未了解', female: '女性', male: '男性', other: '其他', undisclosed: '客户未透露' }
export const emptyBackground = (): ClientBackground => ({ gender: 'unknown', age: null, occupation: '', source: '', observed_on: null })
export const hasBackground = (value?: ClientBackground) => !!value && (value.gender !== 'unknown' || value.age !== null || !!value.occupation.trim())
export const backgroundTags = (value?: ClientBackground) => !value ? [] : [value.gender !== 'unknown' ? GENDER_NAMES[value.gender] : '', value.age !== null ? `${value.age} 岁（记录时）` : '', value.occupation].filter(Boolean)

export function ClientBasicsFields({ stage, background, onStage, onBackground }: {
  stage: LifecycleStage; background: ClientBackground
  onStage: (value: LifecycleStage) => void; onBackground: (value: ClientBackground) => void
}) {
  return <div className="client-basics-fields">
    <label>关系阶段<select value={stage} onChange={event => onStage(event.target.value as LifecycleStage)}>{Object.entries(STAGE_NAMES).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
    <div className="field-row"><label>性别 <small>选填</small><select value={background.gender} onChange={event => onBackground({ ...background, gender: event.target.value as ClientBackground['gender'] })}>{Object.entries(GENDER_NAMES).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label><label>年龄 <small>记录时，选填</small><input type="number" inputMode="numeric" min={0} max={120} step={1} value={background.age ?? ''} onChange={event => onBackground({ ...background, age: event.target.value === '' ? null : Number(event.target.value) })} placeholder="尚未了解" /></label></div>
    <label>职业 <small>选填</small><input maxLength={100} value={background.occupation} onChange={event => onBackground({ ...background, occupation: event.target.value })} placeholder="如：建筑设计师；只填写已了解的信息" /></label>
    <div className="field-row"><label>基础资料依据 <small>{hasBackground(background) ? '填写资料后必填' : '选填'}</small><textarea rows={2} required={hasBackground(background)} maxLength={500} value={background.source} onChange={event => onBackground({ ...background, source: event.target.value })} placeholder="如：虚构客户自述" /></label><label>资料记录日期 <small>留空为今天</small><input type="date" value={background.observed_on ?? ''} onChange={event => onBackground({ ...background, observed_on: event.target.value || null })} /></label></div>
    <p className="field-hint">未知可留空。基础资料帮助理解背景，实际需求与明确偏好决定表达；不会仅凭性别、年龄或职业推断喜好与预算。</p>
  </div>
}

export function ClientBasicsSummary({ stage, background }: { stage?: LifecycleStage; background?: ClientBackground }) {
  return <div className="client-basics-summary"><div className="client-basics-tags"><span>{STAGE_NAMES[stage ?? 'unknown']}</span>{backgroundTags(background).map(tag => <span key={tag}>{tag}</span>)}</div>{hasBackground(background) && <small>基础资料依据：{background!.source}{background!.observed_on ? ` · ${background!.observed_on} 记录` : ''}</small>}</div>
}
