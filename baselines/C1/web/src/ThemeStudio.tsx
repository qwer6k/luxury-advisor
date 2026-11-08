import { useEffect, useRef } from 'react'
import { THEMES } from './themes'
import type { ThemeId, VisualTheme } from './themes'

export function MaterialScene({ variant, miniature = false }: { variant: ThemeId; miniature?: boolean }) {
  return <div className={`material-scene scene-${variant}${miniature ? ' miniature' : ''}`} aria-hidden="true">
    <div className="scene-glow" /><div className="scene-line" />
    <div className="scene-arch" /><div className="scene-orb" />
    <div className="scene-plinth" /><div className="scene-fold" />
    <span className="scene-monogram">序</span>
    {!miniature && <span className="scene-signature">XUYU · MATERIAL STUDY</span>}
  </div>
}

export default function ThemeStudio({ open, theme, onSelect, onClose }: { open: boolean; theme: VisualTheme; onSelect: (theme: ThemeId) => void; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current
    if (!element) return
    if (open && !element.open) element.showModal()
    if (!open && element.open) element.close()
  }, [open])
  return <dialog ref={dialog} className="theme-studio" aria-labelledby="theme-studio-title" onClose={onClose} onClick={event => { if (event.target === event.currentTarget) { const bounds = event.currentTarget.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose() } }}>
    <div className="studio-header"><div><span className="eyebrow">THE XUYU COLLECTION</span><h2 id="theme-studio-title">为此刻，选一种气质。</h2><p>四种视觉语言，同一份待客之心。</p></div><button autoFocus className="close-button" aria-label="关闭风格陈列室" onClick={onClose}>×</button></div>
    <div className="theme-collection" role="group" aria-label="选择界面风格">{THEMES.map(item => <button key={item.id} className={`theme-card${theme.id === item.id ? ' selected' : ''}`} aria-pressed={theme.id === item.id} aria-label={`切换到${item.name}`} onClick={() => onSelect(item.id)}>
      <div className="theme-preview"><MaterialScene variant={item.id} miniature /><span className="theme-preview-number">{item.number}</span><span className="theme-check">{theme.id === item.id ? '✓ 使用中' : '预览此风格 ↗'}</span></div>
      <div className="theme-card-body"><span className="theme-english">{item.english}</span><div className="theme-card-title"><h3>{item.name}</h3><span className="swatches">{item.swatches.map(color => <i key={color} style={{ background: color }} />)}</span></div><p className="theme-mood">{item.mood}</p><p className="theme-description">{item.description}</p></div>
    </button>)}</div>
    <div className="studio-footer"><p role="status" aria-live="polite">当前 · {theme.name}<span>选择后即时生效，偏好会保存在这台设备。</span></p><button className="primary" onClick={onClose}>进入{theme.name} <span aria-hidden="true">↗</span></button></div>
  </dialog>
}
