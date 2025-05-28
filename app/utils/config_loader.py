"""
Configuration Loader

Provides functions to load and save the application configuration.
"""

import os
import json

CONFIG_FILE = "settings.json"

def load_config():
    """
    Load the application configuration from the JSON file
    
    Returns:
        dict: Configuration dictionary, or empty dict if file doesn't exist
    """
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        else:
            config = {}
            
        # Set default values if not present
        if 'automation_sequences_path' not in config:
            config['automation_sequences_path'] = "data/automation_sequences.json"
            
        return config
    except Exception as e:
        print(f"Error loading configuration: {str(e)}")
        # Return default config
        return {
            'automation_sequences_path': "data/automation_sequences.json"
        }
        
def save_config(config):
    """
    Save the application configuration to the JSON file
    
    Args:
        config: Configuration dictionary to save
    """
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Error saving configuration: {str(e)}") 