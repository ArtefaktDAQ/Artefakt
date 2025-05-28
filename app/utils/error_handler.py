"""
Error Handler

Handles errors and displays error messages to the user.
"""

import sys
import traceback
from PyQt6.QtWidgets import QMessageBox


def show_error_dialog(parent, title, message, detailed_text=None):
    """
    Show an error dialog
    
    Args:
        parent: Parent widget
        title: Dialog title
        message: Error message
        detailed_text: Detailed error information
    """
    error_box = QMessageBox(parent)
    error_box.setIcon(QMessageBox.Icon.Critical)
    error_box.setWindowTitle(title)
    error_box.setText(message)
    
    if detailed_text:
        error_box.setDetailedText(detailed_text)
        
    error_box.exec()


def handle_exception(exc_type, exc_value, exc_traceback):
    """
    Global exception handler
    
    Args:
        exc_type: Exception type
        exc_value: Exception value
        exc_traceback: Exception traceback
    """
    # Get the traceback as a string
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
    tb_text = ''.join(tb_lines)
    
    # Log the exception
    print(f"Exception: {exc_value}")
    print(tb_text)
    
    # Show error dialog
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app:
        active_window = app.activeWindow()
        show_error_dialog(
            active_window,
            "Application Error",
            f"An error occurred: {exc_value}",
            tb_text
        )


def install_exception_handler():
    """Install the global exception handler"""
    sys.excepthook = handle_exception 