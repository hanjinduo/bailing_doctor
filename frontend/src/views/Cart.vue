<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get, put } from '@/api'
import { yuan } from '@/utils/format'
import TopBar from '@/components/TopBar.vue'

const router = useRouter()
const items = ref([])
const amount = ref(0)
const hasRx = ref(false)
const loading = ref(true)

const load = async () => {
  loading.value = true
  const j = await get('/cart')
  items.value = j.items || []
  amount.value = j.amount || 0
  hasRx.value = !!j.has_rx
  loading.value = false
}

const setQty = async (item, qty) => {
  const j = await put('/cart/' + item.med_id, { qty })
  if (j.ok) load()
}

const checkout = () => {
  sessionStorage.removeItem('svc')
  router.push('/confirm')
}

onMounted(load)
</script>

<template>
  <div>
    <TopBar title="购物车" />
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="!items.length" class="page">
      <div class="empty">
        购物车还是空的<br /><br />
        <button class="btn btn-sm btn-line" @click="router.push('/shop')">去逛逛</button>
      </div>
    </div>
    <div v-else class="page" style="padding-bottom: 86px">
      <div class="card">
        <div v-for="i in items" :key="i.med_id" class="item">
          <div class="em">{{ i.icon }}</div>
          <div class="bd">
            <div class="tt">
              {{ i.name }}
              <span v-if="i.rx" class="tag r">处方药</span>
            </div>
            <div class="ds">{{ i.spec }}</div>
            <div v-if="i.stock === 0" class="ds" style="color: #e54d42">该商品已售罄，请先移出购物车</div>
            <div v-else-if="i.stock > 0 && i.qty > i.stock" class="ds" style="color: #ed6a0c">
              库存仅剩 {{ i.stock }} 件，请调整数量后再结算
            </div>
            <div class="between" style="margin-top: 6px">
              <span class="price">{{ yuan(i.price) }}</span>
              <span>
                <button class="btn btn-sm btn-gray" @click="setQty(i, i.qty - 1)">－</button>
                <b style="margin: 0 6px">{{ i.qty }}</b>
                <button class="btn btn-sm btn-gray" :disabled="i.stock === 0 || (i.stock > 0 && i.qty >= i.stock)" @click="setQty(i, i.qty + 1)">＋</button>
                <button class="btn btn-sm btn-red" @click="setQty(i, 0)">删除</button>
              </span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="hasRx" class="warn">
        购物车含处方药，结算时需选择「可使用」状态的处方，否则无法提交订单。
      </div>

      <div class="bottom-bar">
        <div>
          <div class="muted">合计（不含运费）</div>
          <div class="price" style="font-size: 18px">{{ yuan(amount) }}</div>
        </div>
        <button class="btn" @click="checkout">去结算</button>
      </div>
    </div>
  </div>
</template>
