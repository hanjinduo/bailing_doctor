<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import { get, post } from '@/api'
import { yuan } from '@/utils/format'
import TopBar from '@/components/TopBar.vue'

const router = useRouter()
const list = ref([])
const loading = ref(true)
const PAGE = 20
const total = ref(0)
const hasMore = ref(false)
const loadingMore = ref(false)

const load = async () => {
  const j = await get('/appts', { limit: PAGE, offset: 0 })
  list.value = j.appts || []
  total.value = j.total || 0
  hasMore.value = !!j.has_more
  loading.value = false
}

const loadMore = async () => {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  const j = await get('/appts', { limit: PAGE, offset: list.value.length })
  list.value = list.value.concat(j.appts || [])
  total.value = j.total || total.value
  hasMore.value = !!j.has_more
  loadingMore.value = false
}

const cancel = async (a) => {
  await showConfirmDialog({ title: '取消预约', message: '确认取消该面诊预约？' })
  const j = await post('/appt/' + a.id + '/cancel')
  if (j.ok) {
    showToast(j.msg)
    load()
  }
}

onMounted(load)
</script>

<template>
  <div>
    <TopBar title="我的预约" right="找医生" @right="router.push('/doctors')" />
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else class="page">
      <div v-for="a in list" :key="a.id" class="card">
        <div class="between">
          <span class="b">{{ a.doc_name }} <span class="muted">{{ a.dept }}</span></span>
          <span class="tag" :class="a.status === '已预约' ? 'g' : ''">{{ a.status }}</span>
        </div>
        <div class="kv"><span>就诊时间</span><span>{{ a.when }}</span></div>
        <div class="kv"><span>就诊地点</span><span>{{ a.place }}</span></div>
        <div class="kv"><span>挂号费</span><span>{{ yuan(a.fee) }}</span></div>
        <div v-if="a.status === '已预约'" style="text-align: right; margin-top: 8px">
          <button class="btn btn-sm btn-line" @click="cancel(a)">取消预约</button>
        </div>
      </div>
      <div v-if="!list.length" class="empty">还没有预约记录</div>
      <div v-if="list.length" class="more">
        <button v-if="hasMore" class="btn btn-line" :disabled="loadingMore" @click="loadMore">
          {{ loadingMore ? '加载中…' : '加载更多' }}
        </button>
        <div v-else class="muted">没有更多了</div>
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
