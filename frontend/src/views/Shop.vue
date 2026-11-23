<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import { get, post } from '@/api'
import { yuan } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const cat = ref(route.query.cat || '')
const meds = ref([])
const cats = ref([])
const banner = ref({ title: '', sub: '' })
const cart = ref({ items: [], amount: 0 })
const loading = ref(false)
const PAGE = 20
const total = ref(0)
const hasMore = ref(false)
const loadingMore = ref(false)

const quick = [
  { p: '/ask', e: '⚡', n: '极速问诊' },
  { p: '/cart', e: '🛒', n: '购物车' },
  { p: '/rxs', e: '💊', n: '我的处方' },
  { p: '/coupons', e: '🎫', n: '优惠券' },
  { p: '/pkgs', e: '🏥', n: '特色门诊' },
  { p: '/orders', e: '📦', n: '商城订单' },
  { p: '/doctors', e: '👨‍⚕️', n: '找医生' },
  { p: '/vip', e: '👑', n: '会员中心' }
]

const load = async () => {
  loading.value = true
  const [j, cj] = await Promise.all([
    get('/meds', { cat: cat.value, limit: PAGE, offset: 0 }),
    get('/cart')
  ])
  meds.value = j.meds || []
  cats.value = j.cats || []
  banner.value = j.banner || { title: '', sub: '' }
  total.value = j.total || 0
  hasMore.value = !!j.has_more
  cart.value = { items: cj.items || [], amount: cj.amount || 0 }
  loading.value = false
}

const loadMore = async () => {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  const j = await get('/meds', { cat: cat.value, limit: PAGE, offset: meds.value.length })
  meds.value = meds.value.concat(j.meds || [])
  total.value = j.total || total.value
  hasMore.value = !!j.has_more
  loadingMore.value = false
}

const setCat = (c) => {
  cat.value = c
  router.replace({ path: '/shop', query: c ? { cat: c } : {} })
  load()
}

const addCart = async (m) => {
  const j = await post('/cart', { med_id: m.id, qty: 1 })
  if (j.ok) {
    showToast(j.msg)
    load()
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="top green">
      <div class="tt" style="text-align: left; font-size: 17px">百灵大药房</div>
      <div class="rt" @click="router.push('/cart')">🛒 购物车</div>
    </div>

    <div class="page" :style="{ paddingBottom: cart.items.length ? '86px' : '12px' }">
      <div class="banner" @click="router.push('/ask')">
        <div class="between">
          <div>
            <h3>{{ banner.title }}</h3>
            <p>{{ banner.sub }}</p>
          </div>
          <span class="btn btn-sm" style="background: rgba(255, 255, 255, 0.24)">极速问诊 ›</span>
        </div>
      </div>

      <div class="card">
        <div class="grid g4">
          <div v-for="q in quick" :key="q.p" class="ico" @click="router.push(q.p)">
            <div class="em">{{ q.e }}</div>
            {{ q.n }}
          </div>
        </div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 6px">药品分类</div>
        <div class="grid g5">
          <div class="ico" @click="setCat('')"><div class="em">🏪</div>全部</div>
          <div v-for="c in cats" :key="c.name" class="ico" @click="setCat(c.name)">
            <div class="em">{{ c.icon }}</div>
            {{ c.name.replace('用药', '') }}
          </div>
        </div>
      </div>

      <div v-if="cat" class="between" style="margin: 0 4px 8px">
        <span class="b">{{ cat }}</span>
        <span class="muted" @click="setCat('')">清除筛选</span>
      </div>
      <div v-else class="b" style="margin: 0 4px 8px">商品推荐</div>

      <div class="card">
        <div v-if="loading" class="loading">加载中…</div>
        <div v-for="m in meds" :key="m.id" class="item" @click="router.push('/product/' + m.id)">
          <div class="em">{{ m.icon }}</div>
          <div class="bd">
            <div class="tt">
              {{ m.name }}
              <span class="tag" :class="m.rx ? 'r' : ''">{{ m.rx ? '处方药' : 'OTC' }}</span>
            </div>
            <div class="ds">{{ m.spec }} · {{ m.cat }}</div>
            <div v-if="m.review_count" style="font-size: 12px; color: #f59e0b; margin: 2px 0">
              ★ {{ m.rating }}<span style="color: #9ca3af">（{{ m.review_count }} 条评价）</span>
            </div>
            <div v-else class="muted" style="font-size: 12px; margin: 2px 0">暂无评价</div>
            <div class="muted">{{ m.intro }}</div>
            <div class="between" style="margin-top: 4px">
              <span class="price">{{ yuan(m.price) }}<small> 已售{{ m.sales }}</small>
                <small v-if="m.stock === 0" style="color: #e54d42"> · 已售罄</small>
                <small v-else-if="m.stock > 0 && m.stock <= 10" style="color: #ed6a0c"> · 仅剩{{ m.stock }}件</small>
              </span>
              <button class="btn btn-sm" :disabled="m.stock === 0" @click.stop="addCart(m)">
                {{ m.stock === 0 ? '已售罄' : '加入购物车' }}
              </button>
            </div>
          </div>
        </div>
        <div v-if="!loading && !meds.length" class="empty">暂无商品</div>
        <div v-if="meds.length" class="more">
          <button v-if="hasMore" class="btn btn-line" :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? '加载中…' : '加载更多' }}
          </button>
          <div v-else class="muted">没有更多了</div>
        </div>
      </div>
    </div>

    <div v-if="cart.items.length" class="bottom-bar">
      <div>
        <div class="muted">{{ cart.items.length }} 件商品</div>
        <div class="price" style="font-size: 17px">{{ yuan(cart.amount) }}</div>
      </div>
      <button class="btn btn-line" @click="router.push('/cart')">查看购物车</button>
    </div>
  </div>
</template>

<style scoped>
.more {
  text-align: center;
  padding: 10px 0;
}
</style>
