"""
Directory Setup

Utility to set up required directories for the application.
"""

import os


def ensure_directories_exist():
    """
    Ensure that all required directories exist.
    Creates them if they don't exist.
    """
    required_dirs = [
        "logs",          # For log files
    ]
    
    for directory in required_dirs:
        os.makedirs(directory, exist_ok=True)
        
    # Return success
    return True 