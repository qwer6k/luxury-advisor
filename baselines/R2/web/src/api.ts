export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options)
  if (!response.ok) {
    if (response.status === 503) throw new Error('模型尚未配置，请在本机配置 Key 后重启服务。')
    if (response.status === 502) throw new Error('本次生成未成功，运行记录已保留。请稍后再试。')
    if (response.status === 422) throw new Error('输入未通过检查，请确认必填信息、字段长度、日期与产品选择。')
    if (response.status === 409 || response.status === 404) {
      const body = await response.json().catch(() => ({}))
      if (typeof body.detail === 'string') throw new Error(body.detail)
    }
    throw new Error(`请求未成功（${response.status}），请稍后再试。`)
  }
  return response.json() as Promise<T>
}

export const jsonBody = (method: string, body: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
