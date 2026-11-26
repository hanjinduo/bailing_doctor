<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import { get, post } from '@/api'
import { yuan } from '@/utils/format'
import TopBar from '@/components/TopBar.vue'
import Sheet from '@/components/Sheet.vue'

const route = useRoute()
const router = useRouter()
const rx = ref(null)
const items = ref([])
const conflicts = ref([])
const fail = ref('')
const auditor = ref(false)
const busy = ref(false)
const showReject = ref(false)
const reason = ref('')

const isMine = computed(() => !!(rx.value && rx.value.mine))
const canAudit = computed(() => !!(rx.value && rx.value.can_audit) && auditor.value)
const hasHigh = computed(() => conflicts.value.some((c) => c.level === 'high'))
const isOffline = computed(() => !!(rx.value && rx.value.source === '线下上传'))
const imgUrl = (n) => (n ? '/uploads/' + n : '')
const isPdf = (n) => /\.pdf$/i.test(n || '')

const load = async () => {
  const j = await get('/rx/' + route.params.id)
  if (!j.ok) {
    fail.value = j.msg || '处方不存在'
    return
  }
  rx.value = j.rx
  items.value = j.items || []
  conflicts.value = j.conflicts || []
  auditor.value = !!j.auditor
}

const audit = async () => {
  if (hasHigh.value) return showToast('存在严重配伍禁忌，不能通过审核')
  await showConfirmDialog({ title: '审核通过', message: '确认该处方用药合理、可放行购药？' })
  busy.value = true
  const j = await post('/rx/' + rx.value.id + '/audit')
  busy.value = false
  if (j.ok) {
    showToast(j.msg)
    load()
  }
}

const reject = async () => {
  if (!reason.value.trim()) return showToast('请填写驳回理由')
  busy.value = true
  const j = await post('/rx/' + rx.value.id + '/reject', { reason: reason.value.trim() })
  busy.value = false
  if (j.ok) {
    showReject.value = false
    reason.value = ''
    showToast(j.msg)
    load()
  }
}

const buy = async () => {
  busy.value = true
  const j = await post('/rx/' + rx.value.id + '/buy')
  busy.value = false
  if (j.ok) {
    showToast(j.msg)
    if (j.skipped && j.skipped.length) {
      // 非处方药/特管药不进入购物车，需明确告知
      setTimeout(() => showToast(j.skipped.join('；')), 1600)
    }
    router.push('/cart')
  }
}

onMounted(load)
// 同路由不同处方复用组件实例时补拉数据
watch(() => route.params.id, (v) => {
  if (v) {
    fail.value = ''
    rx.value = null
    items.value = []
    conflicts.value = []
    load()
  }
})
</script>

