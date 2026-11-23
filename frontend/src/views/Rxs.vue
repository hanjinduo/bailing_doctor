<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import { get, del } from '@/api'
import TopBar from '@/components/TopBar.vue'

const route = useRoute()
const router = useRouter()
const tabs = ['全部', '审核中', '可使用', '已失效']
const tab = ref(route.query.tab || '全部')
const rxs = ref([])
const loading = ref(false)
const PAGE = 20
const total = ref(0)
const hasMore = ref(false)
const loadingMore = ref(false)

const color = (s) => (s === '审核中' ? 'w' : s === '可使用' ? '' : 'g')

const params = (offset) => {
  const p = { limit: PAGE, offset }
  if (tab.value !== '全部') p.status = tab.value
  return p
}

const load = async () => {
  loading.value = true
  const j = await get('/rxs', params(0))
  rxs.value = j.rxs || []
  total.value = j.total || 0
  hasMore.value = !!j.has_more
  loading.value = false
}

const loadMore = async () => {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  const j = await get('/rxs', params(rxs.value.length))
  rxs.value = rxs.value.concat(j.rxs || [])
  total.value = j.total || total.value
  hasMore.value = !!j.has_more
  loadingMore.value = false
}

const switchTab = (t) => {
  tab.value = t
  router.replace({ path: '/rxs', query: t === '全部' ? {} : { tab: t } })
  load()
}

const remove = async (r) => {
  await showConfirmDialog({ title: '删除处方', message: '确认删除该处方？删除后不可用于购药。' })
  const j = await del('/rx/' + r.id)
  if (j.ok) {
    showToast('已删除')
    load()
  }
}

onMounted(load)
</script>

<template>
  <div>
    <TopBar title="我的处方" right="去问诊" @right="router.push('/ask')" />
    <div class="page">
      <div class="seg">
        <div v-for="t in tabs" :key="t" :class="{ on: tab === t }" @click="switchTab(t)">{{ t }}</div>
      </div>

      <div v-if="loading" class="loading">加载中…</div>
      <template v-else>
        <div v-for="r in rxs" :key="r.id" class="rx">
          <div class="between">
            <span class="b">{{ r.diag }}</span>
            <span class="tag" :class="color(r.status)">{{ r.status }}</span>
          </div>
          <div class="muted" style="margin-top: 2px">问诊医生：{{ r.doc }} · {{ r.title || '' }} · {{ r.dept }}</div>
          <div class="muted">开具日期：{{ (r.created || '').slice(0, 10) }} · 单号 {{ r.no }}</div>
          <div class="between" style="margin-top: 10px">
            <span class="muted">共 {{ r.count }} 种药品</span>
            <span>
              <button class="btn btn-sm btn-line" @click="router.push('/rx/' + r.id)">查看用药详情</button>
              <button class="btn btn-sm btn-gray" @click="remove(r)">删除</button>
            </span>
          </div>
        </div>
        <div v-if="!rxs.length" class="empty">该状态下暂无处方</div>
        <div v-if="rxs.length" class="more">
          <button v-if="hasMore" class="btn btn-line" :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? '加载中…' : '加载更多' }}
          </button>
          <div v-else class="muted">没有更多了</div>
        </div>
      </template>

      <div class="card">
        <div class="muted" style="line-height: 1.9">
          处方说明：<br />1. 审核中处方由执业药师审核，约 1 分钟内完成；<br />2. 可使用处方有效期 7 天，可用于购买对应处方药；<br />3.
          已失效处方不可再购买处方药。
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.more {
  text-align: center;
  padding: 10px 0;
}
</style>
