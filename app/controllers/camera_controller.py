"""
Camera Controller

Manages camera operations, recording, and overlays.
"""
import sys
import traceback
from PyQt6.QtCore import QObject, pyqtSlot, Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QImage, QPixmap, QColor, QPainter, QBrush
from PyQt6.QtWidgets import QComboBox, QPushButton, QLabel, QMessageBox, QCheckBox, QSlider, QSpinBox
import os
import time
from datetime import datetime
import cv2
import numpy as np
import random
import threading

from app.core.direct_camera import DirectCameraThread  # New direct camera implementation
from app.core.overlay_manager import BaseOverlay, TextOverlay, TimestampOverlay, SensorOverlay, RectangleOverlay, MotionOverlay
from app.core.interfaces.ndi_interface import NDI_AVAILABLE, NDISourceFinder

from app.settings.settings_manager import SettingsManager
from app.core.logger import Logger
from app.utils.common_types import StatusState

class CameraController(QObject):
    """Controller for managing camera operations"""

    # Signal that will be emitted when the camera status changes
    status_changed = pyqtSignal()
    # Signal emitted when a snapshot is taken
    snapshot_taken = pyqtSignal(str)

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
        self.camera_refresh_btn = getattr(self.main_window, 'camera_refresh_btn', None)
        self.camera_mode = getattr(self.main_window, 'camera_mode', None)
        
        # Initialize internal reference to the UI dropdown
        self._ui_dropdown = None
        
        # Try multiple names for the camera dropdown
        print(f"DEBUG CTRL: CameraController init with main_window (id={id(self.main_window)}):")
        for name in ['camera_source_combo', 'camera_id_dropdown', 'camera_id']:
            val = getattr(self.main_window, name, None)
            if val is not None:
                self._ui_dropdown = val
                print(f"CameraController: Linked _ui_dropdown via main_window.{name}")
                break
        
        if self._ui_dropdown is None and hasattr(self.main_window, 'findChild'):
            try:
                for name in ['camera_source_dropdown_widget', 'camera_source_dropdown', 'camera_id']:
                    val = self.main_window.findChild(QComboBox, name)
                    if val is not None:
                        self._ui_dropdown = val
                        print(f"CameraController: Linked _ui_dropdown via findChild('{name}')")
                        break
            except Exception as e:
                print(f"DEBUG CTRL: findChild failed: {e}")
        
        if self._ui_dropdown is not None:
            # Compatibility for other parts of the code that might still use this name
            self.camera_select = self._ui_dropdown
            print(f"CameraController: Successfully found camera dropdown: {self._ui_dropdown}")
        else:
            self.camera_select = None
            print("CameraController: Error - Could not find camera dropdown widget on main_window!")
        
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
        self.show_on_dashboard = True # Flag to control dashboard display
        self.current_frame = None
        self.should_reconnect = False
        
        # Mouse interaction state
        self.drag_start_pos = None
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.original_width = 1280
        self.original_height = 720
        self.overlays = []
        self.selected_overlay = None

        # Timer for updating sensor overlay data (pushing data to thread)
        self.sensor_push_timer = QTimer()
        self.sensor_push_timer.timeout.connect(self.push_sensor_data_to_thread)
        self.sensor_push_timer.start(200)  # Update 5 times per second (200ms)
        
        # Timer for clearing automation events after they've been processed
        self.event_clear_timer = QTimer()
        self.event_clear_timer.timeout.connect(self._clear_automation_events)
        self.event_clear_timer.setSingleShot(True)
        
        # Track previous motion detection state for edge detection
        self._last_motion_detected = False
        
        # Timer for NDI source discovery
        self.ndi_discovery_timer = QTimer()
        self.ndi_discovery_timer.timeout.connect(self.discover_ndi_sources)
        
        # Initialize camera mode UI state
        if self.camera_mode:
            # Default to Local Camera (0)
            self.camera_mode.blockSignals(True)
            self.camera_mode.setCurrentIndex(0)
            self.camera_mode.blockSignals(False)
            self.refresh_camera_list()
        
        # Initialize camera lazily after the event loop starts to keep the
        # main window paint fast.
        QTimer.singleShot(1500, self.init_camera)
        
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
        
    def _update_run_metadata(self, updates: dict):
        """Merge video-related metadata into the current run record."""
        if not updates:
            return
        try:
            if hasattr(self.main_window, "project_controller"):
                run_dir = self.main_window.project_controller.get_current_run_directory()
                if run_dir:
                    self.main_window.project_controller.update_run_metadata(run_dir, updates)
        except Exception:
            # Metadata persistence must not break recording
            pass

    def _append_video_segment_metadata(self, segment: dict):
        """Append or replace a video segment entry in run metadata."""
        if not segment:
            return
        try:
            project_controller = getattr(self.main_window, "project_controller", None)
            if not project_controller:
                return
            run_dir = project_controller.get_current_run_directory()
            if not run_dir:
                return

            meta = project_controller.get_run_metadata(run_dir) or {}
            videos = meta.get("videos", [])
            path = segment.get("path")
            # Replace any existing segment with the same path
            if path:
                videos = [v for v in videos if v.get("path") != path]
            videos.append(segment)
            meta["videos"] = videos
            project_controller.update_run_metadata(run_dir, meta)
        except Exception:
            # Metadata persistence must not break recording
            pass

    def _add_automation_event(self, event_name: str):
        """Add an event to the automation context for trigger detection"""
        if not hasattr(self.main_window, 'automation_controller'):
            return
        
        try:
            # Initialize events dictionary if it doesn't exist
            if 'events' not in self.main_window.automation_controller.manager.app_context:
                self.main_window.automation_controller.manager.app_context['events'] = set()
            
            # Add event to the context
            events = self.main_window.automation_controller.manager.app_context['events']
            if isinstance(events, set):
                events.add(event_name)
            elif isinstance(events, dict):
                events[event_name] = True
            else:
                # Convert to set if it's not the right type
                self.main_window.automation_controller.manager.app_context['events'] = {event_name}
            
            # Update the context for running sequences
            self.main_window.automation_controller.update_context({})
            
            # Schedule event clearing after 2 seconds (enough time for triggers to detect it)
            # Note: motion_detected events are managed manually and should not be cleared by timer
            if event_name != 'motion_detected':
                if self.event_clear_timer.isActive():
                    self.event_clear_timer.stop()
                self.event_clear_timer.start(2000)  # Clear events after 2 seconds
            
        except Exception as e:
            # Don't break functionality if automation context update fails
            if hasattr(self, 'logger'):
                self.logger.log(f"Error updating automation context with event '{event_name}': {e}", "ERROR")
    
    def _remove_automation_event(self, event_name: str):
        """Remove a specific event from the automation context"""
        if not hasattr(self.main_window, 'automation_controller'):
            return
        
        try:
            if 'events' in self.main_window.automation_controller.manager.app_context:
                events = self.main_window.automation_controller.manager.app_context['events']
                if isinstance(events, set):
                    events.discard(event_name)
                elif isinstance(events, dict):
                    events.pop(event_name, None)
                
                # Update the context for running sequences
                self.main_window.automation_controller.update_context({})
        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.log(f"Error removing automation event '{event_name}': {e}", "ERROR")
    
    def _clear_automation_events(self):
        """Clear automation events from the context after they've been processed"""
        if not hasattr(self.main_window, 'automation_controller'):
            return
        
        try:
            if 'events' in self.main_window.automation_controller.manager.app_context:
                events = self.main_window.automation_controller.manager.app_context['events']
                if isinstance(events, set):
                    events.clear()
                elif isinstance(events, dict):
                    events.clear()
                # Update context to notify sequences
                self.main_window.automation_controller.update_context({})
        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.log(f"Error clearing automation events: {e}", "ERROR")

    def _finalize_video_segment_metadata(self, end_ts: float, start_ts: float | None = None):
        """Update the latest video segment with end/duration information."""
        try:
            project_controller = getattr(self.main_window, "project_controller", None)
            if not project_controller:
                return
            run_dir = project_controller.get_current_run_directory()
            if not run_dir:
                return

            meta = project_controller.get_run_metadata(run_dir) or {}
            videos = meta.get("videos", [])
            path = getattr(self.camera_thread, "output_file", "") if hasattr(self, "camera_thread") else ""

            updated = False
            for seg in videos:
                if path and seg.get("path") == path:
                    seg["end_epoch"] = end_ts
                    if start_ts:
                        seg["duration_sec"] = max(0.0, end_ts - start_ts)
                        seg["start_epoch"] = seg.get("start_epoch") or start_ts
                    updated = True
                    break

            if not updated and path:
                videos.append(
                    {
                        "path": path,
                        "start_epoch": start_ts,
                        "end_epoch": end_ts,
                        "duration_sec": max(0.0, end_ts - start_ts) if start_ts else None,
                    }
                )

            updates = {
                "videos": videos,
                "video_path": path,
                "video_end_epoch": end_ts,
            }
            if start_ts:
                updates["video_duration_sec"] = max(0.0, end_ts - start_ts)
                updates["video_start_epoch"] = start_ts

            project_controller.update_run_metadata(run_dir, updates)
        except Exception:
            pass

    # Dashboard preview toggle (called from main_window.switch_dashboard_camera_source)
    def set_dashboard_display(self, enabled: bool):
        """
        Set whether the camera feed should be displayed on the dashboard.
        """
        self.show_on_dashboard = enabled
        
        # If disabling, clear the dashboard label
        if not enabled and hasattr(self.main_window, 'dashboard_camera_label'):
            replay_mode_active = getattr(self.main_window, 'replay_mode_enabled', False)
            if not replay_mode_active:
                self.main_window.dashboard_camera_label.setText("No camera connected")
                empty_pixmap = QPixmap(320, 240)
                empty_pixmap.fill(Qt.GlobalColor.black)
                self.main_window.dashboard_camera_label.setPixmap(empty_pixmap)
        return
        
    def push_sensor_data_to_thread(self):
        """Push latest sensor values to the camera thread for overlays"""
        if not self.camera_thread or not self.camera_thread.isRunning():
            return
            
        sensor_overlays = [o for o in self.overlays if isinstance(o, SensorOverlay)]
        if not sensor_overlays:
            return
            
        if not hasattr(self.main_window, 'sensor_controller') or not self.main_window.sensor_controller:
            return
            
        for overlay in sensor_overlays:
            sensor = self.main_window.sensor_controller.get_sensor_by_name(overlay.sensor_name)
            if sensor and hasattr(sensor, 'current_value') and sensor.current_value is not None:
                try:
                    value = f"{float(sensor.current_value):.2f}"
                except (ValueError, TypeError):
                    value = str(sensor.current_value)
                
                unit = getattr(sensor, 'unit', "")
                self.camera_thread.update_sensor_overlay_data(overlay.sensor_name, value, unit)

    def init_camera(self):
        """Initialize the camera settings and populate the list"""
        try:
            print("CameraController: init_camera starting...")
            
            # Ensure we have the latest UI references
            if getattr(self, 'camera_select', None) is None:
                for name in ['camera_source_combo', 'camera_id_dropdown', 'camera_id']:
                    val = getattr(self.main_window, name, None)
                    if val is not None:
                        self.camera_select = val
                        print(f"CameraController: init_camera linked dropdown via '{name}'")
                        break
            
            # Try to refresh the list immediately
            self.refresh_camera_list()
            
            # Create the camera thread if it doesn't exist
            if not hasattr(self, 'camera_thread') or not self.camera_thread:
                print("Creating new camera thread...")
                from app.core.direct_camera import DirectCameraThread
                self.camera_thread = DirectCameraThread(main_window=self.main_window)
                # Connect signals
                self.camera_thread.status_update.connect(self.handle_connection_status)
                self.camera_thread.frame_captured.connect(self.update_frame_display)
                self.camera_thread.recording_status_signal.connect(self.handle_recording_status)
                if hasattr(self.camera_thread, 'motion_detected_signal'):
                    self.camera_thread.motion_detected_signal.connect(self._update_motion_indicator)
                print("CameraController: DirectCameraThread created and connected.")
            
            # Schedule a delayed refresh as well, because QMediaDevices can be slow
            QTimer.singleShot(2500, self.refresh_camera_list)
            
            print("CameraController: init_camera routine complete.")
        except Exception as e:
            print(f"CameraController: Error in init_camera: {e}")
            import traceback
            traceback.print_exc()
            self.camera_thread.framerate_warning_signal.connect(self.handle_framerate_warning)
            
            print("Camera thread initialized")
            
            # Set initial motion detection state from settings
            if self.settings:
                # Read settings
                enable_motion = self.settings.get_bool("motion_detection_enabled", False)
                motion_sensitivity = self.settings.get_int("motion_detection_sensitivity", 20)
                motion_min_area = self.settings.get_int("motion_detection_min_area", 500)
                
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
        if self.camera_select is None:
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
            
            # Note: Button text is updated by handle_connection_status which is called
            # by connect_camera/disconnect_camera, so we don't need to set it here again
            
        except Exception as e:
            self.logger.log(f"Error toggling camera: {str(e)}", "ERROR")
            traceback.print_exc()
    
    def _handle_camera_mode_changed(self, index):
        """Handle change in camera mode (Local vs NDI)."""
        # index 0: Local Camera, index 1: NDI Source
        is_ndi_mode = (index == 1)
        
        # Disconnect current camera if running to prevent driver conflicts
        if self.is_connected:
            self.disconnect_camera()
        
        # Refresh the source list based on mode
        self.refresh_camera_list()
        
        # Update discovery timer
        if is_ndi_mode and NDI_AVAILABLE:
            # Re-enable discovery for NDI mode
            if "NDI_SKIP_LOCAL_SOURCES" in os.environ:
                del os.environ["NDI_SKIP_LOCAL_SOURCES"]
            
            if not self.ndi_discovery_timer.isActive():
                self.ndi_discovery_timer.start(5000)
        else:
            self.ndi_discovery_timer.stop()

    def refresh_camera_list(self):
        """Populate the camera selection dropdown with friendly names and filter virtual cameras."""
        # Ensure we have the widget reference
        if getattr(self, '_ui_dropdown', None) is None:
            print(f"DEBUG REFRESH: Re-trying to find dropdown on main_window (id={id(self.main_window)})")
            for name in ['camera_source_combo', 'camera_id_dropdown', 'camera_id']:
                val = getattr(self.main_window, name, None)
                if val is not None:
                    self._ui_dropdown = val
                    self.camera_select = val
                    print(f"CameraController: Successfully re-linked _ui_dropdown via '{name}'")
                    break
            
            if self._ui_dropdown is None and hasattr(self.main_window, 'findChild'):
                print("DEBUG REFRESH: Trying findChild...")
                for name in ['camera_source_dropdown_widget', 'camera_source_dropdown', 'camera_id']:
                    val = self.main_window.findChild(QComboBox, name)
                    if val is not None:
                        self._ui_dropdown = val
                        self.camera_select = val
                        print(f"CameraController: Found _ui_dropdown via findChild('{name}')")
                        break
        
        if self._ui_dropdown is None:
            print("CameraController: refresh_camera_list failed - _ui_dropdown is still None")
            return
            
        print("CameraController: Refreshing camera list...")
        # Store current selection to restore it if possible
        current_data = None
        try:
            current_data = self._ui_dropdown.currentData()
        except Exception:
            pass
            
        self._ui_dropdown.clear()
        
        # Determine mode
        is_ndi_mode = False
        if getattr(self.main_window, 'camera_mode', None) is not None:
            is_ndi_mode = (self.main_window.camera_mode.currentIndex() == 1)
            
        if is_ndi_mode:
            self._ui_dropdown.addItem("Searching for NDI sources...")
            if NDI_AVAILABLE:
                self.discover_ndi_sources()
        else:
            # Simplified indexing for reliability as requested
            print("CameraController: Populating available camera indices...")
            try:
                from PyQt6.QtMultimedia import QMediaDevices
                devices = QMediaDevices.videoInputs()
                num_devices = len(devices)
                print(f"CameraController: QMediaDevices found {num_devices} total inputs")
                
                # Show detected indices first
                for i in range(max(num_devices, 1)):
                    name = "Unknown Device"
                    if i < len(devices):
                        name = devices[i].description()
                    
                    display_text = f"Camera {i}"
                    # Still keep the name in the tooltip so the user can at least see what it MIGHT be
                    tip = f"Reported Name: {name}\nNote: Windows index mapping can be inconsistent."
                    
                    self._ui_dropdown.addItem(display_text, i)
                    self._ui_dropdown.setItemData(self._ui_dropdown.count()-1, tip, Qt.ItemDataRole.ToolTipRole)
                    print(f"CameraController: Added {display_text} (Name: {name})")
                
                # Add extra slots just in case detection missed something
                self._ui_dropdown.insertSeparator(self._ui_dropdown.count())
                for i in range(max(num_devices, 1), 10):
                    self._ui_dropdown.addItem(f"Camera {i} (Unchecked)", i)
                    self._ui_dropdown.setItemData(self._ui_dropdown.count()-1, "Direct access to index. Use if detection failed.", Qt.ItemDataRole.ToolTipRole)
                    
            except Exception as e:
                print(f"CameraController: Error listing cameras: {e}")
                # Ultimate fallback
                for i in range(10):
                    self._ui_dropdown.addItem(f"Camera {i}", i)
            
            # Restore selection
            if current_data is not None:
                idx = self._ui_dropdown.findData(current_data)
                if idx >= 0:
                    self._ui_dropdown.setCurrentIndex(idx)
        
        print(f"CameraController: Refresh complete. Final count: {self._ui_dropdown.count()}")

    def discover_ndi_sources(self):
        """Discover NDI sources on the network and update UI."""
        if not NDI_AVAILABLE:
            return
            
        # Only discover if we are in NDI mode
        if self.camera_mode and self.camera_mode.currentIndex() != 1:
            return
            
        if not hasattr(self, '_ndi_finder'):
            self._ndi_finder = NDISourceFinder()
            
        sources = self._ndi_finder.get_sources()
        
        # Collect current NDI items in dropdown
        ndi_items = {}
        has_searching_msg = False
        searching_msg_index = -1

        selector = getattr(self, '_camera_selector', self.camera_select)
        if selector is None:
            return
            
        for i in range(selector.count()):
            text = selector.itemText(i)
            if text == "Searching for NDI sources...":
                has_searching_msg = True
                searching_msg_index = i
            elif text.startswith("NDI:"):
                ndi_items[text] = i
        
        # Track which NDI sources are still present
        active_ndi_texts = set()
        
        new_sources_found = False
        for s in sources:
            source_name = getattr(s, 'ndi_name', str(s))
            display_text = f"NDI: {source_name}"
            active_ndi_texts.add(display_text)
            
            if display_text not in ndi_items:
                # Add new NDI source
                selector.addItem(display_text, s) # Store the source object as userData
                self.logger.log(f"Discovered NDI source: {display_text}", "INFO")
                new_sources_found = True
        
        # Remove "Searching..." message if we found sources or if we've been searching
        if has_searching_msg and (new_sources_found or len(sources) > 0):
            selector.removeItem(searching_msg_index)

    def connect_camera(self):
        """Connect to the camera"""
        try:
            # Ensure we have the widget reference
            if self.camera_select is None:
                for name in ['camera_source_combo', 'camera_id_dropdown', 'camera_id']:
                    val = getattr(self.main_window, name, None)
                    if val is not None:
                        self.camera_select = val
                        break
            
            if self.camera_select is None:
                print("CameraController: Cannot connect - camera_select is None")
                return
                
            # Get camera selection from UI
            if hasattr(self.camera_select, 'currentText'):
                current_text = self.camera_select.currentText()
                if current_text == "Searching for NDI sources..." or current_text == "" or current_text == "No physical cameras found":
                    return
                # Get index or NDI source object from userData
                camera_id = self.camera_select.currentData()
                if camera_id is None:
                    camera_id = current_text
            else:
                # Fallback for generic widgets
                camera_id = getattr(self.camera_select, 'value', lambda: 0)()
            
            # Check if camera is being used as an optical sensor
            # (Only applies to local cameras with integer IDs)
            try:
                local_cam_id = int(camera_id)
                if hasattr(self.main_window, 'sensor_controller') and self.main_window.sensor_controller:
                    if self.main_window.sensor_controller.is_camera_used_as_sensor(local_cam_id):
                        from PyQt6.QtWidgets import QMessageBox
                        QMessageBox.warning(
                            self.main_window,
                            "Camera in Use",
                            f"Camera {local_cam_id} is currently being used as an Optical Sensor.\n\n"
                            "Please disconnect the optical sensor first, or select a different camera."
                        )
                        return
            except (ValueError, TypeError):
                # It's an NDI source or invalid ID, ignore sensor check for now
                pass
            
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
            self.current_camera_id = camera_id  # Store for use in handle_connection_status
            thread_started = self.camera_thread.connect(camera_id, resolution, fps)
            
            if thread_started:
                # Thread started successfully; connection happens in the background.
                # handle_connection_status will be called when connection is established.
                self.logger.log(f"Starting background connection to camera {camera_id}...")
            else:
                print("Failed to start camera thread")
                self.is_connected = False
                self.handle_connection_status(False, "Failed to start camera thread")
                
                # Reset label text if thread failed to start
                if self.camera_label:
                    self.camera_label.setText("No camera connected")
            
        except Exception as e:
            print(f"Error initiating camera connection: {str(e)}")
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
            
            if not connected and "black frame" in message.lower():
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self.main_window,
                    "Camera Signal Issue",
                    "The selected camera is not sending a valid image. This can happen if the device is being used by another application.\n\n"
                    "Please ensure your webcam is not in use elsewhere and try another source from the list if available."
                )

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
                
                # --- ASYNC SETUP: Move setup logic here since connect_camera is now async ---
                camera_id = getattr(self, 'current_camera_id', 0)
                
                # Add default timestamp overlay if it doesn't exist
                timestamp_exists = any(getattr(o, 'get_type', lambda: '')() == 'timestamp' for o in self.overlays)
                if not timestamp_exists:
                    from app.core.overlay_manager import TimestampOverlay
                    overlay_count = len(self.overlays) + 1
                    overlay_name = f"Timestamp {overlay_count}"
                    new_overlay = TimestampOverlay(overlay_count, overlay_name, "%Y-%m-%d %H:%M:%S")
                    
                    # Set requested defaults
                    new_overlay.position = (0.70, 0.98)  # Adjusted for font scale 1.0 to avoid clipping
                    new_overlay.font_scale = 1.0          # Set font scale to 1.0 as requested
                    new_overlay.text_color = (255, 255, 255)  # White (BGR)
                    new_overlay.bg_color = (0, 0, 0)      # Black (BGR)
                    new_overlay.bg_alpha = 0.5            # 50% opacity
                    
                    self.overlays.append(new_overlay)
                    self.update_overlay_selector()
                    
                    # Pass overlays to camera thread
                    if self.camera_thread and hasattr(self.camera_thread, 'set_overlays'):
                        self.camera_thread.set_overlays(self.overlays)
                    
                    self.logger.log(f"Added default timestamp overlay to camera {camera_id}")

                # -- Apply Motion Detection Settings --
                try:
                    # Read settings from SettingsModel
                    enabled = self.settings.get_bool("motion_detection_enabled", False)
                    sensitivity = self.settings.get_int("motion_detection_sensitivity", 20)
                    min_area = self.settings.get_int("motion_detection_min_area", 500)
                    
                    # Apply to thread
                    if hasattr(self.camera_thread, 'set_motion_detection_enabled'):
                        self.camera_thread.set_motion_detection_enabled(enabled)
                    if hasattr(self.camera_thread, 'update_motion_detection_settings'):
                        self.camera_thread.update_motion_detection_settings(sensitivity, min_area)
                    
                    # Update UI elements to match settings
                    if hasattr(self, 'motion_enabled_widget') and self.motion_enabled_widget:
                        self.motion_enabled_widget.blockSignals(True)
                        self.motion_enabled_widget.setChecked(enabled)
                        self.motion_enabled_widget.blockSignals(False)
                        if hasattr(self, 'motion_sensitivity_widget') and self.motion_sensitivity_widget: 
                            self.motion_sensitivity_widget.setEnabled(enabled)
                        if hasattr(self, 'motion_min_area_widget') and self.motion_min_area_widget: 
                            self.motion_min_area_widget.setEnabled(enabled)
                    
                    # Set initial indicator state
                    if hasattr(self, 'motion_indicator') and self.motion_indicator:
                        style = "background-color: gray; border-radius: 5px;"
                        if enabled:
                            style = "background-color: green; border-radius: 5px;"
                        self.motion_indicator.setStyleSheet(style)
                            
                    self.logger.log(f"Applied motion settings on connect: enabled={enabled}, sens={sensitivity}, area={min_area}", "DEBUG")
                except Exception as motion_err:
                    self.logger.log(f"Error applying motion settings on connect: {motion_err}", "ERROR")

                # Update camera select enabled state
                if getattr(self, 'camera_select', None) is not None:
                    self.camera_select.setEnabled(False)
            
            if not connected:
                # Enable camera select when disconnected
                if getattr(self, 'camera_select', None) is not None:
                    self.camera_select.setEnabled(True)

                if self.camera_label:
                    # Set text for disconnected state
                    self.camera_label.setText("No camera connected")
                    
                    # Clear label with black pixmap
                    empty_pixmap = QPixmap(640, 480)
                    empty_pixmap.fill(Qt.GlobalColor.black)
                    self.camera_label.setPixmap(empty_pixmap)
                
                # Also clear dashboard camera label if it exists and we're currently showing on dashboard
                if hasattr(self.main_window, 'dashboard_camera_label') and self.show_on_dashboard:
                    # Check if replay mode is NOT active before clearing dashboard label
                    replay_mode_active = getattr(self.main_window, 'replay_mode_enabled', False)
                    if not replay_mode_active:
                        self.main_window.dashboard_camera_label.setText("No camera connected")
                        # Clear label with black pixmap
                        empty_pixmap = QPixmap(320, 240)
                        empty_pixmap.fill(Qt.GlobalColor.black)
                        self.main_window.dashboard_camera_label.setPixmap(empty_pixmap)
                
        except Exception as e:
            print(f"Error handling connection status: {str(e)}")
            traceback.print_exc()
    
    @pyqtSlot(QPixmap)
    def update_frame_display(self, pixmap):
        """Update the camera display with the captured frame"""
        try:
            # Don't update dashboard camera label if replay mode is active
            replay_mode_active = False
            if hasattr(self.main_window, 'replay_mode_enabled'):
                replay_mode_active = getattr(self.main_window, 'replay_mode_enabled', False)
            
            if self.camera_label:
                # Save the current frame for potential processing
                self.current_frame = pixmap.copy()
                
                # Scale the pixmap to fit the display while maintaining aspect ratio
                # Use FastTransformation for smoother live performance (Optimization 1)
                scaled_pixmap = pixmap.scaled(self.camera_label.width(), self.camera_label.height(), 
                                            Qt.AspectRatioMode.KeepAspectRatio, 
                                            Qt.TransformationMode.FastTransformation)
                
                self.camera_label.setPixmap(scaled_pixmap)
                
                # Update the dashboard camera preview if it exists and replay is not active
                if hasattr(self.main_window, 'dashboard_camera_label') and not replay_mode_active and self.show_on_dashboard:
                    # Only scale and update if the dashboard label is actually visible (Optimization 3)
                    if self.main_window.dashboard_camera_label.isVisible():
                        # Create a smaller version for the dashboard
                        dashboard_pixmap = pixmap.scaled(self.main_window.dashboard_camera_label.width(), 
                                                        self.main_window.dashboard_camera_label.height(),
                                                        Qt.AspectRatioMode.KeepAspectRatio, 
                                                        Qt.TransformationMode.FastTransformation)
                        
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
                
                # Update FPS information in status bar and camera tab if available
                if self.camera_thread and hasattr(self.camera_thread, 'get_actual_fps'):
                    actual_fps = self.camera_thread.get_actual_fps()
                    target_fps = self.camera_thread.fps
                    if actual_fps > 0:
                        self.main_window.statusBar().showMessage(f"FPS: {actual_fps:.1f}")
                        if hasattr(self.main_window, 'camera_fps_display'):
                            self.main_window.camera_fps_display.setText(f"{actual_fps:.1f} / {target_fps:.1f} FPS")

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
    
    @pyqtSlot(float, float)
    def handle_framerate_warning(self, expected_fps, actual_fps):
        """Handle framerate warning when camera doesn't deliver expected framerate"""
        try:
            # We no longer show a warning message box to the user.
            # The UI now displays actual vs target FPS.
            self.logger.log(f"Framerate lower than expected: Expected {expected_fps:.1f} FPS, but camera is delivering {actual_fps:.1f} FPS. Frames will be duplicated to maintain sync.", "INFO")
        except Exception as e:
            print(f"Error logging framerate warning: {str(e)}")
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
            end_ts = time.time()
            start_ts = getattr(self.camera_thread, "recording_start_time", None)
            video_meta = {
                "video_end_epoch": end_ts,
            }
            if start_ts:
                video_meta["video_duration_sec"] = max(0.0, end_ts - start_ts)
            self._update_run_metadata(video_meta)
            # Finalize the latest segment entry with end/duration
            self._finalize_video_segment_metadata(end_ts, start_ts)
            
            # Update UI state
            self.main_window.record_btn.setText("Start Recording")
            
            # Set recording flag
            self.is_recording = False
            
            self.logger.log("Stopped recording")
            
            # Add event to dashboard and graph
            if hasattr(self.main_window, 'add_dashboard_event'):
                self.main_window.add_dashboard_event("Camera recording stopped", "WARNING")
            
            # Add recording_stopped event to automation context
            self._add_automation_event('recording_stopped')
            
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
            
        # Connect camera refresh button
        if hasattr(self.main_window, 'camera_refresh_btn'):
            print("CameraController: Connecting refresh button signal")
            try:
                self.main_window.camera_refresh_btn.clicked.disconnect()
            except Exception:
                pass
            self.main_window.camera_refresh_btn.clicked.connect(self.refresh_camera_list)
        else:
            print("CameraController: Warning - main_window has no camera_refresh_btn attribute")

        # Connect camera mode selection
        if hasattr(self.main_window, 'camera_mode'):
            try:
                self.main_window.camera_mode.currentIndexChanged.disconnect()
            except Exception:
                pass
            self.main_window.camera_mode.currentIndexChanged.connect(self._handle_camera_mode_changed)

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
            self.main_window.camera_tab_focus_slider.valueChanged.connect(self.main_window.apply_camera_focus_exposure)
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
            self.main_window.camera_tab_exposure_slider.valueChanged.connect(self.main_window.apply_camera_focus_exposure)
            self.main_window.camera_tab_exposure_slider.sliderReleased.connect(self.main_window.apply_camera_focus_exposure)

        # Connect motion detection controls
        if self.motion_enabled_widget:
            try:
                self.motion_enabled_widget.stateChanged.disconnect()
            except Exception:
                pass
            self.motion_enabled_widget.stateChanged.connect(lambda state: self._handle_motion_enabled_changed(state == 2))
            
        if self.motion_sensitivity_widget:
            try:
                self.motion_sensitivity_widget.valueChanged.disconnect()
            except Exception:
                pass
            self.motion_sensitivity_widget.valueChanged.connect(self._handle_motion_settings_changed)
            
        if self.motion_min_area_widget:
            try:
                self.motion_min_area_widget.valueChanged.disconnect()
            except Exception:
                pass
            self.motion_min_area_widget.valueChanged.connect(self._handle_motion_settings_changed)
    
    def take_snapshot(self):
        """Take a snapshot from the camera
        
        Returns:
            str: Path to the saved snapshot if successful, None otherwise
        """
        try:
            if not self.camera_thread or not self.is_connected:
                self.logger.log("Cannot take snapshot: No camera connected")
                return None

            if not self.current_frame:
                self.logger.log("Cannot take snapshot: No frame available")
                return None

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

            # Generate filename with timestamp (including milliseconds to avoid collisions)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = os.path.join(snapshots_dir, f"snapshot_{timestamp}.png")

            # CRITICAL: Convert QPixmap to QImage BEFORE passing to background thread.
            # QPixmap is tied to window system resources and is NOT thread-safe for saving
            # or access in non-UI threads. QImage is a pure data representation and is safe.
            # This fixes potential UI hangs and slowness during snapshots.
            image_to_save = self.current_frame.toImage()
            
            def save_frame_async(image, path, logger, signal_emitter=None):
                try:
                    image.save(path, "PNG")
                    if logger:
                        logger.log(f"Snapshot saved: {path}")
                    else:
                        print(f"Snapshot saved: {path}")
                    
                    # Emit signal AFTER saving is complete
                    if signal_emitter:
                        signal_emitter.emit(path)
                except Exception as e:
                    if logger:
                        logger.log(f"Error saving snapshot in background: {str(e)}", "ERROR")
                    else:
                        print(f"Error saving snapshot in background: {str(e)}")

            save_thread = threading.Thread(
                target=save_frame_async, 
                args=(image_to_save, filename, getattr(self, 'logger', None), self.snapshot_taken),
                daemon=True
            )
            save_thread.start()

            # Optionally, if the camera is recording to video and we need to show confirmation in UI
            if hasattr(self.main_window, 'statusBar'):
                self.main_window.statusBar().showMessage(f"Snapshot saved to {os.path.basename(os.path.dirname(snapshots_dir))}/Snapshots", 3000)
            
            return filename

        except Exception as e:
            self.logger.log(f"Error taking snapshot: {str(e)}", "ERROR")
            import traceback
            self.logger.log(traceback.format_exc(), "ERROR")
            return None
    
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
            overlay_type_combo.addItems(["Text", "Timestamp", "Rectangle", "Sensor", "Motion Indicator"])
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
                text_input.setVisible(selected_type in ["Text", "Timestamp"])
                sensor_combo.setVisible(selected_type == "Sensor")
                
                if selected_type == "Text":
                    text_layout.itemAt(0).widget().setText("Text:")
                    if text_input.text() == "%Y-%m-%d %H:%M:%S" or not text_input.text():
                        text_input.setText("New Overlay")
                elif selected_type == "Timestamp":
                    text_layout.itemAt(0).widget().setText("Format:")
                    if text_input.text() == "New Overlay" or not text_input.text():
                        text_input.setText("%Y-%m-%d %H:%M:%S")
                else:
                    text_layout.itemAt(0).widget().setText("Name:") # Fallback
                
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
            overlay_name = f"{overlay_type.capitalize()} {overlay_count}"
            rel_pos = (0.05, 0.05 + (overlay_count - 1) * 0.05)

            if overlay_type == "text":
                new_overlay = TextOverlay(overlay_count, overlay_name, text_input.text())
            elif overlay_type == "timestamp":
                new_overlay = TimestampOverlay(overlay_count, overlay_name, text_input.text() if text_input.text() else "%Y-%m-%d %H:%M:%S")
                # Set requested defaults for timestamp overlay
                new_overlay.position = (0.70, 0.98)  # Adjusted for font scale 1.0 to avoid clipping
                new_overlay.font_scale = 1.0          # Set font scale to 1.0 as requested
                new_overlay.text_color = (255, 255, 255)  # White (BGR)
                new_overlay.bg_color = (0, 0, 0)      # Black (BGR)
                new_overlay.bg_alpha = 0.5            # 50% opacity
            elif overlay_type == "rectangle":
                new_overlay = RectangleOverlay(overlay_count, overlay_name, 0.15, 0.1)
            elif overlay_type == "sensor":
                selected_sensor = sensor_combo.currentText()
                new_overlay = SensorOverlay(overlay_count, overlay_name, selected_sensor)
            elif overlay_type == "motion indicator":
                new_overlay = MotionOverlay(overlay_count, overlay_name)
            else:
                return

            new_overlay.position = rel_pos
            if overlay_type != "timestamp":
                new_overlay.text_color = (0, 255, 0)  # BGR format (Green)
                new_overlay.bg_color = (0, 0, 0)      # BGR format (Black)
                new_overlay.bg_alpha = 0.5
            else:
                # Use customized defaults for timestamp
                new_overlay.position = (0.70, 0.98)
                new_overlay.font_scale = 1.0
                new_overlay.text_color = (255, 255, 255)
                new_overlay.bg_color = (0, 0, 0)
                new_overlay.bg_alpha = 0.5
            
            self.overlays.append(new_overlay)
            self.selected_overlay = new_overlay
            
            # Update overlay selector in UI
            self.update_overlay_selector()
            
            # Pass overlays to camera thread
            if self.camera_thread and hasattr(self.camera_thread, 'set_overlays'):
                self.camera_thread.set_overlays(self.overlays)
            
            # Save overlays to run directory
            self.save_overlays_to_run()
            
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
            if isinstance(overlay, BaseOverlay):
                self.main_window.overlay_selector.addItem(overlay.name)
            else:
                self.main_window.overlay_selector.addItem(overlay["name"])
        
        # Set the current item to the selected overlay
        if self.selected_overlay:
            try:
                index = self.overlays.index(self.selected_overlay)
                self.main_window.overlay_selector.setCurrentIndex(index)
            except ValueError:
                self.main_window.overlay_selector.setCurrentIndex(-1)
        else:
            self.main_window.overlay_selector.setCurrentIndex(-1)
            
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
        if isinstance(self.selected_overlay, BaseOverlay):
            self.main_window.overlay_font_scale.setValue(self.selected_overlay.font_scale)
            self.main_window.overlay_thickness.setValue(self.selected_overlay.thickness)
            overlay_type = self.selected_overlay.get_type()
            text_color = self.selected_overlay.text_color
            bg_color = self.selected_overlay.bg_color
            bg_alpha = int(self.selected_overlay.bg_alpha * 100)
        else:
            # Fallback for dict (should not happen after migration)
            self.main_window.overlay_font_scale.setValue(self.selected_overlay.get("font_scale", 0.7))
            self.main_window.overlay_thickness.setValue(self.selected_overlay.get("thickness", 2))
            overlay_type = self.selected_overlay.get("type", "text")
            text_color = self.selected_overlay.get("text_color", (0, 255, 0))
            bg_color = self.selected_overlay.get("bg_color", (0, 0, 0))
            bg_alpha = self.selected_overlay.get("bg_alpha", 50)
        
        # Show/hide type-specific controls - Use setExpanded for CollapsibleBox
        if hasattr(self.main_window, 'overlay_text_content_group'):
            self.main_window.overlay_text_content_group.setVisible(overlay_type not in ["motion"])
            self.main_window.overlay_text_content_group.setExpanded(overlay_type in ["text", "timestamp", "sensor"])
            
        if hasattr(self.main_window, 'overlay_text_content'):
            if overlay_type == "timestamp":
                self.main_window.overlay_text_content.setText("Current Time (Automatic)")
                self.main_window.overlay_text_content.setEnabled(False)
            elif overlay_type == "sensor":
                sensor_name = getattr(self.selected_overlay, "sensor_name", "Unknown") if isinstance(self.selected_overlay, BaseOverlay) else self.selected_overlay.get("sensor_name", "Unknown")
                self.main_window.overlay_text_content.setText(f"{sensor_name} (Automatic)")
                self.main_window.overlay_text_content.setEnabled(False)
            else:
                text = getattr(self.selected_overlay, "text", "") if isinstance(self.selected_overlay, BaseOverlay) else self.selected_overlay.get("text", "")
                self.main_window.overlay_text_content.setText(text)
                self.main_window.overlay_text_content.setEnabled(overlay_type == "text")
        
        # Handle rectangle dimensions if available
        if hasattr(self.main_window, 'overlay_dimensions_group'):
            self.main_window.overlay_dimensions_group.setExpanded(overlay_type == "rectangle")
            
            if overlay_type == "rectangle" and hasattr(self.main_window, 'overlay_width') and hasattr(self.main_window, 'overlay_height'):
                w_val = getattr(self.selected_overlay, "width", 0.1) if isinstance(self.selected_overlay, BaseOverlay) else self.selected_overlay.get("width", 0.1)
                h_val = getattr(self.selected_overlay, "height", 0.1) if isinstance(self.selected_overlay, BaseOverlay) else self.selected_overlay.get("height", 0.1)
                
                # Convert relative back to pixels for UI
                self.main_window.overlay_width.setValue(int(w_val * self.original_width))
                self.main_window.overlay_height.setValue(int(h_val * self.original_height))
        
        # Update color preview boxes - Convert BGR to RGB for display
        b, g, r = text_color
        self.main_window.text_color_preview.setStyleSheet(f"background-color: rgb({r}, {g}, {b}); border: 1px solid #888;")

        b, g, r = bg_color
        self.main_window.bg_color_preview.setStyleSheet(f"background-color: rgb({r}, {g}, {b}); border: 1px solid #888;")

        # Update hidden color spinboxes
        if hasattr(self.main_window, 'overlay_text_color_r'):
            self.main_window.overlay_text_color_r.setValue(r)
        if hasattr(self.main_window, 'overlay_text_color_g'):
            self.main_window.overlay_text_color_g.setValue(g)
        if hasattr(self.main_window, 'overlay_text_color_b'):
            self.main_window.overlay_text_color_b.setValue(b)

        if hasattr(self.main_window, 'overlay_bg_color_r'):
            self.main_window.overlay_bg_color_r.setValue(r)
        if hasattr(self.main_window, 'overlay_bg_color_g'):
            self.main_window.overlay_bg_color_g.setValue(g)
        if hasattr(self.main_window, 'overlay_bg_color_b'):
            self.main_window.overlay_bg_color_b.setValue(b)

        # Update opacity
        self.main_window.overlay_bg_alpha.setValue(bg_alpha)
    
    def apply_overlay_settings(self):
        """Apply settings to the selected overlay"""
        try:
            if not self.selected_overlay:
                return
                
            if isinstance(self.selected_overlay, BaseOverlay):
                # Get values from UI
                self.selected_overlay.font_scale = self.main_window.overlay_font_scale.value()
                self.selected_overlay.thickness = self.main_window.overlay_thickness.value()
                
                overlay_type = self.selected_overlay.get_type()
                
                # Get type-specific settings
                if overlay_type == "text":
                    self.selected_overlay.text = self.main_window.overlay_text_content.text()
                elif overlay_type == "rectangle" and hasattr(self.main_window, 'overlay_width') and hasattr(self.main_window, 'overlay_height'):
                    # Convert UI pixels to relative units based on current frame size
                    self.selected_overlay.width = self.main_window.overlay_width.value() / float(self.original_width)
                    self.selected_overlay.height = self.main_window.overlay_height.value() / float(self.original_height)
                
                # BGR format for OpenCV
                self.selected_overlay.text_color = (
                    self.main_window.overlay_text_color_b.value(),
                    self.main_window.overlay_text_color_g.value(),
                    self.main_window.overlay_text_color_r.value()
                )
                    
                self.selected_overlay.bg_color = (
                    self.main_window.overlay_bg_color_b.value(),
                    self.main_window.overlay_bg_color_g.value(),
                    self.main_window.overlay_bg_color_r.value()
                )
                    
                # Get opacity (bg_alpha)
                self.selected_overlay.bg_alpha = self.main_window.overlay_bg_alpha.value() / 100.0
            
            # Update camera thread with the updated overlays
            if self.camera_thread and hasattr(self.camera_thread, 'set_overlays'):
                self.camera_thread.set_overlays(self.overlays)
            
            # Save overlays to run directory
            self.save_overlays_to_run()
            
            self.logger.log("Applied overlay settings")
            
        except Exception as e:
            self.logger.log(f"Error applying overlay settings: {str(e)}")
            traceback.print_exc()

    def save_overlays_to_run(self):
        """Save overlays to the current run directory or global config"""
        try:
            run_dir = None
            is_replay = getattr(self.main_window, 'is_replay_mode', False)
            
            if not is_replay:
                run_dir = getattr(self.project_controller, 'current_run_folder', None)
            
            if run_dir and os.path.isdir(run_dir):
                save_path = run_dir
                self.logger.log(f"Saving overlays to run directory: {save_path}")
            else:
                # Fallback to global config directory
                save_path = os.path.join(os.path.expanduser("~"), ".evolabs_daq")
                if not os.path.exists(save_path):
                    os.makedirs(save_path, exist_ok=True)
                self.logger.log(f"Saving overlays to global config: {save_path}")
                
            overlays_file = os.path.join(save_path, "overlays.json")
            data = [o.to_dict() if isinstance(o, BaseOverlay) else o for o in self.overlays]
            
            import json
            with open(overlays_file, 'w') as f:
                json.dump(data, f, indent=4)
            self.logger.log(f"Overlays saved to {overlays_file}")
        except Exception as e:
            self.logger.log(f"Error saving overlays: {str(e)}", "WARN")

    def load_overlays_from_run(self, run_dir=None):
        """Load overlays from the specified run directory or global config"""
        try:
            if not run_dir:
                run_dir = getattr(self.project_controller, 'current_run_folder', None)
                
            # Try specified directory first
            overlays_file = None
            if run_dir and os.path.isdir(run_dir):
                overlays_file = os.path.join(run_dir, "overlays.json")
            
            # If not found, try global config
            if not overlays_file or not os.path.exists(overlays_file):
                global_path = os.path.join(os.path.expanduser("~"), ".evolabs_daq", "overlays.json")
                if os.path.exists(global_path):
                    overlays_file = global_path
            
            if not overlays_file or not os.path.exists(overlays_file):
                return
                
            import json
            with open(overlays_file, 'r') as f:
                data = json.load(f)
                
            self.overlays = []
            for item in data:
                obj = BaseOverlay.from_dict(item)
                if obj:
                    self.overlays.append(obj)
            
            if self.overlays:
                self.selected_overlay = self.overlays[0]
            else:
                self.selected_overlay = None
                
            self.update_overlay_selector()
            
            if self.camera_thread and hasattr(self.camera_thread, 'set_overlays'):
                self.camera_thread.set_overlays(self.overlays)
                
            self.logger.log(f"Loaded {len(self.overlays)} overlays from {run_dir}")
        except Exception as e:
            self.logger.log(f"Error loading overlays: {str(e)}", "WARN")
    
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
            
            # Save updates to run directory
            self.save_overlays_to_run()
            
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
            
            if hasattr(self.main_window, 'record_audio'):
                record_audio = self.main_window.record_audio.isChecked()
                self.settings.set_value("record_audio", "true" if record_audio else "false")
            
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
                if self.camera_select is not None and hasattr(self.camera_select, 'currentData'):
                     camera_id = self.camera_select.currentData() 
                     if camera_id is None: camera_id = 0 # Default if data is None
                elif hasattr(self.main_window, 'camera_id'): # Fallback for older UI names
                     camera_id = self.main_window.camera_id.currentIndex() if hasattr(self.main_window.camera_id, 'currentIndex') else 0

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
            
            # Use relative coordinates (0.0 - 1.0) of the click within the pixmap
            rel_click_x = pixmap_click_x / pixmap_width
            rel_click_y = pixmap_click_y / pixmap_height
            
            for overlay in self.overlays:
                if not isinstance(overlay, BaseOverlay):
                    continue
                    
                pos_x_rel, pos_y_rel = overlay.position
                overlay_type = overlay.get_type()
                
                # Hit testing based on overlay type
                hit = False
                
                # We need actual pixel sizes for hit testing text
                # Use current original_width/height to estimate displayed size
                if overlay_type == "rectangle":
                    # Rectangle hit test
                    w_rel = overlay.width
                    h_rel = overlay.height
                    
                    if (pos_x_rel <= rel_click_x <= pos_x_rel + w_rel and 
                        pos_y_rel <= rel_click_y <= pos_y_rel + h_rel):
                        hit = True
                elif overlay_type == "motion":
                    # Circular indicator hit test
                    indicator_size_rel = 30 / self.original_width # slightly larger for easier clicking
                    dist = ((rel_click_x - pos_x_rel)**2 + (rel_click_y - pos_y_rel)**2)**0.5
                    if dist < indicator_size_rel:
                        hit = True
                else:
                    # Text-based hit test using cv2.getTextSize
                    text = ""
                    if overlay_type == "text":
                        text = overlay.text
                    elif overlay_type == "timestamp":
                        text = datetime.now().strftime(overlay.format)
                    elif overlay_type == "sensor":
                        text = f"{overlay.sensor_name}: {overlay.sensor_value} {overlay.sensor_unit}"
                    
                    (text_w_px, text_h_px), baseline = cv2.getTextSize(
                        text, cv2.FONT_HERSHEY_SIMPLEX, overlay.font_scale, overlay.thickness)
                    
                    # Convert pixel size back to relative size
                    w_rel = (text_w_px + 16) / self.original_width
                    h_rel = (text_h_px + 16) / self.original_height
                    
                    if (pos_x_rel - 0.01 <= rel_click_x <= pos_x_rel + w_rel + 0.01 and 
                        pos_y_rel - h_rel - 0.01 <= rel_click_y <= pos_y_rel + 0.01):
                        hit = True
                        
                if hit:
                    self.selected_overlay = overlay
                    # Store relative offset from overlay position to click position
                    self.drag_offset_x = rel_click_x - pos_x_rel
                    self.drag_offset_y = rel_click_y - pos_y_rel
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
            if self.drag_start_pos and self.selected_overlay:
                # Final update and save
                if self.camera_thread and hasattr(self.camera_thread, 'set_overlays'):
                    self.camera_thread.set_overlays(self.overlays)
                self.save_overlays_to_run()
                
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
                
                # Get mouse position in relative coordinates (0.0 - 1.0)
                rel_mouse_x = pixmap_mouse_x / pixmap_width
                rel_mouse_y = pixmap_mouse_y / pixmap_height
                
                # Calculate new relative overlay position
                new_rel_x = rel_mouse_x - self.drag_offset_x
                new_rel_y = rel_mouse_y - self.drag_offset_y
                
                # Keep overlay within bounds
                new_rel_x = max(0, min(new_rel_x, 1.0))
                new_rel_y = max(0, min(new_rel_y, 1.0))
                
                # Update overlay position
                if isinstance(self.selected_overlay, BaseOverlay):
                    self.selected_overlay.position = (new_rel_x, new_rel_y)
                else:
                    self.selected_overlay["position"] = (new_rel_x, new_rel_y)
                
                # Update camera thread with the updated overlays (throttled)
                if self.camera_thread and hasattr(self.camera_thread, 'set_overlays'):
                    # Use a small throttle to avoid excessive deepcopy in the thread
                    now = time.time()
                    if not hasattr(self, '_last_drag_update') or now - self._last_drag_update > 0.05:
                        self.camera_thread.set_overlays(self.overlays)
                        self._last_drag_update = now
                
                # Update drag start position to current for next delta if needed
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
        ndi_source_name = self.settings.get_value("ndi_source_name", "Artefakt DAQ")
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
        if isinstance(self.selected_overlay, BaseOverlay):
            b, g, r = self.selected_overlay.text_color
        else:
            b, g, r = self.selected_overlay["text_color"]
            
        current_color = QColorDialog.getColor(
            QColor(r, g, b)  # Convert BGR to RGB for QColorDialog
        )

        if current_color.isValid():
            # Update overlay text color - RGB to BGR conversion for OpenCV
            new_color = (
                current_color.blue(),    # B
                current_color.green(),   # G
                current_color.red()      # R
            )
            
            if isinstance(self.selected_overlay, BaseOverlay):
                self.selected_overlay.text_color = new_color
            else:
                self.selected_overlay["text_color"] = new_color

            # Update UI (using RGB)
            self.main_window.text_color_preview.setStyleSheet(
                f"background-color: rgb({current_color.red()}, {current_color.green()}, {current_color.blue()}); "
                f"border: 1px solid #888;"
            )

            # Update hidden spinboxes to match the new color
            if hasattr(self.main_window, 'overlay_text_color_r'):
                self.main_window.overlay_text_color_r.setValue(current_color.red())
            if hasattr(self.main_window, 'overlay_text_color_g'):
                self.main_window.overlay_text_color_g.setValue(current_color.green())
            if hasattr(self.main_window, 'overlay_text_color_b'):
                self.main_window.overlay_text_color_b.setValue(current_color.blue())

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
        if isinstance(self.selected_overlay, BaseOverlay):
            b, g, r = self.selected_overlay.bg_color
        else:
            b, g, r = self.selected_overlay["bg_color"]
            
        current_color = QColorDialog.getColor(
            QColor(r, g, b)  # Convert BGR to RGB for QColorDialog
        )

        if current_color.isValid():
            # Update overlay background color - RGB to BGR conversion for OpenCV
            new_color = (
                current_color.blue(),    # B
                current_color.green(),   # G
                current_color.red()      # R
            )
            
            if isinstance(self.selected_overlay, BaseOverlay):
                self.selected_overlay.bg_color = new_color
            else:
                self.selected_overlay["bg_color"] = new_color

            # Update UI (using RGB)
            self.main_window.bg_color_preview.setStyleSheet(
                f"background-color: rgb({current_color.red()}, {current_color.green()}, {current_color.blue()}); "
                f"border: 1px solid #888;"
            )

            # Update hidden spinboxes to match the new color
            if hasattr(self.main_window, 'overlay_bg_color_r'):
                self.main_window.overlay_bg_color_r.setValue(current_color.red())
            if hasattr(self.main_window, 'overlay_bg_color_g'):
                self.main_window.overlay_bg_color_g.setValue(current_color.green())
            if hasattr(self.main_window, 'overlay_bg_color_b'):
                self.main_window.overlay_bg_color_b.setValue(current_color.blue())

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
    
    def get_audio_devices(self):
        """Get list of available audio input devices"""
        return DirectCameraThread.get_audio_input_devices()

    def start_recording(self):
        """Start recording video"""
        try:
            # Check if already recording to prevent duplicate calls
            if self.is_recording:
                self.logger.log("Recording already in progress, skipping duplicate start")
                return
            
            # Check if camera is connected and thread is running
            if not self.is_connected or not self.camera_thread or not self.camera_thread.isRunning():
                self.logger.log("Camera not connected. Attempting to connect before recording...")
                self.connect_camera()
                
                # Re-check connection status (connect_camera is synchronous for the connection part)
                if not self.is_connected or not self.camera_thread or not self.camera_thread.isRunning():
                    self.logger.log("Cannot start recording: Camera connection failed")
                    return
                else:
                    self.logger.log("Camera connected successfully. Proceeding with recording.")
                
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
            # Get whether to record audio
            record_audio = self.settings.get_bool("record_audio", True)
            
            # Get specific audio device index
            audio_device_index = self.settings.get_int("record_audio_device", -1)
            if audio_device_index == -1:
                audio_device_index = None

            # Update the camera thread with the current overlays
            if hasattr(self.camera_thread, 'set_overlays') and self.overlays:
                self.camera_thread.set_overlays(self.overlays)
            
            # Start recording in the camera thread
            success = self.camera_thread.start_recording(
                output_dir=output_dir,
                filename=f"recording_{timestamp}.{video_format}",
                codec=codec,
                use_direct_streaming=use_direct_streaming,
                record_audio=record_audio,
                audio_device_index=audio_device_index
            )
            if success:
                video_meta = {
                    "video_path": getattr(self.camera_thread, "output_file", ""),
                    "video_start_epoch": getattr(self.camera_thread, "recording_start_time", time.time()),
                    "video_format": video_format,
                }
                self._update_run_metadata(video_meta)
                # Persist structured segment for replay (supports multiple recordings in one run)
                self._append_video_segment_metadata(
                    {
                        "path": video_meta.get("video_path"),
                        "start_epoch": video_meta.get("video_start_epoch"),
                        "format": video_format,
                    }
                )
            
            # Update UI state
            self.main_window.record_btn.setText("Stop Recording")
            
            # Set recording flag
            self.is_recording = True
            
            self.logger.log(f"Started recording to {output_dir}/recording_{timestamp}.{video_format}")
            
            # Add event to dashboard and graph
            if hasattr(self.main_window, 'add_dashboard_event'):
                self.main_window.add_dashboard_event("Camera recording started", "SUCCESS")
            
            # Add recording_started event to automation context
            self._add_automation_event('recording_started')
            
        except Exception as e:
            self.logger.log(f"Error starting recording: {str(e)}")
    
    # --- Motion Detection Handlers --- START
    @pyqtSlot(bool)
    def _handle_motion_enabled_changed(self, state):
        if not self.camera_thread: return
        
        # If enabling motion detection and camera is already connected, show warning
        if state and self.is_connected:
            QMessageBox.information(
                self.main_window,
                "Motion Detection",
                "Motion detection has been enabled, but the camera is already connected.\n\n"
                "Motion detection will only be active the next time the camera is connected."
            )
        
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
        
        # Add motion detection event to automation context only on transition from False to True
        # This ensures each motion detection is a discrete event that can trigger automation
        if detected and not self._last_motion_detected:
            # Motion just started - add event
            self._add_automation_event('motion_detected')
        elif not detected and self._last_motion_detected:
            # Motion just stopped - clear the event to allow next detection to trigger
            self._remove_automation_event('motion_detected')
        
        # Update the previous state
        self._last_motion_detected = detected
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

    def get_current_frame(self):
        """Get the current raw frame as a numpy array for streaming"""
        if not self.is_connected or not self.camera_thread:
            return None
        
        try:
            # Try to get the current frame from the camera thread
            if hasattr(self.camera_thread, 'cap') and self.camera_thread.cap:
                # Read a frame directly from the camera
                ret, frame = self.camera_thread.cap.read()
                if ret and frame is not None:
                    # Apply overlays if any
                    if hasattr(self.camera_thread, 'apply_overlays'):
                        frame = self.camera_thread.apply_overlays(frame)
                    return frame
        except Exception as e:
            self.logger.log(f"Error getting current frame: {str(e)}", "ERROR")
        
        return None

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
            self.main_window.camera_tab_focus_slider.valueChanged.connect(self.main_window.apply_camera_focus_exposure)
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
            self.main_window.camera_tab_exposure_slider.valueChanged.connect(self.main_window.apply_camera_focus_exposure)
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
        if self.camera_select is not None:
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