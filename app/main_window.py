import sys
import os
import datetime
import time
from PyQt6.QtWidgets import QMainWindow, QMessageBox, QFileDialog, QTableWidgetItem, QDialog, QVBoxLayout, QGridLayout, QLabel, QComboBox, QDoubleSpinBox, QPushButton, QGroupBox, QLineEdit, QHBoxLayout, QSpinBox, QSlider, QCheckBox, QTextEdit, QDialogButtonBox, QTabWidget, QScrollArea, QSizePolicy, QFrame, QListWidget, QFormLayout, QTableWidget, QAbstractItemView, QColorDialog, QApplication
from PyQt6.QtCore import Qt, QTimer, QSettings, QCoreApplication, QEvent, QUrl, QFileInfo, QTime, QPoint, QSize, QDateTime, QDir, pyqtSignal, QObject, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QIcon, QDesktopServices, QColor
from enum import Enum, auto
import traceback
import pathlib
import json
import shutil
from copy import deepcopy

# Import common types
from app.utils.common_types import StatusState

# Import UI module
from app.ui.ui_setup import setup_ui, update_device_connection_status

# Import controllers
from app.controllers.project_controller import ProjectController
from app.controllers.sensor_controller import SensorController
from app.controllers.camera_controller import CameraController
from app.controllers.graph_controller import GraphController
from app.controllers.automation_controller import AutomationController
from app.controllers.data_collection_controller import DataCollectionController
from app.controllers.export_controller import ExportController
from app.controllers.notes_controller import NotesController

# Import models
from app.models.settings_model import SettingsModel
from app.models.sensor_model import SensorModel

# Import core components
from app.core.logger import Logger
from app.utils.config_loader import load_config, save_config

# Import plotting library
import pyqtgraph as pg
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtMultimedia import QMediaPlayer

# Import dialogs
from app.ui.dialogs.other_sensors_dialog import OtherSensorsDialog

VIRTUAL_SENSORS_FILENAME = "virtual_sensors.json"
VIRTUAL_SENSORS_PATH = VIRTUAL_SENSORS_FILENAME  # Store in current directory as fallback

