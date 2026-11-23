<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { showConfirmDialog, showToast } from 'vant'
import { get, post, put, del } from '@/api'
import TopBar from '@/components/TopBar.vue'
import Sheet from '@/components/Sheet.vue'

const list = ref([])
const show = ref(false)
const form = ref({ id: 0, name: '', phone: '', region: '', detail: '', is_default: false })
const PAGE = 20
const hasMore = ref(false)
const loadingMore = ref(false)

const params = (offset) => ({ limit: PAGE, offset })

const load = async () => {
  const j = await get('/addresses', params(0))
  list.value = j.addresses || []
  hasMore.value = !!j.has_more
}

const loadMore = async () => {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  try {
    const j = await get('/addresses', params(list.value.length))
    list.value = list.value.concat(j.addresses || [])
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

const openForm = (a) => {
  form.value = a
    ? { id: a.id, name: a.name, phone: a.phone, region: a.region, detail: a.detail, is_default: !!a.is_default }
    : { id: 0, name: '', phone: '', region: '', detail: '', is_default: false }
  show.value = true
}

const save = async () => {
  const f = form.value
  if (!f.name || !f.phone || !f.region || !f.detail) return showToast('请完整填写地址信息')
  if (!/^1\d{10}$/.test(f.phone)) return showToast('手机号格式不正确')
  const body = {
    name: f.name.trim(),
    phone: f.phone.trim(),
    region: f.region.trim(),
    detail: f.detail.trim(),
    is_default: f.is_default ? 1 : 0
  }
  const j = f.id ? await put('/addresses/' + f.id, body) : await post('/addresses', body)
  if (j.ok) {
    show.value = false
    showToast(j.msg)
    load()
  }
}

const remove = async (a) => {
  await showConfirmDialog({ title: '删除地址', message: '确认删除该地址？' })
  const j = await del('/addresses/' + a.id)
  if (j.ok) {
    showToast(j.msg)
    load()
  }
}

const setDefault = async (a) => {
  const j = await post('/addresses/' + a.id + '/default')
  if (j.ok) {
    showToast(j.msg)
    load()
  }
}

const wechat = async () => {
  const j = await post('/addresses/wechat')
  if (j.ok) {
    showToast(j.msg)
    load()
  }
}

onMounted(async () => {
  await load()
  window.addEventListener('scroll', onScroll, { passive: true })
})

onUnmounted(() => window.removeEventListener('scroll', onScroll))
</script>

<template>
  <div>
    <TopBar title="收货地址" />
    <div class="page" style="padding-bottom: 130px">
      <div v-for="a in list" :key="a.id" class="card">
        <div class="between">
          <span class="b">{{ a.name }} {{ a.phone }}</span>
          <span>
            <span v-if="a.is_default" class="tag">默认地址</span>
            <span style="color: var(--pri); margin-left: 8px" @click="openForm(a)">修改</span>
          </span>
        </div>
        <div class="muted" style="margin-top: 4px">{{ a.region }} {{ a.detail }}</div>
        <div class="between" style="margin-top: 8px">
          <span>
            <button v-if="!a.is_default" class="btn btn-sm btn-line" @click="setDefault(a)">设为默认</button>
          </span>
          <button class="btn btn-sm btn-red" @click="remove(a)">删除</button>
        </div>
      </div>
      <div v-if="!list.length" class="empty">还没有收货地址</div>
      <div v-if="list.length" class="more">
        <div v-if="hasMore">{{ loadingMore ? '加载中…' : '上滑加载更多' }}</div>
        <div v-else>没有更多了</div>
      </div>

      <div class="bottom-bar" style="flex-direction: column; gap: 8px">
        <div style="display: flex; gap: 10px; width: 100%">
          <button class="btn btn-line" @click="wechat">使用微信地址</button>
          <button class="btn" @click="openForm(null)">新增地址</button>
        </div>
      </div>
    </div>

    <Sheet v-model="show" :title="form.id ? '修改地址' : '新增地址'">
      <input v-model="form.name" class="field" placeholder="收货人姓名" />
      <input v-model="form.phone" class="field" placeholder="手机号" maxlength="11" />
      <input v-model="form.region" class="field" placeholder="省市区，如：浙江省杭州市余杭区" />
      <input v-model="form.detail" class="field" placeholder="详细地址，如：五常街道 111 号" />
      <label class="muted" style="display: block; margin-bottom: 10px">
        <input v-model="form.is_default" type="checkbox" /> 设为默认地址
      </label>
      <button class="btn" @click="save">保存</button>
    </Sheet>
  </div>
</template>
