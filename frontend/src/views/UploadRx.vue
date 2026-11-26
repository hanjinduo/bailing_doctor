<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { postForm } from '@/api'
import TopBar from '@/components/TopBar.vue'

const router = useRouter()
const file = ref(null)
const dept = ref('')
const diag = ref('')
const note = ref('')
const busy = ref(false)

const pick = (e) => {
  const f = e.target.files && e.target.files[0]
  if (!f) return
  if (f.size > 5 * 1024 * 1024) {
    showToast('图片不能超过 5MB')
    e.target.value = ''
    return
  }
  file.value = f
}

const submit = async () => {
  if (!file.value) return showToast('请选择处方照片')
  const fd = new FormData()
  fd.append('file', file.value)
  fd.append('dept', dept.value.trim())
  fd.append('diag', diag.value.trim())
  fd.append('note', note.value.trim())
  busy.value = true
  const j = await postForm('/rx/upload', fd)
  busy.value = false
  if (j.ok) {
    showToast(j.msg)
    router.replace('/rx/' + j.rx.id)
  }
}
</script>

<template>
  <div>
    <TopBar title="上传线下处方" />
    <div class="page">
      <div class="card">
        <div class="b" style="margin-bottom: 8px">处方影像</div>
        <label class="picker">
          <input type="file" accept="image/jpeg,image/png,image/webp,application/pdf" @change="pick" />
          <span v-if="!file">＋ 拍照或选择图片 / PDF（≤5MB）</span>
          <span v-else class="picked">{{ file.name }} · {{ (file.size / 1024).toFixed(0) }}KB</span>
        </label>
        <div class="muted" style="margin-top: 8px; line-height: 1.8">
          支持 JPG / PNG / WEBP / PDF。请上传医院开具、含医师签名与用药明细的完整处方。
        </div>
      </div>

      <div class="card">
        <div class="kv"><span>就诊科室</span></div>
        <input v-model="dept" class="ipt" placeholder="如：呼吸内科（选填）" />
        <div class="kv" style="margin-top: 10px"><span>诊断</span></div>
        <input v-model="diag" class="ipt" placeholder="如：急性支气管炎（选填）" />
        <div class="kv" style="margin-top: 10px"><span>备注</span></div>
        <textarea v-model="note" class="ta" placeholder="用药说明、特殊要求等（选填）" />
      </div>

      <button class="btn" :disabled="busy" @click="submit">{{ busy ? '上传中…' : '提交药师审核' }}</button>
      <div class="tip">线下处方同样需执业药师审核，审核通过后可按方购买处方药，且仅能使用一次。</div>
    </div>
  </div>
</template>

<style scoped>
.picker {
  display: block;
  padding: 22px 12px;
  border: 1px dashed var(--line);
  border-radius: 12px;
  text-align: center;
  color: var(--pri);
  font-size: 13px;
  cursor: pointer;
  background: #f8fbfb;
}
.picker input {
  display: none;
}
.picked {
  color: var(--ink);
  font-weight: 600;
}
.ipt,
.ta {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 9px 10px;
  font-size: 13px;
  box-sizing: border-box;
}
.ta {
  height: 70px;
  resize: none;
}
.tip {
  text-align: center;
  font-size: 12px;
  color: var(--gray);
  padding: 8px 0 14px;
  line-height: 1.7;
}
</style>