class DAQApp(QMainWindow):
    """Main application window"""
    def __init__(self):
        """Initialize the main window"""
        super().__init__()
        
        # Set application settings
        self.settings = QSettings("EvoLabs", "DAQ")
        self.settings_model = SettingsModel(self.settings)
        
        # Load application configuration
        self.config = load_config()
        
        # Initialize logger
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"daq_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        # Set log level based on debug_mode setting
        debug_mode = self.settings.value("debug_mode", "false").lower() == "true"
        log_level = "DEBUG" if debug_mode else "INFO"
        self.logger = Logger("UI", log_file=log_file, log_level=log_level)
        self.logger.log("Application started", "INFO")
        
        # Initialize data structures
        self.recording = False
        self.running = False
        self.start_time = None # To store the start time for relative plotting
        self.dragging_overlay = None
        
        # Initialize theme
        self.theme = "dark"  # Default theme
        
        # Add status variables
        self.project_status = StatusState.ERROR # Default to error until checked
        self.sensor_status = StatusState.ERROR
        self.camera_status = StatusState.OPTIONAL # Default camera to optional/inactive
        self.automation_status = StatusState.OPTIONAL # Default automation to optional/inactive
        
        # Initialize attributes for timelapse settings persistence
        self.timelapse_source_folder = QLineEdit()
        self.timelapse_output_file = QLineEdit()
        self.timelapse_duration = QSpinBox()
        self.timelapse_duration.setRange(1, 300) # Default range from timelapse_utils
        self.timelapse_duration.setValue(30)    # Default value
        self.timelapse_fps = QSpinBox()
        self.timelapse_fps.setRange(10, 60)     # Default range
        self.timelapse_fps.setValue(30)        # Default value
        self.timelapse_format = QComboBox()
        self.timelapse_format.addItems(["MP4 (H.264)", "AVI (MJPG)", "AVI (XVID)"]) # Default formats
        
        # Set up the UI
        setup_ui(self)
        
        # Initialize controllers
        self.init_controllers()
        
        # Initialize timers after controllers are created
        self.init_timers()
        
        # Connect signals
        self.connect_signals()
        
        # Load settings
        self.load_settings()
        
        # Set window properties
        self.setWindowTitle("Artefakt")
        self.resize(1920, 1080)
        
        # Set icon if available
        icon_path = os.path.join("assets", "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        # Show startup message
        self.logger.log("Application initialized", "INFO")
        self.statusBar().showMessage("Ready")
        
        # Initial status update
        self.update_status_indicators() # Perform an initial check
        
        # Show dashboard as default tab
        self.stacked_widget.setCurrentIndex(0)  # Show Projects tab by default
        
        # Set default dashboard graph timeframe
        if hasattr(self, 'dashboard_timespan_combo'):
             # Find the index for "All" and set it
            all_index = self.dashboard_timespan_combo.findText("All")
            if all_index != -1:
                self.dashboard_timespan_combo.setCurrentIndex(all_index)
            else:
                # If "All" is not found, add it and set it as current
                self.dashboard_timespan_combo.insertItem(0, "All")
                self.dashboard_timespan_combo.setCurrentIndex(0)
                self.logger.log("Added 'All' to dashboard timespan combo.", "INFO")

        # Auto-connect logic for Arduino and LabJack
        if self.settings.value("arduino_auto_connect", "false") == "true":
            try:
                if hasattr(self, 'arduino_port') and hasattr(self, 'arduino_baud'):
                    port = self.arduino_port.currentText()
                    baud = int(self.arduino_baud.currentText())
                else:
                    port = self.settings.value("arduino_port", "COM3")
                    baud = int(self.settings.value("arduino_baud", "9600"))
                if hasattr(self, 'data_collection_controller'):
                    self.data_collection_controller.connect_arduino(port, baud)
            except Exception as e:
                print(f"Auto-connect Arduino failed: {e}")
        if self.settings.value("labjack_auto_connect", "false") == "true":
            try:
                device_type = self.settings.value("labjack_type", "U3")
                if hasattr(self, 'sensor_controller'):
                    self.sensor_controller.connect_labjack(device_type)
            except Exception as e:
                print(f"Auto-connect LabJack failed: {e}")

        self.other_sensors = []  # Liste für virtuelle Sensoren

    def init_timers(self):
        """Initialize application timers"""
        # UI update timer
        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self.update_ui)
        self.ui_timer.start(100) # Update status less frequently maybe? 10 FPS
        
        # Blink timer for recording indicator
        self.blink_timer = QTimer()
        self.blink_timer.setInterval(1000)  # 1Hz
        self.blink_visible = True
        self.blink_timer.timeout.connect(self.update_running_text)

    def connect_signals(self):
        """Connect signals for UI elements to event handlers"""
        # Connect main buttons
        self.toggle_btn.clicked.connect(self.on_toggle_clicked)
        
        # Connect project save/load buttons
        if hasattr(self, 'save_project_btn') and hasattr(self, 'project_controller'):
            self.save_project_btn.clicked.connect(self.project_controller.save_project)
            
        if hasattr(self, 'load_project_btn') and hasattr(self, 'project_controller'):
            self.load_project_btn.clicked.connect(self.project_controller.on_load_run_clicked)
        
        # Connect browse base directory button
        if hasattr(self, 'browse_base_dir_btn') and hasattr(self, 'project_controller'):
            # Disconnect any existing connections first to avoid duplicates
            try:
                self.browse_base_dir_btn.clicked.disconnect()
            except:
                pass
            # Connect to the correct method in project_controller
            self.browse_base_dir_btn.clicked.connect(self.project_controller.on_load_dir_clicked)
            self.logger.log("Connected browse button for base directory", "INFO")
        
        # Connect controller signals
        # Connect data collection signals if available
        if hasattr(self, 'data_collection_controller'):
            # Connect data received signal to update sensor values
            self.data_collection_controller.data_received_signal.connect(
                self.update_sensor_values)
            
            # Connect status update signal to logger
            self.data_collection_controller.status_update_signal.connect(
                lambda msg, level: self.logger.log(msg, level))
            
            # Connect combined data signal to graph controller for synchronized updates
            if hasattr(self, 'graph_controller'):
                # Disconnect the old signal if it was connected
                try:
                    self.data_collection_controller.data_received_signal.disconnect(
                        self.graph_controller.plot_new_data)
                except:
                    # If it wasn't connected, just proceed
                    pass
                    
                # Connect the combined data signal for synchronized graph updates
                self.data_collection_controller.combined_data_signal.connect(
                    self.graph_controller.plot_new_data)
                self.logger.log("Connected combined data signal to graph controller for synchronized updates", "INFO")
        
        # Connect sensor controller signals
        if hasattr(self, 'sensor_controller'):
            # Connect status change signal
            self.sensor_controller.status_changed.connect(self.update_status_indicators)
            self.sensor_controller.connect_signals()
            
            # DO NOT connect buttons directly here - this creates conflicts
            # Buttons are connected properly in setup_sensor_tab_signals() 
            # These direct connections can cause conflicts
            # Instead, setup_sensor_tab_signals connects the buttons to main window methods
            # which then call the controller methods

        if hasattr(self, 'camera_controller'):
            self.camera_controller.status_changed.connect(self.update_status_indicators)
            self.camera_controller.connect_signals()
            
        if hasattr(self, 'automation_controller'):
            self.automation_controller.status_changed.connect(self.update_status_indicators)
            # Connect UI buttons to controller methods

        
        # Connect navigation buttons
        for i, btn in enumerate(self.nav_buttons):
            btn.clicked.connect(lambda checked, index=i: self.stacked_widget.setCurrentIndex(index))
        
        # Connect tab change signal to handle tab-specific initialization
        self.stacked_widget.currentChanged.connect(self.on_tab_changed)
        
        # Connect settings-related signals
        self.apply_settings_btn.clicked.connect(self.apply_settings)
        
        # Connect project browser tree view
        if hasattr(self, 'project_tree') and hasattr(self, 'project_controller'):
            self.project_tree.clicked.connect(self.project_controller.on_project_tree_clicked)

        # Connect interface status signal to update device status display
        if hasattr(self, 'data_collection_controller'):
            self.data_collection_controller.interface_status_signal.connect(self.handle_interface_status)
            # Connect data received signal to graph controller ONLY if live plotting is NOT active for the main graph
            # Live plotting is handled separately by plot_new_data connected to combined_data_signal
            # if hasattr(self, 'graph_controller'):
            #      self.data_collection_controller.data_received_signal.connect(self.graph_controller.plot_new_data) # Use correct signal name

        # Connect graph live update checkbox
        if hasattr(self, 'graph_live_update_checkbox'):
            self.graph_live_update_checkbox.stateChanged.connect(self.handle_graph_live_update_toggle)

        # Connect graph controls
        if hasattr(self, 'graph_type_combo') and hasattr(self, 'graph_controller'):
            self.graph_type_combo.currentIndexChanged.connect(self.graph_controller.on_graph_type_changed)
            self.graph_primary_sensor.currentIndexChanged.connect(self.graph_controller.update_graph)
            self.graph_secondary_sensor.currentIndexChanged.connect(self.graph_controller.update_graph)
            self.graph_timespan.currentIndexChanged.connect(self.graph_controller.on_timespan_changed)
            self.dashboard_timespan.currentIndexChanged.connect(self.graph_controller.on_dashboard_timespan_changed)
            # Ensure initial state of the live update checkbox is handled after setup
            self.graph_controller.ensure_main_graph_live_update()
            # Connect multi-sensor list changes to update the graph immediately
            if hasattr(self, 'multi_sensor_list'):
                self.multi_sensor_list.itemChanged.connect(self.graph_controller.update_graph)

    def on_tab_changed(self, index):
        """Handle tab change event"""
        # Update specific tab content when switching to that tab
        # Updated tab names to match the new navigation order from ui_setup.py
        tab_names = ["Projects", "Settings", "Camera", "Sensors", "Automation", "Dashboard", "Graphs", "Notes", "Video"]
        if index < 0 or index >= len(tab_names):
            return
        
        tab_name = tab_names[index]
        
        if tab_name == "Dashboard":
            self.graph_controller.update_dashboard_graph()
            
            # Update the dashboard camera preview if camera is connected
            if hasattr(self, 'camera_controller'):
                # Set the default message if no camera frame is available
                if not hasattr(self, 'dashboard_camera_label'):
                    return
                    
        elif tab_name == "Graphs":
            # When switching to graphs tab, update the graph display
            if hasattr(self, 'graph_controller'):
                self.graph_controller.update_graph()
                
        elif tab_name == "Notes":
            # When switching to notes tab, load the note content
            if hasattr(self, 'notes_controller'):
                # Only reload from disk if content hasn't been loaded yet
                if not self.notes_controller.document_loaded:
                    self.notes_controller.load_note()
        
        # Save notes when moving away from Notes tab
        previous_index = getattr(self, 'previous_tab_index', 0)
        if previous_index >= 0 and previous_index < len(tab_names):
            previous_tab = tab_names[previous_index]
            if previous_tab == "Notes" and hasattr(self, 'notes_controller'):
                self.notes_controller.autosave_note()
                
        # Store the current tab index for next time
        self.previous_tab_index = index

    def update_ui(self):
        """Update UI elements"""
        # Call the status update function periodically
        self.update_status_indicators()
        # Any other periodic UI updates can go here

    def update_status_indicators(self):
        """Update the status indicators for each component"""
        # Get status for each controller
        try:
            if hasattr(self, 'project_controller'):
                self.project_status, project_tooltip = self.project_controller.get_status()
            else:
                self.project_status, project_tooltip = StatusState.ERROR, "Project Controller not ready"
        except AttributeError:
            self.project_status, project_tooltip = StatusState.ERROR, "Project Controller not ready"
            
        try:
            if hasattr(self, 'sensor_controller'):
                sensor_status_info = self.sensor_controller.get_status()
                # Handle dictionary return value instead of tuple
                if sensor_status_info["sensor_count"] == 0:
                    self.sensor_status = StatusState.OPTIONAL
                    sensor_tooltip = "No sensors configured (Optional)"
                else:
                    self.sensor_status = StatusState.READY
                    sensor_tooltip = f"Configured with {sensor_status_info['sensor_count']} sensor(s)"
                    if sensor_status_info.get("acquisition_running", False):
                        sensor_tooltip += "\nData acquisition in progress"
                
                # Ensure sensors are never ERROR (red), only OPTIONAL (yellow/orange) or READY (green)
                if self.sensor_status == StatusState.ERROR:
                    self.sensor_status = StatusState.OPTIONAL
                    sensor_tooltip = "No sensors defined (optional but recommended)"
            else:
                self.sensor_status, sensor_tooltip = StatusState.OPTIONAL, "Sensor Controller not ready"
        except Exception as e:
            print(f"Error getting sensor status: {str(e)}")
            self.sensor_status, sensor_tooltip = StatusState.OPTIONAL, "Sensor Controller not ready"

        try:
            if hasattr(self, 'camera_controller'):
                self.camera_status, camera_tooltip = self.camera_controller.get_status()
            else:
                self.camera_status, camera_tooltip = StatusState.OPTIONAL, "Camera Controller not ready"
        except AttributeError:
            self.camera_status, camera_tooltip = StatusState.OPTIONAL, "Camera Controller not ready"

        try:
            if hasattr(self, 'automation_controller'):
                self.automation_status, automation_tooltip = self.automation_controller.get_status()
            else:
                self.automation_status, automation_tooltip = StatusState.OPTIONAL, "Automation Controller not ready"
        except AttributeError:
            self.automation_status, automation_tooltip = StatusState.OPTIONAL, "Automation Controller not ready"


        # --- 2. Update Button Icons and Tooltips ---
        # This assumes you have SVG files named like: Projects_green.svg, Projects_red.svg, etc.
        # And that self.nav_buttons indices correspond correctly. **Verify these indices.**
        button_map = {
             # Map component status to button index and base icon name - updated to match new order
             "project": (0, "Projects"), # nav_buttons[0] is Project button
             "sensors": (3, "Sensors"),  # nav_buttons[3] is Sensors button
             "camera": (2, "Camera"),    # nav_buttons[2] is Camera button
             "automation": (4, "Automation") # nav_buttons[4] is Automation button
        }

        status_color_map = {
            StatusState.READY: "green",
            StatusState.OPTIONAL: "yellow",
            StatusState.ERROR: "red",
            StatusState.RUNNING: "green", # Add mapping for RUNNING state
        }

        statuses = {
            "project": (self.project_status, project_tooltip),
            "sensors": (self.sensor_status, sensor_tooltip),
            "camera": (self.camera_status, camera_tooltip),
            "automation": (self.automation_status, automation_tooltip),
        }

        # Path to icons - adjust if they are elsewhere
        icon_base_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "ui")

        for component, (index, base_name) in button_map.items():
            if index < len(self.nav_buttons): # Check index bounds
                status, tooltip = statuses[component]
                color = status_color_map.get(status, "red") # Default to red if status unknown

                # Handle yellow state - project is never yellow, others are optional
                if status == StatusState.OPTIONAL:
                     if component == "project": # Project cannot be optional/yellow
                          color = "red" # Treat optional project as error
                          tooltip = "Project details must be completed." # Override tooltip
                     else:
                          tooltip = f"{base_name}: Not active (Optional)" # Default yellow tooltip

                # Construct icon path
                icon_path = os.path.join(icon_base_path, f"{base_name}_{color}.svg")

                # Check if icon file exists, otherwise use a default or log error
                if not os.path.exists(icon_path):
                     self.logger.log(f"Icon file not found: {icon_path}", "WARN")
                     # Try to use the default icon without color
                     default_icon_path = os.path.join(icon_base_path, f"{base_name}.svg")
                     if os.path.exists(default_icon_path):
                         self.nav_buttons[index].setIcon(QIcon(default_icon_path))
                     # Skip this iteration if no icon found
                     continue

                # Set the colored icon
                self.nav_buttons[index].setIcon(QIcon(icon_path))

                # Set tooltip
                self.nav_buttons[index].setToolTip(tooltip)
            else:
                self.logger.log(f"Button index {index} for {component} out of range.", "WARN")


        # --- 3. Update Start/Stop Button State ---
        # Determine overall readiness
        project_ready = self.project_status == StatusState.READY
        
        # Check if run description is empty
        run_description_empty = False
        if hasattr(self, 'run_description'):
            run_description_text = self.run_description.toPlainText().strip()
            run_description_empty = not run_description_text
                
        # Modified: User should be able to start a run with just sensors
        # Mark system as ready if either sensors or camera are ready, or automation is ready/optional
        optional_ready = (self.sensor_status == StatusState.READY or 
                         self.camera_status == StatusState.READY or 
                         self.automation_status in [StatusState.READY, StatusState.OPTIONAL])

        can_start = project_ready and optional_ready

        # Get original button styles (preserve the styles that were set during UI setup)
        start_btn_original_style = self.start_btn_style
        stop_btn_original_style = self.stop_btn_style
        
        # Disabled style - maintains shape and size but adds gray overlay
        disabled_style = """
        QPushButton {
            background: #CCCCCC;
            color: #777777;
            border: none;
            padding: 8px 15px;
            border-radius: 5px;
            font-weight: bold;
            font-size: 16px;
            border-bottom: 2px solid #AAAAAA;
        }
        """

        # If we're running, ensure the button stays in Stop mode
        if self.running:
            self.toggle_btn.setEnabled(True)
            self.toggle_btn.setText("Stop")
            self.toggle_btn.setStyleSheet(stop_btn_original_style)
            return
        
        # Only update the button state if we're not already running
        # This prevents the method from changing the button text/style during operation
        if can_start:
            if run_description_empty:
                # Gray out button if run description is empty (system not ready for new test)
                self.toggle_btn.setEnabled(False)
                self.toggle_btn.setStyleSheet(disabled_style)
                self.sidebar_ready_status.setText("Enter Run Description")
                self.sidebar_ready_status.setStyleSheet("color: #FF4136;") # Red
            else:
                # Enable button if everything is ready including run description
                self.toggle_btn.setEnabled(True)
                self.toggle_btn.setStyleSheet(start_btn_original_style)
                self.toggle_btn.setText("Start")
                self.sidebar_ready_status.setText("Ready")
                self.sidebar_ready_status.setStyleSheet("color: #2ECC40;") # Green
        else:
            self.toggle_btn.setEnabled(False)
            self.toggle_btn.setStyleSheet(disabled_style)
            self.toggle_btn.setText("Start")
            self.sidebar_ready_status.setText("Not Ready")
            self.sidebar_ready_status.setStyleSheet("color: #FF4136;") # Red

    def on_toggle_clicked(self):
        """Handle toggle button click - simulate checkbox toggle"""
        # Add a simple debounce to prevent rapid toggling
        if hasattr(self, '_toggle_last_click'):
            now = datetime.datetime.now()
            if (now - self._toggle_last_click).total_seconds() < 0.5:
                print(f"[TOGGLE] Ignoring rapid toggle click, last click: {self._toggle_last_click}")
                self.logger.log("Ignoring rapid toggle click (debounce protection)", "DEBUG")
                return
        self._toggle_last_click = datetime.datetime.now()
        
        # Check the current text of the button instead of relying on the running state
        current_text = self.toggle_btn.text()
        
        if current_text == "Stop":
            # We're running, so stop
            print("[TOGGLE] Button shows 'Stop', stopping acquisition")
            self.logger.log("Stopping acquisition", "DEBUG")
            
            # Save testers value to config before stopping
            if hasattr(self, 'run_testers') and hasattr(self, 'config'):
                testers = self.run_testers.text().strip()
                if testers:
                    self.config["last_testers"] = testers
                    self.save_config()
            
            # Update button first
            self.toggle_btn.setText("Start")
            self.toggle_btn.setStyleSheet(self.start_btn_style)
            self.running = False
            self.start_time = None # Reset start time
            
            # Stop the blink timer
            if self.blink_timer.isActive():
                self.blink_timer.stop()
            self.update_running_text() # Ensure indicator is cleared
                
            # Reset record button if it exists
            if hasattr(self, 'record_btn'):
                self.record_btn.setEnabled(True)
                self.record_btn.setText("Record")
                self.record_btn.setStyleSheet("background-color: #4CAF50; color: white;")
            
            # --- ADDED: Stop graph updates ---
            # Stop live graph updates
            if hasattr(self, 'graph_controller'):
                print("[TOGGLE] Stopping live dashboard graph updates...")
                self.graph_controller.stop_live_dashboard_update()

            # Stop data collection and acquisition
            if hasattr(self, 'data_collection_controller'):
                print("[TOGGLE] Stopping data collection...")
                self.data_collection_controller.stop_data_collection()
                
            if hasattr(self, 'sensor_controller'):
                print("[TOGGLE] Stopping sensor acquisition...")
                self.sensor_controller.stop_acquisition()
                self.logger.log("Stopped data acquisition")
                
            # Stop video recording if active
            if hasattr(self, 'camera_controller') and self.camera_controller.is_recording:
                print("[TOGGLE] Stopping video recording...")
                self.camera_controller.stop_recording()
                self.logger.log("Stopped video recording")
            
            # --- ADDED: Stop all automation sequences ---
            if hasattr(self, 'automation_controller'):
                print("[TOGGLE] Stopping all automation sequences...")
                self.automation_controller.stop_all_automation()
                self.logger.log("Stopped all automation sequences")

            # Update status message
            self.statusBar().showMessage("Stopped recording")
            print("[TOGGLE] Data acquisition stopped successfully")
            
            # Clear run description after run is complete - ONLY after stopping
            if hasattr(self, 'run_description'):
                print("[TOGGLE] Clearing run description")
                self.run_description.clear()
                if hasattr(self, 'project_controller'):
                    self.project_controller.run_description = ""
            
            # Update status indicators and UI state
            self.update_status_indicators()
        else:
            # We're not running, so start
            print("[TOGGLE] Button shows 'Start', starting acquisition")
            self.logger.log("Starting acquisition", "DEBUG")
            
            # Verify that run description is not empty before starting
            if hasattr(self, 'run_description'):
                run_description_text = self.run_description.toPlainText().strip()
                if not run_description_text:
                    self.logger.log("Cannot start acquisition - run description is empty", "ERROR")
                    print("[TOGGLE] Cannot start - run description is empty")
                    self.statusBar().showMessage("Please enter a run description")
                    return
            
            if not self.project_controller.validate_run_settings():
                self.logger.log("Run settings validation failed, cannot start acquisition", "ERROR")
                print("[TOGGLE] Run settings validation failed")
                return
                
            # Create a run directory with timestamp before starting acquisition
            run_dir = self.project_controller.prepare_run_directory()
            if not run_dir:
                self.logger.log("Failed to create run directory, cannot start acquisition", "ERROR")
                print("[TOGGLE] Failed to create run directory")
                return
                
            # Initialize the notes template for this run
            if hasattr(self, 'notes_controller'):
                # Create a new note from the template (this will check if notes.html exists)
                self.notes_controller.document_loaded = False  # Reset to force loading from template
                self.notes_controller.load_note()
                self.logger.log("Notes template initialized for this run", "DEBUG")
                
            # Apply global sampling rate from UI before starting data collection
            if hasattr(self, 'sampling_rate_spinbox') and hasattr(self, 'data_collection_controller'):
                interval_seconds = self.sampling_rate_spinbox.value()
                # Convert interval in seconds to rate in Hz (rate = 1/interval)
                sampling_rate_hz = 1.0 / interval_seconds
                self.data_collection_controller.set_sampling_rate(sampling_rate_hz)
                # Save the interval in seconds to settings
                self.settings.setValue("global_sampling_rate", interval_seconds)
                self.logger.log(f"Applied sampling interval: {interval_seconds} seconds (rate: {sampling_rate_hz:.2f} Hz)")
                
            # Update button first
            self.toggle_btn.setText("Stop")
            self.toggle_btn.setStyleSheet(self.stop_btn_style)
            self.running = True
            self.start_time = time.time() # Record start time for relative plotting
            
            # Start the blink timer
            self.blink_timer.start()
            self.update_running_text() # Initial update
            
            print(f"[TOGGLE] Created run directory: {run_dir}")
            
            # --- ADDED: Start graph updates ---
            # Start live graph updates on dashboard
            if hasattr(self, 'graph_controller'):
                 print("[TOGGLE] Starting live dashboard graph updates...")
                 self.graph_controller.start_live_dashboard_update(self.start_time) # Pass start time

            # Start data collection in the data collection controller
            if hasattr(self, 'data_collection_controller'):
                print("[TOGGLE] Starting data collection...")
                self.data_collection_controller.start_data_collection(run_dir)
            
            # Start data acquisition and recording if configured
            if hasattr(self, 'sensor_controller'):
                print("[TOGGLE] Starting sensor acquisition...")
                self.sensor_controller.start_acquisition()
            
            if self.settings_model.get_value("auto_record", False):
                print("[TOGGLE] Auto-record enabled, starting recording...")
                self.camera_controller.start_recording()
            
            # Log start event
            self.logger.log("Data acquisition started")
            print("[TOGGLE] Data acquisition started successfully")
            self.statusBar().showMessage("Acquisition started...")
            
            # Start dashboard graph updates
            if hasattr(self, 'graph_controller'):
                print("[TOGGLE] Starting live dashboard graph updates...")
                self.graph_controller.start_live_dashboard_update(self.start_time)
            
            # Start video recording if camera is active and recording is enabled
            if hasattr(self, 'camera_controller') and self.camera_controller.is_connected and self.settings.value("camera/record_on_start", "true", type=str).lower() == "true":
                print("[TOGGLE] Starting video recording...")
                self.camera_controller.start_recording()
                self.logger.log("Started video recording")

            # --- ADDED: Start checked automation sequences ---
            if hasattr(self, 'automation_controller'):
                print("[TOGGLE] Starting checked automation sequences...")
                self.automation_controller.start_checked_sequences()
                self.logger.log("Attempted to start checked automation sequences")

            # Update status message
            self.statusBar().showMessage("Recording started")
            print("[TOGGLE] Data acquisition started successfully")

    def update_running_text(self):
        """Update the running text with blink effect"""
        if not hasattr(self, 'sidebar_ready_status'):
            return
            
        self.blink_visible = not self.blink_visible
        
        if self.running:
            if self.blink_visible:
                self.sidebar_ready_status.setText("Running...")
                self.sidebar_ready_status.setStyleSheet("color: #2ECC40;") # Green
            else:
                self.sidebar_ready_status.setText("")
        else:
            self.sidebar_ready_status.setText("Ready")
            self.sidebar_ready_status.setStyleSheet("color: #2ECC40;") # Green

    def on_start_clicked(self):
        """Legacy handler that redirects to start_acquisition"""
        self.start_acquisition()
        
    def on_stop_clicked(self):
        """Legacy handler that redirects to stop_acquisition"""
        self.stop_acquisition()

    def toggle_theme(self):
        """Toggle between light and dark theme"""
        if self.theme == "dark":
            # Switch to light theme
            self.theme = "light"
            if hasattr(self, 'theme_switch_btn'):
                self.theme_switch_btn.setText("Switch to Dark Mode")
            # Apply light theme styling
        else:
            # Switch to dark theme
            self.theme = "dark"
            if hasattr(self, 'theme_switch_btn'):
                self.theme_switch_btn.setText("Switch to Light Mode")
            # Apply dark theme styling

    def toggle_log_visibility(self, state):
        """Toggle log panel visibility"""
        if hasattr(self, 'log_text'):
            self.log_text.setVisible(state)
            self.settings.setValue("show_log", "true" if state else "false")

    def load_settings(self):
        """Load application settings"""
        # Load from QSettings first for compatibility
        debug_mode = self.settings.value("debug_mode", "false").lower() == "true"
        show_log = self.settings.value("show_log", "true").lower() == "true"
        
        # Set the log visible or hidden
        if hasattr(self, 'log_panel'):
            self.log_panel.setVisible(show_log)
        
        # Update the theme
        self.theme = self.settings.value("theme", "dark")
        
        # Check for and load base directory from QSettings or config
        base_dir = self.settings.value("base_directory", "")
        
        # If no base directory in QSettings, check the config file
        if not base_dir and hasattr(self, 'config'):
            base_dir = self.config.get("default_project_dir", "")
        
        # If we have a valid base directory, update the UI
        if base_dir and os.path.exists(base_dir) and hasattr(self, 'project_base_dir'):
            self.project_base_dir.setText(base_dir)
            self.logger.log(f"Loaded base directory: {base_dir}")
            
            # Make sure both settings and config have this value
            self.settings.setValue("base_directory", base_dir)
            if hasattr(self, 'config'):
                self.config["default_project_dir"] = base_dir
                self.save_config()
        
        # Load other settings as usual
        # ... remaining settings loading code ...
        
        # Load the global sampling rate setting if it exists
        if hasattr(self, 'sampling_rate_spinbox'):
            # Load interval in seconds (default 1 second)
            saved_interval = float(self.settings.value("global_sampling_rate", 1.0))
            self.sampling_rate_spinbox.setValue(saved_interval)
            
            # If we have the data collection controller, update it with Hz
            if hasattr(self, 'data_collection_controller'):
                sampling_rate_hz = 1.0 / saved_interval
                self.data_collection_controller.set_sampling_rate(sampling_rate_hz)
        
        # Load previous testers if the field exists
        if hasattr(self, 'run_testers') and hasattr(self, 'config'):
            if "last_testers" in self.config:
                testers = self.config.get("last_testers", "")
                if testers:
                    self.run_testers.setText(testers)
        
        # Load sensors if the sensor controller is available
        if hasattr(self, 'sensor_controller'):
            self.sensor_controller.load_sensors()
        
        # Load application settings from settings model
        self.settings_model.load_settings()
        
        # Apply loaded settings
        if hasattr(self, 'show_log_cb'):
            self.show_log_cb.setChecked(show_log)
        if hasattr(self, 'log_text'):
            self.log_text.setVisible(show_log)
        # Log panel and theme settings have been removed

        self.load_virtual_sensors()

        # --- Inject virtual sensors into main sensor list ---
        if hasattr(self, 'sensor_controller') and hasattr(self, 'other_sensors'):
            from app.models.sensor_model import SensorModel
            existing_names = {s.name for s in self.sensor_controller.sensors}
            for vs in self.other_sensors:
                # If already a SensorModel, skip; else, create from dict
                if isinstance(vs, SensorModel):
                    if vs.name not in existing_names:
                        self.sensor_controller.sensors.append(vs)
                        existing_names.add(vs.name)
                elif isinstance(vs, dict):
                    if vs.get('name') not in existing_names:
                        sensor = SensorModel.from_dict(vs)
                        self.sensor_controller.sensors.append(sensor)
                        existing_names.add(sensor.name)
            # Update UI and dropdowns
            self.sensor_controller.update_sensor_table()

    def apply_settings(self):
        """Apply settings from UI to the application"""
        try:
            # Check if we have access to the data collection controller
            if hasattr(self, 'data_collection_controller'):
                # Apply global sampling rate from UI
                if hasattr(self, 'sampling_rate_spinbox'):
                    interval_seconds = self.sampling_rate_spinbox.value()
                    # Convert interval in seconds to rate in Hz (rate = 1/interval)
                    sampling_rate_hz = 1.0 / interval_seconds
                    self.data_collection_controller.set_sampling_rate(sampling_rate_hz)
                    # Save the interval in seconds to settings
                    self.settings.setValue("global_sampling_rate", interval_seconds)
                    self.logger.log(f"Applied sampling interval: {interval_seconds} seconds (rate: {sampling_rate_hz:.2f} Hz)")
                
                # Update Arduino settings
                if hasattr(self, 'arduino_port_combo') and hasattr(self, 'arduino_baud_combo'):
                    arduino_port = self.arduino_port_combo.currentText()
                    arduino_baud = int(self.arduino_baud_combo.currentText())
                    
                    # Connect to Arduino with the global sampling rate
                    if arduino_port and arduino_port != "Select port":
                        self.data_collection_controller.connect_arduino(arduino_port, arduino_baud)
                
                # Update LabJack settings
                if hasattr(self, 'labjack_device_combo') and hasattr(self, 'labjack_connection_combo'):
                    labjack_device = self.labjack_device_combo.currentText()
                    labjack_connection = self.labjack_connection_combo.currentText()
                    
                    # Connect to LabJack with the global sampling rate
                    if labjack_device and labjack_device != "Select device":
                        self.data_collection_controller.connect_labjack(labjack_device, labjack_connection)
                
                # Update debug mode setting for logger
                if hasattr(self, 'debug_mode_cb'):
                    debug_mode = self.debug_mode_cb.isChecked()
                    self.settings.setValue("debug_mode", "true" if debug_mode else "false")
                    self.logger.log_level = "DEBUG" if debug_mode else "INFO"
                    self.logger.log(f"Debug mode {'enabled' if debug_mode else 'disabled'}")
                        
                # Show a status message
                self.statusBar().showMessage("Settings applied successfully", 3000)
                
        except Exception as e:
            # Log the error
            self.logger.log(f"Error applying settings: {str(e)}", "ERROR")
            # Show an error message in the status bar
            self.statusBar().showMessage(f"Error: {str(e)}", 5000)
    
    def update_graph_ui_elements(self):
        """Update graph UI elements based on selected graph type"""
        # Temporary implementation - will be moved to GraphController in the future
        if hasattr(self, 'graph_type_combo') and hasattr(self, 'secondary_sensor_label'):
            graph_type = self.graph_type_combo.currentText()
            
            # Show/hide multi-sensor list based on graph type
            if hasattr(self, 'multi_sensor_group'):
                self.multi_sensor_group.setVisible(graph_type == "Standard Time Series")
            
            # Show/hide secondary sensor based on graph type
            secondary_visible = graph_type in ["Temperature Difference", "Correlation Analysis"]
            if hasattr(self, 'secondary_sensor_label'):
                self.secondary_sensor_label.setVisible(secondary_visible)
            if hasattr(self, 'graph_secondary_sensor'):
                self.graph_secondary_sensor.setVisible(secondary_visible)
            
            # Show/hide window size for moving average
            window_size_visible = graph_type == "Moving Average"
            if hasattr(self, 'window_size_label'):
                self.window_size_label.setVisible(window_size_visible)
            if hasattr(self, 'window_size_spinbox'):
                self.window_size_spinbox.setVisible(window_size_visible)
            
            # Show/hide histogram bins
            histogram_bins_visible = graph_type == "Histogram"
            if hasattr(self, 'graph_histogram_bins_label'):
                self.graph_histogram_bins_label.setVisible(histogram_bins_visible)
            if hasattr(self, 'histogram_bins_spinbox'):
                self.histogram_bins_spinbox.setVisible(histogram_bins_visible)
            
            # Box Plot specific: Hide Secondary Sensor, Window Size, Histogram Bins
            if graph_type == "Box Plot":
                if hasattr(self, 'secondary_sensor_label'): self.secondary_sensor_label.setVisible(False)
                if hasattr(self, 'graph_secondary_sensor'): self.graph_secondary_sensor.setVisible(False)
                if hasattr(self, 'window_size_label'): self.window_size_label.setVisible(False)
                if hasattr(self, 'window_size_spinbox'): self.window_size_spinbox.setVisible(False)
                if hasattr(self, 'graph_histogram_bins_label'): self.graph_histogram_bins_label.setVisible(False)
                if hasattr(self, 'histogram_bins_spinbox'): self.histogram_bins_spinbox.setVisible(False)
    
    def on_timespan_changed(self, graph_widget, is_main_graph=False):
        """Handle timespan change for graphs"""
        # Delegate to graph controller
        if is_main_graph:
            self.graph_controller.on_timespan_changed()
        else:
            self.graph_controller.on_dashboard_timespan_changed()
        
    # Camera mouse event handlers - temporary stubs that will delegate to camera controller
    def camera_mouse_press(self, event):
        """Handle mouse press events on the camera display"""
        # Forward to camera controller
        self.camera_controller.camera_mouse_press(event)
        
    def camera_mouse_release(self, event):
        """Handle mouse release events on the camera display"""
        # Forward to camera controller
        self.camera_controller.camera_mouse_release(event)
        
    def camera_mouse_move(self, event):
        """Handle mouse move events on the camera display"""
        # Forward to camera controller
        self.camera_controller.camera_mouse_move(event)

    def closeEvent(self, event: QCloseEvent):
        """Handle window close event"""
        # Cleanup and shutdown operations
        self.logger.log("Application shutting down...")
        
        # Save notes if the notes controller is available
        if hasattr(self, 'notes_controller'):
            self.notes_controller.save_note()
            self.logger.log("Saved notes before shutdown")
        
        # Save project data if the project controller is available
        if hasattr(self, 'project_controller'):
            # Save the current project and test series
            if self.project_controller.current_project:
                # Save to project metadata and project_state.json
                self.project_controller.save_project()
                self.project_controller.save_state_to_json()
                
                # Save current project and test series to config
                if hasattr(self, 'config'):
                    if self.project_controller.current_project:
                        self.config["last_project"] = self.project_controller.current_project
                    if self.project_controller.current_test_series:
                        self.config["last_test_series"] = self.project_controller.current_test_series
                
                self.logger.log(f"Saved project data for: {self.project_controller.current_project}")
        
        # Save base directory settings explicitly to ensure they're not lost
        if hasattr(self, 'project_base_dir'):
            base_dir = self.project_base_dir.text()
            if base_dir and os.path.exists(base_dir):
                # Save to both QSettings and config
                self.settings.setValue("base_directory", base_dir)
                self.settings.sync()  # Force settings to disk
                
                if hasattr(self, 'config'):
                    self.config["default_project_dir"] = base_dir
                    save_config(self.config)  # Direct call to save_config function
        
        # Shutdown controllers
        if hasattr(self, 'data_collection_controller'):
            self.data_collection_controller.shutdown()
        
        if hasattr(self, 'camera_controller') and self.camera_controller:
            self.camera_controller.close_camera()
            
        # Save any unsaved settings
        self.save_settings()
        
        # Log application shutdown
        self.logger.log("Application shutdown complete")
        event.accept()
        
        self.save_virtual_sensors()
        
    def save_settings(self):
        """Save application settings"""
        if hasattr(self, 'settings_model'):
            self.settings_model.save_settings()
            self.logger.log("Settings saved")
        else:
            self.logger.log("Settings model not available to save settings", "WARN")
            
        # Save project state if project controller exists
        if hasattr(self, 'project_controller'):
            self.save_project_state()
            
        # Save configuration
        if hasattr(self, 'config'):
            self.save_config()

    # Camera-related methods
    def connect_camera(self):
        """Connect to a camera"""
        if not hasattr(self, 'camera_controller'):
            return
            
        # Forward to the controller
        if self.camera_connect_btn.text() == "Connect":
            # Get settings from the camera tab
            camera_id = self.camera_id.currentIndex()
            
            # Get resolution and framerate from settings instead of UI elements (which were removed)
            resolution = self.settings.value("camera/resolution", "1280x720")
            fps = int(self.settings.value("camera/fps", "30"))
            
            # Update the settings values
            self.settings.setValue("camera/default_camera", str(camera_id))
            # Resolution and framerate are already set via the settings popup
            
            # Connect to the camera
            self.camera_controller.toggle_camera()
            
            # Apply focus and exposure settings after connection
            if self.camera_controller.is_connected:
                self.apply_camera_focus_exposure()
        else:
            # Disconnect the camera using the force_disconnect method for reliability
            print("Using force_disconnect for more reliable camera disconnection")
            self.camera_controller.force_disconnect()
        
    def take_snapshot(self):
        """Take a camera snapshot"""
        self.camera_controller.take_snapshot()
        
    def toggle_recording(self):
        """Start or stop video recording"""
        self.camera_controller.toggle_recording()
        
    def add_overlay(self):
        """Add a new overlay to the camera feed"""
        self.camera_controller.add_overlay()
        
    def apply_overlay_settings(self):
        """Apply settings to the selected overlay"""
        self.camera_controller.apply_overlay_settings()
        
    def remove_overlay(self):
        """Remove the selected overlay"""
        self.camera_controller.remove_overlay()
        
    def choose_text_color(self):
        """Choose text color for overlay"""
        self.camera_controller.choose_text_color()
        
    def choose_bg_color(self):
        """Choose background color for overlay"""
        self.camera_controller.choose_bg_color()
        
    def apply_camera_settings(self):
        """Apply camera settings"""
        self.camera_controller.apply_camera_settings()
    
    # Sensor-related methods
    def add_sensor(self):
        """Show the add sensor dialog"""
        try:
            print("add_sensor method in main_window called")
            if hasattr(self, 'sensor_controller') and self.sensor_controller:
                print("Calling sensor_controller.add_sensor()")
                # Call the controller method
                success = self.sensor_controller.add_sensor()
                
                if not success:
                    print("SensorController.add_sensor() returned False, falling back to show_add_sensor_dialog")
                    # As a fallback, try to show the dialog directly
                    if hasattr(self, 'show_add_sensor_dialog'):
                        self.show_add_sensor_dialog()
            else:
                print("Error: sensor_controller not found")
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", "Sensor controller not available")
        except Exception as e:
            print(f"Error in add_sensor: {e}")
            import traceback
            traceback.print_exc()
    
    def edit_sensor(self):
        """Edit the selected sensor"""
        try:
            print("edit_sensor method in main_window called")
            if hasattr(self, 'sensor_controller') and self.sensor_controller:
                print("Calling sensor_controller.edit_sensor()")
                # Call the controller method
                self.sensor_controller.edit_sensor()
            else:
                print("Error: sensor_controller not found")
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", "Sensor controller not available")
        except Exception as e:
            print(f"Error in edit_sensor: {e}")
            import traceback
            traceback.print_exc()
    
    def remove_sensor(self):
        """Remove the selected sensor"""
        self.sensor_controller.remove_sensor()
    
    # Arduino-related methods
    def detect_arduino(self):
        """Detect available Arduino ports"""
        if not hasattr(self, 'data_collection_controller'):
            self.logger.log("Data collection controller not initialized", "ERROR")
            return
            
        # Get available Arduino ports
        available_ports = self.data_collection_controller.get_arduino_ports()
        
        if not available_ports:
            QMessageBox.information(self, "Arduino Detection", "No Arduino devices found.")
            return
            
        # Clear the port combobox
        self.arduino_port.clear()
        
        # Add available ports
        for port in available_ports:
            self.arduino_port.addItem(port)
            
        # Select the first port
        if len(available_ports) > 0:
            self.arduino_port.setCurrentText(available_ports[0])
            
        self.logger.log(f"Found {len(available_ports)} Arduino ports: {', '.join(available_ports)}")
        QMessageBox.information(self, "Arduino Detection", 
                               f"Found {len(available_ports)} Arduino port(s):\n{', '.join(available_ports)}")
        
    def connect_arduino(self):
        """Connect to Arduino"""
        if not hasattr(self, 'data_collection_controller'):
            self.logger.log("Data collection controller not initialized", "ERROR")
            return
            
        # Get Arduino settings from UI
        port = self.arduino_port.currentText()
        baud_rate = int(self.arduino_baud.currentText())
        poll_interval = self.arduino_poll_interval.value()
        
        # Check if already connected
        if 'arduino' in self.data_collection_controller.interfaces and \
           self.data_collection_controller.interfaces['arduino']['connected']:
            # Disconnect
            self.data_collection_controller.disconnect_arduino()
            self.update_arduino_connected_status(False)
            return
            
        # Connect to Arduino
        success = self.data_collection_controller.connect_arduino(port, baud_rate, poll_interval)
        
        # Update UI based on connection result
        if success:
            # Save settings
            self.settings.setValue("arduino_port", port)
            self.settings.setValue("arduino_baud", baud_rate)
            self.settings.setValue("arduino_poll_interval", poll_interval)
            self.update_arduino_connected_status(True)
        else:
            QMessageBox.warning(self, "Arduino Connection", 
                               "Failed to connect to Arduino. Check the port and settings.")
            self.update_arduino_connected_status(False)
    
    def test_arduino(self):
        """Test Arduino connection - Deprecated, kept for backwards compatibility"""
        pass
    
    def update_command_ui(self):
        """Update the command UI based on selected command type"""
        if not hasattr(self, 'arduino_command_type') or not hasattr(self, 'arduino_custom_command'):
            return
            
        # Get the selected command type
        command_type = self.arduino_command_type.currentText()
        
        # Show/hide custom command field based on selected type
        if command_type == "CUSTOM":
            self.arduino_custom_command_label.setVisible(True)
            self.arduino_custom_command.setVisible(True)
            
            # Disable normal fields
            self.arduino_device_id.setEnabled(False)
            self.arduino_command_value.setEnabled(False)
        else:
            self.arduino_custom_command_label.setVisible(False)
            self.arduino_custom_command.setVisible(False)
            
            # Enable normal fields
            self.arduino_device_id.setEnabled(True)
            self.arduino_command_value.setEnabled(True)
            
            # Set default values based on command type
            if command_type == "LED" or command_type == "RELAY":
                self.arduino_command_value.setText("ON")
            elif command_type == "MOTOR":
                self.arduino_command_value.setText("100")
            elif command_type == "SERVO":
                self.arduino_command_value.setText("90")
    
    def send_arduino_command(self):
        """Send command to Arduino from the UI"""
        if not hasattr(self, 'data_collection_controller'):
            self.logger.log("Data collection controller not initialized", "ERROR")
            return
            
        # Check if Arduino is connected
        if 'arduino' not in self.data_collection_controller.interfaces or \
           not self.data_collection_controller.interfaces['arduino']['connected']:
            QMessageBox.warning(self, "Arduino Command", "Arduino is not connected")
            return
            
        try:
            # Get the command parameters from the UI
            command_type = self.arduino_command_type.currentText()
            
            if command_type == "CUSTOM":
                # Send custom command directly
                custom_cmd = self.arduino_custom_command.text().strip()
                if not custom_cmd:
                    QMessageBox.warning(self, "Arduino Command", "Please enter a custom command")
                    return
                    
                # Parse the custom command
                cmd_parts = custom_cmd.split(':')
                if len(cmd_parts) == 1:
                    # Command only
                    success = self.data_collection_controller.send_arduino_command(cmd_parts[0])
                elif len(cmd_parts) == 2:
                    # Command and device/value
                    cmd = cmd_parts[0]
                    
                    # Check if there's a value
                    if '=' in cmd_parts[1]:
                        dev_val = cmd_parts[1].split('=')
                        device = dev_val[0]
                        value = dev_val[1].rstrip(';')
                        success = self.data_collection_controller.send_arduino_command(cmd, device, value)
                    else:
                        # Just command and device
                        device = cmd_parts[1].rstrip(';')
                        success = self.data_collection_controller.send_arduino_command(cmd, device)
                else:
                    QMessageBox.warning(self, "Arduino Command", "Invalid custom command format")
                    return
            else:
                # Use structured command
                device_id = self.arduino_device_id.text().strip()
                value = self.arduino_command_value.text().strip()
                
                # Send through the controller
                success = self.data_collection_controller.control_device(command_type, device_id, value)
                
            # Show result
            if success:
                self.statusBar().showMessage("Command sent successfully", 2000)
            else:
                QMessageBox.warning(self, "Arduino Command", "Failed to send command")
                
        except Exception as e:
            self.logger.log(f"Error sending Arduino command: {str(e)}", "ERROR")
            QMessageBox.warning(self, "Arduino Command", f"Error: {str(e)}")
    
    # LabJack-related methods
    def connect_labjack(self):
        """Connect to the LabJack T7 Pro device"""
        try:
            # Get the device connection parameter
            device_identifier = self.device_identifier_combobox.currentText().strip()
            
            # Connect to the LabJack device
            self.sensor_controller.connect_labjack(device_identifier)
            
            # Update device info fields
            device_info = {}
            device_info["serial"] = self.sensor_controller.get_labjack_info("serial", "Unknown")
            device_info["name"] = self.sensor_controller.get_labjack_info("name", "Unknown")
            device_info["firmware"] = self.sensor_controller.get_labjack_info("firmware", "Unknown")
            device_info["hardware"] = self.sensor_controller.get_labjack_info("hardware", "Unknown")
            
            # Force update status in all UI places
            self.sensor_controller.force_update_labjack_status()
            
            # Update the button and connection status UI
            self.labjack_connect_button.setText("Disconnect")
            self.labjack_connect_button.setStyleSheet("color: green; font-weight: bold;")
            self.update_device_connection_status_ui('labjack', True)
            
            # Show a message to the user
            self.show_status_message(f"LabJack {device_info['name']} connected successfully", "success")
            
            # Refresh the UI to ensure everything is updated
            QApplication.processEvents()
            
            return True
        except Exception as e:
            self.show_status_message(f"Failed to connect to LabJack: {str(e)}", "error")
            return False
    
    def test_labjack(self):
        """Test LabJack connection"""
        self.sensor_controller.test_labjack()
    
    # Graph-related methods
    def update_graph(self):
        """Update the main analysis graph based on UI selections."""
        if hasattr(self, 'logger'):
            self.logger.debug("Gathering parameters to update main graph")

        if not hasattr(self, 'graph_controller') or not hasattr(self, 'graph_widget') or not hasattr(self, 'sensor_controller'):
            if hasattr(self, 'logger'):
                self.logger.error("Graph controller, graph widget, or sensor controller not initialized.")
            return
            
        # Ensure UI elements exist before accessing them
        required_attrs = [
            'graph_type_combo', 'graph_primary_sensor', 'graph_secondary_sensor', 
            'graph_timespan', 'multi_sensor_list', 'window_size_spinbox', 
            'histogram_bins_spinbox'
        ]
        for attr in required_attrs:
            if not hasattr(self, attr):
                if hasattr(self, 'logger'):
                    self.logger.error(f"Graph UI element '{attr}' not found in main window.")
                return

        # Get parameters from UI
        graph_type = self.graph_type_combo.currentText()
        # Get the HISTORICAL KEY from the selected item's userData
        primary_sensor_key = self.graph_primary_sensor.currentData() 
        secondary_sensor_key = self.graph_secondary_sensor.currentData() if self.graph_secondary_sensor.isVisible() else None
        timespan = self.graph_timespan.currentText()
        
        # Get list of selected additional sensor HISTORICAL KEYS from multi_sensor_list userData
        multi_sensor_keys = []
        if self.multi_sensor_list.isVisible():
            selected_items = self.multi_sensor_list.selectedItems()
            multi_sensor_keys = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items if item.data(Qt.ItemDataRole.UserRole) is not None]

        # Get specific parameters based on graph type
        window_size = self.window_size_spinbox.value() if self.window_size_spinbox.isVisible() else None
        histogram_bins = self.histogram_bins_spinbox.value() if self.histogram_bins_spinbox.isVisible() else None
        
        # Log the keys being sent
        if hasattr(self, 'logger'):
             self.logger.debug(f"Calling update_specific_graph with: type={graph_type}, primary_key={primary_sensor_key}, secondary_key={secondary_sensor_key}, multi_keys={multi_sensor_keys}, timespan={timespan}")

        # Delegate plotting to the GraphController using historical keys
        self.graph_controller.update_specific_graph(
            graph_widget=self.graph_widget, 
            primary_sensor_key=primary_sensor_key, # Pass key
            secondary_sensor_key=secondary_sensor_key, # Pass key
            timespan=timespan, 
            graph_type=graph_type, 
            multi_sensor_keys=multi_sensor_keys, # Pass keys
            window_size=window_size,
            histogram_bins=histogram_bins,
            is_main_graph=True # Indicate this is for the main analysis graph
        )

    def update_dashboard_graph(self):
        """Update the dashboard graph"""
        self.graph_controller.update_dashboard_graph()
        
    def update_sensor_values(self, data):
        """Update sensor values with data received from hardware interfaces"""
        if not data or not hasattr(self, 'sensor_controller'):
            return
            
        # Forward to sensor controller to update sensor data
        self.sensor_controller.update_sensor_data(data)
        
        # Also update the automation context if we have both controllers
        if hasattr(self, 'sensor_controller') and hasattr(self, 'automation_controller'):
            self.sensor_controller.update_automation_context()

    def apply_plot_formatting(self):
        """Apply formatting to plots"""
        self.graph_controller.apply_plot_formatting()

    # Motion detection methods
    def handle_motion_detection_state(self, state):
        """Handle motion detection state changes"""
        # Store motion detection state
        self.motion_detection_enabled = state
        
        # If camera controller exists, notify it
        if hasattr(self, 'camera_controller') and self.camera_controller is not None:
            self.camera_controller.handle_motion_detection_state(state)
        
        # Enable/disable motion detection controls (do this regardless of controller)
        if hasattr(self, 'motion_detection_sensitivity'):
            self.motion_detection_sensitivity.setEnabled(state)
            
        if hasattr(self, 'motion_detection_min_area'):
            self.motion_detection_min_area.setEnabled(state)

    # NDI methods
    def init_ndi(self):
        """Initialize NDI streaming"""
        self.camera_controller.init_ndi()
        
    def browse_ffmpeg_path(self):
        """Open file dialog to browse for FFmpeg executable"""
        file_filter = "Executable files (*.exe);;All files (*)" if sys.platform == "win32" else "All files (*)"
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select FFmpeg Executable", "", file_filter
        )
        
        if file_path:
            # Update the text field with the selected path
            self.ffmpeg_binary_path.setText(file_path)
            
            # Save to settings
            self.settings.setValue("ffmpeg_binary", file_path)
            
            # Log the change
            self.logger.log(f"FFmpeg path set to: {file_path}")
            
            # Show a confirmation message
            QMessageBox.information(
                self, 
                "FFmpeg Path Updated", 
                f"FFmpeg path set to:\n{file_path}\n\nThis will be used for all future video encoding."
            ) 

    def resizeEvent(self, event):
        """Handle window resize events"""
        super().resizeEvent(event)
        # Update status bar with new window size
        # self.statusBar().showMessage(f"Window size: {self.width()} x {self.height()}")
        
    # Add methods for JSON persistence
    def save_project_state(self):
        """Saves the current project/test/run details to project_state.json in the project dir."""
        # Delegate to project controller
        if hasattr(self, 'project_controller'):
            self.project_controller.save_state_to_json()
        else:
            self.logger.log("Project controller not available to save state.", "WARN")

    def load_project_state(self, project_path):
        """Loads project/test/run details from project_state.json for the given project path."""
        # Delegate to project controller
        if hasattr(self, 'project_controller'):
            self.project_controller.load_state_from_json(project_path)
            self.update_status_indicators() # Update status after loading
        else:
            self.logger.log("Project controller not available to load state.", "WARN")
        
    def save_config(self):
        """Save the application configuration"""
        try:
            # Save to config.json
            save_config(self.config)
            
            # Ensure that the base directory is correctly saved in both storage locations
            if hasattr(self, 'project_base_dir'):
                base_dir = self.project_base_dir.text()
                if base_dir and os.path.exists(base_dir):
                    # Save to QSettings
                    self.settings.setValue("base_directory", base_dir)
                    self.settings.sync()  # Force sync to disk
                    
                    # Make sure config has it too
                    self.config["default_project_dir"] = base_dir
                    
                    # Log the save
                    self.logger.log(f"Saved base directory to config: {base_dir}")
    
        except Exception as e:
            self.logger.log(f"Error saving config: {str(e)}", "ERROR")
            import traceback
            traceback.print_exc()
        
    def update_project_group_box_colors(self):
        """Update the group box border colors based on form completion
        - Orange: Default/Incomplete
        - Green: Complete with valid data
        """
        # Get relevant data
        base_dir = self.project_base_dir.text().strip()
        project_name = self.project_selector.currentText().strip()
        series_name = self.test_series_selector.currentText().strip()
        run_description = self.run_description.toPlainText().strip()
        run_testers = self.run_testers.text().strip()
        
        # Default style is orange
        default_style = "QGroupBox { border: 2px solid #FFA500; border-radius: 5px; padding-top: 15px; margin-top: 10px; }"
        complete_style = "QGroupBox { border: 2px solid #4CAF50; border-radius: 5px; padding-top: 15px; margin-top: 10px; }"
        
        # Check project group box completion - only if the attribute exists
        if hasattr(self, 'project_group'):
            if base_dir and os.path.exists(base_dir) and project_name:
                self.project_group.setStyleSheet(complete_style)
            else:
                self.project_group.setStyleSheet(default_style)
            
        # Check test series group box completion - only if the attribute exists
        if hasattr(self, 'test_series_group'):
            if series_name:
                self.test_series_group.setStyleSheet(complete_style)
            else:
                self.test_series_group.setStyleSheet(default_style)
            
        # Check run group box completion - only if the attribute exists
        if hasattr(self, 'run_group'):
            # Show green only if both description and testers are filled
            if run_description and run_testers:
                self.run_group.setStyleSheet(complete_style)
            else:
                self.run_group.setStyleSheet(default_style)
                
            # Don't change the background color of individual fields
            # to avoid confusing users with red backgrounds

    def init_controllers(self):
        """Initialize all application controllers"""
        self.logger.log("Initializing controllers...", "INFO")
        
        # Initialize Project Controller
        self.project_controller = ProjectController(self)
        
        # Initialize Settings Model (already done in __init__, but ensure it's accessible)
        # self.settings_model = SettingsModel(self.settings)
        
        # Initialize Sensor Controller
        self.sensor_controller = SensorController(self, self.settings_model)

        # Initialize Camera Controller
        # Make sure to pass the settings model
        self.camera_controller = CameraController(self, self.settings_model, self.project_controller) # Pass project_controller

        # Initialize Graph Controller
        self.graph_controller = GraphController(self, self.sensor_controller, self.settings_model) # Pass settings model

        # Initialize Automation Controller
        self.automation_controller = AutomationController(self, self.config)

        # Initialize Data Collection Controller
        self.data_collection_controller = DataCollectionController(self)

        # Initialize Export Controller
        self.export_controller = ExportController(self, self.settings_model)
        
        # Initialize Notes Controller
        self.notes_controller = NotesController(self)

        # Initialize the data collection controller to set up timers
        self.data_collection_controller.initialize()

        # Setup the sensor tab UI components
        self.setup_sensor_tab()

        # Log initialization
        self.logger.log("Controllers initialized successfully", "INFO")

    def connect_controller_signals(self):
        """Connect controller-specific signals"""
        # Connect data collection signals if available
        if hasattr(self, 'data_collection_controller'):
            # Connect data received signal to update sensor values
            self.data_collection_controller.data_received_signal.connect(
                self.update_sensor_values)
            
            # Connect status update signal to logger
            self.data_collection_controller.status_update_signal.connect(
                lambda msg, level: self.logger.log(msg, level))
            
            # Connect combined data signal to graph controller for synchronized updates
            if hasattr(self, 'graph_controller'):
                # Disconnect the old signal if it was connected
                try:
                    self.data_collection_controller.data_received_signal.disconnect(
                        self.graph_controller.plot_new_data)
                except:
                    # If it wasn't connected, just proceed
                    pass
                    
                # Connect the combined data signal for synchronized graph updates
                self.data_collection_controller.combined_data_signal.connect(
                    self.graph_controller.plot_new_data)
                self.logger.log("Connected combined data signal to graph controller for synchronized updates", "INFO")
        
        # Connect sensor controller signals
        if hasattr(self, 'sensor_controller'):
            # Connect status change signal
            self.sensor_controller.status_changed.connect(self.update_status_indicators)
            
            # DO NOT connect buttons directly here - this creates conflicts
            # Buttons are connected properly in setup_sensor_tab_signals() 
            # These direct connections can cause conflicts
            # Instead, setup_sensor_tab_signals connects the buttons to main window methods
            # which then call the controller methods

        # Connect automation controller signals
        if hasattr(self, 'automation_controller'):
            # Connect status change signal
            self.automation_controller.status_changed.connect(self.update_status_indicators)
            # Connect UI buttons to controller methods


    def handle_interface_status(self, interface_type, is_connected):
        """Handle interface status updates
        
        Args:
            interface_type (str): Type of interface ('arduino', 'labjack', 'other')
            is_connected (bool): Whether the interface is connected
        """
        # Debug
        print(f"handle_interface_status: {interface_type} is_connected={is_connected}")
        
        # Update device connection status in UI
        self.update_device_connection_status_ui(interface_type, is_connected)

    def update_device_connection_status_ui(self, device_type, is_connected):
        """Update the connection status UI indicators for a specific device type
        
        Args:
            device_type (str): Type of device ('arduino', 'labjack', 'other', etc.)
            is_connected (bool): Whether the device is connected
        """
        print(f"update_device_connection_status_ui: type={device_type}, connected={is_connected}")
        
        # Update the corresponding method based on device type
        if device_type.lower() == 'arduino':
            self.update_arduino_connected_status(is_connected)
        elif device_type.lower() == 'labjack':
            self.update_labjack_connected_status(is_connected)
        elif device_type.lower() == 'other':
            # Directly call our specialized other sensors method
            self.update_other_connected_status(is_connected)
        else:
            print(f"Warning: Unknown device type: {device_type}")
            
        # Also update the interfaces dictionary directly to ensure consistency
        if hasattr(self, 'data_collection_controller') and hasattr(self.data_collection_controller, 'interfaces'):
            if device_type.lower() == 'arduino' and 'arduino' in self.data_collection_controller.interfaces:
                if isinstance(self.data_collection_controller.interfaces['arduino'], dict):
                    self.data_collection_controller.interfaces['arduino']['connected'] = is_connected
                    print(f"DEBUG: Directly updated 'arduino' connected status to {is_connected} in interfaces dict")
            elif device_type.lower() == 'labjack' and 'labjack' in self.data_collection_controller.interfaces:
                if isinstance(self.data_collection_controller.interfaces['labjack'], dict):
                    self.data_collection_controller.interfaces['labjack']['connected'] = is_connected
                    print(f"DEBUG: Directly updated 'labjack' connected status to {is_connected} in interfaces dict")
            elif device_type.lower() == 'other' and 'other_serial' in self.data_collection_controller.interfaces:
                if isinstance(self.data_collection_controller.interfaces['other_serial'], dict):
                    self.data_collection_controller.interfaces['other_serial']['connected'] = is_connected
                    print(f"DEBUG: Directly updated 'other_serial' connected status to {is_connected} in interfaces dict")
                    
        # If we have an "other" device, also update the data collection controller's state directly
        if device_type.lower() == 'other' and hasattr(self, 'data_collection_controller'):
            if 'other_serial' not in self.data_collection_controller.interfaces:
                self.data_collection_controller.interfaces['other_serial'] = {'connected': is_connected, 'type': 'other_serial'}
                print(f"DEBUG: Created 'other_serial' entry with connected={is_connected} in interfaces dict")
        
        # Force application to process events immediately
        from PyQt6.QtCore import QCoreApplication
        QCoreApplication.processEvents()

    def update_other_connected_status(self, is_connected):
        """Update the Other Sensors connection status display
        
        Args:
            is_connected (bool): Whether Other Sensors are connected
        """
        print(f"Direct Other Sensors status update: is_connected={is_connected}")
        
        # Set the text and color directly on the other_status label if it exists
        if hasattr(self, 'other_status'):
            status_text = "Connected" if is_connected else "Not connected"
            status_color = "green" if is_connected else "grey"
            print(f"Directly updating other_status label to '{status_text}' with color '{status_color}'")
            self.other_status.setText(status_text)
            self.other_status.setStyleSheet(f"color: {status_color}; font-weight: bold; font-size: 14px;")
            self.other_status.repaint()
        
        # Force application to process events immediately
        from PyQt6.QtCore import QCoreApplication
        QCoreApplication.processEvents()
        
        # Log the status change
        status_str = "connected" if is_connected else "disconnected"
        if hasattr(self, 'logger'):
            self.logger.log(f"Other Sensors {status_str}", "INFO")

    def init_device_status(self):
        """Initialize device status indicators in the UI"""
        try:
            # Arduino status
            self.arduino_status_indicator = QLabel()
            self.arduino_status_indicator.setFixedSize(16, 16)
            self.arduino_status_indicator.setStyleSheet("background-color: #F44336; border-radius: 8px;")
            self.arduino_status_indicator.setToolTip("Arduino Connection Status")
            
            self.arduino_status_label = QLabel("Disconnected")
            self.arduino_status_label.setStyleSheet("color: #F44336;")
            
            # LabJack status
            self.labjack_status_indicator = QLabel()
            self.labjack_status_indicator.setFixedSize(16, 16)
            self.labjack_status_indicator.setStyleSheet("background-color: #F44336; border-radius: 8px;")
            self.labjack_status_indicator.setToolTip("LabJack Connection Status")
            
            self.labjack_status_label = QLabel("Disconnected")
            self.labjack_status_label.setStyleSheet("color: #F44336;")
            
            # Other Serial Devices status
            self.other_status_indicator = QLabel()
            self.other_status_indicator.setFixedSize(16, 16)
            self.other_status_indicator.setStyleSheet("background-color: #F44336; border-radius: 8px;")
            self.other_status_indicator.setToolTip("Other Serial Devices Connection Status")
            
            self.other_status_label = QLabel("Disconnected")
            self.other_status_label.setStyleSheet("color: #F44336;")
            
            print("Device status indicators successfully initialized")
        except Exception as e:
            print(f"Error initializing device status indicators: {e}")

    def update_arduino_connected_status(self, is_connected):
        """Update the Arduino connection status display
        
        Args:
            is_connected (bool): Whether the Arduino is connected
        """
        print(f"Direct Arduino status update: is_connected={is_connected}")
        
        # First try to update the button if it exists
        if hasattr(self, 'arduino_connect_btn'):
            self.arduino_connect_btn.setText("Disconnect" if is_connected else "Connect")
            
            # Apply appropriate button style
            if is_connected:
                # Red border for disconnect button
                red_border_style = """
                    QPushButton {
                        background-color: transparent;
                        color: #F44336;
                        border: 2px solid #F44336;
                        padding: 6px 12px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: rgba(244, 67, 54, 0.1);
                    }
                    QPushButton:pressed {
                        background-color: rgba(244, 67, 54, 0.2);
                    }
                """
                self.arduino_connect_btn.setStyleSheet(red_border_style)
            else:
                # Green border for connect button
                green_border_style = """
                    QPushButton {
                        background-color: transparent;
                        color: #4CAF50;
                        border: 2px solid #4CAF50;
                        padding: 6px 12px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: rgba(76, 175, 80, 0.1);
                    }
                    QPushButton:pressed {
                        background-color: rgba(76, 175, 80, 0.2);
                    }
                """
                self.arduino_connect_btn.setStyleSheet(green_border_style)
            
            self.arduino_connect_btn.repaint()
        
        # Set the text and color directly on the arduino_status label if it exists
        if hasattr(self, 'arduino_status'):
            status_text = "Connected" if is_connected else "Not connected"
            status_color = "green" if is_connected else "grey"
            print(f"Directly updating arduino_status label to '{status_text}' with color '{status_color}'")
            self.arduino_status.setText(status_text)
            self.arduino_status.setStyleSheet(f"color: {status_color}; font-weight: bold; font-size: 14px;")
            self.arduino_status.repaint()
        
        # Force application to process events immediately
        from PyQt6.QtCore import QCoreApplication
        QCoreApplication.processEvents()
        
        # Log the status change
        status_str = "connected" if is_connected else "disconnected"
        if hasattr(self, 'logger'):
            self.logger.log(f"Arduino {status_str}", "INFO")

    def show_arduino_settings_popup(self):
        """Show Arduino settings in a popup dialog"""
        print("=== Opening Arduino Settings Popup Dialog ===")
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QGridLayout, QLabel, QComboBox, QDoubleSpinBox, QPushButton, QGroupBox, QLineEdit, QHBoxLayout, QCheckBox, QTextEdit
        from PyQt6.QtCore import Qt
        
        # Create dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Arduino Settings")
        dialog.setMinimumWidth(350)
        dialog.setMinimumHeight(400)
        
        # Main layout
        layout = QVBoxLayout(dialog)
        
        # Create a group box for Arduino settings
        arduino_group = QGroupBox("Arduino Settings")
        arduino_layout = QGridLayout(arduino_group)
        
        # Arduino Port
        arduino_layout.addWidget(QLabel("Port:"), 0, 0)
        port_combo = QComboBox()
        port_combo.setEditable(True)
        
        # Use the same port as in the main window
        if hasattr(self, 'arduino_port'):
            current_port = self.arduino_port.currentText()
            port_combo.addItem(current_port)
        else:
            port_combo.addItem(self.settings.value("arduino_port", "COM3"))
            
        arduino_layout.addWidget(port_combo, 0, 1)
        
        # Auto-detect button
        detect_btn = QPushButton("Auto Detect")
        arduino_layout.addWidget(detect_btn, 0, 2)
        
        # Baud Rate
        arduino_layout.addWidget(QLabel("Baud Rate:"), 1, 0)
        baud_combo = QComboBox()
        baud_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        
        # Use the same baud rate as in the main window
        if hasattr(self, 'arduino_baud'):
            baud_combo.setCurrentText(self.arduino_baud.currentText())
        else:
            baud_combo.setCurrentText(str(self.settings.value("arduino_baud", "9600")))
            
        arduino_layout.addWidget(baud_combo, 1, 1)
        
        # Note: Poll interval removed as it's controlled by the global sampling rate
        
        # Auto-connect at program start checkbox
        auto_connect_checkbox = QCheckBox("Auto-connect at program start")
        auto_connect_checkbox.setChecked(self.settings.value("arduino_auto_connect", "false") == "true")
        arduino_layout.addWidget(auto_connect_checkbox, 2, 0, 1, 3)
        
        # Arduino connect button
        buttons_layout = QHBoxLayout()
        connect_btn = QPushButton("Connect")
        
        # Apply green border style
        green_border_style = """
            QPushButton {
                background-color: transparent;
                color: #4CAF50;
                border: 2px solid #4CAF50;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(76, 175, 80, 0.1);
            }
            QPushButton:pressed {
                background-color: rgba(76, 175, 80, 0.2);
            }
        """
        
        # Add red border style for disconnect button
        red_border_style = """
            QPushButton {
                background-color: transparent;
                color: #F44336;
                border: 2px solid #F44336;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(244, 67, 54, 0.1);
            }
            QPushButton:pressed {
                background-color: rgba(244, 67, 54, 0.2);
            }
        """
        
        connect_btn.setStyleSheet(green_border_style)
        
        # If we're already connected, change the button text and style
        if hasattr(self, 'data_collection_controller') and \
           'arduino' in self.data_collection_controller.interfaces and \
           self.data_collection_controller.interfaces['arduino']['connected']:
            connect_btn.setText("Disconnect")
            connect_btn.setStyleSheet(red_border_style)
        
        buttons_layout.addWidget(connect_btn)
        arduino_layout.addLayout(buttons_layout, 3, 0, 1, 3)
        
        # Connect detect button - DO NOT connect to self.detect_arduino to avoid duplicates
        def detect_arduino_ports():
            if not hasattr(self, 'data_collection_controller'):
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(dialog, "Arduino Detection", "Data collection controller not initialized")
                return
                
            # Get available Arduino ports
            available_ports = self.data_collection_controller.get_arduino_ports()
            
            # Clear the port combobox
            port_combo.clear()
            
            if not available_ports:
                port_combo.addItem("No ports found")
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(dialog, "Arduino Detection", "No Arduino devices found.")
                return
                
            # Add available ports
            for port in available_ports:
                port_combo.addItem(port)
                
            # Select the first port
            if len(available_ports) > 0:
                port_combo.setCurrentText(available_ports[0])
                
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(dialog, "Arduino Detection", 
                                   f"Found {len(available_ports)} Arduino port(s):\n{', '.join(available_ports)}")
        
        # ONLY connect to local function, not to self.detect_arduino
        detect_btn.clicked.connect(detect_arduino_ports)
        
        # Connect connect button
        def connect_arduino():
            if not hasattr(self, 'data_collection_controller'):
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(dialog, "Arduino Connection", "Data collection controller not initialized")
                return
                
            # Get Arduino settings from the dialog
            port = port_combo.currentText()
            baud_rate = int(baud_combo.currentText())
            
            # Check if already connected
            is_connected = False
            if 'arduino' in self.data_collection_controller.interfaces and \
               self.data_collection_controller.interfaces['arduino']['connected']:
                is_connected = True
                
            if is_connected:
                # Disconnect
                self.data_collection_controller.disconnect_arduino()
                connect_btn.setText("Connect")
                connect_btn.setStyleSheet(green_border_style)
                self.update_arduino_connected_status(False)
                return
            
            # Make sure the global sampling rate is set from the sampling_rate_spinbox
            if hasattr(self, 'sampling_rate_spinbox'):
                sampling_rate = self.sampling_rate_spinbox.value()
                self.data_collection_controller.set_sampling_rate(sampling_rate)
                self.logger.log(f"Applied global sampling rate before connecting Arduino: {sampling_rate} Hz")
            
            # Connect to Arduino using global sampling rate
            success = self.data_collection_controller.connect_arduino(port, baud_rate)
            
            # Update UI based on connection result
            if success:
                connect_btn.setText("Disconnect")
                connect_btn.setStyleSheet(red_border_style)
                # Save settings
                self.settings.setValue("arduino_port", port)
                self.settings.setValue("arduino_baud", baud_rate)
                self.settings.setValue("arduino_auto_connect", "true" if auto_connect_checkbox.isChecked() else "false")
                
                # Update main window UI with values from the dialog
                if hasattr(self, 'arduino_port'):
                    self.arduino_port.setCurrentText(port)
                if hasattr(self, 'arduino_baud'):
                    self.arduino_baud.setCurrentText(str(baud_rate))
            else:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(dialog, "Arduino Connection", 
                                  "Failed to connect to Arduino. Check the port and settings.")
                self.update_arduino_connected_status(False)
        
        connect_btn.clicked.connect(connect_arduino)
        
        # Add Arduino group to main layout FIRST
        layout.addWidget(arduino_group)
        
        # --- HOW-TO BOX AND EXAMPLES (Placed AFTER Arduino settings) ---
        howto_text = (
            '<b>How to use Arduino with EvoLabs DAQ:</b><br>'
            '<ul>'
            '<li>Upload the provided Arduino example code to your Arduino board.</li>'
            '<li>Connect the Arduino to your PC via USB and select the correct port and baud rate.</li>'
            '<li>The Arduino code must:</li>'
            '<ul>'
            '<li>Send sensor data to the PC via Serial (e.g., <code>Serial.println()</code>).</li>'
            '<li>Respond to commands from the PC (e.g., via <code>Serial.readStringUntil()</code>).</li>'
            '<li>Optionally, communicate with other Arduinos via I2C if using master/slave setup.</li>'
            '</ul>'
            '<li>See the example codes for a template you can adapt for your sensors.</li>'
            '</ul>'
            '<b>Example code files:</b> <br>'
            '1. <code>Arduino_Master.ino</code>: Master device, reads sensors, sends data to PC.<br>'
            '2. <code>Arduino_Slave_with_K-Type.ino</code>: Slave device, reads K-Type thermocouple, responds to I2C requests.'
        )
        howto_box = QTextEdit()
        howto_box.setReadOnly(True)
        howto_box.setHtml(howto_text)
        howto_box.setMinimumHeight(170)
        layout.addWidget(howto_box) # Use addWidget instead of insertWidget

        # --- BUTTONS TO VIEW EXAMPLES (Placed AFTER HowTo box) ---
        def show_code_dialog(title, file_path):
            code_dialog = QDialog(dialog)
            code_dialog.setWindowTitle(title)
            code_dialog.setMinimumSize(700, 500)
            vbox = QVBoxLayout(code_dialog)
            code_edit = QTextEdit()
            code_edit.setReadOnly(True)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    code = f.read()
            except Exception as e:
                code = f"Could not load file: {file_path}\n\nError: {e}"
            code_edit.setPlainText(code)
            vbox.addWidget(code_edit)
            close_btn = QPushButton('Close')
            close_btn.clicked.connect(code_dialog.accept)
            vbox.addWidget(close_btn)
            code_dialog.exec()

        # Use absolute paths to ensure correct loading
        master_path = str(pathlib.Path('docs/Arduino/Arduino_Master.ino').absolute())
        slave_path = str(pathlib.Path('docs/Arduino/Arduino_Slave_with_K-Type.ino').absolute())
        btn_layout = QHBoxLayout()
        btn_master = QPushButton('View Master Example')
        btn_slave = QPushButton('View Slave Example')
        btn_layout.addWidget(btn_master)
        btn_layout.addWidget(btn_slave)
        layout.addLayout(btn_layout) # Use addLayout instead of insertLayout
        btn_master.clicked.connect(lambda: show_code_dialog('Arduino_Master.ino', master_path))
        btn_slave.clicked.connect(lambda: show_code_dialog('Arduino_Slave_with_K-Type.ino', slave_path))
        
        # Add close button at the bottom
        button_layout = QHBoxLayout()
        close_btn = QPushButton("Close")
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)
        
        # Connect buttons
        close_btn.clicked.connect(dialog.reject)
        
        # Show dialog
        dialog.exec()
        
    def show_labjack_settings_popup(self):
        """Show LabJack settings in a popup dialog"""
        print("=== Opening LabJack Settings Popup Dialog ===")
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QGridLayout, QLabel, 
                                    QComboBox, QPushButton, QGroupBox, QHBoxLayout,
                                    QSpinBox, QDoubleSpinBox, QCheckBox, QTextEdit,
                                    QApplication) # <<< ADDED QApplication import
        from PyQt6.QtCore import Qt
        
        # Define button styles at the top so they're available before use
        green_border_style = """
            QPushButton {
                background-color: transparent;
                color: #4CAF50;
                border: 2px solid #4CAF50;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(76, 175, 80, 0.1);
            }
            QPushButton:pressed {
                background-color: rgba(76, 175, 80, 0.2);
            }
        """
        red_border_style = """
            QPushButton {
                background-color: transparent;
                color: #F44336;
                border: 2px solid #F44336;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(244, 67, 54, 0.1);
            }
            QPushButton:pressed {
                background-color: rgba(244, 67, 54, 0.2);
            }
        """
        
        # Create dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("LabJack Settings")
        dialog.setMinimumWidth(400)
        dialog.setMinimumHeight(400)
        
        # Main layout
        layout = QVBoxLayout(dialog)
        
        # Create a group box for LabJack settings
        connection_group = QGroupBox("Connection Settings")
        connection_layout = QGridLayout(connection_group)
        
        # Device Type
        connection_layout.addWidget(QLabel("Device Type:"), 0, 0)
        device_type = QComboBox()
        device_type.addItems(["U3", "U6", "T7", "UE9"])
        if hasattr(self, 'labjack_type'):
            device_type.setCurrentText(self.labjack_type.currentText())
        else:
            device_type.setCurrentText(self.settings.value("labjack_type", "U3"))
        connection_layout.addWidget(device_type, 0, 1)

        # Status label and value
        status_label = QLabel("Status:")
        connection_layout.addWidget(status_label, 1, 0)
        status_value = QLabel("Not Connected")
        if hasattr(self, 'sensor_controller') and \
           hasattr(self.sensor_controller, 'labjack') and \
           self.sensor_controller.labjack is not None:
            status_value.setText("Connected")
            status_value.setStyleSheet("color: green; font-weight: bold;")
        else:
            status_value.setStyleSheet("color: gray; font-weight: bold;")
        connection_layout.addWidget(status_value, 1, 1)

        # Auto-connect at program start checkbox
        auto_connect_checkbox = QCheckBox("Auto-connect at program start")
        auto_connect_checkbox.setChecked(self.settings.value("labjack_auto_connect", "false") == "true")
        connection_layout.addWidget(auto_connect_checkbox, 2, 0, 1, 3)

        # Connect Button
        connect_btn = QPushButton("Connect")
        connect_btn.setStyleSheet(green_border_style)
        connection_layout.addWidget(connect_btn, 3, 2)

        # Test Button
        test_btn = QPushButton("Test")
        connection_layout.addWidget(test_btn, 4, 2)
        
        # Add connection group to main layout
        layout.addWidget(connection_group)
        
        # Channel configuration group
        channel_group = QGroupBox("Channel Configuration")
        channel_layout = QGridLayout(channel_group)
        
        # Note: Sampling rate setting removed as it's controlled by the global sampling rate
        
        # Use high resolution
        high_res = QCheckBox("Use High Resolution")
        high_res.setChecked(self.settings.value("labjack_high_res", "true") == "true")
        channel_layout.addWidget(high_res, 0, 0, 1, 2)
        
        # Add channel group to main layout
        layout.addWidget(channel_group)
        
        # Information section
        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setMaximumHeight(100)
        
        # Set information text
        device_info = """
        <b>Device Information:</b><br>
        <i>Note: Connect to a device to see detailed information.</i>
        """
        
        # --- ADDED DEBUG LOG ---
        self.logger.log("DEBUG POPUP INIT: Checking for connected labjack...", "DEBUG")
        has_sensor_controller = hasattr(self, 'sensor_controller')
        has_labjack = has_sensor_controller and hasattr(self.sensor_controller, 'labjack')
        is_labjack_not_none = has_labjack and self.sensor_controller.labjack is not None
        self.logger.log(f"DEBUG POPUP INIT: has_sensor_controller={has_sensor_controller}, has_labjack={has_labjack}, is_labjack_not_none={is_labjack_not_none}", "DEBUG")
        # ----------------------
        
        # If we're connected, get more detailed info
        if has_sensor_controller and has_labjack and is_labjack_not_none:
            self.logger.log("DEBUG POPUP INIT: LabJack is connected, trying to get device info", "DEBUG")
            try:
                # Try to get actual device info - this will vary by device type
                # Get the numeric device type first
                device_type_code = self.sensor_controller.get_labjack_info("device_type", -1)
                # Translate the numeric code to a readable name
                device_type_map = {7: "T7", 4: "T4", 3: "U3", 6: "U6", 9: "UE9"}
                type_info = device_type_map.get(device_type_code, f"Unknown({device_type_code})")
                
                serial_info = self.sensor_controller.get_labjack_info("serial_number", "Unknown")
                firmware_info = self.sensor_controller.get_labjack_info("firmware_version", "Unknown")
                
                self.logger.log(f"DEBUG POPUP INIT: Got device info - Type code: {device_type_code}, translated to: {type_info}, Serial: {serial_info}, Firmware: {firmware_info}", "DEBUG")
                
                device_info = """
                <b>Device Information:</b><br>
                Type: {}<br>
                Serial Number: {}<br>
                Firmware Version: {}<br>
                """.format(type_info, serial_info, firmware_info)
                
                self.logger.log(f"DEBUG POPUP INIT: Formatted HTML: {device_info}", "DEBUG")
            except Exception as e:
                self.logger.log(f"DEBUG POPUP INIT: Error getting device info: {str(e)}", "ERROR")
                import traceback
                self.logger.log(traceback.format_exc(), "ERROR")
        else:
            self.logger.log("DEBUG POPUP INIT: LabJack is not connected, using default info text", "DEBUG")
            
        self.logger.log("DEBUG POPUP INIT: Setting HTML for info_text", "DEBUG")
        info_text.setHtml(device_info)
        QApplication.processEvents()  # Force UI update
        self.logger.log("DEBUG POPUP INIT: Finished setting up info_text", "DEBUG")
        layout.addWidget(info_text)
        
        # Add buttons at the bottom
        button_layout = QHBoxLayout()
        save_btn = QPushButton("Save Settings")
        close_btn = QPushButton("Close")
        
        button_layout.addWidget(save_btn)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)
        
        # If we're already connected, change the button text and style
        if hasattr(self, 'sensor_controller') and \
           hasattr(self.sensor_controller, 'labjack') and \
           self.sensor_controller.labjack is not None:
            connect_btn.setText("Disconnect")
            connect_btn.setStyleSheet(red_border_style)
        
        # Connect buttons
        close_btn.clicked.connect(dialog.reject)
        
        # Connect save button
        def save_settings():
            # Save settings
            device_type_value = device_type.currentText()
            self.settings.setValue("labjack_type", device_type_value)
            self.settings.setValue("labjack_high_res", "true" if high_res.isChecked() else "false")
            self.settings.setValue("labjack_auto_connect", "true" if auto_connect_checkbox.isChecked() else "false")
            
            # Update main window UI if applicable
            if hasattr(self, 'labjack_type'):
                self.labjack_type.setCurrentText(device_type_value)
                
            # Show confirmation dialog
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(dialog, "Settings Saved", 
                                  f"LabJack settings have been saved.\n\nDevice type: {device_type_value}\nHighRes: {'Enabled' if high_res.isChecked() else 'Disabled'}\nAuto-connect: {'Enabled' if auto_connect_checkbox.isChecked() else 'Disabled'}")
        
        save_btn.clicked.connect(save_settings)
        
        # Define connect action function
        def connect_labjack():
            self.logger.log("DEBUG POPUP: connect_labjack function called", "DEBUG")
            
            # Update the main window UI with values from the dialog
            self.settings.setValue("labjack_type", device_type.currentText())
            self.settings.setValue("labjack_auto_connect", "true" if auto_connect_checkbox.isChecked() else "false")
            self.logger.log(f"Saved LabJack device type: {device_type.currentText()}")
            
            # Determine desired action based on button text
            action = connect_btn.text() # "Connect" or "Disconnect"
            
            if action == "Disconnect":
                # Attempt to disconnect
                self.logger.log("DEBUG POPUP: Attempting disconnect...", "DEBUG")
                success = self.sensor_controller.disconnect_labjack()
                if success:
                    connect_btn.setText("Connect")
                    connect_btn.setStyleSheet(green_border_style)
                    status_value.setText("Not Connected")
                    status_value.setStyleSheet("color: gray; font-weight: bold;")
                    # Clear info box on disconnect
                    info_text.setHtml("<b>Device Information:</b><br><i>Not connected</i>")
                else:
                    self.logger.log("DEBUG POPUP: Disconnect failed.", "WARN")
                return # Done with disconnect action
            
            # --- If action is "Connect" --- 
            self.logger.log("DEBUG POPUP: Attempting connect...", "DEBUG")
            
            # Make sure the global sampling rate is set from the sampling_rate_spinbox
            if hasattr(self, 'sampling_rate_spinbox') and hasattr(self, 'data_collection_controller'):
                sampling_rate = self.sampling_rate_spinbox.value()
                self.data_collection_controller.set_sampling_rate(sampling_rate)
                self.logger.log(f"Applied global sampling rate before connecting LabJack: {sampling_rate} Hz")
            
            # Attempt to connect to LabJack
            success = self.sensor_controller.connect_labjack(
                device_identifier="ANY"  # Use ANY to auto-detect instead of specific device type
            )
            
            # Update UI based on connection result (success or failure)
            if success:
                self.logger.log("DEBUG POPUP: Connection successful, updating UI.", "DEBUG")
                
                connect_btn.setText("Disconnect")
                connect_btn.setStyleSheet(red_border_style)
                status_value.setText("Connected")
                status_value.setStyleSheet("color: green; font-weight: bold;")
                
                # --- Update device info box --- 
                try:
                    # Get info using the controller's method
                    # Get the numeric device type first
                    device_type_code = self.sensor_controller.get_labjack_info("device_type", -1)
                    # Translate the numeric code to a readable name
                    device_type_map = {7: "T7", 4: "T4", 3: "U3", 6: "U6", 9: "UE9"}
                    type_info = device_type_map.get(device_type_code, f"Unknown({device_type_code})")
                    
                    serial_info = self.sensor_controller.get_labjack_info("serial_number", "Unknown")
                    firmware_info = self.sensor_controller.get_labjack_info("firmware_version", "Unknown")
                    
                    # Debug log the retrieved info
                    self.logger.log(f"DEBUG POPUP: Retrieved info - Type code: {device_type_code}, translated to: {type_info}, Serial: {serial_info}, FW: {firmware_info}", "DEBUG")
                    
                    device_info = """
                    <b>Device Information:</b><br>
                    Type: {}<br>
                    Serial Number: {}<br>
                    Firmware Version: {}<br>
                    """.format(type_info, serial_info, firmware_info)
                    
                    info_text.setHtml(device_info)
                    self.logger.log("DEBUG POPUP: Updated info_text successfully.", "DEBUG")
                    QApplication.processEvents() # Force UI update
                except Exception as e:
                    self.logger.log(f"DEBUG POPUP: Error updating device info text: {str(e)}", "ERROR")
                    import traceback
                    self.logger.log(traceback.format_exc(), "ERROR")
                    info_text.setHtml("<b>Device Information:</b><br><i>Error retrieving info</i>") # Show error in box
            else:
                self.logger.log("DEBUG POPUP: Connection failed.", "WARN")
                connect_btn.setText("Connect") # Ensure button says Connect on failure
                connect_btn.setStyleSheet(green_border_style)
                status_value.setText("Connection Failed")
                status_value.setStyleSheet("color: red; font-weight: bold;")
                info_text.setHtml("<b>Device Information:</b><br><i>Connection failed</i>") # Show failure in box
        
        # Explicitly connect the button click signal to our function
        connect_btn.clicked.connect(connect_labjack)
        self.logger.log("DEBUG POPUP: Connected button click signal to connect_labjack function", "DEBUG")
        
        # Connect test button
        def test_labjack_connection():
            # Use sensor controller to test LabJack connection
            if hasattr(self, 'sensor_controller'):
                self.sensor_controller.test_labjack()
        
        test_btn.clicked.connect(test_labjack_connection)
        
        # --- ADDED DEBUG --- 
        print(f"DEBUG POPUP: Is connect_labjack callable? {callable(connect_labjack)}")
        # -------------------
        
        # Show dialog
        dialog.exec()
        
    def apply_camera_focus_exposure(self):
        """Apply camera focus and exposure settings"""
        # Check if the camera controller exists
        if not hasattr(self, 'camera_controller') or not self.camera_controller.is_connected:
            self.logger.log("Cannot apply camera settings: camera not connected", "WARN")
            return
            
        try:
            # Check if the UI elements exist
            if not hasattr(self, 'camera_tab_manual_focus') or not hasattr(self, 'camera_tab_focus_slider') or \
               not hasattr(self, 'camera_tab_manual_exposure') or not hasattr(self, 'camera_tab_exposure_slider'):
                self.logger.log("Camera UI elements not found", "WARN")
                return
                
            # Get focus and exposure settings from the camera tab controls
            manual_focus = self.camera_tab_manual_focus.isChecked()
            focus_value = self.camera_tab_focus_slider.value()
            manual_exposure = self.camera_tab_manual_exposure.isChecked()
            exposure_value = self.camera_tab_exposure_slider.value()
            
            # Update slider enabled states
            self.camera_tab_focus_slider.setEnabled(manual_focus)
            self.camera_tab_exposure_slider.setEnabled(manual_exposure)
            
            # Save to settings
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
                    import cv2
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
            self.logger.log(f"Error applying camera focus/exposure: {str(e)}", "ERROR")
            import traceback
            traceback.print_exc()
            
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
        
    def show_camera_settings_popup(self):
        """Show camera settings in a popup dialog"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Camera Settings")
        dialog.setMinimumWidth(700)  # Increased width for two columns
        dialog.setMinimumHeight(600)
        
        # Create main layout for the dialog
        main_layout = QVBoxLayout(dialog)
        
        # Create a horizontal layout for two columns
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(20)  # Space between columns
        
        # Create left column
        left_column = QVBoxLayout()
        
        # Create right column
        right_column = QVBoxLayout()
        
        # Create camera parameters group
        camera_settings_group = QGroupBox("Camera Parameters")
        camera_settings_layout = QGridLayout(camera_settings_group)
        
        # Resolution selection
        camera_settings_layout.addWidget(QLabel("Resolution:"), 0, 0)
        camera_resolution = QComboBox()
        camera_resolution.addItems(["640x480", "800x600", "1280x720", "1920x1080"])
        camera_resolution.setCurrentText(self.settings.value("camera/resolution", "1280x720"))
        camera_settings_layout.addWidget(camera_resolution, 0, 1)
        
        # Framerate selection
        camera_settings_layout.addWidget(QLabel("Framerate:"), 1, 0)
        camera_framerate = QComboBox()
        camera_framerate.addItems(["15", "30", "60"])
        camera_framerate.setCurrentText(self.settings.value("camera/fps", "30"))
        camera_settings_layout.addWidget(camera_framerate, 1, 1)
        
        # Set values from existing camera resolution and framerate
        if hasattr(self, 'camera_resolution'):
            camera_resolution.setCurrentText(self.camera_resolution.currentText())
        if hasattr(self, 'camera_framerate'):
            camera_framerate.setCurrentText(self.camera_framerate.currentText())
        
        # Add camera parameters group to left column
        left_column.addWidget(camera_settings_group)
        
        # Recording settings group
        recording_settings_group = QGroupBox("Recording Settings")
        recording_settings_layout = QGridLayout(recording_settings_group)
        
        # Auto-record on start
        auto_record = QCheckBox("Auto-record when started")
        auto_record.setChecked(self.settings.value("auto_record", "false") == "true")
        recording_settings_layout.addWidget(auto_record, 0, 0, 1, 2)
        
        # Start camera on start
        start_camera_on_start = QCheckBox("Start camera on start")
        start_camera_on_start.setChecked(self.settings.value("start_camera_on_start", "false") == "true")
        recording_settings_layout.addWidget(start_camera_on_start, 1, 0, 1, 2)
        
        # Include overlays in recording
        record_with_overlays = QCheckBox("Include overlays in recording")
        record_with_overlays.setChecked(self.settings.value("record_with_overlays", "true") == "true")
        recording_settings_layout.addWidget(record_with_overlays, 2, 0, 1, 2)
        
        # Direct FFmpeg streaming
        use_direct_streaming = QCheckBox("Use direct FFmpeg streaming (recommended)")
        use_direct_streaming.setToolTip("Streams frames directly to FFmpeg instead of buffering them in memory. Requires FFmpeg to be correctly configured.")
        use_direct_streaming.setChecked(self.settings.value("use_direct_streaming", "true").lower() == "true")
        recording_settings_layout.addWidget(use_direct_streaming, 3, 0, 1, 2)
        
        # Recording format
        recording_settings_layout.addWidget(QLabel("Format:"), 4, 0) # Row changed from 3 to 4
        recording_format = QComboBox()
        recording_format.addItems(["MP4 (H.264)", "AVI (MJPG)", "AVI (XVID)"]) # Updated order
        # Set MP4 as default
        recording_format.setCurrentText(self.settings.value("recording_format", "MP4 (H.264)"))
        recording_settings_layout.addWidget(recording_format, 4, 1) # Row changed from 3 to 4
        
        # Video Quality slider
        recording_settings_layout.addWidget(QLabel("Video Quality:"), 5, 0) # Row changed from 4 to 5
        video_quality_slider = QSlider(Qt.Orientation.Horizontal)
        video_quality_slider.setMinimum(20)
        video_quality_slider.setMaximum(100)
        
        # Initialize quality from settings or use default
        quality_value = int(self.settings.value("video_quality", "70"))
        video_quality_slider.setValue(quality_value)
        
        video_quality_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        video_quality_slider.setTickInterval(10)
        recording_settings_layout.addWidget(video_quality_slider, 5, 1) # Row changed from 4 to 5
        
        # Display current quality value
        video_quality_label = QLabel(f"{quality_value}%")
        video_quality_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        recording_settings_layout.addWidget(video_quality_label, 6, 1) # Row changed from 5 to 6
        
        # Connect quality slider to update the label
        video_quality_slider.valueChanged.connect(lambda value: video_quality_label.setText(f"{value}%"))
        
        # Add recording settings group to left column
        left_column.addWidget(recording_settings_group)
        
        # NDI Output Settings (moved from settings tab left column)
        ndi_group = QGroupBox("NDI Output Settings")
        ndi_layout = QGridLayout(ndi_group)
        
        # Enable NDI output
        enable_ndi = QCheckBox("Enable NDI Output")
        enable_ndi.setChecked(self.settings.value("enable_ndi", "false") == "true")
        ndi_layout.addWidget(enable_ndi, 0, 0, 1, 2)
        
        # NDI Source Name
        ndi_layout.addWidget(QLabel("Source Name:"), 1, 0)
        ndi_source_name = QLineEdit(self.settings.value("ndi_source_name", "EvoLabs DAQ"))
        ndi_layout.addWidget(ndi_source_name, 1, 1)
        
        # Include overlays in NDI output
        ndi_with_overlays = QCheckBox("Include overlays in NDI output")
        ndi_with_overlays.setChecked(self.settings.value("ndi_with_overlays", "true") == "true")
        ndi_layout.addWidget(ndi_with_overlays, 2, 0, 1, 2)
        
        # Add NDI group to left column
        left_column.addWidget(ndi_group)
        
        # Add stretch to push everything to the top
        left_column.addStretch()
        
        # Motion detection group
        motion_detection_group = QGroupBox("Motion Detection")
        motion_detection_layout = QVBoxLayout(motion_detection_group)
        
        # Enable motion detection
        motion_detection_enable = QCheckBox("Enable Motion Detection")
        motion_detection_enable.setChecked(self.settings.value("camera/motion_detection", "false") == "true")
        motion_detection_layout.addWidget(motion_detection_enable)
        
        # Sensitivity slider
        motion_sensitivity_layout = QHBoxLayout()
        motion_sensitivity_layout.addWidget(QLabel("Sensitivity:"))
        motion_sensitivity = QSlider(Qt.Orientation.Horizontal)
        motion_sensitivity.setMinimum(1)
        motion_sensitivity.setMaximum(100)
        motion_sensitivity.setValue(int(self.settings.value("camera/motion_sensitivity", "50")))
        motion_sensitivity.setTickPosition(QSlider.TickPosition.TicksBelow)
        motion_sensitivity.setTickInterval(10)
        motion_sensitivity_layout.addWidget(motion_sensitivity, 1)
        
        # Value display for sensitivity
        motion_sensitivity_value = QLabel(str(motion_sensitivity.value()))
        motion_sensitivity.valueChanged.connect(lambda v: motion_sensitivity_value.setText(str(v)))
        motion_sensitivity_value.setMinimumWidth(30)
        motion_sensitivity_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        motion_sensitivity_layout.addWidget(motion_sensitivity_value)
        
        motion_detection_layout.addLayout(motion_sensitivity_layout)
        
        # Minimum area
        min_area_layout = QHBoxLayout()
        min_area_layout.addWidget(QLabel("Min Area:"))
        motion_min_area = QSpinBox()
        motion_min_area.setRange(100, 10000)
        motion_min_area.setSingleStep(100)
        motion_min_area.setValue(int(self.settings.value("camera/motion_min_area", "500")))
        min_area_layout.addWidget(motion_min_area)
        motion_detection_layout.addLayout(min_area_layout)
        
        # Add help text
        motion_detection_help = QLabel("Motion detection can trigger automation sequences.\nHigher sensitivity detects smaller movements.")
        motion_detection_help.setWordWrap(True)
        motion_detection_help.setStyleSheet("font-size: 8pt; color: #888;")
        motion_detection_layout.addWidget(motion_detection_help)
        
        # Set values if attributes exist
        if hasattr(self, 'motion_detection_enable'):
            motion_detection_enable.setChecked(self.motion_detection_enable.isChecked())
        if hasattr(self, 'motion_detection_sensitivity'):
            motion_sensitivity.setValue(self.motion_detection_sensitivity.value())
        if hasattr(self, 'motion_detection_min_area'):
            motion_min_area.setValue(self.motion_detection_min_area.value())
        
        # Add motion detection group to right column
        right_column.addWidget(motion_detection_group)
        
        # Add stretch to right column to push everything to the top and align with left column
        right_column.addStretch()
        
        # Add both columns to the columns layout
        columns_layout.addLayout(left_column)
        columns_layout.addLayout(right_column)
        
        # Add columns layout to main layout
        main_layout.addLayout(columns_layout)
        
        # Add buttons to save/cancel
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(lambda: self.apply_camera_settings_from_popup(
            camera_resolution.currentText(),
            camera_framerate.currentText(),
            motion_detection_enable.isChecked(),
            motion_sensitivity.value(),
            motion_min_area.value(),
            auto_record.isChecked(),
            start_camera_on_start.isChecked(),
            record_with_overlays.isChecked(),
            recording_format.currentText(),
            video_quality_slider.value(),
            # Add NDI settings
            enable_ndi.isChecked(),
            ndi_source_name.text(),
            ndi_with_overlays.isChecked(),
            use_direct_streaming.isChecked(),
            dialog
        ))
        button_box.rejected.connect(dialog.reject)
        main_layout.addWidget(button_box)
        
        # Show the dialog as modal
        dialog.exec()
        
    def apply_camera_settings_from_popup(self, resolution, framerate, motion_enabled, sensitivity, min_area, 
                                        auto_record, start_camera_on_start, record_with_overlays, 
                                        recording_format, video_quality, 
                                        enable_ndi, ndi_source_name, ndi_with_overlays,
                                        use_direct_streaming, dialog):
        """Apply camera settings from the popup dialog"""
        # Update settings
        self.settings.setValue("camera/resolution", resolution)
        self.settings.setValue("camera/fps", framerate)
        self.settings.setValue("camera/motion_detection", "true" if motion_enabled else "false")
        self.settings.setValue("camera/motion_sensitivity", str(sensitivity))
        self.settings.setValue("camera/motion_min_area", str(min_area))
        
        # Update recording settings
        self.settings.setValue("auto_record", "true" if auto_record else "false")
        self.settings.setValue("start_camera_on_start", "true" if start_camera_on_start else "false")
        self.settings.setValue("record_with_overlays", "true" if record_with_overlays else "false")
        self.settings.setValue("recording_format", recording_format)
        self.settings.setValue("video_quality", str(video_quality))
        
        # Update NDI settings
        self.settings.setValue("enable_ndi", "true" if enable_ndi else "false")
        self.settings.setValue("ndi_source_name", ndi_source_name)
        self.settings.setValue("ndi_with_overlays", "true" if ndi_with_overlays else "false")
        self.settings.setValue("use_direct_streaming", "true" if use_direct_streaming else "false")
        
        # Update UI elements if they exist
        if hasattr(self, 'camera_resolution'):
            self.camera_resolution.setCurrentText(resolution)
        if hasattr(self, 'camera_framerate'):
            self.camera_framerate.setCurrentText(framerate)
        if hasattr(self, 'motion_detection_enable'):
            self.motion_detection_enable.setChecked(motion_enabled)
        if hasattr(self, 'motion_detection_sensitivity'):
            self.motion_detection_sensitivity.setValue(sensitivity)
        if hasattr(self, 'motion_detection_min_area'):
            self.motion_detection_min_area.setValue(min_area)
            
        # Update recording settings UI elements if they exist
        if hasattr(self, 'auto_record'):
            self.auto_record.setChecked(auto_record)
        if hasattr(self, 'start_camera_on_start'):
            self.start_camera_on_start.setChecked(start_camera_on_start)
        if hasattr(self, 'record_with_overlays'):
            self.record_with_overlays.setChecked(record_with_overlays)
        if hasattr(self, 'recording_format'):
            self.recording_format.setCurrentText(recording_format)
        if hasattr(self, 'video_quality_slider'):
            self.video_quality_slider.setValue(video_quality)
            
        # Update NDI UI elements if they exist
        if hasattr(self, 'enable_ndi'):
            self.enable_ndi.setChecked(enable_ndi)
        if hasattr(self, 'ndi_source_name'):
            self.ndi_source_name.setText(ndi_source_name)
        if hasattr(self, 'ndi_with_overlays'):
            self.ndi_with_overlays.setChecked(ndi_with_overlays)
        if hasattr(self, 'use_direct_streaming'):
            self.use_direct_streaming.setChecked(use_direct_streaming)
            
        # Apply settings to camera controller if connected
        if hasattr(self, 'camera_controller') and self.camera_controller.is_connected:
            self.camera_controller.update_camera_settings(
                motion_detection=motion_enabled,
                motion_sensitivity=sensitivity,
                motion_min_area=min_area
            )
            
        # Initialize NDI if needed
        if enable_ndi and hasattr(self, 'init_ndi'):
            self.init_ndi()
            
        # Close the dialog
        dialog.accept()
        
    def start_acquisition(self):
        """Start data acquisition"""
        # Set the acquisition flag
        self.is_acquiring = True
        self.paused = False
        
        print("DEBUG MainWindow: start_acquisition called")
        
        # Get the run directory
        run_dir = self.get_current_run_dir()
        if run_dir:
            # Create the run directory if it doesn't exist
            os.makedirs(run_dir, exist_ok=True)
            
            # Move virtual_sensors.json to the run directory if it exists in current directory
            virtual_sensors_fallback_path = VIRTUAL_SENSORS_PATH
            virtual_sensors_run_path = os.path.join(run_dir, VIRTUAL_SENSORS_FILENAME)
            if os.path.exists(virtual_sensors_fallback_path) and not os.path.exists(virtual_sensors_run_path):
                try:
                    shutil.copy2(virtual_sensors_fallback_path, virtual_sensors_run_path)
                    self.logger.log(f"Copied virtual sensors config to run directory")
                except Exception as e:
                    self.logger.log(f"Failed to copy virtual sensors to run: {str(e)}", "ERROR")
            
            # Start data collection
            self.data_collection_controller.start_data_collection(run_dir)
            
            # Start the sensor controller
            if hasattr(self, 'sensor_controller'):
                print("DEBUG MainWindow: Calling sensor_controller.start_acquisition()")
                self.sensor_controller.start_acquisition()
            
            # Check if we have OtherSerial sensors and verify they're connected
            has_virtual_sensors = len(getattr(self, 'other_sensors', [])) > 0
            if has_virtual_sensors:
                print(f"DEBUG MainWindow: Has {len(self.other_sensors)} virtual sensors")
                # Check if other_serial interface is connected in the controller
                if hasattr(self.data_collection_controller, 'interfaces'):
                    other_serial_connected = 'other_serial' in self.data_collection_controller.interfaces and self.data_collection_controller.interfaces['other_serial'].get('connected', False)
                    print(f"DEBUG MainWindow: OtherSerial interface connected = {other_serial_connected}")
                    
            # Update the UI states
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
            
            # Change the status LED
            self.animation_status.setStyleSheet("background-color: green; border-radius: 10px;")
            
            # Log the acquisition start
            self.logger.log(f"Started data acquisition to {run_dir}")
            
            # Update other UI elements to indicate acquisition has started
            # ...
            
        else:
            # Show an error message
            QMessageBox.warning(
                self,
                "Data Acquisition",
                "Cannot start data acquisition - no run directory available",
                QMessageBox.StandardButton.Ok
            )
        
    def stop_acquisition(self):
        """Stop data acquisition"""
        print(f"[STOP] stop_acquisition called (redirecting to toggle)")
        self.logger.log("stop_acquisition called", "DEBUG")
        
        # Force button to Stop first
        self.toggle_btn.setText("Stop")
        
        # Then trigger the toggle
        self.on_toggle_clicked()
        
    def show_other_settings_popup(self):
        """Show the popup for managing COM port polling sequences"""
        # Create a dialog for managing sequences
        from app.ui.dialogs.other_sensors_dialog import OtherSensorsDialog
        
        # Get existing configuration (if any)
        sensors = deepcopy(getattr(self, 'other_sensors', []))
        sequences = deepcopy(getattr(self, 'other_sequences', []))
        
        # Check if any Other Sensors are currently connected
        other_sensors_connected = False
        if hasattr(self, 'data_collection_controller'):
            data_controller = self.data_collection_controller
            if hasattr(data_controller, 'interfaces') and 'other_serial' in data_controller.interfaces:
                other_serial_interfaces = data_controller.interfaces['other_serial']
                
                # Check if other_serial_interfaces is a dictionary with a 'connected' key directly
                if isinstance(other_serial_interfaces, dict) and 'connected' in other_serial_interfaces:
                    other_sensors_connected = other_serial_interfaces['connected']
                # Safely iterate through values only when they are dictionaries
                elif isinstance(other_serial_interfaces, dict):
                    other_sensors_connected = any(
                        isinstance(conn, dict) and conn.get('connected', False) 
                        for conn in other_serial_interfaces.values()
                    )
                
                if other_sensors_connected:
                    self.logger.log("Other Sensors connection detected", "INFO")
        
        # Show the dialog
        dialog = OtherSensorsDialog(self, sensors=sensors, sequences=sequences)
        
        # If we already have a connection, make sure the UI reflects this state
        if other_sensors_connected and hasattr(self, 'update_device_connection_status_ui'):
            self.update_device_connection_status_ui('other', True)
        
        # Execute the dialog and handle the result
        if dialog.exec():
            # Only update sequences as sensors are now managed in the main sensor table
            self.other_sequences = dialog.sequences
            
            # Keep the existing sensors reference for backward compatibility
            self.other_sensors = dialog.sensors
            
            # Save the configurations
            self.save_virtual_sensors()
            
            # Reconnect all configured sequences with their associated virtual sensors
            if hasattr(self, 'sensor_controller'):
                # Try to use the dedicated method if available
                if hasattr(self.sensor_controller, 'reinitialize_other_serial_connections'):
                    self.logger.log("Reconnecting virtual sensors after configuration change...")
                    self.sensor_controller.reinitialize_other_serial_connections()
                elif hasattr(self.sensor_controller, 'initialize_other_serial_connections'):
                    self.logger.log("Reconnecting virtual sensors after configuration change...")
                    self.sensor_controller.initialize_other_serial_connections()
                else:
                    # Use the built-in method
                    self._connect_virtual_sensors()
            else:
                # Fallback to the basic connection method
                self._connect_virtual_sensors()
            
            # Update the sensor table to reflect any changes
            if hasattr(self, 'sensor_controller'):
                self.sensor_controller.update_sensor_table()

    def handle_labjack_connect_button(self):
        """Handle clicking the LabJack connect button"""
        print("DEBUG MAIN_WINDOW: handle_labjack_connect_button called") # <<< ADDED
        try:
            print("LabJack connect button clicked")
            
            # Get the current button text
            button_text = ""
            if hasattr(self, 'labjack_connect_btn') and self.labjack_connect_btn is not None:
                button_text = self.labjack_connect_btn.text()
                
            # Check if we should connect or disconnect
            if button_text == "Connect":
                # Show the LabJack connection dialog
                print("DEBUG MAIN_WINDOW: Calling show_connect_labjack_dialog()") # <<< ADDED
                self.show_connect_labjack_dialog()
            else:
                # Disconnect using the controller's method
                print("DEBUG MAIN_WINDOW: Disconnecting LabJack via sensor_controller") # <<< ADDED
                if hasattr(self, 'sensor_controller') and self.sensor_controller is not None:
                    # Use the new disconnect method that properly cleans up resources
                    self.sensor_controller.disconnect_labjack()
                    
                # Update button state using our dedicated method
                self.update_labjack_connected_status(False)
                
                # Log the disconnection
                if hasattr(self, 'logger') and self.logger is not None:
                    self.logger.log("Disconnected from LabJack")
        except Exception as e:
            print(f"Error in handle_labjack_connect_button: {e}")
            if hasattr(self, 'logger') and self.logger is not None:
                self.logger.log(f"Error in handle_labjack_connect_button: {e}", "ERROR")

    def setup_sensor_tab(self):
        """Set up the sensor tab UI and functionality"""
        try:
            print("Setting up sensor tab UI...")
            
            # Set up table
            if hasattr(self, 'data_table'):
                self.data_table.setColumnCount(6)  # Change from 5 to 6 columns to include color
                self.data_table.setHorizontalHeaderLabels(["Show", "Sensor", "Value", "Interface", "Offset/Unit", "Color"])
                self.data_table.setColumnWidth(0, 50)   # Show column is narrow
                self.data_table.setColumnWidth(1, 150)  # Sensor name
                self.data_table.setColumnWidth(2, 120)  # Value
                self.data_table.setColumnWidth(3, 100)  # Interface type
                self.data_table.setColumnWidth(4, 100)  # Offset/Unit
                self.data_table.setColumnWidth(5, 80)   # Color
                
                # Enable selection
                self.data_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
                self.data_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
                
                # Set table properties
                self.data_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
                self.data_table.setAlternatingRowColors(True)
                self.data_table.setSortingEnabled(False)
                
                print("Sensor table set up")
            else:
                print("Warning: data_table widget not found")
            
            # Configure buttons - Keep them enabled
            if hasattr(self, 'edit_sensor_btn'):
                print("Edit sensor button found")
            if hasattr(self, 'remove_sensor_btn'):
                print("Remove sensor button found")
            
            # If we have a sensor controller, update the table with any existing sensors
            if hasattr(self, 'sensor_controller'):
                self.sensor_controller.update_sensor_table()
                print("Sensor table populated with existing sensors")
            
            # Set up the values update timer
            # Get the sampling rate from settings (default to 0.5Hz if not set)
            sampling_rate = float(self.settings.value("labjack_sampling_rate", "1.0"))
            
            # Calculate update interval in milliseconds (minimum 100ms for UI responsiveness)
            update_interval = max(int(1000 / sampling_rate), 100)
            
            self.sensor_values_timer = QTimer(self)
            
            # Create dummy data for the timer callback
            # Without this, the update_sensor_values method won't update automation context
            dummy_data = {'dummy': 0, 'timestamp': time.time()}
            
            # Connect timer to a lambda that calls update_sensor_values with dummy data
            self.sensor_values_timer.timeout.connect(lambda: self.sensor_controller.update_automation_context() if hasattr(self, 'sensor_controller') and hasattr(self, 'automation_controller') else None)
            
            # --- RE-ENABLE TABLE UPDATE TIMER --- 
            print(f"DEBUG MAIN_WINDOW: Sensor values timer setup AND STARTING. Interval: {update_interval}ms")
            self.sensor_values_timer.start(update_interval)
            # -----------------------------------
                
            # Connect signals - this is where the buttons get connected to methods
            self.setup_sensor_tab_signals()
            print("Sensor tab UI setup complete")
        except Exception as e:
            print(f"Error in setup_sensor_tab: {e}")
            import traceback
            traceback.print_exc()

    def setup_sensor_tab_signals(self):
        """Connect signals for the sensor tab buttons."""
        try:
            if hasattr(self, 'add_sensor_btn'):
                self.add_sensor_btn.clicked.connect(self.add_sensor)
                print("Connected add_sensor_btn")
            else:
                print("Warning: add_sensor_btn not found")

            if hasattr(self, 'edit_sensor_btn'):
                self.edit_sensor_btn.clicked.connect(self.edit_sensor)
                print("Connected edit_sensor_btn")
            else:
                print("Warning: edit_sensor_btn not found")

            if hasattr(self, 'remove_sensor_btn'):
                self.remove_sensor_btn.clicked.connect(self.remove_sensor)
                print("Connected remove_sensor_btn")
            else:
                print("Warning: remove_sensor_btn not found")
                
            # Connect cell clicked signal for selection/color change
            if hasattr(self, 'data_table'):
                 self.data_table.cellClicked.connect(self.sensor_cell_clicked)
                 print("Connected data_table cellClicked")

        except Exception as e:
            print(f"Error connecting sensor tab signals: {e}")
            import traceback
            traceback.print_exc()

    def show_add_sensor_dialog(self):
        """Show the add sensor dialog directly"""
        print("show_add_sensor_dialog called")
        
        # Try different approaches to show the dialog
        if hasattr(self, 'sensor_controller') and self.sensor_controller:
            print("Using sensor_controller to show dialog")
            self.sensor_controller.add_sensor()
        else:
            print("No sensor_controller found, trying direct approach")
            # Creating a basic dialog as a fallback
            from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, 
                                        QPushButton, QMessageBox)
            
            # Create a simple error dialog
            dialog = QDialog(self)
            dialog.setWindowTitle("Add Sensor")
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel("Error: Sensor controller not initialized."))
            layout.addWidget(QLabel("Please make sure the application is properly initialized."))
            
            # Add a button to close the dialog
            button = QPushButton("OK")
            button.clicked.connect(dialog.accept)
            layout.addWidget(button)
            
            # Show the dialog
            dialog.exec()

    def update_sensor_values(self):
        """Update sensor values - called by the sensor timer"""
        try:
            # Check if sensor controller exists
            if hasattr(self, 'sensor_controller') and self.sensor_controller:
                # Let the sensor controller do the update
                self.sensor_controller.update_sensor_values()
        except Exception as e:
            print(f"Error in update_sensor_values: {e}")
            # Don't print the full stack trace every time to avoid log spam

    def select_sensor(self, row, column):
        """Handle sensor selection in the table
        
        Args:
            row: The row index
            column: The column index
        """
        print(f"SELECT_SENSOR CALLED with row={row}, column={column}")
        
        try:
            # Enable the buttons directly - no complex checks
            if hasattr(self, 'edit_sensor_btn'):
                self.edit_sensor_btn.setEnabled(True)
                print("Successfully enabled edit_sensor_btn")
                
            if hasattr(self, 'remove_sensor_btn'):
                self.remove_sensor_btn.setEnabled(True)
                print("Successfully enabled remove_sensor_btn")
                
        except Exception as e:
            print(f"Error in select_sensor: {e}")
            import traceback
            traceback.print_exc()

    def sensor_cell_clicked(self, row, column):
        """Handle click on a sensor table cell"""
        try:
            # Check if the click was on the color column (column 5)
            if column == 5:
                # Get the sensor
                if hasattr(self, 'sensor_controller') and self.sensor_controller:
                    if row < len(self.sensor_controller.sensors):
                        sensor = self.sensor_controller.sensors[row]
                        
                        # Open color picker dialog
                        from PyQt6.QtGui import QColor
                        
                        # Ensure we start with a valid color
                        try:
                            current_color = QColor(sensor.color)
                            if not current_color.isValid():
                                current_color = QColor("#FFFFFF")  # Default to white if invalid
                        except:
                            current_color = QColor("#FFFFFF")  # Default to white on error
                            
                        color = QColorDialog.getColor(current_color, self, "Choose Sensor Color")
                        if color.isValid():
                            # Update sensor color with the color name
                            sensor.color = color.name()
                            
                            # Immediately force the color in the table cell
                            if hasattr(self, 'data_table'):
                                item = self.data_table.item(row, column)
                                if item:
                                    item.setBackground(color)
                                    item.setText(color.name())
                                    text_color = "black" if color.lightness() > 128 else "white"
                                    item.setForeground(QColor(text_color))
                            
                            # Update the table 
                            self.sensor_controller.update_sensor_table()
                            
                            # Log the change
                            if hasattr(self, 'logger'):
                                self.logger.log(f"Changed color for sensor {sensor.name} to {sensor.color}")
        except Exception as e:
            print(f"Error in sensor_cell_clicked: {e}")
            import traceback
            traceback.print_exc()

    def update_labjack_connected_status(self, is_connected):
        """Update the LabJack connection status display
        
        Args:
            is_connected (bool): Whether the LabJack is connected
        """
        print(f"Direct LabJack status update: is_connected={is_connected}")
        
        # First try to update the button if it exists
        if hasattr(self, 'labjack_connect_btn'):
            self.labjack_connect_btn.setText("Disconnect" if is_connected else "Connect")
            
            # Apply appropriate button style
            if is_connected:
                # Red border for disconnect button
                red_border_style = """
                    QPushButton {
                        background-color: transparent;
                        color: #F44336;
                        border: 2px solid #F44336;
                        padding: 6px 12px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: rgba(244, 67, 54, 0.1);
                    }
                    QPushButton:pressed {
                        background-color: rgba(244, 67, 54, 0.2);
                    }
                """
                self.labjack_connect_btn.setStyleSheet(red_border_style)
            else:
                # Green border for connect button
                green_border_style = """
                    QPushButton {
                        background-color: transparent;
                        color: #4CAF50;
                        border: 2px solid #4CAF50;
                        padding: 6px 12px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: rgba(76, 175, 80, 0.1);
                    }
                    QPushButton:pressed {
                        background-color: rgba(76, 175, 80, 0.2);
                    }
                """
                self.labjack_connect_btn.setStyleSheet(green_border_style)
            
            self.labjack_connect_btn.repaint()
        
        # Set the text and color directly on the labjack_status label if it exists
        if hasattr(self, 'labjack_status'):
            status_text = "Connected" if is_connected else "Not connected"
            status_color = "green" if is_connected else "grey"
            print(f"Directly updating labjack_status label to '{status_text}' with color '{status_color}'")
            self.labjack_status.setText(status_text)
            self.labjack_status.setStyleSheet(f"color: {status_color}; font-weight: bold; font-size: 14px;")
            self.labjack_status.repaint()
        
        # Force application to process events immediately
        from PyQt6.QtCore import QCoreApplication
        QCoreApplication.processEvents()
        
        # Log the status change
        status_str = "connected" if is_connected else "disconnected"
        if hasattr(self, 'logger'):
            self.logger.log(f"LabJack {status_str}", "INFO")

    def update_other_connected_status(self, is_connected):
        """Update the Other Sensors connection status display
        
        Args:
            is_connected (bool): Whether Other Sensors are connected
        """
        print(f"Direct Other Sensors status update: is_connected={is_connected}")
        
        # Set the text and color directly on the other_status label if it exists
        if hasattr(self, 'other_status'):
            status_text = "Connected" if is_connected else "Not connected"
            status_color = "green" if is_connected else "grey"
            print(f"Directly updating other_status label to '{status_text}' with color '{status_color}'")
            self.other_status.setText(status_text)
            self.other_status.setStyleSheet(f"color: {status_color}; font-weight: bold; font-size: 14px;")
            self.other_status.repaint()
        
        # Force application to process events immediately
        from PyQt6.QtCore import QCoreApplication
        QCoreApplication.processEvents()
        
        # Log the status change
        status_str = "connected" if is_connected else "disconnected"
        if hasattr(self, 'logger'):
            self.logger.log(f"Other Sensors {status_str}", "INFO")

    @pyqtSlot(int)
    def handle_graph_live_update_toggle(self, state):
        """Handles the live update checkbox toggle on the graph tab."""
        is_checked = (state == Qt.CheckState.Checked.value) # Convert int state to boolean
        print(f"DEBUG: Graph live update toggled: {is_checked} (state={state})")
        
        # Only control graph updates without affecting data collection
        if hasattr(self, 'graph_controller'):
            # Call the correct start/stop methods for the MAIN graph live update
            if is_checked:
                print("DEBUG: Starting main graph live update...")
                self.graph_controller.start_main_graph_live_update()
            else:
                print("DEBUG: Stopping main graph live update...")
                self.graph_controller.stop_main_graph_live_update()
        else:
            print("Warning: graph_controller not found when toggling live update.")

    def log(self, message, level="INFO"):
        """Log messages using the application logger"""
        if hasattr(self, 'logger'):
            self.logger.log(message, level)
        else:
            print(f"[{level}] {message}") # Fallback if logger not initialized

    def load_run_video(self, file_path):
        """Load a specified video file into the video player"""
        if not hasattr(self, 'video_player') or not hasattr(self, 'media_player'):
            self.log("Video player components not found.", "ERROR")
            QMessageBox.warning(self, "Error", "Video player not available in the UI.")
            return

        if not os.path.exists(file_path):
            self.log(f"Video file not found: {file_path}", "ERROR")
            QMessageBox.warning(self, "Error", f"Video file not found:\n{file_path}")
            return

        try:
            self.media_player.setSource(QUrl.fromLocalFile(file_path))
            # Ensure the Automation tab is selected to show the video player
            # Find the index for Automation tab
            automation_index = -1
            nav_button_names = [btn.text() for btn in self.nav_buttons]
            try:
                automation_index = nav_button_names.index("Automation")
            except ValueError:
                self.log("Automation tab not found in nav buttons.", "ERROR")
                QMessageBox.warning(self, "Error", "Could not switch to Automation tab to show video.")
                return

            if automation_index != -1:
                self.stacked_widget.setCurrentIndex(automation_index)
                self.nav_buttons[automation_index].setChecked(True) # Ensure button state matches

            self.log(f"Loaded video: {file_path}", "INFO")
            self.media_player.play() # Optionally start playing immediately

        except Exception as e:
            self.log(f"Error loading video '{file_path}': {e}", "ERROR")
            QMessageBox.critical(self, "Error", f"Could not load video:\n{e}")

    def load_virtual_sensors(self):
        """Load virtual sensors and sequences from JSON file. Priority: current run dir > last run > data dir."""
        def get_last_run_virtual_sensors_path():
            try:
                # Try to load from settings.json (not QSettings)
                settings_path = os.path.join(os.getcwd(), "settings.json")
                if not os.path.exists(settings_path):
                    return None
                with open(settings_path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                default_project_dir = settings.get("default_project_dir")
                last_project = settings.get("last_project")
                last_test_series = settings.get("last_test_series")
                if not (default_project_dir and last_project and last_test_series):
                    return None
                series_dir = os.path.join(default_project_dir, last_project, last_test_series)
                if not os.path.isdir(series_dir):
                    return None
                # Find newest run folder
                run_folders = [d for d in os.listdir(series_dir) if os.path.isdir(os.path.join(series_dir, d)) and d.lower().startswith("run_")]
                if not run_folders:
                    return None
                # Sort by timestamp in folder name (format: Run_YYYY-MM-DD_HH-MM-SS)
                def run_folder_key(name):
                    import re
                    m = re.match(r"Run_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})", name)
                    if not m:
                        return ""
                    return m.group(1) + "_" + m.group(2)
                run_folders.sort(key=run_folder_key, reverse=True)
                newest_run = run_folders[0]
                run_path = os.path.join(series_dir, newest_run)
                vs_path = os.path.join(run_path, VIRTUAL_SENSORS_FILENAME)
                if os.path.exists(vs_path):
                    return vs_path
                return None
            except Exception as e:
                if hasattr(self, 'logger'):
                    self.logger.log(f"Error finding last run's virtual_sensors.json: {e}", "ERROR")
                return None

        # Priority 1: Try to load from current run directory first
        current_run_path = self.get_virtual_sensors_path()
        if current_run_path != VIRTUAL_SENSORS_PATH and os.path.exists(current_run_path):
            try:
                with open(current_run_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.other_sensors = data.get("sensors", [])
                self.other_sequences = data.get("sequences", [])
                self.logger.log(f"Loaded virtual sensors from current run: {current_run_path}")
                self._connect_virtual_sensors()
                return
            except Exception as e:
                self.logger.log(f"Error loading virtual sensors from current run: {e}", "ERROR")

        # Priority 2: Try to load from newest run folder (only on first load)
        if not hasattr(self, '_virtual_sensors_loaded_once'):
            self._virtual_sensors_loaded_once = True
            last_run_path = get_last_run_virtual_sensors_path()
            if last_run_path:
                try:
                    with open(last_run_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self.other_sensors = data.get("sensors", [])
                    self.other_sequences = data.get("sequences", [])
                    self.logger.log(f"Loaded virtual sensors from last run: {last_run_path}")
                    self._connect_virtual_sensors()
                    return
                except Exception as e:
                    self.logger.log(f"Error loading virtual sensors from last run: {e}", "ERROR")

        # Priority 3: Fallback to current directory
        if os.path.exists(VIRTUAL_SENSORS_PATH):
            try:
                with open(VIRTUAL_SENSORS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.other_sensors = data.get("sensors", [])
                self.other_sequences = data.get("sequences", [])
                self.logger.log(f"Loaded virtual sensors from fallback location: {VIRTUAL_SENSORS_PATH}")
                self._connect_virtual_sensors()
            except Exception as e:
                self.logger.log(f"Error loading virtual sensors from fallback location: {e}", "ERROR")
                self.other_sensors = []
                self.other_sequences = []
        else:
            # No virtual sensors file found anywhere
            self.other_sensors = []
            self.other_sequences = []
            self.logger.log("No virtual sensors file found, starting with empty configuration")

    def _connect_virtual_sensors(self):
        """Connect to virtual sensors based on configured sequences"""
        success = False
        if not hasattr(self, 'other_sequences') or not self.other_sequences:
            return False
            
        for sensor in self.other_sensors:
            if sensor.get("mapping") and ":" in sensor.get("mapping", ""):
                seq_name, var_name = sensor.get("mapping").split(":", 1)
                # Find the sequence by name
                for sequence in self.other_sequences:
                    if sequence.get("name") == seq_name:
                        # Connect the sequence if it has a port
                        port = sequence.get("port", "")
                        if not port:
                            print(f"DEBUG MainWindow: Sequence {seq_name} has no port, cannot connect.")
                            continue

                        # Check if this port is already managed or if we should skip due to manual disconnect
                        if hasattr(self, 'data_collection_controller'):
                            dcc = self.data_collection_controller
                            if dcc.other_serial_manually_disconnected:
                                print(f"DEBUG MainWindow: Other serial manually disconnected, skipping auto-connect for sequence {seq_name} on port {port}")
                                if hasattr(self, 'logger'): self.logger.log(f"Skipping auto-connection of OtherSerial sequence {seq_name} - manually disconnected.", "INFO")
                                continue 

                        print(f"DEBUG MainWindow: Attempting to connect sequence {seq_name} on port {port}")
                        
                        # Pass False for is_explicit_reconnect if we are in an auto-connect scenario
                        # to respect the manual disconnect flag.
                        if self.sensor_controller.reinitialize_other_serial_connections(is_explicit_reconnect=False):
                            print(f"DEBUG MainWindow: Successfully reinitialized (or confirmed) connection for sequence {seq_name}")
                            if hasattr(self, 'logger'): self.logger.log(f"Virtual sensor for sequence {seq_name} (port {port}) connected.", "INFO")
                        else:
                            print(f"DEBUG MainWindow: Failed to reinitialize connection for sequence {seq_name} on port {port}")
                        break
        return success

    def save_virtual_sensors(self):
        """Save virtual sensors and sequences to JSON file."""
        path = self.get_virtual_sensors_path()
        # Only create directory if we're saving to a run directory (not the fallback path)
        if path != VIRTUAL_SENSORS_PATH:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"sensors": self.other_sensors, "sequences": getattr(self, "other_sequences", [])}, f, indent=2)
            self.logger.log(f"Saved virtual sensors to {path}")
        except Exception as e:
            self.logger.log(f"Error saving virtual sensors: {e}", "ERROR")

    def get_virtual_sensors_path(self):
        """Return the path to the virtual_sensors.json file (run dir if active, else current dir)."""
        run_dir = self.get_current_run_dir()
        if run_dir and os.path.isdir(run_dir):
            return os.path.join(run_dir, VIRTUAL_SENSORS_FILENAME)
        return VIRTUAL_SENSORS_PATH

    def move_virtual_sensors_to_run(self):
        """Move virtual_sensors.json to the run directory if a run is active."""
        run_dir = self.get_current_run_dir()
        if run_dir and os.path.isdir(run_dir):
            src = VIRTUAL_SENSORS_PATH
            dst = os.path.join(run_dir, VIRTUAL_SENSORS_FILENAME)
            if os.path.exists(src):
                try:
                    import shutil
                    shutil.move(src, dst)
                    self.logger.log(f"Moved virtual sensors config to run dir: {dst}")
                except Exception as e:
                    self.logger.log(f"Error moving virtual sensors config: {e}", "ERROR")

    def get_current_run_dir(self):
        """Get the current run directory from the project controller"""
        if hasattr(self, 'project_controller'):
            return self.project_controller.get_current_run_directory()
        return None
