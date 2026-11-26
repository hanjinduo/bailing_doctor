<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import { get, post, del } from '@/api'
import TopBar from '@/components/TopBar.vue'

const route = useRoute()
const router = useRouter()
const tabs = ['全部', '审核中', '可使用', '已使用', '已失效']
const tab = ref(route.query.tab || '全部')
const rxs = ref([])
const loading = ref(false)
const PAGE = 20
const total = ref(0)
const hasMore = ref(false)
const loadingMore = ref(false)
const busy = ref(0)

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

// 按方加购：把处方内可线上销售的处方药按开具数量放入购物车
const buy = async (r) => {
  busy.value = r.id
  const j = await post('/rx/' + r.id + '/buy')
  busy.value = 0
  if (j.ok) {
    showToast(j.msg)
    if (j.skipped && j.skipped.length) setTimeout(() => showToast(j.skipped.join('；')), 1600)
    router.push('/cart')
  }
}

const remove = async (r) => {
  if (r.status === '已使用') return showToast('已用于购药的处方不可删除')
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
    <TopBar title="我的处方" right="上传线下处方" @right="router.push('/rx/upload')" />
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
          <div class="muted" style="margin-top: 2px">问诊医生：{{ r.doc || '线下医院' }} · {{ r.title || '' }} · {{ r.dept }}</div>
          <div class="muted">开具日期：{{ (r.created || '').slice(0, 10) }} · 单号 {{ r.no }}</div>
          <div v-if="r.source && r.source !== '线上问诊'" class="muted">来源：{{ r.source }}</div>
          <div v-if="r.used_at" class="muted">核销时间：{{ r.used_at }}</div>
          <div class="between" style="margin-top: 10px">
            <span class="muted">共 {{ r.count }} 种药品</span>
            <span>
              <button v-if="r.status === '可使用'" class="btn btn-sm buy" :disabled="busy === r.id" @click="buy(r)">按方购药</button>
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
          处方说明：<br />1. 审核中处方由执业药师审核，约 1 分钟内完成；<br />2. 可使用处方有效期 7 天，仅能按开具的药品与数量购买一次；<br />3.
          购药支付成功后处方即核销，不可重复使用；<br />4. 已失效处方不可再购买处方药。
        </div>
        <div class="up" @click="router.push('/rx/upload')">＋ 上传线下医院处方，药师审核后可线上购药</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.more {
  text-align: center;
  padding: 10px 0;
}
.seg {
  overflow-x: auto;
  white-space: nowrap;
}
.buy {
  background: var(--pri);
  color: #fff;
  border: 0;
  margin-right: 6px;
}
.up {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--line);
  color: var(--pri);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
</style>