<template>
  <div>
    <TopBar title="处方详情" />
    <div v-if="fail" class="empty">{{ fail }}</div>
    <div v-else-if="!rx" class="loading">加载中…</div>
    <div v-else class="page">
      <div class="card">
        <div class="between">
          <span class="b" style="font-size: 16px">{{ isOffline ? '线下处方' : '电子处方' }}</span>
          <span class="tag" :class="rx.status === '审核中' ? 'w' : rx.status === '可使用' ? '' : 'g'">{{ rx.status }}</span>
        </div>
        <div class="split"></div>
        <div class="kv"><span>处方单号</span><span>{{ rx.no }}</span></div>
        <div class="kv"><span>处方来源</span><span>{{ rx.source || '线上问诊' }}</span></div>
        <div class="kv"><span>诊断</span><b>{{ rx.diag }}</b></div>
        <div class="kv"><span>开具医生</span><span>{{ rx.doc }} · {{ rx.title || '' }} · {{ rx.dept }}</span></div>
        <div class="kv"><span>患者</span><span>{{ rx.patient || '本人' }}</span></div>
        <div class="kv"><span>开具时间</span><span>{{ (rx.created || '').slice(0, 16) }}</span></div>
        <div v-if="rx.expire" class="kv"><span>有效期至</span><span>{{ rx.expire }}</span></div>
        <div v-if="rx.sign" class="kv"><span>医师签名</span><span>{{ rx.sign }}</span></div>
        <div v-if="rx.audit_by" class="kv"><span>审核药师</span><span>{{ rx.audit_by }} · {{ rx.audit_at }}</span></div>
        <div v-if="rx.used_at" class="kv"><span>核销时间</span><span>{{ rx.used_at }}</span></div>
        <div v-if="rx.order_id" class="kv">
          <span>关联订单</span>
          <span class="lnk" @click="router.push('/order/' + rx.order_id)">查看订单 ›</span>
        </div>
        <div v-if="rx.reject_reason" class="kv"><span>驳回理由</span><span style="color: #ef4444">{{ rx.reject_reason }}</span></div>
      </div>

      <div v-if="rx.img" class="card">
        <div class="b" style="margin-bottom: 8px">处方影像</div>
        <img v-if="!isPdf(rx.img)" :src="imgUrl(rx.img)" class="shot" alt="处方影像" />
        <a v-else :href="imgUrl(rx.img)" target="_blank" class="muted">查看处方 PDF 影像 ›</a>
      </div>

      <div v-if="conflicts.length" class="card warn-card" :class="{ high: hasHigh }">
        <div class="b" style="margin-bottom: 6px">用药安全提示（配伍禁忌）</div>
        <div v-for="(c, k) in conflicts" :key="k" class="cf">
          <span class="lv" :class="c.level === 'high' ? 'lv-h' : 'lv-m'">{{ c.level_cn || c.level }}</span>
          <span>{{ c.a }} + {{ c.b }}：{{ c.tip }}</span>
        </div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 6px">用药明细</div>
        <div v-for="(i, k) in items" :key="k" class="item">
          <div class="em">💊</div>
          <div class="bd">
            <div class="tt">
              {{ i.name }}
              <span v-if="i.control" class="mini ctl">特管药</span>
              <span v-else-if="i.rx" class="mini">处方药</span>
              <span v-else class="mini otc">OTC</span>
              <span v-if="!i.bound" class="mini otc">已下架</span>
            </div>
            <div class="ds">{{ i.spec }}</div>
            <div class="muted">{{ i.usage }} × {{ i.qty }}</div>
          </div>
          <div class="price">{{ yuan(i.price) }}</div>
        </div>
        <div class="split"></div>
        <div class="kv"><span>用药建议</span></div>
        <div class="muted" style="line-height: 1.8; color: #374151">{{ rx.advice }}</div>
      </div>

      <!-- 药师审方：仅药师/管理员可见可操作 -->
      <template v-if="canAudit">
        <div class="tip">您当前为药师身份，请核对诊断与用药后再放行。</div>
        <button class="btn" :disabled="busy || hasHigh" @click="audit">审核通过，允许购药</button>
        <button class="btn btn-gray" style="margin-top: 8px" @click="showReject = true">驳回处方</button>
      </template>

      <!-- 患者侧 -->
      <template v-else>
        <button v-if="rx.status === '可使用' && isMine" class="btn" :disabled="busy" @click="buy">按方加购</button>
        <button v-if="rx.status === '审核中' && isMine" class="btn btn-line" @click="router.push('/rxs')">
          等待药师审核，先看看其他处方
        </button>
        <div v-if="rx.status === '审核中'" class="tip">处方已提交执业药师审核，通过后即可购买。</div>
        <div v-else-if="rx.status === '已使用'" class="tip">该处方已用于购药核销，不可重复使用。</div>
        <div v-else-if="rx.status !== '可使用'" class="warn">该处方已失效，如需购药请重新问诊。</div>
      </template>

      <Sheet v-model="showReject" title="填写驳回理由">
        <textarea v-model="reason" class="ta" placeholder="如：诊断与用药不符 / 用法用量超限 / 需补充检查" />
        <button class="btn" :disabled="busy" @click="reject">确认驳回并通知患者</button>
      </Sheet>
    </div>
  </div>
</template>

<style scoped>
.lnk {
  color: var(--pri);
  cursor: pointer;
}
.mini {
  font-size: 10px;
  font-weight: 400;
  padding: 1px 5px;
  border-radius: 6px;
  background: #eefaf7;
  color: #0a8f8a;
  margin-left: 4px;
}
.mini.otc {
  background: #eef2f7;
  color: #64748b;
}
.mini.ctl {
  background: #fef2f2;
  color: #ef4444;
}
.warn-card {
  background: #fffbeb;
  border: 1px solid #fde68a;
}
.warn-card.high {
  background: #fef2f2;
  border-color: #fecaca;
}
.cf {
  display: flex;
  gap: 6px;
  font-size: 12px;
  line-height: 1.7;
  color: #374151;
}
.lv {
  flex: 0 0 auto;
  height: 18px;
  line-height: 18px;
  padding: 0 6px;
  border-radius: 6px;
  font-size: 10px;
  color: #fff;
}
.lv-h {
  background: #ef4444;
}
.lv-m {
  background: #f59e0b;
}
.shot {
  width: 100%;
  border-radius: 10px;
  display: block;
}
.ta {
  width: 100%;
  height: 84px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px 10px;
  font-size: 13px;
  resize: none;
  margin-bottom: 10px;
  box-sizing: border-box;
}
.tip {
  text-align: center;
  font-size: 12px;
  color: var(--gray);
  padding: 6px 0 10px;
  line-height: 1.7;
}
</style>
