<script setup lang="ts">
import { tone } from '../services/format'
defineProps<{status:string}>()
</script>
<template><span class="status-badge" :class="tone(status)"><span class="status-dot"/>{{status}}</span></template>
