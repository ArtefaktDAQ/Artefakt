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
        # Only process if camera is connected
        if not hasattr(self, 'camera_controller') or not self.camera_controller.is_connected:
            return
            
        try:
            # Get focus and exposure settings from the camera tab controls
            manual_focus = self.camera_tab_manual_focus.isChecked()
            focus_value = self.camera_tab_focus_slider.value()
            manual_exposure = self.camera_tab_manual_exposure.isChecked()
            exposure_value = self.camera_tab_exposure_slider.value()
            
            # Update slider enabled states
            self.camera_tab_focus_slider.setEnabled(manual_focus)
            self.camera_tab_exposure_slider.setEnabled(manual_exposure)
            
            # Save to settings - use setValue instead of set_value
            self.settings.setValue("camera/manual_focus", "true" if manual_focus else "false")
            self.settings.setValue("camera/focus_value", str(focus_value))
            self.settings.setValue("camera/manual_exposure", "true" if manual_exposure else "false")
            self.settings.setValue("camera/exposure_value", str(exposure_value))
            
            # Apply settings to camera directly
            if self.camera_controller and self.camera_controller.camera_thread:
                if hasattr(self.camera_controller.camera_thread, 'set_camera_properties'):
                    self.camera_controller.camera_thread.set_camera_properties(
                        manual_focus=manual_focus,
                        focus_value=focus_value,
                        manual_exposure=manual_exposure,
                        exposure_value=exposure_value
                    )
                else:
                    # Fallback for direct camera manipulation
                    if hasattr(self.camera_controller.camera_thread, 'cap') and self.camera_controller.camera_thread.cap:
                        if manual_focus:
                            self.camera_controller.camera_thread.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)  # Disable autofocus
                            self.camera_controller.camera_thread.cap.set(cv2.CAP_PROP_FOCUS, focus_value)
                        else:
                            self.camera_controller.camera_thread.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)  # Enable autofocus
                        
                        if manual_exposure:
                            self.camera_controller.camera_thread.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # Magic value for manual
                            self.camera_controller.camera_thread.cap.set(cv2.CAP_PROP_EXPOSURE, exposure_value)
                        else:
                            self.camera_controller.camera_thread.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)  # Magic value for auto
                
        except Exception as e:
            print(f"Error applying camera focus/exposure: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def connect_camera(self):
        """Connect to a camera"""
        if not hasattr(self, 'camera_controller'):
            return
            
        # Forward to the controller
        if self.camera_connect_btn.text() == "Connect":
            # Get settings from the settings tab
            camera_id = self.camera_id.currentIndex()
            
            # Get resolution and fps from the settings tab
            resolution = self.camera_resolution.currentText()
            fps = int(self.camera_framerate.currentText())
            
            # Update the settings values
            self.settings.setValue("camera/default_camera", str(camera_id))
            self.settings.setValue("camera/resolution", resolution)
            self.settings.setValue("camera/fps", str(fps))
            
            # Connect to the camera
            self.camera_controller.toggle_camera()
            
            # Apply focus and exposure settings after connection
            if self.camera_controller.is_connected:
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
    if hasattr(main_window, 'camera_tab_manual_focus') and hasattr(main_window, 'camera_tab_focus_slider'):
        main_window.camera_tab_manual_focus.stateChanged.connect(main_window.apply_camera_focus_exposure)
        main_window.camera_tab_focus_slider.valueChanged.connect(main_window.update_focus_value_label)
        main_window.camera_tab_focus_slider.sliderReleased.connect(main_window.apply_camera_focus_exposure)
    
    if hasattr(main_window, 'camera_tab_manual_exposure') and hasattr(main_window, 'camera_tab_exposure_slider'):
        main_window.camera_tab_manual_exposure.stateChanged.connect(main_window.apply_camera_focus_exposure)
        main_window.camera_tab_exposure_slider.valueChanged.connect(main_window.update_exposure_value_label)
        main_window.camera_tab_exposure_slider.sliderReleased.connect(main_window.apply_camera_focus_exposure)
    
    # Connect the camera connect button
    if hasattr(main_window, 'camera_connect_btn'):
        main_window.camera_connect_btn.clicked.connect(main_window.connect_camera)
    
    # Any additional UI setup or customization can be done here
    pass 