package ph.cronos.monitor;

import android.Manifest;
import android.content.*;
import android.os.Build;
import android.os.PowerManager;
import android.net.Uri;
import android.provider.Settings;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;
import com.getcapacitor.*;
import com.getcapacitor.annotation.*;
import java.net.URI;
import org.json.JSONObject;

@CapacitorPlugin(name="TabletAlarm",permissions={@Permission(alias="notifications",strings={Manifest.permission.POST_NOTIFICATIONS})})
public class TabletAlarmPlugin extends Plugin {
    private final BroadcastReceiver events=new BroadcastReceiver(){
        @Override public void onReceive(Context context,Intent intent){
            try{
                if(intent.hasExtra("notification"))notifyListeners("notification",new JSObject(intent.getStringExtra("notification")));
                if(intent.hasExtra("state"))notifyListeners("state",new JSObject().put("state",intent.getStringExtra("state")));
            }catch(Exception ignored){}
        }
    };
    @Override public void load(){
        AlarmNotifications.channels(getContext());
        ContextCompat.registerReceiver(getContext(),events,new IntentFilter(TabletMonitorService.EVENT),ContextCompat.RECEIVER_NOT_EXPORTED);
    }
    static void validateApi(String api,boolean debug) throws Exception {
        URI uri=new URI(api);
        boolean loopback="127.0.0.1".equals(uri.getHost())||"localhost".equals(uri.getHost());
        if(uri.getUserInfo()!=null||uri.getQuery()!=null||uri.getFragment()!=null||uri.getHost()==null||!uri.getPath().endsWith("/api/v1")
            ||!("https".equals(uri.getScheme())||(debug&&loopback&&"http".equals(uri.getScheme()))))throw new IllegalArgumentException("Use an HTTPS Cronos API address");
    }
    static void validateConnection(JSONObject config,boolean debug) throws Exception {
        validateApi(config.getString("api"),debug);
        URI api=new URI(config.getString("api")), socket=new URI(config.getString("websocket"));
        String expected="https".equals(api.getScheme())?"wss":"ws";
        if(!expected.equals(socket.getScheme())||!api.getAuthority().equals(socket.getAuthority())
            ||!"/api/v1/realtime/ws".equals(socket.getPath())||socket.getQuery()!=null||socket.getFragment()!=null||socket.getUserInfo()!=null)
            throw new IllegalArgumentException("Use the authenticated Cronos notification endpoint");
    }
    @PluginMethod public void enable(PluginCall call){
        if(Build.VERSION.SDK_INT>=33&&getPermissionState("notifications")!=PermissionState.GRANTED){requestPermissionForAlias("notifications",call,"permissionResult");return;}
        permissionResult(call);
    }
    @PermissionCallback private void permissionResult(PluginCall call){
        if(!NotificationManagerCompat.from(getContext()).areNotificationsEnabled()){call.reject("Allow Cronos notifications in Android settings to enable tablet alarms.");return;}
        AlarmNotifications.channels(getContext());call.resolve();
    }
    @PluginMethod public void start(PluginCall call){
        try{
            if(!NotificationManagerCompat.from(getContext()).areNotificationsEnabled())throw new IllegalStateException("Allow Cronos notifications first.");
            JSONObject config=new JSONObject();
            for(String field:new String[]{"api","token","websocket","channel"}){
                String value=call.getString(field);if(value==null||value.isEmpty())throw new IllegalArgumentException("Missing monitoring configuration");config.put(field,value);
            }
            validateConnection(config,(getContext().getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE)!=0);MonitorCredentials.save(getContext(),config);
            ContextCompat.startForegroundService(getContext(),new Intent(getContext(),TabletMonitorService.class).setAction("START"));
            call.resolve();
        }catch(Exception ignored){call.reject("Cannot start tablet monitoring. Allow notifications and check the API address.");}
    }
    @PluginMethod public void stop(PluginCall call){
        MonitorCredentials.clear(getContext());getContext().stopService(new Intent(getContext(),TabletMonitorService.class));
        AlarmNotifications.silence(getContext());TabletMonitorService.state="stopped";call.resolve();
    }
    @PluginMethod public void status(PluginCall call){call.resolve(new JSObject().put("state",TabletMonitorService.state));}
    @PluginMethod public void test(PluginCall call){
        if(!NotificationManagerCompat.from(getContext()).areNotificationsEnabled()){call.reject("Allow Cronos notifications first.");return;}
        AlarmNotifications.show(getContext(),"Cronos tablet alarm test","test","");call.resolve();
    }
    @PluginMethod public void silence(PluginCall call){AlarmNotifications.silence(getContext());call.resolve();}
    @PluginMethod public void batteryStatus(PluginCall call){
        PowerManager power=(PowerManager)getContext().getSystemService(Context.POWER_SERVICE);
        call.resolve(new JSObject().put("unrestricted",power.isIgnoringBatteryOptimizations(getContext().getPackageName())));
    }
    @PluginMethod public void allowBackgroundAlarms(PluginCall call){
        try{
            PowerManager power=(PowerManager)getContext().getSystemService(Context.POWER_SERVICE);
            if(!power.isIgnoringBatteryOptimizations(getContext().getPackageName())){
                Intent intent=new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,Uri.parse("package:"+getContext().getPackageName()));
                getActivity().startActivity(intent);
            }
            call.resolve();
        }catch(Exception ignored){call.reject("Open Android battery settings and allow unrestricted battery use for Cronos.");}
    }
    @PluginMethod public void settings(PluginCall call){
        Intent intent=new Intent(Build.VERSION.SDK_INT>=26?Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS:Settings.ACTION_SETTINGS);
        intent.putExtra(Settings.EXTRA_APP_PACKAGE,getContext().getPackageName());intent.putExtra(Settings.EXTRA_CHANNEL_ID,AlarmNotifications.ALARMS);
        getActivity().startActivity(intent);call.resolve();
    }
    private void openIncident(Intent intent){
        String id=intent.getStringExtra("incident_id");
        if(id!=null){intent.removeExtra("incident_id");notifyListeners("openIncident",new JSObject().put("id",id),true);}
    }
    @Override protected void handleOnNewIntent(Intent intent){openIncident(intent);}
    @Override protected void handleOnResume(){openIncident(getActivity().getIntent());}
    @Override protected void handleOnDestroy(){getContext().unregisterReceiver(events);}
}
