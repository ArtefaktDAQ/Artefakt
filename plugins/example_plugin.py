from app.core.interfaces.base_interface import BaseInterface
import random

class ExampleCustomSensor(BaseInterface):
    """
    An example of a custom sensor plugin.
    This demonstrates how a user can add new hardware support 
    without touching the core codebase.

    Mandatory Attributes:
    - DISPLAY_NAME: The name shown in the UI.
    - DESCRIPTION: A short tooltip/info text.
    - ICON: Can be an emoji ("⚡") or a path to a file ("icon.png") relative to this file.
    - CONFIG_SCHEMA: Defines what the user can configure in the "Add Sensor" dialog.
    """
    
    DISPLAY_NAME = "Power Meter"
    DESCRIPTION = "A simulated device that provides voltage and current readings."
    
    # ICON can be a single emoji character or a filename (e.g., "power_meter.png") 
    # located in the same directory as this plugin.
    ICON = "⚡"  # Other measurement icons: 💧💡🌡️📏⚖️📊🔋💨🌱🧲🔊☀️
    
    # CONFIG_SCHEMA defines the fields shown in the 'Add Sensor' dialog.
    # Supported types: "string", "number", "boolean", "list" (with 'options')
    CONFIG_SCHEMA = {
        "ip_address": {
            "type": "string",
            "label": "Device IP",
            "default": "192.168.1.100"
        },
        "device_mode": {
            "type": "list",
            "label": "Operating Mode",
            "options": ["Simulation", "Real-Time", "Aggressive"],
            "default": "Simulation"
        },
        "enable_averaging": {
            "type": "boolean",
            "label": "Enable Averaging",
            "default": True
        }
    }

    def __init__(self, ip_address="127.0.0.1", device_mode="Simulation", enable_averaging=True, **kwargs):
        """
        Constructor is called when the sensor is added to the system.
        The arguments must match the keys in CONFIG_SCHEMA.
        
        Using **kwargs is recommended to prevent crashes if old configuration 
        keys (like 'update_speed') still exist in your settings file.
        """
        super().__init__(name="Power Meter")
        self.ip_address = ip_address
        self.device_mode = device_mode
        self.enable_averaging = enable_averaging

    def connect(self):
        """
        Connect to your hardware here.
        Return True if successful, False otherwise.
        """
        print(f"Connecting to Simulated Power Meter at {self.ip_address} (Mode: {self.device_mode})...")
        self.connected = True
        return True

    def disconnect(self):
        """
        Clean up resources (close ports, sockets, etc.)
        """
        self.connected = False

    @classmethod
    def get_output_keys(cls):
        """
        Return the list of measurement keys this sensor provides.
        These will appear as selectable sensors in the UI.
        """
        return ["Voltage", "Current", "Power"]

    def read_data(self):
        """
        Return latest readings as a dictionary.
        This is called periodically based on the 'Poll Rate' set in the UI.
        
        Follows 'Direct Reading' rule: return the absolute latest value available.
        The polling thread manages the timing, so this method should NOT block.
        """
        if not self.connected:
            return None
            
        # Simulated device update - replace this with your actual hardware polling logic.
        return {
            "Voltage": round(230 + random.uniform(-2, 2), 2),
            "Current": round(5 + random.uniform(-0.5, 0.5), 2),
            "Power": round(1150 + random.uniform(-50, 50), 2)
        }

    def write_data(self, data):
        """
        Optional: Handle commands sent to the sensor.
        """
        print(f"Custom Sensor received command: {data}")
        return True
