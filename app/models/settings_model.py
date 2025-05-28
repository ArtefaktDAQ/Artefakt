"""
Settings Model

Manages application settings and provides a simplified interface for accessing and saving settings.
"""

import os
from PyQt6.QtCore import QSettings


class SettingsModel:
    """Model for managing application settings"""
    
    def __init__(self, settings: QSettings):
        """
        Initialize the settings model
        
        Args:
            settings: QSettings instance
        """
        self.settings = settings
        self.defaults = {
            # Application settings
            "debug_mode": "false",
            "show_log": "true",
            "theme": "dark",
            
            # Arduino settings
            "arduino_port": "COM3",
            "arduino_baud": "9600",
            "arduino_mode": "continuous",
            "arduino_poll_interval": "1.0",
            "sensor_update_rate": "1.0",
            
            # Camera settings
            "camera_id": "0",
            "camera_resolution": "1280x720",
            "camera_framerate": "30",
            "auto_record": "false",
            "start_camera_on_start": "true",
            "record_with_overlays": "true",
            "recording_output_dir": "recordings",
            "recording_format": "AVI (MJPG)",
            "ffmpeg_binary": "ffmpeg",  # Default FFmpeg executable path
            
            # Graph settings
            "plot_style_preset": "Dark",
            "plot_font_size": "10",
            "plot_line_width": "2",
            
            # Motion detection settings
            "motion_detection_enabled": "false",
            "motion_detection_sensitivity": "20",
            "motion_detection_min_area": "500",
            
            # LabJack settings
            "labjack_type": "U3",
            
            # NDI settings
            "enable_ndi": "false",
            "ndi_source_name": "EvoLabs DAQ",
            "ndi_with_overlays": "true",
            
            # Project settings
            "project_base_dir": "",
        }
    
    def load_settings(self):
        """Load settings and apply defaults if needed"""
        # Nothing to do as QSettings automatically loads values on access
        pass
    
    def save_settings(self):
        """Save all settings to storage"""
        # QSettings automatically saves values when set
        self.settings.sync()
    
    def get_value(self, key, default=None):
        """
        Get a setting value
        
        Args:
            key: Setting key
            default: Default value if not found (uses class defaults if None)
        
        Returns:
            The setting value
        """
        if default is None and key in self.defaults:
            default = self.defaults[key]
            
        return self.settings.value(key, default)
    
    def set_value(self, key, value):
        """
        Set a setting value
        
        Args:
            key: Setting key
            value: Setting value
        """
        self.settings.setValue(key, value)
    
    def get_bool(self, key, default=None):
        """Get a boolean setting value"""
        value = self.get_value(key, default)
        if isinstance(value, bool):
            return value
        return str(value).lower() == "true"
    
    def get_int(self, key, default=None):
        """Get an integer setting value"""
        value = self.get_value(key, default)
        try:
            return int(value)
        except (ValueError, TypeError):
            if default is not None:
                return default
            return 0
    
    def get_float(self, key, default=None):
        """Get a float setting value"""
        value = self.get_value(key, default)
        try:
            return float(value)
        except (ValueError, TypeError):
            if default is not None:
                return default
            return 0.0
    
    def reset_to_defaults(self):
        """Reset all settings to default values"""
        for key, value in self.defaults.items():
            self.settings.setValue(key, value)
        self.settings.sync() 