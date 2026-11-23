<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import { get, post } from '@/api'
import { yuan } from '@/utils/format'
import TopBar from '@/components/TopBar.vue'

const route = useRoute()
const router = useRouter()
const med = ref(null)
const loading = ref(true)
// stock < 0 表示不限库存（后端约定：NULL / 负值），>= 0 为真实库存
const stock = computed(() => (med.value ? Number(med.value.stock ?? -1) : -1))
const soldOut = computed(() => stock.value === 0)
const stockText = computed(() => {
  if (stock.value < 0) return '不限量'
  return stock.value === 0 ? '已售罄' : '仅剩 ' + stock.value + ' 件'
})
const lowStock = computed(() => stock.value > 0 && stock.value <= 10)
// ---------- 用户评价 ----------
const rvSummary = ref(null)
const rvList = ref([])
const rvLimit = ref(3)
const rvTotal = ref(0)
const rvLoading = ref(false)
const stars = (n) => '★★★★★'.slice(0, Math.round(Number(n) || 0)) + '☆☆☆☆☆'.slice(0, 5 - Math.round(Number(n) || 0))

async function loadReviews() {
  rvLoading.value = true
  try {
    const j = await get('/meds/' + route.params.id + '/reviews?limit=' + rvLimit.value)
    if (j && j.ok) {
      rvSummary.value = j.summary
      rvList.value = j.reviews || []
      rvTotal.value = j.total || 0
    }
  } catch (e) {
    // 评价加载失败不影响主信息展示
  }
  rvLoading.value = false
}
const toggleMore = async () => {
  rvLimit.value = rvList.value.length >= rvTotal.value ? 3 : rvTotal.value
  await loadReviews()
}

const qty = ref(1)
const maxQty = computed(() => (stock.value >= 0 ? Math.max(stock.value, 1) : 99))
const inc = () => {
  if (qty.value >= maxQty.value) {
    showToast(stock.value >= 0 ? '库存仅剩 ' + stock.value + ' 件' : '单次最多购买 99 件')
    return
  }
  qty.value++
}

onMounted(async () => {
  // 走 /meds/{id} 单查：列表接口已分页（默认 20 条），用列表本地 find 会漏掉 id 靠后的商品
  await load()
})

// 同一路由不同商品复用组件实例时 onMounted 不会再次执行，必须监听参数变化重新拉取
watch(() => route.params.id, async (v) => {
  if (!v) return
  loading.value = true
  qty.value = 1          // 切换商品时数量归位，避免沿用上一件商品的购买数量
  rvSummary.value = null  // 评价概览与列表同步清空，避免短暂展示上一件商品的评价
  rvList.value = []
  rvTotal.value = 0
  rvLimit.value = 3
  await load()
})

async function load() {
  const j = await get('/meds/' + route.params.id)
  med.value = j && j.ok ? j.med : null
  loading.value = false
  if (med.value) loadReviews()
}

const add = async (buy) => {
  const j = await post('/cart', { med_id: med.value.id, qty: qty.value })
  if (j && j.ok) {
    showToast(j.msg)
    if (buy) router.push('/cart')
  }
}
</script>

