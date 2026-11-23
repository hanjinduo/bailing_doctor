<script setup>
defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue'])
const close = () => emit('update:modelValue', false)
</script>

<template>
  <div v-if="modelValue" class="mask" @click.self="close">
    <div class="sheet">
      <h4 v-if="title">{{ title }}</h4>
      <slot />
    </div>
  </div>
</template>
