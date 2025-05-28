"""
Initialization

Handles application initialization processes.
"""

import os
import json


def load_config():
    """
    Load application configuration from file
    
    Returns:
        Dictionary with configuration values
    """
    config_file = "config.json"
    default_config = {
        "default_project_dir": "projects",
        "default_recording_dir": "recordings",
        "default_snapshot_dir": "snapshots",
        "default_export_dir": "exports",
        "recent_projects": []
    }
    
    if os.path.exists(config_file):
        try:
            with open(config_file, "r") as f:
                config = json.load(f)
            # Make sure all default values are present
            for key, value in default_config.items():
                if key not in config:
                    config[key] = value
            return config
        except Exception as e:
            print(f"Error loading config: {e}")
            return default_config
    else:
        # Create default config file
        with open(config_file, "w") as f:
            json.dump(default_config, f, indent=4)
        return default_config


def save_config(config):
    """
    Save application configuration to file
    
    Args:
        config: Dictionary with configuration values
        
    Returns:
        True if successful, False otherwise
    """
    config_file = "config.json"
    try:
        with open(config_file, "w") as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False 