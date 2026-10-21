import type { CapacitorConfig } from '@capacitor/cli'
const developmentApi=process.env.CRONOS_ANDROID_DEV_API==='true'
const config: CapacitorConfig = {appId:'ph.cronos.monitor',appName:'Cronos',loggingBehavior:'none',webDir:'dist',android:{allowMixedContent:developmentApi},plugins:{SystemBars:{insetsHandling:'native',style:'LIGHT'}}}
export default config
