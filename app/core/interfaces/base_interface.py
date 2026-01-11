"""
Base Interface

Defines the base interface that all hardware interfaces must implement.
"""

from abc import ABC, abstractmethod


class BaseInterface(ABC):
    """
    Abstract base class for hardware interfaces.
    All hardware interfaces must inherit from this class.
    """
    
    # Metadata for the UI and registration
    DISPLAY_NAME = "Base Interface"
    DESCRIPTION = "Base class for all hardware interfaces"
    ICON = "🔌"  # Default icon for the UI card
    HELP_TEXT = None  # Optional HTML help text shown in the config dialog
    
    # Define what configuration fields this interface needs for the UI
    # This schema allows the UI to automatically generate the "Add Sensor" dialog.
    # Supported types: "string", "number", "list", "boolean"
    # Example: 
    # CONFIG_SCHEMA = {
    #     "port": {"type": "list", "label": "Serial Port", "options_cmd": "list_ports"},
    #     "baud_rate": {"type": "number", "label": "Baud Rate", "default": 9600}
    # }
    CONFIG_SCHEMA = {}

    def __init__(self, name=""):
        """
        Initialize the interface
        
        Args:
            name: Interface name/identifier
        """
        self.name = name
        self.connected = False
        self.enabled = True
        self.auto_connect = False
        self.error_message = ""
    
    @classmethod
    def get_ui_options(cls, field_name):
        """
        Returns options for a 'list' type field in CONFIG_SCHEMA.
        Override this to provide dynamic lists (like available COM ports).
        """
        return []
        
    def connect(self):
        """
        Connect to the hardware device
        
        Returns:
            True if connected successfully, False otherwise
        """
        self.connected = True
        return True
        
    def disconnect(self):
        """Disconnect from the hardware device"""
        self.connected = False
        
    def is_connected(self):
        """
        Check if the interface is connected
        
        Returns:
            True if connected, False otherwise
        """
        return self.connected
        
    @abstractmethod
    def read_data(self):
        """
        Read data from the device
        
        Returns:
            Dictionary with sensor values or None if failed
        """
        pass
        
    def write_data(self, data):
        """
        Write data to the device
        
        Args:
            data: Data to write
            
        Returns:
            True if successful, False otherwise
        """
        return False

    @classmethod
    def get_output_keys(cls):
        """
        Returns a list of available data keys this interface provides.
        Example: ["Temperature", "Humidity"] or ["Voltage", "Current"]
        """
        return []
        
    def get_error(self):
        """
        Get the last error message
        
        Returns:
            Error message string
        """
        return self.error_message 