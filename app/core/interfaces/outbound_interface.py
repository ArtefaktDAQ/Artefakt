"""
Outbound Interface Base Class

Defines the base interface for plugins that consume DAQ data (Outbound).
Unlike standard interfaces, these are designed to push data to external systems.
"""

from abc import ABC, abstractmethod

class BaseOutboundInterface(ABC):
    """
    Abstract base class for outbound data interfaces.
    All outbound plugins must inherit from this class.
    """
    
    # Metadata for the UI and registration
    DISPLAY_NAME = "Outbound Interface"
    DESCRIPTION = "Base class for all outbound data interfaces. Plugins are only active during an active data collection run."
    ICON = "📤"  # Default icon for outbound interfaces
    HELP_TEXT = None  # Optional HTML help text shown in the config dialog
    
    # Define what configuration fields this interface needs for the UI
    # Same format as BaseInterface.CONFIG_SCHEMA
    CONFIG_SCHEMA = {}

    def __init__(self, name=""):
        """
        Initialize the outbound interface
        
        Args:
            name: Interface name/identifier
        """
        self.name = name
        self.enabled = True
        self.connected = False
        self.error_message = ""
        
        # Mode-specific settings (if applicable)
        self.mode = "Default"
        
        # Current run folder path
        self.run_directory = ""

    def set_run_directory(self, path):
        """
        Set the current run directory path.
        Plugins can override this to react to folder changes.
        """
        self.run_directory = path

    @abstractmethod
    def push_data(self, data):
        """
        Called whenever a new synchronized data snapshot is available.
        
        Args:
            data: Dictionary containing {'timestamp': float, 'sensor_name': value, ...}
                  May also include 'automation_trigger', 'automation_action', etc.
        """
        pass

    def connect(self):
        """
        Optional: Connect to the external system (e.g., open socket, connect to DB).
        Returns True if successful.
        """
        self.connected = True
        return True

    def disconnect(self):
        """
        Optional: Disconnect from the external system.
        """
        self.connected = False

    def is_connected(self):
        """Check if the interface is connected/active."""
        return self.connected

    def get_error(self):
        """Get the last error message."""
        return self.error_message
