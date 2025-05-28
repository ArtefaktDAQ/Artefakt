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
    
    def __init__(self, name=""):
        """
        Initialize the interface
        
        Args:
            name: Interface name/identifier
        """
        self.name = name
        self.connected = False
        self.error_message = ""
        
    @abstractmethod
    def connect(self):
        """
        Connect to the hardware device
        
        Returns:
            True if connected successfully, False otherwise
        """
        pass
        
    @abstractmethod
    def disconnect(self):
        """Disconnect from the hardware device"""
        pass
        
    @abstractmethod
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
        
    @abstractmethod
    def write_data(self, data):
        """
        Write data to the device
        
        Args:
            data: Data to write
            
        Returns:
            True if successful, False otherwise
        """
        pass
        
    def get_error(self):
        """
        Get the last error message
        
        Returns:
            Error message string
        """
        return self.error_message 