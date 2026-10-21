<script setup lang="ts">
import { computed } from 'vue'
import { Line } from 'vue-chartjs'
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend } from 'chart.js'
ChartJS.register(CategoryScale,LinearScale,PointElement,LineElement,Tooltip,Legend)
const props=defineProps<{points:{time:string;[key:string]:unknown}[];mode?:'latency'}>()
const data=computed(()=>({labels:props.points.map(p=>new Date(p.time).toLocaleTimeString('en-PH',{hour:'2-digit',minute:'2-digit',timeZone:'Asia/Manila'})),datasets:props.mode==='latency'?[{label:'Response time (ms)',data:props.points.map(p=>p.latency_ms as number|null),borderColor:'#009e70',pointRadius:2,tension:.3}]:[{label:'CPU avg',data:props.points.map(p=>p.cpu as number|null),borderColor:'#009e70',pointRadius:0,tension:.3},{label:'CPU max',data:props.points.map(p=>p.cpu_max as number|null),borderColor:'#e9a229',borderDash:[4,4],pointRadius:0},{label:'RAM avg',data:props.points.map(p=>p.ram as number|null),borderColor:'#6483d8',pointRadius:0,tension:.3},{label:'Health min',data:props.points.map(p=>p.score_min as number|null),borderColor:'#e34c61',pointRadius:0,tension:.3}]}))
const options=computed(()=>({responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom' as const,labels:{usePointStyle:true,boxWidth:6,padding:18}}},scales:{y:{min:0,...(!props.mode?{max:100}:{}),grid:{color:'#edf1f5'}},x:{grid:{display:false},ticks:{maxTicksLimit:6}}}}))
</script>
<template><div v-if="points.length" class="chart-container"><Line :data="data" :options="options"/></div><div v-else class="empty compact">No samples in this period.</div></template>
