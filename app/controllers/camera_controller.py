"""
Camera Controller

Manages camera operations, recording, and overlays.
"""
import sys
import traceback
from PyQt6.QtCore import QObject, pyqtSlot, Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QImage, QPixmap, QColor, QPainter, QBrush
from PyQt6.QtWidgets import QComboBox, QPushButton, QLabel, QMessageBox, QCheckBox, QSlider, QSpinBox, QColorDialog
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
        
        # Performance: Track last update time to throttle UI updates
        self._last_main_view_update = 0
        self._main_view_fps_limit = 1.0 / 30.0 # 30 FPS limit for main view
        
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
        
        # Initialize camera threads (pool of 4)
        self.camera_threads = [None] * 4
        self.is_connected = [False] * 4
        self.is_recording = [False] * 4
        self.camera_configs = [
            {
                "record_video": True, 
                "record_audio": False, 
                "mode": 0, 
                "source": None, 
                "resolution": "1280x720", 
                "fps": 30,
                "manual_focus": False,
                "focus_value": 0,
                "manual_exposure": False,
                "exposure_value": 0,
                "motion_enabled": False,
                "motion_sensitivity": 20,
                "motion_min_area": 500
            } 
            for _ in range(4)
        ]
        self.active_camera_index = 0 # Camera currently selected in settings tab
        self.main_view_index = 0     # Camera shown in the large preview
        self.dashboard_slots = [-1, -1, -1, -1] # Indices of cameras shown on dashboard (all off by default)
        
        self.show_on_dashboard = True # Global flag to control dashboard display
        self.current_frames = [None] * 4
        self._frame_skips = [0] * 4
        self.should_reconnect = [False] * 4
        
        # Mouse interaction state
        self.drag_start_pos = None
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.original_width = 1280
        self.original_height = 720
        self.overlays = [[] for _ in range(4)] # Per-camera overlays
        self.selected_overlay = None # Currently selected overlay for the active camera index
        self.is_dragging = False     # Flag for overlay dragging state

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
        QTimer.singleShot(500, self.init_camera)
        
        # --- Initial Motion Detection Config --- START
        # Call handlers AFTER init_camera ensures thread exists and connections are made
        if self.motion_enabled_widget:
            # Ensure initial UI state matches saved setting
            setting_value = self.settings.get_value("motion_detection_enabled", "false")
            initial_enabled = setting_value.lower() == "true" if setting_value is not None else False
            self.motion_enabled_widget.setChecked(initial_enabled)
            self._handle_motion_enabled_changed(0, initial_enabled) # Sync with thread and update UI enable state
        if self.motion_sensitivity_widget and self.motion_min_area_widget:
            # Ensure initial UI state matches saved setting
            sensitivity_value = self.settings.get_value("motion_detection_sensitivity", "20")
            min_area_value = self.settings.get_value("motion_detection_min_area", "500")
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
            if event_name != 'motion_detected' and not event_name.startswith('motion_detected_cam'):
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

    def _finalize_video_segment_metadata(self, path: str, end_ts: float, start_ts: float | None = None):
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

            updated = False
            for seg in videos:
                if path and seg.get("path") == path:
                    seg["end_epoch"] = end_ts
                    if start_ts:
                        seg["duration_sec"] = max(0.0, end_ts - start_ts)
                        seg["start_epoch"] = seg.get("start_epoch") or start_ts
                    updated = True
                    break

            updates = {
                "videos": videos,
                "video_end_epoch": end_ts,
            }
            if start_ts and not updated: # Fallback for old style single camera
                updates["video_duration_sec"] = max(0.0, end_ts - start_ts)
                updates["video_start_epoch"] = start_ts

            project_controller.update_run_metadata(run_dir, updates)
        except Exception:
            pass

    # Dashboard preview toggle (called from main_window.switch_dashboard_camera_source)
    def set_dashboard_display(self, enabled: bool):
        """
        Set whether the camera feeds should be displayed on the dashboard.
        """
        self.show_on_dashboard = enabled
        
        # If disabling, clear all dashboard labels
        if not enabled:
            for i in range(4):
                lbl = None
                if hasattr(self.main_window, 'dashboard_camera_labels') and i < len(self.main_window.dashboard_camera_labels):
                    lbl = self.main_window.dashboard_camera_labels[i]
                else:
                    lbl = getattr(self.main_window, f'dashboard_camera_label_{i+1}', None)
                
                if lbl:
                    lbl.setText("No camera connected")
                    empty_pixmap = QPixmap(320, 240)
                    empty_pixmap.fill(Qt.GlobalColor.black)
                    lbl.setPixmap(empty_pixmap)
        return
        
    def push_sensor_data_to_thread(self):
        """Push latest sensor values to the camera threads for overlays"""
        for i in range(4):
            if not self.camera_threads[i] or not self.camera_threads[i].isRunning():
                continue
                
            sensor_overlays = [o for o in self.overlays[i] if isinstance(o, SensorOverlay)]
            if not sensor_overlays:
                continue
            
            if not hasattr(self.main_window, 'sensor_controller') or not self.main_window.sensor_controller:
                continue
            
            for overlay in sensor_overlays:
                sensor = self.main_window.sensor_controller.get_sensor_by_name(overlay.sensor_name)
                if sensor and hasattr(sensor, 'current_value') and sensor.current_value is not None:
                    try:
                        value = f"{float(sensor.current_value):.2f}"
                    except (ValueError, TypeError):
                        value = str(sensor.current_value)
                    
                    unit = getattr(sensor, 'unit', "")
                    self.camera_threads[i].update_sensor_overlay_data(overlay.sensor_name, value, unit)

    def init_camera(self):
        """Initialize the camera settings and populate the list"""
        try:
            print("CameraController: init_camera starting...")
            
            # Load initial settings from QSettings into camera_configs[0]
            if hasattr(self.main_window, 'settings'):
                settings = self.main_window.settings
                idx = 0 # Default slot
                
                # Try to get the saved camera ID/index
                try:
                    saved_source = settings.value("camera/default_camera")
                    if saved_source is not None:
                        # If it's a number (local camera index)
                        if str(saved_source).isdigit():
                            self.camera_configs[idx]["source"] = int(saved_source)
                        else:
                            # It might be an NDI source name
                            self.camera_configs[idx]["source"] = str(saved_source)
                except:
                    pass
                
                self.camera_configs[idx]["resolution"] = settings.value("camera/resolution", "1280x720")
                try:
                    self.camera_configs[idx]["fps"] = int(settings.value("camera/fps", "30"))
                except:
                    pass
                
                self.camera_configs[idx]["manual_focus"] = settings.value("camera/manual_focus", "false").lower() == "true"
                try:
                    self.camera_configs[idx]["focus_value"] = int(settings.value("camera/focus_value", "0"))
                except:
                    pass
                    
                self.camera_configs[idx]["manual_exposure"] = settings.value("camera/manual_exposure", "false").lower() == "true"
                try:
                    self.camera_configs[idx]["exposure_value"] = int(settings.value("camera/exposure_value", "0"))
                except:
                    pass

            self.refresh_camera_list()
            self.refresh_audio_devices()
            self.load_overlays_from_run() # Load saved overlays
            QTimer.singleShot(500, self.refresh_camera_list)
            print("CameraController: init_camera routine complete.")
            return True
        except Exception as e:
            print(f"CameraController: Error in init_camera: {e}")
            traceback.print_exc()
            return False

    def refresh_audio_devices(self):
        """Populate the audio device dropdown"""
        if not hasattr(self.main_window, 'camera_audio_device'): return
        self.main_window.camera_audio_device.clear()
        self.main_window.camera_audio_device.addItem("Default Mic", -1)
        try:
            devices = self.get_audio_devices()
            for dev in devices:
                self.main_window.camera_audio_device.addItem(dev['name'], dev['index'])
        except: pass
    
    def toggle_camera(self):
        """Toggle camera connection for the active slot"""
        idx = self.active_camera_index
        if not self.is_connected[idx]:
            self.connect_camera(idx)
        else:
            self.disconnect_camera(idx)
            self.reconnect_camera_buttons()
    
    def _handle_camera_mode_changed(self, index):
        """Handle change in camera mode (Local vs NDI)."""
        self.refresh_camera_list()
        if index == 1 and NDI_AVAILABLE:
            if not self.ndi_discovery_timer.isActive():
                self.ndi_discovery_timer.start(500) # Reverted to 500ms as requested
        else:
            self.ndi_discovery_timer.stop()

    def refresh_camera_list(self):
        """Populate the camera selection dropdown"""
        if self.camera_select is None: return
        self.camera_select.clear()
        
        is_ndi = False
        if self.camera_mode: is_ndi = (self.camera_mode.currentIndex() == 1)
            
        if is_ndi:
            self.camera_select.addItem("Searching for NDI sources...")
            if NDI_AVAILABLE: self.discover_ndi_sources()
        else:
            try:
                from PyQt6.QtMultimedia import QMediaDevices
                devices = QMediaDevices.videoInputs()
                for i in range(max(len(devices), 1)):
                    name = devices[i].description() if i < len(devices) else f"Camera {i}"
                    self.camera_select.addItem(f"Camera {i}", i)
            except Exception as e:
                for i in range(10): self.camera_select.addItem(f"Camera {i}", i)

    def discover_ndi_sources(self):
        """Discover NDI sources on the network and update UI."""
        if not NDI_AVAILABLE or (self.camera_mode and self.camera_mode.currentIndex() != 1):
            return
        if not hasattr(self, '_ndi_finder'):
            self._ndi_finder = NDISourceFinder()
        
        sources = self._ndi_finder.get_sources()
        if not sources:
            return

        # Update the dropdown if it's currently showing "Searching..." or we have new sources
        if self.camera_select:
            current_count = self.camera_select.count()
            current_text = self.camera_select.currentText()
            
            # If we were searching and found something, clear and update
            if "Searching" in current_text or current_count <= 1:
                self.camera_select.clear()
                for s in sources:
                    name = getattr(s, 'ndi_name', str(s))
                    self.camera_select.addItem(name, s)
            else:
                # Update list while preserving selection if possible
                selected_name = current_text
                self.camera_select.blockSignals(True)
                # Quick check if sources changed
                existing_names = [self.camera_select.itemText(i) for i in range(self.camera_select.count())]
                new_names = [getattr(s, 'ndi_name', str(s)) for s in sources]
                
                if set(existing_names) != set(new_names):
                    self.camera_select.clear()
                    for s in sources:
                        name = getattr(s, 'ndi_name', str(s))
                        self.camera_select.addItem(name, s)
                    
                    # Restore selection
                    idx = self.camera_select.findText(selected_name)
                    if idx >= 0:
                        self.camera_select.setCurrentIndex(idx)
                self.camera_select.blockSignals(False)

    def connect_camera(self, index=None):
        """Connect to the camera at the specified slot index (0-3)"""
        if index is None: index = self.active_camera_index
        try:
            # Use configurations from the slot
            camera_id = self.camera_configs[index].get("source")
            res = self.camera_configs[index].get("resolution", "1280x720")
            fps = self.camera_configs[index].get("fps", 30)

            # If this is the active slot, we can double check with the UI but 
            # the configs should already be up to date thanks to signals.
            if camera_id is None:
                self.handle_connection_status(index, False, "No camera source selected")
                return

            if self.camera_threads[index] and self.camera_threads[index].isRunning():
                return

            if not self.camera_threads[index]:
                from app.core.direct_camera import DirectCameraThread
                thread = DirectCameraThread(index=index, main_window=self.main_window)
                self.camera_threads[index] = thread
                thread.frame_captured.connect(self.update_frame_display)
                thread.status_update.connect(self.handle_connection_status)
                thread.recording_status_signal.connect(self.handle_recording_status)
                if hasattr(thread, 'motion_detected_signal'):
                    thread.motion_detected_signal.connect(self._update_motion_indicator)
                if hasattr(thread, 'framerate_warning_signal'):
                    thread.framerate_warning_signal.connect(self.handle_framerate_warning)

            # Restore automatic timestamp overlay if no overlays exist for this slot
            if not self.overlays[index]:
                ts_ov = TimestampOverlay(1, "Timestamp", "%Y-%m-%d %H:%M:%S")
                ts_ov.position = (1.0, 1.0)
                self.overlays[index].append(ts_ov)
                self.update_overlay_selector()

            self.camera_threads[index].set_overlays(self.overlays[index])
            self.camera_threads[index].connect(camera_id, res, fps)
            
            # Apply initial settings once connected
            if self.camera_configs[index].get("motion_enabled"):
                self.camera_threads[index].set_motion_detection_enabled(True)
                self.camera_threads[index].update_motion_detection_settings(
                    self.camera_configs[index].get("motion_sensitivity", 20),
                    self.camera_configs[index].get("motion_min_area", 500)
                )
            
            self.camera_threads[index].set_camera_properties(
                manual_focus=self.camera_configs[index].get("manual_focus", False),
                focus_value=self.camera_configs[index].get("focus_value", 0),
                manual_exposure=self.camera_configs[index].get("manual_exposure", False),
                exposure_value=self.camera_configs[index].get("exposure_value", 0)
            )
        except Exception as e:
            self.handle_connection_status(index, False, str(e))

    def disconnect_camera(self, index=None):
        """Disconnect from the camera at the specified slot index"""
        if index is None: index = self.active_camera_index
        if self.camera_threads[index]:
            self.camera_threads[index].disconnect()
            self.is_connected[index] = False
            self.handle_connection_status(index, False, "Disconnected")

    def disconnect_all_cameras(self):
        """Disconnect all connected cameras"""
        self.logger.log("Disconnecting all cameras...")
        disconnected_count = 0
        for i in range(4):
            if self.is_connected[i]:
                self.disconnect_camera(i)
                disconnected_count += 1
        
        if disconnected_count > 0:
            self.logger.log(f"Successfully disconnected {disconnected_count} cameras.")
        else:
            self.logger.log("No cameras were connected.")

    @pyqtSlot(int, bool, str)
    def handle_connection_status(self, index, connected, message):
        """Handle connection status updates from a camera thread"""
        if index < 4: 
            old_connected = self.is_connected[index]
            self.is_connected[index] = connected
            
            # If camera just connected and we are in a run, start recording if enabled
            if connected and not old_connected:
                is_run_active = getattr(self.main_window, 'running', False)
                should_record = self.camera_configs[index].get("record_video", True)
                
                if is_run_active and should_record and not self.is_recording[index]:
                    self.logger.log(f"Camera {index+1} connected during run, starting recording...")
                    
                    output_dir = "recordings"
                    if hasattr(self.main_window, 'project_controller'):
                        run_dir = self.main_window.project_controller.get_current_run_directory()
                        if run_dir: output_dir = run_dir
                    
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    quality = int(self.settings.get_value("video_quality", "70"))
                    fname = f"recording_cam{index+1}_{timestamp}.mp4"
                    
                    if self.camera_threads[index]:
                        self.camera_threads[index].set_video_quality(quality)
                        self.camera_threads[index].set_overlays(self.overlays[index])
                        success = self.camera_threads[index].start_recording(
                            output_dir=output_dir, filename=fname, codec="H264",
                            record_audio=self.camera_configs[index].get("record_audio", False),
                            audio_device_index=self.camera_configs[index].get("audio_device", -1)
                        )
                        if success:
                            self.is_recording[index] = True
                            self._append_video_segment_metadata({
                                "path": os.path.join(output_dir, fname), 
                                "start_epoch": time.time(), 
                                "camera_index": index
                            })
            
            # If camera just disconnected, ensure metadata is finalized
            if not connected and old_connected and self.is_recording[index]:
                self.logger.log(f"Camera {index+1} disconnected during recording, finalizing metadata...")
                path = getattr(self.camera_threads[index], "output_file", "")
                start_time = getattr(self.camera_threads[index], "recording_start_time", None)
                self.is_recording[index] = False
                self._finalize_video_segment_metadata(path, time.time(), start_time)
        
        # If disconnected, clear the frames for this camera
        if not connected:
            self.current_frames[index] = None
            # Update UI immediately to clear the labels
            self.update_camera_display()
            # Clear dashboard labels if needed
            if self.show_on_dashboard:
                for i, slot in enumerate(self.dashboard_slots):
                    if slot == index:
                        # Find the correct label
                        lbl = None
                        if hasattr(self.main_window, 'dashboard_camera_labels') and i < len(self.main_window.dashboard_camera_labels):
                            lbl = self.main_window.dashboard_camera_labels[i]
                        else:
                            lbl = getattr(self.main_window, f'dashboard_camera_label_{i+1}', None)
                        
                        if lbl and lbl.isVisible():
                            lbl.setText("No camera connected")
                            empty_pixmap = QPixmap(320, 240)
                            empty_pixmap.fill(Qt.GlobalColor.black)
                            lbl.setPixmap(empty_pixmap)

        if index == self.active_camera_index and self.camera_connect_btn:
            self.camera_connect_btn.setText("Disconnect" if connected else "Connect")
            from app.ui.theme import ButtonStyles
            self.camera_connect_btn.setStyleSheet(ButtonStyles.danger("small") if connected else ButtonStyles.success("small"))
            self.camera_select.setEnabled(not connected)
        
        any_connected = any(self.is_connected)
        if hasattr(self.main_window, 'record_btn'): 
            self.main_window.record_btn.setEnabled(any_connected)
        if hasattr(self.main_window, 'snapshot_btn'):
            self.main_window.snapshot_btn.setEnabled(any_connected)
        if hasattr(self.main_window, 'add_overlay_btn'):
            self.main_window.add_overlay_btn.setEnabled(any_connected)
            
        # Emit status changed signal so main window can update icons
        self.status_changed.emit()

    @pyqtSlot(int, QImage)
    def update_frame_display(self, index, image):
        """Update the camera display with the captured frame"""
        if index >= 4: return
        
        # Convert QImage to QPixmap in the GUI thread
        pixmap = QPixmap.fromImage(image)
        
        # We always keep the last frame reference
        self.current_frames[index] = pixmap
        self._frame_skips[index] += 1
        
        # CPU Optimization: Only process UI updates if the relevant tab is active
        # Index 2: Camera Tab, Index 5: Dashboard Tab
        current_tab_widget = None
        if hasattr(self.main_window, 'stacked_widget'):
            current_tab_widget = self.main_window.stacked_widget.currentWidget()

        # 1. Main View (Large Preview) - ONLY if on Camera Tab
        is_camera_tab = (hasattr(self.main_window, 'camera_tab') and current_tab_widget == self.main_window.camera_tab)
        if is_camera_tab and index == self.main_view_index and self.camera_label:
            now = time.time()
            if now - self._last_main_view_update >= self._main_view_fps_limit:
                scaled = pixmap.scaled(self.camera_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                if self.is_recording[index]:
                    p = QPainter(scaled)
                    p.setBrush(QBrush(QColor(255, 0, 0, 200)))
                    p.drawEllipse(15, 15, 15, 15)
                    p.end()
                self.camera_label.setPixmap(scaled)
                self._last_main_view_update = now

        # 2. Dashboard View - ONLY if on Dashboard Tab
        is_dashboard_tab = (hasattr(self.main_window, 'dashboard_tab') and current_tab_widget == self.main_window.dashboard_tab)
        if self.show_on_dashboard and is_dashboard_tab:
            for i, slot in enumerate(self.dashboard_slots):
                if slot == index:
                    # Find the correct label
                    lbl = None
                    if hasattr(self.main_window, 'dashboard_camera_labels') and i < len(self.main_window.dashboard_camera_labels):
                        lbl = self.main_window.dashboard_camera_labels[i]
                    else:
                        lbl = getattr(self.main_window, f'dashboard_camera_label_{i+1}', None)
                    
                    if lbl:
                        lbl.setPixmap(pixmap)

        # 3. Thumbnails - update only every 20th frame and ONLY if on Camera Tab
        if is_camera_tab and self._frame_skips[index] % 20 == 0:
            if hasattr(self.main_window, 'camera_preview_labels') and index < len(self.main_window.camera_preview_labels):
                lbl = self.main_window.camera_preview_labels[index]
                lbl.setPixmap(pixmap.scaled(lbl.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))

    @pyqtSlot(int, bool)
    def handle_recording_status(self, index, is_recording):
        if index < 4: self.is_recording[index] = is_recording
        any_rec = any(self.is_recording)
        if hasattr(self.main_window, 'record_btn'):
            self.main_window.record_btn.setText("Stop Recording" if any_rec else "Start Recording")
            self.main_window.record_btn.setStyleSheet(self.recording_button_style if any_rec else self.original_button_style)

    def handle_framerate_warning(self, index, exp, act):
        self.logger.log(f"Cam {index+1} low FPS: {act}/{exp}", "WARN")
    
    @pyqtSlot()
    def toggle_recording(self):
        """Toggle recording on/off for all connected cameras"""
        try:
            if not any(self.is_connected): return
            if not any(self.is_recording): self.start_recording()
            else: self.stop_recording()
        except Exception as e:
            self.logger.log(f"Error toggling recording: {str(e)}")
    
    def start_recording(self):
        """Start recording for all enabled cameras"""
        try:
            output_dir = "recordings"
            if hasattr(self.main_window, 'project_controller'):
                run_dir = self.main_window.project_controller.get_current_run_directory()
                if run_dir: output_dir = run_dir
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            quality = int(self.settings.get_value("video_quality", "70"))
            use_direct = self.settings.get_bool("use_direct_streaming", True)
            use_hw = self.settings.get_bool("use_hw_accel", True)
            
            count = 0
            for i in range(4):
                if not self.is_connected[i] or not self.camera_threads[i]: continue
                if not self.camera_configs[i].get("record_video", True): continue
                
                self.camera_threads[i].set_video_quality(quality)
                self.camera_threads[i].set_overlays(self.overlays[i])
                
                fname = f"recording_cam{i+1}_{timestamp}.mp4"
                success = self.camera_threads[i].start_recording(
                    output_dir=output_dir, filename=fname, codec="H264",
                    use_direct_streaming=use_direct,
                    use_hw_accel=use_hw,
                    record_audio=self.camera_configs[i].get("record_audio", False),
                    audio_device_index=self.camera_configs[i].get("audio_device", -1)
                )
                if success:
                    count += 1
                    self.is_recording[i] = True
                    self._append_video_segment_metadata({"path": os.path.join(output_dir, fname), "start_epoch": time.time(), "camera_index": i})
            
            if count > 0:
                self.logger.log(f"Started {count} recordings")
                self._add_automation_event('recording_started')
        except Exception as e:
            self.logger.log(f"Error starting recording: {str(e)}")

    def stop_recording(self):
        """Stop all active camera recordings"""
        count = 0
        for i in range(4):
            if self.is_recording[i] and self.camera_threads[i]:
                path = getattr(self.camera_threads[i], "output_file", "")
                self.camera_threads[i].stop_recording()
                self.is_recording[i] = False
                count += 1
                self._finalize_video_segment_metadata(path, time.time(), getattr(self.camera_threads[i], "recording_start_time", None))
        if count > 0:
            self.logger.log(f"Stopped {count} recordings")
            self._add_automation_event('recording_stopped')
    
    def shutdown(self):
        """Clean up all camera resources"""
        try:
            self.stop_recording()
            for i in range(4):
                if self.camera_threads[i]:
                    self.camera_threads[i].stop()
                    self.camera_threads[i].wait(1000)
            if hasattr(self, 'ndi_interface'): self.ndi_interface.stop()
        except Exception as e: print(f"Error shutdown: {e}")

    def connect_signals(self):
        """Connect UI signals to controller methods"""
        self.reconnect_camera_buttons()
        if hasattr(self.main_window, 'camera_refresh_btn'):
            try: self.main_window.camera_refresh_btn.clicked.disconnect()
            except: pass
            self.main_window.camera_refresh_btn.clicked.connect(self.refresh_camera_list)
        
        if self.camera_select:
            try: self.camera_select.currentIndexChanged.disconnect()
            except: pass
            self.camera_select.currentIndexChanged.connect(
                lambda: self.camera_configs[self.active_camera_index].update({"source": self.camera_select.currentData()})
            )
        
        # Connect adjust tab signals
        if hasattr(self.main_window, 'camera_tab_manual_focus'):
            try: self.main_window.camera_tab_manual_focus.stateChanged.disconnect()
            except: pass
            self.main_window.camera_tab_manual_focus.stateChanged.connect(lambda: self.apply_camera_settings())
            
        if hasattr(self.main_window, 'camera_tab_focus_slider'):
            try: self.main_window.camera_tab_focus_slider.valueChanged.disconnect()
            except: pass
            self.main_window.camera_tab_focus_slider.valueChanged.connect(lambda: self.apply_camera_settings())
            
        if hasattr(self.main_window, 'camera_tab_manual_exposure'):
            try: self.main_window.camera_tab_manual_exposure.stateChanged.disconnect()
            except: pass
            self.main_window.camera_tab_manual_exposure.stateChanged.connect(lambda: self.apply_camera_settings())
            
        if hasattr(self.main_window, 'camera_tab_exposure_slider'):
            try: self.main_window.camera_tab_exposure_slider.valueChanged.disconnect()
            except: pass
            self.main_window.camera_tab_exposure_slider.valueChanged.connect(lambda: self.apply_camera_settings())
        
        if hasattr(self.main_window, 'camera_resolution'):
            self.main_window.camera_resolution.currentIndexChanged.connect(
                lambda: self.camera_configs[self.active_camera_index].update({"resolution": self.main_window.camera_resolution.currentText()})
            )
        
        if hasattr(self.main_window, 'camera_framerate'):
            self.main_window.camera_framerate.currentIndexChanged.connect(
                lambda: self.camera_configs[self.active_camera_index].update({"fps": int(self.main_window.camera_framerate.currentText())})
            )

        if hasattr(self.main_window, 'camera_mode'):
            try: self.main_window.camera_mode.currentIndexChanged.disconnect()
            except: pass
            self.main_window.camera_mode.currentIndexChanged.connect(self._handle_camera_mode_changed)

        if self.motion_enabled_widget:
            self.motion_enabled_widget.stateChanged.connect(lambda state: self._handle_motion_enabled_changed(self.active_camera_index, state == 2))
        if self.motion_sensitivity_widget:
            self.motion_sensitivity_widget.valueChanged.connect(self._handle_motion_settings_changed)
        if self.motion_min_area_widget:
            self.motion_min_area_widget.valueChanged.connect(self._handle_motion_settings_changed)
        
        # Connect recording toggles
        if hasattr(self.main_window, 'record_video_checkbox'):
            self.main_window.record_video_checkbox.toggled.connect(self._handle_record_video_toggled)
        if hasattr(self.main_window, 'record_audio_checkbox'):
            self.main_window.record_audio_checkbox.toggled.connect(
                lambda checked: self.camera_configs[self.active_camera_index].update({"record_audio": checked})
            )
        
        if hasattr(self.main_window, 'camera_audio_device'):
            self.main_window.camera_audio_device.currentIndexChanged.connect(
                lambda: self.camera_configs[self.active_camera_index].update({"audio_device": self.main_window.camera_audio_device.currentData()})
            )

        if hasattr(self.main_window, 'overlay_selector'):
            try: self.main_window.overlay_selector.currentIndexChanged.disconnect()
            except: pass
            self.main_window.overlay_selector.currentIndexChanged.connect(self.on_overlay_selected)
    
    def reconnect_camera_buttons(self):
        """Reconnect all major camera tab buttons"""
        btns = {
            'snapshot_btn': self.take_snapshot,
            'record_btn': self.toggle_recording,
            'add_overlay_btn': self.add_overlay,
            'remove_overlay_btn': self.remove_overlay,
            'apply_overlay_settings_btn': self.apply_overlay_settings,
            'camera_apply_settings_btn': self.apply_camera_settings,
            'camera_connect_btn': self.toggle_camera,
            'disconnect_all_btn': self.disconnect_all_cameras
        }
        for attr, method in btns.items():
            if hasattr(self.main_window, attr):
                btn = getattr(self.main_window, attr)
                try: btn.clicked.disconnect()
                except: pass
                btn.clicked.connect(method)

    def take_snapshot(self, index=None):
        """Take a snapshot from the camera at the specified slot index"""
        # Default to the active camera slot (selected in the camera tab)
        if index is None: index = self.active_camera_index
        
        # Support for "all connected cameras"
        if index == -1 or index == "all":
            paths = []
            for i in range(4):
                if self.is_connected[i] and self.current_frames[i]:
                    path = self._perform_snapshot(i)
                    if path: paths.append(path)
            return "; ".join(paths) if paths else None

        return self._perform_snapshot(index)

    def _perform_snapshot(self, index):
        """Internal helper to capture a single snapshot"""
        try:
            if not self.camera_threads[index] or not self.is_connected[index] or not self.current_frames[index]:
                return None
            run_dir = self.project_controller.get_current_run_directory() if self.project_controller else None
            path = os.path.join(run_dir, "Snapshots") if run_dir else os.path.join(".", "Snapshots")
            os.makedirs(path, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            fname = os.path.join(path, f"snapshot_cam{index+1}_{ts}.png")
            self.current_frames[index].toImage().save(fname, "PNG")
            self.snapshot_taken.emit(fname)
            return fname
        except Exception as e: self.logger.log(f"Error snapshot: {e}", "ERROR"); return None
    
    def add_overlay(self):
        """Add a new overlay to the active camera slot with improved configuration dialog"""
        index = self.active_camera_index
        try:
            from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                                       QComboBox, QDialogButtonBox, QLineEdit, QFormLayout)
            dialog = QDialog(self.main_window)
            dialog.setWindowTitle(f"Add Overlay Cam {index+1}")
            dialog.setMinimumWidth(350)
            
            layout = QVBoxLayout(dialog)
            form = QFormLayout()
            
            type_combo = QComboBox()
            type_combo.addItems(["Text", "Timestamp", "Rectangle", "Sensor", "Motion Indicator"])
            form.addRow("Type:", type_combo)
            
            # Content input (changes meaning based on type)
            content_label = QLabel("Text:")
            content_input = QLineEdit("New Overlay")
            form.addRow(content_label, content_input)
            
            # Sensor selector (initially hidden)
            sensor_combo = QComboBox()
            sensor_combo.setVisible(False)
            sensor_label = QLabel("Sensor:")
            sensor_label.setVisible(False)
            if hasattr(self.main_window, 'sensor_controller') and self.main_window.sensor_controller:
                sensors = self.main_window.sensor_controller.sensors
                if isinstance(sensors, list):
                    for s in sensors:
                        name = getattr(s, 'name', str(s))
                        sensor_combo.addItem(name)
                elif isinstance(sensors, dict):
                    for sname in sensors.keys():
                        sensor_combo.addItem(sname)
            form.addRow(sensor_label, sensor_combo)
            
            def on_type_changed(text):
                is_sensor = (text == "Sensor")
                is_timestamp = (text == "Timestamp")
                is_motion = (text == "Motion Indicator")
                is_rect = (text == "Rectangle")
                
                sensor_combo.setVisible(is_sensor)
                sensor_label.setVisible(is_sensor)
                
                content_input.setVisible(not is_motion and not is_rect)
                content_label.setVisible(not is_motion and not is_rect)
                
                if is_sensor:
                    content_label.setText("Format:")
                    content_input.setText("%.2f")
                elif is_timestamp:
                    content_label.setText("Time Format:")
                    content_input.setText("%H:%M:%S")
                elif text == "Text":
                    content_label.setText("Text:")
                    content_input.setText("New Text")
            
            type_combo.currentTextChanged.connect(on_type_changed)
            layout.addLayout(form)
            
            bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            bbox.accepted.connect(dialog.accept)
            bbox.rejected.connect(dialog.reject)
            layout.addWidget(bbox)
            
            if dialog.exec() != QDialog.DialogCode.Accepted: 
                return
            
            otype = type_combo.currentText()
            count = len(self.overlays[index]) + 1
            name = f"{otype} {count}"
            
            if otype == "Text":
                new_ov = TextOverlay(count, name, content_input.text())
            elif otype == "Timestamp":
                new_ov = TimestampOverlay(count, name, content_input.text() or "%Y-%m-%d %H:%M:%S")
            elif otype == "Rectangle":
                new_ov = RectangleOverlay(count, name, 0.1, 0.1)
            elif otype == "Sensor":
                sname = sensor_combo.currentText() or "Unknown"
                new_ov = SensorOverlay(count, name, sname)
                # Apply initial format if provided in content_input
            elif otype == "Motion Indicator":
                new_ov = MotionOverlay(count, name)
            else:
                return
                
            if otype == "Timestamp":
                new_ov.position = (1.0, 1.0)
            else:
                new_ov.position = (0.05, 0.05 + (count-1)*0.05)
                
            self.overlays[index].append(new_ov)
            self.selected_overlay = new_ov
            self.update_overlay_selector()
            
            if self.camera_threads[index]: 
                self.camera_threads[index].set_overlays(self.overlays[index])
            
            self.save_overlays_to_run(index)
            
        except Exception as e: 
            self.logger.log(f"Error adding overlay: {e}", "ERROR")
            import traceback
            traceback.print_exc()
    
    def update_overlay_selector(self):
        if not hasattr(self.main_window, 'overlay_selector'): return
        try:
            self.main_window.overlay_selector.blockSignals(True)
            self.main_window.overlay_selector.clear()
            idx = self.active_camera_index
            
            # Ensure selected_overlay belongs to this slot
            if not self.selected_overlay or self.selected_overlay not in self.overlays[idx]:
                self.selected_overlay = self.overlays[idx][0] if self.overlays[idx] else None
                
            for o in self.overlays[idx]: 
                self.main_window.overlay_selector.addItem(o.name)
                
            if self.selected_overlay: 
                self.main_window.overlay_selector.setCurrentText(self.selected_overlay.name)
                
            self.main_window.overlay_selector.blockSignals(False)
            self.update_overlay_settings_ui()
        except: pass
        
    def on_overlay_selected(self, index):
        idx = self.active_camera_index
        if 0 <= index < len(self.overlays[idx]):
            self.selected_overlay = self.overlays[idx][index]
            self.update_overlay_settings_ui()
    
    def update_overlay_settings_ui(self):
        if not self.selected_overlay: return
        try:
            o = self.selected_overlay
            if hasattr(self.main_window, 'overlay_font_scale'): 
                self.main_window.overlay_font_scale.setValue(o.font_scale)
            if hasattr(self.main_window, 'overlay_thickness'): 
                self.main_window.overlay_thickness.setValue(o.thickness)
            if hasattr(self.main_window, 'overlay_text_content'):
                if hasattr(o, 'text'): self.main_window.overlay_text_content.setText(o.text)
                elif hasattr(o, 'format'): self.main_window.overlay_text_content.setText(o.format)
                elif hasattr(o, 'sensor_name'): self.main_window.overlay_text_content.setText(o.sensor_name)
            
            # Update colors and alpha
            if hasattr(self.main_window, 'overlay_bg_alpha'):
                self.main_window.overlay_bg_alpha.setValue(int(o.bg_alpha * 100))
            
            # Dimensions for RectangleOverlay
            if isinstance(o, RectangleOverlay):
                if hasattr(self.main_window, 'overlay_width'): 
                    self.main_window.overlay_width.setValue(int(o.width * 100))
                if hasattr(self.main_window, 'overlay_height'): 
                    self.main_window.overlay_height.setValue(int(o.height * 100))
            
            # Update color previews if they exist
            if hasattr(self.main_window, 'text_color_preview'):
                color = o.text_color # BGR
                self.main_window.text_color_preview.setStyleSheet(
                    f"background-color: rgb({color[2]}, {color[1]}, {color[0]}); border: 1px solid #555; border-radius: 4px;"
                )
            if hasattr(self.main_window, 'bg_color_preview'):
                color = o.bg_color # BGR
                self.main_window.bg_color_preview.setStyleSheet(
                    f"background-color: rgb({color[2]}, {color[1]}, {color[0]}); border: 1px solid #555; border-radius: 4px;"
                )
        except Exception as e:
            self.logger.log(f"Error updating overlay UI: {e}", "DEBUG")
    
    def apply_overlay_settings(self):
        idx = self.active_camera_index
        if not self.selected_overlay: return
        try:
            o = self.selected_overlay
            if hasattr(self.main_window, 'overlay_font_scale'):
                o.font_scale = self.main_window.overlay_font_scale.value()
            if hasattr(self.main_window, 'overlay_thickness'):
                o.thickness = self.main_window.overlay_thickness.value()
            if hasattr(self.main_window, 'overlay_text_content'):
                text = self.main_window.overlay_text_content.text()
                if hasattr(o, 'text'): o.text = text
                elif hasattr(o, 'format'): o.format = text
                elif hasattr(o, 'sensor_name'): o.sensor_name = text
            
            if hasattr(self.main_window, 'overlay_bg_alpha'):
                o.bg_alpha = self.main_window.overlay_bg_alpha.value() / 100.0
            
            # Dimensions for RectangleOverlay
            if isinstance(o, RectangleOverlay):
                if hasattr(self.main_window, 'overlay_width'):
                    o.width = self.main_window.overlay_width.value() / 100.0
                if hasattr(self.main_window, 'overlay_height'):
                    o.height = self.main_window.overlay_height.value() / 100.0
                
            if self.camera_threads[idx]: self.camera_threads[idx].set_overlays(self.overlays[idx])
            self.save_overlays_to_run(idx)
            self.update_overlay_settings_ui() # Refresh previews
        except Exception as e:
            self.logger.log(f"Error applying overlay settings: {e}", "ERROR")

    def save_overlays_to_run(self, index=None):
        if index is None:
            for i in range(4): self.save_overlays_to_run(i)
            return
        try:
            run_dir = self.project_controller.current_run_folder if self.project_controller else None
            path = run_dir if run_dir and os.path.isdir(run_dir) else os.path.join(os.path.expanduser("~"), ".evolabs_daq")
            os.makedirs(path, exist_ok=True)
            import json
            with open(os.path.join(path, f"overlays_cam{index+1}.json"), 'w') as f:
                json.dump([o.to_dict() for o in self.overlays[index]], f, indent=4)
        except: pass

    def load_overlays_from_run(self, run_dir=None):
        try:
            import json
            for i in range(4):
                fpath = os.path.join(run_dir, f"overlays_cam{i+1}.json") if run_dir else os.path.join(os.path.expanduser("~"), ".evolabs_daq", f"overlays_cam{i+1}.json")
                if os.path.exists(fpath):
                    with open(fpath, 'r') as f:
                        data = json.load(f)
                        self.overlays[i] = [BaseOverlay.from_dict(d) for d in data if BaseOverlay.from_dict(d)]
                        if self.camera_threads[i]: self.camera_threads[i].set_overlays(self.overlays[i])
                
                # Restore automatic timestamp overlay if still empty
                if not self.overlays[i]:
                    from app.core.overlay_manager import TimestampOverlay
                    ts_ov = TimestampOverlay(1, "Timestamp", "%Y-%m-%d %H:%M:%S")
                    ts_ov.position = (1.0, 1.0)
                    self.overlays[i].append(ts_ov)
                    if self.camera_threads[i]: self.camera_threads[i].set_overlays(self.overlays[i])

            self.update_overlay_selector()
        except: pass
    
    def remove_overlay(self):
        idx = self.active_camera_index
        if self.selected_overlay and self.selected_overlay in self.overlays[idx]:
            self.overlays[idx].remove(self.selected_overlay)
            self.selected_overlay = self.overlays[idx][0] if self.overlays[idx] else None
            self.update_overlay_selector()
            if self.camera_threads[idx]: self.camera_threads[idx].set_overlays(self.overlays[idx])
            self.save_overlays_to_run(idx)
    
    def apply_camera_settings(self):
        idx = self.active_camera_index
        try:
            if hasattr(self.main_window, 'camera_resolution'):
                res = self.main_window.camera_resolution.currentText()
                self.camera_configs[idx]["resolution"] = res
            if hasattr(self.main_window, 'camera_framerate'):
                fps_text = self.main_window.camera_framerate.currentText()
                if fps_text and fps_text.isdigit():
                    self.camera_configs[idx]["fps"] = int(fps_text)
                
            # Focus and Exposure settings from Adjust tab
            manual_focus = False
            focus_value = 0
            manual_exposure = False
            exposure_value = 0
            
            if hasattr(self.main_window, 'camera_tab_manual_focus'):
                manual_focus = self.main_window.camera_tab_manual_focus.isChecked()
                self.camera_configs[idx]["manual_focus"] = manual_focus
            if hasattr(self.main_window, 'camera_tab_focus_slider'):
                focus_value = self.main_window.camera_tab_focus_slider.value()
                self.camera_configs[idx]["focus_value"] = focus_value
                self.main_window.camera_tab_focus_slider.setEnabled(manual_focus)
                if hasattr(self.main_window, 'camera_tab_focus_value'):
                    self.main_window.camera_tab_focus_value.setText(str(focus_value))
                    
            if hasattr(self.main_window, 'camera_tab_manual_exposure'):
                manual_exposure = self.main_window.camera_tab_manual_exposure.isChecked()
                self.camera_configs[idx]["manual_exposure"] = manual_exposure
            if hasattr(self.main_window, 'camera_tab_exposure_slider'):
                exposure_value = self.main_window.camera_tab_exposure_slider.value()
                self.camera_configs[idx]["exposure_value"] = exposure_value
                self.main_window.camera_tab_exposure_slider.setEnabled(manual_exposure)
                if hasattr(self.main_window, 'camera_tab_exposure_value'):
                    self.main_window.camera_tab_exposure_value.setText(str(exposure_value))

            if self.is_connected[idx]: 
                thread = self.camera_threads[idx]
                if thread and thread.isRunning():
                    if hasattr(thread, 'set_camera_properties'):
                        thread.set_camera_properties(
                            manual_focus=manual_focus,
                            focus_value=focus_value,
                            manual_exposure=manual_exposure,
                            exposure_value=exposure_value
                        )
        except Exception as e:
            self.logger.log(f"Error applying camera settings: {e}", "ERROR")

    def _get_rel_image_pos(self, event_pos):
        """Calculate relative position (0.0-1.0) within the actual image area of the label"""
        idx = self.main_view_index
        if not self.camera_label or not self.current_frames[idx]:
            return None, None
            
        lbl_w = self.camera_label.width()
        lbl_h = self.camera_label.height()
        img_w = self.current_frames[idx].width()
        img_h = self.current_frames[idx].height()
        
        # Calculate how the image is scaled inside the label (KeepAspectRatio)
        scale = min(lbl_w / img_w, lbl_h / img_h)
        actual_w = img_w * scale
        actual_h = img_h * scale
        
        offset_x = (lbl_w - actual_w) / 2
        offset_y = (lbl_h - actual_h) / 2
        
        # Relative coordinates within the ACTUAL image area
        rel_x = (event_pos.x() - offset_x) / actual_w
        rel_y = (event_pos.y() - offset_y) / actual_h
        
        return rel_x, rel_y
    
    def camera_mouse_press(self, event):
        idx = self.main_view_index
        if not self.camera_label or not self.current_frames[idx]: return
        
        # When clicking on the preview, switch configuration slot to this camera
        if idx != self.active_camera_index:
            self.set_active_config_slot(idx)
            if hasattr(self.main_window, 'camera_side_tabs'):
                self.main_window.camera_side_tabs.setCurrentIndex(2) # Switch to Overlay tab
        
        rel_x, rel_y = self._get_rel_image_pos(event.position())
        if rel_x is None or rel_x < 0 or rel_x > 1 or rel_y < 0 or rel_y > 1:
            return

        img_w = self.current_frames[idx].width()
        img_h = self.current_frames[idx].height()

        # Selection tolerance: wider in X direction to account for text length
        # o.position is top-left of text. We allow a box that is roughly 
        # 30% of image width and 10% of image height.
        for o in self.overlays[idx]:
            # Use get_bounds if available, otherwise fallback to old logic
            if hasattr(o, 'get_bounds'):
                x1, y1, x2, y2 = o.get_bounds(img_w, img_h)
                # Add a small selection tolerance
                if (x1 - 0.02 <= rel_x <= x2 + 0.02) and (y1 - 0.02 <= rel_y <= y2 + 0.02):
                    self.selected_overlay = o
                    self.is_dragging = True
                    self.drag_offset_x = rel_x - o.position[0]
                    self.drag_offset_y = rel_y - o.position[1]
                    self.update_overlay_selector()
                    break
            else:
                # Use slightly larger hitbox and center it vertically around o.position[1]
                # Since o.position[1] is usually the baseline or top, 
                # we check a range around it.
                if (o.position[0] - 0.05 <= rel_x <= o.position[0] + 0.35) and \
                   (o.position[1] - 0.08 <= rel_y <= o.position[1] + 0.08):
                    self.selected_overlay = o
                    self.is_dragging = True
                    self.drag_offset_x = rel_x - o.position[0]
                    self.drag_offset_y = rel_y - o.position[1]
                    self.update_overlay_selector()
                    break
                
    def camera_mouse_move(self, event):
        idx = self.main_view_index
        if self.is_dragging and self.selected_overlay:
            rel_x, rel_y = self._get_rel_image_pos(event.position())
            if rel_x is not None:
                # Clamp coordinates to [0, 1] range
                new_x = max(0.0, min(1.0, rel_x - self.drag_offset_x))
                new_y = max(0.0, min(1.0, rel_y - self.drag_offset_y))
                self.selected_overlay.position = (new_x, new_y)
                if self.camera_threads[idx]: 
                    self.camera_threads[idx].set_overlays(self.overlays[idx])
    
    def camera_mouse_release(self, event):
        if self.is_dragging:
            self.is_dragging = False
            self.save_overlays_to_run(self.main_view_index)

    def close_camera(self, index=None):
        if index is None:
            for i in range(4): self.close_camera(i)
            return
        if self.camera_threads[index]: self.camera_threads[index].stop(); self.is_connected[index] = False
    
    def init_ndi(self):
        from app.core.interfaces.ndi_interface import NDIInterface
        if not hasattr(self, 'ndi_interface'): self.ndi_interface = NDIInterface()
        if self.settings.get_bool("enable_ndi", False): self.ndi_interface.start()
        else: self.ndi_interface.stop()

    def get_status(self):
        """Return overall status of all cameras"""
        connected_count = sum(1 for c in self.is_connected if c)
        if connected_count == 0:
            return (StatusState.OPTIONAL, "No cameras connected")
        
        if any(self.is_recording):
            return (StatusState.RUNNING, f"{connected_count} Cam(s) Recording")
            
        return (StatusState.READY, f"{connected_count} Cam(s) OK")

    def get_current_frame(self, index=None):
        if index is None: index = self.main_view_index
        return self.current_frames[index]

    def set_main_view(self, index):
        if 0 <= index < 4: self.main_view_index = index; self.update_camera_display()

    def set_active_config_slot(self, index):
        if 0 <= index < 4: 
            self.active_camera_index = index
            # Reset selected overlay to the first one of the new slot
            self.selected_overlay = self.overlays[index][0] if self.overlays[index] else None
            
            self.refresh_settings_ui()

    def refresh_settings_ui(self):
        idx = self.active_camera_index
        if self.camera_select:
            source_idx = self.camera_select.findData(self.camera_configs[idx]["source"])
            if source_idx >= 0: self.camera_select.setCurrentIndex(source_idx)
        
        # Update connection button for this slot
        if self.camera_connect_btn:
            connected = self.is_connected[idx]
            self.camera_connect_btn.setText("Disconnect" if connected else "Connect")
            from app.ui.theme import ButtonStyles
            self.camera_connect_btn.setStyleSheet(ButtonStyles.danger("small") if connected else ButtonStyles.success("small"))
            if self.camera_select:
                self.camera_select.setEnabled(not connected)

        # Update recording checkboxes
        if hasattr(self.main_window, 'record_video_checkbox'):
            self.main_window.record_video_checkbox.blockSignals(True)
            self.main_window.record_video_checkbox.setChecked(self.camera_configs[idx].get("record_video", True))
            self.main_window.record_video_checkbox.blockSignals(False)
        if hasattr(self.main_window, 'record_audio_checkbox'):
            self.main_window.record_audio_checkbox.blockSignals(True)
            self.main_window.record_audio_checkbox.setChecked(self.camera_configs[idx].get("record_audio", False))
            self.main_window.record_audio_checkbox.blockSignals(False)
            
        if hasattr(self.main_window, 'camera_audio_device'):
            self.main_window.camera_audio_device.blockSignals(True)
            audio_idx = self.main_window.camera_audio_device.findData(self.camera_configs[idx].get("audio_device", -1))
            if audio_idx >= 0: self.main_window.camera_audio_device.setCurrentIndex(audio_idx)
            self.main_window.camera_audio_device.blockSignals(False)
            
        if hasattr(self.main_window, 'camera_resolution'):
            self.main_window.camera_resolution.blockSignals(True)
            self.main_window.camera_resolution.setCurrentText(self.camera_configs[idx].get("resolution", "1280x720"))
            self.main_window.camera_resolution.blockSignals(False)
        
        if hasattr(self.main_window, 'camera_framerate'):
            self.main_window.camera_framerate.blockSignals(True)
            self.main_window.camera_framerate.setCurrentText(str(self.camera_configs[idx].get("fps", 30)))
            self.main_window.camera_framerate.blockSignals(False)
            
        # Update focus/exposure sliders for this slot
        if hasattr(self.main_window, 'camera_tab_manual_focus'):
            self.main_window.camera_tab_manual_focus.blockSignals(True)
            self.main_window.camera_tab_manual_focus.setChecked(self.camera_configs[idx].get("manual_focus", False))
            self.main_window.camera_tab_manual_focus.blockSignals(False)
        if hasattr(self.main_window, 'camera_tab_focus_slider'):
            self.main_window.camera_tab_focus_slider.blockSignals(True)
            self.main_window.camera_tab_focus_slider.setValue(self.camera_configs[idx].get("focus_value", 0))
            self.main_window.camera_tab_focus_slider.setEnabled(self.camera_configs[idx].get("manual_focus", False))
            self.main_window.camera_tab_focus_slider.blockSignals(False)
            
        if hasattr(self.main_window, 'camera_tab_manual_exposure'):
            self.main_window.camera_tab_manual_exposure.blockSignals(True)
            self.main_window.camera_tab_manual_exposure.setChecked(self.camera_configs[idx].get("manual_exposure", False))
            self.main_window.camera_tab_manual_exposure.blockSignals(False)
        if hasattr(self.main_window, 'camera_tab_exposure_slider'):
            self.main_window.camera_tab_exposure_slider.blockSignals(True)
            self.main_window.camera_tab_exposure_slider.setValue(self.camera_configs[idx].get("exposure_value", 0))
            self.main_window.camera_tab_exposure_slider.setEnabled(self.camera_configs[idx].get("manual_exposure", False))
            self.main_window.camera_tab_exposure_slider.blockSignals(False)

        # Update motion detection settings
        if hasattr(self.main_window, 'motion_detection_enabled'):
            self.main_window.motion_detection_enabled.setChecked(self.camera_configs[idx].get("motion_enabled", False))
        if hasattr(self.main_window, 'motion_detection_sensitivity'):
            self.main_window.motion_detection_sensitivity.setValue(self.camera_configs[idx].get("motion_sensitivity", 20))
        if hasattr(self.main_window, 'motion_detection_min_area'):
            self.main_window.motion_detection_min_area.setValue(self.camera_configs[idx].get("motion_min_area", 500))
            
        self.update_overlay_selector()

    def update_camera_display(self):
        if not self.camera_label: return
        for i in range(4):
            pix = self.current_frames[i]
            if i == self.main_view_index:
                if pix: self.camera_label.setPixmap(pix.scaled(self.camera_label.size(), Qt.AspectRatioMode.KeepAspectRatio))
                else: self.camera_label.setText(f"Cam {i+1} disconnected")
            if hasattr(self.main_window, 'camera_preview_labels') and i < len(self.main_window.camera_preview_labels):
                lbl = self.main_window.camera_preview_labels[i]
                if pix: lbl.setPixmap(pix.scaled(lbl.size(), Qt.AspectRatioMode.KeepAspectRatio))
                else: lbl.setText(f"C{i+1}")
                # Maintain the cursor and other styles while updating the border
                border_color = "#4CAF50" if i == self.main_view_index else "#333"
                lbl.setStyleSheet(f"background: black; color: white; border: 2px solid {border_color};")
                lbl.setCursor(Qt.CursorShape.PointingHandCursor)
    
    def handle_motion_detection_state(self, state):
        idx = self.active_camera_index
        if self.camera_threads[idx]: self.camera_threads[idx].set_motion_detection_enabled(state)

    @pyqtSlot(bool)
    def _handle_record_video_toggled(self, checked):
        """Handle manual toggle of the record video checkbox"""
        index = self.active_camera_index
        self.camera_configs[index]["record_video"] = checked
        
        # If a run is active, we should start or stop recording for this camera
        is_run_active = getattr(self.main_window, 'running', False)
        if is_run_active:
            if checked and not self.is_recording[index] and self.is_connected[index]:
                self.logger.log(f"Recording enabled for Camera {index+1} during run, starting...")
                
                output_dir = "recordings"
                if hasattr(self.main_window, 'project_controller'):
                    run_dir = self.main_window.project_controller.get_current_run_directory()
                    if run_dir: output_dir = run_dir
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                quality = int(self.settings.get_value("video_quality", "70"))
                fname = f"recording_cam{index+1}_{timestamp}.mp4"
                
                if self.camera_threads[index]:
                    self.camera_threads[index].set_video_quality(quality)
                    self.camera_threads[index].set_overlays(self.overlays[index])
                    success = self.camera_threads[index].start_recording(
                        output_dir=output_dir, filename=fname, codec="H264",
                        record_audio=self.camera_configs[index].get("record_audio", False),
                        audio_device_index=self.camera_configs[index].get("audio_device", -1)
                    )
                    if success:
                        self.is_recording[index] = True
                        self._append_video_segment_metadata({
                            "path": os.path.join(output_dir, fname), 
                            "start_epoch": time.time(), 
                            "camera_index": index
                        })
            elif not checked and self.is_recording[index]:
                self.logger.log(f"Recording disabled for Camera {index+1} during run, stopping...")
                path = getattr(self.camera_threads[index], "output_file", "")
                start_time = getattr(self.camera_threads[index], "recording_start_time", None)
                self.camera_threads[index].stop_recording()
                self.is_recording[index] = False
                self._finalize_video_segment_metadata(path, time.time(), start_time)

    @pyqtSlot(int, bool)
    def _handle_motion_enabled_changed(self, index, state):
        self.camera_configs[index]["motion_enabled"] = state
        if self.camera_threads[index]: self.camera_threads[index].set_motion_detection_enabled(state)

    @pyqtSlot()
    def _handle_motion_settings_changed(self):
        idx = self.active_camera_index
        sensitivity = self.motion_sensitivity_widget.value()
        min_area = self.motion_min_area_widget.value()
        self.camera_configs[idx]["motion_sensitivity"] = sensitivity
        self.camera_configs[idx]["motion_min_area"] = min_area
        if self.camera_threads[idx]:
            self.camera_threads[idx].update_motion_detection_settings(sensitivity, min_area)

    @pyqtSlot(int, bool)
    def _update_motion_indicator(self, index, detected):
        if index == self.main_view_index and self.motion_indicator:
            self.motion_indicator.setStyleSheet(f"background-color: {'red' if detected else 'green'}; border-radius: 5px;")
            
        # Add to automation context for triggers
        cam_event = f'motion_detected_cam{index+1}'
        if detected:
            self._add_automation_event('motion_detected')
            self._add_automation_event(cam_event)
        else:
            # We don't remove it immediately to allow sequences to catch it, 
            # but for motion we usually want edge detection.
            # Actually, _add_automation_event handles the set/dict logic.
            self._remove_automation_event('motion_detected')
            self._remove_automation_event(cam_event)
    
    def get_audio_devices(self):
        from app.core.direct_camera import DirectCameraThread
        return DirectCameraThread.get_audio_input_devices()

    def choose_text_color(self):
        if not self.selected_overlay: return
        initial = QColor(self.selected_overlay.text_color[2], 
                        self.selected_overlay.text_color[1], 
                        self.selected_overlay.text_color[0])
        color = QColorDialog.getColor(initial, self.main_window, "Select Text Color")
        if color.isValid():
            # Convert QColor (RGB) to BGR tuple for OpenCV
            self.selected_overlay.text_color = (color.blue(), color.green(), color.red())
            self.apply_overlay_settings()

    def choose_bg_color(self):
        if not self.selected_overlay: return
        initial = QColor(self.selected_overlay.bg_color[2], 
                        self.selected_overlay.bg_color[1], 
                        self.selected_overlay.bg_color[0])
        color = QColorDialog.getColor(initial, self.main_window, "Select Background Color")
        if color.isValid():
            # Convert QColor (RGB) to BGR tuple for OpenCV
            self.selected_overlay.bg_color = (color.blue(), color.green(), color.red())
            self.apply_overlay_settings()

    def update_camera_settings(self, **kwargs): pass
    def force_disconnect(self): self.close_camera()
