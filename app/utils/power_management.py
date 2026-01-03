import ctypes
import os
import platform
import logging

logger = logging.getLogger(__name__)

# Windows Constants for SetThreadExecutionState
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_AWAYMODE_REQUIRED = 0x00000040

class PowerManagement:
    """Utility to manage system power states and prevent sleep during data acquisition."""
    
    _is_preventing_sleep = False
    
    @classmethod
    def prevent_sleep(cls, prevent_display_sleep=False):
        """
        Prevent the system from entering sleep mode.
        
        Args:
            prevent_display_sleep: If True, also prevents the monitor from turning off.
        """
        if platform.system() == 'Windows':
            try:
                flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
                if prevent_display_sleep:
                    flags |= ES_DISPLAY_REQUIRED
                
                # SetThreadExecutionState returns the previous state, or 0 on failure
                result = ctypes.windll.kernel32.SetThreadExecutionState(flags)
                if result != 0:
                    cls._is_preventing_sleep = True
                    logger.info(f"System sleep prevented (display_sleep={'on' if not prevent_display_sleep else 'off'})")
                else:
                    logger.error("Failed to set thread execution state to prevent sleep.")
            except Exception as e:
                logger.error(f"Error preventing system sleep: {e}")
        else:
            # For Linux/macOS, other methods would be needed (e.g. caffeinate on macOS)
            logger.warning(f"Sleep prevention not implemented for {platform.system()}")

    @classmethod
    def allow_sleep(cls):
        """Allow the system to enter sleep mode again."""
        if platform.system() == 'Windows':
            try:
                # Reset to continuous state without requirements
                result = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
                if result != 0:
                    cls._is_preventing_sleep = False
                    logger.info("System sleep allowed again")
                else:
                    logger.error("Failed to reset thread execution state.")
            except Exception as e:
                logger.error(f"Error allowing system sleep: {e}")
        else:
            pass

    @classmethod
    def is_preventing_sleep(cls):
        """Check if sleep prevention is currently active."""
        return cls._is_preventing_sleep

