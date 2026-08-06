"""
Directory Setup

Utility to set up required directories for the application.
"""

import os
import shutil

# Current branded config directory; legacy name kept for one-time migration.
APP_CONFIG_DIR_NAME = ".artefakt_daq"
LEGACY_CONFIG_DIR_NAME = ".evolabs_daq"


def _migrate_legacy_config_dir(legacy_dir, new_dir):
    """
    One-time migrate ~/.evolabs_daq -> ~/.artefakt_daq.

    Prefers an atomic move. If that fails (e.g. files locked), copies into the
    new directory and renames the legacy folder to *.migrated when possible.
    """
    if os.path.isdir(new_dir) or not os.path.isdir(legacy_dir):
        return

    try:
        shutil.move(legacy_dir, new_dir)
        return
    except OSError:
        pass

    try:
        shutil.copytree(legacy_dir, new_dir)
    except OSError:
        return

    bak = legacy_dir + ".migrated"
    try:
        if os.path.exists(bak):
            shutil.rmtree(bak)
        os.rename(legacy_dir, bak)
    except OSError:
        # New dir is usable; legacy may remain until next successful cleanup.
        pass


def get_app_config_dir(create=True):
    """
    Return the user config directory for Artefakt DAQ (~/.artefakt_daq).

    If only the legacy ~/.evolabs_daq directory exists, migrate it once to the
    new branded path before returning.
    """
    home = os.path.expanduser("~")
    new_dir = os.path.join(home, APP_CONFIG_DIR_NAME)
    legacy_dir = os.path.join(home, LEGACY_CONFIG_DIR_NAME)

    _migrate_legacy_config_dir(legacy_dir, new_dir)

    config_dir = new_dir
    if create:
        os.makedirs(config_dir, exist_ok=True)
    return config_dir


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

    get_app_config_dir(create=True)
        
    # Return success
    return True
