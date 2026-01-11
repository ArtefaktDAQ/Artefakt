from app.core.interfaces.outbound_interface import BaseOutboundInterface
import json
import os
import socket
import time

class OutboundDemoPlugin(BaseOutboundInterface):
    """
    Demo Outbound Plugin showing multiple modes of operation.
    """
    DISPLAY_NAME = "Outbound Device"
    DESCRIPTION = "Broadcasts data via UDP, JSONL, or basic alarms. Note: Only active during a data collection run."
    ICON = "📡"
    
    HELP_TEXT = """
    <h3>Outbound Device Plugin</h3>
    <p>This plugin demonstrates three ways to push DAQ data to external systems. 
    <b>Important:</b> Outbound plugins are only active during an <b>active data collection run</b> 
    (when the 'Start' button has been clicked and a run is in progress).</p>
    <ul>
        <li><b>UDP Broadcast:</b> Sends every data snapshot as a JSON packet to a target IP/Port.</li>
        <li><b>JSON Logger:</b> Appends data to a <code>outbound_log.jsonl</code> file in the current run directory.</li>
        <li><b>Simple Alarm:</b> Monitors a specific sensor and prints an alert to the console if it exceeds a threshold.</li>
    </ul>
    <h4>Internal Sensor Names</h4>
    <p>When using the <b>Simple Alarm</b>, you must use the <b>exact internal name</b> of the sensor. 
    Some sensors (especially LabJack) have complex names like <code>labjack_AIN2_EF_READ_A</code>.</p>
    <p><b>How to find the correct name:</b></p>
    <ol>
        <li>Start a short test run.</li>
        <li>Open the <b>Help</b> tab in this window and check the <b>Available Live Sensor Keys</b> list at the bottom.</li>
        <li>Alternatively, check the header of the <b>CSV file</b> generated for the run.</li>
    </ol>
    """
    
    # CONFIG_SCHEMA defines the fields. We removed auto_start as it's handled by the General tab.
    CONFIG_SCHEMA = {
        "mode": {
            "type": "list",
            "label": "Operating Mode",
            "options": ["UDP Broadcast", "JSON Logger", "Simple Alarm"],
            "default": "UDP Broadcast"
        },
        "target_ip": {
            "type": "string",
            "label": "Target IP (UDP)",
            "default": "127.0.0.1"
        },
        "port": {
            "type": "number",
            "label": "Port (UDP)",
            "default": 5005
        },
        "alarm_sensor": {
            "type": "string",
            "label": "Alarm Sensor Name",
            "default": "Voltage"
        },
        "alarm_threshold": {
            "type": "number",
            "label": "Alarm Threshold",
            "default": 240.0
        }
    }

    def __init__(self, name="Outbound Device", auto_connect=False, mode="UDP Broadcast", target_ip="127.0.0.1", port=5005, **kwargs):
        super().__init__(name=name)
        self.auto_connect = auto_connect
        self.mode = mode
        self.target_ip = target_ip
        self.port = int(port)
        self.alarm_sensor = kwargs.get("alarm_sensor", "Voltage")
        
        # Robust threshold parsing
        threshold_val = kwargs.get("alarm_threshold", 240.0)
        if isinstance(threshold_val, str):
            threshold_val = threshold_val.replace(',', '.')
        try:
            self.alarm_threshold = float(threshold_val)
        except (ValueError, TypeError):
            self.alarm_threshold = 240.0
        
        self.socket = None
        self.log_file = None

    def set_run_directory(self, path):
        """React to run folder changes."""
        super().set_run_directory(path)
        
        # If we are in JSON Logger mode and connected, we might want to 
        # move the log file to the new run directory.
        if self.mode == "JSON Logger" and self.connected:
            # Re-connect to update the log file location
            self.disconnect()
            self.connect()

    def connect(self):
        """Initialize resources based on mode."""
        print(f"Outbound Device: Connecting in mode {self.mode}...")
        try:
            if self.mode == "UDP Broadcast":
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            elif self.mode == "JSON Logger":
                # Use run directory if available, otherwise project root
                base_path = self.run_directory if self.run_directory else os.getcwd()
                log_path = os.path.join(base_path, "outbound_log.jsonl")
                self.log_file = open(log_path, "a")
                print(f"Outbound Device: Logging to {log_path}")
            
            self.connected = True
            return True
        except Exception as e:
            self.error_message = str(e)
            print(f"Outbound Device Error: {e}")
            return False

    def disconnect(self):
        """Release resources."""
        if self.socket:
            self.socket.close()
            self.socket = None
        if self.log_file:
            self.log_file.close()
            self.log_file = None
        self.connected = False

    def push_data(self, data):
        """Receive data snapshot and process based on mode."""
        if not self.connected:
            return

        # Always include the timestamp
        payload = {"ts": data.get("timestamp"), "data": {}}
        
        # Filter for actual sensor values (ignore automation strings for standard payload)
        for k, v in data.items():
            if k not in ["timestamp", "automation_trigger", "automation_action", "automation_sequence", "automation_image"] and not k.endswith("_timestamp"):
                payload["data"][k] = v

        # Add automation events if present
        trigger = data.get("automation_trigger")
        if trigger:
            payload["event"] = trigger

        # Use stripped mode for comparison
        mode = str(self.mode).strip()

        if mode == "UDP Broadcast":
            self._send_udp(payload)
        elif mode == "JSON Logger":
            self._log_json(payload)
        elif mode == "Simple Alarm":
            self._check_alarm(data)

    def _send_udp(self, payload):
        if self.socket:
            try:
                msg = json.dumps(payload).encode('utf-8')
                self.socket.sendto(msg, (self.target_ip, self.port))
            except Exception: pass

    def _log_json(self, payload):
        if self.log_file:
            try:
                self.log_file.write(json.dumps(payload) + "\n")
                self.log_file.flush()
            except Exception: pass

    def _check_alarm(self, data):
        # 1. Prepare target sensor name (case-insensitive, stripped)
        target = str(self.alarm_sensor).strip().lower()
        if not target: return

        # 2. Find the value in the data (check direct, prefixed, and case-insensitive)
        val = None
        
        # Try direct match first
        if self.alarm_sensor in data:
            val = data[self.alarm_sensor]
        else:
            # Try case-insensitive and prefixed matches
            for key, value in data.items():
                k_lower = str(key).lower()
                # Match direct case-insensitive
                if k_lower == target:
                    val = value
                    break
                # Match prefixed versions (e.g. if target is "AIN2", match "labjack_AIN2")
                for prefix in ["labjack_", "arduino_", "mqtt_", "csv_", "other_serial_"]:
                    if k_lower == f"{prefix}{target}":
                        val = value
                        break
                if val is not None: break

        if val is not None:
            try:
                # 3. Convert to string and handle comma as decimal separator
                clean_val = str(val).replace(',', '.')
                
                # 4. Extract only the numeric part (handles values like "33.66 C")
                import re
                match = re.search(r"([-+]?\d*\.?\d+)", clean_val)
                if match:
                    float_val = float(match.group(1))
                    if float_val >= self.alarm_threshold:
                        print(f"!!! OUTBOUND ALARM: {self.alarm_sensor} is {float_val:.2f} (Threshold: {self.alarm_threshold}) !!!", flush=True)
            except (ValueError, TypeError): pass

    @classmethod
    def get_field_visibility(cls, current_config):
        """
        Returns a dict of {field_name: is_visible} based on current config.
        Used by the UI to hide irrelevant fields.
        """
        mode = current_config.get("mode", "UDP Broadcast")
        return {
            "mode": True,
            "target_ip": mode == "UDP Broadcast",
            "port": mode == "UDP Broadcast",
            "alarm_sensor": mode == "Simple Alarm",
            "alarm_threshold": mode == "Simple Alarm"
        }
