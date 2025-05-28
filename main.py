import sys
import traceback
import signal
from PyQt6.QtWidgets import QApplication
import qdarktheme

# Import the main application class from our app package
from app.main_window import DAQApp
from app import __version__, __author__, __description__

# Import utilities
from app.utils.directory_setup import ensure_directories_exist
from app.utils.error_handler import install_exception_handler

def signal_handler(sig, frame):
    """Handle keyboard interrupt (SIGINT) gracefully"""
    print("\nKeyboardInterrupt received, shutting down gracefully...")
    global QApplication
    QApplication.quit()
    sys.exit(0)

def main():
    """Main application entry point"""
    try:
        # Install signal handler for keyboard interrupt
        signal.signal(signal.SIGINT, signal_handler)
        
        # Install global exception handler
        install_exception_handler()
        
        # Ensure all necessary directories exist
        ensure_directories_exist()
        
        # Initialize Qt application
        app = QApplication(sys.argv)
        
        # Set application metadata
        app.setApplicationName("Artefakt DAQ")
        app.setApplicationVersion(__version__)
        app.setOrganizationName(__author__)
        app.setApplicationDisplayName(f"DAQ v{__version__}")
        
        # Set application style
        app.setStyle("Fusion")
        qdarktheme.setup_theme("dark")
        
        # Create and show main window
        window = DAQApp()
        window.show()
        
        # Start the event loop
        sys.exit(app.exec())
        
    except Exception as e:
        print("Critical error in main application:")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        print("\nFull traceback:")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main() 