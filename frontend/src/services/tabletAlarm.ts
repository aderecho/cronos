import { Capacitor,registerPlugin,type PluginListenerHandle } from '@capacitor/core'
export const isTablet=Capacitor.getPlatform()==='android'
export type AlarmMessage={id:number;title:string;incident_id:string;kind:string}
export const tabletAlarm=registerPlugin<{
 enable():Promise<void>
 start(config:{api:string;token:string;websocket:string;channel:string}):Promise<void>
 stop():Promise<void>
 status():Promise<{state:string}>
 test():Promise<void>
 silence():Promise<void>
 settings():Promise<void>
 batteryStatus():Promise<{unrestricted:boolean}>
 allowBackgroundAlarms():Promise<void>
 addListener(event:'notification',listener:(message:AlarmMessage)=>void):Promise<PluginListenerHandle>
 addListener(event:'state',listener:(message:{state:string})=>void):Promise<PluginListenerHandle>
 addListener(event:'openIncident',listener:(message:{id:string})=>void):Promise<PluginListenerHandle>
}>('TabletAlarm')
