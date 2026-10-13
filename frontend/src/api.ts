import type { MutationBody } from './types'

export async function request<T>(path: string, body?: MutationBody, csrf?: string): Promise<T> {
  if (body !== undefined && !csrf) throw new Error('尚未取得会话校验信息，请等待页面连接成功。')
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 25000)
  try {
    const response = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST', cache: 'no-store', signal: controller.signal,
      headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf! }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
    const data = await response.json().catch(() => { throw new Error(`服务响应无法读取（HTTP ${response.status}）。`) })
    if (!response.ok) throw new Error(data.error || `请求未完成（HTTP ${response.status}）。`)
    return data as T
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw new Error('服务响应超时，已保留上一份数据。请稍后重试。')
    if (error instanceof TypeError) throw new Error('暂时无法连接本地服务，已保留上一份数据。')
    throw error
  } finally { clearTimeout(timeout) }
}

/** Each resource uses its own generation; old responses must not replace newer data. */
export function latestRequest() {
  let generation = 0
  return { next: () => ++generation, current: (id: number) => id === generation, invalidate: () => { generation++ } }
}
