import { defineStore } from 'pinia'
import { get, post } from '@/api'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    user: null,
    stat: {}
  }),
  getters: {
    isLogin: (s) => !!s.token,
    isVip: (s) => !!(s.user && s.user.vip_until)
  },
  actions: {
    async login(phone, pwd) {
      const r = await post('/login', { phone, pwd })
      if (r.ok) this.setAuth(r.token, r.user)
      return r
    },
    async register(phone, pwd, name = '', code = '') {
      const r = await post('/register', { phone, pwd, name, code })
      if (r.ok) this.setAuth(r.token, r.user)
      return r
    },
    setAuth(token, user) {
      this.token = token || ''
      localStorage.setItem('token', this.token)
      if (user) this.user = user
    },
    async fetchMe() {
      const r = await get('/me')
      if (r.ok) {
        this.user = r.user
        this.stat = r.stat || {}
      }
      return r
    },
    logout() {
      this.token = ''
      this.user = null
      this.stat = {}
      localStorage.removeItem('token')
      localStorage.removeItem('uid')
    }
  }
})
