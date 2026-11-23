<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import { get, post } from '@/api'
import { yuan } from '@/utils/format'
import TopBar from '@/components/TopBar.vue'

const route = useRoute()
const router = useRouter()
const tabs = ['全部', '待支付', '待接诊', '问诊中', '已结束']
const tab = ref(route.query.status || '全部')
const chats = ref([])
const loading = ref(false)
const PAGE = 20
const total = ref(0)
const hasMore = ref(false)
const loadingMore = ref(false)

const MODE = { text: '图文', voice: '语音', video: '视频' }
const color = (s) => (s === '待支付' ? 'r' : s === '问诊中' || s === '待接诊' ? 'w' : 'g')

const params = (offset) => {
  const p = { limit: PAGE, offset }
  if (tab.value !== '全部') p.status = tab.value
  return p
}

// 后端 /api/chats 忽略 status 参数，仍由前端按 status 本地过滤；这里只负责分页拉取
// offset 必须按「已从服务端拉取条数」推进，不能用本地过滤后的长度，否则会重复拉同一批
const fetched = ref(0)

const load = async () => {
  loading.value = true
  const j = await get('/chats', params(0))
  const all = j.chats || []
  chats.value = tab.value === '全部' ? all : all.filter((c) => c.status === tab.value)
  fetched.value = all.length
  total.value = j.total || 0
  hasMore.value = !!j.has_more
  loading.value = false
}

const loadMore = async () => {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  const j = await get('/chats', params(fetched.value))
  const all = j.chats || []
  const more = all.filter((c) => tab.value === '全部' || c.status === tab.value)
  chats.value = chats.value.concat(more)
  fetched.value += all.length
  total.value = j.total || total.value
  hasMore.value = !!j.has_more
  loadingMore.value = false
}

const switchTab = (t) => {
  tab.value = t
  router.replace({ path: '/mychats', query: t === '全部' ? {} : { status: t } })
  load()
}

const cancelChat = async (c) => {
  await showConfirmDialog({ title: '取消问诊', message: '确认取消该问诊订单？' })
  const j = await post('/chat/' + c.id + '/cancel')
  if (j.ok) {
    showToast(j.msg)
    load()
  }
}

onMounted(load)
</script>

<template>
  <div>
    <TopBar title="问诊记录" right="去问诊" @right="router.push('/ask')" />
    <div class="page">
      <div class="seg">
        <div v-for="t in tabs" :key="t" :class="{ on: tab === t }" @click="switchTab(t)">{{ t }}</div>
      </div>

      <div v-if="loading" class="loading">加载中…</div>
      <template v-else>
        <div v-for="c in chats" :key="c.id" class="card">
          <div class="between">
            <span class="b">{{ c.doc }} {{ c.title }} · {{ c.dept }}</span>
            <span class="tag" :class="color(c.status)">{{ c.status }}</span>
          </div>
          <div class="muted" style="margin-top: 4px">症状：{{ c.symptom }}</div>
          <div class="muted">
            {{ (c.created || '').slice(0, 16) }} · {{ MODE[c.mode] || '图文' }}问诊 · {{ yuan(c.fee) }}
          </div>
          <div style="text-align: right; margin-top: 8px">
            <template v-if="c.status === '待支付'">
              <button class="btn btn-sm btn-gray" @click="cancelChat(c)">取消订单</button>
              <button class="btn btn-sm" @click="router.push('/paychat/' + c.id)">去支付 {{ yuan(c.fee) }}</button>
            </template>
            <button v-else-if="c.status === '待接诊'" class="btn btn-sm btn-line" @click="router.push('/chat/' + c.id)">
              进入问诊
            </button>
            <button v-else-if="c.status === '问诊中'" class="btn btn-sm" @click="router.push('/chat/' + c.id)">
              继续问诊
            </button>
            <button v-else class="btn btn-sm btn-gray" @click="router.push('/chat/' + c.id)">查看记录</button>
          </div>
        </div>
        <div v-if="!chats.length" class="empty">暂无问诊记录</div>
        <div v-if="chats.length" class="more">
          <button v-if="hasMore" class="btn btn-line" :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? '加载中…' : '加载更多' }}
          </button>
          <div v-else class="muted">没有更多了</div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.more {
  text-align: center;
  padding: 10px 0;
}
</style>
