import { Notify } from 'quasar'
import { api } from './api'
import { apiBase } from './connection'
import { tabletAlarm,isTablet,type AlarmMessage } from './tabletAlarm'
let connection:WebSocket|null=null
let deviceId:number|null=null
let generation=0
let pending:Promise<string>|null=null
let stopNative:Promise<unknown>=Promise.resolve()
let listenersReady=false,nativeActive=false
let retry:ReturnType<typeof setTimeout>|undefined
let incidentHandler:(id:string)=>void=()=>{}
const status=(detail:string)=>window.dispatchEvent(new CustomEvent('cronos:push-status',{detail}))
const connected='Notifications connected. Live alerts are enabled while the app is open.'
function present(notification:AlarmMessage){
 window.dispatchEvent(new Event('cronos:refresh'))
 Notify.create({message:notification.title,color:notification.kind==='recovery'?'positive':'warning',timeout:8000,
  actions:notification.incident_id?[{label:'View incident',handler:()=>incidentHandler(notification.incident_id)}]:[]})
}
async function nativeListeners(){
 if(listenersReady)return
 await tabletAlarm.addListener('notification',message=>{if(nativeActive)present(message)})
 await tabletAlarm.addListener('state',({state})=>status(state==='connected'?'Tablet monitoring connected. Background alarms are active.':state==='stopped'?'Tablet monitoring stopped. Register this device to restart.':'Tablet monitoring reconnecting. Alerts need a live network connection.'))
 await tabletAlarm.addListener('openIncident',({id})=>incidentHandler(id))
 listenersReady=true
}
function socketUrl(path:string){
 const base=new URL(apiBase(),window.location.href)
 const url=new URL(path,base)
 url.protocol=base.protocol==='https:'?'wss:':'ws:'
 return url.toString()
}
export function disconnectPush(){
 nativeActive=false;generation++;clearTimeout(retry);connection?.close();connection=null;pending=null;deviceId=null
 if(isTablet)stopNative=stopNative.then(()=>tabletAlarm.stop()).catch(()=>{})
}
export async function registerPush(onIncident:(id:string)=>void):Promise<string>{
 incidentHandler=onIncident
 if(pending)return pending
 if(connection?.readyState===WebSocket.OPEN)return connected
 disconnectPush()
 const current=generation
 const work=(async()=>{
  if(isTablet){await stopNative;await tabletAlarm.enable();await nativeListeners()}
  const config=await api<{configured:boolean;websocket_path:string;user_id:number}>('/realtime/config')
  if(!config.configured)throw new Error('Live notifications are not configured on the backend.')
  const pref=await api<{push_enabled:boolean}>('/notification-preferences')
  if(!pref.push_enabled)throw new Error('Enable live notifications first.')
  const storageKey=`cronos.notification.device.${config.user_id}`
  let token=localStorage.getItem(storageKey)||localStorage.getItem(`cronos.pusher.device.${config.user_id}`)
  if(!token)token=`cronos:${crypto.randomUUID()}`
  localStorage.setItem(storageKey,token)
  const device=await api<{id:number;channel:string}>('/devices',{method:'POST',body:JSON.stringify({token,label:isTablet?'Cronos Android':'Cronos browser'})})
  if(current!==generation)throw new Error('Notification connection cancelled.')
  deviceId=device.id
  const websocket=socketUrl(config.websocket_path)
  if(isTablet){
   nativeActive=true
   await tabletAlarm.start({api:apiBase(),token,websocket,channel:device.channel})
   for(let i=0;i<30;i++){
    if(current!==generation)throw new Error('Notification connection cancelled.')
    if((await tabletAlarm.status()).state==='connected')return 'Tablet monitoring connected. Background alarms are active.'
    await new Promise(resolve=>setTimeout(resolve,500))
   }
   throw new Error('Tablet monitoring could not connect. Check your network and register this device again.')
  }
  let attempts=0
  const seen=new Set<number>()
  return await new Promise<string>((resolve,reject)=>{
   let ready=false
   const timeout=setTimeout(()=>reject(new Error('Notification connection timed out. Check your network and try again.')),15000)
   const connect=()=>{
    if(current!==generation)return
    const socket=new WebSocket(websocket);connection=socket
    socket.onopen=()=>{if(current===generation)socket.send(JSON.stringify({type:'authenticate',token}));else socket.close()}
    socket.onmessage=event=>{
     if(current!==generation||connection!==socket)return
     let message:any;try{message=JSON.parse(event.data)}catch{return}
     if(message.type==='ready'){ready=true;attempts=0;clearTimeout(timeout);status(connected);resolve(connected)}
     else if(message.type==='ping')socket.send(JSON.stringify({type:'pong'}))
     else if(message.type==='notification'&&!seen.has(message.id)){
      seen.add(message.id);if(seen.size>100)seen.delete(seen.values().next().value!)
      present(message)
     }
    }
    socket.onclose=event=>{
     if(current!==generation||connection!==socket)return
     connection=null
     if([4400,4403].includes(event.code)){
      clearTimeout(timeout);status('Notification access ended. Register this device again.')
      if(!ready)reject(new Error('Notification authorization failed. Register this device again.'))
      return
     }
     status('Notifications disconnected. Reconnecting when the network is available.')
     retry=setTimeout(connect,Math.min(30000,1000*2**Math.min(attempts++,5)))
    }
    socket.onerror=()=>{/* onclose owns reconnect and user-facing status */}
   }
   connect()
  })
 })()
 pending=work
 try{return await work}catch(e){if(current===generation)disconnectPush();throw e}finally{if(pending===work)pending=null}
}
export async function unregisterPush(){const id=deviceId;disconnectPush();if(id)await api(`/devices/${id}`,{method:'DELETE'})}
export function disconnectDevice(id:number){if(id===deviceId)disconnectPush()}
