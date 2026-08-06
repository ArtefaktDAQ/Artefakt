"""
MCP Server for Artefakt DAQ
Provides tools for AI Assistant to access DAQ data.
"""
import json
import time
import bisect
import re
import inspect
import os
import sys
import cv2
import numpy as np
import base64
import traceback
from datetime import datetime
from typing import List, Dict, Any, Optional
import threading
from PyQt6.QtCore import QObject, QMetaObject, Qt, Q_RETURN_ARG, Q_ARG, pyqtSlot, QThread, QCoreApplication, pyqtSignal, QBuffer, QIODevice
from PyQt6.QtGui import QTextCursor
from PyQt6.QtMultimedia import QMediaDevices

class MCPServer(QObject):
    """
    A server that provides access to application data following a tool-based protocol.
    Provides tools for the LLM to query sensor data, sampling rates, and notes.
    """
    # Signal used to safely dispatch tool calls to the main GUI thread
    # Parameters: tool_name, arguments, result_container_dict
    _dispatch_signal = pyqtSignal(str, dict, object)

    # Tools that are safe to run in the background thread (no direct QWidget access)
    # This prevents the UI from freezing while the AI is processing data.
    SAFE_BACKGROUND_TOOLS = [
        "get_sampling_rate",
        "query_sensor_data",
        "get_sensor_statistics",
        "get_automation_info",
        "get_available_sensors",
        "get_current_time",
        "get_data_summary",
        "get_project_config",
        "get_documentation",
        "get_projects_list",
        "get_csv_preview",
        "list_available_interfaces",
        "get_interface_schema",
        "get_live_interface_data",
        "check_server_status",
        "list_serial_ports",
        "get_serial_sequence",
        "list_serial_sequences",
    ]

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        
        # Connect the signal to the internal dispatcher using a BlockingQueuedConnection.
        # This ensures the call happens on the main thread and the background thread waits for it.
        self._dispatch_signal.connect(self._dispatch_to_main_thread, Qt.ConnectionType.BlockingQueuedConnection)
        
        # Ensure this object stays on the main thread (where it was created)
        if main_window and hasattr(main_window, 'thread'):
            self.moveToThread(main_window.thread())

    def _check_permission(self, setting_key: str) -> bool:
        """Check if a specific tool category is enabled in settings."""
        if hasattr(self.main_window, 'settings'):
            val = self.main_window.settings.value(setting_key, "true")
            return str(val).lower() == "true"
        return True

    def _app_root(self):
        import sys
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

    def _validate_path_component(self, name: str, label: str) -> Optional[str]:
        """Reject empty names and path traversal in project path components."""
        if not name or not str(name).strip():
            return f"{label} must not be empty."
        if '..' in name or '/' in name or '\\' in name:
            return f"Invalid {label}: path separators and '..' are not allowed."
        return None

    def _get_allowed_path_roots(self) -> List[str]:
        """Return normalized absolute roots permitted for file-path MCP tools."""
        roots = []
        if hasattr(self.main_window, 'project_base_dir'):
            base = self.main_window.project_base_dir.text().strip()
            if base:
                roots.append(os.path.normpath(os.path.realpath(os.path.abspath(base))))
        app_root = os.path.normpath(os.path.realpath(self._app_root()))
        roots.append(app_root)
        plugins_dir = os.path.join(app_root, "plugins")
        if os.path.isdir(plugins_dir):
            roots.append(os.path.normpath(os.path.realpath(plugins_dir)))
        if hasattr(self.main_window, 'project_controller'):
            run_dir = self.main_window.project_controller.get_current_run_directory()
            if run_dir:
                roots.append(os.path.normpath(os.path.realpath(os.path.abspath(run_dir))))
        return roots

    def _is_path_allowed(self, file_path: str) -> bool:
        """Return True if file_path resolves under an allowed application directory."""
        if not file_path or not str(file_path).strip():
            return False
        try:
            resolved = os.path.normpath(os.path.realpath(os.path.abspath(file_path)))
        except (OSError, ValueError):
            return False
        for root in self._get_allowed_path_roots():
            root_prefix = root if root.endswith(os.sep) else root + os.sep
            if resolved == root or resolved.startswith(root_prefix):
                return True
        return False

    @pyqtSlot(object)
    def _get_device_names_internal(self, names_dict: dict):
        """Helper to get video input names on the main thread."""
        try:
            from PyQt6.QtMultimedia import QMediaDevices
            devices = QMediaDevices.videoInputs()
            for i, dev in enumerate(devices):
                names_dict[i] = dev.description()
        except Exception as e:
            print(f"[MCP] Error getting device names: {e}")

    def set_dashboard_config(self, 
                             show_automation: bool = None, 
                             show_events: bool = None, 
                             show_image: bool = None, 
                             show_camera: bool = None,
                             timespan: str = None,
                             camera_slots: List[bool] = None) -> Dict[str, Any]:
        """
        Configure dashboard visibility options, timespan, and active camera slots.
        - show_automation, show_events, show_image, show_camera: bool to toggle visibility.
        - timespan: one of ["10s", "30s", "1min", "5min", "15min", "30min", "1h", "3h", "6h", "12h", "24h", "All"].
        - camera_slots: list of 4 booleans for Cam 1-4.
        """
        if not self.main_window:
            return {"error": "Main window not available"}
            
        results = []
        if show_automation is not None and hasattr(self.main_window, 'checkbox_automation_status'):
            self.main_window.checkbox_automation_status.setChecked(show_automation)
            results.append(f"Automation visibility: {show_automation}")
            
        if show_events is not None and hasattr(self.main_window, 'checkbox_recent_events'):
            self.main_window.checkbox_recent_events.setChecked(show_events)
            results.append(f"Events visibility: {show_events}")
            
        if show_image is not None and hasattr(self.main_window, 'checkbox_image'):
            self.main_window.checkbox_image.setChecked(show_image)
            results.append(f"Image visibility: {show_image}")
            
        if show_camera is not None and hasattr(self.main_window, 'checkbox_camera_preview'):
            self.main_window.checkbox_camera_preview.setChecked(show_camera)
            results.append(f"Camera visibility: {show_camera}")
            
        if timespan is not None and hasattr(self.main_window, 'dashboard_timespan'):
            index = self.main_window.dashboard_timespan.findText(timespan)
            if index >= 0:
                self.main_window.dashboard_timespan.setCurrentIndex(index)
                results.append(f"Timespan set to: {timespan}")
            else:
                results.append(f"Error: Timespan '{timespan}' not found")
                
        if camera_slots is not None and hasattr(self.main_window, 'dashboard_camera_checkboxes'):
            for i, checked in enumerate(camera_slots):
                if i < len(self.main_window.dashboard_camera_checkboxes):
                    self.main_window.dashboard_camera_checkboxes[i].setChecked(checked)
            results.append(f"Camera slots updated: {camera_slots}")
            
        return {"message": "; ".join(results) if results else "No changes applied"}

    def set_graph_config(self,
                         graph_type: str = None,
                         primary_sensor: str = None,
                         secondary_sensor: str = None,
                         timespan: str = None,
                         style_preset: str = None,
                         show_control_run: bool = None,
                         control_run_offset: float = None,
                         line_width: int = None) -> Dict[str, Any]:
        """
        Configure the main graph view options.
        - graph_type: "Standard Time Series", "Temperature Difference", "Rate of Change (dT/dt)", "Moving Average", "Fourier Analysis", "Histogram", "Box Plot", "Correlation Analysis".
        - primary_sensor: sensor ID to plot.
        - secondary_sensor: sensor ID for secondary axis.
        - timespan: "10s", "30s", "1min", "5min", "15min", "30min", "1h", "3h", "6h", "12h", "24h", "All".
        - style_preset: "Standard", "Solarized", "Dark", "High Contrast", "Pastel", "Colorful".
        - show_control_run: boolean to show/hide control run data.
        - control_run_offset: float (seconds) to shift control run data in time.
        - line_width: integer for plot line thickness.
        """
        if not self.main_window:
            return {"error": "Main window not available"}
            
        results = []
        
        if graph_type is not None and hasattr(self.main_window, 'graph_type_combo'):
            index = self.main_window.graph_type_combo.findText(graph_type)
            if index >= 0:
                self.main_window.graph_type_combo.setCurrentIndex(index)
                results.append(f"Graph type set to: {graph_type}")
            else:
                results.append(f"Error: Graph type '{graph_type}' not found")
                
        if primary_sensor is not None and hasattr(self.main_window, 'graph_primary_sensor'):
            index = self.main_window.graph_primary_sensor.findText(primary_sensor)
            if index >= 0:
                self.main_window.graph_primary_sensor.setCurrentIndex(index)
                results.append(f"Primary sensor set to: {primary_sensor}")
            else:
                results.append(f"Error: Primary sensor '{primary_sensor}' not found")
                
        if secondary_sensor is not None and hasattr(self.main_window, 'graph_secondary_sensor'):
            index = self.main_window.graph_secondary_sensor.findText(secondary_sensor)
            if index >= 0:
                self.main_window.graph_secondary_sensor.setCurrentIndex(index)
                results.append(f"Secondary sensor set to: {secondary_sensor}")
            else:
                results.append(f"Error: Secondary sensor '{secondary_sensor}' not found")
                
        if timespan is not None and hasattr(self.main_window, 'graph_timespan'):
            index = self.main_window.graph_timespan.findText(timespan)
            if index >= 0:
                self.main_window.graph_timespan.setCurrentIndex(index)
                results.append(f"Timespan set to: {timespan}")
            else:
                results.append(f"Error: Timespan '{timespan}' not found")
                
        if style_preset is not None and hasattr(self.main_window, 'plot_style_preset'):
            index = self.main_window.plot_style_preset.findText(style_preset)
            if index >= 0:
                self.main_window.plot_style_preset.setCurrentIndex(index)
                results.append(f"Style preset set to: {style_preset}")
            else:
                results.append(f"Error: Style preset '{style_preset}' not found")
                
        if show_control_run is not None and hasattr(self.main_window, 'show_control_run_checkbox'):
            self.main_window.show_control_run_checkbox.setChecked(show_control_run)
            results.append(f"Show control run: {show_control_run}")

        if control_run_offset is not None and hasattr(self.main_window, 'control_run_time_offset'):
            self.main_window.control_run_time_offset.setValue(control_run_offset)
            results.append(f"Control run offset set to: {control_run_offset}s")
            
        if line_width is not None and hasattr(self.main_window, 'plot_line_width'):
            self.main_window.plot_line_width.setValue(line_width)
            results.append(f"Line width set to: {line_width}")
            
        # Trigger update if any changes were made
        if results and hasattr(self.main_window, 'update_graph'):
            self.main_window.update_graph()
            
        return {"message": "; ".join(results) if results else "No changes applied"}

    def control_playback(self, 
                         action: str = None, 
                         speed: str = None, 
                         position: str = None, 
                         step_frames: int = None) -> Dict[str, Any]:
        """
        Control data/video playback.
        - action: "play", "pause", "toggle", "stop".
        - speed: "0.25x", "0.5x", "1x", "2x", "4x".
        - position: time string like "12:21" or "12m 21s" or "0".
        - step_frames: integer (positive for forward, negative for backward).
        """
        if not self.main_window:
            return {"error": "Main window not available"}
            
        results = []
        
        if action:
            if action == "play":
                if not getattr(self.main_window, 'replay_is_playing', False):
                    self.main_window.on_replay_play_toggle()
                results.append("Playback: Play")
            elif action == "pause":
                if getattr(self.main_window, 'replay_is_playing', False):
                    self.main_window.on_replay_play_toggle()
                results.append("Playback: Pause")
            elif action == "toggle":
                self.main_window.on_replay_play_toggle()
                results.append("Playback: Toggled")
            elif action == "stop":
                if getattr(self.main_window, 'replay_is_playing', False):
                    self.main_window.on_replay_play_toggle()
                self.main_window._update_replay_frame(0.0, update_sliders=True, force_video_seek=True)
                results.append("Playback: Stopped and reset to 0")

        if speed and hasattr(self.main_window, 'replay_speed'):
            index = self.main_window.replay_speed.findText(speed)
            if index >= 0:
                self.main_window.replay_speed.setCurrentIndex(index)
                results.append(f"Speed set to: {speed}")
            else:
                results.append(f"Error: Speed '{speed}' not found")
                
        if position:
            if self.main_window.set_replay_position_by_string(position):
                results.append(f"Position set to: {position}")
            else:
                results.append(f"Error: Failed to set position to '{position}'")
                
        if step_frames is not None:
            if step_frames > 0:
                self.main_window.step_replay_forward(step_frames)
                results.append(f"Stepped forward {step_frames} frames")
            elif step_frames < 0:
                self.main_window.step_replay_backward(abs(step_frames))
                results.append(f"Stepped backward {abs(step_frames)} frames")
                
        return {"message": "; ".join(results) if results else "No changes applied"}

    def add_quick_note(self, text: str) -> Dict[str, Any]:
        """Add a quick timestamped note to the current run or replay."""
        if not self.main_window:
            return {"error": "Main window not available"}
            
        if self.main_window.add_quick_note(text):
            return {"message": f"Note added: {text}"}
        else:
            return {"error": "Failed to add note. Ensure a project is loaded or running."}

    def update_app_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update application settings.
        - settings: dictionary of key-value pairs to update in SettingsManager.
        """
        if not self._check_permission("ai_allow_config"):
            return {"error": "Configuration changes are disabled by the user."}

        if not hasattr(self.main_window, 'settings_manager'):
            return {"error": "Settings manager not available"}
            
        results = []
        for key, value in settings.items():
            self.main_window.settings_manager.set(key, value)
            results.append(f"Setting '{key}' set to {value}")
            
        self.main_window.settings_manager.save_settings()
        return {"message": "; ".join(results) if results else "No changes applied"}

    def save_plugin_code(self, filename: str, code: str) -> Dict[str, Any]:
        """
        Create or update a plugin file in the 'plugins/' directory.
        """
        if not self._check_permission("ai_allow_config"):
            return {"error": "Plugin and config changes are disabled by the user."}

        if not filename.endswith(".py"):
            return {"error": "Filename must end with .py"}
            
        # Clean filename to prevent path traversal
        clean_filename = os.path.basename(filename)
        plugin_dir = os.path.join(self._app_root(), "plugins")
        
        if not os.path.exists(plugin_dir):
            try:
                os.makedirs(plugin_dir)
            except Exception as e:
                return {"error": f"Failed to create plugins directory: {str(e)}"}
                
        file_path = os.path.join(plugin_dir, clean_filename)
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code)
            
            # Trigger a reload of the interface registry so the new plugin is immediately available
            try:
                from app.core.interfaces.interface_registry import InterfaceRegistry
                InterfaceRegistry._initialized = False
                InterfaceRegistry.initialize()
                
                # Also trigger reload in the DataCollectionController if it exists
                if hasattr(self.main_window, 'data_collection_controller'):
                    self.main_window.data_collection_controller.reload_outbound_plugins()
                
                refresh_msg = " (Interface Registry refreshed)"
            except Exception as e:
                refresh_msg = f" (Warning: Could not refresh registry: {str(e)})"
                
            return {"message": f"Plugin saved successfully to {clean_filename}{refresh_msg}", "path": file_path}
        except Exception as e:
            return {"error": f"Failed to save plugin: {str(e)}"}

    def list_plugins(self) -> Dict[str, Any]:
        """List all Python files in the plugins directory."""
        if not self._check_permission("ai_allow_config"):
            return {"error": "Plugin and config changes are disabled by the user."}

        plugin_dir = os.path.join(self._app_root(), "plugins")
        if not os.path.exists(plugin_dir):
            return {"plugins": [], "message": "Plugins directory does not exist."}
            
        try:
            files = [f for f in os.listdir(plugin_dir) if f.endswith(".py")]
            return {"plugins": files}
        except Exception as e:
            return {"error": f"Failed to list plugins: {str(e)}"}

    def read_plugin_code(self, filename: str) -> Dict[str, Any]:
        """Read the source code of a plugin file."""
        if not self._check_permission("ai_allow_config"):
            return {"error": "Plugin and config changes are disabled by the user."}

        if not filename.endswith(".py"):
            return {"error": "Only .py files can be read from the plugins directory."}
            
        clean_filename = os.path.basename(filename)
        plugin_dir = os.path.join(self._app_root(), "plugins")
        file_path = os.path.join(plugin_dir, clean_filename)
        
        if not os.path.exists(file_path):
            return {"error": f"Plugin file '{clean_filename}' not found."}
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            return {"filename": clean_filename, "code": content}
        except Exception as e:
            return {"error": f"Failed to read plugin: {str(e)}"}

    def get_sampling_rate(self) -> float:
        """Get the current global sampling rate in Hz."""
        try:
            if hasattr(self.main_window, 'data_collection_controller'):
                return float(self.main_window.data_collection_controller.sampling_rate)
        except Exception as e:
            print(f"MCP Error get_sampling_rate: {e}")
        return 0.0

    def query_sensor_data(self, timeframe_seconds: int = 60, sensor_ids: Optional[Any] = None) -> Dict[str, Any]:
        """
        Query historical sensor data.
        
        Args:
            timeframe_seconds: How many seconds of history to retrieve. Use 0 for ALL data.
            sensor_ids: Optional list of sensor IDs or names. If a string, it will be treated as a single sensor.
        """
        # Check permission
        if not self._check_permission("ai_allow_sensor_data"):
            return {"error": "Access to sensor data is disabled by the user."}

        if not hasattr(self.main_window, 'data_collection_controller'):
            return {"error": "Data collection controller not available"}
        
        # If timeframe is 0, we use a huge range to get everything
        if timeframe_seconds == 0:
            timeframe_seconds = 86400 * 365 * 10 # 10 years
        if isinstance(sensor_ids, str):
            sensor_ids = [sensor_ids]
            
        controller = self.main_window.data_collection_controller
        
        # Determine the reference "now" time
        # If we have live data, use current system time.
        # If we only have historical CSV data, use the end of that data as "now".
        current_system_time = time.time()
        latest_data_ts = 0
        
        # Check latest in live buffer
        controller.historical_buffer_mutex.lock()
        try:
            for buf in controller.historical_buffer.values():
                if buf:
                    latest_data_ts = max(latest_data_ts, buf[-1][0])
        finally:
            controller.historical_buffer_mutex.unlock()
            
        # Check latest in CSV data
        if hasattr(controller, 'csv_historical_data') and controller.csv_historical_data:
            for s_data in controller.csv_historical_data.values():
                if s_data.get('time'):
                    latest_data_ts = max(latest_data_ts, s_data['time'][-1])
        
        # If the latest data is more than 10 seconds old, we're likely in replay/loaded mode.
        # Use latest data timestamp as the reference point for "the last X seconds".
        if latest_data_ts > 0 and (current_system_time - latest_data_ts > 10.0):
            reference_time = latest_data_ts
        else:
            reference_time = current_system_time
            
        start_time = reference_time - timeframe_seconds
        
        # Data volume check
        total_estimated_points = 0
        if timeframe_seconds > 3600: # More than 1 hour
            sampling_rate = self.get_sampling_rate()
            if sampling_rate > 0:
                total_estimated_points = timeframe_seconds * sampling_rate
        
        results = {}
        # If very large, add a warning for the LLM
        volume_warning = ""
        if total_estimated_points > 100000:
            volume_warning = f"Warning: Requesting ~{int(total_estimated_points)} points. Data retrieval is time-intense. Better query specific timeframes."
        
        # Build mapping of display names to internal keys and track units
        display_to_key = {}
        key_to_unit = {}
        if hasattr(self.main_window, 'sensor_controller'):
            for s in self.main_window.sensor_controller.sensors:
                key = self.main_window.sensor_controller.get_historical_buffer_key(s)
                display_to_key[s.name.lower()] = key
                display_to_key[key.lower()] = key
                key_to_unit[key] = getattr(s, 'unit', '')
                if hasattr(s, 'port') and s.port:
                    display_to_key[s.port.lower()] = key

        # 1. Process Live Buffer Data
        buffer_snapshots = {}
        controller.historical_buffer_mutex.lock()
        try:
            # Quick copy of buffer references to minimize lock time
            for key in controller.historical_buffer.keys():
                # We convert to list to get a static snapshot
                buffer_snapshots[key] = list(controller.historical_buffer[key])
        finally:
            controller.historical_buffer_mutex.unlock()

        target_keys = []
        if sensor_ids:
            for sid in sensor_ids:
                sid_lower = sid.lower()
                if sid_lower in display_to_key:
                    target_keys.append(display_to_key[sid_lower])
                else:
                    # Try case-insensitive match in buffer keys
                    for actual_key in buffer_snapshots.keys():
                        if actual_key.lower() == sid_lower:
                            target_keys.append(actual_key)
                            break
        else:
            # Use all available keys from both buffer and CSV
            all_keys = set(buffer_snapshots.keys())
            if hasattr(controller, 'csv_historical_data'):
                all_keys.update(controller.csv_historical_data.keys())
            target_keys = list(all_keys)

        for key in target_keys:
            data_points = []
            
            # Try live buffer snapshot
            if key in buffer_snapshots:
                buffer = buffer_snapshots[key]
                for ts, val in buffer:
                    if ts >= start_time:
                        data_points.append({"t": round(ts, 3), "v": val})
            
            # Try CSV data if live buffer snapshot didn't have everything or doesn't exist
            # CSV data access is handled via data_collection_controller's own logic
            if hasattr(controller, 'csv_historical_data') and key in controller.csv_historical_data:
                csv_sensor_data = controller.csv_historical_data[key]
                csv_times = csv_sensor_data['time']
                csv_values = csv_sensor_data['value']
                
                # CSV data is usually large, so we find the start index
                idx = bisect.bisect_left(csv_times, start_time)
                for i in range(idx, len(csv_times)):
                    ts = csv_times[i]
                    val = csv_values[i]
                    # Don't add if already in data_points from live buffer
                    # (though usually keys don't overlap in a way that matters here)
                    data_points.append({"t": round(ts, 3), "v": val})
            
            if data_points:
                # Limit output to avoid hitting LLM context limits (last 1000 points)
                if len(data_points) > 1000:
                    data_points = data_points[-1000:]
                    note = f"Truncated to last 1000 points. {volume_warning}"
                else:
                    note = volume_warning
                    
                results[key] = {
                    "unit": key_to_unit.get(key, ""),
                    "count": len(data_points),
                    "data": data_points,
                    "note": note
                }
        
        return results

    def get_notes(self) -> str:
        """Get the current plain text content of the notes document."""
        # Check permission
        if not self._check_permission("ai_allow_notes"):
            return "Access to notes is disabled by the user."

        try:
            if hasattr(self.main_window, 'notes_controller'):
                return self.main_window.notes_controller.notes_editor.toPlainText()
        except Exception as e:
            print(f"MCP Error get_notes: {e}")
        return ""

    def get_notes_html(self) -> str:
        """Get the current HTML content of the notes document including all styling and images."""
        # Check permission
        if not self._check_permission("ai_allow_notes"):
            return "Access to notes is disabled by the user."

        try:
            if hasattr(self.main_window, 'notes_controller'):
                return self.main_window.notes_controller.notes_editor.toHtml()
        except Exception as e:
            print(f"MCP Error get_notes_html: {e}")
        return ""

    def edit_notes(self, html_content: str, search_anchor: Optional[str] = None) -> Dict[str, Any]:
        """
        Insert or append HTML content into the notes.
        - html_content: The HTML string to insert.
        - search_anchor: Optional text to search for. If found, content is inserted after that paragraph.
        """
        if not self._check_permission("ai_allow_notes"):
            return {"error": "Access to notes is disabled by the user."}
            
        try:
            if hasattr(self.main_window, 'notes_controller'):
                success = self.main_window.notes_controller.insert_at_location(html_content, search_anchor)
                if success:
                    return {"message": "Notes updated successfully."}
                else:
                    return {"error": "Failed to update notes."}
        except Exception as e:
            return {"error": f"Error editing notes: {str(e)}"}
        return {"error": "Notes controller not available."}

    def insert_note_media(self, media_type: str, search_anchor: Optional[str] = None) -> Dict[str, Any]:
        """
        Insert a graph or camera screenshot into the notes.
        - media_type: 'graph' or 'camera'.
        - search_anchor: Optional text to search for. If found, media is inserted after that paragraph.
        """
        if not self._check_permission("ai_allow_notes"):
            return {"error": "Access to notes is disabled by the user."}
            
        try:
            if hasattr(self.main_window, 'notes_controller'):
                controller = self.main_window.notes_controller
                
                # If anchor provided, move the editor's cursor there first
                if search_anchor:
                    document = controller.notes_editor.document()
                    search_cursor = QTextCursor(document)
                    found_cursor = document.find(search_anchor, search_cursor)
                    if not found_cursor.isNull():
                        found_cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                        controller.notes_editor.setTextCursor(found_cursor)
                
                if media_type == "graph":
                    controller.insert_graph_image()
                    return {"message": "Graph inserted successfully."}
                elif media_type == "camera":
                    controller.insert_video_image()
                    return {"message": "Camera snapshot inserted successfully."}
                else:
                    return {"error": f"Invalid media type: {media_type}. Use 'graph' or 'camera'."}
        except Exception as e:
            return {"error": f"Error inserting media: {str(e)}"}
        return {"error": "Notes controller not available."}

    def get_automation_info(self) -> Dict[str, Any]:
        """Get detailed information about automation sequences, their states, and shared variables."""
        # Check permission
        if not self._check_permission("ai_allow_automation"):
            return {"error": "Access to automation information is disabled by the user."}

        if not hasattr(self.main_window, 'automation_controller'):
            return {"error": "Automation controller not available"}
        
        try:
            controller = self.main_window.automation_controller
            manager = controller.manager
            
            sequences = []
            for seq in manager.sequences:
                is_running = seq in manager.active_sequences
                status = "STOPPED (IDLE - NO TRIGGERS ARE BEING CHECKED)"
                if is_running:
                    status = "RUNNING (ACTIVE - WATCHING TRIGGERS)"
                elif hasattr(seq, '_current_step_failed') and seq._current_step_failed:
                    status = "FAILED"
                
                # Get step descriptions for more context
                step_details = []
                for i, step in enumerate(seq.steps):
                    trigger_desc = getattr(step.trigger, 'description', 'Unknown Trigger')
                    action_desc = getattr(step.action, 'description', 'Unknown Action')
                    step_details.append({
                        "step": i + 1,
                        "trigger": trigger_desc,
                        "action": action_desc,
                        "enabled": step.enabled,
                        "is_active": (is_running and seq.current_step_index == i)
                    })

                sequences.append({
                    "name": seq.name,
                    "status": status,
                    "step_count": len(seq.steps),
                    "current_step": seq.current_step_index + 1 if is_running else 0,
                    "loop": getattr(seq, 'loop', False),
                    "steps": step_details
                })
                
            serial_seq_count = len(getattr(self.main_window, 'other_sequences', None) or [])
            return {
                "sequences": sequences,
                "active_sequences_count": len(manager.active_sequences),
                "shared_variables": manager.variables if hasattr(manager, 'variables') else {},
                "note": "Shared variables can be used across sequences and by SystemActions.",
                "tip": (
                    "This tool lists Automations only. "
                    f"There are currently {serial_seq_count} Serial protocol sequence(s) — "
                    "inspect those with get_serial_sequence (not get_automation_info)."
                )
            }
        except Exception as e:
            return {"error": f"Failed to get automation info: {str(e)}"}

    def get_project_config(self) -> Dict[str, Any]:
        """
        Returns the complete system configuration for AI context.
        Use this to understand sensor calibrations, full automation logic, and app settings.
        """
        config = {
            "app_settings": {},
            "sensors": [],
            "automation": []
        }
        
        try:
            # 1. Add general settings
            if hasattr(self.main_window, 'settings_model'):
                keys = [
                    "theme", "arduino_port", "arduino_baud", "labjack_type", 
                    "sampling_rate", "enable_ndi", "camera_resolution",
                    "motion_detection_enabled", "auto_record", "plot_style_preset",
                    "plot_line_width"
                ]
                config["app_settings"] = {k: self.main_window.settings_model.get_value(k) for k in keys}
                
            # 2. Add full sensor models
            if hasattr(self.main_window, 'sensor_controller'):
                config["sensors"] = [s.to_dict() for s in self.main_window.sensor_controller.sensors]
                
            # 3. Add full automation sequences
            if hasattr(self.main_window, 'automation_controller'):
                config["automation"] = [seq.to_dict() for seq in self.main_window.automation_controller.manager.sequences]
                
            # 4. Add other serial sequences
            if hasattr(self.main_window, 'other_sequences'):
                config["serial_sequences"] = self.main_window.other_sequences
                
            return config
        except Exception as e:
            return {"error": f"Failed to gather project config: {str(e)}"}

    def get_projects_list(self) -> Dict[str, Any]:
        """
        List all projects, test series, and runs available in the base directory.
        """
        # Check permission
        if not self._check_permission("ai_allow_projects"):
            return {"error": "Access to project management is disabled by the user."}

        if not hasattr(self.main_window, 'project_controller'):
            return {"error": "Project controller not available"}
            
        try:
            controller = self.main_window.project_controller
            base_dir = controller.main_window.project_base_dir.text()
            if not base_dir or not os.path.exists(base_dir):
                return {"error": "Project base directory not set or does not exist."}

            projects = []
            for p_name in os.listdir(base_dir):
                p_path = os.path.join(base_dir, p_name)
                if os.path.isdir(p_path) and not p_name.startswith('.'):
                    series_list = []
                    for s_name in os.listdir(p_path):
                        s_path = os.path.join(p_path, s_name)
                        if os.path.isdir(s_path) and not s_name.startswith('.'):
                            runs = []
                            for r_name in os.listdir(s_path):
                                r_path = os.path.join(s_path, r_name)
                                if os.path.isdir(r_path) and not r_name.startswith('.'):
                                    metadata = controller.get_run_metadata(r_path)
                                    runs.append({
                                        "name": r_name,
                                        "tester": metadata.get("tester", "Unknown"),
                                        "description": metadata.get("description", ""),
                                        "date": metadata.get("date", "Unknown"),
                                        "path": r_path
                                    })
                            series_list.append({
                                "name": s_name,
                                "runs": runs
                            })
                    projects.append({
                        "name": p_name,
                        "series": series_list
                    })
            
            return {
                "base_directory": base_dir,
                "projects": projects
            }
        except Exception as e:
            return {"error": f"Failed to list projects: {str(e)}"}

    def set_active_project(self, project_name: str, series_name: str, run_name: str) -> Dict[str, Any]:
        """
        Load a specific project run into the UI for analysis or replay.
        """
        # Check permission
        if not self._check_permission("ai_allow_projects"):
            return {"error": "Access to project management is disabled by the user."}

        if not hasattr(self.main_window, 'project_controller'):
            return {"error": "Project controller not available"}

        for label, value in (
            ("project_name", project_name),
            ("series_name", series_name),
            ("run_name", run_name),
        ):
            err = self._validate_path_component(value, label)
            if err:
                return {"error": err}

        base_dir = self.main_window.project_base_dir.text().strip()
        if not base_dir:
            return {"error": "Project base directory is not configured."}

        run_dir = os.path.normpath(os.path.join(base_dir, project_name, series_name, run_name))
        base_abs = os.path.normpath(os.path.abspath(base_dir))
        run_abs = os.path.normpath(os.path.abspath(run_dir))
        if run_abs != base_abs and not run_abs.startswith(base_abs + os.sep):
            return {"error": "Requested run path escapes the project base directory."}

        try:
            # We must use QMetaObject to call this on the main thread safely if not already there
            # but execute_tool handles the thread dispatch for us.
            self.main_window.project_controller.load_run(project_name, series_name, run_name)
            return {"status": "success", "message": f"Loaded run '{run_name}'"}
        except Exception as e:
            return {"error": f"Failed to set active project: {str(e)}"}

    def configure_next_run(self, testers: str = None, description: str = None, sampling_rate: float = None) -> Dict[str, Any]:
        """
        Configure the upcoming data acquisition run in the UI.
        """
        # Check permission
        if not self._check_permission("ai_allow_projects"):
            return {"error": "Access to project management is disabled by the user."}

        try:
            updates = []
            if testers is not None:
                if hasattr(self.main_window, 'run_testers'):
                    self.main_window.run_testers.setText(testers)
                    updates.append("testers")
            
            if description is not None:
                if hasattr(self.main_window, 'run_description'):
                    self.main_window.run_description.setPlainText(description)
                    updates.append("description")
                    
            if sampling_rate is not None:
                if hasattr(self.main_window, 'sampling_rate_spinbox'):
                    self.main_window.sampling_rate_spinbox.setValue(sampling_rate)
                    updates.append("sampling_rate")
            
            if not updates:
                return {"status": "no_change", "message": "No configuration parameters provided."}
                
            return {"status": "success", "message": f"Updated {', '.join(updates)} in the UI for the next run."}
        except Exception as e:
            return {"error": f"Failed to update UI configuration: {str(e)}"}

    def export_run(self) -> Dict[str, Any]:
        """
        Trigger the export dialog for the currently selected or active project item.
        """
        # Check permission
        if not self._check_permission("ai_allow_projects"):
            return {"error": "Access to project management is disabled by the user."}

        if not hasattr(self.main_window, 'project_controller'):
            return {"error": "Project controller not available"}

        try:
            # This will open a dialog, which might pause the AI or require user input
            self.main_window.project_controller.export_project()
            return {"status": "success", "message": "Export process initiated."}
        except Exception as e:
            return {"error": f"Failed to initiate export: {str(e)}"}

    def import_run(self) -> Dict[str, Any]:
        """
        Trigger the import dialog to add a project archive to the system.
        """
        # Check permission
        if not self._check_permission("ai_allow_projects"):
            return {"error": "Access to project management is disabled by the user."}

        if not hasattr(self.main_window, 'project_controller'):
            return {"error": "Project controller not available"}

        try:
            # This will open a file dialog
            self.main_window.project_controller.import_project()
            return {"status": "success", "message": "Import process initiated."}
        except Exception as e:
            return {"error": f"Failed to initiate import: {str(e)}"}

    def get_documentation(self, topic: str = "overview") -> str:
        """
        Access the internal AI Information System to read about how the app works.
        Topics: 'overview', 'sensors', 'automation', 'vision', 'tools_overview', 'tools_fft', etc.
        """
        doc_map = {
            "overview": "app/core/docs/overview.md",
            "projects": "app/core/docs/overview.md",
            "sensors": "app/core/docs/sensors_guide.md",
            "sensors_arduino": "app/core/docs/sensors_arduino.md",
            "sensors_serial": "app/core/docs/sensors_serial.md",
            "sensors_labjack": "app/core/docs/sensors_labjack.md",
            "sensors_mqtt": "app/core/docs/sensors_mqtt.md",
            "sensors_csv": "app/core/docs/sensors_csv.md",
            "sensors_advanced": "app/core/docs/sensors_advanced.md",
            "sensors_optical": "app/core/docs/sensors_optical.md",
            "sensors_audio": "app/core/docs/sensors_audio.md",
            "automation": "app/core/docs/automation_logic.md",
            "vision": "app/core/docs/vision_guide.md",
            "camera": "app/core/docs/camera_vision_logic.md",
            "dashboard_video": "app/core/docs/dashboard_video_guide.md",
            "ai_graphs": "app/core/docs/ai_graphs_guide.md",
            "tools_overview": "app/core/docs/tools_overview.md",
            "tools_fft": "app/core/docs/tools_fft.md",
            "tools_calibration": "app/core/docs/tools_calibration.md",
            "tools_statistics": "app/core/docs/tools_statistics.md",
            "tools_diagnostics": "app/core/docs/tools_diagnostics.md",
            "tools_calculator": "app/core/docs/tools_calculator.md",
            "tools_optical_rpm": "app/core/docs/tools_optical_rpm.md",
            "sensors_remote_daq": "app/core/docs/sensors_remote_daq.md",
            "remote_grpc": "app/core/docs/sensors_remote_daq.md",
            "plugins": "app/core/docs/plugins_guide.md"
        }
        
        path = doc_map.get(topic.lower())
        if not path:
            return f"Error: Topic '{topic}' not found. Available: {list(doc_map.keys())}"
            
        try:
            abs_path = os.path.join(self._app_root(), path)
            if not os.path.exists(abs_path):
                return f"Error: Documentation file not found at {abs_path}."
                
            with open(abs_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Error reading documentation: {str(e)}"

    def get_available_sensors(self) -> List[Dict[str, Any]]:
        """Get a list of all configured sensors with their names, IDs, and metadata."""
        if not hasattr(self.main_window, 'sensor_controller'):
            return []
            
        sensors = []
        controller = getattr(self.main_window, 'data_collection_controller', None)
        
        for s in self.main_window.sensor_controller.sensors:
            internal_key = self.main_window.sensor_controller.get_historical_buffer_key(s)
            
            # Check if this sensor has ANY data in live or CSV
            has_data = False
            if controller:
                controller.historical_buffer_mutex.lock()
                try:
                    if internal_key in controller.historical_buffer and controller.historical_buffer[internal_key]:
                        has_data = True
                finally:
                    controller.historical_buffer_mutex.unlock()
                if not has_data and hasattr(controller, 'csv_historical_data') and internal_key in controller.csv_historical_data:
                    if controller.csv_historical_data[internal_key].get('time'):
                        has_data = True

            sensors.append({
                "name": s.name,
                "id": internal_key,
                "interface": s.interface_type,
                "unit": getattr(s, 'unit', ''),
                "port": getattr(s, 'port', ''),
                "offset": getattr(s, 'offset', 0.0),
                "factor": getattr(s, 'conversion_factor', 1.0),
                "color": getattr(s, 'color', '#FFFFFF'),
                "enabled": getattr(s, 'enabled', True),
                "show_in_graph": getattr(s, 'show_in_graph', True),
                "use_secondary_axis": getattr(s, 'use_secondary_axis', False),
                "averaging_enabled": getattr(s, 'averaging_enabled', False),
                "current_value": getattr(s, 'current_value', None),
                "has_data_in_run": has_data
            })
        return sensors

    def get_current_time(self) -> Dict[str, Any]:
        """Get the current system time and the time of the latest available data point."""
        current_system_time = time.time()
        latest_data_ts = 0
        
        if hasattr(self.main_window, 'data_collection_controller'):
            controller = self.main_window.data_collection_controller
            
            # Check latest in live buffer
            controller.historical_buffer_mutex.lock()
            try:
                for buf in controller.historical_buffer.values():
                    if buf:
                        latest_data_ts = max(latest_data_ts, buf[-1][0])
            finally:
                controller.historical_buffer_mutex.unlock()
                
            # Check latest in CSV data
            if hasattr(controller, 'csv_historical_data') and controller.csv_historical_data:
                for s_data in controller.csv_historical_data.values():
                    if s_data.get('time'):
                        latest_data_ts = max(latest_data_ts, s_data['time'][-1])

        # Logical "now" for timeframe calculations
        if latest_data_ts > 0 and (current_system_time - latest_data_ts > 10.0):
            reference_now = latest_data_ts
            mode = "Replay/Loaded Run"
        else:
            reference_now = current_system_time
            mode = "Live Monitoring"

        return {
            "current_system_time": current_system_time,
            "current_system_datetime": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_system_time)),
            "latest_data_timestamp": latest_data_ts,
            "latest_data_datetime": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(latest_data_ts)) if latest_data_ts > 0 else "None",
            "logical_now_timestamp": reference_now,
            "logical_now_datetime": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(reference_now)),
            "system_mode": mode
        }

    def get_data_summary(self) -> Dict[str, Any]:
        """Get a summary of all available data including time ranges and sensor counts."""
        if not hasattr(self.main_window, 'data_collection_controller'):
            return {"error": "Data collection controller not available"}
            
        controller = self.main_window.data_collection_controller
        summary = {
            "sampling_rate_hz": getattr(controller, 'sampling_rate', 0.0),
            "live_buffer": {"sensor_count": 0, "start_time": None, "end_time": None},
            "csv_historical": {"sensor_count": 0, "start_time": None, "end_time": None}
        }
        
        # Live buffer summary
        controller.historical_buffer_mutex.lock()
        try:
            summary["live_buffer"]["sensor_count"] = len(controller.historical_buffer)
            all_ts = []
            for buf in controller.historical_buffer.values():
                if buf:
                    all_ts.append(buf[0][0])
                    all_ts.append(buf[-1][0])
            if all_ts:
                summary["live_buffer"]["start_time"] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(min(all_ts)))
                summary["live_buffer"]["end_time"] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(max(all_ts)))
        finally:
            controller.historical_buffer_mutex.unlock()
            
        # CSV historical summary
        if hasattr(controller, 'csv_historical_data') and controller.csv_historical_data:
            summary["csv_historical"]["sensor_count"] = len(controller.csv_historical_data)
            all_ts_csv = []
            for s_data in controller.csv_historical_data.values():
                if s_data.get('time'):
                    all_ts_csv.append(s_data['time'][0])
                    all_ts_csv.append(s_data['time'][-1])
            if all_ts_csv:
                summary["csv_historical"]["start_time"] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(min(all_ts_csv)))
                summary["csv_historical"]["end_time"] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(max(all_ts_csv)))
        
        # Add run directory info if available
        if hasattr(controller, 'run_directory'):
            summary["run_directory"] = controller.run_directory
                
        return summary

    def get_graph_screenshot(self, graph_type: str = "dashboard", max_width: Optional[int] = None) -> Dict[str, Any]:
        """
        Capture a screenshot of a graph and return as base64.
        
        Args:
            graph_type: Either 'dashboard' or 'graphs_tab'.
            max_width: Optional override for maximum image width.
        """
        # Check permission
        if not self._check_permission("ai_allow_vision"):
            return {"error": "Access to graph screenshots (vision) is disabled by the user."}

        try:
            widget = None
            if graph_type == "dashboard":
                widget = getattr(self.main_window, 'dashboard_graph_widget', None)
            else:
                widget = getattr(self.main_window, 'graph_widget', None)
                
            if widget is None:
                return {"error": f"Graph widget '{graph_type}' not found"}
                
            from PyQt6.QtCore import QBuffer, QIODevice, Qt
            import base64
            
            # Use grab() to capture the widget's visual state
            pixmap = widget.grab()
            
            # Optimization: Resize if too large to improve speed
            # Default to 512 for tool calls if not specified, as it's much faster for vision models
            max_w = self.main_window.settings_model.get_int("ai_max_image_width", 512)
            if max_width is not None:
                max_w = max_width
            
            if pixmap.width() > max_w:
                pixmap = pixmap.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
            
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            
            # Use JPEG for smaller payload size, with configurable quality from settings. Default 40 for speed.
            quality = self.main_window.settings_model.get_int("ai_image_quality", 40)
                
            pixmap.save(buffer, "JPEG", quality=quality)
            img_base64 = base64.b64encode(buffer.data().data()).decode()
            
            return {
                "format": "jpeg",
                "base64": img_base64,
                "width": pixmap.width(),
                "height": pixmap.height(),
                "graph_source": graph_type,
                "note": f"Screenshot of {graph_type} captured successfully. I should analyze this image."
            }
        except Exception as e:
            return {"error": f"Failed to capture graph: {str(e)}"}

    def list_camera_sources(self) -> Dict[str, Any]:
        """List all available local cameras and NDI sources."""
        if not hasattr(self.main_window, 'camera_controller'):
            return {"error": "Camera controller not available"}
            
        controller = self.main_window.camera_controller
        local_cameras = []
        ndi_sources = []
        
        # 1. Get names from QMediaDevices - MUST be on main thread for stability
        device_names = {}
        
        def _get_names():
            try:
                devices = QMediaDevices.videoInputs()
                for i, dev in enumerate(devices):
                    device_names[i] = dev.description()
            except: pass

        # Check if we are on main thread
        is_main_thread = False
        try:
            if QCoreApplication.instance() and QThread.currentThread() == QCoreApplication.instance().thread():
                is_main_thread = True
        except: pass

        if is_main_thread:
            _get_names()
        else:
            # Safely call on main thread and wait
            QMetaObject.invokeMethod(self, "_get_device_names_internal", 
                                   Qt.ConnectionType.BlockingQueuedConnection,
                                   Q_ARG(object, device_names))

        # 2. Ping indices with OpenCV to verify what actually works
        # This part is slow and now runs in the background if called from background

        # Track which indices are currently used by slots
        used_indices = []
        for i in range(4):
            if controller.is_connected[i] and controller.camera_configs[i].get("mode") == 0:
                try: used_indices.append(int(controller.camera_configs[i].get("source")))
                except: pass

        for i in range(10): # Check first 10 indices
            name = device_names.get(i, f"Camera {i}")
            if i in used_indices:
                local_cameras.append({"id": i, "name": name, "status": "In Use"})
                continue
            
            # Try to open briefly to check status
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) if sys.platform == 'win32' else cv2.VideoCapture(i)
            if cap and cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    mean_val = np.mean(frame)
                    if mean_val < 2:
                        local_cameras.append({"id": i, "name": name, "status": "FAULTY (Shows Black Frame/No Signal) - DO NOT USE"})
                    else:
                        status = "WORKING (Live Feed Detected)"
                        if "ndi" in name.lower() and "webcam" in name.lower():
                            status += " - WARNING: This is a VIRTUAL driver. It may only show a test pattern if the NDI source is not selected in the NDI Webcam tool. Use REAL NDI sources from 'ndi_sources' instead."
                        local_cameras.append({"id": i, "name": name, "status": status})
                else:
                    local_cameras.append({"id": i, "name": name, "status": "Busy/Failed to read"})
                cap.release()
            else:
                # If we have a name from QMediaDevices but couldn't open it, it's likely busy
                if i in device_names:
                    local_cameras.append({"id": i, "name": name, "status": "Inaccessible (Busy/Locked)"})

        # NDI sources
        try:
            # Always try to trigger a discovery if NDI is available
            # This ensures the AI sees sources even if the UI is in Local mode
            if hasattr(controller, 'discover_ndi_sources'):
                controller.discover_ndi_sources()
        except: pass

        if hasattr(controller, '_ndi_finder'):
            sources = controller._ndi_finder.get_sources()
            for s in sources:
                name = str(getattr(s, 'ndi_name', s))
                ndi_sources.append({
                    "id": name,
                    "name": name
                })
        
        return {
            "local_cameras": local_cameras,
            "ndi_sources": ndi_sources,
            "slots": [
                {
                    "slot_index": i, 
                    "ui_label": f"Slot {i+1} (Cam {i+1})",
                    "connected": controller.is_connected[i], 
                    "source": str(controller.camera_configs[i].get("source")) if controller.camera_configs[i].get("source") is not None else None,
                    "mode": "Local" if controller.camera_configs[i].get("mode") == 0 else "NDI",
                    "working_status": "Connected" if controller.is_connected[i] else ("Error: " + controller.last_error_messages[i] if controller.last_error_messages[i] else "Disconnected"),
                    "last_error": controller.last_error_messages[i]
                }
                for i in range(4)
            ],
            "note": "CRITICAL: Use 'slot_index' (0-3) for tool calls. index 0 = Slot 1, etc. \n"
                    "CONNECTION: For NDI sources, you MUST set 'mode=1' in 'connect_camera'. For local/USB, use 'mode=0'.\n"
                    "NDI DISCOVERY: REAL network NDI sources (e.g. 'WORKSTATION-01 (OBS)') appear in the 'ndi_sources' list. "
                    "VIRTUAL NDI drivers (e.g. 'NDI Webcam Video 1') often appear in 'local_cameras' with an integer ID. "
                    "If the user wants an NDI camera, FIRST check 'ndi_sources'. Only use 'local_cameras' if it's a physical USB webcam.\n"
                    "TROUBLESHOOTING: If a camera returns a black frame (is_dark_frame=True), it is not the right source. "
                    "Try a different index or a different NDI source name.\n"
                    "indices often shift. If index 0 is black, IMMEDIATELY try index 1, then 2, etc.\n"
                    "Virtual NDI/OBS cameras often occupy the first indices and show black if not active.\n"
                    "Always prefer indices that have status 'Available' over those with 'Available (Black Frame)'."
        }

    def connect_camera(self, slot_index: Optional[int] = None, source: Any = 0, mode: int = 0, resolution: str = "1280x720", fps: int = 30) -> Dict[str, Any]:
        """
        Connect a camera to a specific slot or the next free slot.
        
        Args:
            slot_index: 0-3. If None, uses next free slot.
            source: Camera ID (int for local) or Name (str for NDI).
            mode: 0 for Local, 1 for NDI.
            resolution: e.g. "1280x720".
            fps: e.g. 30.
        """
        if not self._check_permission("ai_allow_vision"):
            return {"error": "Camera control is disabled by the user."}

        if not hasattr(self.main_window, 'camera_controller'):
            return {"error": "Camera controller not available"}
            
        controller = self.main_window.camera_controller
        
        # Ensure types are correct even if the LLM sent strings
        try:
            if slot_index is not None: slot_index = int(slot_index)
            if mode is not None: mode = int(mode)
            if fps is not None: fps = int(fps)
        except: pass

        # Find next free slot if not provided
        is_auto_selected = False
        if slot_index is None:
            is_auto_selected = True
            for i in range(4):
                # A slot is free if not connected AND no thread is currently running for it
                is_busy = controller.is_connected[i] or (controller.camera_threads[i] and controller.camera_threads[i].isRunning())
                if not is_busy:
                    slot_index = i
                    break
            
            if slot_index is None:
                # If all are busy, try to find one that is just "connected" but maybe not initialized
                for i in range(4):
                    if not controller.is_connected[i]:
                        slot_index = i
                        break
            
            if slot_index is None:
                return {"error": "No free camera slots available (all 4 are occupied)."}
        
        if not (0 <= slot_index < 4):
            return {"error": f"Invalid slot_index {slot_index}. Must be 0-3."}
            
        try:
            # Auto-detect mode if source is a string but mode is 0
            if isinstance(source, str) and mode == 0:
                # If it's not a numeric string, it's almost certainly an NDI source
                if not source.isdigit():
                    mode = 1
                    print(f"[MCP] Auto-detected NDI mode for source: {source}")
            
            # Check if this source was recently tried and failed with a black frame
            last_err = getattr(controller, 'last_error_messages', [""]*4)[slot_index]
            
            # 1. Select the slot in the UI first so everything refreshes
            controller.set_active_config_slot(slot_index)
            
            # 2. Update config for the slot
            controller.camera_configs[slot_index]["source"] = source
            controller.camera_configs[slot_index]["mode"] = mode
            controller.camera_configs[slot_index]["resolution"] = resolution
            controller.camera_configs[slot_index]["fps"] = fps
            
            # 3. Trigger connection
            controller.connect_camera(slot_index)
            
            # 4. Final UI refresh to ensure dropdowns match the new config
            controller.refresh_settings_ui()
            
            msg = f"Cam {slot_index+1} (Slot {slot_index+1}) selected and connection initiated."
            if is_auto_selected:
                msg = f"No slot specified. {msg}"
            
            if last_err:
                msg += f" NOTE: The last attempt on this slot reported: '{last_err}'. I should use 'get_camera_frame' in a few seconds to verify if this new attempt succeeded."
            else:
                msg += " IMPORTANT: I must use 'get_camera_frame' to verify if the stream is working (not a black screen)."

            return {
                "success": True, 
                "slot_index": slot_index, 
                "message": msg,
                "last_known_error": last_err
            }
        except Exception as e:
            return {"error": f"Failed to connect camera: {str(e)}"}

    def disconnect_camera(self, slot_index: int) -> Dict[str, Any]:
        """Disconnect camera from a specific slot (0-3)."""
        if not self._check_permission("ai_allow_vision"):
            return {"error": "Camera control is disabled by the user."}

        if not hasattr(self.main_window, 'camera_controller'):
            return {"error": "Camera controller not available"}
            
        try:
            slot_index = int(slot_index)
        except: pass

        if not (0 <= slot_index < 4):
            return {"error": f"Invalid slot_index {slot_index}. Must be 0-3."}
            
        try:
            self.main_window.camera_controller.disconnect_camera(slot_index)
            return {"success": True, "message": f"Camera {slot_index+1} disconnected."}
        except Exception as e:
            return {"error": f"Failed to disconnect: {str(e)}"}

    def get_camera_frame(self, slot_index: int = 0, max_width: Optional[int] = None) -> Dict[str, Any]:
        """Capture a frame from a specific camera slot (0-3)."""
        if not self._check_permission("ai_allow_vision"):
            return {"error": "Access to vision/camera frames is disabled by the user."}
            
        if not hasattr(self.main_window, 'camera_controller'):
            return {"error": "Camera controller not available"}
            
        try:
            slot_index = int(slot_index)
        except: pass

        controller = self.main_window.camera_controller
        if not (0 <= slot_index < 4):
            return {"error": f"Invalid slot_index {slot_index}. Must be 0-3."}
            
        pixmap = controller.current_frames[slot_index]
        if not pixmap or pixmap.isNull():
            thread = controller.camera_threads[slot_index]
            last_err = getattr(controller, 'last_error_messages', [""]*4)[slot_index]
            
            if thread and thread.isRunning() and not thread.is_connected():
                # Thread is alive but not connected yet
                if last_err:
                    return {"error": f"Cam {slot_index+1} failed to connect. Last error: {last_err}. I should try a different source index or check if the device is in use."}
                else:
                    return {"error": f"Cam {slot_index+1} is still initializing or connecting. This usually takes 3-5 seconds. I MUST wait a few seconds and try 'get_camera_frame' again before reporting an error or retrying 'connect_camera'."}
            
            err_msg = f"No frame available for Cam {slot_index+1}. Is it connected?"
            if last_err:
                err_msg += f" Last system error: {last_err}"
            return {"error": err_msg}
            
        try:
            # Optimization: Resize if too large. Use settings from the UI/Model.
            # Default to 512 for tool calls if not specified, as it's much faster for vision models
            max_w = self.main_window.settings_model.get_int("ai_max_image_width", 512)
            if max_width is not None:
                max_w = max_width
            
            if pixmap.width() > max_w:
                pixmap = pixmap.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
            
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            
            # Use configurable quality from settings. Default to 40 for speed.
            quality = self.main_window.settings_model.get_int("ai_image_quality", 40)
            
            pixmap.save(buffer, "JPEG", quality=quality)
            img_base64 = base64.b64encode(buffer.data().data()).decode()
            
            # Simple check for black/blank frames to help the AI realize it's not working
            is_dark = False
            try:
                img = pixmap.toImage()
                w, h = img.width(), img.height()
                # Check 5 points (center and corners)
                points = [(w//2, h//2), (w//4, h//4), (3*w//4, 3*w//4), (w//4, 3*w//4), (3*w//4, h//4)]
                dark_count = 0
                for px, py in points:
                    c = img.pixelColor(px, py)
                    if c.red() < 10 and c.green() < 10 and c.blue() < 10:
                        dark_count += 1
                if dark_count == len(points):
                    is_dark = True
            except: pass

            return {
                "format": "jpeg",
                "base64": img_base64,
                "width": pixmap.width(),
                "height": pixmap.height(),
                "slot": slot_index,
                "is_dark_frame": is_dark,
                "note": "Image data returned in 'base64' field. " + 
                        ("WARNING: This frame appears to be black/very dark. It might be a disconnected virtual camera." if is_dark else "I should analyze this visually if I am a vision model.")
            }
        except Exception as e:
            return {"error": f"Failed to capture frame: {str(e)}"}

    def get_optical_sensor_preview(self, sensor_name: str, max_width: Optional[int] = None) -> Dict[str, Any]:
        """Capture a frame from a specific optical sensor interface."""
        if not self._check_permission("ai_allow_vision"):
            return {"error": "Access to vision/camera frames is disabled by the user."}
            
        sc = getattr(self.main_window, 'sensor_controller', None)
        if not sc:
            return {"error": "Sensor controller not available."}
            
        if not hasattr(sc, 'optical_sensor_interfaces'):
            return {"error": "No optical sensors configured."}
            
        interface = sc.optical_sensor_interfaces.get(sensor_name)
        if not interface:
            return {"error": f"Optical sensor '{sensor_name}' not found or not connected."}
            
        frame = getattr(interface, 'last_frame', None)
        if frame is None:
            return {"error": f"No frame available for sensor '{sensor_name}'. Is the camera connected and streaming?"}
            
        try:
            # Convert OpenCV BGR frame to QImage/QPixmap for encoding
            import cv2
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_frame.shape
            bytes_per_line = ch * w
            from PyQt6.QtGui import QImage, QPixmap
            qimg = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            
            # Optimization: Resize if too large
            max_w = self.main_window.settings_model.get_int("ai_max_image_width", 512)
            if max_width is not None:
                max_w = max_width
            
            if pixmap.width() > max_w:
                pixmap = pixmap.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
            
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            
            quality = self.main_window.settings_model.get_int("ai_image_quality", 40)
            pixmap.save(buffer, "JPEG", quality=quality)
            img_base64 = base64.b64encode(buffer.data().data()).decode()
            
            return {
                "format": "jpeg",
                "base64": img_base64,
                "width": pixmap.width(),
                "height": pixmap.height(),
                "sensor_name": sensor_name,
                "note": "Image data returned in 'base64' field."
            }
        except Exception as e:
            return {"error": f"Failed to capture optical preview: {str(e)}"}

    def get_audio_sensor_preview(self, sensor_name: str) -> Dict[str, Any]:
        """Get audio spectrum and level summary for a specific audio sensor interface."""
        sc = getattr(self.main_window, 'sensor_controller', None)
        if not sc:
            return {"error": "Sensor controller not available."}
            
        if not hasattr(sc, 'audio_sensor_interfaces'):
            return {"error": "No audio sensors configured."}
            
        interface = sc.audio_sensor_interfaces.get(sensor_name)
        if not interface:
            return {"error": f"Audio sensor '{sensor_name}' not found or not connected."}
            
        with getattr(interface, '_data_lock', threading.Lock()):
            rms, peak = getattr(interface, 'last_levels', (0.0, 0.0))
            spectrum = getattr(interface, 'last_spectrum', None)
            
        result = {
            "sensor_name": sensor_name,
            "rms_level": float(rms),
            "peak_level": float(peak),
            "db_level": float(20 * np.log10(rms + 1e-10))
        }
        
        if spectrum:
            freqs, magnitudes = spectrum
            # Get top 5 dominant frequency peaks
            if len(magnitudes) > 0:
                # Simple peak detection: find indices of largest magnitudes
                top_indices = np.argsort(magnitudes)[-5:][::-1]
                result["dominant_frequencies"] = [
                    {"frequency_hz": float(freqs[i]), "magnitude": float(magnitudes[i])}
                    for i in top_indices if magnitudes[i] > 0
                ]
        
        return result

    def write_mqtt_message(self, topic: str, payload: str) -> Dict[str, Any]:
        """Publish a message to an MQTT topic."""
        if not self._check_permission("ai_allow_config"):
            return {"error": "Configuration changes are disabled by the user."}

        dcc = getattr(self.main_window, 'data_collection_controller', None)
        if not dcc:
            return {"error": "Data collection controller not available."}
            
        if not hasattr(dcc, 'mqtt_thread') or not dcc.mqtt_thread:
            return {"error": "MQTT interface not initialized."}
            
        if not dcc.mqtt_thread.is_connected():
            return {"error": "MQTT interface is not connected to a broker."}
            
        success = dcc.mqtt_thread.publish(topic, payload)
        return {
            "success": success,
            "topic": topic,
            "message": f"Successfully published to {topic}" if success else f"Failed to publish to {topic}"
        }

    def manage_camera_overlay(self, slot_index: int, action: str, overlay_id: Optional[int] = None, 
                             overlay_type: str = "text", name: Optional[str] = None, 
                             position: tuple = (0.05, 0.05), text_color: tuple = (255, 255, 255),
                             bg_color: tuple = (0, 0, 0), bg_alpha: float = 0.5,
                             font_scale: float = 0.7, thickness: int = 2,
                             content: str = "") -> Dict[str, Any]:
        """
        Manage video overlays for a camera slot.
        """
        if not self._check_permission("ai_allow_vision"):
            return {"error": "Camera control is disabled by the user."}

        if not hasattr(self.main_window, 'camera_controller'):
            return {"error": "Camera controller not available"}
            
        try:
            slot_index = int(slot_index)
            if overlay_id is not None: overlay_id = int(overlay_id)
        except: pass

        controller = self.main_window.camera_controller
        if not (0 <= slot_index < 4):
            return {"error": f"Invalid slot_index {slot_index}. Must be 0-3."}
            
        overlays = controller.overlays[slot_index]
        
        from app.core.overlay_manager import BaseOverlay, TextOverlay, TimestampOverlay, SensorOverlay, RectangleOverlay, MotionOverlay
        
        try:
            if action == "add":
                new_id = (max([o.id for o in overlays]) + 1) if overlays else 1
                ov_name = name or f"{overlay_type.capitalize()} {new_id}"
                
                if overlay_type == "text":
                    obj = TextOverlay(new_id, ov_name, content)
                elif overlay_type == "timestamp":
                    obj = TimestampOverlay(new_id, ov_name, content or "%Y-%m-%d %H:%M:%S")
                elif overlay_type == "sensor":
                    obj = SensorOverlay(new_id, ov_name, content)
                elif overlay_type == "rectangle":
                    obj = RectangleOverlay(new_id, ov_name)
                elif overlay_type == "motion":
                    obj = MotionOverlay(new_id, ov_name)
                    # Automatically enable motion detection if adding a motion overlay
                    controller.camera_configs[slot_index]["motion_enabled"] = True
                    if controller.camera_threads[slot_index]:
                        controller.camera_threads[slot_index].set_motion_detection_enabled(True)
                else:
                    return {"error": f"Unknown overlay type: {overlay_type}"}
                
                # Apply styles
                obj.position = position
                obj.text_color = text_color
                obj.bg_color = bg_color
                obj.bg_alpha = bg_alpha
                obj.font_scale = font_scale
                obj.thickness = thickness
                
                overlays.append(obj)
                message = f"Overlay '{ov_name}' added to Cam {slot_index+1}."
                
            elif action == "remove":
                if overlay_id is None: return {"error": "overlay_id required for remove"}
                found = next((o for o in overlays if o.id == overlay_id), None)
                if not found: return {"error": f"Overlay {overlay_id} not found"}
                overlays.remove(found)
                message = f"Overlay {overlay_id} removed."
                
            elif action == "update":
                if overlay_id is None: return {"error": "overlay_id required for update"}
                found = next((o for o in overlays if o.id == overlay_id), None)
                if not found: return {"error": f"Overlay {overlay_id} not found"}
                
                # Update properties
                if name: found.name = name
                found.position = position
                found.text_color = text_color
                found.bg_color = bg_color
                found.bg_alpha = bg_alpha
                found.font_scale = font_scale
                found.thickness = thickness
                
                if overlay_type == "text" and hasattr(found, 'text'): found.text = content
                elif overlay_type == "timestamp" and hasattr(found, 'format'): found.format = content
                elif overlay_type == "sensor" and hasattr(found, 'sensor_name'): found.sensor_name = content
                
                message = f"Overlay {overlay_id} updated."
            else:
                return {"error": f"Unknown action: {action}"}
                
            # Sync with thread
            if controller.camera_threads[slot_index]:
                controller.camera_threads[slot_index].set_overlays(overlays)
            
            # Save persistent settings
            controller.save_overlays_to_run(slot_index)
            
            return {"success": True, "message": message, "overlays": [o.to_dict() for o in overlays]}
            
        except Exception as e:
            return {"error": f"Overlay management failed: {str(e)}"}

    def list_camera_overlays(self, slot_index: int) -> Dict[str, Any]:
        """List all active overlays for a specific camera slot."""
        if not hasattr(self.main_window, 'camera_controller'):
            return {"error": "Camera controller not available"}
        
        controller = self.main_window.camera_controller
        if not (0 <= slot_index < 4):
            return {"error": f"Invalid slot_index {slot_index}. Must be 0-3."}
            
        overlays = controller.overlays[slot_index]
        return {
            "slot_index": slot_index,
            "count": len(overlays),
            "overlays": [o.to_dict() for o in overlays]
        }

    def start_camera_recording(self, slot_index: Optional[int] = None) -> Dict[str, Any]:
        """
        Start recording video from a specific camera slot or all connected cameras.
        """
        if not self._check_permission("ai_allow_vision"):
            return {"error": "Camera control is disabled by the user."}

        if not hasattr(self.main_window, 'camera_controller'):
            return {"error": "Camera controller not available"}
            
        try:
            if slot_index is not None: slot_index = int(slot_index)
        except: pass

        controller = self.main_window.camera_controller

        try:
            if slot_index is None:
                controller.start_recording()
                active = [i for i, r in enumerate(controller.is_recording) if r]
                return {"success": True, "message": f"Recording started for slots: {active}"}
            
            if not (0 <= slot_index < 4):
                return {"error": f"Invalid slot_index {slot_index}. Must be 0-3."}
                
            if not controller.is_connected[slot_index]:
                return {"error": f"Camera at slot {slot_index} is not connected."}
                
            # Trigger recording for specific slot by temporarily disabling others in config if needed?
            # Or just call the thread directly. The controller's start_recording is a bit "all or nothing"
            # based on camera_configs[i]["record_video"].
            
            # Let's use the thread directly for more precision if a slot is specified
            thread = controller.camera_threads[slot_index]
            if not thread:
                return {"error": "Camera thread not initialized."}
                
            if controller.is_recording[slot_index]:
                return {"message": f"Camera {slot_index+1} is already recording."}
            
            # Use controller's logic to get dir and filenames
            output_dir = "recordings"
            if hasattr(self.main_window, 'project_controller'):
                run_dir = self.main_window.project_controller.get_current_run_directory()
                if run_dir: output_dir = run_dir
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = f"recording_cam{slot_index+1}_{timestamp}.mp4"
            
            success = thread.start_recording(
                output_dir=output_dir, 
                filename=fname, 
                codec="H264",
                use_hw_accel=controller.settings.get_bool("use_hw_accel", True),
                record_audio=controller.camera_configs[slot_index].get("record_audio", False),
                audio_device_index=controller.camera_configs[slot_index].get("audio_device", -1)
            )
            
            if success:
                controller.is_recording[slot_index] = True
                controller._append_video_segment_metadata({
                    "path": os.path.join(output_dir, fname), 
                    "start_epoch": time.time(), 
                    "camera_index": slot_index
                })
                return {"success": True, "message": f"Recording started for Cam {slot_index+1}.", "file": fname}
            else:
                return {"error": f"Failed to start recording for Cam {slot_index+1}."}
                
        except Exception as e:
            return {"error": f"Start recording failed: {str(e)}"}

    def stop_camera_recording(self, slot_index: Optional[int] = None) -> Dict[str, Any]:
        """
        Stop active camera recordings.
        """
        if not self._check_permission("ai_allow_vision"):
            return {"error": "Camera control is disabled by the user."}

        if not hasattr(self.main_window, 'camera_controller'):
            return {"error": "Camera controller not available"}
            
        try:
            if slot_index is not None: slot_index = int(slot_index)
        except: pass

        controller = self.main_window.camera_controller
        
        try:
            if slot_index is None:
                controller.stop_recording()
                return {"success": True, "message": "All camera recordings stopped."}
            
            if not (0 <= slot_index < 4):
                return {"error": f"Invalid slot_index {slot_index}. Must be 0-3."}
                
            if not controller.is_recording[slot_index]:
                return {"message": f"Camera {slot_index+1} is not currently recording."}
                
            thread = controller.camera_threads[slot_index]
            if thread:
                thread.stop_recording()
                controller.is_recording[slot_index] = False
                thread._wait_for_finalize(timeout_s=20.0)
                return {"success": True, "message": f"Recording stopped for Cam {slot_index+1}."}
            else:
                return {"error": "Camera thread not found."}
                
        except Exception as e:
            return {"error": f"Stop recording failed: {str(e)}"}

    def set_camera_properties(self, slot_index: int, 
                             manual_focus: Optional[bool] = None, 
                             focus_value: Optional[int] = None,
                             manual_exposure: Optional[bool] = None, 
                             exposure_value: Optional[int] = None) -> Dict[str, Any]:
        """
        Adjust camera hardware properties like focus and exposure.
        
        Args:
            slot_index: 0-3.
            manual_focus: Set to True to enable manual focus, False for auto.
            focus_value: 0-255 (if manual_focus is True).
            manual_exposure: Set to True for manual exposure, False for auto.
            exposure_value: Exposure value (usually negative for webcams, e.g. -5 to -7).
        """
        if not hasattr(self.main_window, 'camera_controller'):
            return {"error": "Camera controller not available"}
            
        controller = self.main_window.camera_controller
        if not (0 <= slot_index < 4):
            return {"error": f"Invalid slot_index {slot_index}. Must be 0-3."}
            
        thread = controller.camera_threads[slot_index]
        if not thread or not controller.is_connected[slot_index]:
            return {"error": f"Camera at slot {slot_index} is not connected or active."}
            
        try:
            # Update config
            if manual_focus is not None: controller.camera_configs[slot_index]["manual_focus"] = manual_focus
            if focus_value is not None: controller.camera_configs[slot_index]["focus_value"] = focus_value
            if manual_exposure is not None: controller.camera_configs[slot_index]["manual_exposure"] = manual_exposure
            if exposure_value is not None: controller.camera_configs[slot_index]["exposure_value"] = exposure_value
            
            # Apply to thread
            thread.set_camera_properties(
                manual_focus=manual_focus,
                focus_value=focus_value,
                manual_exposure=manual_exposure,
                exposure_value=exposure_value
            )
            
            # Save settings
            controller.save_camera_settings(slot_index)
            
            return {"success": True, "message": f"Properties updated for Cam {slot_index+1}."}
        except Exception as e:
            return {"error": f"Failed to set camera properties: {str(e)}"}

    def set_motion_detection_settings(self, slot_index: int, 
                                     enabled: Optional[bool] = None, 
                                     sensitivity: Optional[int] = None, 
                                     min_area: Optional[int] = None) -> Dict[str, Any]:
        """
        Configure motion detection for a specific camera.
        
        Args:
            slot_index: 0-3.
            enabled: Enable or disable motion detection.
            sensitivity: 0-100 (lower is more sensitive for background subtraction).
            min_area: Minimum pixel area for a moving object to trigger detection (e.g. 500).
        """
        if not hasattr(self.main_window, 'camera_controller'):
            return {"error": "Camera controller not available"}
            
        controller = self.main_window.camera_controller
        if not (0 <= slot_index < 4):
            return {"error": f"Invalid slot_index {slot_index}. Must be 0-3."}
            
        thread = controller.camera_threads[slot_index]
        
        # If sensitivity or min_area is provided but enabled is not specified, 
        # assume we want to enable it.
        if enabled is None and (sensitivity is not None or min_area is not None):
            enabled = True
        
        try:
            # Update config
            if enabled is not None: controller.camera_configs[slot_index]["motion_enabled"] = enabled
            if sensitivity is not None: controller.camera_configs[slot_index]["motion_sensitivity"] = sensitivity
            if min_area is not None: controller.camera_configs[slot_index]["motion_min_area"] = min_area
            
            # Apply to thread if it exists
            if thread:
                if enabled is not None:
                    thread.set_motion_detection_enabled(enabled)
                if sensitivity is not None or min_area is not None:
                    s = sensitivity if sensitivity is not None else controller.camera_configs[slot_index].get("motion_sensitivity", 20)
                    m = min_area if min_area is not None else controller.camera_configs[slot_index].get("motion_min_area", 500)
                    thread.update_motion_detection_settings(s, m)
            
            # Save settings
            controller.save_camera_settings(slot_index)
            
            status = "enabled" if enabled is not False else "disabled"
            return {"success": True, "message": f"Motion detection {status} and settings updated for Cam {slot_index+1}."}
        except Exception as e:
            return {"error": f"Failed to update motion settings: {str(e)}"}

    def take_camera_snapshot(self, slot_index: int) -> Dict[str, Any]:
        """
        Take a snapshot from a camera and save it to the project's snapshots folder.
        
        Args:
            slot_index: 0-3.
        """
        if not hasattr(self.main_window, 'camera_controller'):
            return {"error": "Camera controller not available"}
            
        try:
            slot_index = int(slot_index)
        except: pass

        controller = self.main_window.camera_controller
        if not (0 <= slot_index < 4):
            return {"error": f"Invalid slot_index {slot_index}. Must be 0-3."}
            
        try:
            path = controller.take_snapshot(slot_index)
            if path:
                return {"success": True, "message": f"Snapshot saved to {path}", "path": path}
            else:
                return {"error": "Failed to take snapshot. Is the camera connected and providing frames?"}
        except Exception as e:
            return {"error": f"Snapshot failed: {str(e)}"}

    def _get_sensor_by_name_or_id(self, identifier: str):
        """Helper to find a sensor by its display name OR its internal historical key (ID)."""
        sc = getattr(self.main_window, 'sensor_controller', None)
        if not sc:
            return None
            
        # 1. Try by display name (exact)
        sensor = sc.get_sensor_by_name(identifier)
        if sensor:
            return sensor
            
        # 2. Try by historical buffer key (ID)
        sensor = sc.get_sensor_by_historical_key(identifier)
        if sensor:
            return sensor
            
        # 3. Try case-insensitive name match if first two failed
        for s in sc.sensors:
            if hasattr(s, 'name') and s.name.lower() == identifier.lower():
                return s
                
        return None

    def update_sensor_settings(self, sensor_name: str, 
                               enabled: Optional[bool] = None, 
                               color: Optional[str] = None, 
                               stale_timeout_factor: Optional[float] = None, 
                               averaging_enabled: Optional[bool] = None,
                               use_secondary_axis: Optional[bool] = None,
                               show_in_graph: Optional[bool] = None) -> Dict[str, Any]:
        """
        Update sensor management settings like activation, smoothing, stale timeout, and axis assignment.
        """
        sc = getattr(self.main_window, 'sensor_controller', None)
        dcc = getattr(self.main_window, 'data_collection_controller', None)
        
        if not sc:
            return {"error": "Sensor controller not available."}
            
        sensor = self._get_sensor_by_name_or_id(sensor_name)
        if not sensor:
            return {"error": f"Sensor '{sensor_name}' not found. Try 'get_available_sensors' to see valid names/IDs."}
            
        # Update Model properties
        if enabled is not None: 
            sensor.enabled = enabled
        if color is not None: 
            sensor.color = color
        if stale_timeout_factor is not None: 
            sensor.stale_timeout_factor = stale_timeout_factor
        if averaging_enabled is not None: 
            sensor.averaging_enabled = averaging_enabled
        if use_secondary_axis is not None:
            sensor.use_secondary_axis = use_secondary_axis
        if show_in_graph is not None:
            sensor.show_in_graph = show_in_graph
        
        # 1. Refresh the UI Sensor Table
        sc.update_sensor_table()
        
        # 2. Invalidate Data Collection Cache (essential for smoothing/averaging changes)
        if dcc:
            dcc.invalidate_sensor_cache(sensor)
            
        # 3. Update UI styles (e.g., if color or axis changed)
        gc = getattr(self.main_window, 'graph_controller', None)
        if gc:
            if hasattr(gc, 'update_graph'):
                gc.update_graph()
            if hasattr(gc, 'update_dashboard_graph'):
                gc.update_dashboard_graph()
        
        # 4. Persist changes to virtual_sensors.json
        if hasattr(self.main_window, 'save_virtual_sensors'):
            self.main_window.save_virtual_sensors()
            
        return {
            "success": True,
            "sensor": sensor.name,
            "updated": {
                "enabled": sensor.enabled,
                "color": sensor.color,
                "stale_timeout_factor": sensor.stale_timeout_factor,
                "averaging_enabled": sensor.averaging_enabled,
                "use_secondary_axis": getattr(sensor, 'use_secondary_axis', False),
                "show_in_graph": getattr(sensor, 'show_in_graph', True)
            }
        }

    def remove_sensor(self, sensor_name: str) -> Dict[str, Any]:
        """
        Permanently remove a sensor from the system.
        """
        if not self._check_permission("ai_allow_config"):
            return {"error": "Configuration changes are disabled by the user."}

        sc = getattr(self.main_window, 'sensor_controller', None)
        if not sc:
            return {"error": "Sensor controller not available."}
            
        sensor = self._get_sensor_by_name_or_id(sensor_name)
        if not sensor:
            return {"error": f"Sensor '{sensor_name}' not found."}
            
        # Find index and remove from list
        try:
            # We use name comparison to find the correct object in the list
            found_idx = -1
            for i, s in enumerate(sc.sensors):
                if s.name == sensor.name:
                    found_idx = i
                    break
            
            if found_idx == -1:
                return {"error": f"Sensor object for '{sensor_name}' not found in active list."}
                
            removed_sensor = sc.sensors.pop(found_idx)
            
            # SPECIAL CLEANUP for Read CSV:
            if getattr(removed_sensor, 'interface_type', '') == "Read CSV" and hasattr(self.main_window, 'csv_configs'):
                for cfg in self.main_window.csv_configs:
                    if 'mappings' in cfg:
                        cfg['mappings'] = [m for m in cfg['mappings'] if m.get('sensor_name') != removed_sensor.name]
                # Update interfaces (might stop thread if no mappings left)
                self.main_window.update_csv_interfaces(self.main_window.csv_configs)

            # Clean up UI and persistence
            sc.update_sensor_table()
            if hasattr(sc, 'save_sensors'):
                sc.save_sensors() # Saves to sensors.json
            
            # Sync with main_window.other_sensors (virtual_sensors.json)
            if hasattr(self.main_window, 'other_sensors'):
                self.main_window.other_sensors = [
                    vs for vs in self.main_window.other_sensors 
                    if not ((isinstance(vs, dict) and vs.get('name') == removed_sensor.name) or 
                            (hasattr(vs, 'name') and vs.name == removed_sensor.name))
                ]
                if hasattr(self.main_window, 'save_virtual_sensors'):
                    self.main_window.save_virtual_sensors()
            
            return {"success": True, "message": f"Sensor '{sensor_name}' removed."}
        except Exception as e:
            return {"error": f"Failed to remove sensor: {str(e)}"}

    def edit_sensor(self, sensor_name: str, 
                    new_name: Optional[str] = None, 
                    port: Optional[str] = None, 
                    unit: Optional[str] = None) -> Dict[str, Any]:
        """
        Edit core sensor properties like name, hardware port, or measurement unit.
        """
        sc = getattr(self.main_window, 'sensor_controller', None)
        if not sc:
            return {"error": "Sensor controller not available."}
            
        sensor = self._get_sensor_by_name_or_id(sensor_name)
        if not sensor:
            return {"error": f"Sensor '{sensor_name}' not found."}

        # Update properties
        if new_name:
            sensor.name = new_name
        if port:
            sensor.port = port
        if unit:
            sensor.unit = unit

        # Save and Refresh
        sc.update_sensor_table()
        if hasattr(self.main_window, 'save_virtual_sensors'):
            self.main_window.save_virtual_sensors()
            
        return {
            "success": True, 
            "message": f"Sensor '{sensor_name}' updated.",
            "new_config": sensor.to_dict()
        }

    def get_sensor_statistics(self, timeframe_seconds: int = 0, sensor_ids: Optional[Any] = None) -> Dict[str, Any]:
        """
        Calculate statistics (min, max, avg) for sensors.
        
        Args:
            timeframe_seconds: Lookback period in seconds. Use 0 for ALL available data.
            sensor_ids: Optional list of sensor IDs or names.
        """
        # If timeframe is 0, we use a huge range to get everything
        if timeframe_seconds == 0:
            timeframe_seconds = 86400 * 365 # 1 year

        # This internally reuses query_sensor_data logic
        data = self.query_sensor_data(timeframe_seconds, sensor_ids)
        stats = {}
        
        for key, info in data.items():
            if isinstance(info, dict) and "error" in info:
                stats[key] = info
                continue
            
            if not isinstance(info, dict) or "data" not in info:
                continue
                
            vals = [pt["v"] for pt in info["data"]]
            if not vals:
                stats[key] = {"error": "No data found in this timeframe."}
                continue
                
            stats[key] = {
                "unit": info.get("unit", ""),
                "min": round(min(vals), 4),
                "max": round(max(vals), 4),
                "avg": round(sum(vals) / len(vals), 4),
                "latest_value": round(vals[-1], 4),
                "count": len(vals),
                "time_range_seconds": timeframe_seconds
            }
        return stats

    def save_automation_sequence(self, name: str, steps: List[Dict[str, Any]], loop: bool = False, checked: bool = False, run_linked: bool = False) -> Dict[str, Any]:
        """
        Create and save a new automation sequence.
        
        Args:
            name: Unique name for the automation.
            steps: List of step dictionaries (trigger/action pairs).
            loop: Whether the sequence should loop indefinitely.
            checked: Whether the sequence is enabled (checked in UI).
            run_linked: Whether the sequence should stop when the run stops.
        """
        if not self._check_permission("ai_allow_automation"):
            return {"error": "Automation control is disabled in settings."}

        if not hasattr(self.main_window, 'automation_controller'):
            return {"error": "Automation controller not available."}

        try:
            from app.models.automation import AutomationSequence
            manager = self.main_window.automation_controller.manager
            
            # 1. Check for duplicate name
            existing = next((s for s in manager.sequences if s.name == name), None)
            if existing:
                # If it already exists, we overwrite it (or we could return error)
                # Overwriting is better for an AI-driven "fix this sequence" workflow
                manager.remove_sequence(existing)
                note = f"Overwrote existing sequence '{name}'."
            else:
                note = f"Created new sequence '{name}'."

            # 2. Prepare the dictionary for deserialization
            sequence_data = {
                "name": name,
                "loop": loop,
                "steps": steps,
                "checked": checked,
                "run_linked": run_linked
            }
            
            # 3. Create the sequence object
            # Note: This is running in the worker thread.
            new_sequence = AutomationSequence.from_dict(sequence_data)
            
            # 4. Ensure it belongs to the GUI thread
            # This helps avoid threading issues when the manager uses it
            new_sequence.moveToThread(self.main_window.thread())
            for step in new_sequence.steps:
                step.moveToThread(self.main_window.thread())
                if hasattr(step, 'trigger'): step.trigger.moveToThread(self.main_window.thread())
                if hasattr(step, 'action'): step.action.moveToThread(self.main_window.thread())

            # 5. Add to manager (this automatically saves to the JSON file)
            manager.add_sequence(new_sequence)

            # Echo a compact view of what was actually stored so the AI can verify
            saved_steps = []
            for i, step in enumerate(new_sequence.steps):
                trig = getattr(step, "trigger", None)
                act = getattr(step, "action", None)
                saved_steps.append({
                    "step": i + 1,
                    "trigger": getattr(trig, "description", None) or getattr(trig, "name", "Unknown"),
                    "trigger_type": type(trig).__name__ if trig is not None else None,
                    "action": getattr(act, "description", None) or getattr(act, "name", "Unknown"),
                    "action_type": type(act).__name__ if act is not None else None,
                    "enabled": getattr(step, "enabled", True),
                })

            return {
                "success": True,
                "message": f"Automation '{name}' saved successfully. {note}",
                "sequence_name": name,
                "step_count": len(new_sequence.steps),
                "checked": checked,
                "loop": loop,
                "run_linked": run_linked,
                "steps": saved_steps,
                "tip": "Verify live status with get_automation_info. Call control_automation(action='start') to arm triggers."
            }
        except KeyError as e:
            return {"error": f"Missing required field in automation JSON: {str(e)}. Please check documentation for schema."}
        except Exception as e:
            import traceback
            print(f"MCP Error save_automation_sequence: {e}")
            traceback.print_exc()
            return {"error": f"Failed to create automation: {str(e)}"}

    def remove_automation_sequence(self, name: str) -> Dict[str, Any]:
        """
        Permanently delete an automation sequence.
        
        Args:
            name: The name of the sequence to remove.
        """
        if not self._check_permission("ai_allow_automation"):
            return {"error": "Automation control is disabled in settings."}

        if not hasattr(self.main_window, 'automation_controller'):
            return {"error": "Automation controller not available."}

        try:
            manager = self.main_window.automation_controller.manager
            existing = next((s for s in manager.sequences if s.name == name), None)
            
            if not existing:
                return {"error": f"Sequence '{name}' not found."}

            # Stop if running
            if existing in manager.active_sequences:
                manager.stop_sequence(existing)

            # Remove and save
            manager.remove_sequence(existing)
            return {
                "success": True, 
                "message": f"Automation sequence '{name}' has been deleted.",
                "name": name
            }
        except Exception as e:
            return {"error": f"Failed to remove automation: {str(e)}"}

    def control_automation(self, name: str, action: str) -> Dict[str, Any]:
        """
        Control the execution state of an automation sequence.
        
        Args:
            name: The name of the sequence.
            action: "start", "stop", "enable" (check), or "disable" (uncheck).
        """
        if not self._check_permission("ai_allow_automation"):
            return {"error": "Automation control is disabled in settings."}

        if not hasattr(self.main_window, 'automation_controller'):
            return {"error": "Automation controller not available."}

        try:
            controller = self.main_window.automation_controller
            manager = controller.manager
            
            # Find the sequence
            sequence = next((s for s in manager.sequences if s.name == name), None)
            if not sequence:
                return {"error": f"Sequence '{name}' not found."}
            
            action = action.lower().strip()
            
            if action == "start":
                if sequence in manager.active_sequences:
                    return {"success": True, "message": f"Sequence '{name}' is ALREADY RUNNING and active.", "status": "RUNNING"}
                
                print(f"[MCP] Issuing START for sequence: {name}")
                manager.start_sequence(sequence)
                is_running = sequence in manager.active_sequences
                
                return {
                    "success": True,
                    "message": (
                        f"Sequence '{name}' started. Triggers are NOW active and being checked."
                        if is_running else
                        f"Sequence '{name}' start requested but is not yet active."
                    ),
                    "status": "RUNNING" if is_running else "pending"
                }
                
            elif action == "stop":
                if sequence not in manager.active_sequences:
                    return {"success": True, "message": f"Sequence '{name}' is already stopped.", "status": "STOPPED"}
                
                print(f"[MCP] Issuing STOP for sequence: {name}")
                manager.stop_sequence(sequence)
                
                return {
                    "success": True, 
                    "message": f"Sequence '{name}' stopped. No further triggers will be checked.",
                    "status": "STOPPED"
                }
                
            elif action == "enable":
                sequence.checked = True
                manager.save_sequences()
                manager.status_changed.emit() # Notify UI
                return {"success": True, "message": f"Sequence '{name}' is now enabled (checked)."}
                
            elif action == "disable":
                sequence.checked = False
                if sequence in manager.active_sequences:
                    QMetaObject.invokeMethod(manager, "stop_sequence", 
                                           Qt.ConnectionType.QueuedConnection,
                                           Q_ARG(object, sequence))
                manager.save_sequences()
                manager.status_changed.emit()
                return {"success": True, "message": f"Sequence '{name}' is now disabled (unchecked)."}
            else:
                return {"error": f"Unknown action: {action}. Use 'start', 'stop', 'enable', or 'disable'."}
                
        except Exception as e:
            return {"error": f"Failed to control automation: {str(e)}"}

    def list_available_interfaces(self) -> List[Dict[str, Any]]:
        """List all available hardware interfaces and their current status."""
        from app.core.interfaces.interface_registry import InterfaceRegistry
        
        interfaces = []
        registered = InterfaceRegistry.get_interfaces()
        
        dcc = getattr(self.main_window, 'data_collection_controller', None)
        sc = getattr(self.main_window, 'sensor_controller', None)
        
        # Get physical ports to help the AI understand where devices CAN be connected
        physical_ports = []
        try:
            from app.core.interfaces.other_serial_interface import OtherSerialInterface
            physical_ports = OtherSerialInterface.list_ports()
        except: pass

        # Internal mapping for known built-in keys
        known_keys = ["arduino", "labjack", "mqtt", "other_serial", "serial", "audio", "optical", "power_meter", "csv"]
        
        for name, cls in registered.items():
            status = "Disconnected"
            instance = None
            error = ""
            
            # 1. Check DCC interfaces dict (Case-Insensitive)
            if dcc and hasattr(dcc, 'interfaces'):
                # Try multiple variations of the name
                search_names = {name, name.lower(), name.replace(" ", "_").lower(), name.replace(" ", "")}
                
                # Add specific mappings for built-ins if not covered
                if "Arduino" in name: search_names.add("arduino")
                if "LabJack" in name: search_names.add("labjack")
                if "MQTT" in name: search_names.add("mqtt")
                if "CSV" in name or "csv" in name.lower(): search_names.add("csv")
                
                for s_name in search_names:
                    if s_name in dcc.interfaces:
                        if dcc.interfaces[s_name].get('connected'):
                            status = "Connected"
                        # Prioritize instance if found
                        if not instance:
                            instance = dcc.interfaces[s_name].get('instance') or dcc.interfaces[s_name].get('interface')
                        if status == "Connected":
                            break

            # 2. Check individual controller properties/threads if status still disconnected
            if status == "Disconnected" and dcc:
                name_lower = name.lower()
                if "arduino" in name_lower and (getattr(dcc, 'arduino_connected', False) or (hasattr(dcc, 'arduino_thread') and dcc.arduino_thread.is_connected())):
                    status = "Connected"
                elif "labjack" in name_lower and (getattr(dcc, 'labjack_connected', False) or (hasattr(dcc, 'labjack_thread') and dcc.labjack_thread.is_connected())):
                    status = "Connected"
                elif "mqtt" in name_lower and (getattr(dcc, 'mqtt_connected', False) or (hasattr(dcc, 'mqtt_thread') and dcc.mqtt_thread.is_connected())):
                    status = "Connected"
                elif "csv" in name_lower and hasattr(dcc, 'csv_thread'):
                    if dcc.csv_thread.isRunning() and (len(dcc.csv_thread.interfaces) > 0 or getattr(dcc.csv_thread, 'running', False)):
                        status = "Connected"
                elif ("serial" in name_lower or "other" in name_lower) and (getattr(dcc, 'other_serial_connected', False) or (hasattr(dcc, 'other_serial_thread') and dcc.other_serial_thread.is_connected())):
                    status = "Connected"

            # 3. Check Sensor Controller for active sensors of this type
            # (If a sensor is currently receiving data, the interface must be connected)
            if status == "Disconnected" and sc and hasattr(sc, 'sensors'):
                for sensor in sc.sensors:
                    sit = getattr(sensor, 'interface_type', '').lower()
                    if sit == name.lower() or sit == name.replace(" ", "").lower():
                        if sensor.current_value is not None:
                            status = "Connected"
                            break

            # 4. Check instance directly if we found one
            if instance:
                if status == "Disconnected" and hasattr(instance, 'is_connected') and instance.is_connected():
                    status = "Connected"
                if not error:
                    error = getattr(instance, "error_message", "")
            
            interfaces.append({
                "name": name,
                "display_name": getattr(cls, "DISPLAY_NAME", name),
                "description": getattr(cls, "DESCRIPTION", ""),
                "status": status,
                "error": error,
                "available_ports": physical_ports if "serial" in name.lower() or "arduino" in name.lower() else []
            })
            
        return interfaces

    def get_interface_schema(self, interface_name: str) -> Dict[str, Any]:
        """Get the configuration schema for a specific interface."""
        from app.core.interfaces.interface_registry import InterfaceRegistry
        cls = InterfaceRegistry.get_interface_class(interface_name)
        if not cls:
            # Try case-insensitive match
            registered = InterfaceRegistry.get_interfaces()
            for name, r_cls in registered.items():
                if name.lower() == interface_name.lower():
                    cls = r_cls
                    interface_name = name
                    break
        
        if not cls:
            return {"error": f"Interface '{interface_name}' not found."}
            
        return {
            "name": interface_name,
            "display_name": getattr(cls, "DISPLAY_NAME", interface_name),
            "description": getattr(cls, "DESCRIPTION", ""),
            "config_schema": getattr(cls, "CONFIG_SCHEMA", {}),
            "predefined_sensors": cls.get_output_keys() if hasattr(cls, 'get_output_keys') else [],
            "help_text": getattr(cls, "HELP_TEXT", "")
        }

    def get_live_interface_data(self, interface_name: str) -> Dict[str, Any]:
        """
        Get the most recent raw data keys and values received from a connected interface.
        Use this to discover which sensors are available on dynamic interfaces like Arduino or MQTT.
        """
        dcc = getattr(self.main_window, 'data_collection_controller', None)
        sc = getattr(self.main_window, 'sensor_controller', None)
        if not dcc:
            return {"error": "Data collection controller not available."}
            
        # Mapping of canonical names to possible internal prefixes
        name_to_prefixes = {
            "Arduino": ["arduino_", "Arduino_"],
            "LabJack": ["labjack_", "LabJack_"],
            "MQTT": ["mqtt_", "MQTT_"],
            "Other Serial": ["other_serial_", "Other Serial_"],
            "Serial": ["other_serial_", "Serial_"],
            "Read CSV": ["csv_", "CSV_"],
            "Audio": ["audio_", "Audio_"],
            "Optical": ["optical_", "Optical_"]
        }
        
        from app.core.interfaces.interface_registry import InterfaceRegistry
        registered = InterfaceRegistry.get_interfaces()
        
        canonical_name = interface_name
        for name in registered.keys():
            if name.lower() == interface_name.lower():
                canonical_name = name
                break
        
        prefixes = name_to_prefixes.get(canonical_name, [f"{canonical_name}_", f"{canonical_name.lower()}_"])
        st_lower = canonical_name.lower()
        
        # Get list of configured sensors for this interface to distinguish them
        configured_sensor_names = []
        configured_sensor_ports = [] # Some use port as mapping key
        if sc:
            for s in sc.sensors:
                if s.interface_type.lower() == st_lower:
                    configured_sensor_names.append(s.name)
                    if hasattr(s, 'port') and s.port:
                        configured_sensor_ports.append(s.port)

        configured_data = {}
        discovered_but_unconfigured = {}
        live_data = {} # Keep for backward compatibility check
        
        # --- 1. Try to get data from DCC's combined_data (Source of truth for all processed data) ---
        dcc.combined_data_mutex.lock()
        try:
            for key, value in dcc.combined_data.items():
                if key == 'timestamp' or key.endswith('_timestamp'):
                    continue
                    
                matched_prefix = None
                for p in prefixes:
                    if key.startswith(p):
                        matched_prefix = p
                        break
                
                if matched_prefix:
                    sensor_key = key[len(matched_prefix):]
                    live_data[sensor_key] = value # Fill live_data for compatibility
                    # If it's a configured sensor name, it's processed
                    if sensor_key in configured_sensor_names or sensor_key in configured_sensor_ports:
                        configured_data[sensor_key] = value
                    else:
                        discovered_but_unconfigured[sensor_key] = value
        finally:
            dcc.combined_data_mutex.unlock()
            
        # --- 2. Try to get data from Interface Threads directly (Discovered sensors even if not configured) ---
        discovered_keys = []
        thread_data = {}
        
        # Check specialized threads in DCC
        if "arduino" in st_lower and hasattr(dcc, 'arduino_thread'):
            discovered_keys = dcc.arduino_thread.get_available_sensor_names()
            thread_data = dcc.arduino_thread.get_latest_data()
        elif "labjack" in st_lower and hasattr(dcc, 'labjack_thread'):
            if hasattr(dcc.labjack_thread, '_labjack_interface') and dcc.labjack_thread._labjack_interface:
                discovered_keys = dcc.labjack_thread._labjack_interface.get_instance_output_keys()
            thread_data = getattr(dcc.labjack_thread, 'latest_data', {})
        elif "mqtt" in st_lower and hasattr(dcc, 'mqtt_thread'):
            if hasattr(dcc.mqtt_thread, 'mqtt') and dcc.mqtt_thread.mqtt:
                discovered_keys = dcc.mqtt_thread.mqtt.get_instance_output_keys()
            thread_data = getattr(dcc.mqtt_thread, 'latest_data', {})
        elif "serial" in st_lower or "other" in st_lower:
            if hasattr(dcc, 'other_serial_thread'):
                thread_data = getattr(dcc.other_serial_thread, 'latest_data', {}) if hasattr(dcc.other_serial_thread, 'latest_data') else {}
                discovered_keys = list(thread_data.keys())
        elif "optical" in st_lower:
            for key, thread in dcc.interface_threads.items():
                if "optical" in key.lower():
                    if hasattr(thread, 'interface') and thread.interface:
                        if hasattr(thread.interface, 'get_instance_output_keys'):
                            discovered_keys.extend(thread.interface.get_instance_output_keys())
                    thread_data.update(getattr(thread, 'latest_data', {}))
        elif "csv" in st_lower and hasattr(dcc, 'csv_thread'):
            # For CSV, we can report headers from all active interfaces as discovered keys
            for iface in dcc.csv_thread.interfaces:
                if hasattr(iface, 'headers') and iface.headers:
                    discovered_keys.extend(iface.headers)
                # Also include currently mapped sensor names as they are effectively "live"
                if hasattr(iface, 'mappings') and iface.mappings:
                    for m in iface.mappings:
                        sensor_name = m.get('sensor_name')
                        if sensor_name:
                            thread_data[sensor_name] = "Mapped (Active)"

        # Merge thread discovery into discovered_but_unconfigured if not already in configured_data
        for key in discovered_keys:
            if key not in configured_data and key not in configured_sensor_ports:
                val = thread_data.get(key, "Discovered (no value yet)")
                discovered_but_unconfigured[key] = val
                live_data[key] = val
        
        # Merge raw thread_data values
        for key, val in thread_data.items():
            if key not in configured_data and key not in configured_sensor_ports and key != 'timestamp':
                discovered_but_unconfigured[key] = val
                live_data[key] = val

        # --- 3. Fallback: check sensors in SensorController ---
        if not configured_data and sc:
            for sensor in sc.sensors:
                if sensor.interface_type.lower() == st_lower and sensor.current_value is not None:
                    configured_data[sensor.name] = sensor.current_value
                    live_data[sensor.name] = sensor.current_value

        if not live_data:
            note = (
                f"I checked combined_data (prefixes {prefixes}) and interface-specific discovery methods. "
                "Ensure the interface is connected and sending data."
            )
            if canonical_name in ("Serial", "Other Serial", "OtherSerial"):
                note += " For Serial: verify the pipeline with get_serial_sequence, and confirm publish targets match sensor mappings."
            return {
                "interface": canonical_name,
                "status": "No live data or discovered sensors found.",
                "note": note
            }

        result = {
            "interface": canonical_name,
            "status": "Connected",
            "configured_sensors": configured_data,
            "available_unconfigured_sensors": discovered_but_unconfigured,
            "note": "Configured sensors are already in the system. Available unconfigured sensors are being received from the hardware but haven't been added as sensors yet.",
            "timestamp": dcc.combined_data.get(f"{st_lower}_timestamp") or dcc.combined_data.get('timestamp')
        }
        if canonical_name in ("Serial", "Other Serial", "OtherSerial"):
            result["tip"] = (
                "Serial live keys are usually 'SequenceName:publish_target'. "
                "Inspect pipelines with get_serial_sequence; sensors need matching mapping."
            )
        return result

    def get_csv_preview(self, file_path: str, row_count: int = 5) -> Dict[str, Any]:
        """
        Read the first few rows of a CSV file to understand its structure.
        """
        if not self._check_permission("ai_allow_sensor_data"):
            return {"error": "Access to sensor data is disabled in settings."}

        if not self._is_path_allowed(file_path):
            return {"error": f"Access denied: file path is outside allowed directories ({file_path})."}

        if not os.path.exists(file_path):
            return {"error": f"File not found: {file_path}"}
            
        try:
            import csv
            with open(file_path, 'r', newline='', encoding='utf-8', errors='ignore') as f:
                # Detect delimiter
                sample = f.read(4096)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample)
                    delimiter = dialect.delimiter
                except:
                    delimiter = ','
                
                reader = csv.reader(f, delimiter=delimiter)
                headers = next(reader, None)
                rows = []
                for _ in range(row_count):
                    try:
                        row = next(reader, None)
                        if row is None: break
                        rows.append(row)
                    except StopIteration:
                        break
                    
            return {
                "file_path": file_path,
                "delimiter": delimiter,
                "headers": headers,
                "preview_rows": rows,
                "row_count": len(rows),
                "total_columns": len(headers) if headers else 0
            }
        except Exception as e:
            return {"error": f"Failed to read CSV: {str(e)}"}

    def toggle_interface_connection(self, interface_name: str, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Connect or disconnect a hardware interface."""
        if not self._check_permission("ai_allow_config"):
            return {"error": "Configuration changes are disabled by the user."}

        dcc = getattr(self.main_window, 'data_collection_controller', None)
        if not dcc:
            return {"error": "Data collection controller not available."}
            
        if not params:
            params = {}
            
        # Standardize name and map to internal DCC keys
        # DCC uses lowercase keys for built-ins
        name_map = {
            "Arduino": "arduino",
            "LabJack": "labjack",
            "MQTT": "mqtt",
            "Other Serial": "other_serial",
            "Serial": "other_serial",
            "OtherSerial": "other_serial",
            "Audio": "audio",
            "Optical": "optical",
            "Power Meter": "power_meter",
            "Read CSV": "csv"
        }
        
        from app.core.interfaces.interface_registry import InterfaceRegistry
        registered = InterfaceRegistry.get_interfaces()
        
        canonical_name = interface_name
        for name in registered.keys():
            if name.lower() == interface_name.lower():
                canonical_name = name
                break
        
        internal_key = name_map.get(canonical_name, canonical_name.lower())
        
        # Check if the interface exists in DCC
        if internal_key not in dcc.interfaces:
            # Special case for Read CSV which uses a separate thread
            if canonical_name == "Read CSV":
                if action == "connect":
                    if hasattr(self.main_window, 'csv_configs'):
                        dcc.csv_thread.set_configs(self.main_window.csv_configs)
                        dcc.csv_thread.start()
                        return {"success": True, "message": "CSV polling thread started."}
                else:
                    dcc.csv_thread.stop()
                    return {"success": True, "message": "CSV polling thread stopped."}

            # Try to connect if it's a plugin or built-in that hasn't been used yet
            if action == "connect":
                # For built-ins, DCC has specialized connect methods
                if canonical_name == "Arduino":
                    success = dcc.connect_arduino(
                        port=params.get('port'),
                        baud_rate=params.get('baud_rate'),
                        poll_interval=params.get('poll_interval')
                    )
                elif canonical_name == "LabJack":
                    success = dcc.connect_labjack()
                elif canonical_name == "MQTT":
                    success = dcc.connect_mqtt()
                elif canonical_name in ("Serial", "Other Serial"):
                    # Use the robust reinitialization logic in SensorController
                    if hasattr(self.main_window, 'sensor_controller'):
                        success = self.main_window.sensor_controller.reinitialize_other_serial_connections(
                            is_explicit_reconnect=True,
                            port=params.get('port'),
                            baud_rate=params.get('baud_rate')
                        )
                    else:
                        success = dcc.connect_other_serial(
                            port=params.get('port'),
                            baud_rate=params.get('baud_rate')
                        )
                else:
                    success = dcc.connect_plugin_interface(canonical_name)
                return {"success": success, "message": f"Connection {'initiated' if success else 'failed'} for {canonical_name}"}
            return {"error": f"Interface '{canonical_name}' not initialized."}
            
        # Interface is already in the dictionary
        instance = dcc.interfaces[internal_key].get('instance') or dcc.interfaces[internal_key].get('interface')
        
        try:
            if action == "connect":
                if canonical_name == "Arduino":
                    success = dcc.connect_arduino(
                        port=params.get('port'),
                        baud_rate=params.get('baud_rate'),
                        poll_interval=params.get('poll_interval')
                    )
                elif canonical_name == "LabJack":
                    success = dcc.connect_labjack()
                elif canonical_name == "MQTT":
                    success = dcc.connect_mqtt()
                elif canonical_name in ("Serial", "Other Serial"):
                    # Use the robust reinitialization logic in SensorController
                    if hasattr(self.main_window, 'sensor_controller'):
                        success = self.main_window.sensor_controller.reinitialize_other_serial_connections(
                            is_explicit_reconnect=True,
                            port=params.get('port'),
                            baud_rate=params.get('baud_rate')
                        )
                    else:
                        port = params.get('port') or getattr(instance, 'port', None)
                        baud = params.get('baud_rate') or getattr(instance, 'baud_rate', 9600)
                        success = dcc.connect_other_serial(port=port, baud_rate=baud)
                elif instance:
                    success = instance.connect()
                else:
                    success = dcc.connect_plugin_interface(canonical_name)
                
                dcc.interfaces[internal_key]['connected'] = success
                if success:
                    dcc.interface_status_signal.emit(internal_key, True)
                return {"success": success, "message": f"Connect to {canonical_name} {'successful' if success else 'failed'}"}
            elif action == "disconnect":
                if canonical_name == "Arduino":
                    dcc.disconnect_arduino()
                elif canonical_name == "LabJack":
                    dcc.disconnect_labjack()
                elif canonical_name == "MQTT":
                    dcc.disconnect_mqtt()
                elif canonical_name in ("Serial", "Other Serial"):
                    dcc.disconnect_other_serial()
                elif instance:
                    instance.disconnect()
                
                dcc.interfaces[internal_key]['connected'] = False
                dcc.interface_status_signal.emit(internal_key, False)
                return {"success": True, "message": f"Disconnected from {canonical_name}"}
            else:
                return {"error": f"Unknown action '{action}'. Use 'connect' or 'disconnect'."}
        except Exception as e:
            import traceback
            print(f"[MCP] Error in toggle_interface_connection: {traceback.format_exc()}")
            return {"error": f"Error toggling connection: {str(e)}"}

    def configure_sensor_calibration(self, sensor_name: str, offset: Optional[float] = None, factor: Optional[float] = None, unit: Optional[str] = None) -> Dict[str, Any]:
        """Update calibration parameters (offset, factor, unit) for a sensor."""
        sc = getattr(self.main_window, 'sensor_controller', None)
        if not sc:
            return {"error": "Sensor controller not available."}
            
        sensor = self._get_sensor_by_name_or_id(sensor_name)
        if not sensor:
            return {"error": f"Sensor '{sensor_name}' not found."}
            
        if offset is not None: sensor.offset = offset
        if factor is not None: sensor.conversion_factor = factor
        if unit is not None: sensor.unit = unit
        
        # Save project/config to persist changes
        if hasattr(self.main_window, 'save_virtual_sensors'):
            self.main_window.save_virtual_sensors()
            
        sc.update_sensor_table()
        
        return {
            "success": True,
            "sensor": sensor.name,
            "new_offset": sensor.offset,
            "new_factor": sensor.conversion_factor,
            "new_unit": sensor.unit
        }

    def add_sensor(self, interface_name: str, sensor_name: str, unit: str = "", params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Add a new sensor to a hardware interface.
        If the sensor name already exists for that interface, it will update the existing configuration.
        """
        if not self._check_permission("ai_allow_config"):
            return {"error": "Configuration changes are disabled by the user."}

        dcc = getattr(self.main_window, 'data_collection_controller', None)
        if not dcc:
            return {"error": "Data collection controller not available."}
            
        if not params:
            params = {}

        # SPECIAL HANDLING for Read CSV:
        if "csv" in interface_name.lower() or interface_name == "Read CSV":
            file_path = params.get("file") or params.get("file_path")
            column = params.get("column") or params.get("port")
            if not file_path:
                return {"error": "CSV sensor requires 'file' or 'file_path' in params."}
            if not column:
                return {"error": "CSV sensor requires 'column' (the name or index of the CSV column) in params."}
            if not self._is_path_allowed(file_path):
                return {"error": f"Access denied: CSV file path is outside allowed directories ({file_path})."}
            
            # Ensure it's in MainWindow.csv_configs
            if not hasattr(self.main_window, 'csv_configs'):
                self.main_window.csv_configs = []
            
            # Find or create config for this file
            file_config = next((c for c in self.main_window.csv_configs if c.get('file') == file_path), None)
            if not file_config:
                file_config = {
                    "file": file_path,
                    "enabled": True,
                    "poll": params.get("poll_interval", 1.0),
                    "mappings": []
                }
                self.main_window.csv_configs.append(file_config)
            
            # Add/Update mapping in the interface configuration
            mapping = next((m for m in file_config["mappings"] if m.get("sensor_name") == sensor_name), None)
            if not mapping:
                mapping = {"sensor_name": sensor_name, "column": column, "extract_rule": params.get("extract_rule", "")}
                file_config["mappings"].append(mapping)
            else:
                mapping.update({"column": column, "extract_rule": params.get("extract_rule", mapping.get("extract_rule", ""))})
            
            # Apply update to interfaces (restarts CSV thread with new mappings)
            self.main_window.update_csv_interfaces(self.main_window.csv_configs)
            
            # Now continue to add the SensorModel so it shows in the UI
            interface_name = "Read CSV" # Standardize
            params["port"] = column # Use column as port for CSV sensors

        # AUTOMATIC LINKING for Serial sensors:
        # If no mapping is provided, try to find a matching sequence/variable
        if interface_name in ("Serial", "OtherSerial"):
            if "mapping" not in params and "measurement" not in params:
                found_mapping = None
                found_port = None
                
                # Search through sequences for a publish target that matches the sensor name
                if hasattr(self.main_window, 'other_sequences'):
                    for seq in self.main_window.other_sequences:
                        # Check both engine 'steps' and legacy 'actions'
                        steps = seq.get("steps") or seq.get("actions") or []
                        for step in steps:
                            if (step.get("type") or "").strip().lower() == "publish":
                                target = step.get("target")
                                if not target: continue
                                
                                # Exact match or flexible match
                                if target == sensor_name or target.lower() == sensor_name.lower() or \
                                   target.lower().replace("_", "") == sensor_name.lower().replace("_", ""):
                                    found_mapping = f"{seq.get('name')}:{target}"
                                    found_port = seq.get("port")
                                    break
                        if found_mapping: break
                
                if found_mapping:
                    params["mapping"] = found_mapping
                    if "port" not in params and found_port:
                        params["port"] = found_port

        config = {
            "name": sensor_name,
            "type": interface_name,
            "unit": unit,
            "enabled": True,
            "auto_connect": True
        }
        config.update(params)
            
        # persist=True ensures it's saved to virtual_sensors.json
        success = dcc.add_sensor_from_config(config, persist=True)

        result = {
            "success": success,
            "message": f"Sensor '{sensor_name}' {'successfully configured' if success else 'failed to configure'} on interface '{interface_name}'.",
            "interface": interface_name,
            "sensor_name": sensor_name,
            "unit": unit,
            "params": {k: v for k, v in params.items() if k not in ("name", "type", "unit", "enabled", "auto_connect")},
        }
        if interface_name in ("Serial", "OtherSerial"):
            mapping = params.get("mapping") or params.get("measurement")
            result["mapping"] = mapping
            result["port"] = params.get("port")
            if not mapping:
                result["warning"] = (
                    "No Serial mapping resolved. Set params.mapping to 'SequenceName:publish_target', "
                    "or make publish.target match the sensor_name, then re-add. "
                    "Inspect sequences with get_serial_sequence."
                )
            else:
                result["tip"] = "Mapping links this sensor to a publish target from configure_serial_sequence."
        return result

    def test_serial_command(self, port: str, command: str, baud_rate: int = 9600, timeout: float = 2.0, line_ending: str = "None") -> Dict[str, Any]:
        """
        Send a manual command to a serial port and return the response.
        Use this to verify communication protocols before creating a sequence.
        
        To observe unsolicited data (passive listening), use an empty string as the command: command="".
        
        line_ending options: "None", "LF (\n)", "CRLF (\r\n)", "CR (\r)".
        If the device doesn't respond, try different line endings and baud rates.
        """
        if not self._check_permission("ai_allow_config"):
            return {"error": "Configuration changes are disabled by the user."}

        dcc = getattr(self.main_window, 'data_collection_controller', None)
        if not dcc:
            return {"error": "Data collection controller not available."}
            
        # Add line ending if requested
        le_upper = str(line_ending).upper()
        if "CRLF" in le_upper:
            command += "\r\n"
        elif "LF" in le_upper:
            command += "\n"
        elif "CR" in le_upper:
            command += "\r"
        elif line_ending != "None" and line_ending:
            # Try to handle raw strings like "\n" or "\r\n"
            if line_ending == "\\n": command += "\n"
            elif line_ending == "\\r\\n": command += "\r\n"
            elif line_ending == "\\r": command += "\r"
            else: command += line_ending # Append as is if unknown format
            
        print(f"DEBUG MCPServer: test_serial_command port={port}, command={repr(command)}, baud={baud_rate}, timeout={timeout}")
            
        # 1. Ensure interface is connected to the right port/baud
        interface_entry = dcc.interfaces.get('other_serial', {})
        is_connected = interface_entry.get('connected', False)
        
        # Fallback to check thread directly for instance/port
        instance = interface_entry.get('instance')
        if not instance and hasattr(dcc, 'other_serial_thread'):
            instance = getattr(dcc.other_serial_thread, 'interface', None)
        
        # Determine current sequences if we need to reconnect
        current_sequences = None
        if hasattr(self.main_window, 'other_sequences'):
            from app.core.interfaces.other_serial_interface import SerialSequence
            current_sequences = [SerialSequence.from_dict(s) for s in self.main_window.other_sequences if s.get('port') == port]

        current_port = getattr(instance, 'port', None) or interface_entry.get('port')
        current_baud = getattr(instance, 'baud_rate', None) or interface_entry.get('baud_rate')
        
        if not is_connected or not instance or current_port != port or current_baud != baud_rate:
            # Try to connect - use explicit reconnect to override manual disconnects
            if hasattr(dcc, 'explicit_reconnect_other_serial'):
                success = dcc.explicit_reconnect_other_serial(port=port, baud_rate=baud_rate, sequences=current_sequences)
            else:
                success = dcc.connect_other_serial(port=port, baud_rate=baud_rate, sequences=current_sequences)
                
            if not success:
                return {"error": f"Failed to connect to serial port {port}."}
        
        # 2. Send command and wait for response
        try:
            # Use the safe, thread-queued manual command method in DCC
            if hasattr(dcc, 'test_other_serial_manual_command'):
                response = dcc.test_other_serial_manual_command(command, timeout=timeout)
            else:
                return {"error": "Manual command testing not supported in this version."}
                
            return {
                "success": True,
                "port": port,
                "command": command,
                "response": response,
                "note": "If response is empty, try increasing timeout or checking line endings (e.g., \\r\\n)."
            }
        except Exception as e:
            return {"error": f"Serial test failed: {str(e)}"}

    def update_interface_config(self, interface_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update the global configuration for a hardware interface (e.g., change baud rate, port).
        Note: This might require a reconnection to take effect.
        """
        # For built-in interfaces, update SettingsModel
        built_ins = {
            "Arduino": {"port": "arduino_port", "baud_rate": "arduino_baud", "poll_interval": "arduino_poll_interval"},
            "LabJack": {"device_type": "labjack_type"},
            "Serial": {"port": "other_port", "baud_rate": "other_baud", "poll_interval": "other_poll_interval"},
            "Other Serial": {"port": "other_port", "baud_rate": "other_baud", "poll_interval": "other_poll_interval"}
        }
        
        updated_keys = []
        if interface_name in built_ins:
            mapping = built_ins[interface_name]
            for param_key, setting_key in mapping.items():
                if param_key in params:
                    self.main_window.settings_model.set_value(setting_key, params[param_key])
                    updated_keys.append(setting_key)
            
            # Apply Arduino changes live
            if interface_name == "Arduino" and updated_keys:
                dcc = getattr(self.main_window, 'data_collection_controller', None)
                if dcc:
                    dcc.connect_arduino(
                        port=params.get('port'), 
                        baud_rate=params.get('baud_rate'), 
                        poll_interval=params.get('poll_interval')
                    )
            
            # Apply Serial/Other Serial changes live
            if interface_name in ("Serial", "Other Serial") and updated_keys:
                dcc = getattr(self.main_window, 'data_collection_controller', None)
                if dcc:
                    # Clear manual disconnect flag to allow live update
                    if hasattr(dcc, 'other_serial_manually_disconnected'):
                        dcc.other_serial_manually_disconnected = False
                    
                    # If already connected, we might need to reconnect to change baud/port
                    # or just update poll_interval
                    dcc.connect_other_serial(
                        port=params.get('port'),
                        baud_rate=params.get('baud_rate'),
                        poll_interval=params.get('poll_interval')
                    )
        
        # For plugins and all interfaces, update any existing sensor configs that use this interface
        # in the other_sensors list (which is where persist=True saves them)
        if hasattr(self.main_window, 'other_sensors'):
            for config in self.main_window.other_sensors:
                if config.get("type") == interface_name:
                    config.update(params)
                    updated_keys.append(f"sensor_config:{config.get('name')}")
        
        # SPECIAL FIX: For Serial sequences, we MUST also update the other_sequences list
        # so the change persists and is applied when reconnecting.
        if interface_name in ("Serial", "Other Serial", "OtherSerial") and hasattr(self.main_window, 'other_sequences'):
            for seq in self.main_window.other_sequences:
                # If poll_interval or baud_rate is provided, update it for all sequences
                if "poll_interval" in params:
                    try:
                        seq["poll_interval"] = float(params["poll_interval"])
                        updated_keys.append(f"sequence_poll:{seq.get('name')}")
                    except (ValueError, TypeError): pass
                if "baud_rate" in params:
                    try:
                        seq["baud"] = int(params["baud_rate"])
                        updated_keys.append(f"sequence_baud:{seq.get('name')}")
                    except (ValueError, TypeError): pass
            
            # Also apply live to the active interface instance if it exists
            dcc = getattr(self.main_window, 'data_collection_controller', None)
            if dcc and hasattr(dcc, 'interfaces') and 'other_serial' in dcc.interfaces:
                instance = dcc.interfaces['other_serial'].get('instance')
                if instance and hasattr(instance, 'update_settings'):
                    instance.update_settings(params)
                    # Sync with thread
                    if hasattr(dcc, 'other_serial_thread') and dcc.other_serial_thread:
                        dcc.other_serial_thread.poll_interval = getattr(instance, 'poll_interval', 1.0)

        # SPECIAL FIX: For Read CSV interfaces
        if ("csv" in interface_name.lower() or interface_name == "Read CSV") and hasattr(self.main_window, 'csv_configs'):
            file_path = params.get("file") or params.get("file_path")
            if file_path:
                for cfg in self.main_window.csv_configs:
                    if cfg.get("file") == file_path:
                        if "poll" in params or "poll_interval" in params:
                            cfg["poll"] = float(params.get("poll") or params.get("poll_interval"))
                        if "delimiter" in params:
                            cfg["delimiter"] = params["delimiter"]
                        if "decimal_separator" in params:
                            cfg["decimal_separator"] = params["decimal_separator"]
                        updated_keys.append(f"csv_config:{file_path}")
                if updated_keys:
                    self.main_window.update_csv_interfaces(self.main_window.csv_configs)
            
        if updated_keys:
            self.main_window.save_virtual_sensors()
        
        if not updated_keys:
            return {"error": f"No configuration found or updated for interface '{interface_name}'."}
            
        return {
            "success": True,
            "message": f"Updated {len(updated_keys)} configuration keys for interface '{interface_name}'.",
            "updated_keys": updated_keys,
            "note": "You may need to toggle the interface connection for changes to take effect."
        }

    def configure_interface(self, sensor_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Configure hardware-specific settings for a sensor's interface (e.g., ROI for optical, gain for audio).
        """
        sc = getattr(self.main_window, 'sensor_controller', None)
        if not sc:
            return {"error": "Sensor controller not available."}
            
        sensor = sc.get_sensor_by_name(sensor_name)
        if not sensor:
            return {"error": f"Sensor '{sensor_name}' not found."}
            
        # 1. Update the Model's specialized config
        itype = getattr(sensor, 'interface_type', '').lower()
        if itype == 'opticalsensor':
            if not hasattr(sensor, 'optical_config'): sensor.optical_config = {}
            sensor.optical_config.update(params)
        elif itype == 'audiosensor':
            if not hasattr(sensor, 'audio_config'): sensor.audio_config = {}
            sensor.audio_config.update(params)
        elif itype in ('serial', 'otherserial'):
            if not hasattr(sensor, 'sequence_config'): sensor.sequence_config = {}
            sensor.sequence_config.update(params)
        elif itype == 'arduino':
            # Arduino settings are often interface-wide (poll_interval)
            dcc = getattr(self.main_window, 'data_collection_controller', None)
            if dcc and 'poll_interval' in params:
                dcc.connect_arduino(poll_interval=params['poll_interval'])
        elif itype == 'mqtt':
            dcc = getattr(self.main_window, 'data_collection_controller', None)
            if dcc and hasattr(dcc, 'mqtt_thread') and dcc.mqtt_thread:
                if 'poll_interval' in params:
                    dcc.mqtt_thread.poll_interval = float(params['poll_interval'])
                if hasattr(dcc.mqtt_thread, 'mqtt') and dcc.mqtt_thread.mqtt:
                    dcc.mqtt_thread.mqtt.update_settings(params)
            
        # 2. Apply to active interface if connected
        interface = None
        if itype == 'opticalsensor' and hasattr(sc, 'optical_sensor_interfaces'):
            interface = sc.optical_sensor_interfaces.get(sensor.name)
        elif itype == 'audiosensor' and hasattr(sc, 'audio_sensor_interfaces'):
            interface = sc.audio_sensor_interfaces.get(sensor.name)
        elif itype in ('serial', 'otherserial'):
            # Serial interfaces are shared by port
            dcc = getattr(self.main_window, 'data_collection_controller', None)
            if dcc and hasattr(dcc, 'interfaces') and 'other_serial' in dcc.interfaces:
                interface = dcc.interfaces['other_serial'].get('instance')
                
        if interface and hasattr(interface, 'update_settings'):
            interface.update_settings(params)
            
        # 3. Persist changes
        if hasattr(self.main_window, 'save_virtual_sensors'):
            self.main_window.save_virtual_sensors()
            
        return {
            "success": True,
            "sensor": sensor.name,
            "interface_type": itype,
            "applied_params": params
        }

    def _normalize_serial_steps(self, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Normalize serial sequence steps for storage and AI feedback.

        - Canonical PascalCase / lowercase types
        - Accept docs shorthand (source/start/end/ms/target-on-parse)
        - Strip irrelevant empty fields the LLM may dump onto every step
        - Auto-add missing publish steps for ParseValue result_vars
        """
        TYPE_MAP = {
            "sendcommand": "SendCommand",
            "send": "SendCommand",
            "wait": "Wait",
            "readresponse": "ReadResponse",
            "read": "ReadResponse",
            "parsevalue": "ParseValue",
            "parse": "ParseValue",
            "publish": "publish",
        }
        ALLOWED_FIELDS = {
            "SendCommand": {"type", "command", "line_ending"},
            "Wait": {"type", "wait_time"},
            "ReadResponse": {"type", "read_type", "timeout", "result_var"},
            "ParseValue": {
                "type", "source_var", "parse_method", "start_marker", "end_marker",
                "result_type", "result_var", "multiplier"
            },
            "publish": {"type", "source_var", "target"},
        }

        def sanitize_var(v):
            if not v or not isinstance(v, str):
                return v
            if ":" in v:
                return v.split(":")[-1]
            return v

        notes = []
        normalized = []

        for i, raw in enumerate(steps or []):
            if not isinstance(raw, dict):
                notes.append(f"Step {i + 1}: ignored (not an object).")
                continue

            step = dict(raw)
            raw_type = str(step.get("type", "")).strip()
            canonical = TYPE_MAP.get(raw_type.lower())
            if not canonical:
                notes.append(f"Step {i + 1}: unknown type '{raw_type}' ignored.")
                continue

            # Accept documentation shorthand / legacy UI field names
            if "wait_time" not in step and "ms" in step:
                step["wait_time"] = step.pop("ms")
            if "source_var" not in step and "source" in step:
                step["source_var"] = step.pop("source")
            if "start_marker" not in step and "start" in step:
                step["start_marker"] = step.pop("start")
            if "end_marker" not in step and "end" in step:
                step["end_marker"] = step.pop("end")
            if canonical == "ParseValue" and "result_var" not in step and step.get("target"):
                step["result_var"] = step.pop("target")
                notes.append(
                    f"Step {i + 1}: moved 'target' -> 'result_var' "
                    f"(target is only for publish steps)."
                )
            if canonical == "ReadResponse" and "result_var" not in step and step.get("target"):
                step["result_var"] = step.pop("target")

            # Defaults / required fields
            if canonical == "SendCommand":
                step.setdefault("command", "")
                step.setdefault("line_ending", "LF")
            elif canonical == "Wait":
                try:
                    step["wait_time"] = int(step.get("wait_time", 300))
                except (TypeError, ValueError):
                    step["wait_time"] = 300
                if step["wait_time"] < 300:
                    notes.append(f"Step {i + 1}: wait_time raised to 300ms (hardware needs time).")
                    step["wait_time"] = 300
            elif canonical == "ReadResponse":
                step.setdefault("read_type", "Read Line")
                step.setdefault("timeout", 1000)
                if not step.get("result_var"):
                    step["result_var"] = "raw_data"
                    notes.append(f"Step {i + 1}: defaulted result_var to 'raw_data'.")
            elif canonical == "ParseValue":
                step.setdefault("parse_method", "Between Markers")
                step.setdefault("result_type", "Number (Float)")
                step.setdefault("start_marker", "")
                step.setdefault("end_marker", "")
                if not step.get("source_var"):
                    step["source_var"] = "raw_data"
                    notes.append(f"Step {i + 1}: defaulted source_var to 'raw_data'.")
                if not step.get("result_var"):
                    # Prefer a stable name derived from the start marker when possible
                    marker = str(step.get("start_marker") or "").strip(" :")
                    auto_name = re.sub(r"[^A-Za-z0-9_]+", "_", marker).strip("_").lower() or f"val_{i + 1}"
                    if not auto_name.endswith("_val"):
                        auto_name = f"{auto_name}_val"
                    step["result_var"] = auto_name
                    notes.append(
                        f"Step {i + 1}: missing result_var — auto-set to '{auto_name}'. "
                        "Always set result_var explicitly for ParseValue."
                    )
            elif canonical == "publish":
                if not step.get("source_var"):
                    step["source_var"] = "value"
                    notes.append(f"Step {i + 1}: defaulted publish source_var to 'value'.")
                if not step.get("target"):
                    step["target"] = step["source_var"]
                    notes.append(
                        f"Step {i + 1}: defaulted publish target to '{step['target']}'. "
                        "Set target to the sensor display name when possible."
                    )

            for key in ("result_var", "source_var", "target"):
                if key in step:
                    step[key] = sanitize_var(step[key])

            # Keep only fields relevant to this step type (drops LLM schema-fill junk)
            clean = {"type": canonical}
            for key in ALLOWED_FIELDS[canonical]:
                if key == "type":
                    continue
                if key in step and step[key] not in (None, ""):
                    clean[key] = step[key]
                elif key in step and key in ("end_marker", "start_marker", "command"):
                    # Allow empty markers/command when intentionally provided
                    if key in raw or key in step:
                        clean[key] = step.get(key, "")
            # Ensure required keys always present after cleanup
            if canonical == "SendCommand":
                clean.setdefault("command", "")
                clean.setdefault("line_ending", "LF")
            elif canonical == "Wait":
                clean.setdefault("wait_time", 300)
            elif canonical == "ReadResponse":
                clean.setdefault("read_type", "Read Line")
                clean.setdefault("timeout", 1000)
                clean.setdefault("result_var", "raw_data")
            elif canonical == "ParseValue":
                clean.setdefault("source_var", "raw_data")
                clean.setdefault("parse_method", "Between Markers")
                clean.setdefault("start_marker", "")
                clean.setdefault("end_marker", "")
                clean.setdefault("result_type", "Number (Float)")
                clean.setdefault("result_var", f"val_{i + 1}")
            elif canonical == "publish":
                clean.setdefault("source_var", "value")
                clean.setdefault("target", clean["source_var"])

            normalized.append(clean)

        # Safety net: auto-publish ParseValue results that have no matching publish
        published_sources = set()
        for s in normalized:
            if s.get("type") == "publish":
                src = s.get("source_var")
                if src:
                    published_sources.add(src)

        auto_added = []
        for s in normalized:
            if s.get("type") != "ParseValue":
                continue
            result_var = s.get("result_var")
            if result_var and result_var not in published_sources:
                pub = {"type": "publish", "source_var": result_var, "target": result_var}
                auto_added.append(pub)
                published_sources.add(result_var)

        if auto_added:
            normalized.extend(auto_added)
            notes.append(
                f"Auto-added {len(auto_added)} publish step(s) for ParseValue result_var(s) "
                "that had no publish. Prefer adding publish yourself with target = sensor display name."
            )

        return {"steps": normalized, "notes": notes, "auto_added_publish_count": len(auto_added)}

    def configure_serial_sequence(self, port: str, sequence_name: str, steps: List[Dict[str, Any]], poll_interval: Optional[float] = None) -> Dict[str, Any]:
        """
        Configure a custom communication sequence for a serial device (OtherSerial).
        """
        if not self._check_permission("ai_allow_config"):
            return {"error": "Configuration changes are disabled by the user."}

        dcc = getattr(self.main_window, 'data_collection_controller', None)
        if not dcc:
            return {"error": "Data collection controller not available."}

        if not steps:
            return {"error": "steps is required and must be a non-empty list. Call get_documentation(topic='sensors_serial') for the exact JSON format."}

        # 1. Update/Add to the global sequences list in MainWindow
        if not hasattr(self.main_window, 'other_sequences'):
            self.main_window.other_sequences = []

        # Find existing or create new
        seq_config = next((s for s in self.main_window.other_sequences if s.get('name') == sequence_name and s.get('port') == port), None)
        if not seq_config:
            seq_config = {"name": sequence_name, "port": port}
            self.main_window.other_sequences.append(seq_config)

        norm = self._normalize_serial_steps(steps)
        normalized_steps = norm["steps"]
        if not normalized_steps:
            return {
                "error": "No valid steps after normalization.",
                "notes": norm["notes"],
                "hint": "Each step needs type in [SendCommand, Wait, ReadResponse, ParseValue, publish]. See get_documentation(topic='sensors_serial')."
            }

        # Validate pipeline shape for clearer AI feedback
        types = [s.get("type") for s in normalized_steps]
        if "ReadResponse" not in types:
            norm["notes"].append("WARNING: No ReadResponse step — sequence will not capture hardware output.")
        if "ParseValue" not in types:
            norm["notes"].append("WARNING: No ParseValue step — raw text may not become numeric sensor values.")
        if "publish" not in types:
            norm["notes"].append("WARNING: No publish step — sensors cannot map to sequence outputs.")

        publish_targets = [s.get("target") for s in normalized_steps if s.get("type") == "publish"]
        sensor_mapping_hint = [
            f"{sequence_name}:{t}" for t in publish_targets if t
        ]

        seq_config["steps"] = normalized_steps
        if poll_interval is not None:
            seq_config["poll_interval"] = poll_interval

        # Clear legacy actions to ensure UI uses the new steps
        if "actions" in seq_config:
            del seq_config["actions"]

        connected = False
        # 2. If interface is active, update it live
        if hasattr(dcc, 'interfaces') and 'other_serial' in dcc.interfaces:
            interface = dcc.interfaces['other_serial'].get('instance')
            if interface and getattr(interface, 'port', None) == port:
                from app.core.interfaces.other_serial_interface import SerialSequence
                new_seqs = []
                for s_data in self.main_window.other_sequences:
                    if s_data.get('port') == port:
                        seq_obj = SerialSequence.from_dict(s_data)
                        if seq_obj:
                            new_seqs.append(seq_obj)

                if new_seqs:
                    interface.sequences = new_seqs
                if poll_interval is not None:
                    interface.poll_interval = poll_interval
                connected = True
        else:
            # Interface not active at all, try to auto-connect if we have a port
            if port and hasattr(dcc, 'connect_other_serial'):
                from app.core.interfaces.other_serial_interface import SerialSequence
                new_seqs = [SerialSequence.from_dict(s) for s in self.main_window.other_sequences if s.get('port') == port]
                success = dcc.connect_other_serial(port=port, sequences=new_seqs, poll_interval=poll_interval or 1.0)
                connected = bool(success)
                if success and hasattr(self.main_window, 'update_device_connection_status_ui'):
                    QMetaObject.invokeMethod(self.main_window, "update_device_connection_status_ui",
                                           Qt.ConnectionType.QueuedConnection,
                                           Q_ARG(object, "other"),
                                           Q_ARG(object, True))

        # 3. Persist
        if hasattr(self.main_window, 'save_virtual_sensors'):
            self.main_window.save_virtual_sensors()

        return {
            "success": True,
            "port": port,
            "sequence": sequence_name,
            "step_count": len(normalized_steps),
            "steps": normalized_steps,
            "auto_added_publish_count": norm["auto_added_publish_count"],
            "notes": norm["notes"],
            "publish_targets": publish_targets,
            "sensor_mapping_hint": sensor_mapping_hint,
            "interface_connected": connected,
            "tip": (
                "Verify with get_serial_sequence. For custom sensor names, set publish.target "
                "to the display name (e.g. 'ser_Humidity') then add_sensor(interface='Serial', "
                "sensor_name=that name). Mapping form is SequenceName:publish_target."
            )
        }

    def get_serial_sequence(self, port: str = "", sequence_name: str = "") -> Dict[str, Any]:
        """
        Inspect saved Serial (OtherSerial) sequences. Not the same as Automations.
        """
        sequences = getattr(self.main_window, 'other_sequences', None) or []
        if not sequences:
            return {
                "sequences": [],
                "note": "No serial sequences configured. Use configure_serial_sequence after test_serial_command."
            }

        matched = []
        for s in sequences:
            if port and s.get("port") != port:
                continue
            if sequence_name and s.get("name") != sequence_name:
                continue
            matched.append({
                "name": s.get("name"),
                "port": s.get("port"),
                "poll_interval": s.get("poll_interval"),
                "step_count": len(s.get("steps") or s.get("actions") or []),
                "steps": s.get("steps") or s.get("actions") or [],
            })

        if (port or sequence_name) and not matched:
            return {
                "error": f"No serial sequence found matching port='{port}' sequence_name='{sequence_name}'.",
                "available": [{"name": s.get("name"), "port": s.get("port")} for s in sequences]
            }

        return {
            "sequences": matched,
            "count": len(matched),
            "note": "These are Serial protocol pipelines, NOT Automations. Use get_automation_info for Automations."
        }

    def list_serial_sequences(self) -> Dict[str, Any]:
        """List all configured Serial sequences (summary only)."""
        return self.get_serial_sequence()

    def remove_serial_sequence(self, port: str, sequence_name: str) -> Dict[str, Any]:
        """
        Permanently remove a custom serial sequence.
        """
        dcc = getattr(self.main_window, 'data_collection_controller', None)
        if not dcc:
            return {"error": "Data collection controller not available."}

        if not hasattr(self.main_window, 'other_sequences'):
            return {"error": "No serial sequences found."}

        # 1. Find and remove from global list
        original_count = len(self.main_window.other_sequences)
        self.main_window.other_sequences = [s for s in self.main_window.other_sequences
                                          if not (s.get('name') == sequence_name and s.get('port') == port)]

        if len(self.main_window.other_sequences) == original_count:
            available = [{"name": s.get("name"), "port": s.get("port")} for s in getattr(self.main_window, 'other_sequences', [])]
            return {
                "error": f"Sequence '{sequence_name}' on port '{port}' not found.",
                "available": available
            }

        # 2. Update live interface if active
        if hasattr(dcc, 'interfaces') and 'other_serial' in dcc.interfaces:
            interface = dcc.interfaces['other_serial'].get('instance')
            if interface and getattr(interface, 'port', None) == port:
                from app.core.interfaces.other_serial_interface import SerialSequence
                new_seqs = [SerialSequence.from_dict(s) for s in self.main_window.other_sequences if s.get('port') == port]
                interface.sequences = new_seqs

        # 3. Persist
        if hasattr(self.main_window, 'save_virtual_sensors'):
            self.main_window.save_virtual_sensors()

        return {
            "success": True,
            "message": f"Sequence '{sequence_name}' removed from port '{port}'.",
            "remaining_sequences": [{"name": s.get("name"), "port": s.get("port")} for s in self.main_window.other_sequences]
        }

    def list_serial_ports(self) -> List[str]:
        """List all physically available COM/Serial ports on the system."""
        from app.core.interfaces.other_serial_interface import OtherSerialInterface
        return OtherSerialInterface.list_ports()

    def check_server_status(self) -> Dict[str, Any]:
        """Check the AI server health and thread state."""
        return {
            "status": "Healthy",
            "server_thread": QThread.currentThread().objectName() or "Main",
            "main_thread": QCoreApplication.instance().thread().objectName() or "Main",
            "is_main_thread": QThread.currentThread() == QCoreApplication.instance().thread(),
            "active_tools": len(self.list_tools())
        }

    def get_ui_state(self) -> Dict[str, Any]:
        """
        Returns the current active tab and any visible modal dialogs.
        """
        if not self.main_window or not hasattr(self.main_window, 'stacked_widget'):
            return {"error": "UI navigation not available"}
            
        try:
            current_index = self.main_window.stacked_widget.currentIndex()
            available_tabs = []
            current_tab_name = "Unknown"
            
            # Map indices to names from the navigation buttons
            if hasattr(self.main_window, 'nav_buttons'):
                for i, btn in enumerate(self.main_window.nav_buttons):
                    name = btn.text()
                    available_tabs.append(name)
                    if i == current_index:
                        current_tab_name = name
            
            # Handle the hidden Data Flow tab if it exists
            if hasattr(self.main_window, 'data_flow_page_index'):
                available_tabs.append("Data Flow")
                if current_index == self.main_window.data_flow_page_index:
                    current_tab_name = "Data Flow"

            # Identify active popups (Dialogs)
            from PyQt6.QtWidgets import QApplication, QDialog
            active_popups = []
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, QDialog) and widget.isVisible():
                    # Exclude the AI Chat itself to avoid redundancy
                    title = widget.windowTitle() or "Unnamed Dialog"
                    if title != "AI Assistant":
                        active_popups.append({
                            "title": title,
                            "modal": widget.isModal()
                        })

            return {
                "current_tab": current_tab_name,
                "current_tab_index": current_index,
                "available_tabs": available_tabs,
                "active_popups": active_popups
            }
        except Exception as e:
            return {"error": f"Failed to get UI state: {str(e)}"}

    def list_tools(self) -> List[Dict[str, Any]]:
        """Simplified metadata for better local model compatibility."""
        return [
            {
                "name": "add_sensor",
                "description": "Add a new sensor to a hardware interface. \n- For 'Arduino': Standard protocol (Master-Slave). \n- For 'Serial': Custom protocol (Requires SerialSequence). Set params.mapping to 'SequenceName:publish_target' OR make publish.target match sensor_name. \nCRITICAL: If using 'Serial' on an Arduino port, the interface type in this tool MUST be 'Serial', not 'Arduino'. They are different drivers.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "interface_name": {"type": "string", "description": "Interface type (e.g., 'Arduino', 'Serial', 'LabJack', 'Read CSV')"},
                        "sensor_name": {"type": "string", "description": "Unique display name for the sensor (e.g. 'ser_Humidity')"},
                        "unit": {"type": "string", "description": "Measurement unit (e.g., 'V', 'C', '%')"},
                        "params": {"type": "object", "description": "Interface-specific settings. For Serial: {mapping: 'SeqName:publish_target', port: 'COM4'}."}
                    },
                    "required": ["interface_name", "sensor_name"]
                }
            },
            {
                "name": "test_serial_command",
                "description": "Send a manual command to a serial port and return the response. WARNING: Use this ONLY for custom 'Serial' (OtherSerial) devices. Do NOT use for standard 'Arduino' interface boards, as it may disrupt communication. Prefer line_ending='CR' or 'LF' when probing Arduinos.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "port": {"type": "string", "description": "Serial port (e.g., 'COM3')"},
                        "command": {"type": "string", "description": "The command string to send (do NOT include line endings here — use line_ending)"},
                        "baud_rate": {"type": "integer", "default": 9600},
                        "timeout": {"type": "number", "default": 2.0, "description": "Time to wait for response (seconds)"},
                        "line_ending": {"type": "string", "description": "None | LF (\\n) | CR (\\r) | CRLF (\\r\\n). Many devices need CR or LF."}
                    },
                    "required": ["port", "command"]
                }
            },
            {
                "name": "configure_interface",
                "description": "Configure hardware-specific settings for an interface. \n- For 'Arduino': use {'poll_interval': 2.0} with any Arduino sensor name. \n- For 'Optical': use {'mode': 'light_events', 'brightness_threshold': 30, 'roi_x': 0, 'roi_y': 0, 'roi_width': 100, 'roi_height': 100}. Other optical params: 'brightness_roi_x/y/width/height', 'target_hue', 'hue_tolerance', 'rpm_roi_x/y/width/height'. \n- For 'Audio': use {'noise_gate': 0.05, 'smoothing': 0.3, 'band_low': 100, 'band_high': 4000}. \n- For 'MQTT': use {'poll_interval': 0.5}. \n- For 'Serial': use {'poll_interval': 2.0}.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sensor_name": {"type": "string", "description": "The name of any sensor on this interface"},
                        "params": {"type": "object", "description": "Settings to apply"}
                    },
                    "required": ["sensor_name", "params"]
                }
            },
            {
                "name": "configure_serial_sequence",
                "description": "Configure a Serial (OtherSerial) protocol pipeline. CRITICAL: Call test_serial_command FIRST. Use ONLY the fields listed for each step type — do NOT fill unused fields. REQUIRED pattern: SendCommand (optional) -> Wait (>=300ms) -> ReadResponse (result_var) -> ParseValue (source_var+result_var) -> publish (source_var+target). For multi-value lines, repeat ParseValue+publish per value. publish.target should match the sensor display name. Returns the normalized steps so you can verify — use get_serial_sequence to re-read later. NOT an Automation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "port": {"type": "string", "description": "Serial port (e.g., 'COM3')"},
                        "sequence_name": {"type": "string", "description": "Name of the sequence"},
                        "steps": {
                            "type": "array",
                            "description": "Ordered pipeline steps. Each object should ONLY include fields for its type.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "enum": ["SendCommand", "Wait", "ReadResponse", "ParseValue", "publish"]},
                                    "command": {"type": "string", "description": "SendCommand only."},
                                    "line_ending": {"type": "string", "description": "SendCommand only: None, LF, CR, CRLF."},
                                    "wait_time": {"type": "integer", "description": "Wait only. Milliseconds (minimum 300)."},
                                    "read_type": {"type": "string", "description": "ReadResponse only: Read Line, Read Until Timeout, Read N Bytes."},
                                    "timeout": {"type": "integer", "description": "ReadResponse only. Max wait ms."},
                                    "result_var": {"type": "string", "description": "REQUIRED for ReadResponse and ParseValue. Where to store the output (e.g. 'raw_data', 'h_val')."},
                                    "source_var": {"type": "string", "description": "REQUIRED for ParseValue and publish. Variable to read from."},
                                    "parse_method": {"type": "string", "description": "ParseValue only: Between Markers (preferred), After Marker, Before Marker, Regex Pattern, Entire Response."},
                                    "start_marker": {"type": "string", "description": "ParseValue: text before the value (e.g. 'Humidity:')."},
                                    "end_marker": {"type": "string", "description": "ParseValue: text after the value (e.g. ';'). Empty string allowed."},
                                    "result_type": {"type": "string", "description": "ParseValue: Number (Float), Number (Integer), or Text."},
                                    "target": {"type": "string", "description": "publish ONLY. Final sensor key / display name (e.g. 'ser_Humidity')."}
                                },
                                "required": ["type"]
                            }
                        },
                        "poll_interval": {"type": "number", "description": "How often to run the sequence (seconds)"}
                    },
                    "required": ["port", "sequence_name", "steps"]
                }
            },
            {
                "name": "get_serial_sequence",
                "description": "Inspect saved Serial protocol sequences (steps, port, poll_interval). Use this to VERIFY configure_serial_sequence. This is NOT get_automation_info — Automations are a different system.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "port": {"type": "string", "description": "Optional filter by COM port"},
                        "sequence_name": {"type": "string", "description": "Optional filter by sequence name"}
                    }
                }
            },
            {
                "name": "list_serial_sequences",
                "description": "List all configured Serial protocol sequences (summary). Alias of get_serial_sequence with no filters.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "update_interface_config",
                "description": "Update global settings for an interface (like port or baud rate) across all its sensors.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "interface_name": {"type": "string"},
                        "params": {"type": "object", "description": "Key-value pairs of settings to update"}
                    },
                    "required": ["interface_name", "params"]
                }
            },
            {
                "name": "get_live_interface_data",
                "description": "Get the most recent raw data keys and values received from a connected interface. Use this to discover available sensors on dynamic devices like Arduino or MQTT.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "interface_name": {"type": "string"}
                    },
                    "required": ["interface_name"]
                }
            },
            {
                "name": "list_available_interfaces",
                "description": "List all available hardware interfaces (Arduino, LabJack, MQTT, etc.) and their connection status.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "get_interface_schema",
                "description": "Get the configuration schema and any predefined sensor keys for an interface type.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "interface_name": {"type": "string"}
                    },
                    "required": ["interface_name"]
                }
            },
            {
                "name": "toggle_interface_connection",
                "description": "Connect or disconnect a hardware interface. \n- For 'Arduino': use {'port': 'COM3', 'baud_rate': 9600, 'poll_interval': 1.0}. \n- For 'Serial': use {'port': 'COM3', 'baud_rate': 9600}. \nCRITICAL: 'Arduino' and 'Serial' are MUTUALLY EXCLUSIVE on the same port. To switch from 'Arduino' to 'Serial', you MUST 'disconnect' Arduino first, then 'connect' Serial.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "interface_name": {"type": "string", "description": "Interface name ('Arduino', 'Serial', 'LabJack', 'MQTT')"},
                        "action": {"type": "string", "enum": ["connect", "disconnect"]},
                        "params": {
                            "type": "object",
                            "description": "Connection settings. For 'Serial', MUST include 'port'."
                        }
                    },
                    "required": ["interface_name", "action"]
                }
            },
            {
                "name": "configure_sensor_calibration",
                "description": "Update a sensor's offset, conversion factor, or unit. Use this for the 'Calibration Wizard' workflow.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sensor_name": {"type": "string"},
                        "offset": {"type": "number"},
                        "factor": {"type": "number"},
                        "unit": {"type": "string"}
                    },
                    "required": ["sensor_name"]
                }
            },
            {
                "name": "update_sensor_settings",
                "description": "Update sensor management settings: enable/disable, color, smoothing (averaging), and stale timeout factor.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sensor_name": {"type": "string", "description": "The exact name of the sensor"},
                        "enabled": {"type": "boolean", "description": "True to activate, False to deactivate"},
                        "color": {"type": "string", "description": "Hex color code (e.g., '#4287f5')"},
                        "stale_timeout_factor": {"type": "number", "description": "Multiplier for stale check (stale xInt)"},
                        "averaging_enabled": {"type": "boolean", "description": "Enable/disable smoothing (moving average)"}
                    },
                    "required": ["sensor_name"]
                }
            },
            {
                "name": "remove_sensor",
                "description": "Permanently remove a sensor from the system.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sensor_name": {"type": "string", "description": "The exact name of the sensor to remove"}
                    },
                    "required": ["sensor_name"]
                }
            },
            {
                "name": "edit_sensor",
                "description": "Edit core sensor properties like name, hardware port, or measurement unit.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sensor_name": {"type": "string", "description": "The current name of the sensor"},
                        "new_name": {"type": "string", "description": "New name for the sensor"},
                        "port": {"type": "string", "description": "New hardware port/channel"},
                        "unit": {"type": "string", "description": "New measurement unit"}
                    },
                    "required": ["sensor_name"]
                }
            },
            {
                "name": "get_projects_list",
                "description": "List all projects, test series, and runs available in the system.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "set_active_project",
                "description": "Load a specific run from a project for analysis or replay.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_name": {"type": "string"},
                        "series_name": {"type": "string"},
                        "run_name": {"type": "string"}
                    },
                    "required": ["project_name", "series_name", "run_name"]
                }
            },
            {
                "name": "configure_next_run",
                "description": "Configure the fields for the upcoming run in the UI (testers, description, and global sampling rate). Use this for PREPARING a run. These changes are visible in the Projects tab immediately.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "testers": {"type": "string", "description": "Names of testers (comma-separated)"},
                        "description": {"type": "string", "description": "Description of the next run"},
                        "sampling_rate": {"type": "number", "description": "Global sampling rate in Hz (e.g. 1.0)"}
                    }
                }
            },
            {
                "name": "export_run",
                "description": "Trigger the export process for project data.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "import_run",
                "description": "Trigger the import process to add an external project archive.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "list_serial_ports",
                "description": "List all physically available COM/Serial ports on the system. Use this to find the correct port for a new device.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "check_server_status",
                "description": "Check the AI server health and thread state.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "get_current_time",
                "description": "Get current time. Result 'logical_now' is the end of available data. Use this to orient yourself in the timeline.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "get_project_config",
                "description": "CRITICAL: MANDATORY at the start of every session. Returns the full project configuration. WARNING: For any task involving sensors or automations, you MUST call 'get_documentation' (topic='sensors' or 'automation') to understand the specific logic and lifecycle requirements.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "get_documentation",
                "description": "REQUIRED for ANY 'How', 'What', or 'Why' questions. Access the Source of Truth docs. Topics: 'overview', 'sensors', 'automation', 'vision', 'ai_graphs', and specific sensor topics like 'sensors_serial', 'sensors_arduino', etc. NOTE: All documentation files contain the mandatory 'AI Interaction Protocol' which forbids you from asking users to run tools.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "enum": ["overview", "projects", "sensors", "sensors_arduino", "sensors_serial", "sensors_labjack", "sensors_mqtt", "sensors_csv", "sensors_advanced", "sensors_optical", "sensors_audio", "sensors_remote_daq", "automation", "vision", "camera", "dashboard_video", "ai_graphs", "tools_overview", "tools_fft", "tools_calibration", "tools_statistics", "tools_diagnostics", "tools_calculator", "tools_optical_rpm", "remote_grpc", "plugins"], "default": "overview"}
                    }
                }
            },
            {
                "name": "get_data_summary",
                "description": "Get summary of all available data, time ranges, and sampling rates. Use this to see if data is actually being recorded.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "set_graph_config",
                "description": "Configure the main graph view options including type, sensors, and styling. CRITICAL: Only include the parameters that the user explicitly asked to change or that are strictly necessary for the new view. Do NOT change styling (like style_preset) unless requested.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "graph_type": {"type": "string", "enum": ["Standard Time Series", "Temperature Difference", "Rate of Change (dT/dt)", "Moving Average", "Fourier Analysis", "Histogram", "Box Plot", "Correlation Analysis"]},
                        "primary_sensor": {"type": "string", "description": "Sensor ID to plot (e.g., 'T_Ambient')"},
                        "secondary_sensor": {"type": "string", "description": "Sensor ID for secondary axis"},
                        "timespan": {"type": "string", "enum": ["10s", "30s", "1min", "5min", "15min", "30min", "1h", "3h", "6h", "12h", "24h", "All"]},
                        "style_preset": {"type": "string", "enum": ["Standard", "Solarized", "Dark", "High Contrast", "Pastel", "Colorful"]},
                        "show_control_run": {"type": "boolean", "description": "Show or hide control run data"},
                        "control_run_offset": {"type": "number", "description": "Time offset in seconds for the control run data (+ shifts right, - shifts left)"},
                        "line_width": {"type": "integer", "minimum": 1, "maximum": 10}
                    }
                }
            },
            {
                "name": "get_available_sensors",
                "description": "List all configured sensors, their IDs, units, and latest values. Use this to identify which sensor the user is talking about.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "get_sensor_statistics",
                "description": "Get min/max/avg for sensors. Use timeframe_seconds=0 for THE WHOLE RUN.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "timeframe_seconds": {"type": "integer", "default": 0, "description": "Seconds back from logical now. Use 0 for ALL DATA."},
                        "sensor_ids": {"type": "array", "items": {"type": "string"}, "description": "List of sensor IDs."}
                    }
                }
            },
            {
                "name": "query_sensor_data",
                "description": "Get raw time/value points. Only use if explicit precision is needed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "timeframe_seconds": {"type": "integer", "default": 60},
                        "sensor_ids": {"type": "array", "items": {"type": "string"}}
                    }
                }
            },
            {
                "name": "get_notes",
                "description": "Read user-written notes as plain text.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "get_notes_html",
                "description": "Read the notes document with full HTML structure, including styling and images. Use this to understand the layout and find where to insert content.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "edit_notes",
                "description": "Insert text or HTML into the notes document. You can append to the end or find specific text to insert after.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "html_content": {"type": "string", "description": "The HTML or text content to insert."},
                        "search_anchor": {"type": "string", "description": "Optional text to search for. If provided and found, content is inserted after that paragraph."}
                    },
                    "required": ["html_content"]
                }
            },
            {
                "name": "insert_note_media",
                "description": "Insert a live graph or camera snapshot directly into the notes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "media_type": {"type": "string", "enum": ["graph", "camera"], "description": "Type of media to insert."},
                        "search_anchor": {"type": "string", "description": "Optional text to search for. If provided and found, media is inserted after that paragraph."}
                    },
                    "required": ["media_type"]
                }
            },
            {
                "name": "get_automation_info",
                "description": "Get LIVE status of all automation sequences, active steps, and shared variables. Use this to see which sequence is currently running. Does NOT list Serial protocol sequences — use get_serial_sequence for those.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "get_graph_screenshot",
                "description": "Capture a graph image (base64). Essential for visual analysis of trends.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "graph_type": {"type": "string", "enum": ["dashboard", "graphs_tab"], "default": "dashboard"},
                        "max_width": {"type": "integer"}
                    }
                }
            },
            {
                "name": "save_automation_sequence",
                "description": "Create or UPDATE an automation sequence. If the 'name' matches an existing one, it will be OVERWRITTEN with the new steps. WARNING: You MUST call 'get_documentation(topic=\"automation\")' first for the required JSON structure. Setting 'checked': true only enables the sequence for future runs; it does NOT start background monitoring. You must usually call control_automation(action='start') after saving if the user wants it active NOW.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Unique name for the automation"},
                        "steps": {
                            "type": "array", 
                            "items": {
                                "type": "object",
                                "properties": {
                                    "trigger": {
                                        "type": "object",
                                        "description": "Trigger definition. REQUIRED fields: 'type' (TIME_DURATION, TIME_SPECIFIC, SENSOR_VALUE, EVENT, OPTICAL_EVENT, AUDIO_EVENT), 'name'. \n- TIME_DURATION: needs 'minutes', 'seconds'. \n- TIME_SPECIFIC: needs 'hour' (0-23), 'minute' (0-59). Use this for 'Start at 17:00'. \n- SENSOR_VALUE: needs 'sensor_name', 'operator' (>, <, ==), 'threshold'. \n- EVENT: needs 'event_type'.",
                                        "required": ["type", "name"]
                                    },
                                    "action": {
                                        "type": "object",
                                        "description": "Action definition. REQUIRED fields: 'type' (SYSTEM_ACTION, ARDUINO_COMMAND, LABJACK_COMMAND, SET_VARIABLE, JUMP_TO_STEP, CONDITION), 'name'. \n- SYSTEM_ACTION: needs 'specific_action_type' (e.g., take_snapshot, start_recording, start_acquisition) and 'parameters' (object).",
                                        "required": ["type", "name"]
                                    },
                                    "enabled": {"type": "boolean", "default": True}
                                },
                                "required": ["trigger", "action"]
                            }, 
                            "description": "List of triggers and actions"
                        },
                        "loop": {"type": "boolean", "default": False},
                        "checked": {"type": "boolean", "default": False, "description": "Whether the sequence is enabled (checked) in the UI."},
                        "run_linked": {"type": "boolean", "default": False, "description": "Whether the sequence should stop automatically when the run stops."}
                    },
                    "required": ["name", "steps"]
                }
            },
            {
                "name": "control_automation",
                "description": "Start (ARM), stop, enable, or disable an automation sequence. CRITICAL: 'start' is synonymous with 'ARMING' the triggers. Without calling 'start', a sequence is DEAD and will NOT fire (even at 17:00). If a user says 'run/enable it', you MUST call 'start' to begin background monitoring.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name of the sequence"},
                        "action": {"type": "string", "enum": ["start", "stop", "enable", "disable"]}
                    },
                    "required": ["name", "action"]
                }
            },
            {
                "name": "remove_serial_sequence",
                "description": "Permanently remove a custom serial sequence. Use this to clean up incorrect or redundant sequences.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "port": {"type": "string", "description": "Serial port (e.g., 'COM3')"},
                        "sequence_name": {"type": "string", "description": "Name of the sequence to remove"}
                    },
                    "required": ["port", "sequence_name"]
                }
            },
            {
                "name": "remove_automation_sequence",
                "description": "Permanently delete an automation sequence. Use this to clean up the workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "The name of the sequence to remove"}
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "list_camera_sources",
                "description": "List all available local cameras and NDI sources. Returns source IDs and names, and shows which slots (0-3) are currently occupied.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "connect_camera",
                "description": "Connect a camera source to a specific slot. \n"
                               "- slot_index 0 = 'cam1' (Slot 1)\n"
                               "- slot_index 1 = 'cam2' (Slot 2)\n"
                               "- slot_index 2 = 'cam3' (Slot 3)\n"
                               "- slot_index 3 = 'cam4' (Slot 4)\n"
                               "If slot_index is omitted, it will automatically use the first available free slot.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "slot_index": {"type": "integer", "description": "0-3. MANDATORY if the user specified a slot. Mapping: cam1=0, cam2=1, cam3=2, cam4=3. NEVER use 1-based indexing."},
                        "source": {"type": "string", "description": "ID for local camera (e.g. '0') or name for NDI (e.g. 'My NDI Source')"},
                        "mode": {"type": "integer", "enum": [0, 1], "description": "0=Local, 1=NDI"},
                        "resolution": {"type": "string", "default": "1280x720"},
                        "fps": {"type": "integer", "default": 30}
                    },
                    "required": ["source"]
                }
            },
            {
                "name": "disconnect_camera",
                "description": "Disconnect a camera from a specific slot (0-3). 0='cam1', 1='cam2', etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "slot_index": {"type": "integer", "description": "0-3"}
                    },
                    "required": ["slot_index"]
                }
            },
            {
                "name": "get_camera_frame",
                "description": "Capture a live frame (base64) from a camera slot (0-3). 0='cam1', 1='cam2', etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "slot_index": {"type": "integer", "default": 0, "description": "0-3"},
                        "max_width": {"type": "integer"}
                    }
                }
            },
            {
                "name": "get_csv_preview",
                "description": "Read the first few rows of a CSV file to understand its headers and data format. Essential before adding CSV sensors.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Full path to the CSV file"},
                        "row_count": {"type": "integer", "default": 5, "description": "Number of rows to preview"}
                    },
                    "required": ["file_path"]
                }
            },
            {
                "name": "manage_camera_overlay",
                "description": "Add, update, or remove video overlays. Supports text, timestamps, sensor values, rectangles, and motion indicators.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "slot_index": {"type": "integer", "description": "0-3. 0='cam1', 1='cam2', etc."},
                        "action": {"type": "string", "enum": ["add", "update", "remove"]},
                        "overlay_id": {"type": "integer", "description": "ID of the overlay (required for update/remove)"},
                        "overlay_type": {"type": "string", "enum": ["text", "timestamp", "sensor", "rectangle", "motion"]},
                        "name": {"type": "string"},
                        "position": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2, "description": "[x, y] normalized 0.0-1.0"},
                        "text_color": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3, "description": "[B, G, R] color tuple"},
                        "bg_color": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3, "description": "[B, G, R] background color tuple"},
                        "bg_alpha": {"type": "number", "minimum": 0, "maximum": 1},
                        "font_scale": {"type": "number", "default": 0.7},
                        "thickness": {"type": "integer", "default": 2},
                        "content": {"type": "string", "description": "Text content, time format, or sensor name."}
                    },
                    "required": ["slot_index", "action"]
                }
            },
            {
                "name": "take_camera_snapshot",
                "description": "Capture a high-quality frame from a camera and save it to the project's Snapshots folder.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "slot_index": {"type": "integer", "description": "0-3. 0='cam1', 1='cam2', etc."}
                    },
                    "required": ["slot_index"]
                }
            },
            {
                "name": "start_camera_recording",
                "description": "Start recording video for a specific camera slot or all cameras.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "slot_index": {"type": "integer", "description": "0-3. Omit to start ALL cameras."}
                    }
                }
            },
            {
                "name": "stop_camera_recording",
                "description": "Stop recording video for a specific camera slot or all cameras.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "slot_index": {"type": "integer", "description": "0-3. Omit to stop ALL cameras."}
                    }
                }
            },
            {
                "name": "get_optical_sensor_preview",
                "description": "Capture a live frame (base64) from a specific Optical sensor. Use this to verify ROI and detection settings.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sensor_name": {"type": "string", "description": "The name of the optical sensor (e.g., 'Optical 1')"},
                        "max_width": {"type": "integer"}
                    },
                    "required": ["sensor_name"]
                }
            },
            {
                "name": "get_audio_sensor_preview",
                "description": "Get a summary of the current audio spectrum and levels for a specific Audio sensor. Returns RMS, Peak, and dominant frequency bands.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sensor_name": {"type": "string", "description": "The name of the audio sensor"}
                    },
                    "required": ["sensor_name"]
                }
            },
            {
                "name": "write_mqtt_message",
                "description": "Publish a message to an MQTT topic. Useful for controlling remote devices or resetting counters.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "The MQTT topic to publish to"},
                        "payload": {"type": "string", "description": "The message content"}
                    },
                    "required": ["topic", "payload"]
                }
            },
            {
                "name": "set_dashboard_config",
                "description": "Configure dashboard visibility options, timespan, and active camera slots.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "show_automation": {"type": "boolean", "description": "Toggle visibility of Automation Status"},
                        "show_events": {"type": "boolean", "description": "Toggle visibility of Recent System Events"},
                        "show_image": {"type": "boolean", "description": "Toggle visibility of Last Images"},
                        "show_camera": {"type": "boolean", "description": "Toggle visibility of Camera Preview"},
                        "timespan": {"type": "string", "enum": ["10s", "30s", "1min", "5min", "15min", "30min", "1h", "3h", "6h", "12h", "24h", "All"]},
                        "camera_slots": {"type": "array", "items": {"type": "boolean"}, "minItems": 4, "maxItems": 4, "description": "Active status for Cam 1, 2, 3, 4"}
                    }
                }
            },
            {
                "name": "control_playback",
                "description": "Control data/video playback (replay mode). Note: Setting 'position' or 'step_frames' will seek to that point but will NOT automatically start playback if it was paused. It will stay in the current play/pause state.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["play", "pause", "toggle", "stop"]},
                        "speed": {"type": "string", "enum": ["0.25x", "0.5x", "1x", "2x", "4x"]},
                        "position": {"type": "string", "description": "Time string like '12:21', '12m 21s', or '0'"},
                        "step_frames": {"type": "integer", "description": "Number of frames to step (positive for forward, negative for backward)"}
                    }
                }
            },
            {
                "name": "add_quick_note",
                "description": "Add a quick timestamped note to the current run or replay.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The content of the note"}
                    },
                    "required": ["text"]
                }
            },
            {
                "name": "get_ui_state",
                "description": "Get the current active tab and any visible popups or dialogs.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "update_app_settings",
                "description": "Update application settings (e.g., video quality, log levels).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "settings": {"type": "object", "description": "Key-value pairs of settings to update"}
                    },
                    "required": ["settings"]
                }
            },
            {
                "name": "save_plugin_code",
                "description": "Create or update a Python plugin file (Inbound or Outbound) in the 'plugins/' directory. \nCRITICAL: You MUST use the documentation topic 'plugins' to understand the required structure and classes (BaseInterface or BaseOutboundInterface).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "The name of the file (e.g., 'my_sensor.py'). MUST end in .py."},
                        "code": {"type": "string", "description": "The full Python source code for the plugin."}
                    },
                    "required": ["filename", "code"]
                }
            },
            {
                "name": "list_plugins",
                "description": "List all Python files available in the 'plugins/' directory.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "read_plugin_code",
                "description": "Read the source code of a plugin file from the 'plugins/' directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "The name of the plugin file to read (e.g., 'example_plugin.py')."}
                    },
                    "required": ["filename"]
                }
            }
        ]

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Dispatch tool calls from the LLM with robust name matching and thread safety."""
        # 1. Determine if we are already on the main thread
        is_main_thread = False
        try:
            if QCoreApplication.instance() and QThread.currentThread() == QCoreApplication.instance().thread():
                is_main_thread = True
        except Exception:
            pass

        # 2. Check if the tool is safe to run in the background
        # We clean the name first to match the list
        clean_name = name.lower().strip().replace("functions.", "").replace("to=", "")
        match = re.search(r'[a-z_][a-z0-9_]*', clean_name)
        if match:
            clean_name = match.group(0)
            
        is_safe_background = clean_name in self.SAFE_BACKGROUND_TOOLS

        if is_main_thread or is_safe_background:
            if is_safe_background and not is_main_thread:
                print(f"[MCP] Executing safe tool '{name}' directly in background thread.")
            return self._execute_internal(name, arguments)
        else:
            # Dispatch to main thread and wait for result using the signal
            result_container = {"data": None, "error": None}
            
            print(f"[MCP] Dispatching UI-bound tool '{name}' to main thread via signal...")
            # We pass the result_container dictionary as an 'object' to ensure it's handled as a reference
            self._dispatch_signal.emit(name, arguments or {}, result_container)
            
            if result_container["error"]:
                print(f"[MCP] Tool '{name}' failed on main thread: {result_container['error']}")
                return {"error": result_container["error"]}
                
            print(f"[MCP] Tool '{name}' execution completed successfully on main thread.")
            return result_container["data"]

    @pyqtSlot(str, dict, object)
    def _dispatch_to_main_thread(self, name: str, arguments: dict, result_container: dict):
        """Internal slot to execute tool logic on the main GUI thread."""
        try:
            result_container["data"] = self._execute_internal(name, arguments)
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            print(f"[MCP] Error in tool '{name}' on main thread: {error_msg}")
            result_container["error"] = str(e)

    def _execute_internal(self, name: str, arguments: Dict[str, Any]) -> Any:
        """The actual tool dispatch logic (should be called on main thread)."""
        print(f"[MCP] Starting execution of '{name}' on thread: {QThread.currentThread().objectName() or 'Main'}")
        
        # Local models sometimes hallucinate prefixes like 'functions.' or suffixes like 'richjson'
        clean_name = name.lower().strip()
        
        # 1. Remove common prefixes
        if "functions." in clean_name:
            clean_name = clean_name.replace("functions.", "")
        if "to=" in clean_name:
            clean_name = clean_name.replace("to=", "")
            
        # 2. Extract alphanumeric part (the actual function name)
        match = re.search(r'[a-z_][a-z0-9_]*', clean_name)
        if match:
            clean_name = match.group(0)

        mapping = {
            "get_sampling_rate": self.get_sampling_rate,
            "query_sensor_data": self.query_sensor_data,
            "get_sensor_statistics": self.get_sensor_statistics,
            "get_notes": self.get_notes,
            "get_notes_html": self.get_notes_html,
            "edit_notes": self.edit_notes,
            "insert_note_media": self.insert_note_media,
            "get_automation_info": self.get_automation_info,
            "get_available_sensors": self.get_available_sensors,
            "get_current_time": self.get_current_time,
            "get_data_summary": self.get_data_summary,
            "get_graph_screenshot": self.get_graph_screenshot,
            "get_project_config": self.get_project_config,
            "get_documentation": self.get_documentation,
            "set_graph_config": self.set_graph_config,
            "get_projects_list": self.get_projects_list,
            "set_active_project": self.set_active_project,
            "configure_next_run": self.configure_next_run,
            "export_run": self.export_run,
            "import_run": self.import_run,
            "save_automation_sequence": self.save_automation_sequence,
            "remove_automation_sequence": self.remove_automation_sequence,
            "control_automation": self.control_automation,
            "list_camera_sources": self.list_camera_sources,
            "connect_camera": self.connect_camera,
            "disconnect_camera": self.disconnect_camera,
            "get_camera_frame": self.get_camera_frame,
            "get_optical_sensor_preview": self.get_optical_sensor_preview,
            "get_audio_sensor_preview": self.get_audio_sensor_preview,
            "write_mqtt_message": self.write_mqtt_message,
            "get_csv_preview": self.get_csv_preview,
            "manage_camera_overlay": self.manage_camera_overlay,
            "take_camera_snapshot": self.take_camera_snapshot,
            "start_camera_recording": self.start_camera_recording,
            "stop_camera_recording": self.stop_camera_recording,
            "list_available_interfaces": self.list_available_interfaces,
            "get_interface_schema": self.get_interface_schema,
            "get_live_interface_data": self.get_live_interface_data,
            "toggle_interface_connection": self.toggle_interface_connection,
            "configure_sensor_calibration": self.configure_sensor_calibration,
            "update_sensor_settings": self.update_sensor_settings,
            "remove_sensor": self.remove_sensor,
            "edit_sensor": self.edit_sensor,
            "add_sensor": self.add_sensor,
            "test_serial_command": self.test_serial_command,
            "list_serial_ports": self.list_serial_ports,
            "configure_interface": self.configure_interface,
            "configure_serial_sequence": self.configure_serial_sequence,
            "get_serial_sequence": self.get_serial_sequence,
            "list_serial_sequences": self.list_serial_sequences,
            "remove_serial_sequence": self.remove_serial_sequence,
            "update_interface_config": self.update_interface_config,
            "check_server_status": self.check_server_status,
            "set_dashboard_config": self.set_dashboard_config,
            "control_playback": self.control_playback,
            "add_quick_note": self.add_quick_note,
            "get_ui_state": self.get_ui_state,
            "update_app_settings": self.update_app_settings,
            "save_plugin_code": self.save_plugin_code,
            "list_plugins": self.list_plugins,
            "read_plugin_code": self.read_plugin_code
        }
        
        func = mapping.get(clean_name)
        
        if func:
            try:
                if not arguments:
                    result = func()
                else:
                    # Robustly handle unexpected arguments
                    sig = inspect.signature(func)
                    valid_args = {}
                    for param in sig.parameters.values():
                        if param.name in arguments:
                            valid_args[param.name] = arguments[param.name]
                    result = func(**valid_args)
                
                print(f"[MCP] Execution of '{name}' finished successfully.")
                return result
            except Exception as e:
                import traceback
                print(f"[MCP] ERROR in '{name}': {str(e)}\n{traceback.format_exc()}")
                return {"error": f"Execution error: {str(e)}"}
                
        available = sorted(mapping.keys())
        print(f"[MCP] ERROR: Tool '{name}' not found.")
        return {"error": f"Tool '{name}' not found. Available: {available}"}
