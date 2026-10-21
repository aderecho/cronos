<script setup lang="ts">
import {Server as ServerIcon,ChevronRight} from 'lucide-vue-next'
import StatusBadge from './StatusBadge.vue'
import MetricBar from './MetricBar.vue'
import {percent,relative} from '../services/format'
import type {Server} from '../types'
defineProps<{servers:Server[]}>()
defineEmits<{select:[server:Server]}>()
function displayState(s:Server){return ['Unreachable','Endpoint unreachable','Maintenance'].includes(s.availability)?s.availability:s.health_state}
</script>
<template><div class="server-table"><div class="table-head server-grid"><span>Server</span><span>Health</span><span>Resources</span><span>Status</span><span/></div><button v-for="s in servers" :key="s.id" class="server-row server-grid" @click="$emit('select',s)"><div class="identity"><ServerIcon :size="21"/><div><strong>{{s.name}}</strong><small>{{s.hostname}} <span>·</span> {{s.environment}}</small></div></div><div class="health-cell"><b>{{s.fresh?percent(s.last_score):'—'}}</b><div v-if="s.fresh&&s.last_score!==null" class="health-track"><i :class="s.last_score<50?'bad':s.last_score<80?'warn':''" :style="{width:`${s.last_score}%`}"/></div><small v-else>{{s.last_seen?'Stale · '+relative(s.last_seen):'Awaiting agent'}}</small></div><div class="resource-cell"><MetricBar label="CPU" :value="s.latest_metrics.cpu" :stale="!s.fresh"/><MetricBar label="RAM" :value="s.latest_metrics.ram" :stale="!s.fresh"/><MetricBar label="Disk" :value="s.latest_metrics.filesystems?.[0]?.used_percent" :stale="!s.fresh"/></div><div class="state-cell"><StatusBadge :status="displayState(s)"/></div><ChevronRight class="row-chevron" :size="17"/></button><div v-if="!servers.length" class="empty"><ServerIcon :size="30"/><b>No servers found</b><span>Add a server or change your search.</span></div></div></template>
