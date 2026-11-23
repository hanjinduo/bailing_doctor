import axios from 'axios'
import { showToast } from 'vant'

// 后端采用 JWT(HS256) 鉴权，登录后自动携带 Authorization: Bearer <token>
const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api',
  timeout: 30000
})

http.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('token')
  if (token) cfg.headers.Authorization = 'Bearer ' + token
  return cfg
})

http.interceptors.response.use(
  (res) => {
    const d = res.data
    if (d && d.ok === false && d.msg) showToast(d.msg)
    return d
  },
  (err) => {
    const status = err.response && err.response.status
    const d = err.response && err.response.data
    // 422 参数校验 / 429 限流 都是后端返回的中文提示，直接展示
    const msg = (d && (d.detail || d.msg)) || '网络异常，请确认服务已启动'
    if (status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('uid')
      showToast(msg)
      if (!location.hash.startsWith('#/login')) location.hash = '#/login'
    } else {
      showToast(msg)
    }
    return Promise.reject(err)
  }
)

export const get = (url, params) => http.get(url, { params })
export const post = (url, data) => http.post(url, data || {})
export const put = (url, data) => http.put(url, data || {})
export const del = (url) => http.delete(url)
export const postForm = (url, form) => http.post(url, form)
export const getBlob = (url) => http.get(url, { responseType: 'blob' })

export default http
