package ph.cronos.monitor;

import android.app.*;
import android.content.*;
import android.media.AudioAttributes;
import android.media.RingtoneManager;
import android.os.Build;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;

/** OS-managed alarm audio: respects the tablet's alarm volume and channel settings. */
final class AlarmNotifications {
    static final String ALARMS = "cronos_alarms_v1", RECOVERY = "cronos_recovery_v1", MONITOR = "cronos_monitor_v1";
    static final int ALARM_ID = 7101, MONITOR_ID = 7102;
    static void channels(Context context) {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        NotificationChannel alarm = new NotificationChannel(ALARMS,"Server alarms",NotificationManager.IMPORTANCE_HIGH);
        alarm.setDescription("Audible server incidents and test alarms. Uses alarm volume.");
        alarm.setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM),new AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_ALARM).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
        alarm.enableVibration(true);
        alarm.setVibrationPattern(new long[]{0,700,400,700});
        manager.createNotificationChannel(alarm);
        manager.createNotificationChannel(new NotificationChannel(RECOVERY,"Server recovery",NotificationManager.IMPORTANCE_DEFAULT));
        manager.createNotificationChannel(new NotificationChannel(MONITOR,"Background monitoring",NotificationManager.IMPORTANCE_LOW));
    }
    static PendingIntent open(Context context, String incident) {
        Intent intent = new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP);
        if (incident != null && !incident.isEmpty()) intent.putExtra("incident_id",incident);
        return PendingIntent.getActivity(context,7103,intent,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
    }
    static PendingIntent command(Context context, String action) {
        return PendingIntent.getService(context,action.hashCode(),new Intent(context,TabletMonitorService.class).setAction(action),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
    }
    static void show(Context context,String title,String kind,String incident) {
        channels(context);
        boolean recovery = "recovery".equals(kind);
        NotificationCompat.Builder builder = new NotificationCompat.Builder(context,recovery?RECOVERY:ALARMS)
            .setSmallIcon(R.drawable.ic_notification).setContentTitle(recovery?"Cronos recovery":"Cronos alarm")
            .setContentText(title).setStyle(new NotificationCompat.BigTextStyle().bigText(title))
            .setPriority(NotificationCompat.PRIORITY_MAX).setCategory(recovery?NotificationCompat.CATEGORY_STATUS:NotificationCompat.CATEGORY_ALARM)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE).setContentIntent(open(context,incident)).setAutoCancel(true)
            .setTimeoutAfter(30000);
        if (!recovery) builder.addAction(0,"Stop alarm",command(context,"SILENCE"));
        if (Build.VERSION.SDK_INT < 26 && !recovery) builder.setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM))
            .setVibrate(new long[]{0,700,400,700});
        Notification notification = builder.build();
        if (!recovery) notification.flags |= Notification.FLAG_INSISTENT;
        NotificationManagerCompat.from(context).notify(recovery?7104:ALARM_ID,notification);
    }
    static Notification monitoring(Context context,String text) {
        channels(context);
        return new NotificationCompat.Builder(context,MONITOR).setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("Cronos monitoring active").setContentText(text).setOngoing(true).setOnlyAlertOnce(true)
            .setContentIntent(open(context,null)).addAction(0,"Stop monitoring",command(context,"STOP")).build();
    }
    static void silence(Context context) {NotificationManagerCompat.from(context).cancel(ALARM_ID);}
}
