package ph.cronos.monitor;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override public void onCreate(Bundle savedInstanceState) {
        registerPlugin(TabletAlarmPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
