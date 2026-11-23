<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '@/api'

const router = useRouter()
const data = ref({ banner: {}, depts: [], doctors: [], news: [] })
const loading = ref(true)

const quick = [
  { icon: '⚡', name: '极速问诊', path: '/ask' },
  { icon: '🔍', name: '找医生', path: '/doctors' },
  { icon: '💊', name: '我的处方', path: '/rxs' },
  { icon: '🎫', name: '优惠券', path: '/coupons' },
  { icon: '🏥', name: '特色门诊', path: '/pkgs' },
  { icon: '🛒', name: '百灵药房', path: '/shop' },
  { icon: '💬', name: '问诊记录', path: '/mychats' },
  { icon: '👤', name: '个人中心', path: '/me' }
]

onMounted(async () => {
  const j = await get('/home')
  data.value = { banner: j.banner || {}, depts: j.depts || [], doctors: j.doctors || [], news: j.news || [] }
  loading.value = false
})
</script>

<template>
  <div>
    <div class="top green">
      <div class="tt" style="text-align: left; font-size: 17px">百灵医生</div>
      <div class="rt" @click="router.push('/me')">👤</div>
    </div>
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else class="page">
      <div class="banner" @click="router.push('/ask')">
        <h3>{{ data.banner.title }}</h3>
        <p>{{ data.banner.sub }}</p>
        <div style="margin-top: 10px">
          <span class="btn btn-sm" style="background: rgba(255, 255, 255, 0.22)">立即问诊 ›</span>
        </div>
      </div>

      <div class="card">
        <div class="grid g4">
          <div v-for="q in quick" :key="q.name" class="ico" @click="router.push(q.path)">
            <div class="em">{{ q.icon }}</div>{{ q.name }}
          </div>
        </div>
      </div>

      <div class="card">
        <div class="between" style="margin-bottom: 4px">
          <span class="b">选择科室</span>
          <span class="muted" @click="router.push('/doctors')">全部 ›</span>
        </div>
        <div class="grid g4">
          <div v-for="d in data.depts" :key="d.id" class="ico" @click="router.push({ path: '/doctors', query: { dept: d.id } })">
            <div class="em">{{ d.icon }}</div>{{ d.name }}
          </div>
        </div>
      </div>

      <div class="card">
        <div class="between" style="margin-bottom: 6px">
          <span class="b">推荐医生</span>
          <span class="muted" @click="router.push('/doctors')">更多 ›</span>
        </div>
        <div v-for="d in data.doctors" :key="d.id" class="item" @click="router.push('/doctor/' + d.id)">
          <div class="em">{{ d.icon }}</div>
          <div class="bd">
            <div class="tt">{{ d.name }} <span class="muted">{{ d.title }}</span></div>
            <div class="ds">{{ d.dept }} · 从医{{ d.years }}年 · {{ d.good }}</div>
          </div>
          <div style="text-align: right">
            <div class="price">¥{{ d.fee }}</div>
            <div class="muted">挂号</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="between" style="margin-bottom: 6px">
          <span class="b">健康资讯</span>
          <span class="muted" @click="router.push('/news')">更多 ›</span>
        </div>
        <div v-for="n in data.news" :key="n.id" class="item" @click="router.push('/news/' + n.id)">
          <div class="em">{{ n.icon }}</div>
          <div class="bd">
            <div class="tt">{{ n.title }}</div>
            <div class="ds">{{ n.digest }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
