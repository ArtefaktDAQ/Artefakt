"""
Settings Manager

Handles storing and retrieving application settings.
"""

import os
import json
from pathlib import Path

class SettingsManager:
    """Manages application settings"""
    
    def __init__(self, settings_file=None):
        """Initialize the settings manager"""
        # Default settings file location
        if settings_file is None:
            # Get application directory
            app_dir = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent
            self.settings_file = os.path.join(app_dir, 'settings.json')
        else:
            self.settings_file = settings_file
        
        # Initialize settings
        self.settings = {}
        
        # Load settings
        self.load_settings()
    
    def load_settings(self):
        """Load settings from file"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    self.settings = json.load(f)
            else:
                # Create with default settings
                self.settings = self._get_default_settings()
                self.save_settings()
        except Exception as e:
            print(f"Error loading settings: {str(e)}")
            # Use defaults
            self.settings = self._get_default_settings()
    
    def save_settings(self):
        """Save settings to file"""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            
            # Write settings
            with open(self.settings_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
                
            return True
        except Exception as e:
            print(f"Error saving settings: {str(e)}")
            return False
    
    def get_value(self, section, key, default=None):
        """Get a setting value"""
        try:
            if section in self.settings and key in self.settings[section]:
                return self.settings[section][key]
            return default
        except Exception:
            return default
    
    def set_value(self, section, key, value):
        """Set a setting value"""
        try:
            # Create section if it doesn't exist
            if section not in self.settings:
                self.settings[section] = {}
            
            # Set value
            self.settings[section][key] = value
            
            # Save settings
            self.save_settings()
            
            return True
        except Exception as e:
            print(f"Error setting value: {str(e)}")
            return False
    
    def get_section(self, section, default=None):
        """Get an entire section of settings"""
        if default is None:
            default = {}
            
        try:
            if section in self.settings:
                return self.settings[section]
            return default
        except Exception:
            return default
    
    def _get_default_settings(self):
        """Get default settings"""
        return {
            'general': {
                'theme': 'light',
                'language': 'en',
                'auto_save': True,
                'show_debug': False
            },
            'camera': {
                'auto_connect': False,
                'default_camera': 0,
                'resolution': '1280x720',
                'fps': 30,
                'recording_dir': 'recordings'
            },
            'data': {
                'sample_rate': 1000,
                'save_dir': 'data',
                'file_format': 'csv'
            },
            'display': {
                'show_grid': True,
                'grid_color': '#CCCCCC',
                'background_color': '#FFFFFF',
                'line_width': 1
            }
        } 