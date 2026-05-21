# Plugin System Guide

Artefakt DAQ supports a modular plugin system that allows you to add custom hardware interfaces (Inbound) and custom data consumers (Outbound) without modifying the core codebase.

## 1. Inbound Plugins (Sensors/Hardware)

Inbound plugins are used to bring data into the system. They inherit from `BaseInterface`.

### File Location
Place your plugin in the `plugins/` directory (e.g., `plugins/my_custom_sensor.py`).

### Template
```python
from app.core.interfaces.base_interface import BaseInterface
import random

class MyCustomSensor(BaseInterface):
    DISPLAY_NAME = "My Sensor"
    DESCRIPTION = "Brief description of the sensor."
    ICON = "🌡️" # Emoji or path to icon file
    HELP_TEXT = "<h3>My Sensor Guide</h3><p>Specific instructions for this sensor.</p>"
    
    # Configuration fields shown in the 'Add Sensor' dialog
    CONFIG_SCHEMA = {
        "port": {
            "type": "string",
            "label": "COM Port",
            "default": "COM3"
        },
        "baud_rate": {
            "type": "number",
            "label": "Baud Rate",
            "default": 9600
        }
    }

    def __init__(self, port="COM3", baud_rate=9600, **kwargs):
        super().__init__(name="My Sensor")
        self.port = port
        self.baud_rate = baud_rate

    def connect(self):
        # Initialize hardware connection
        self.connected = True
        return True

    def disconnect(self):
        # Close hardware connection
        self.connected = False

    @classmethod
    def get_output_keys(cls):
        # List of measurement keys this sensor provides
        return ["Temperature", "Humidity"]

    def read_data(self):
        # Return latest readings as a dictionary
        if not self.connected: return None
        return {
            "Temperature": 25.0 + random.uniform(-1, 1),
            "Humidity": 50.0 + random.uniform(-5, 5)
        }
```

## 2. Outbound Plugins (Data Pushing)

Outbound plugins are used to push data to external systems (UDP, Files, MQTT, etc.) during a run. They inherit from `BaseOutboundInterface`.

### Template
```python
from app.core.interfaces.outbound_interface import BaseOutboundInterface
import json

class MyOutboundPlugin(BaseOutboundInterface):
    DISPLAY_NAME = "My Outbound"
    DESCRIPTION = "Pushes data to an external service."
    ICON = "📤"
    
    CONFIG_SCHEMA = {
        "url": {
            "type": "string",
            "label": "Server URL",
            "default": "http://localhost:8080"
        }
    }

    def __init__(self, url="http://localhost:8080", **kwargs):
        super().__init__(name="My Outbound")
        self.url = url

    def connect(self):
        self.connected = True
        return True

    def disconnect(self):
        self.connected = False

    def push_data(self, data):
        # 'data' is a dictionary containing all active sensor readings
        if not self.connected: return
        # Process and send data here
        pass
```

## 3. UI Integration

- **Inbound:** After creating the file and saving it to `plugins/` (using the `save_plugin_code` tool), the system will automatically refresh its registry. You can then go to the **Sensors** tab, click **Add Sensor**, and select your plugin from the interface list.
- **Outbound:** Go to the **General** tab -> **Outbound Plugins** and add your plugin. It will appear in the list of available outbound interfaces.

## 4. Tips for the AI Assistant
- Use `save_plugin_code` to create or update plugin files.
- Use `list_plugins` to see what custom interfaces are currently installed.
- Use `read_plugin_code` to inspect the implementation of existing plugins (useful for debugging or answering user questions about them).
- Always include the mandatory attributes: `DISPLAY_NAME`, `DESCRIPTION`, `ICON`, and `CONFIG_SCHEMA`.
- Use `**kwargs` in the constructor to maintain compatibility with older configuration keys.
- For icons, you can use any standard emoji or a relative path to a PNG/ICO file in the `plugins/` directory.
