<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { get, post } from '@/api'
import TopBar from '@/components/TopBar.vue'

const router = useRouter()
const tab = ref('可用')
const live = ref([])
const dead = ref([])
const tpls = ref([])
const loading = ref(false)
const PAGE = 20
const hasMore = ref(false)
const loadingMore = ref(false)

const params = (offset) => ({ limit: PAGE, offset })

const load = async () => {
  loading.value = true
  const j = await get('/coupons', params(0))
  live.value = j.coupons || []
  dead.value = j.invalid || []
  tpls.value = (j.tpls || []).filter((t) => !t.claimed)
  hasMore.value = !!j.has_more
  loading.value = false
}

// 分页作用于「我的券」全集（可用 + 失效），offset 用已加载条数累加
const loadMore = async () => {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  try {
    const j = await get('/coupons', params(live.value.length + dead.value.length))
    live.value = live.value.concat(j.coupons || [])
    dead.value = dead.value.concat(j.invalid || [])
    hasMore.value = !!j.has_more
  } finally {
    loadingMore.value = false
  }
}

// 触底加载：距页面底部 80px 内自动续拉
const onScroll = () => {
  if (!hasMore.value || loadingMore.value) return
  const el = document.documentElement
  if (el.scrollTop + window.innerHeight >= el.scrollHeight - 80) loadMore()
}

const claim = async (t) => {
  const j = await post('/coupons/claim', { tpl_id: t.id })
  if (j.ok) {
    showToast(j.msg)
    load()
  }
}

onMounted(async () => {
  await load()
  window.addEventListener('scroll', onScroll, { passive: true })
})

onUnmounted(() => window.removeEventListener('scroll', onScroll))
</script>

<template>
  <div>
    <TopBar title="优惠券" />
    <div class="page">
      <div class="seg">
        <div :class="{ on: tab === '可用' }" @click="tab = '可用'">可用（{{ live.length }}）</div>
        <div :class="{ on: tab === '失效' }" @click="tab = '失效'">已失效（{{ dead.length }}）</div>
      </div>

      <div v-if="loading" class="loading">加载中…</div>
      <template v-else>
        <template v-if="tab === '可用'">
          <div v-for="c in live" :key="c.id" class="coupon">
            <div class="l"><b>¥{{ c.amount }}</b><span>满{{ c.threshold }}元可用</span></div>
            <div class="r">
              <div class="between"><span class="b">{{ c.name }}</span><span class="muted">{{ c.scope }}</span></div>
              <div class="muted">有效期至 {{ c.expire }}</div>
              <div class="between" style="margin-top: 8px">
                <span class="muted">下单自动可选</span>
                <button class="btn btn-sm" @click="router.push('/shop')">去使用</button>
              </div>
            </div>
          </div>
        </template>
        <template v-else>
          <div v-for="c in dead" :key="c.id" class="coupon dead">
            <div class="l"><b>¥{{ c.amount }}</b><span>满{{ c.threshold }}元可用</span></div>
            <div class="r">
              <div class="between"><span class="b">{{ c.name }}</span><span class="muted">{{ c.scope }}</span></div>
              <div class="muted">有效期至 {{ c.expire }}</div>
              <div class="muted" style="margin-top: 8px">状态：{{ c.status }}</div>
            </div>
          </div>
        </template>
        <div v-if="!(tab === '可用' ? live : dead).length" class="empty">暂无优惠券</div>
        <div v-if="live.length || dead.length" class="more">
          <div v-if="hasMore">{{ loadingMore ? '加载中…' : '上滑加载更多' }}</div>
          <div v-else>没有更多了</div>
        </div>
      </template>

      <div class="card" style="margin-top: 6px">
        <div class="b" style="margin-bottom: 6px">领券中心</div>
        <div v-for="t in tpls" :key="t.id" class="between tpl">
          <div>
            <div class="b">{{ t.name }}</div>
            <div class="muted">满 {{ t.threshold }} 减 {{ t.amount }} · 限{{ t.scope }}</div>
          </div>
          <button class="btn btn-sm btn-line" @click="claim(t)">领取</button>
        </div>
        <div v-if="!tpls.length" class="muted">已领取全部券</div>
      </div>

      <div class="muted" style="text-align: center; padding: 8px 0">优惠券不可叠加使用，每单限用一张</div>
    </div>
  </div>
</template>

<style scoped>
.tpl {
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
</style>
