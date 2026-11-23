<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get } from '@/api'
import TopBar from '@/components/TopBar.vue'

const route = useRoute()
const router = useRouter()
const depts = ref([])
const doctors = ref([])
const sel = ref(Number(route.query.dept || 0))
const PAGE = 20
const hasMore = ref(false)
const loadingMore = ref(false)

const params = (offset) => {
  const p = { limit: PAGE, offset }
  if (sel.value) p.dept_id = sel.value
  return p
}

const load = async () => {
  const j = await get('/doctors', params(0))
  doctors.value = j.doctors || []
  hasMore.value = !!j.has_more
}

const loadMore = async () => {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  try {
    const j = await get('/doctors', params(doctors.value.length))
    doctors.value = doctors.value.concat(j.doctors || [])
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

const pick = (id) => {
  sel.value = id
  router.replace({ path: '/doctors', query: id ? { dept: id } : {} })
}

watch(sel, load)

onMounted(async () => {
  const d = await get('/depts')
  depts.value = d.depts || []
  await load()
  window.addEventListener('scroll', onScroll, { passive: true })
})

onUnmounted(() => window.removeEventListener('scroll', onScroll))
</script>

<template>
  <div>
    <TopBar title="找医生" />
    <div class="page">
      <div class="chips">
        <div class="chip" :class="{ on: !sel }" @click="pick(0)">全部</div>
        <div v-for="d in depts" :key="d.id" class="chip" :class="{ on: sel === d.id }" @click="pick(d.id)">
          {{ d.icon }} {{ d.name }}
        </div>
      </div>
      <div class="card">
        <div v-for="d in doctors" :key="d.id" class="item" @click="router.push('/doctor/' + d.id)">
          <div class="em">{{ d.icon }}</div>
          <div class="bd">
            <div class="tt">{{ d.name }} <span class="muted">{{ d.title }}</span></div>
            <div class="ds">{{ d.dept }} · 从医 {{ d.years }} 年</div>
            <div class="ds">擅长：{{ d.good }}</div>
          </div>
          <div style="text-align: right">
            <div class="price">¥{{ d.fee }}</div>
            <div class="muted">挂号</div>
          </div>
        </div>
        <div v-if="!doctors.length" class="empty">该科室暂无医生</div>
        <div v-if="doctors.length" class="more">
          <div v-if="hasMore" class="muted">{{ loadingMore ? '加载中…' : '上滑加载更多' }}</div>
          <div v-else class="muted">没有更多了</div>
        </div>
      </div>
    </div>
  </div>
</template>
