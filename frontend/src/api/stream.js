// SSE 流式请求封装
//
// 为什么不用 EventSource：浏览器原生 EventSource 只支持 GET、且无法自定义请求头，
// 而问诊接口需要 POST 提交消息体、并携带 Authorization: Bearer <token>。
// 因此这里用 fetch + ReadableStream 手工解析 SSE 帧（data: <json>\n\n），
// 既能带鉴权头，又能逐帧回调，做到真正的边生成边渲染。

const BASE = import.meta.env.VITE_API_BASE || '/api'

/**
 * POST 一个 SSE 接口并消费流
 * @param {string} url      相对 BASE 的路径，如 '/chat/stream'
 * @param {object} body     请求体
 * @param {object} handlers { onDelta(v), onDone(obj) }
 * @returns {Promise<object>} done 帧内容
 */
export async function streamPost(url, body, handlers = {}) {
  const { onDelta, onDone } = handlers
  const token = localStorage.getItem('token')

  const res = await fetch(BASE + url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: 'Bearer ' + token } : {})
    },
    body: JSON.stringify(body || {})
  })

  // 业务校验失败（会话不存在、状态不对等）后端会返回普通 JSON，此时按普通错误处理
  const ctype = res.headers.get('content-type') || ''
  if (!res.ok || !ctype.includes('text/event-stream')) {
    let msg = '网络异常，请确认服务已启动'
    try {
      const d = await res.json()
      msg = d.detail || d.msg || msg
    } catch (e) {
      /* 响应体非 JSON，保留默认提示 */
    }
    if (res.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('uid')
      if (!location.hash.startsWith('#/login')) location.hash = '#/login'
    }
    throw new Error(msg)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''
  let doneFrame = null

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let cut
    while ((cut = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, cut).trim()
      buf = buf.slice(cut + 2)
      if (!frame.startsWith('data:')) continue
      let obj
      try {
        obj = JSON.parse(frame.slice(5).trim())
      } catch (e) {
        continue // 心跳或半包，跳过
      }
      if (obj.t === 'delta') {
        if (onDelta) onDelta(obj.v)
      } else if (obj.t === 'done') {
        doneFrame = obj
        if (onDone) onDone(obj)
      }
    }
  }
  return doneFrame
}
