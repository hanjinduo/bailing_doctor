<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import { get, post } from '@/api'
import { yuan } from '@/utils/format'
import TopBar from '@/components/TopBar.vue'

const route = useRoute()
const router = useRouter()
const rx = ref(null)
const fail = ref('')

const load = async () => {
  const j = await get('/rx/' + route.params.id)
  if (!j.ok) fail.value = j.msg || '处方不存在'
  else rx.value = j.rx
}

const audit = async () => {
  const j = await post('/rx/' + rx.value.id + '/audit')
  if (j.ok) {
    showToast(j.msg)
    load()
  }
}

onMounted(load)
// 同路由不同处方复用组件实例时补拉数据
watch(() => route.params.id, (v) => { if (v) { fail.value = ''; rx.value = null; load() } })
</script>

<template>
  <div>
    <TopBar title="处方详情" />
    <div v-if="fail" class="empty">{{ fail }}</div>
    <div v-else-if="!rx" class="loading">加载中…</div>
    <div v-else class="page">
      <div class="card">
        <div class="between">
          <span class="b" style="font-size: 16px">电子处方</span>
          <span class="tag" :class="rx.status === '审核中' ? 'w' : rx.status === '可使用' ? '' : 'g'">{{ rx.status }}</span>
        </div>
        <div class="split"></div>
        <div class="kv"><span>处方单号</span><span>{{ rx.no }}</span></div>
        <div class="kv"><span>诊断</span><b>{{ rx.diag }}</b></div>
        <div class="kv"><span>开具医生</span><span>{{ rx.doc }} · {{ rx.title || '' }} · {{ rx.dept }}</span></div>
        <div class="kv"><span>患者</span><span>{{ rx.patient || '本人' }}</span></div>
        <div class="kv"><span>开具时间</span><span>{{ (rx.created || '').slice(0, 16) }}</span></div>
        <div v-if="rx.expire" class="kv"><span>有效期至</span><span>{{ rx.expire }}</span></div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 6px">用药明细</div>
        <div v-for="(i, k) in rx.items" :key="k" class="item">
          <div class="em">💊</div>
          <div class="bd">
            <div class="tt">{{ i.name }}</div>
            <div class="ds">{{ i.spec }}</div>
            <div class="muted">{{ i.usage }} × {{ i.qty }}</div>
          </div>
          <div class="price">{{ yuan(i.price) }}</div>
        </div>
        <div class="split"></div>
        <div class="kv"><span>用药建议</span></div>
        <div class="muted" style="line-height: 1.8; color: #374151">{{ rx.advice }}</div>
      </div>

      <button v-if="rx.status === '审核中'" class="btn" @click="audit">模拟药师审核通过</button>
      <button v-else-if="rx.status === '可使用'" class="btn" @click="router.push('/shop')">去购买处方药</button>
      <div v-else class="warn">该处方已失效，如需购药请重新问诊。</div>
    </div>
  </div>
</template>
