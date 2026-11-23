<script setup>
import { ref, onMounted } from 'vue'
import { showToast, showConfirmDialog } from 'vant'
import { get, del, postForm, getBlob } from '@/api'
import TopBar from '@/components/TopBar.vue'

const records = ref([])
const note = ref('')
const file = ref(null)
const PAGE = 20
const total = ref(0)
const hasMore = ref(false)
const loadingMore = ref(false)

const load = async () => {
  const j = await get('/records', { limit: PAGE, offset: 0 })
  records.value = j.records || []
  total.value = j.total || 0
  hasMore.value = !!j.has_more
}

const loadMore = async () => {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  const j = await get('/records', { limit: PAGE, offset: records.value.length })
  records.value = records.value.concat(j.records || [])
  total.value = j.total || total.value
  hasMore.value = !!j.has_more
  loadingMore.value = false
}

const pickFile = (e) => {
  file.value = e.target.files[0] || null
}

const upload = async () => {
  if (!file.value) return showToast('请选择文件')
  const fd = new FormData()
  fd.append('file', file.value)
  fd.append('note', note.value || '')
  const j = await postForm('/record/upload', fd)
  if (j.ok) {
    showToast('上传成功')
    note.value = ''
    file.value = null
    load()
  }
}

const openFile = async (r) => {
  const blob = await getBlob('/record/file/' + r.id)
  window.open(URL.createObjectURL(blob), '_blank')
}

const remove = async (r) => {
  await showConfirmDialog({ title: '删除病历', message: '确认删除该病历文件？' })
  const j = await del('/record/' + r.id)
  if (j.ok) {
    showToast('已删除')
    load()
  }
}

onMounted(load)
</script>

<template>
  <div>
    <TopBar title="健康档案" />
    <div class="page">
      <div class="card">
        <div v-for="r in records" :key="r.id" class="item">
          <div class="em">📄</div>
          <div class="bd">
            <div class="tt">{{ r.name }}</div>
            <div class="ds">{{ r.note || '无备注' }}</div>
            <div class="muted">{{ (r.created || '').slice(0, 16) }}</div>
          </div>
          <div style="text-align: right">
            <button class="btn btn-sm btn-line" @click="openFile(r)">查看</button>
            <div style="height: 6px"></div>
            <button class="btn btn-sm btn-red" @click="remove(r)">删除</button>
          </div>
        </div>
        <div v-if="!records.length" class="empty">暂无病历资料，点击下方上传</div>
        <div v-if="records.length" class="more">
          <button v-if="hasMore" class="btn btn-line" :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? '加载中…' : '加载更多' }}
          </button>
          <div v-else class="muted">没有更多了</div>
        </div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 8px">上传病历 / 检查报告</div>
        <input v-model="note" class="field" placeholder="备注，如：2026 年体检报告" />
        <input type="file" class="field" style="padding: 9px" @change="pickFile" />
        <button class="btn" @click="upload">上传</button>
        <div class="muted" style="margin-top: 8px">支持图片、PDF 等格式，仅本人可见</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.more {
  text-align: center;
  padding: 10px 0;
}
</style>
