"""
MQTT Interface

Handles communication with MQTT brokers.
"""

import time
import json
import logging
import threading

logger = logging.getLogger(__name__)
from PyQt6.QtCore import QObject, pyqtSignal
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

from app.core.interfaces.base_interface import BaseInterface


class MQTTInterface(BaseInterface):
    """Interface for MQTT brokers"""
    
    DISPLAY_NAME = "MQTT"
    DESCRIPTION = "Connect to an MQTT broker"
    ICON = "☁️"
    
    HELP_TEXT = """
    <h3>MQTT Interface</h3>
    <p>Connects to an MQTT broker to receive sensor data.</p>
    <p><b>How to use:</b></p>
    <ol>
        <li>Enter your broker address and port.</li>
        <li>Set a unique Client ID.</li>
        <li>Add sensors with interface type 'MQTT' and set the 'Topic' as the sensor port.</li>
    </ol>
    """
    
    CONFIG_SCHEMA = {
        "broker": {"type": "string", "label": "Broker Address", "default": "localhost"},
        "port": {"type": "number", "label": "Port", "default": 1883},
        "client_id": {"type": "string", "label": "Client ID", "default": "ArtefaktDAQ"},
        "username": {"type": "string", "label": "Username", "default": ""},
        "password": {"type": "string", "label": "Password", "default": ""}
    }

    # Connection lost callback
    on_connection_lost = None
    
    @classmethod
    def get_output_keys(cls):
        """Return a list of available MQTT topics.
        Note: For MQTT, this is dynamic and requires a connection.
        """
        return []

    def get_instance_output_keys(self):
        """Return a list of topics received during the current connection."""
        with self._buffer_lock:
            return sorted(list(self.subscribed_topics))

    def __init__(self, broker="localhost", port=1883, client_id="ArtefaktDAQ", 
                 username=None, password=None, keepalive=60):
        """
        Initialize the MQTT interface
        
        Args:
            broker: MQTT broker address
            port: MQTT broker port
            client_id: MQTT client identifier
            username: Username for authentication
            password: Password for authentication
            keepalive: Keepalive interval in seconds
        """
        super().__init__(name="MQTT")
        self.broker = broker
        self.port = port
        self.client_id = client_id
        self.username = username
        self.password = password
        self.keepalive = keepalive
        
        self.client = None
        self.data_buffer = {}  # Stores latest {topic: value}
        self.subscribed_topics = set()
        self._buffer_lock = threading.Lock()
        
        if not MQTT_AVAILABLE:
            self.error_message = "paho-mqtt library not installed"
            
    def connect(self):
        """
        Connect to the MQTT broker
        
        Returns:
            True if connected successfully, False otherwise
        """
        if not MQTT_AVAILABLE:
            self.error_message = "paho-mqtt library not installed"
            return False

        if self.client:
            self.disconnect()
            
        try:
            # Create MQTT client
            # Using CallbackAPIVersion.VERSION2 for paho-mqtt 2.x compatibility
            try:
                self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, self.client_id)
            except AttributeError:
                # Fallback for older paho-mqtt versions
                self.client = mqtt.Client(self.client_id)
            
            if self.username:
                self.client.username_pw_set(self.username, self.password)
            
            # Set callbacks
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            
            # Connect to broker
            self.client.connect(self.broker, self.port, self.keepalive)
            
            # Start background loop
            self.client.loop_start()
            
            # We don't set self.connected = True here; we wait for _on_connect
            # but for the interface pattern, we might want to wait a bit
            timeout = 5.0
            start_time = time.time()
            while not self.connected and time.time() - start_time < timeout:
                time.sleep(0.1)
                
            if not self.connected:
                self.error_message = "Timed out waiting for MQTT connection"
                self.client.loop_stop()
                return False
                
            return True
            
        except Exception as e:
            err_str = str(e)
            if "refused" in err_str or "10061" in err_str:
                self.error_message = f"Connection refused by {self.broker}:{self.port}. Is the broker running?"
            elif "timed out" in err_str.lower():
                self.error_message = f"Connection to {self.broker} timed out. Check your network settings."
            else:
                self.error_message = f"MQTT error: {err_str}"
            self.connected = False
            return False
            
    def disconnect(self):
        """Disconnect from the MQTT broker"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
        self.connected = False
        self.client = None
        
    def is_connected(self):
        """Check if the interface is connected"""
        return self.connected
        
    def subscribe(self, topic):
        """Subscribe to a topic"""
        if self.client and self.connected:
            self.client.subscribe(topic)
            with self._buffer_lock:
                self.subscribed_topics.add(topic)
            return True
        return False
        
    def unsubscribe(self, topic):
        """Unsubscribe from a topic"""
        if self.client and self.connected:
            self.client.unsubscribe(topic)
            with self._buffer_lock:
                self.subscribed_topics.discard(topic)
            return True
        return False
        
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """Callback for when the client connects to the broker"""
        if rc == 0:
            self.connected = True
            self.error_message = ""
            # Resubscribe to topics if reconnecting
            with self._buffer_lock:
                topics = list(self.subscribed_topics)
            for topic in topics:
                self.client.subscribe(topic)
        else:
            self.connected = False
            self.error_message = f"MQTT connection failed with result code {rc}"
            
    def _on_disconnect(self, client, userdata, disconnect_flags, rc, properties=None):
        """Callback for when the client disconnects from the broker"""
        self.connected = False
        if rc != 0:
            self.error_message = f"Unexpected MQTT disconnection (rc={rc})"
            if self.on_connection_lost:
                self.on_connection_lost(self.error_message)
                
    def _store_message_value(self, topic, value):
        """Store a parsed payload, flattening JSON dicts into topic/key scalars."""
        if isinstance(value, dict):
            stored = False
            for k, v in value.items():
                if isinstance(v, (int, float, str, bool)):
                    self.data_buffer[f"{topic}/{k}"] = v
                    stored = True
                elif isinstance(v, list):
                    self.data_buffer[f"{topic}/{k}"] = json.dumps(v)
                    stored = True
            if not stored:
                logger.debug("MQTT: skipped non-scalar JSON dict on topic %s", topic)
            return

        self.data_buffer[topic] = value

    def _on_message(self, client, userdata, msg):
        """Callback for when a message is received"""
        topic = msg.topic
        payload = msg.payload.decode('utf-8', errors='replace')
        
        # Try to parse as JSON if it looks like it
        try:
            if payload.startswith('{') or payload.startswith('['):
                value = json.loads(payload)
            else:
                # Try to convert to float/int
                try:
                    value = float(payload)
                    if value == int(value):
                        value = int(value)
                except ValueError:
                    value = payload
        except Exception:
            value = payload
            
        with self._buffer_lock:
            self._store_message_value(topic, value)
            
    def read_data(self):
        """
        Read data from the buffer
        
        Returns:
            Dictionary with {topic: value} pairs or None if no data
        """
        with self._buffer_lock:
            if not self.data_buffer:
                return None
            data = self.data_buffer.copy()
            self.data_buffer.clear()
            return data
            
    def write_data(self, data):
        """
        Publish data to the broker
        
        Args:
            data: Tuple or list of (topic, payload)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected() or not self.client:
            return False
            
        try:
            if isinstance(data, (tuple, list)) and len(data) == 2:
                topic, payload = data
                self.client.publish(topic, payload)
                return True
            return False
        except Exception as e:
            self.error_message = f"Failed to publish MQTT message: {e}"
            return False
            
    def update_settings(self, settings):
        """Update MQTT settings at runtime (limited)"""
        if "broker" in settings or "port" in settings:
            # Requires reconnect
            pass
        return True
