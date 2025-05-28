"""
Logger Module

Simple logging utility for the application.
"""

import os
import time
from datetime import datetime

class Logger:
    """Simple logger for the application"""
    
    def __init__(self, name, log_file=None, console=True, log_level="INFO"):
        """Initialize the logger
        
        Args:
            name: Name of the logger
            log_file: Path to log file (None for no file logging)
            console: Whether to log to console
            log_level: Minimum log level to display (DEBUG, INFO, WARNING, ERROR)
        """
        self.name = name
        self.log_file = log_file
        self.console = console
        self.log_level = log_level
        
        # Create log directory if needed
        if log_file:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    def _should_log(self, level):
        """Check if the message should be logged based on level
        
        Args:
            level: Log level of the message
            
        Returns:
            bool: Whether the message should be logged
        """
        log_levels = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}
        return log_levels.get(level, 0) >= log_levels.get(self.log_level, 1)
    
    def log(self, message, level="INFO"):
        """Log a message
        
        Args:
            message: Message to log
            level: Log level (INFO, WARNING, ERROR, DEBUG)
        """
        # Check if this level should be logged
        if not self._should_log(level):
            return
            
        # Format timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Format log message
        log_message = f"[{timestamp}] [{self.name}] [{level}] {message}"
        
        # Print to console if enabled
        if self.console:
            print(log_message)
        
        # Write to file if enabled
        if self.log_file:
            try:
                with open(self.log_file, "a") as f:
                    f.write(log_message + "\n")
            except Exception as e:
                print(f"Error writing to log file: {str(e)}")
    
    def info(self, message):
        """Log an info message"""
        self.log(message, "INFO")
    
    def warning(self, message):
        """Log a warning message"""
        self.log(message, "WARNING")
    
    def error(self, message):
        """Log an error message"""
        self.log(message, "ERROR")
    
    def debug(self, message):
        """Log a debug message"""
        self.log(message, "DEBUG")
        
    def close(self):
        """Close the logger and perform cleanup"""
        try:
            # Log shutdown message
            self.log("Logger shutting down")
            
            # Close file if it's open
            if hasattr(self, '_file') and self._file:
                self._file.close()
                
        except Exception as e:
            print(f"Error closing logger: {str(e)}") 