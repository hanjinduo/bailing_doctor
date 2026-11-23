import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/login', component: () => import('@/views/Login.vue'), meta: { public: true, bare: true } },
  { path: '/register', component: () => import('@/views/Register.vue'), meta: { public: true, bare: true } },
  { path: '/', redirect: '/home' },
  { path: '/home', component: () => import('@/views/Home.vue'), meta: { tab: 'home' } },
  { path: '/ask', component: () => import('@/views/Ask.vue'), meta: { tab: 'ask' } },
  { path: '/doctors', component: () => import('@/views/Doctors.vue') },
  { path: '/doctor/:id', component: () => import('@/views/Doctor.vue') },
  { path: '/msgs', component: () => import('@/views/Msgs.vue'), meta: { tab: 'msgs' } },
  { path: '/chat/:cid', component: () => import('@/views/Chat.vue'), meta: { bare: true } },
  { path: '/paychat/:cid', component: () => import('@/views/PayChat.vue') },
  { path: '/vip', component: () => import('@/views/Vip.vue') },
  { path: '/shop', component: () => import('@/views/Shop.vue'), meta: { tab: 'shop' } },
  { path: '/product/:id', component: () => import('@/views/Product.vue') },
  { path: '/cart', component: () => import('@/views/Cart.vue') },
  { path: '/confirm', component: () => import('@/views/Confirm.vue') },
  { path: '/address', component: () => import('@/views/Address.vue') },
  { path: '/me', component: () => import('@/views/Me.vue'), meta: { tab: 'me' } },
  { path: '/mychats', component: () => import('@/views/MyChats.vue') },
  { path: '/rxs', component: () => import('@/views/Rxs.vue') },
  { path: '/rx/:id', component: () => import('@/views/Rx.vue') },
  { path: '/coupons', component: () => import('@/views/Coupons.vue') },
  { path: '/orders', component: () => import('@/views/Orders.vue') },
  { path: '/order/:id', component: () => import('@/views/OrderDetail.vue') },
  { path: '/records', component: () => import('@/views/Records.vue') },
  { path: '/news', component: () => import('@/views/News.vue') },
  { path: '/news/:id', component: () => import('@/views/NewsDetail.vue') },
  { path: '/pkgs', component: () => import('@/views/Pkgs.vue') },
  { path: '/pkg/:id', component: () => import('@/views/Pkg.vue') },
  { path: '/appts', component: () => import('@/views/Appts.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/home' }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})

router.beforeEach((to) => {
  const token = localStorage.getItem('token')
  if (!to.meta.public && !token) return { path: '/login' }
  if (to.path === '/login' && token) return { path: '/home' }
  return true
})

export default router
