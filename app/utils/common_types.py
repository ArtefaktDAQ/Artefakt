"""
Common types used across the application
"""
from enum import Enum, auto

class StatusState(Enum):
    """
    Status state for components in the application.
    Used to determine visual indicators and app behavior.
    """
    ERROR = auto()    # Red - indicates error/mandatory missing data
    OPTIONAL = auto() # Yellow - optional but inactive
    READY = auto()    # Green - ready to use 
    RUNNING = auto()  # Green - component is actively running (e.g., automation sequence) 