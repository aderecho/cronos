package ph.cronos.monitor;

import android.app.Service;
import android.content.Intent;
import android.os.*;
import androidx.core.app.NotificationManagerCompat;
import java.net.URI;
import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;
import org.json.JSONObject;

/** Native background connection to Cronos's authenticated gateway, never to the broker. */
public class TabletMonitorService extends Service {
    static final String EVENT="ph.cronos.monitor.MONITOR_EVENT";
    static volatile String state="stopped";
    private WebSocketClient socket;
    private JSONObject config;
    private PowerManager.WakeLock connectionWakeLock;
    private int generation=0, attempts=0;
    private String lastError="none";
    private int lastCloseCode=0;
    private volatile boolean destroyed=false;
    private HandlerThread monitorThread;
    private Handler main;
    private final Runnable reconnect=()->{if(!destroyed)connect();};
    private final Runnable authTimeout=()->{if(!destroyed&&socket!=null&&!"connected".equals(state))socket.close();};

    // Bounded lease renewed only while the user-visible monitoring service is running.
    private final Runnable keepConnectionAwake=new Runnable(){
        @Override public void run(){
            if(destroyed)return;
            if(connectionWakeLock==null){
                PowerManager power=(PowerManager)getSystemService(POWER_SERVICE);
                connectionWakeLock=power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"Cronos:alarmConnection");
                connectionWakeLock.setReferenceCounted(false);
            }
            connectionWakeLock.acquire(10*60*1000L);
            main.postDelayed(this,9*60*1000L);
        }
    };

    @Override public void onCreate(){
        super.onCreate();
        monitorThread=new HandlerThread("CronosAlarmMonitor");
        monitorThread.start();
        main=new Handler(monitorThread.getLooper());
    }
    @Override public IBinder onBind(Intent intent){return null;}
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        String action=intent==null?"START":intent.getAction();
        if("SILENCE".equals(action)){AlarmNotifications.silence(this);if(socket==null){stopSelf();return START_NOT_STICKY;}return START_STICKY;}
        if("STOP".equals(action)){MonitorCredentials.clear(this);AlarmNotifications.silence(this);stopSelf();return START_NOT_STICKY;}
        startForeground(AlarmNotifications.MONITOR_ID,AlarmNotifications.monitoring(this,"Connecting to server alerts…"));
        if(socket!=null)return START_STICKY;
        try {
            config=MonitorCredentials.load(this);
            if(config==null){stopSelf();return START_NOT_STICKY;}
            // Upgrade the stored endpoint after installing over the previous provider build.
            if(!config.has("websocket"))config.put("websocket",config.getString("api").replaceFirst("^http","ws")+"/realtime/ws");
            TabletAlarmPlugin.validateConnection(config,(getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE)!=0);
            main.post(keepConnectionAwake);
            main.post(this::connect);
        }catch(Exception ignored){MonitorCredentials.clear(this);stopSelf();return START_NOT_STICKY;}
        return START_STICKY;
    }
    private void connect(){
        if(destroyed)return;
        int current=++generation;
        main.removeCallbacks(authTimeout);
        if(socket!=null)socket.close();
        update("reconnecting");
        try {
            socket=new WebSocketClient(new URI(config.getString("websocket"))){
                @Override public void onOpen(ServerHandshake handshake){
                    if(current!=generation||destroyed){close();return;}
                    try{send(new JSONObject().put("type","authenticate").put("token",config.getString("token")).toString());}
                    catch(Exception ignored){close();}
                }
                @Override public void onMessage(String text){
                    if(current!=generation||destroyed)return;
                    try{
                        if(text.length()>4096){close(4400);return;}
                        JSONObject event=new JSONObject(text);
                        String type=event.optString("type","");
                        if("ping".equals(type)){send("{\"type\":\"pong\"}");return;}
                        main.post(()->{
                            if(current!=generation||destroyed)return;
                            if("ready".equals(type)){attempts=0;main.removeCallbacks(authTimeout);main.removeCallbacks(reconnect);update("connected");}
                            else if("notification".equals(type)){try{receive(event);}catch(Exception ignored){update("invalid notification");}}
                        });
                    }catch(Exception ignored){close(4400);}
                }
                @Override public void onClose(int code,String reason,boolean remote){
                    lastCloseCode=code;
                    main.post(()->{
                        if(current!=generation||destroyed)return;
                        main.removeCallbacks(authTimeout);
                        if(code==4403||code==4400){MonitorCredentials.clear(TabletMonitorService.this);AlarmNotifications.silence(TabletMonitorService.this);stopSelf();return;}
                        update("reconnecting");scheduleReconnect();
                    });
                }
                @Override public void onError(Exception error){
                    lastError=error.getClass().getSimpleName();
                    // Never log endpoint, authentication payload, or exception contents.
                    main.post(()->{if(current==generation&&!destroyed)update("reconnecting");});
                }
            };
            socket.setConnectionLostTimeout(30);
            socket.connect();
            main.postDelayed(authTimeout,15000);
        }catch(Exception ignored){scheduleReconnect();}
    }
    private void scheduleReconnect(){
        if(destroyed)return;
        main.removeCallbacks(reconnect);
        main.postDelayed(reconnect,Math.min(30000,1000L*(1L<<Math.min(attempts++,5))));
    }
    private void receive(JSONObject notification) throws Exception {
        long id=notification.getLong("id");
        android.content.SharedPreferences prefs=getSharedPreferences("cronos-alarm-received",0);
        String key="seen-"+config.getString("channel");
        org.json.JSONArray old=new org.json.JSONArray(prefs.getString(key,"[]"));
        for(int i=0;i<old.length();i++)if(old.getLong(i)==id)return;
        org.json.JSONArray seen=new org.json.JSONArray();
        for(int i=Math.max(0,old.length()-99);i<old.length();i++)seen.put(old.getLong(i));
        seen.put(id);prefs.edit().putString(key,seen.toString()).apply();
        AlarmNotifications.show(this,notification.optString("title","Server incident"),notification.optString("kind","initial"),notification.optString("incident_id",""));
        sendBroadcast(new Intent(EVENT).setPackage(getPackageName()).putExtra("notification",notification.toString()));
    }
    private void update(String next){
        if(destroyed)return;
        state=next;
        PowerManager power=(PowerManager)getSystemService(POWER_SERVICE);
        boolean allowed=power.isIgnoringBatteryOptimizations(getPackageName());
        String text="connected".equals(next)?(allowed?"Listening for alarms, including with the screen locked":"Allow background alarms in Settings for idle delivery"):"Reconnecting — alerts need a live network connection";
        try{NotificationManagerCompat.from(this).notify(AlarmNotifications.MONITOR_ID,AlarmNotifications.monitoring(this,text));}catch(SecurityException ignored){}
        sendBroadcast(new Intent(EVENT).setPackage(getPackageName()).putExtra("state",next));
    }
    @Override protected void dump(java.io.FileDescriptor fd,java.io.PrintWriter writer,String[] args){
        writer.println("Cronos monitor state="+state+" socket="+(socket==null?"none":socket.getReadyState())+" lastError="+lastError+" closeCode="+lastCloseCode);
        writer.println("Cronos wakeLockHeld="+(connectionWakeLock!=null&&connectionWakeLock.isHeld()));
        if(config!=null)writer.println("Cronos gateway="+config.optString("websocket","unset"));
    }
    @Override public void onDestroy(){
        destroyed=true;generation++;main.removeCallbacksAndMessages(null);
        if(connectionWakeLock!=null&&connectionWakeLock.isHeld())connectionWakeLock.release();
        if(socket!=null){socket.close();socket=null;}
        state="stopped";
        sendBroadcast(new Intent(EVENT).setPackage(getPackageName()).putExtra("state","stopped"));
        stopForeground(STOP_FOREGROUND_REMOVE);super.onDestroy();
        monitorThread.quitSafely();
    }
}