<template>
  <div>
    <TopBar title="商品详情" right="购物车" @right="router.push('/cart')" />
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="!med" class="empty">商品不存在或已下架</div>
    <div v-else class="page" style="padding-bottom: 96px">
      <div class="card">
        <div style="display: flex; gap: 12px; align-items: center">
          <div class="em" style="font-size: 40px">{{ med.icon }}</div>
          <div style="flex: 1">
            <div class="b" style="font-size: 16px">
              {{ med.name }}
              <span class="tag" :class="med.rx ? 'r' : ''">{{ med.rx ? '处方药' : 'OTC' }}</span>
            </div>
            <div class="muted">{{ med.spec }} · {{ med.cat }}</div>
            <div class="price" style="font-size: 20px; margin-top: 4px">{{ yuan(med.price) }}</div>
          </div>
        </div>
        <div class="muted" style="margin-top: 8px">
          已售 {{ med.sales }} 件 ·
          <span :style="soldOut ? 'color: #e54d42' : lowStock ? 'color: #ed6a0c' : ''">{{ stockText }}</span>
          · 满 ¥29 包邮（会员包邮）
        </div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 6px">商品介绍</div>
        <div class="muted" style="line-height: 1.8">{{ med.intro }}</div>
        <div v-if="med.rx" class="warn" style="margin-top: 10px">
          该商品为处方药，下单前需在问诊中由医生开具处方，结算时选择「可使用」状态的处方。
        </div>
      </div>

      <div class="card">
        <div class="between">
          <span>购买数量<span class="muted" style="margin-left: 6px">（库存 {{ stockText }}）</span></span>
          <span>
            <button class="btn btn-sm btn-gray" :disabled="qty <= 1" @click="qty > 1 && qty--">－</button>
            <b style="margin: 0 10px">{{ qty }}</b>
            <button class="btn btn-sm btn-gray" :disabled="soldOut || qty >= maxQty" @click="inc()">＋</button>
          </span>
        </div>
      </div>

      <div class="card" v-if="rvSummary && rvSummary.count">
        <div class="between" style="margin-bottom: 10px">
          <span class="b">用户评价（{{ rvSummary.count }}）</span>
          <span class="muted" v-if="rvTotal > 3" @click="toggleMore">
            {{ rvList.length >= rvTotal ? '收起' : '查看全部 ' + rvTotal + ' 条 ›' }}
          </span>
        </div>
        <div class="rv-top">
          <div class="rv-score">
            <div class="num">{{ rvSummary.avg }}</div>
            <div class="s">{{ stars(rvSummary.avg) }}</div>
            <div class="muted" style="font-size: 11px">好评率 {{ rvSummary.good_rate }}%</div>
          </div>
          <div class="rv-bar">
            <div v-for="d in rvSummary.dist" :key="d.star" class="line">
              <span class="lb">{{ d.star }}星</span>
              <span class="bg"><i :style="{ width: (rvSummary.count ? (d.n * 100 / rvSummary.count) : 0) + '%' }"></i></span>
              <span class="n">{{ d.n }}</span>
            </div>
          </div>
        </div>
        <div class="split"></div>
        <div v-for="r in rvList" :key="r.id" class="rv-item">
          <div class="between">
            <span class="nick">{{ r.nick }}</span>
            <span class="s" style="font-size: 12px">{{ stars(r.rating) }}</span>
          </div>
          <div class="txt">{{ r.content || '该用户没有填写评价内容' }}</div>
          <div class="muted" style="font-size: 11px; margin-top: 4px">{{ r.created }}</div>
        </div>
        <div v-if="rvLoading" class="loading" style="padding: 10px 0">加载中…</div>
      </div>

      <div v-if="med.rx" class="card">
        <div class="between" @click="router.push('/rxs')">
          <span>我的处方</span><span class="muted">查看可用处方 ›</span>
        </div>
      </div>

      <div class="bottom-bar">
        <div>
          <div class="muted">小计</div>
          <div class="price" style="font-size: 18px">{{ yuan(med.price * qty) }}</div>
        </div>
        <div style="display: flex; gap: 8px">
          <button class="btn btn-line" :disabled="soldOut" @click="add(false)">{{ soldOut ? '已售罄' : '加入购物车' }}</button>
          <button class="btn" :disabled="soldOut" @click="add(true)">{{ soldOut ? '已售罄' : '立即购买' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rv-top {
  display: flex;
  gap: 16px;
  align-items: center;
}
.rv-score {
  width: 84px;
  text-align: center;
}
.rv-score .num {
  font-size: 26px;
  font-weight: 700;
  color: #0f766e;
  line-height: 1.1;
}
.rv-score .s {
  color: #f59e0b;
  font-size: 12px;
  letter-spacing: 1px;
}
.rv-bar {
  flex: 1;
}
.rv-bar .line {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.rv-bar .lb {
  font-size: 11px;
  color: #9ca3af;
  width: 26px;
}
.rv-bar .bg {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: #f1f2f4;
  overflow: hidden;
  display: block;
}
.rv-bar .bg i {
  display: block;
  height: 100%;
  background: #f59e0b;
  border-radius: 3px;
}
.rv-bar .n {
  font-size: 11px;
  color: #9ca3af;
  width: 22px;
  text-align: right;
}
.rv-item {
  padding: 8px 0;
  border-bottom: 1px solid #f5f6f8;
}
.rv-item:last-child {
  border-bottom: none;
}
.rv-item .nick {
  font-size: 13px;
  color: #374151;
}
.rv-item .txt {
  font-size: 13px;
  color: #111827;
  line-height: 1.7;
  margin-top: 4px;
}
</style>
