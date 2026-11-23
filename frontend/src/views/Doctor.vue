<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import { get, post } from '@/api'
import TopBar from '@/components/TopBar.vue'

const route = useRoute()
const router = useRouter()
const id = computed(() => route.params.id)
const doctor = ref(null)
const slots = ref([])
const mode = ref('text')

const services = [
  { key: 'text', icon: '💬', name: '图文问诊', fee: 50, desc: '24 小时内不限次沟通' },
  { key: 'video', icon: '🎥', name: '视频问诊', fee: 150, desc: '15 分钟面对面问诊' }
]
const curFee = computed(() => (mode.value === 'video' ? 150 : 50))

const load = async () => {
  const j = await get('/doctor/' + id.value)
  if (!j.ok) return showToast(j.msg || '医生不存在')
  doctor.value = j.doctor
  slots.value = (j.slots || []).filter((s) => s.left > 0).slice(0, 4)
}

onMounted(load)
// 同路由切换医生时复用组件实例，需监听参数变化重新拉取
watch(id, (v) => { if (v) { doctor.value = null; slots.value = []; load() } })

const book = async (s) => {
  const j = await post('/appt', { slot_id: s.id })
  if (j.ok) showToast(j.msg || '挂号成功')
}

const goAsk = () => {
  router.push({
    path: '/ask',
    query: { doctorid: id.value, doctor: doctor.value.name, dept: doctor.value.dept, mode: mode.value }
  })
}
</script>

<template>
  <div>
    <TopBar title="医生主页" />
    <div v-if="!doctor" class="loading">加载中…</div>
    <div v-else class="page" style="padding-bottom: 86px">
      <div class="card">
        <div class="hd">
          <div class="avatar lg">{{ doctor.icon }}</div>
          <div>
            <div class="b" style="font-size: 17px">
              {{ doctor.name }} <span class="muted" style="font-weight: 400">{{ doctor.title }}</span>
            </div>
            <div class="muted">{{ doctor.dept }} · {{ doctor.hospital }}</div>
            <div class="muted">好评 {{ doctor.score }} · 已服务 {{ doctor.serve }} 人</div>
          </div>
        </div>
        <div class="split"></div>
        <div class="muted">擅长：{{ doctor.good }}</div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 8px">选择问诊服务</div>
        <div class="grid g2">
          <div
            v-for="s in services"
            :key="s.key"
            class="opt"
            :class="{ on: mode === s.key }"
            style="margin: 0"
            @click="mode = s.key"
          >
            <div style="font-size: 22px">{{ s.icon }}</div>
            <div class="b">{{ s.name }}</div>
            <div class="price">¥{{ s.fee }}</div>
            <div class="muted" style="font-size: 11px">{{ s.desc }}</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 6px">医生简介</div>
        <div class="muted" style="line-height: 1.8; color: #374151">{{ doctor.intro }}</div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 8px">患者评价（{{ doctor.reviews.length }}）</div>
        <div v-for="(r, i) in doctor.reviews" :key="i" style="padding: 8px 0; border-bottom: 1px solid var(--line)">
          <div class="between">
            <span class="b">{{ r.name }}</span>
            <span class="muted">{{ '★'.repeat(r.score) }}</span>
          </div>
          <div class="muted" style="color: #374151; margin-top: 4px">{{ r.text }}</div>
        </div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 8px">可预约号源</div>
        <div
          v-for="s in slots"
          :key="s.id"
          class="between"
          style="padding: 8px 0; border-bottom: 1px solid var(--line)"
        >
          <span>{{ s.day }} {{ s.time }} <span class="muted">余{{ s.left }}</span></span>
          <button class="btn btn-sm btn-line" @click="book(s)">挂号 ¥{{ doctor.fee }}</button>
        </div>
        <div v-if="!slots.length" class="empty">暂无可预约号源</div>
      </div>

      <div class="bottom-bar">
        <div>
          <div class="muted">{{ mode === 'video' ? '视频问诊' : '图文问诊' }}</div>
          <div class="price" style="font-size: 18px">¥{{ curFee }}</div>
        </div>
        <button class="btn" @click="goAsk">去问诊</button>
      </div>
    </div>
  </div>
</template>
