import type { Run } from './types'

export default function ReplyReview({ run }: { run: Run }) {
  if (!run.reply_brief && !run.quality_review) return null
  const findings = run.quality_review?.findings ?? []
  return <div className="reply-review">
    {run.quality_review?.copy_blocked && <p className="error" role="alert">候选中仍有需要修正的内容，请核实并修改后再采用。</p>}
    <details><summary>本次表达考虑 <span>{findings.length ? `${findings.length} 处需要留意` : '查看沟通重点与参考线索'}</span></summary><div className="reply-review-body">
      {run.reply_brief && <><p className="reply-goal">{run.reply_brief.goal}</p><div className="reply-approaches">{run.reply_brief.approaches.map((item, index) => <div key={item.title}><span>0{index + 1}</span><strong>{item.title}</strong><p>{item.intent}</p></div>)}</div>{!!run.reply_brief.focus_evidence.length && <div className="reply-evidence"><h3>用于起草的线索</h3>{run.reply_brief.focus_evidence.slice(0, 4).map(item => <p key={item.ref}><strong>{item.topic}</strong>{item.value}</p>)}<small>这些是提供给起草过程的线索，仍需检查正文是否使用得当。</small></div>}</>}
      {!!findings.length && <div className="reply-findings"><h3>采用前再看一眼</h3>{findings.map((item, index) => <p key={index}><strong>第 {item.candidate_index} 条</strong>{item.message}{item.excerpt && <q>{item.excerpt}</q>}</p>)}</div>}
      <p className="review-note">自动检查覆盖部分明显问题，事实、贴合度与语气仍需顾问确认。</p>
    </div></details>
  </div>
}
