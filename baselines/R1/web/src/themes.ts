import { useEffect, useState } from 'react'

export const THEMES = [
  { id: 'forest', name: '翡林私邸', english: 'THE PRIVATE SALON', number: '01', mood: '静谧 · 亲近 · 从容', description: '森林绿与暖象牙，在安静的私人会客厅里，让每一次关心自然发生。', material: '森林绿 / 象牙白 / 哑光黄铜', headline: ['把关心，', '说得恰到好处。'], note: '给对话留白，让理解靠近。', swatches: ['#183f35', '#f5f3ea', '#b09361'] },
  { id: 'obsidian', name: '曜石沙龙', english: 'AFTER HOURS', number: '02', mood: '深邃 · 精致 · 笃定', description: '曜石黑与香槟金，如晚间沙龙的一束柔光，聚焦每一句值得被听见的话。', material: '曜石黑 / 香槟金 / 烟灰', headline: ['言语有光，', '相处有度。'], note: '珍视每一次，被认真对待的时刻。', swatches: ['#181a1c', '#c8ae7f', '#777674'] },
  { id: 'gallery', name: '雾白艺廊', english: 'A STUDY IN STILLNESS', number: '03', mood: '纯净 · 理性 · 自由', description: '雾白、墨色与建筑般的留白，以艺廊式横向布局，呈现清晰而舒展的表达。', material: '石膏白 / 墨黑 / 冷石灰', headline: ['少一点修饰，', '多一点懂得。'], note: '好的表达，自有它的分量。', swatches: ['#f5f5f2', '#272928', '#b9bcb5'] },
  { id: 'atelier', name: '赤陶工坊', english: 'THE HUMAN TOUCH', number: '04', mood: '温暖 · 细腻 · 真诚', description: '干邑棕与纸本米色，像手作皮具的一针一线，把耐心藏进细节。', material: '干邑棕 / 纸本米 / 赤陶', headline: ['让每一句话，', '都有手心的温度。'], note: '细细斟酌，才值得交到对方手中。', swatches: ['#713e2d', '#f3e9da', '#bd865c'] },
] as const

export type ThemeId = typeof THEMES[number]['id']
export type VisualTheme = typeof THEMES[number]
const STORAGE_KEY = 'xuyu.visual-theme.v1'
export const isTheme = (value: unknown): value is ThemeId => THEMES.some(theme => theme.id === value)

export function useVisualTheme() {
  const [themeId, setThemeId] = useState<ThemeId>(() => {
    const query = new URLSearchParams(location.search).get('theme')
    if (isTheme(query)) return query
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (isTheme(saved)) return saved
    } catch { /* The current session can still switch themes without storage. */ }
    return 'forest'
  })
  useEffect(() => {
    document.documentElement.dataset.theme = themeId
    document.documentElement.style.colorScheme = themeId === 'obsidian' ? 'dark' : 'light'
    const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    if (themeColor) themeColor.content = themeId === 'obsidian' ? '#181a1c' : themeId === 'atelier' ? '#f3e9da' : themeId === 'gallery' ? '#f5f5f2' : '#183f35'
    try { localStorage.setItem(STORAGE_KEY, themeId) } catch { /* Optional persistence. */ }
  }, [themeId])
  function selectTheme(value: ThemeId) {
    setThemeId(value)
    // Keep an explicitly shared theme URL in sync with the visible selection.
    const url = new URL(location.href)
    if (url.searchParams.has('theme')) {
      url.searchParams.set('theme', value)
      history.replaceState(null, '', url)
    }
  }
  return { theme: THEMES.find(value => value.id === themeId)!, selectTheme }
}
