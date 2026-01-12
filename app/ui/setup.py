"""
UI Setup Module

This module is responsible for setting up the user interface of the application.
It delegates to the original ui_setup function from the ui_setup.py file.
"""

# Import the original UI setup function from the local ui_setup.py file
from app.ui.ui_setup import setup_ui as original_setup_ui
import cv2

def setup_ui(main_window):
    """
    Set up the user interface for the main window.
    
    Args:
        main_window: The main application window instance
    """
    # Add camera control methods to the main window first
    def update_focus_value_label(self):
        """Update the focus value label when the slider changes"""
        if hasattr(self, 'camera_tab_focus_slider') and hasattr(self, 'camera_tab_focus_value'):
            value = self.camera_tab_focus_slider.value()
            self.camera_tab_focus_value.setText(str(value))
    
    def update_exposure_value_label(self):
        """Update the exposure value label when the slider changes"""
        if hasattr(self, 'camera_tab_exposure_slider') and hasattr(self, 'camera_tab_exposure_value'):
            value = self.camera_tab_exposure_slider.value()
            self.camera_tab_exposure_value.setText(str(value))
    
    def apply_camera_focus_exposure(self):
        """Apply camera focus and exposure settings immediately"""
        # Forward to camera controller which now handles per-slot settings and saving
        if hasattr(self, 'camera_controller'):
            self.camera_controller.apply_camera_settings()
    
    def connect_camera(self):
        """Connect to a camera"""
        if not hasattr(self, 'camera_controller'):
            return
            
        # Forward to the controller
        if self.camera_connect_btn.text() == "Connect":
            # Check if replay is active with video - if so, stop replay video first
            if hasattr(self, 'replay_mode_enabled') and self.replay_mode_enabled:
                if hasattr(self, 'replay_active_video_path') and self.replay_active_video_path:
                    # Replay video is active - clear it before connecting camera
                    if hasattr(self, '_clear_replay_video'):
                        self._clear_replay_video()
            
            # Connect to the camera (controller handles slot-specific settings)
            self.camera_controller.toggle_camera()
            
            # Apply focus and exposure settings after connection
            if any(self.camera_controller.is_connected):
                self.apply_camera_focus_exposure()
        else:
            # Disconnect the camera
            self.camera_controller.toggle_camera()
    
    # Attach methods to the main window object
    main_window.update_focus_value_label = update_focus_value_label.__get__(main_window)
    main_window.update_exposure_value_label = update_exposure_value_label.__get__(main_window)
    main_window.apply_camera_focus_exposure = apply_camera_focus_exposure.__get__(main_window)
    main_window.connect_camera = connect_camera.__get__(main_window)
    
    # Call the original UI setup function
    original_setup_ui(main_window)
    
    # Connect camera control signals now that UI elements exist
    # Camera Tab focus/exposure signals are now handled in camera_controller.py
    pass
    
    # Connect the camera connect button
    if hasattr(main_window, 'camera_connect_btn'):
        main_window.camera_connect_btn.clicked.connect(main_window.connect_camera)
    
    # Any additional UI setup or customization can be done here
    pass 