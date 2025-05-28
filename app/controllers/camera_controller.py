"""
Camera Controller

Manages camera operations, recording, and overlays.
"""
import sys
import traceback
from PyQt6.QtCore import QObject, pyqtSlot, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QColor, QPainter, QBrush
from PyQt6.QtWidgets import QComboBox, QPushButton, QLabel, QMessageBox, QCheckBox, QSlider, QSpinBox
import os
import time
from datetime import datetime
import cv2
import numpy as np
import random

from app.core.direct_camera import DirectCameraThread  # New direct camera implementation

from app.settings.settings_manager import SettingsManager
from app.core.logger import Logger
from app.utils.common_types import StatusState

class CameraController(QObject):
    """Controller for managing camera operations"""

    # Signal that will be emitted when the camera status changes
    status_changed = pyqtSignal()

    def __init__(self, main_window, settings_model, project_controller):
        """
        Initialize the camera controller
        
        Args:
            main_window: Main application window
            settings_model: The application's SettingsModel instance
            project_controller: The application's ProjectController instance
        """
        super().__init__()
        self.main_window = main_window
        self.settings = settings_model # Use the passed SettingsModel
        self.project_controller = project_controller # Store project_controller
        self.logger = Logger("CameraController")
        
        # Get common UI elements
        self.camera_connect_btn = getattr(self.main_window, 'camera_connect_btn', None)
        self.camera_select = getattr(self.main_window, 'camera_id', None)
        self.camera_label = getattr(self.main_window, 'camera_label', None)
        self.record_btn = getattr(self.main_window, 'record_btn', None)

        # --- Motion Detection UI Elements --- START
        self.motion_enabled_widget = getattr(self.main_window, 'motion_detection_enabled', None)
        self.motion_sensitivity_widget = getattr(self.main_window, 'motion_detection_sensitivity', None)
        self.motion_min_area_widget = getattr(self.main_window, 'motion_detection_min_area', None) 
        self.motion_indicator = getattr(self.main_window, 'motion_detection_indicator', None)
        
        # Try direct lookup if not found via attribute name
        if self.motion_enabled_widget is None and hasattr(self.main_window, 'findChild'):
            from PyQt6.QtWidgets import QCheckBox
            try:
                self.motion_enabled_widget = self.main_window.findChild(QCheckBox, 'motion_detection_enabled')
            except Exception as e:
                self.logger.log(f"Error finding motion_detection_enabled via findChild: {e}", "ERROR")
        # --- Motion Detection UI Elements --- END
        
        # Store original and recording button styles
        if self.record_btn:
            self.original_button_style = self.record_btn.styleSheet()
            self.recording_button_style = """
                QPushButton {
                    background-color: transparent;
                    border: 2px solid #F44336;  /* Red border */
                    border-radius: 3px;
                    padding: 3px 6px;
                    font-size: 12px;
                    min-height: 22px;
                    max-height: 22px;
                }
                QPushButton:hover {
                    background-color: rgba(244, 67, 54, 0.15);
                }
                QPushButton:pressed {
                    background-color: rgba(244, 67, 54, 0.3);
                }
            """
        
        # Initialize camera thread (using new direct implementation)
        self.camera_thread = None
        
        # Current state
        self.is_connected = False
        self.is_recording = False
        self.current_frame = None
        self.should_reconnect = False
        
        # Mouse interaction state
        self.drag_start_pos = None
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.overlays = []
        self.selected_overlay = None
        
        # Initialize camera
        self.init_camera()
        
        # --- Initial Motion Detection Config --- START
        # Call handlers AFTER init_camera ensures thread exists and connections are made
        if self.motion_enabled_widget:
            # Ensure initial UI state matches saved setting
            setting_value = self.settings.get_value("motion", "motion_detection_enabled", "false")
            initial_enabled = setting_value.lower() == "true" if setting_value is not None else False
            self.motion_enabled_widget.setChecked(initial_enabled)
            self._handle_motion_enabled_changed(initial_enabled) # Sync with thread and update UI enable state
        if self.motion_sensitivity_widget and self.motion_min_area_widget:
            # Ensure initial UI state matches saved setting
            sensitivity_value = self.settings.get_value("motion", "motion_detection_sensitivity", "20")
            min_area_value = self.settings.get_value("motion", "motion_detection_min_area", "500")
            initial_sensitivity = int(sensitivity_value) if sensitivity_value is not None else 20
            initial_min_area = int(min_area_value) if min_area_value is not None else 500
            self.motion_sensitivity_widget.setValue(initial_sensitivity)
            self.motion_min_area_widget.setValue(initial_min_area)
            self._handle_motion_settings_changed() # Sync with thread
        # --- Initial Motion Detection Config --- END
        
        # Connect signals for UI elements
        self.connect_signals()
        
        self.logger.log("Camera controller initialized")
        
    def init_camera(self):
        """Initialize the camera"""
        try:
            print("Initializing camera...")
            # Create the camera thread
            from app.core.direct_camera import DirectCameraThread
            
            # Check if an existing thread is already running
            if hasattr(self, 'camera_thread') and self.camera_thread:
                # If thread is running, stop it
                if self.camera_thread.isRunning():
                    print("Stopping existing camera thread...")
                    self.camera_thread.stop()
                    
                    # Wait for thread to finish
                    if not self.camera_thread.wait(3000):  # 3 second timeout
                        print("Thread did not stop in time, forcing termination...")
                        self.camera_thread.terminate()
            
            print("Creating new camera thread...")
            # Create new thread with reference to main window for sensor access
            self.camera_thread = DirectCameraThread(main_window=self.main_window)
            
            # Connect signals
            self.camera_thread.status_update.connect(self.handle_connection_status)
            self.camera_thread.frame_captured.connect(self.update_frame_display)
            self.camera_thread.recording_status_signal.connect(self.handle_recording_status)
            self.camera_thread.motion_detected_signal.connect(self._update_motion_indicator)
            
            print("Camera thread initialized")
            
            # Set initial motion detection state from settings
            if self.settings_model:
                # Read settings
                enable_motion = self.settings_model.value("camera/motion_detection", "false").lower() == "true"
                motion_sensitivity = int(self.settings_model.value("camera/motion_sensitivity", 20))
                motion_min_area = int(self.settings_model.value("camera/motion_min_area", 500))
                
                # Set initial state in camera thread
                self.camera_thread.set_motion_detection_enabled(enable_motion)
                self.camera_thread.update_motion_detection_settings(motion_sensitivity, motion_min_area)
                
            return True
        except Exception as e:
            print(f"Error initializing camera: {str(e)}")
            self.logger.log(f"Error initializing camera: {str(e)}", "ERROR")
            traceback.print_exc()
            return False
    
    def populate_camera_list(self):
        """Populate the camera selection dropdown"""
        if not self.camera_select:
            return
            
        try:
            self.camera_select.clear()
            
            # Add camera options (we'll detect up to 5 cameras)
            for i in range(5):
                self.camera_select.addItem(f"Camera {i}", i)
            
            # Select the default camera
            default_camera = self.settings.get_value('camera', 'default_camera', 0)
            
            # Ensure index is valid
            if default_camera < self.camera_select.count():
                self.camera_select.setCurrentIndex(default_camera)
                
        except Exception as e:
            print(f"Error populating camera list: {str(e)}")
    
    @pyqtSlot()
    def toggle_camera(self):
        """Toggle camera connection (connect/disconnect)"""
        try:
            print(f"Toggle camera called. Current state: is_connected={self.is_connected}")
            
            if not self.is_connected:
                print("Attempting to connect camera...")
                self.connect_camera()
            else:
                print("Attempting to disconnect camera...")
                self.disconnect_camera()
            
            # Always reconnect camera buttons after toggling camera connection
            self.reconnect_camera_buttons()
            
            # Update UI based on the new state
            if self.camera_connect_btn:
                button_text = "Disconnect" if self.is_connected else "Connect"
                print(f"Setting button text to: {button_text}")
                self.camera_connect_btn.setText(button_text)
                self.camera_connect_btn.repaint()
            
        except Exception as e:
            self.logger.log(f"Error toggling camera: {str(e)}", "ERROR")
            traceback.print_exc()
    
    def connect_camera(self):
        """Connect to the camera"""
        try:
            # Get camera settings from UI
            camera_id = self.camera_select.value() if hasattr(self.camera_select, 'value') else 0
            
            # Get settings with proper defaults
            resolution = self.settings.get_value('camera/resolution', "1280x720")
            fps_val = self.settings.get_value('camera/fps', "30")
            fps = int(fps_val) if fps_val is not None else 30
            
            # Check if camera is already connected - using function call instead of attribute
            if self.camera_thread and self.camera_thread.is_connected():
                print("Camera is already connected")
                return
            
            # Show connecting status
            if self.camera_label:
                self.camera_label.setText("Connecting...")
            
            # Create new camera thread if needed
            if not self.camera_thread:
                print("Creating new camera thread")
                self.camera_thread = DirectCameraThread(main_window=self.main_window)
                
                # Connect signals with proper error checking
                try:
                    # Disconnect any existing connections first to avoid duplicates
                    try:
                        self.camera_thread.frame_captured.disconnect()
                    except:
                        pass
                    
                    try:
                        self.camera_thread.status_update.disconnect()
                    except:
                        pass
                    
                    try:
                        self.camera_thread.recording_status_signal.disconnect()
                    except:
                        pass
                    
                    # Connect signals using queued connection to prevent GUI freezing
                    print("Connecting camera thread signals...")
                    self.camera_thread.frame_captured.connect(
                        self.update_frame_display, Qt.ConnectionType.QueuedConnection)
                    print("Frame captured signal connected")
                    
                    self.camera_thread.status_update.connect(
                        self.handle_connection_status, Qt.ConnectionType.QueuedConnection)
                    print("Status update signal connected")
                    
                    self.camera_thread.recording_status_signal.connect(
                        self.handle_recording_status, Qt.ConnectionType.QueuedConnection)
                    print("Recording status signal connected")
                    
                    if hasattr(self.camera_thread, 'motion_detected_signal'):
                        self.camera_thread.motion_detected_signal.connect(
                            self._update_motion_indicator, Qt.ConnectionType.QueuedConnection)
                        print("Motion detection signal connected")
                    
                except Exception as signal_error:
                    print(f"Error connecting camera thread signals: {str(signal_error)}")
                    traceback.print_exc()
            
            # Connect to camera
            print("Attempting camera connection...")
            success = self.camera_thread.connect(camera_id, resolution, fps)
            
            if success:
                # -- Apply Motion Detection Settings AFTER Successful Connect --
                print("--> Entering Apply Motion Settings block in connect_camera") # LOG
                try:
                    # Read settings from SettingsModel
                    enabled = self.settings.get_bool("motion_detection_enabled", False)
                    sensitivity = self.settings.get_int("motion_detection_sensitivity", 20)
                    min_area = self.settings.get_int("motion_detection_min_area", 500)
                    print(f"    Read from SettingsModel: enabled={enabled}, sens={sensitivity}, area={min_area}") # LOG
                    
                    # Apply to thread
                    if hasattr(self.camera_thread, 'set_motion_detection_enabled'):
                        print(f"    Calling thread.set_motion_detection_enabled({enabled})") # LOG
                        self.camera_thread.set_motion_detection_enabled(enabled)
                        print("    Called thread.set_motion_detection_enabled") # LOG
                    if hasattr(self.camera_thread, 'update_motion_detection_settings'):
                        print(f"    Calling thread.update_motion_detection_settings({sensitivity}, {min_area})") # LOG
                        self.camera_thread.update_motion_detection_settings(sensitivity, min_area)
                        print("    Called thread.update_motion_detection_settings") # LOG
                    
                    # Update UI elements to match settings
                    if self.motion_enabled_widget:
                         # Block signals temporarily to prevent feedback loops
                        print("    Blocking signals for motion_enabled_widget") # LOG
                        self.motion_enabled_widget.blockSignals(True)
                        print(f"    Calling motion_enabled_widget.setChecked({enabled})") # LOG
                        self.motion_enabled_widget.setChecked(enabled)
                        print("    Called motion_enabled_widget.setChecked") # LOG
                        self.motion_enabled_widget.blockSignals(False)
                        print("    Unblocked signals for motion_enabled_widget") # LOG
                        # Manually update enabled state of other widgets
                        if self.motion_sensitivity_widget: self.motion_sensitivity_widget.setEnabled(enabled)
                        if self.motion_min_area_widget: self.motion_min_area_widget.setEnabled(enabled)
                    
                    # Set initial indicator state (green if enabled, gray if not)
                    if self.motion_indicator:
                        style = "background-color: gray; border-radius: 5px;"
                        if enabled:
                            style = "background-color: green; border-radius: 5px;"
                        print(f"    Setting motion_indicator style: {style}") # LOG
                        self.motion_indicator.setStyleSheet(style)
                        print("    Set motion_indicator style") # LOG
                            
                    self.logger.log(f"Applied motion settings on connect: enabled={enabled}, sens={sensitivity}, area={min_area}", "DEBUG")
                except Exception as motion_err:
                    self.logger.log(f"Error applying motion settings on connect: {motion_err}", "ERROR")
                print("<-- Exiting Apply Motion Settings block in connect_camera") # LOG
                # -- End Motion Detection Apply --

                # Update UI state
                self.camera_connect_btn.setEnabled(True)
                self.camera_connect_btn.setText("Disconnect")
                self.camera_connect_btn.repaint()
                
                self.camera_select.setEnabled(False)
                if hasattr(self, 'record_btn') and self.record_btn:
                    self.record_btn.setEnabled(True)
                
                # Explicitly set connected state
                self.is_connected = True
                
                # Update status
                self.handle_connection_status(True, "Camera connected")
            else:
                print("Failed to connect to camera")
                self.is_connected = False
                self.handle_connection_status(False, "Failed to connect to camera")
                
                # Reset label text if connection failed
                if self.camera_label:
                    self.camera_label.setText("No camera connected")
            
        except Exception as e:
            print(f"Error connecting to camera: {str(e)}")
            print("Full traceback:")
            traceback.print_exc()
            self.is_connected = False
            self.handle_connection_status(False, f"Error: {str(e)}")
            
            # Reset label text if an error occurred
            if self.camera_label:
                self.camera_label.setText("No camera connected")
    
    def disconnect_camera(self):
        """Disconnect from the camera"""
        try:
            if self.camera_thread:
                print("Disconnecting camera...")
                
                # Stop the thread first
                self.camera_thread.disconnect()
                
                # Update UI state
                self.camera_connect_btn.setEnabled(True)
                self.camera_select.setEnabled(True)
                if hasattr(self, 'record_btn') and self.record_btn:
                    self.record_btn.setEnabled(False)
                
                # Clear camera display
                if self.camera_label:
                    self.camera_label.clear()
                    self.camera_label.setText("No camera connected")
                    self.camera_label.repaint()
                
                # Explicitly set the connection state to False
                self.is_connected = False
                
                # Update button text to "Connect" and force refresh
                if self.camera_connect_btn:
                    self.camera_connect_btn.setText("Connect")
                    self.camera_connect_btn.repaint()
                
                # Update status
                self.handle_connection_status(False, "Camera disconnected")
                
                # Ensure other UI elements are updated for disconnected state
                if hasattr(self.main_window, 'snapshot_btn'):
                    self.main_window.snapshot_btn.setEnabled(False)
                
                if hasattr(self.main_window, 'record_btn'):
                    self.main_window.record_btn.setEnabled(False)
                
                if hasattr(self.main_window, 'add_overlay_btn'):
                    self.main_window.add_overlay_btn.setEnabled(False)
                
                print("Camera disconnected successfully")
                
            else:
                print("No camera thread to disconnect")
                self.is_connected = False
                
        except Exception as e:
            print(f"Error disconnecting camera: {str(e)}")
            print("Full traceback:")
            traceback.print_exc()
            self.is_connected = False  # Ensure state is updated even on error
            self.handle_connection_status(False, f"Error: {str(e)}")
    
    @pyqtSlot(bool, str)
    def handle_connection_status(self, connected, message):
        """Handle connection status updates from the camera thread"""
        try:
            # Update state
            self.is_connected = connected
            
            # Log connection message
            print(f"Camera {'connected' if connected else 'disconnected'}: {message}")
            print(f"Camera controller connection state updated to: {self.is_connected}")
            
            # Update UI
            if self.camera_connect_btn:
                # Force update button text based on connection state
                if connected:
                    self.camera_connect_btn.setText("Disconnect")
                else:
                    self.camera_connect_btn.setText("Connect")
                    
                # Force button update
                self.camera_connect_btn.repaint()
                
                # Change the border color of the connect button based on connection status
                if connected:
                    # Red border for the connect button when connected
                    self.camera_connect_btn.setStyleSheet("""
                        QPushButton {
                            background-color: transparent;
                            border: 2px solid #FF0000;  /* Red border */
                            border-radius: 3px;
                            padding: 3px 6px;
                            font-size: 12px;
                            min-height: 22px;
                            max-height: 22px;
                        }
                        QPushButton:hover {
                            background-color: rgba(255, 0, 0, 0.15);
                            border-color: #d32f2f;
                        }
                        QPushButton:pressed {
                            background-color: rgba(255, 0, 0, 0.3);
                            border-color: #b71c1c;
                        }
                    """)
                else:
                    # Green border for the connect button when disconnected (ready to connect)
                    self.camera_connect_btn.setStyleSheet("""
                        QPushButton {
                            background-color: transparent;
                            border: 2px solid #4CAF50;  /* Green border */
                            border-radius: 3px;
                            padding: 3px 6px;
                            font-size: 12px;
                            min-height: 22px;
                            max-height: 22px;
                        }
                        QPushButton:hover {
                            background-color: rgba(76, 175, 80, 0.15);
                            border-color: #3d8b40;
                        }
                        QPushButton:pressed {
                            background-color: rgba(76, 175, 80, 0.3);
                            border-color: #2e6830;
                        }
                    """)
            
            # Enable or disable camera-dependent buttons
            if hasattr(self.main_window, 'record_btn'):
                self.main_window.record_btn.setEnabled(connected)
                
            if hasattr(self.main_window, 'snapshot_btn'):
                self.main_window.snapshot_btn.setEnabled(connected)
                
            if hasattr(self.main_window, 'add_overlay_btn'):
                self.main_window.add_overlay_btn.setEnabled(connected)
            
            # Update camera tab control states if connected
            if connected:
                # Apply camera settings from the camera tab controls directly
                if hasattr(self.main_window, 'apply_camera_focus_exposure'):
                    self.main_window.apply_camera_focus_exposure()
                
                # NOTE: Motion detection setup moved to connect_camera to avoid duplication
                # and race conditions since this method is called by connect_camera.
            
            if not connected and self.camera_label:
                # Set text for disconnected state
                self.camera_label.setText("No camera connected")
                
                # Clear label with black pixmap
                empty_pixmap = QPixmap(640, 480)
                empty_pixmap.fill(Qt.GlobalColor.black)
                self.camera_label.setPixmap(empty_pixmap)
                
        except Exception as e:
            print(f"Error handling connection status: {str(e)}")
            traceback.print_exc()
    
    @pyqtSlot(QPixmap)
    def update_frame_display(self, pixmap):
        """Update the camera display with the captured frame"""
        try:
            if self.camera_label:
                # Save the current frame for potential processing
                self.current_frame = pixmap.copy()
                
                # Scale the pixmap to fit the display while maintaining aspect ratio
                scaled_pixmap = pixmap.scaled(self.camera_label.width(), self.camera_label.height(), 
                                            Qt.AspectRatioMode.KeepAspectRatio, 
                                            Qt.TransformationMode.SmoothTransformation)
                
                self.camera_label.setPixmap(scaled_pixmap)
                
                # Update the dashboard camera preview if it exists
                if hasattr(self.main_window, 'dashboard_camera_label'):
                    # Create a smaller version for the dashboard
                    dashboard_pixmap = pixmap.scaled(self.main_window.dashboard_camera_label.width(), 
                                                    self.main_window.dashboard_camera_label.height(),
                                                    Qt.AspectRatioMode.KeepAspectRatio, 
                                                    Qt.TransformationMode.SmoothTransformation)
                    
                    self.main_window.dashboard_camera_label.setPixmap(dashboard_pixmap)
                
                # Update the recording label if we're recording
                if self.is_recording:
                    # Create a copy of the pixmap with a red indicator for recording
                    recording_pixmap = scaled_pixmap.copy()
                    painter = QPainter(recording_pixmap)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    painter.setBrush(QBrush(QColor(255, 0, 0, 200)))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(15, 15, 15, 15)  # Draw a red circle
                    painter.end()
                    
                    # Set the processed pixmap
                    self.camera_label.setPixmap(recording_pixmap)
                
                # Update FPS information in status bar if available
                if self.camera_thread and hasattr(self.camera_thread, 'get_actual_fps'):
                    fps = self.camera_thread.get_actual_fps()
                    if fps > 0:
                        self.main_window.statusBar().showMessage(f"FPS: {fps:.1f}")

                # Send frame to NDI if enabled
                if hasattr(self, 'ndi_interface') and hasattr(self, '_ndi_enabled') and self._ndi_enabled:
                    # Check if NDI is available and running
                    if self.ndi_interface.is_available() and self.ndi_interface.is_running():
                        try:
                            # Check if we need to extract the actual image data for NDI
                            # Convert the QPixmap to a QImage
                            image = pixmap.toImage()
                            
                            # Convert QImage to OpenCV format (numpy array)
                            width = image.width()
                            height = image.height()
                            ptr = image.constBits()
                            ptr.setsize(image.sizeInBytes())
                            
                            # QImage is stored as RGBA, but we need BGR or BGRA for OpenCV/NDI
                            if image.format() == QImage.Format.Format_RGB32:
                                # RGBA to BGR conversion
                                frame = np.array(ptr).reshape(height, width, 4)
                                frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
                            else:
                                # Convert to the right format first
                                cvt_image = image.convertToFormat(QImage.Format.Format_RGB32)
                                ptr = cvt_image.constBits()
                                ptr.setsize(cvt_image.sizeInBytes())
                                frame = np.array(ptr).reshape(height, width, 4)
                                frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)

                            # Now we have a BGR format frame, update the NDI interface
                            self.ndi_interface.update_frame(frame)
                            # self.logger.log("NDI frame sent", "DEBUG")  # Very noisy, uncomment for debugging
                            
                        except Exception as e:
                            # Only log occasionally to avoid filling logs
                            if random.random() < 0.01:  # Log only about 1% of errors
                                self.logger.log(f"Error sending frame to NDI: {str(e)}", "ERROR")
            
        except Exception as e:
            print(f"Error updating camera display: {str(e)}")
            
            # Disable update from the thread if there's a problem
            if self.camera_thread and hasattr(self.camera_thread, 'frame_captured'):
                try:
                    self.camera_thread.frame_captured.disconnect(self.update_frame_display)
                except:
                    pass
    
    def handle_recording_status(self, is_recording):
        """Handle recording status updates from the camera thread"""
        try:
            self.is_recording = is_recording
            if hasattr(self.main_window, 'record_btn') and self.main_window.record_btn:
                # Update button text
                self.main_window.record_btn.setText("Stop Recording" if is_recording else "Start Recording")
                
                # Change button style based on recording state
                if is_recording:
                    self.main_window.record_btn.setStyleSheet(self.recording_button_style)
                else:
                    self.main_window.record_btn.setStyleSheet(self.original_button_style)
                
                print(f"Recording status updated: {is_recording}")
        except Exception as e:
            print(f"Error handling recording status: {str(e)}")
            traceback.print_exc()
    
    @pyqtSlot()
    def toggle_recording(self):
        """Toggle recording on/off"""
        try:
            if not self.is_connected:
                self.logger.log("Cannot record: Camera not connected")
                return
                
            if not self.is_recording:
                # Start recording
                self.start_recording()
            else:
                # Stop recording
                self.stop_recording()
                
        except Exception as e:
            self.logger.log(f"Error toggling recording: {str(e)}")
    
    def stop_recording(self):
        """Stop recording video"""
        try:
            # Check if camera is connected and thread is running
            if not self.is_connected or not self.camera_thread or not self.camera_thread.isRunning():
                self.logger.log("Cannot stop recording: Camera not connected")
                return
                
            # Stop recording in the camera thread
            self.camera_thread.stop_recording()
            
            # Update UI state
            self.main_window.record_btn.setText("Start Recording")
            
            # Set recording flag
            self.is_recording = False
            
            self.logger.log("Stopped recording")
            
        except Exception as e:
            self.logger.log(f"Error stopping recording: {str(e)}")
    
    def shutdown(self):
        """Clean up resources when shutting down"""
        try:
            # Disconnect camera
            if self.is_connected and self.camera_thread:
                self.disconnect_camera()
                
        except Exception as e:
            print(f"Error during camera shutdown: {str(e)}")

    def connect_signals(self):
        """Connect UI signals to controller methods"""
        # Properly connect camera connect button
        if hasattr(self.main_window, 'camera_connect_btn'):
            try:
                self.main_window.camera_connect_btn.clicked.disconnect()
            except Exception:
                pass
            self.main_window.camera_connect_btn.clicked.connect(self.toggle_camera)
            
        # Connect record button
        if hasattr(self.main_window, 'record_btn'):
            try:
                self.main_window.record_btn.clicked.disconnect()
            except Exception:
                pass
            self.main_window.record_btn.clicked.connect(self.toggle_recording)
            
        # Connect snapshot button
        if hasattr(self.main_window, 'snapshot_btn'):
            try:
                self.main_window.snapshot_btn.clicked.disconnect()
            except Exception:
                pass
            self.main_window.snapshot_btn.clicked.connect(self.take_snapshot)
        
        # Connect overlay buttons
        if hasattr(self.main_window, 'add_overlay_btn'):
            try:
                self.main_window.add_overlay_btn.clicked.disconnect()
            except Exception:
                pass
            self.main_window.add_overlay_btn.clicked.connect(self.add_overlay)
            
        if hasattr(self.main_window, 'remove_overlay_btn'):
            try:
                self.main_window.remove_overlay_btn.clicked.disconnect()
            except Exception:
                pass
            self.main_window.remove_overlay_btn.clicked.connect(self.remove_overlay)
            
        if hasattr(self.main_window, 'apply_overlay_settings_btn'):
            try:
                self.main_window.apply_overlay_settings_btn.clicked.disconnect()
            except Exception:
                pass
            self.main_window.apply_overlay_settings_btn.clicked.connect(self.apply_overlay_settings)
            
        if hasattr(self.main_window, 'camera_apply_settings_btn'):
            try:
                self.main_window.camera_apply_settings_btn.clicked.disconnect()
            except Exception:
                pass
            self.main_window.camera_apply_settings_btn.clicked.connect(self.apply_camera_settings)
            
        # Connect focus and exposure controls if they exist
        if hasattr(self.main_window, 'camera_tab_manual_focus') and hasattr(self.main_window, 'camera_tab_focus_slider'):
            try:
                self.main_window.camera_tab_manual_focus.stateChanged.disconnect()
            except Exception:
                pass
            self.main_window.camera_tab_manual_focus.stateChanged.connect(self.main_window.apply_camera_focus_exposure)
            
            try:
                self.main_window.camera_tab_focus_slider.valueChanged.disconnect()
                self.main_window.camera_tab_focus_slider.sliderReleased.disconnect()
            except Exception:
                pass
            self.main_window.camera_tab_focus_slider.valueChanged.connect(self.main_window.update_focus_value_label)
            self.main_window.camera_tab_focus_slider.sliderReleased.connect(self.main_window.apply_camera_focus_exposure)
        
        if hasattr(self.main_window, 'camera_tab_manual_exposure') and hasattr(self.main_window, 'camera_tab_exposure_slider'):
            try:
                self.main_window.camera_tab_manual_exposure.stateChanged.disconnect()
            except Exception:
                pass
            self.main_window.camera_tab_manual_exposure.stateChanged.connect(self.main_window.apply_camera_focus_exposure)
            
            try:
                self.main_window.camera_tab_exposure_slider.valueChanged.disconnect()
                self.main_window.camera_tab_exposure_slider.sliderReleased.disconnect()
            except Exception:
                pass
            self.main_window.camera_tab_exposure_slider.valueChanged.connect(self.main_window.update_exposure_value_label)
            self.main_window.camera_tab_exposure_slider.sliderReleased.connect(self.main_window.apply_camera_focus_exposure)
    
    def take_snapshot(self):
        """Take a snapshot from the camera"""
        try:
            if not self.camera_thread or not self.is_connected:
                self.logger.log("Cannot take snapshot: No camera connected")
                return

            if not self.current_frame:
                self.logger.log("Cannot take snapshot: No frame available")
                return

            # Determine the save directory using the project controller's new helper method
            run_dir = None
            if self.project_controller:
                run_dir = self.project_controller.get_current_run_directory()

            if not run_dir:
                self.logger.log("Cannot take snapshot: No active run directory.", "WARN")
                # Fallback to a default directory in the base directory
                if self.project_controller and hasattr(self.main_window, 'project_base_dir'):
                    base_dir = self.main_window.project_base_dir.text()
                    if base_dir and os.path.exists(base_dir):
                        snapshots_dir = os.path.join(base_dir, "Snapshots")
                    else:
                        snapshots_dir = os.path.join(".", "Snapshots")
                else:
                    snapshots_dir = os.path.join(".", "Snapshots")
            else:
                # Save to Snapshots subfolder in the run directory
                snapshots_dir = os.path.join(run_dir, "Snapshots")

            # Create the snapshots directory if it doesn't exist
            os.makedirs(snapshots_dir, exist_ok=True)

            # Generate filename with timestamp
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(snapshots_dir, f"snapshot_{timestamp}.png")

            # Save the frame
            self.current_frame.save(filename, "PNG")

            self.logger.log(f"Snapshot saved: {filename}")
            
            # Optionally, if the camera is recording to video and we need to show confirmation in UI
            if hasattr(self.main_window, 'statusBar'):
                self.main_window.statusBar().showMessage(f"Snapshot saved to {os.path.basename(os.path.dirname(snapshots_dir))}/Snapshots", 3000)

        except Exception as e:
            self.logger.log(f"Error taking snapshot: {str(e)}", "ERROR")
            import traceback
            self.logger.log(traceback.format_exc(), "ERROR")
    
    def add_overlay(self):
        """Add a new overlay to the camera feed"""
        try:
            # Create a menu for overlay type selection
            from PyQt6.QtWidgets import QMenu, QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton, QHBoxLayout, QDialogButtonBox, QLineEdit
            from PyQt6.QtCore import Qt
            
            # Create overlay selection dialog
            overlay_dialog = QDialog(self.main_window)
            overlay_dialog.setWindowTitle("Add Overlay")
            overlay_dialog.setFixedWidth(300)
            overlay_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
            
            # Dialog layout
            layout = QVBoxLayout(overlay_dialog)
            
            # Overlay type selection
            type_layout = QHBoxLayout()
            type_layout.addWidget(QLabel("Overlay type:"))
            
            overlay_type_combo = QComboBox()
            overlay_type_combo.addItems(["Text", "Timestamp", "Rectangle", "Sensor"])
            type_layout.addWidget(overlay_type_combo)
            
            layout.addLayout(type_layout)
            
            # Text input for text overlay
            text_layout = QHBoxLayout()
            text_layout.addWidget(QLabel("Text:"))
            
            text_input = QLineEdit("New Overlay")
            text_layout.addWidget(text_input)
            
            layout.addLayout(text_layout)
            
            # Sensor selection for sensor overlay
            sensor_layout = QHBoxLayout()
            sensor_layout.addWidget(QLabel("Sensor:"))
            
            sensor_combo = QComboBox()
            # Check if we have access to the sensor controller
            sensor_names = []
            if hasattr(self.main_window, 'sensor_controller') and self.main_window.sensor_controller:
                sensor_names = self.main_window.sensor_controller.get_sensor_names()
                
            sensor_combo.addItems(sensor_names if sensor_names else ["No sensors available"])
            sensor_combo.setVisible(False)  # Initially hidden
            sensor_layout.addWidget(sensor_combo)
            
            layout.addLayout(sensor_layout)
            
            # Button box
            button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            button_box.accepted.connect(overlay_dialog.accept)
            button_box.rejected.connect(overlay_dialog.reject)
            layout.addWidget(button_box)
            
            # Show/hide input fields based on overlay type
            def on_type_changed(index):
                selected_type = overlay_type_combo.currentText()
                text_input.setVisible(selected_type == "Text")
                sensor_combo.setVisible(selected_type == "Sensor")
                
                if selected_type == "Text":
                    text_layout.itemAt(0).widget().setText("Text:")
                elif selected_type == "Timestamp":
                    text_layout.itemAt(0).widget().setText("Format:")
                
                # Enable/disable OK button if Sensor is selected but no sensors available
                if selected_type == "Sensor" and (not sensor_names or sensor_names[0] == "No sensors available"):
                    button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
                else:
                    button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
            
            overlay_type_combo.currentIndexChanged.connect(on_type_changed)
            on_type_changed(0)  # Initialize visibility
            
            # Center dialog on parent
            overlay_dialog.move(
                self.main_window.x() + (self.main_window.width() - overlay_dialog.width()) // 2,
                self.main_window.y() + (self.main_window.height() - overlay_dialog.height()) // 2
            )
            
            # Show dialog and get result
            result = overlay_dialog.exec()
            if result != QDialog.DialogCode.Accepted:
                return
                
            # Get selected overlay type
            overlay_type = overlay_type_combo.currentText().lower()
            
            # Create a new overlay object
            overlay_count = len(self.overlays) + 1
            
            # Default overlay properties with BGR color format (OpenCV uses BGR)
            # Green text (0, 255, 0) in RGB becomes (0, 255, 0) in BGR
            # Black background (0, 0, 0) in RGB becomes (0, 0, 0) in BGR
            new_overlay = {
                "id": overlay_count,
                "name": f"{overlay_type.capitalize()} {overlay_count}",
                "type": overlay_type,
                "position": (50, 50 + (overlay_count - 1) * 30),
                "font_scale": 0.7,
                "thickness": 2,
                "text_color": (0, 255, 0),  # BGR format (Green)
                "bg_color": (0, 0, 0),      # BGR format (Black)
                "bg_alpha": 50,
                "visible": True
            }
            
            # Add type-specific properties
            if overlay_type == "text":
                new_overlay["text"] = text_input.text()
            elif overlay_type == "timestamp":
                new_overlay["text"] = "Current Time"  # Just a placeholder, will be replaced
            elif overlay_type == "rectangle":
                new_overlay["width"] = 150
                new_overlay["height"] = 80
            elif overlay_type == "sensor":
                selected_sensor = sensor_combo.currentText()
                new_overlay["sensor_name"] = selected_sensor
                new_overlay["text"] = f"{selected_sensor}: N/A"  # Default text, will be updated dynamically
            
            self.overlays.append(new_overlay)
            self.selected_overlay = new_overlay
            
            # Update overlay selector in UI
            self.update_overlay_selector()
            
            # Pass overlays to camera thread
            if self.camera_thread and hasattr(self.camera_thread, 'set_overlays'):
                self.camera_thread.set_overlays(self.overlays)
            
            self.logger.log(f"Added {overlay_type} overlay #{overlay_count}")
            
        except Exception as e:
            self.logger.log(f"Error adding overlay: {str(e)}")
            traceback.print_exc()
    
    def update_overlay_selector(self):
        """Update the overlay selector dropdown"""
        if not hasattr(self.main_window, 'overlay_selector'):
            return
            
        # Temporarily disconnect signal if we've already connected it
        try:
            if hasattr(self, '_overlay_selector_connected') and self._overlay_selector_connected:
                self.main_window.overlay_selector.currentIndexChanged.disconnect()
        except:
            pass  # Ignore if not connected
            
        # Clear and repopulate the overlay selector
        self.main_window.overlay_selector.clear()
        
        for overlay in self.overlays:
            self.main_window.overlay_selector.addItem(overlay["name"])
        
        # Set the current item to the selected overlay
        if self.selected_overlay:
            index = self.overlays.index(self.selected_overlay)
            self.main_window.overlay_selector.setCurrentIndex(index)
            
        # Connect signal to handle overlay selection changes
        self.main_window.overlay_selector.currentIndexChanged.connect(self.on_overlay_selected)
        self._overlay_selector_connected = True
            
        # Update overlay settings UI
        self.update_overlay_settings_ui()
        
    def on_overlay_selected(self, index):
        """Handle overlay selection change"""
        if index >= 0 and index < len(self.overlays):
            self.selected_overlay = self.overlays[index]
            self.update_overlay_settings_ui()
    
    def update_overlay_settings_ui(self):
        """Update overlay settings UI based on selected overlay"""
        if not hasattr(self.main_window, 'overlay_font_scale') or not self.selected_overlay:
            return
            
        # Update UI controls with the selected overlay's properties
        self.main_window.overlay_font_scale.setValue(self.selected_overlay["font_scale"])
        self.main_window.overlay_thickness.setValue(self.selected_overlay["thickness"])
        
        # Get overlay type
        overlay_type = self.selected_overlay.get("type", "text")
        
        # Show/hide type-specific controls - Use setExpanded for CollapsibleBox
        if hasattr(self.main_window, 'overlay_text_content_group'):
            # Set expansion state based on overlay type
            self.main_window.overlay_text_content_group.setExpanded(overlay_type in ["text", "timestamp", "sensor"])
            
        if hasattr(self.main_window, 'overlay_text_content'):
            # For timestamp overlays, disable text editing but show the field
            if overlay_type == "timestamp":
                self.main_window.overlay_text_content.setText("Current Time (Automatic)")
                self.main_window.overlay_text_content.setEnabled(False)
            elif overlay_type == "sensor":
                sensor_name = self.selected_overlay.get("sensor_name", "Unknown")
                self.main_window.overlay_text_content.setText(f"{sensor_name} (Automatic)")
                self.main_window.overlay_text_content.setEnabled(False)
            else:
                self.main_window.overlay_text_content.setText(self.selected_overlay.get("text", ""))
                self.main_window.overlay_text_content.setEnabled(overlay_type == "text")
        
        # Handle rectangle dimensions if available
        if hasattr(self.main_window, 'overlay_dimensions_group'):
            # Set expansion state based on overlay type
            self.main_window.overlay_dimensions_group.setExpanded(overlay_type == "rectangle")
            
            if overlay_type == "rectangle" and hasattr(self.main_window, 'overlay_width') and hasattr(self.main_window, 'overlay_height'):
                self.main_window.overlay_width.setValue(self.selected_overlay.get("width", 150))
                self.main_window.overlay_height.setValue(self.selected_overlay.get("height", 80))
        
        # Update color preview boxes - Convert BGR to RGB for display
        b, g, r = self.selected_overlay["text_color"]
        self.main_window.text_color_preview.setStyleSheet(f"background-color: rgb({r}, {g}, {b}); border: 1px solid #888;")
        
        b, g, r = self.selected_overlay["bg_color"]
        self.main_window.bg_color_preview.setStyleSheet(f"background-color: rgb({r}, {g}, {b}); border: 1px solid #888;")
        
        # Update opacity
        self.main_window.overlay_bg_alpha.setValue(self.selected_overlay["bg_alpha"])
    
    def apply_overlay_settings(self):
        """Apply settings to the selected overlay"""
        try:
            if not self.selected_overlay:
                return
                
            # Get values from UI
            self.selected_overlay["font_scale"] = self.main_window.overlay_font_scale.value()
            self.selected_overlay["thickness"] = self.main_window.overlay_thickness.value()
            
            # Get overlay type
            overlay_type = self.selected_overlay.get("type", "text")
            
            # Get type-specific settings
            if overlay_type == "text":
                self.selected_overlay["text"] = self.main_window.overlay_text_content.text()
            elif overlay_type == "rectangle" and hasattr(self.main_window, 'overlay_width') and hasattr(self.main_window, 'overlay_height'):
                self.selected_overlay["width"] = self.main_window.overlay_width.value()
                self.selected_overlay["height"] = self.main_window.overlay_height.value()
            
            # Get colors from hidden spinboxes
            if hasattr(self.main_window, 'overlay_text_color_r') and \
               hasattr(self.main_window, 'overlay_text_color_g') and \
               hasattr(self.main_window, 'overlay_text_color_b'):
                # BGR format for OpenCV
                self.selected_overlay["text_color"] = (
                    self.main_window.overlay_text_color_b.value(),
                    self.main_window.overlay_text_color_g.value(),
                    self.main_window.overlay_text_color_r.value()
                )
                
            if hasattr(self.main_window, 'overlay_bg_color_r') and \
               hasattr(self.main_window, 'overlay_bg_color_g') and \
               hasattr(self.main_window, 'overlay_bg_color_b'):
                # BGR format for OpenCV
                self.selected_overlay["bg_color"] = (
                    self.main_window.overlay_bg_color_b.value(),
                    self.main_window.overlay_bg_color_g.value(),
                    self.main_window.overlay_bg_color_r.value()
                )
                
            # Get opacity (bg_alpha) - applied to all overlay types
            if hasattr(self.main_window, 'overlay_bg_alpha'):
                self.selected_overlay["bg_alpha"] = self.main_window.overlay_bg_alpha.value()
                print(f"Applied opacity: {self.main_window.overlay_bg_alpha.value()} to overlay type: {overlay_type}")
            
            # Update camera thread with the updated overlays
            if self.camera_thread and hasattr(self.camera_thread, 'set_overlays'):
                self.camera_thread.set_overlays(self.overlays)
                print(f"Updated overlays with new settings. Current opacity value: {self.selected_overlay.get('bg_alpha', 'N/A')}")
            
            self.logger.log("Applied overlay settings")
            
        except Exception as e:
            self.logger.log(f"Error applying overlay settings: {str(e)}")
            traceback.print_exc()
    
    def remove_overlay(self):
        """Remove the selected overlay"""
        try:
            if not self.selected_overlay:
                return
                
            # Remove the selected overlay
            self.overlays.remove(self.selected_overlay)
            
            # Update selected overlay
            if self.overlays:
                self.selected_overlay = self.overlays[0]
            else:
                self.selected_overlay = None
                
            # Update overlay selector
            self.update_overlay_selector()
            
            # Update camera thread with the updated overlays
            if self.camera_thread and hasattr(self.camera_thread, 'set_overlays'):
                self.camera_thread.set_overlays(self.overlays)
            
            self.logger.log("Removed overlay")
            
        except Exception as e:
            self.logger.log(f"Error removing overlay: {str(e)}")
    
    def apply_camera_settings(self):
        """Apply camera settings"""
        try:
            # Get camera settings from UI
            resolution = self.main_window.camera_resolution.currentText()
            fps = int(self.main_window.camera_framerate.currentText())
            
            # Save to settings
            self.settings.set_value("camera/resolution", resolution)
            self.settings.set_value("camera/framerate", str(fps))
            
            # Get video quality from SETTINGS (updated by popup)
            video_quality_str = self.settings.get_value("video_quality", "70")
            try:
                video_quality = int(video_quality_str)
            except (ValueError, TypeError):
                video_quality = 70 # Default if setting is invalid
            self.logger.log(f"Read video_quality from settings: {video_quality}%", "DEBUG")
                
            # Get FFmpeg binary path from UI if available
            ffmpeg_binary = "ffmpeg"  # Default value
            if hasattr(self.main_window, 'ffmpeg_binary_path'):
                ffmpeg_binary = self.main_window.ffmpeg_binary_path.text().strip()
                print(f"FFmpeg binary path set to: {ffmpeg_binary}")
                
                # Ensure the path exists if it's not just 'ffmpeg'
                if ffmpeg_binary != "ffmpeg" and not os.path.isfile(ffmpeg_binary):
                    self.main_window.logger.log(f"Warning: FFmpeg binary not found at {ffmpeg_binary}")
                    
                    # Try to find in PATH
                    import shutil
                    ffmpeg_in_path = shutil.which('ffmpeg')
                    if ffmpeg_in_path:
                        self.main_window.logger.log(f"Found FFmpeg in PATH: {ffmpeg_in_path}")
                        # Ask user if they want to use the one in PATH instead
                        reply = QMessageBox.question(
                            self.main_window,
                            "FFmpeg Found in PATH",
                            f"The specified FFmpeg path does not exist:\n{ffmpeg_binary}\n\n"
                            f"But FFmpeg was found in your system PATH at:\n{ffmpeg_in_path}\n\n"
                            "Do you want to use this FFmpeg installation instead?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.Yes
                        )
                        
                        if reply == QMessageBox.StandardButton.Yes:
                            ffmpeg_binary = ffmpeg_in_path
                            self.main_window.ffmpeg_binary_path.setText(ffmpeg_in_path)
                            self.main_window.logger.log(f"Using FFmpeg from PATH: {ffmpeg_in_path}")
                    else:
                        # Show warning
                        QMessageBox.warning(
                            self.main_window,
                            "FFmpeg Not Found",
                            f"The FFmpeg executable was not found at:\n{ffmpeg_binary}\n\n"
                            "Please make sure the path is correct or download FFmpeg from:\n"
                            "https://ffmpeg.org/download.html\n\n"
                            "Video encoding may not work correctly."
                        )
            
            # Get option for direct streaming
            use_direct_streaming = self.settings.get_bool("use_direct_streaming", True)
            self.logger.log(f"Read use_direct_streaming from settings: {use_direct_streaming}", "DEBUG")
            
            # Save to settings
            self.settings.set_value("video_quality", str(video_quality))
            self.settings.set_value("ffmpeg_binary", ffmpeg_binary)
            
            # Update recording settings if available
            if hasattr(self.main_window, 'record_with_overlays'):
                record_with_overlays = self.main_window.record_with_overlays.isChecked()
                self.settings.set_value("record_with_overlays", "true" if record_with_overlays else "false")
            
            if hasattr(self.main_window, 'recording_output_dir'):
                recording_output_dir = self.main_window.recording_output_dir.text()
                self.settings.set_value("recording_output_dir", recording_output_dir)
            
            if hasattr(self.main_window, 'recording_format'):
                recording_format = self.main_window.recording_format.currentText()
                self.settings.set_value("recording_format", recording_format)
            
            # Update camera if connected
            if self.camera_thread and self.is_connected:
                # Set video quality
                if hasattr(self.camera_thread, 'set_video_quality'):
                    self.camera_thread.set_video_quality(video_quality)
                
                # Set FFmpeg binary
                if hasattr(self.camera_thread, 'set_ffmpeg_binary'):
                    self.camera_thread.set_ffmpeg_binary(ffmpeg_binary)
                
                # Set direct streaming option
                if hasattr(self.camera_thread, 'enable_direct_streaming'):
                    if not self.is_recording:
                        self.camera_thread.enable_direct_streaming(use_direct_streaming)
                        self.logger.log(f"Direct streaming mode set to: {use_direct_streaming}")
                    else:
                        self.logger.log("Recording active: Direct streaming setting will apply on next recording.")
                
                # Decide if reconnect is needed (resolution or fps change)
                # TODO: Check if resolution or fps actually changed compared to current thread state
                # For now, assume reconnect might be needed if applying settings while connected.
                # A more robust check would compare new settings to camera_thread.width/height/fps
                # Example (needs access to camera_thread attributes):
                # current_res = f"{self.camera_thread.width}x{self.camera_thread.height}"
                # if resolution != current_res or fps != self.camera_thread.fps:
                #    reconnect_needed = True
                
                # Simplified: Reconnect logic might need refinement based on what changed.
                # For now, the code proceeds to stop/connect/start if settings are applied while connected.
                
                # Get current camera ID for reconnect
                camera_id = 0
                if hasattr(self.main_window, 'camera_select') and hasattr(self.main_window.camera_select, 'currentData'):
                     camera_id = self.main_window.camera_select.currentData() 
                     if camera_id is None: camera_id = 0 # Default if data is None
                elif hasattr(self.main_window, 'camera_id'): # Fallback for older UI names
                     camera_id = self.main_window.camera_id.value()

                print(f"Applying settings to connected camera {camera_id}...")
                print(f"Resolution: {resolution}, FPS: {fps}")
                
                # --- Reconnect Logic --- 
                # Check if the thread is actually running before stopping
                was_running = self.camera_thread.isRunning()
                if was_running:
                    print("Stopping camera thread temporarily to apply settings...")
                    self.camera_thread.stop() # Use stop() which handles release and wait
                    # self.camera_thread.wait() # Ensure thread has stopped - stop() includes wait
                
                print(f"Connecting camera {camera_id} with new settings...")
                # Connect with new settings
                # Make sure to pass the potentially updated resolution/fps
                success = self.camera_thread.connect(camera_id, resolution, fps)
                
                # Restart thread if it was running and connect succeeded
                if success and was_running:
                    print("Restarting camera thread...")
                    # self.camera_thread.start() # connect() should start the thread
                elif not success:
                     print("Failed to reconnect camera with new settings.")
                     self.handle_connection_status(False, "Failed to reconnect after settings change")
            
            self.logger.log(f"Applied camera settings: {resolution}@{fps}fps, quality: {video_quality}%, FFmpeg: {ffmpeg_binary}, DirectStream: {use_direct_streaming}")
            
        except Exception as e:
            self.logger.log(f"Error applying camera settings: {str(e)}")
            traceback.print_exc()
    
    def camera_mouse_press(self, event):
        """Handle mouse press events on the camera display"""
        try:
            # Make sure we have a camera label
            if not self.camera_label:
                return
            
            # Store the drag start position
            self.drag_start_pos = event.position()
            
            # Get current pixmap and dimensions for coordinate transformation
            if not hasattr(self.camera_label, 'pixmap') or not callable(getattr(self.camera_label, 'pixmap', None)):
                return
            
            pixmap = self.camera_label.pixmap()
            if pixmap is None or pixmap.isNull():
                return
            
            label_width = self.camera_label.width()
            label_height = self.camera_label.height()
            pixmap_width = pixmap.width()
            pixmap_height = pixmap.height()
            
            # Calculate pixmap position within label (centered)
            pixmap_x = (label_width - pixmap_width) / 2 if pixmap_width < label_width else 0
            pixmap_y = (label_height - pixmap_height) / 2 if pixmap_height < label_height else 0
            
            # Transform click coordinates from label space to pixmap space
            # First, adjust for pixmap position within label
            pixmap_click_x = event.position().x() - pixmap_x
            pixmap_click_y = event.position().y() - pixmap_y
            
            # Skip if click is outside the pixmap area
            if (pixmap_click_x < 0 or pixmap_click_x >= pixmap_width or 
                pixmap_click_y < 0 or pixmap_click_y >= pixmap_height):
                return
            
            # Store original frame dimensions for scaling back to original coordinates
            if self.current_frame:
                self.original_width = self.current_frame.width()
                self.original_height = self.current_frame.height()
                
                # Calculate scaling factors between original frame and displayed pixmap
                self.scale_x = self.original_width / pixmap_width
                self.scale_y = self.original_height / pixmap_height
            else:
                # If we don't have the original frame, use 1:1 scaling
                self.original_width = pixmap_width
                self.original_height = pixmap_height
                self.scale_x = 1.0
                self.scale_y = 1.0
            
            # Check if we clicked on an overlay
            self.selected_overlay = None
            
            for overlay in self.overlays:
                # Get overlay properties in original frame coordinates
                pos_x, pos_y = overlay["position"]
                overlay_type = overlay.get("type", "text")
                
                # Convert overlay position from original frame to displayed pixmap coordinates
                display_x = pos_x / self.scale_x
                display_y = pos_y / self.scale_y
                
                # Hit testing based on overlay type
                hit = False
                
                if overlay_type == "rectangle":
                    # Rectangle hit test
                    width = overlay.get("width", 100) / self.scale_x
                    height = overlay.get("height", 50) / self.scale_y
                    
                    # Add padding for easier selection (5 pixels in each direction)
                    padding_x = 5 / self.scale_x
                    padding_y = 5 / self.scale_y
                    
                    # Calculate rectangle bounds with padding
                    rect_left = display_x - padding_x
                    rect_right = display_x + width + padding_x
                    rect_top = display_y - padding_y
                    rect_bottom = display_y + height + padding_y
                    
                    if (rect_left <= pixmap_click_x <= rect_right and 
                        rect_top <= pixmap_click_y <= rect_bottom):
                        hit = True
                else:
                    # Text or timestamp hit test
                    text = overlay.get("text", "")
                    if overlay_type == "timestamp":
                        # For timestamp overlays, use a standard length for hit testing
                        text = "YYYY-MM-DD HH:MM:SS"
                        
                    font_scale = overlay.get("font_scale", 0.7)
                    thickness = overlay.get("thickness", 2)
                    
                    # Better text size calculation for different font scales
                    # The 8.0 multiplier is approximate for the FONT_HERSHEY_SIMPLEX font
                    # Testing shows this provides better estimation of actual rendered width
                    text_width = len(text) * 8.0 * font_scale / self.scale_x
                    text_height = 25 * font_scale / self.scale_y  # Increased height for better hit detection
                    
                    # Add horizontal padding for hit testing
                    padding_x = 10 / self.scale_x  # 10 pixels in original frame coordinates
                    padding_y = 10 / self.scale_y  # 10 pixels in original frame coordinates
                    
                    # Improved hit testing with padding for the entire text box
                    text_left = display_x - padding_x
                    text_right = display_x + text_width + padding_x
                    text_top = display_y - text_height - padding_y
                    text_bottom = display_y + padding_y
                    
                    if (text_left <= pixmap_click_x <= text_right and 
                        text_top <= pixmap_click_y <= text_bottom):
                        hit = True
                        
                if hit:
                    self.selected_overlay = overlay
                    # Store offset from overlay position to click position (in pixmap space)
                    self.drag_offset_x = pixmap_click_x - display_x
                    self.drag_offset_y = pixmap_click_y - display_y
                    break
                
            # Update overlay settings UI if an overlay was selected
            if self.selected_overlay:
                self.update_overlay_selector()
            
        except Exception as e:
            self.logger.log(f"Error handling mouse press: {str(e)}")
            traceback.print_exc()
    
    def camera_mouse_release(self, event):
        """Handle mouse release events on the camera display"""
        try:
            # Reset drag start position
            self.drag_start_pos = None
            
        except Exception as e:
            self.logger.log(f"Error handling mouse release: {str(e)}")
    
    def camera_mouse_move(self, event):
        """Handle mouse move events on the camera display"""
        try:
            # Make sure we have a camera label
            if not self.camera_label:
                return
            
            # If we're dragging an overlay, update its position
            if self.drag_start_pos and self.selected_overlay:
                # Get current pixmap and dimensions
                if not hasattr(self.camera_label, 'pixmap') or not callable(getattr(self.camera_label, 'pixmap', None)):
                    return
                
                pixmap = self.camera_label.pixmap()
                if pixmap is None or pixmap.isNull():
                    return
                
                label_width = self.camera_label.width()
                label_height = self.camera_label.height()
                pixmap_width = pixmap.width()
                pixmap_height = pixmap.height()
                
                # Calculate pixmap position within label (centered)
                pixmap_x = (label_width - pixmap_width) / 2 if pixmap_width < label_width else 0
                pixmap_y = (label_height - pixmap_height) / 2 if pixmap_height < label_height else 0
                
                # Get mouse position in pixmap coordinates
                pixmap_mouse_x = event.position().x() - pixmap_x
                pixmap_mouse_y = event.position().y() - pixmap_y
                
                # Calculate new overlay position in pixmap coordinates
                # Subtract the drag offset to get the top-left position
                new_pixmap_x = pixmap_mouse_x - self.drag_offset_x
                new_pixmap_y = pixmap_mouse_y - self.drag_offset_y
                
                # Keep overlay within pixmap bounds
                new_pixmap_x = max(0, min(new_pixmap_x, pixmap_width))
                new_pixmap_y = max(0, min(new_pixmap_y, pixmap_height))
                
                # Convert back to original frame coordinates
                new_frame_x = new_pixmap_x * self.scale_x
                new_frame_y = new_pixmap_y * self.scale_y
                
                # Update overlay position
                self.selected_overlay["position"] = (new_frame_x, new_frame_y)
                
                # Update camera thread with the updated overlays
                if self.camera_thread and hasattr(self.camera_thread, 'set_overlays'):
                    self.camera_thread.set_overlays(self.overlays)
                
                # Update drag start position
                self.drag_start_pos = event.position()
            
        except Exception as e:
            self.logger.log(f"Error handling mouse move: {str(e)}")
            traceback.print_exc()
    
    def close_camera(self):
        """Close the camera connection"""
        try:
            if self.camera_thread:
                # Stop recording if active
                if self.is_recording:
                    self.camera_thread.stop_recording()
                
                # Stop the thread
                self.camera_thread.stop()
                
                # Update UI
                if hasattr(self.main_window, 'camera_connect_btn'):
                    self.main_window.camera_connect_btn.setText("Connect")
                
                if hasattr(self.main_window, 'camera_label'):
                    self.main_window.camera_label.setText("No camera connected")
                
                self.logger.log("Camera closed")
            
        except Exception as e:
            self.logger.log(f"Error closing camera: {str(e)}")
    
    def init_ndi(self):
        """Initialize NDI sender"""
        # Check if NDI is already available in the module
        from app.core.interfaces.ndi_interface import NDIInterface
        
        # Get NDI settings from application settings
        enable_ndi = self.settings.get_value("enable_ndi", "false").lower() == "true"
        ndi_source_name = self.settings.get_value("ndi_source_name", "EvoLabs DAQ")
        ndi_with_overlays = self.settings.get_value("ndi_with_overlays", "true").lower() == "true"
        
        # Log the NDI settings
        self.logger.log(f"NDI Settings - Enabled: {enable_ndi}, Source: {ndi_source_name}, With Overlays: {ndi_with_overlays}", "INFO")
        
        # Create NDI interface as a class attribute if not already created
        if not hasattr(self, 'ndi_interface'):
            self.ndi_interface = NDIInterface(source_name=ndi_source_name)
            self.logger.log(f"NDI Interface created. Available: {self.ndi_interface.is_available()}", "INFO")
        else:
            # Update properties if interface already exists
            self.ndi_interface.set_properties(source_name=ndi_source_name)
            self.logger.log(f"NDI Interface updated with source name: {ndi_source_name}", "INFO")
            
        # Start NDI if enabled and available
        if enable_ndi:
            if self.ndi_interface.is_available():
                # If already running, stop first to apply new settings
                if self.ndi_interface.is_running():
                    self.ndi_interface.stop()
                
                # Start NDI with current settings
                if self.ndi_interface.start():
                    self.logger.log(f"NDI Output started with source name: {ndi_source_name}", "INFO")
                else:
                    self.logger.log("Failed to start NDI Output", "ERROR")
            else:
                self.logger.log("NDI libraries not available. Cannot enable NDI output.", "WARN")
                # Show NDI installation info if not available
                if hasattr(self.main_window, 'statusBar'):
                    self.main_window.statusBar().showMessage("NDI not available. See documentation for installation instructions.", 5000)
        else:
            # Stop NDI if it was running but is now disabled
            if hasattr(self, 'ndi_interface') and self.ndi_interface.is_running():
                self.ndi_interface.stop()
                self.logger.log("NDI Output stopped (disabled in settings)", "INFO")
        
        # Store settings for access by frame handling
        self._ndi_enabled = enable_ndi
        self._ndi_with_overlays = ndi_with_overlays
    
    def handle_motion_detection_state(self, state):
        """Handle motion detection state changes"""
        self.motion_detection_enabled = state
        
        # Enable/disable motion detection controls
        if hasattr(self.main_window, 'motion_detection_sensitivity'):
            self.main_window.motion_detection_sensitivity.setEnabled(state)
            
        if hasattr(self.main_window, 'motion_detection_min_area'):
            self.main_window.motion_detection_min_area.setEnabled(state)
    
    def choose_text_color(self):
        """Open color dialog to choose text color"""
        from PyQt6.QtWidgets import QColorDialog
        
        if not self.selected_overlay:
            return
            
        # Get current color - BGR to RGB conversion for display
        b, g, r = self.selected_overlay["text_color"]
        current_color = QColorDialog.getColor(
            QColor(r, g, b)  # Convert BGR to RGB for QColorDialog
        )
        
        if current_color.isValid():
            # Update overlay text color - RGB to BGR conversion for OpenCV
            self.selected_overlay["text_color"] = (
                current_color.blue(),    # B
                current_color.green(),   # G
                current_color.red()      # R
            )
            
            # Update UI (using RGB)
            self.main_window.text_color_preview.setStyleSheet(
                f"background-color: rgb({current_color.red()}, {current_color.green()}, {current_color.blue()}); "
                f"border: 1px solid #888;"
            )
            
            # Update the camera thread with the updated overlays
            if self.camera_thread and hasattr(self.camera_thread, 'set_overlays'):
                self.camera_thread.set_overlays(self.overlays)

    def choose_bg_color(self):
        """Open color dialog to choose background color"""
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QColor
        
        if not self.selected_overlay:
            return
            
        # Get current color - BGR to RGB conversion for display
        b, g, r = self.selected_overlay["bg_color"]
        current_color = QColorDialog.getColor(
            QColor(r, g, b)  # Convert BGR to RGB for QColorDialog
        )
        
        if current_color.isValid():
            # Update overlay background color - RGB to BGR conversion for OpenCV
            self.selected_overlay["bg_color"] = (
                current_color.blue(),    # B
                current_color.green(),   # G
                current_color.red()      # R
            )
            
            # Update UI (using RGB)
            self.main_window.bg_color_preview.setStyleSheet(
                f"background-color: rgb({current_color.red()}, {current_color.green()}, {current_color.blue()}); "
                f"border: 1px solid #888;"
            )
            
            # Update the camera thread with the updated overlays
            if self.camera_thread and hasattr(self.camera_thread, 'set_overlays'):
                self.camera_thread.set_overlays(self.overlays)

    def update_camera_display(self):
        """Update the camera display - called when tab changes"""
        try:
            # Always reconnect camera buttons when camera tab is selected
            self.reconnect_camera_buttons()
            
            # Check if camera label exists
            if not hasattr(self.main_window, 'camera_label'):
                self.logger.log("Camera label not found", "WARN")
                return
                
            # If in connecting state but not yet connected, show connecting message
            if self.camera_thread and self.camera_thread.isRunning() and not self.is_connected:
                self.main_window.camera_label.setText("Connecting...")
                return
            
            # If not connected or no camera thread, show not connected message
            if not self.is_connected or not self.camera_thread:
                self.main_window.camera_label.setText("No camera connected")
                
                # Also update UI components state
                if hasattr(self.main_window, 'snapshot_btn'):
                    self.main_window.snapshot_btn.setEnabled(False)
                
                if hasattr(self.main_window, 'record_btn'):
                    self.main_window.record_btn.setEnabled(False)
                
                if hasattr(self.main_window, 'add_overlay_btn'):
                    self.main_window.add_overlay_btn.setEnabled(False)
                
                return
                
            # If already connected and camera has frame, update with latest frame
            if self.current_frame and not self.current_frame.isNull():
                self.main_window.camera_label.setPixmap(self.current_frame)
                
                # Enable camera-dependent buttons
                if hasattr(self.main_window, 'snapshot_btn'):
                    self.main_window.snapshot_btn.setEnabled(True)
                
                if hasattr(self.main_window, 'record_btn'):
                    self.main_window.record_btn.setEnabled(True)
                
                if hasattr(self.main_window, 'add_overlay_btn'):
                    self.main_window.add_overlay_btn.setEnabled(True)
            
            # Ensure camera thread is running
            if not self.camera_thread.isRunning():
                self.camera_thread.start()
                
            # Apply camera settings when tab is selected
            if hasattr(self.main_window, 'apply_camera_focus_exposure'):
                self.main_window.apply_camera_focus_exposure()
                
        except Exception as e:
            self.logger.log(f"Error updating camera display: {str(e)}", "ERROR")
            if hasattr(self.main_window, 'camera_label'):
                self.main_window.camera_label.setText("No camera connected")
    
    def start_recording(self):
        """Start recording video"""
        try:
            # Check if camera is connected and thread is running
            if not self.is_connected or not self.camera_thread or not self.camera_thread.isRunning():
                self.logger.log("Cannot start recording: Camera not connected")
                return
                
            # Check if we have an active project run directory
            output_dir = "recordings"
            use_run_dir = False
            
            # Try to get the run directory from project controller
            if hasattr(self.main_window, 'project_controller'):
                # Get base directory
                base_dir = self.main_window.project_base_dir.text().strip()
                project_name = self.main_window.project_selector.currentText().strip()
                series_name = self.main_window.test_series_selector.currentText().strip()
                
                # Check if we have a current run
                if (base_dir and project_name and series_name and 
                    self.main_window.project_controller.current_run and
                    self.main_window.project_controller.current_project == project_name and
                    self.main_window.project_controller.current_test_series == series_name):
                    
                    # Build run directory path
                    run_dir = os.path.join(base_dir, project_name, series_name, 
                                         self.main_window.project_controller.current_run)
                    
                    # Check if directory exists
                    if os.path.exists(run_dir):
                        output_dir = run_dir
                        use_run_dir = True
                        self.logger.log(f"Using project run directory for video: {output_dir}")
            
            # If no run directory found, use default or UI setting
            if not use_run_dir and hasattr(self.main_window, 'recording_output_dir'):
                ui_output_dir = self.main_window.recording_output_dir.text().strip()
                if ui_output_dir:
                    output_dir = ui_output_dir
            
            # Create timestamp for filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Get format from UI or use default
            video_format = "mp4"
            codec = "H264"
            if hasattr(self.main_window, 'recording_format'):
                format_text = self.main_window.recording_format.currentText()
                if "AVI (MJPG)" in format_text:
                    video_format = "avi"
                    codec = "MJPG"
                elif "AVI (XVID)" in format_text:
                    video_format = "avi"
                    codec = "XVID"
                elif "MP4" in format_text:
                    video_format = "mp4"
                    codec = "H264"
            
            # Get video quality from SETTINGS (updated by popup)
            video_quality_str = self.settings.get_value("video_quality", "70")
            try:
                video_quality = int(video_quality_str)
            except (ValueError, TypeError):
                video_quality = 70 # Default if setting is invalid
            self.logger.log(f"Read video_quality from settings: {video_quality}%", "DEBUG")
                
            # Apply quality setting to camera thread
            if hasattr(self.camera_thread, 'set_video_quality'):
                self.camera_thread.set_video_quality(video_quality)
            
            # Get whether to use direct streaming from SETTINGS (updated by popup)
            use_direct_streaming = self.settings.get_bool("use_direct_streaming", True) # Use get_bool and correct key

            # Update the camera thread with the current overlays
            if hasattr(self.camera_thread, 'set_overlays') and self.overlays:
                self.camera_thread.set_overlays(self.overlays)
            
            # Start recording in the camera thread
            self.camera_thread.start_recording(
                output_dir=output_dir,
                filename=f"recording_{timestamp}.{video_format}",
                codec=codec,
                use_direct_streaming=use_direct_streaming
            )
            
            # Update UI state
            self.main_window.record_btn.setText("Stop Recording")
            
            # Set recording flag
            self.is_recording = True
            
            self.logger.log(f"Started recording to {output_dir}/recording_{timestamp}.{video_format}")
            
        except Exception as e:
            self.logger.log(f"Error starting recording: {str(e)}")
    
    # --- Motion Detection Handlers --- START
    @pyqtSlot(bool)
    def _handle_motion_enabled_changed(self, state):
        if not self.camera_thread: return
        
        if hasattr(self.camera_thread, 'set_motion_detection_enabled'):
            self.camera_thread.set_motion_detection_enabled(state)
            self.settings.set_value("motion", "motion_detection_enabled", "true" if state else "false")
            self.logger.log(f"Motion detection enabled changed: {state}")
        
        # Update UI state (enable/disable sensitivity/area widgets)
        if self.motion_sensitivity_widget:
            self.motion_sensitivity_widget.setEnabled(state)
        if self.motion_min_area_widget:
            self.motion_min_area_widget.setEnabled(state)
        
        # Reset indicator if disabled
        if not state and self.motion_indicator:
             self.motion_indicator.setStyleSheet("background-color: gray; border-radius: 5px;") # Gray when disabled

    @pyqtSlot()
    def _handle_motion_settings_changed(self):
        if not self.camera_thread: return

        if (hasattr(self.camera_thread, 'update_motion_detection_settings') and
                self.motion_sensitivity_widget and self.motion_min_area_widget):
            
            sensitivity = self.motion_sensitivity_widget.value()
            min_area = self.motion_min_area_widget.value()
            
            # Update thread's detector
            self.camera_thread.update_motion_detection_settings(sensitivity, min_area)
            
            # Save settings
            self.settings.set_value("motion", "motion_detection_sensitivity", str(sensitivity))
            self.settings.set_value("motion", "motion_detection_min_area", str(min_area))
            self.logger.log(f"Motion settings updated: Sensitivity={sensitivity}, Min Area={min_area}")

    @pyqtSlot(bool)
    def _update_motion_indicator(self, detected: bool):
        """Handle motion detection state changes from the camera thread"""
        # First, decide the desired color based on widget state and detection
        color = "gray"  # Default color (disabled/inactive)
        
        # If we have the checkbox widget, check its state
        if self.motion_enabled_widget is not None:
            is_checked = self.motion_enabled_widget.isChecked()
            
            # If motion detection is enabled via the checkbox
            if is_checked:
                # Decide color based on detection state
                if detected:
                    color = "red"    # Motion detected
                else:
                    color = "green"  # No motion detected
        else:
            # No widget reference - try to read from settings directly
            try:
                enabled = self.settings.get_bool("motion_detection_enabled", False)
                if enabled:
                    # Decide color based on detection state
                    if detected:
                        color = "red"    # Motion detected
                    else:
                        color = "green"  # No motion detected
            except Exception as e:
                self.logger.log(f"Error reading motion settings: {e}", "ERROR")
        
        # Finally, set the indicator color if we have a reference to it
        if self.motion_indicator is not None:
            style = f"background-color: {color}; border-radius: 5px;"
            self.motion_indicator.setStyleSheet(style)
    # --- Motion Detection Handlers --- END 

    def get_status(self):
        """
        Check the status of the camera component.
        
        Returns:
            tuple: (StatusState, tooltip_string)
                StatusState: ERROR if camera error
                             OPTIONAL if camera is disabled
                             READY if camera is ready
                tooltip_string: Description of the current status
        """
        # Camera is optional, so if not active, return OPTIONAL
        if not self.is_connected:
            return (StatusState.OPTIONAL, "Camera: Not connected (Optional)")
            
        # Camera is connected and active
        tooltip = f"Camera connected: {self.camera_thread.get_actual_fps():.1f} FPS"
        if self.is_recording:
            tooltip += "\nRecording in progress"
        
        return (StatusState.READY, tooltip)

    def reconnect_camera_buttons(self):
        """Explicitly reconnect all camera tab buttons"""
        # Snapshot button
        if hasattr(self.main_window, 'snapshot_btn'):
            try:
                self.main_window.snapshot_btn.clicked.disconnect()
            except Exception:
                pass
            self.main_window.snapshot_btn.clicked.connect(self.take_snapshot)
            
        # Record button
        if hasattr(self.main_window, 'record_btn'):
            try:
                self.main_window.record_btn.clicked.disconnect()
            except Exception:
                pass
            self.main_window.record_btn.clicked.connect(self.toggle_recording)
            
        # Add overlay button
        if hasattr(self.main_window, 'add_overlay_btn'):
            try:
                self.main_window.add_overlay_btn.clicked.disconnect()
            except Exception:
                pass
            self.main_window.add_overlay_btn.clicked.connect(self.add_overlay)
            
        # Remove overlay button
        if hasattr(self.main_window, 'remove_overlay_btn'):
            try:
                self.main_window.remove_overlay_btn.clicked.disconnect()
            except Exception:
                pass
            self.main_window.remove_overlay_btn.clicked.connect(self.remove_overlay)
            
        # Apply overlay settings button
        if hasattr(self.main_window, 'apply_overlay_settings_btn'):
            try:
                self.main_window.apply_overlay_settings_btn.clicked.disconnect()
            except Exception:
                pass
            self.main_window.apply_overlay_settings_btn.clicked.connect(self.apply_overlay_settings)
            
        # Camera apply settings button
        if hasattr(self.main_window, 'camera_apply_settings_btn'):
            try:
                self.main_window.camera_apply_settings_btn.clicked.disconnect()
            except Exception:
                pass
            self.main_window.camera_apply_settings_btn.clicked.connect(self.apply_camera_settings)
            
        # Camera connect button
        if hasattr(self.main_window, 'camera_connect_btn'):
            try:
                self.main_window.camera_connect_btn.clicked.disconnect()
            except Exception:
                pass
            print("Reconnecting camera connect button")
            # Connect button directly to toggle_camera method
            self.main_window.camera_connect_btn.clicked.connect(self.main_window.connect_camera)
        
        # Focus and exposure controls
        if hasattr(self.main_window, 'camera_tab_manual_focus') and hasattr(self.main_window, 'camera_tab_focus_slider'):
            try:
                self.main_window.camera_tab_manual_focus.stateChanged.disconnect()
            except Exception:
                pass
            self.main_window.camera_tab_manual_focus.stateChanged.connect(self.main_window.apply_camera_focus_exposure)
            
            try:
                self.main_window.camera_tab_focus_slider.valueChanged.disconnect()
                self.main_window.camera_tab_focus_slider.sliderReleased.disconnect()
            except Exception:
                pass
            self.main_window.camera_tab_focus_slider.valueChanged.connect(self.main_window.update_focus_value_label)
            self.main_window.camera_tab_focus_slider.sliderReleased.connect(self.main_window.apply_camera_focus_exposure)
        
        if hasattr(self.main_window, 'camera_tab_manual_exposure') and hasattr(self.main_window, 'camera_tab_exposure_slider'):
            try:
                self.main_window.camera_tab_manual_exposure.stateChanged.disconnect()
            except Exception:
                pass
            self.main_window.camera_tab_manual_exposure.stateChanged.connect(self.main_window.apply_camera_focus_exposure)
            
            try:
                self.main_window.camera_tab_exposure_slider.valueChanged.disconnect()
                self.main_window.camera_tab_exposure_slider.sliderReleased.disconnect()
            except Exception:
                pass
            self.main_window.camera_tab_exposure_slider.valueChanged.connect(self.main_window.update_exposure_value_label)
            self.main_window.camera_tab_exposure_slider.sliderReleased.connect(self.main_window.apply_camera_focus_exposure)

    def update_camera_settings(self, motion_detection=None, motion_sensitivity=None, motion_min_area=None):
        """Update camera settings"""
        try:
            # Update motion detection settings
            if motion_detection is not None:
                self.settings.set_value("motion_detection_enabled", "true" if motion_detection else "false")
                
            if motion_sensitivity is not None:
                self.settings.set_value("motion_detection_sensitivity", str(motion_sensitivity))
                
            if motion_min_area is not None:
                self.settings.set_value("motion_detection_min_area", str(motion_min_area))
                
            # Apply settings to camera thread if it exists
            if self.camera_thread and self.is_connected:
                # Set motion detection properties if the thread has them
                if hasattr(self.camera_thread, 'set_motion_detection'):
                    self.camera_thread.set_motion_detection(
                        motion_detection=motion_detection,
                        sensitivity=motion_sensitivity,
                        min_area=motion_min_area
                    )
                    
            self.logger.log(f"Updated camera settings: motion detection={motion_detection}, sensitivity={motion_sensitivity}, min area={motion_min_area}")
        except Exception as e:
            self.logger.log(f"Error updating camera settings: {str(e)}")
            traceback.print_exc()

    def force_disconnect(self):
        """Force a camera disconnect with explicit UI updates"""
        print("Force disconnecting camera...")
        
        # Set state to disconnected
        self.is_connected = False
        
        # Update button text immediately
        if self.camera_connect_btn:
            self.camera_connect_btn.setText("Connect")
            self.camera_connect_btn.repaint()
        
        # Enable camera selection
        if self.camera_select:
            self.camera_select.setEnabled(True)
        
        # Disable camera-dependent buttons
        if hasattr(self.main_window, 'record_btn'):
            self.main_window.record_btn.setEnabled(False)
        
        if hasattr(self.main_window, 'snapshot_btn'):
            self.main_window.snapshot_btn.setEnabled(False)
        
        if hasattr(self.main_window, 'add_overlay_btn'):
            self.main_window.add_overlay_btn.setEnabled(False)
        
        # Clear camera display
        if self.camera_label:
            self.camera_label.clear()
            self.camera_label.setText("No camera connected")
            self.camera_label.repaint()
        
        # Only try to disconnect the camera thread if it exists
        if self.camera_thread:
            try:
                # Stop any recording
                if hasattr(self.camera_thread, 'recording') and self.camera_thread.recording:
                    self.camera_thread.stop_recording()
                
                # Disconnect camera
                self.camera_thread.disconnect()
                
                # Optionally wait for the thread to finish
                if hasattr(self.camera_thread, 'wait') and self.camera_thread.isRunning():
                    if not self.camera_thread.wait(3000):  # 3 second timeout
                        print("Camera thread did not stop naturally, terminating...")
                        self.camera_thread.terminate()
                        self.camera_thread.wait(1000)
            except Exception as e:
                print(f"Error during force disconnect: {str(e)}")
        
        print("Force disconnect completed")