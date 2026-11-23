<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showLoadingToast, closeToast } from 'vant'
import { get, post } from '@/api'
import TopBar from '@/components/TopBar.vue'

const route = useRoute()
const router = useRouter()
const cat = ref(route.query.cat || '全部')
const cats = ref([])
const news = ref([])
const PAGE = 20
const hasMore = ref(false)
const loadingMore = ref(false)

const load = async () => {
  const j = await get('/news', { cat: cat.value, limit: PAGE, offset: 0 })
  cats.value = j.cats || []
  news.value = j.news || []
  hasMore.value = !!j.has_more
}

const loadMore = async () => {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  const j = await get('/news', { cat: cat.value, limit: PAGE, offset: news.value.length })
  news.value = news.value.concat(j.news || [])
  hasMore.value = !!j.has_more
  loadingMore.value = false
}

const pick = (c) => {
  cat.value = c
  router.replace({ path: '/news', query: c === '全部' ? {} : { cat: c } })
  load()
}

const gen = async () => {
  showLoadingToast({ message: '生成中…', forbidClick: true })
  const j = await post('/news/generate', { cat: '养生保健' })
  closeToast()
  if (j.ok) router.push('/news/' + j.news.id)
}

onMounted(load)
</script>

<template>
  <div>
    <TopBar title="健康资讯" />
    <div class="page">
      <div class="chips">
        <div v-for="c in cats" :key="c" class="chip" :class="{ on: cat === c }" @click="pick(c)">{{ c }}</div>
      </div>
      <div class="card">
        <div v-for="n in news" :key="n.id" class="item" @click="router.push('/news/' + n.id)">
          <div class="em">{{ n.icon }}</div>
          <div class="bd">
            <div class="tt">{{ n.title }}</div>
            <div class="ds">{{ n.digest }}</div>
            <div class="muted">{{ n.cat }} · {{ (n.created || '').slice(0, 10) }}</div>
          </div>
        </div>
        <div v-if="!news.length" class="empty">暂无资讯</div>
        <div v-if="news.length" class="more">
          <button v-if="hasMore" class="btn btn-line" :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? '加载中…' : '加载更多' }}
          </button>
          <div v-else class="muted">没有更多了</div>
        </div>
      </div>
      <button class="btn btn-line" @click="gen">✨ AI 生成一篇科普</button>
    </div>
  </div>
</template>

<style scoped>
.more {
  text-align: center;
  padding: 10px 0;
}
</style>
