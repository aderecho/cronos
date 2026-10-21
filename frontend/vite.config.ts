import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { quasar, transformAssetUrls } from '@quasar/vite-plugin'
export default defineConfig({plugins:[vue({template:{transformAssetUrls}}),quasar()],server:{port:9100,strictPort:true,proxy:{'/api':{target:'http://127.0.0.1:8100',changeOrigin:true,ws:true}}},build:{chunkSizeWarningLimit:700}})
