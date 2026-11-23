<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import { get, post } from '@/api'
import TopBar from '@/components/TopBar.vue'

const route = useRoute()
const router = useRouter()
const depts = ref([])
const vip = ref({ vip: false, quick_free_left: 0 })
const symptom = ref(route.query.symptom || '')
const deptId = ref(0)
const deptName = ref('')
const mode = ref(route.query.mode || 'text')
const submitting = ref(false)

const doctorId = Number(route.query.doctorid || 0)
const doctorName = route.query.doctor || ''
const doctorDept = route.query.dept || ''

const modes = [
  { key: 'text', icon: '💬', name: '图文问诊', fee: '¥50', desc: '随时沟通，医生文字回复' },
  { key: 'voice', icon: '📞', name: '语音问诊', fee: '¥50', desc: '语音通话 10 分钟' },
  { key: 'video', icon: '🎥', name: '视频问诊', fee: '¥150', desc: '面对面视频问诊' }
]

onMounted(async () => {
  const [d, v] = await Promise.all([get('/depts'), get('/vip')])
  depts.value = d.depts || []
  vip.value = { vip: !!v.vip, quick_free_left: v.quick_free_left || 0 }
})

const pickDept = (d) => {
  deptId.value = d.id
  deptName.value = d.name
}

const start = async () => {
  if (symptom.value.trim().length < 5) return showToast('请至少描述 5 个字的症状')
  if (submitting.value) return
  submitting.value = true
  try {
    const body = { symptom: symptom.value.trim(), mode: mode.value }
    if (doctorId) body.doctor_id = doctorId
    else if (deptName.value) body.dept = deptName.value
    const j = await post('/chat/start', body)
    if (j.ok) router.push('/paychat/' + j.chat_id)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div>
    <TopBar title="极速问诊" />
    <div class="page">
      <div
        v-if="vip.vip && vip.quick_free_left > 0 && !doctorId"
        class="card"
        style="background: #f0fdfa; border: 1px solid #99f6e4"
      >
        <div class="between">
          <span class="b">👑 会员专享</span>
          <span class="muted">本月还可免费极速问诊 {{ vip.quick_free_left }} 次</span>
        </div>
        <div class="muted">选择「图文问诊」且不指定医生时自动免单</div>
      </div>

      <div v-if="doctorName" class="card">
        <div class="hd">
          <div class="avatar">🩺</div>
          <div>
            <div class="b">{{ doctorName }}</div>
            <div class="muted">{{ doctorDept }}</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 8px">选择科室</div>
        <div class="chips">
          <div
            v-for="d in depts"
            :key="d.id"
            class="chip"
            :class="{ on: deptId === d.id }"
            @click="pickDept(d)"
          >
            {{ d.icon }} {{ d.name }}
          </div>
        </div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 8px">描述症状</div>
        <textarea v-model="symptom" class="field" placeholder="请描述主要不适、持续时间、是否用药等，至少 5 个字"></textarea>
        <div class="muted">医生将根据描述给出初步建议，必要时请线下就诊</div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 8px">问诊方式</div>
        <div v-for="m in modes" :key="m.key" class="opt" :class="{ on: mode === m.key }" @click="mode = m.key">
          <div class="between">
            <div>
              <b>{{ m.icon }} {{ m.name }}</b>
              <div class="muted">{{ m.desc }}</div>
            </div>
            <div class="price">{{ m.fee }}</div>
          </div>
        </div>
      </div>

      <button class="btn" :disabled="submitting" @click="start">提交并支付</button>
      <div class="muted" style="text-align: center; margin-top: 10px">支付后医生将尽快接诊，未接诊可取消</div>
    </div>
  </div>
</template>
