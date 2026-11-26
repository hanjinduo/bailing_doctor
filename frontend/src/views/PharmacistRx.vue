<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '@/api'
import TopBar from '@/components/TopBar.vue'

const router = useRouter()
const rows = ref([])
const total = ref(0)
const loading = ref(false)
const hasMore = ref(false)
const PAGE = 20

const load = async (offset = 0, append = false) => {
  loading.value = true
  const j = await get('/rx/pending', { limit: PAGE, offset })
  if (j.ok) {
    rows.value = append ? rows.value.concat(j.rx || []) : j.rx || []
    total.value = j.total || 0
    hasMore.value = !!j.has_more
  }
  loading.value = false
}

onMounted(() => load(0))
</script>

<template>
  <div>
    <TopBar title="药师审方台" />
    <div class="page">
      <div class="card head">
        <div class="b">待审处方 {{ total }} 张</div>
        <div class="muted" style="margin-top: 4px">核对诊断与用药合理性，存在严重配伍禁忌的处方不得放行。</div>
      </div>

      <div v-if="loading" class="loading">加载中…</div>
      <template v-else>
        <div v-for="r in rows" :key="r.id" class="rx">
          <div class="between">
            <span class="b">{{ r.diag }}</span>
            <span class="tag w">待审</span>
          </div>
          <div class="muted" style="margin-top: 2px">{{ r.patient_name || '患者' }} · {{ r.dept }} · 单号 {{ r.no }}</div>
          <div class="muted">开具医生：{{ r.doc || '线下医院' }} · {{ (r.created || '').slice(0, 16) }}</div>
          <div class="muted">
            用药：<span v-for="(i, k) in r.items" :key="k">{{ k ? '、' : '' }}{{ i.name }}×{{ i.qty }}</span>
          </div>
          <div v-if="r.conflicts && r.conflicts.length" class="cf">
            配伍风险：
            <span v-for="(c, k) in r.conflicts" :key="k" class="lv" :class="c.level === 'high' ? 'h' : 'm'">
              {{ c.a }}+{{ c.b }}
            </span>
          </div>
          <div class="between" style="margin-top: 10px">
            <span class="muted">来源：{{ r.source || '线上问诊' }}</span>
            <button class="btn btn-sm" @click="router.push('/rx/' + r.id)">去审方</button>
          </div>
        </div>
        <div v-if="!rows.length" class="empty">暂无待审处方</div>
        <div v-if="hasMore" class="more">
          <button class="btn btn-line" :disabled="loading" @click="load(rows.length, true)">加载更多</button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.head {
  background: #eefaf7;
}
.cf {
  margin-top: 6px;
  font-size: 12px;
  color: #92400e;
}
.lv {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 6px;
  color: #fff;
  font-size: 10px;
}
.lv.h {
  background: #ef4444;
}
.lv.m {
  background: #f59e0b;
}
.more {
  text-align: center;
  padding: 10px 0;
}
</style>
