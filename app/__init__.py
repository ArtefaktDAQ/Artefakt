"""
Artefakt DAQ Application Package
"""

__version__ = "0.4.0"
__author__ = "Artefakt"
__description__ = "Data Acquisition System for Laboratory Equipment"
__license__ = "GPL-3.0"

# Version components for programmatic access
VERSION_MAJOR = 0
VERSION_MINOR = 4
VERSION_PATCH = 0
VERSION_BUILD = None  # For development builds

def get_version_string():
    """Get formatted version string"""
    version = f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"
    if VERSION_BUILD:
        version += f".{VERSION_BUILD}"
    return version

def get_version_info():
    """Get version information as dictionary"""
    return {
        "version": __version__,
        "major": VERSION_MAJOR,
        "minor": VERSION_MINOR,
        "patch": VERSION_PATCH,
        "build": VERSION_BUILD,
        "author": __author__,
        "description": __description__,
        "license": __license__
    } 