"""
Sensor Controller

Manages sensor data acquisition and operations.
"""
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit, QDialogButtonBox, QColorDialog, QCheckBox, QFormLayout, QSpinBox, QDoubleSpinBox, QPushButton, QMessageBox, QTableWidgetItem, QWidget, QScrollArea, QTextEdit, QInputDialog, QListWidgetItem)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt
from app.models.sensor_model import SensorModel
from app.utils.common_types import StatusState
from app.models.settings_model import SettingsModel

# Import the LabJack interface
import sys
import os
import queue  # Add this import for queue.Empty exceptions
import time
import collections  # For deque in buffer clearing

# Import from the app.core.interfaces package
try:
    from app.core.interfaces.labjack_interface import LabJackInterface
    print("Successfully imported LabJackInterface from app.core.interfaces")
except ImportError as e:
    print(f"Error importing LabJackInterface: {e}")
    LabJackInterface = None

class SensorController(QObject):
    """Controller for managing sensor operations"""
    
    # Signal emitted when sensor status changes
    status_changed = pyqtSignal()
    
    # Konstante für leere Sensorwerte
    NO_VALUE_DISPLAY = "—"  # Em-Dash für fehlende Werte
    
    def __init__(self, main_window, settings_model: SettingsModel):
        """
        Initialize the sensor controller
        
        Args:
            main_window: The main application window instance
            settings_model: The application's SettingsModel instance
        """
        super().__init__()
        self.main_window = main_window # Correctly assign main_window
        self.settings = settings_model # Use the passed SettingsModel
        self.sensors = []
        self.is_acquiring = False
        self.acquisition_thread = None
        
        # Initialize data structures
        self.acquisition_running = False
        self.connected = False  # Generic connection state
        
        # Initialize LabJack interface reference
        self.labjack_interface = None
        
        # Initialize Arduino monitoring timer
        self._arduino_monitor_timer = None
        
        # Connect signals
        self.connect_signals()
        
        # Initialize the controller (load sensors, start monitoring)
        self.initialize()
    
    def connect_signals(self):
        """Connect UI signals to controller methods"""
        # Don't connect any sensor management buttons here - they're handled by main window
        # IMPORTANT: Don't connect add/edit/remove buttons here - causes conflicts
        # These are now handled by the main window's setup_sensor_tab_signals method
        
        # Connect detection/connection buttons if they exist
        if hasattr(self.main_window, 'detect_arduino_btn'):
            # Only connect if not already connected
            if not self.main_window.detect_arduino_btn.receivers(self.main_window.detect_arduino_btn.clicked):
                self.main_window.detect_arduino_btn.clicked.connect(self.detect_arduino)
        if hasattr(self.main_window, 'connect_arduino_btn'):
            # Only connect if not already connected
            if not self.main_window.connect_arduino_btn.receivers(self.main_window.connect_arduino_btn.clicked):
                self.main_window.connect_arduino_btn.clicked.connect(self.connect_arduino)
        if hasattr(self.main_window, 'connect_labjack_btn'):
            # Only connect if not already connected
            if not self.main_window.connect_labjack_btn.receivers(self.main_window.connect_labjack_btn.clicked):
                self.main_window.connect_labjack_btn.clicked.connect(self.connect_labjack)
        if hasattr(self.main_window, 'labjack_test_btn'):
            # Only connect if not already connected
            if not self.main_window.labjack_test_btn.receivers(self.main_window.labjack_test_btn.clicked):
                self.main_window.labjack_test_btn.clicked.connect(self.test_labjack)
    
    def update_sensor_table(self, update_dropdowns=True):
        """Update the sensor table"""
        from PyQt6.QtWidgets import QTableWidgetItem, QCheckBox, QWidget, QVBoxLayout
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QColor
        
        if not hasattr(self.main_window, 'data_table'):
            return
            
        # Get the table and ensure it has 7 columns
        table = self.main_window.data_table
        
        # Ensure table has 9 columns (added Smooth/Average)
        if table.columnCount() < 9:
            table.setColumnCount(9)
            table.setHorizontalHeaderLabels(["Use", "Sensor", "Value", "Interface", "Offset/Unit", "Stale xInt", "Smooth", "Color", "Cal."])
            table.setColumnWidth(0, 50)  # Use checkbox
            table.setColumnWidth(1, 120)  # Sensor name
            table.setColumnWidth(2, 90)   # Value
            table.setColumnWidth(3, 80)   # Interface
            table.setColumnWidth(4, 95)   # Offset/Unit
            table.setColumnWidth(5, 85)  # Stale xInt
            table.setColumnWidth(6, 55)  # Smooth checkbox
            table.setColumnWidth(7, 70)   # Color
            table.setColumnWidth(8, 50)   # Cal.
        
        # Clear the table rows
        table.setRowCount(0)
        
        # Add rows for each sensor
        for i, sensor in enumerate(self.sensors):
            table.insertRow(i)
            
            # Create a checkbox for "Show in Graph"
            show_checkbox = QCheckBox()
            show_checkbox.setChecked(sensor.show_in_graph)
            show_checkbox.stateChanged.connect(lambda state, s=sensor: self.toggle_sensor_in_graph(s, state))
            
            # Center the checkbox in the cell
            cell_widget = QTableWidgetItem()
            table.setItem(i, 0, cell_widget)
            table.setCellWidget(i, 0, show_checkbox)
            
            # Sensor name
            name_item = QTableWidgetItem(sensor.name)
            table.setItem(i, 1, name_item)
            
            # Current value (check for staleness)
            is_stale = False
            if hasattr(self.main_window, 'data_collection_controller'):
                dcc = self.main_window.data_collection_controller
                hist_key = self.get_historical_buffer_key(sensor)
                if hist_key:
                    timeout_val = dcc._get_stale_timeout_for_key(hist_key)
                    if hist_key in dcc._last_sensor_update:
                        last_ts = dcc._last_sensor_update[hist_key]
                        if time.time() - last_ts > timeout_val:
                            is_stale = True
                    else:
                        is_stale = True

            if is_stale:
                value_text = self.NO_VALUE_DISPLAY
            else:
                value_text = str(sensor.current_value) if sensor.current_value is not None else self.NO_VALUE_DISPLAY
                if sensor.unit and sensor.current_value is not None:
                    value_text += f" {sensor.unit}"
            
            value_item = QTableWidgetItem(value_text)
            table.setItem(i, 2, value_item)
            
            # Interface type
            interface_item = QTableWidgetItem(sensor.interface_type)
            table.setItem(i, 3, interface_item)
            
            # Offset/Unit
            offset_unit = f"{sensor.offset} {sensor.unit}"
            offset_item = QTableWidgetItem(offset_unit)
            table.setItem(i, 4, offset_item)
            
            # Stale factor (multiplier of sampling interval)
            from PyQt6.QtWidgets import QDoubleSpinBox
            stale_spin = QDoubleSpinBox()
            stale_spin.setRange(0.1, 50.0)
            stale_spin.setSingleStep(0.5)
            stale_spin.setDecimals(2)
            default_factor = getattr(sensor, "stale_timeout_factor", None)
            stale_spin.setValue(default_factor if default_factor is not None else 5.0)
            stale_spin.setToolTip("Gap threshold = factor / sampling rate")
            stale_spin.valueChanged.connect(lambda val, s=sensor: self._update_sensor_stale_factor(s, val))
            table.setCellWidget(i, 5, stale_spin)

            # Create a checkbox for "Averaging"
            smooth_checkbox = QCheckBox()
            # Handle potentially missing averaging_enabled on older models
            is_smooth = getattr(sensor, 'averaging_enabled', False)
            smooth_checkbox.setChecked(is_smooth)
            smooth_checkbox.setToolTip("Enable moving average (last 10 values) for this sensor to reduce noise")
            smooth_checkbox.stateChanged.connect(lambda state, s=sensor: self.toggle_sensor_averaging(s, state))
            
            # Center the checkbox in the cell
            smooth_container = QWidget()
            smooth_layout = QVBoxLayout(smooth_container)
            smooth_layout.setContentsMargins(0, 0, 0, 0)
            smooth_layout.setSpacing(0)
            smooth_layout.addStretch()
            smooth_layout.addWidget(smooth_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
            smooth_layout.addStretch()
            table.setCellWidget(i, 6, smooth_container)

            # Color
            # Replace the colored cell with a button
            color_button = QPushButton(sensor.color)
            # Set button color using stylesheet with contrasting text color
            try:
                color_obj = QColor(sensor.color)
                if not color_obj.isValid():
                    color_obj = QColor("#FFFFFF")  # Fallback to white if invalid
                
                # Determine text color based on background brightness for better contrast
                text_color = "black" if color_obj.lightness() > 128 else "white"
                color_style = f"""
                    QPushButton {{
                        background-color: {color_obj.name()};
                        color: {text_color};
                        min-height: 20px;
                        max-height: 20px;
                        padding: 1px 6px;
                        margin: 0px;
                        border: none;
                    }}
                """
            except Exception as e:
                print(f"Error setting button style: {e}")
                color_style = f"""
                    QPushButton {{
                        background-color: {sensor.color};
                        min-height: 20px;
                        max-height: 20px;
                        padding: 1px 6px;
                        margin: 0px;
                        border: none;
                    }}
                """
                
            color_button.setStyleSheet(color_style)
            color_button.setToolTip("Click to change the sensor color")
            
            # Connect button click to color change function
            color_button.clicked.connect(lambda _, s=sensor, r=i: self.change_sensor_color(s, r))
            
            # Wrap button in a container widget with center alignment
            color_container = QWidget()
            color_layout = QVBoxLayout(color_container)
            color_layout.setContentsMargins(0, 0, 0, 0)
            color_layout.setSpacing(0)
            color_layout.addStretch()
            color_layout.addWidget(color_button, alignment=Qt.AlignmentFlag.AlignCenter)
            color_layout.addStretch()
            
            # Add the button container to the table
            table.setCellWidget(i, 7, color_container)
            
            # Calibration button - check if sensor is calibrated
            is_calibrated = self._is_sensor_calibrated(sensor)
            if is_calibrated:
                cal_button = QPushButton("✓")
                cal_button.setStyleSheet("""
                    QPushButton {
                        background-color: #4CAF50;
                        color: white;
                        border: none;
                        border-radius: 4px;
                        font-weight: bold;
                        min-height: 20px;
                        max-height: 20px;
                        padding: 1px 6px;
                        margin: 0px;
                    }
                    QPushButton:hover {
                        background-color: #66BB6A;
                    }
                """)
                cal_button.setToolTip("Calibrated - Click to view/edit calibration")
            else:
                cal_button = QPushButton("🔧")
                cal_button.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #FF9800;
                        border: 1px solid #FF9800;
                        border-radius: 4px;
                        font-weight: bold;
                        min-height: 20px;
                        max-height: 20px;
                        padding: 1px 6px;
                        margin: 0px;
                    }
                    QPushButton:hover {
                        background-color: rgba(255, 152, 0, 0.1);
                        border: 1px solid #FFB74D;
                    }
                """)
                cal_button.setToolTip("Not calibrated - Click to calibrate sensor")
            
            cal_button.clicked.connect(lambda _, s=sensor: self.open_calibration_for_sensor(s))
            
            # Wrap button in a container widget with center alignment
            cal_container = QWidget()
            cal_layout = QVBoxLayout(cal_container)
            cal_layout.setContentsMargins(0, 0, 0, 0)
            cal_layout.setSpacing(0)
            cal_layout.addStretch()
            cal_layout.addWidget(cal_button, alignment=Qt.AlignmentFlag.AlignCenter)
            cal_layout.addStretch()
            
            table.setCellWidget(i, 8, cal_container)
            
            # Set row height to fit buttons properly
            table.setRowHeight(i, 34)
            
        # Update graph dropdowns if requested
        if update_dropdowns:
            self.update_graph_sensor_dropdowns()
            
    def _update_sensor_stale_factor(self, sensor, factor):
        """Update per-sensor stale timeout factor (multiplier of sampling interval)."""
        try:
            sensor.stale_timeout_factor = float(factor)
        except Exception:
            sensor.stale_timeout_factor = None
        self.save_sensors()
        if hasattr(self.main_window, "logger"):
            self.main_window.logger.log(
                f"Set stale timeout factor for {sensor.name} to {sensor.stale_timeout_factor}",
                "INFO"
            )
        # No need to restart; the data collection controller reads factors dynamically
        
    def toggle_sensor_averaging(self, sensor, state):
        """Toggle sensor averaging (smoothing)"""
        # PyQt6 sends the integer value of CheckState, not the enum itself
        # Checked = 2, Unchecked = 0
        sensor.averaging_enabled = int(state) == Qt.CheckState.Checked.value
        
        # Save the updated sensor configuration
        self.save_sensors()
        
        if hasattr(self.main_window, "logger"):
            status = "enabled" if sensor.averaging_enabled else "disabled"
            self.main_window.logger.log(f"Averaging {status} for sensor: {sensor.name}", "INFO")
        
        # Invalidate the ENTIRE sensor cache in data collection controller so the change takes effect immediately
        # We clear the entire cache to ensure no stale sensor references remain
        if hasattr(self.main_window, 'data_collection_controller'):
            dc = self.main_window.data_collection_controller
            dc.invalidate_sensor_cache(None)
        
        # Clear the averaging buffer for this sensor to start fresh
        # This is important both when enabling (to start with clean buffer) and disabling (to clear accumulated data)
        if hasattr(self.main_window, 'data_collection_controller'):
            dc = self.main_window.data_collection_controller
            # Find ALL prefixed keys that match this sensor and clear their buffers
            interface_type = getattr(sensor, 'interface_type', '')
            sensor_name = getattr(sensor, 'name', None)
            sensor_port = getattr(sensor, 'port', None)
            
            # Construct the base prefixed key to match against
            prefixed_key_base = None
            if interface_type.lower() == 'labjack' and sensor_port:
                prefixed_key_base = f"labjack_{sensor_port}"
            elif interface_type.lower() == 'arduino' and sensor_name:
                prefixed_key_base = f"arduino_{sensor_name}"
            elif interface_type.lower() == 'otherserial' and sensor_name:
                prefixed_key_base = f"other_serial_{sensor_name}"
            elif interface_type.lower() == 'audiosensor' and sensor_name:
                prefixed_key_base = f"audio_{sensor_name}"
            elif interface_type.lower() == 'opticalsensor' and sensor_name:
                prefixed_key_base = f"optical_{sensor_name}"
            
            # Clear all buffers that match this sensor (including variants like AIN0_EF_READ_A)
            if prefixed_key_base:
                dc.combined_data_mutex.lock()
                try:
                    cleared_count = 0
                    for buffer_key in list(dc.averaging_buffers.keys()):
                        # For LabJack, check if the buffer key starts with our base or matches exactly
                        if interface_type.lower() == 'labjack':
                            # Match labjack_AIN0 with labjack_AIN0_EF_READ_A or labjack_AIN0
                            if buffer_key == prefixed_key_base or buffer_key.startswith(f"{prefixed_key_base}_"):
                                # Clear buffer - create new empty deque with same maxlen if it's a deque
                                old_buf = dc.averaging_buffers[buffer_key]
                                if isinstance(old_buf, collections.deque):
                                    window_size = old_buf.maxlen if old_buf.maxlen is not None else 100
                                    dc.averaging_buffers[buffer_key] = collections.deque(maxlen=window_size)
                                else:
                                    # Old format or unknown - initialize as deque
                                    window_size = dc._averaging_window_size if dc._averaging_window_size is not None else 10
                                    dc.averaging_buffers[buffer_key] = collections.deque(maxlen=window_size)
                                cleared_count += 1
                        else:
                            # For other interfaces, exact match
                            if buffer_key == prefixed_key_base:
                                # Clear buffer - create new empty deque with same maxlen if it's a deque
                                old_buf = dc.averaging_buffers[buffer_key]
                                if isinstance(old_buf, collections.deque):
                                    window_size = old_buf.maxlen if old_buf.maxlen is not None else 100
                                    dc.averaging_buffers[buffer_key] = collections.deque(maxlen=window_size)
                                else:
                                    # Old format or unknown - initialize as deque
                                    window_size = dc._averaging_window_size if dc._averaging_window_size is not None else 10
                                    dc.averaging_buffers[buffer_key] = collections.deque(maxlen=window_size)
                                cleared_count += 1
                finally:
                    dc.combined_data_mutex.unlock()
        
    def toggle_sensor_in_graph(self, sensor, state):
        """Toggle sensor visibility in graphs"""
        # PyQt6 sends the integer value of CheckState, not the enum itself
        # Checked = 2, Unchecked = 0
        sensor.show_in_graph = int(state) == Qt.CheckState.Checked.value
        
        # Save the updated sensor configuration
        self.save_sensors()
        
        # Emit status changed signal so the nav button icon updates
        self.status_changed.emit()
        
        # Update the graph sensor dropdowns/lists
        self.update_graph_sensor_dropdowns()
        
        # Update the main analysis graph
        if hasattr(self.main_window, 'update_graph'):
            self.main_window.update_graph()
            
        # Refresh tools window if it exists
        if hasattr(self.main_window, '_tools_window') and self.main_window._tools_window:
            self.main_window._tools_window.refresh_sensors()
        elif hasattr(self.main_window, 'tools_window') and self.main_window.tools_window:
            self.main_window.tools_window.refresh_sensors()
        
        # Reinitialize the dashboard graph if data collection is active
        if (hasattr(self.main_window, 'data_collection_controller') and 
            hasattr(self.main_window.data_collection_controller, 'collecting_data') and
            self.main_window.data_collection_controller.collecting_data):
            
            if (hasattr(self.main_window, 'graph_controller') and 
                hasattr(self.main_window.graph_controller, 'live_plotting_active') and
                self.main_window.graph_controller.live_plotting_active):
                
                # Reinitialize the dashboard with the updated sensor list
                print(f"DEBUG: Reinitializing dashboard graph due to sensor toggle: {sensor.name}")
                start_time = self.main_window.data_collection_controller.start_time
                if start_time is not None:
                    self.main_window.graph_controller.start_live_dashboard_update(start_time)
            
    def update_graph_sensor_dropdowns(self):
        """Update graph sensor dropdowns"""
        # Update primary sensor dropdown
        if hasattr(self.main_window, 'graph_primary_sensor'):
            current_text = self.main_window.graph_primary_sensor.currentText()
            self.main_window.graph_primary_sensor.clear()
            
            current_index_to_restore = -1
            
            # Add currently configured sensors
            for i, sensor in enumerate(self.sensors):
                if sensor.enabled and sensor.show_in_graph:  # Only add enabled sensors configured to show in graph
                    historical_key = self.get_historical_buffer_key(sensor)
                    self.main_window.graph_primary_sensor.addItem(sensor.name, userData=historical_key)
                    if sensor.name == current_text:
                        current_index_to_restore = self.main_window.graph_primary_sensor.count() - 1 # Index of the just added item
            
            # Add sensors from control run if available and checkbox is checked
            # Control sensors have '_ctrl' suffix, so they won't conflict with current sensors
            show_control = False
            if hasattr(self.main_window, 'show_control_run_checkbox'):
                show_control = self.main_window.show_control_run_checkbox.isChecked()
            
            if show_control and hasattr(self.main_window, 'control_run_controller'):
                control_sensors = self.main_window.control_run_controller.get_control_run_sensors()
                for sensor_key, sensor_name in control_sensors:
                    display_name = f"{sensor_name} (Control)"
                    self.main_window.graph_primary_sensor.addItem(display_name, userData=sensor_key)
                    if display_name == current_text:
                        current_index_to_restore = self.main_window.graph_primary_sensor.count() - 1
                    
            # Try to restore the previously selected sensor
            if current_index_to_restore != -1:
                self.main_window.graph_primary_sensor.setCurrentIndex(current_index_to_restore)
            elif self.main_window.graph_primary_sensor.count() > 0:
                self.main_window.graph_primary_sensor.setCurrentIndex(0) # Select first item if previous was removed
        
        # Update secondary sensor dropdown
        if hasattr(self.main_window, 'graph_secondary_sensor'):
            current_text = self.main_window.graph_secondary_sensor.currentText()
            self.main_window.graph_secondary_sensor.clear()
            
            current_index_to_restore = -1
            
            # Add currently configured sensors
            for i, sensor in enumerate(self.sensors):
                if sensor.enabled and sensor.show_in_graph:  # Only add enabled sensors configured to show in graph
                    historical_key = self.get_historical_buffer_key(sensor)
                    self.main_window.graph_secondary_sensor.addItem(sensor.name, userData=historical_key)
                    if sensor.name == current_text:
                        current_index_to_restore = self.main_window.graph_secondary_sensor.count() - 1
            
            # Add sensors from control run if available and checkbox is checked
            # Control sensors have '_ctrl' suffix, so they won't conflict with current sensors
            show_control = False
            if hasattr(self.main_window, 'show_control_run_checkbox'):
                show_control = self.main_window.show_control_run_checkbox.isChecked()
            
            if show_control and hasattr(self.main_window, 'control_run_controller'):
                control_sensors = self.main_window.control_run_controller.get_control_run_sensors()
                for sensor_key, sensor_name in control_sensors:
                    display_name = f"{sensor_name} (Control)"
                    self.main_window.graph_secondary_sensor.addItem(display_name, userData=sensor_key)
                    if display_name == current_text:
                        current_index_to_restore = self.main_window.graph_secondary_sensor.count() - 1
                    
            # Try to restore the previously selected sensor
            if current_index_to_restore != -1:
                self.main_window.graph_secondary_sensor.setCurrentIndex(current_index_to_restore)
            elif self.main_window.graph_secondary_sensor.count() > 0:
                self.main_window.graph_secondary_sensor.setCurrentIndex(0)
                
        # Update multi-sensor list
        if hasattr(self.main_window, 'multi_sensor_list'):
            # Remember which items were selected by historical key
            selected_keys = set()
            for i in range(self.main_window.multi_sensor_list.count()):
                item = self.main_window.multi_sensor_list.item(i)
                if item.isSelected():
                    key = item.data(Qt.ItemDataRole.UserRole)
                    if key:
                        selected_keys.add(key)
            
            # Clear and repopulate the list
            self.main_window.multi_sensor_list.clear()
            
            items_to_reselect = []
            
            # Add currently configured sensors
            for sensor in self.sensors:
                if sensor.enabled and sensor.show_in_graph:  # Only add enabled sensors configured to show in graph
                    historical_key = self.get_historical_buffer_key(sensor)
                    item = QListWidgetItem(sensor.name)
                    item.setData(Qt.ItemDataRole.UserRole, historical_key)
                    self.main_window.multi_sensor_list.addItem(item)
                    if historical_key in selected_keys:
                        items_to_reselect.append(item)
            
            # Add sensors from control run if available and checkbox is checked
            # Control sensors have '_ctrl' suffix, so they won't conflict with current sensors
            show_control = False
            if hasattr(self.main_window, 'show_control_run_checkbox'):
                show_control = self.main_window.show_control_run_checkbox.isChecked()
            
            if show_control and hasattr(self.main_window, 'control_run_controller'):
                control_sensors = self.main_window.control_run_controller.get_control_run_sensors()
                for sensor_key, sensor_name in control_sensors:
                    display_name = f"{sensor_name} (Control)"
                    item = QListWidgetItem(display_name)
                    item.setData(Qt.ItemDataRole.UserRole, sensor_key)
                    self.main_window.multi_sensor_list.addItem(item)
                    if sensor_key in selected_keys:
                        items_to_reselect.append(item)
            
            # Reselect items that were selected before
            for item in items_to_reselect:
                item.setSelected(True)
            
            # If Standard Time Series is selected and no items were previously selected, select all by default
            if hasattr(self.main_window, 'graph_type_combo'):
                graph_type = self.main_window.graph_type_combo.currentText()
                if graph_type == "Standard Time Series" and len(items_to_reselect) == 0:
                    # Select all items in the multi-sensor list
                    for i in range(self.main_window.multi_sensor_list.count()):
                        self.main_window.multi_sensor_list.item(i).setSelected(True)
    
    def add_sensor(self):
        """Add a new sensor"""
        try:
            print("Starting add_sensor method")
            
            # Create a new dialog for adding a sensor
            dialog = QDialog(self.main_window)
            dialog.setWindowTitle("Add Sensor")
            dialog.setMinimumWidth(400)
            
            print("Created dialog")
            
            # Main layout
            layout = QVBoxLayout(dialog)
            
            # Form layout for inputs
            form_layout = QFormLayout()
            
            # Device type selection (Arduino, LabJack, etc.)
            device_type_combo = QComboBox()
            device_type_combo.addItem("Arduino")
            device_type_combo.addItem("LabJack")
            device_type_combo.addItem("MQTT")
            device_type_combo.addItem("Other/Virtual Sensor")
            device_type_combo.addItem("Optical Sensor")
            device_type_combo.addItem("Read CSV")
            device_type_combo.setCurrentIndex(0)  # Default to Arduino
            
            print("Created device type combo")
            
            # Enable LabJack option if we have the interface module
            try:
                from app.core.interfaces.labjack_interface import LabJackInterface
                # LabJack option should be enabled if we have the module
                print("Successfully imported LabJackInterface, enabling option")
            except ImportError as e:
                print(f"Could not import LabJackInterface, disabling option: {e}")
                device_type_combo.model().item(1).setEnabled(False)  # Disable LabJack option
                
            form_layout.addRow("Device Type:", device_type_combo)
            
            # Port selection container (will be updated based on device type)
            port_container = QWidget()
            port_layout = QHBoxLayout(port_container)
            port_layout.setContentsMargins(0, 0, 0, 0)
            
            # Arduino port selection widgets
            arduino_port_combo = QComboBox()
            refresh_btn = QPushButton("Refresh")
            port_layout.addWidget(arduino_port_combo)
            port_layout.addWidget(refresh_btn)
            
            # Function to refresh Arduino ports
            def refresh_arduino_ports():
                arduino_port_combo.clear()
                try:
                    if hasattr(self.main_window, 'data_collection_controller'):
                        available_ports = self.main_window.data_collection_controller.get_arduino_ports()
                        for port in available_ports:
                            arduino_port_combo.addItem(port)
                        if len(available_ports) > 0:
                            arduino_port_combo.setCurrentIndex(0)
                        print(f"Found {len(available_ports)} Arduino port(s): {', '.join(available_ports) if available_ports else 'None'}")
                except Exception as e:
                    self.main_window.logger.log(f"Error refreshing ports: {str(e)}", "ERROR")
                    QMessageBox.warning(dialog, "Port Refresh", f"Error refreshing ports: {str(e)}")
            
            # Automatically refresh Arduino ports if Arduino is connected
            if device_type_combo.currentText() == "Arduino" and hasattr(self.main_window, 'data_collection_controller'):
                if 'arduino' in self.main_window.data_collection_controller.interfaces and \
                   self.main_window.data_collection_controller.interfaces['arduino']['connected']:
                    print("Arduino is connected, auto-refreshing ports")
                    refresh_arduino_ports()
                else:
                    print("Arduino is not connected, deferring port refresh to user action")
            
            # LabJack channel selection widgets
            labjack_channel_combo = QComboBox()
            labjack_channel_combo.setVisible(False)  # Hide initially
            port_layout.addWidget(labjack_channel_combo)
            
            # CSV Mapping selection widgets
            csv_mapping_combo = QComboBox()
            csv_mapping_combo.setVisible(False)  # Hide initially
            port_layout.addWidget(csv_mapping_combo)
            
            form_layout.addRow("Port/Channel:", port_container)
            
            # Function to populate LabJack channels
            def populate_labjack_channels():
                labjack_channel_combo.clear()
                
                # Try to get detailed channel information
                channels_info = self.get_labjack_channels_info()
                
                if channels_info:
                    # Group channels by type for better organization
                    analog_inputs = []
                    digital_ios = []
                    ef_channels = []
                    analog_outputs = []
                    
                    # Sort channels by type
                    for channel in channels_info:
                        channel_type = channel.get("type", "")
                        if channel_type == "analog_input":
                            analog_inputs.append(channel)
                        elif channel_type == "digital_io":
                            digital_ios.append(channel)
                        elif channel_type.startswith("ef_"):
                            ef_channels.append(channel)
                        elif channel_type == "analog_output":
                            analog_outputs.append(channel)
                    
                    # Add channels to combo box with headers for each type
                    if analog_inputs:
                        labjack_channel_combo.addItem("--- Analog Inputs ---")
                        for channel in analog_inputs:
                            labjack_channel_combo.addItem(f"{channel['name']} - {channel['description']}")
                    
                    if digital_ios:
                        labjack_channel_combo.addItem("--- Digital I/O ---")
                        for channel in digital_ios:
                            labjack_channel_combo.addItem(f"{channel['name']} - {channel['description']}")
                    
                    if ef_channels:
                        labjack_channel_combo.addItem("--- Extended Features ---")
                        for channel in ef_channels:
                            labjack_channel_combo.addItem(f"{channel['name']} - {channel['description']}")
                    
                    if analog_outputs:
                        labjack_channel_combo.addItem("--- Analog Outputs ---")
                        for channel in analog_outputs:
                            labjack_channel_combo.addItem(f"{channel['name']} - {channel['description']}")
                else:
                    # Fall back to simple channel list if detailed info not available
                    channels = self.get_labjack_channels()
                    for channel in channels:
                        labjack_channel_combo.addItem(channel)
            
            # Function to handle device type change
            def on_device_type_changed(index):
                device_type = device_type_combo.currentText()
                if device_type == "Arduino":
                    arduino_port_combo.setVisible(True)
                    refresh_btn.setVisible(True)
                    labjack_channel_combo.setVisible(False)
                    # Don't auto-refresh here, let the user click the refresh button
                elif device_type == "LabJack":
                    arduino_port_combo.setVisible(False)
                    refresh_btn.setVisible(False)
                    labjack_channel_combo.setVisible(True)
                    csv_mapping_combo.setVisible(False)
                    if hasattr(self, 'mqtt_topic_input'): self.mqtt_topic_input.setVisible(False)
                    populate_labjack_channels()  # Populate channels when switching to LabJack
                elif device_type == "MQTT":
                    arduino_port_combo.setVisible(False)
                    refresh_btn.setVisible(False)
                    labjack_channel_combo.setVisible(False)
                    csv_mapping_combo.setVisible(False)
                    if not hasattr(self, 'mqtt_topic_input'):
                        self.mqtt_topic_input = QLineEdit()
                        self.mqtt_topic_input.setPlaceholderText("e.g. sensors/temperature")
                        port_layout.addWidget(self.mqtt_topic_input)
                    self.mqtt_topic_input.setVisible(True)
                elif device_type == "Read CSV":
                    arduino_port_combo.setVisible(False)
                    refresh_btn.setVisible(False)
                    labjack_channel_combo.setVisible(False)
                    csv_mapping_combo.setVisible(True)
                    if hasattr(self, 'mqtt_topic_input'): self.mqtt_topic_input.setVisible(False)
                    
                    # Populate CSV mappings
                    csv_mapping_combo.clear()
                    csv_configs = getattr(self.main_window, 'csv_configs', [])
                    for cfg in csv_configs:
                        file_name = os.path.basename(cfg.get('file', 'Unknown'))
                        for mapping in cfg.get('mappings', []):
                            sensor_name = mapping.get('sensor_name', 'Unnamed')
                            csv_mapping_combo.addItem(f"{sensor_name} (from {file_name})", sensor_name)
                    
                    if csv_mapping_combo.count() == 0:
                        csv_mapping_combo.addItem("No CSV mappings configured")
                        csv_mapping_combo.setEnabled(False)
                    else:
                        csv_mapping_combo.setEnabled(True)
                elif device_type == "Other/Virtual Sensor":
                    # First check if we have any sequences with published variables
                    other_sequences = getattr(self.main_window, 'other_sequences', [])
                    
                    # Check if we have any sequences with published variables
                    has_valid_sequences = False
                    for seq in other_sequences:
                        for action in seq.get("actions", []):
                            if action.get("type") == "publish" and action.get("target"):
                                has_valid_sequences = True
                                break
                        if has_valid_sequences:
                            break
                    
                    if not has_valid_sequences:
                        # No published variables found, need to create sequences first
                        result = QMessageBox.question(
                            self.main_window,
                            "Create Sequences First",
                            "Before adding a virtual sensor, you need to create sequences with published variables.\n\n"
                            "Would you like to open the sequence management dialog now?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        )
                        
                        if result == QMessageBox.StandardButton.Yes:
                            # Close this dialog
                            dialog.reject()
                            
                            # Show the sequence management dialog
                            if hasattr(self.main_window, 'show_other_settings_popup'):
                                self.main_window.show_other_settings_popup()
                            return
                    else:
                        # We have valid sequences, proceed with the sensor dialog
                        from app.ui.dialogs.other_sensors_dialog import AddEditSensorDialog
                        
                        # Close the current dialog
                        dialog.reject()
                        
                        # Open AddEditSensorDialog
                        sensor_dialog = AddEditSensorDialog(self.main_window, sequences=other_sequences)
                        if sensor_dialog.exec():
                            # Get the new sensor configuration
                            new_sensor = sensor_dialog.get_sensor()
                            
                            # Create OtherSerial sensor
                            name = new_sensor.get("name", "")
                            sensor_type = new_sensor.get("type", "")
                            mapping = new_sensor.get("mapping", "")
                            
                            # Add to main_window.other_sensors
                            if name and mapping:
                                # Create sensor model
                                from app.models.sensor_model import SensorModel
                                
                                # Create dictionary for sensor (needed for both places)
                                sensor_dict = {
                                    "name": name,
                                    "type": sensor_type,
                                    "mapping": mapping,
                                    "interface_type": "OtherSerial"
                                }
                                
                                # Add to other_sensors list for persistence
                                if not hasattr(self.main_window, 'other_sensors'):
                                    self.main_window.other_sensors = []
                                self.main_window.other_sensors.append(sensor_dict)
                                
                                # Add to main sensor list
                                sensor_model = SensorModel.from_dict(sensor_dict)
                                self.add_sensor_to_list(sensor_model)
                                
                                # Save the configuration
                                if hasattr(self.main_window, 'save_virtual_sensors'):
                                    self.main_window.save_virtual_sensors()
                                    
                                # Update the sensor table
                                self.update_sensor_table()
                                
                                # Connect any associated sequence
                                if hasattr(self.main_window, 'data_collection_controller') and ":" in mapping:
                                    seq_name, var_name = mapping.split(":", 1)
                                    # Find the sequence by name
                                    for sequence in other_sequences:
                                        if sequence.get("name") == seq_name:
                                            # Create the sequence object and connect
                                            port = sequence.get("port", "")
                                            baud = sequence.get("baud", 9600)
                                            poll_interval = sequence.get("poll_interval", 1.0)
                                            steps = sequence.get("actions", [])
                                            
                                            # Connect sequence if not already connected
                                            self.main_window.data_collection_controller.connect_other_serial(
                                                port=port,
                                                baud_rate=baud,
                                                poll_interval=poll_interval,
                                                sequence=self.main_window.data_collection_controller.create_serial_sequence(seq_name, steps)
                                            )
                                            break
                    return
                elif device_type == "Optical Sensor":
                    # Close the current dialog and open the Optical Sensor dialog
                    dialog.reject()
                    
                    # Open the Optical Sensor add dialog
                    self._show_add_optical_sensor_dialog()
                    return
            
            # Connect the device type combo box change event
            device_type_combo.currentIndexChanged.connect(on_device_type_changed)
            
            # Function to update sensor name text field when LabJack channel is selected
            def on_labjack_channel_changed(index):
                # Only process valid selections (skip headers)
                channel_text = labjack_channel_combo.currentText()
                if not channel_text.startswith("---"):
                    # Extract the channel name and update the sensor name field
                    channel_name = self._extract_channel_name(channel_text)
                    if channel_name:
                        sensor_name_edit.setText(channel_name)
            
            # Connect the LabJack channel combo box change event
            labjack_channel_combo.currentIndexChanged.connect(on_labjack_channel_changed)
            
            # Function to update sensor name text field when CSV mapping is selected
            def on_csv_mapping_changed(index):
                sensor_name = csv_mapping_combo.currentData()
                if sensor_name:
                    sensor_name_edit.setText(sensor_name)
            
            # Connect the CSV mapping combo box change event
            csv_mapping_combo.currentIndexChanged.connect(on_csv_mapping_changed)
            
            # Automatically refresh Arduino ports if Arduino is connected
            if device_type_combo.currentText() == "Arduino" and hasattr(self.main_window, 'data_collection_controller'):
                if 'arduino' in self.main_window.data_collection_controller.interfaces and \
                   self.main_window.data_collection_controller.interfaces['arduino']['connected']:
                    print("Arduino is connected, auto-refreshing ports")
                    refresh_arduino_ports()
                else:
                    print("Arduino is not connected, deferring port refresh to user action")
            
            # Connect the refresh button
            refresh_btn.clicked.connect(refresh_arduino_ports)
            
            # Sensor selection - dynamically populated from available Arduino sensors
            sensor_name_combo = QComboBox()
            sensor_name_edit = QLineEdit()
            sensor_name_layout = QVBoxLayout()
            
            # Try to get available sensor names from Arduino data
            available_sensors = []
            if hasattr(self.main_window, 'data_collection_controller'):
                available_sensors = self.main_window.data_collection_controller.get_available_sensor_names()
            
            # Add a custom option in case user wants to enter a name manually
            sensor_name_combo.addItem("-- Select a sensor --")
            if available_sensors:
                for sensor_name in available_sensors:
                    sensor_name_combo.addItem(sensor_name)
                sensor_name_combo.addItem("Custom (enter name below)")
                sensor_name_edit.setPlaceholderText("Enter custom sensor name if needed")
                sensor_name_edit.setEnabled(False)
            else:
                sensor_name_combo.addItem("Custom (enter name below)")
                sensor_name_edit.setPlaceholderText("No sensors detected - enter sensor name")
                sensor_name_edit.setEnabled(True)
            
            # Function to handle sensor combo selection change
            def on_sensor_combo_changed(index):
                if sensor_name_combo.currentText() == "Custom (enter name below)":
                    sensor_name_edit.setEnabled(True)
                    sensor_name_edit.clear()
                else:
                    sensor_name_edit.setEnabled(False)
                    sensor_name_edit.setText(sensor_name_combo.currentText())
            
            # Function to handle device type change for sensor names
            def update_sensor_name_options(index):
                device_type = device_type_combo.currentText()
                if device_type == "LabJack" or device_type == "Read CSV":
                    # For LabJack and CSV, hide the dropdown and enable text field directly
                    sensor_name_combo.setVisible(False)
                    sensor_name_edit.setVisible(True)
                    sensor_name_edit.setEnabled(True)
                    
                    # Set a placeholder text
                    sensor_name_edit.setPlaceholderText("Enter sensor name")
                else:
                    # For Arduino, restore original behavior
                    sensor_name_combo.setVisible(True)
                    sensor_name_edit.setVisible(True)
                    sensor_name_combo.clear()
                    sensor_name_combo.addItem("-- Select a sensor --")
                    if available_sensors:
                        for sensor_name in available_sensors:
                            sensor_name_combo.addItem(sensor_name)
                        sensor_name_combo.addItem("Custom (enter name below)")
                        sensor_name_edit.setEnabled(False)
                    else:
                        sensor_name_combo.addItem("Custom (enter name below)")
                        sensor_name_edit.setEnabled(True)
            
            # Connect device type change to sensor name options update
            device_type_combo.currentIndexChanged.connect(update_sensor_name_options)
            
            sensor_name_combo.currentIndexChanged.connect(on_sensor_combo_changed)
            sensor_name_layout.addWidget(sensor_name_combo)
            sensor_name_layout.addWidget(sensor_name_edit)
            form_layout.addRow("Sensor Name:", sensor_name_layout)
            
            # Offset and unit
            offset_layout = QHBoxLayout()
            offset_spinbox = QDoubleSpinBox()
            offset_spinbox.setDecimals(2)
            offset_spinbox.setRange(-9999, 9999)
            offset_spinbox.setValue(0.00)
            offset_layout.addWidget(offset_spinbox)
            
            unit_edit = QLineEdit()
            unit_edit.setPlaceholderText("Unit (e.g. °C, bar)")
            offset_layout.addWidget(unit_edit)
            form_layout.addRow("Offset/Unit:", offset_layout)
            
            # Color picker
            color_button = QPushButton("Choose Color")
            selected_color = QColor("#4287f5")
            
            def update_color_button():
                color_style = f"background-color: {selected_color.name()}; color: {'black' if selected_color.lightness() > 128 else 'white'};"
                color_button.setStyleSheet(color_style)
                
            update_color_button()
            
            def choose_color():
                nonlocal selected_color
                color = QColorDialog.getColor(selected_color, dialog, "Choose Sensor Color")
                if color.isValid():
                    selected_color = color
                    update_color_button()
                    
            color_button.clicked.connect(choose_color)
            form_layout.addRow("Color:", color_button)
            
            # Show in graph checkbox
            show_in_graph = QCheckBox("Show in Graph")
            show_in_graph.setChecked(True)
            form_layout.addRow("", show_in_graph)
            
            layout.addLayout(form_layout)
            
            # Dialog buttons
            button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)
            layout.addWidget(button_box)
            
            # Execute the dialog
            print("About to show dialog")
            result = dialog.exec()
            print(f"Dialog result: {result}")
            
            if result == QDialog.DialogCode.Accepted:
                # Process accepted result
                print("Dialog accepted, processing input")
                
                device_type = device_type_combo.currentText()
                
                # Get the sensor name based on device type
                if device_type == "LabJack" or device_type == "Read CSV":
                    # For LabJack/CSV, just use the text from the edit field
                    name = sensor_name_edit.text()
                else:
                    # For Arduino, use existing logic
                    name = sensor_name_edit.text() if sensor_name_edit.isEnabled() else sensor_name_combo.currentText()
                
                # Create the sensor based on device type
                if device_type == "LabJack":
                    # For LabJack, use our specialized method
                    port = self._extract_channel_name(labjack_channel_combo.currentText())
                    
                    new_sensor = self.create_labjack_sensor(
                        name=name,
                        port=port,
                        unit=unit_edit.text(),
                        offset=offset_spinbox.value(),
                        conversion_factor=1.0,  # Default to 1.0 for now
                        color=selected_color.name(),
                        enabled=True,
                        show_in_graph=show_in_graph.isChecked()
                    )
                elif device_type == "Read CSV":
                    # For CSV, use the selected mapping name as port
                    port = f"csv_{csv_mapping_combo.currentData()}"
                    new_sensor = SensorModel(
                        name=name,
                        interface_type="CSV",
                        port=port,
                        unit=unit_edit.text(),
                        offset=offset_spinbox.value(),
                        conversion_factor=1.0,
                        color=selected_color.name(),
                        enabled=True,
                        show_in_graph=show_in_graph.isChecked(),
                        stale_timeout_factor=3.0, # Set stale factor to 3x sampling interval
                        averaging_enabled=False
                    )
                elif device_type == "MQTT":
                    # For MQTT, use the topic input
                    port = self.mqtt_topic_input.text().strip() if hasattr(self, 'mqtt_topic_input') else ""
                    new_sensor = SensorModel(
                        name=name,
                        interface_type="MQTT",
                        port=port,
                        unit=unit_edit.text(),
                        offset=offset_spinbox.value(),
                        conversion_factor=1.0,
                        color=selected_color.name(),
                        enabled=True,
                        show_in_graph=show_in_graph.isChecked(),
                        stale_timeout_factor=None, # Default for new sensor
                        averaging_enabled=False    # Default for new sensor
                    )
                    
                    # Automatically subscribe if connected
                    if hasattr(self.main_window, 'data_collection_controller'):
                        dcc = self.main_window.data_collection_controller
                        if hasattr(dcc, 'mqtt_thread') and dcc.mqtt_thread.is_connected() and port:
                            dcc.mqtt_thread.subscribe(port)
                else:
                    # For other device types, use the standard creation method
                    new_sensor = SensorModel(
                        name=name,
                        interface_type=device_type,
                        port=self._extract_channel_name(arduino_port_combo.currentText() if device_type == "Arduino" else labjack_channel_combo.currentText()),
                        unit=unit_edit.text(),
                        offset=offset_spinbox.value(),
                        conversion_factor=1.0,  # Default to 1.0 for now (removed from UI)
                        color=selected_color.name(),
                        enabled=True,
                        show_in_graph=show_in_graph.isChecked(),
                        stale_timeout_factor=None,
                        averaging_enabled=False
                    )
                    
                    # If Arduino sensor was created with a name that matches available_sensors, set empty port to support direct name matching
                    if device_type == "Arduino" and name in available_sensors:
                        new_sensor.port = ""  # Empty port to force name-based matching
                
                # Log detailed information about the sensor being created
                self.main_window.logger.log(f"Creating new sensor: {new_sensor.name} ({new_sensor.interface_type})")
                self.main_window.logger.log(f"  - Port/Channel: {new_sensor.port}")
                self.main_window.logger.log(f"  - Unit: {new_sensor.unit}")
                self.main_window.logger.log(f"  - Offset: {new_sensor.offset}")
                self.main_window.logger.log(f"  - Color: {new_sensor.color}")
                self.main_window.logger.log(f"  - Show in Graph: {new_sensor.show_in_graph}")
                
                # Additional debugging for LabJack sensors
                if device_type == "LabJack":
                    self.main_window.logger.log(f"  - LabJack sensor details:")
                    self.main_window.logger.log(f"    - Conversion factor: {new_sensor.conversion_factor}")
                    self.main_window.logger.log(f"    - Offset: {new_sensor.offset}")
                    self.main_window.logger.log(f"    - Enabled: {new_sensor.enabled}")
                    self.main_window.logger.log(f"    - Raw port value: '{new_sensor.port}'")
                
                # Post-processing for specific sensor types
                if device_type == "LabJack":
                    # Ensure all necessary properties are set for LabJack sensors
                    self.main_window.logger.log(f"Post-processing LabJack sensor: {new_sensor.name}")
                    # Sanitize the new LabJack sensor to ensure all properties are correct
                    self._sanitize_labjack_sensor(new_sensor)
                    
                    # Log the final state after sanitizing
                    self.main_window.logger.log(f"  - LabJack sensor after sanitizing:")
                    self.main_window.logger.log(f"    - Port: {new_sensor.port}")
                    self.main_window.logger.log(f"    - Conversion factor: {new_sensor.conversion_factor}")
                    self.main_window.logger.log(f"    - Offset: {new_sensor.offset}")
                    self.main_window.logger.log(f"    - Color: {new_sensor.color}")
                
                # Add the new sensor to the list
                self.sensors.append(new_sensor)
                
                # Update the UI
                if hasattr(self.main_window, 'data_table'):
                    self.update_sensor_table()
                    
                # Log the new sensor addition
                self.main_window.logger.log(f"Added new sensor: {new_sensor.name}")
                
                # Update status indicators immediately
                if hasattr(self.main_window, 'update_status_indicators'):
                    self.main_window.update_status_indicators()
                
                # Reinitialize the dashboard graph if data collection is active
                if (hasattr(self.main_window, 'data_collection_controller') and 
                    hasattr(self.main_window.data_collection_controller, 'collecting_data') and
                    self.main_window.data_collection_controller.collecting_data):
                    
                    if (hasattr(self.main_window, 'graph_controller') and 
                        hasattr(self.main_window.graph_controller, 'live_plotting_active') and
                        self.main_window.graph_controller.live_plotting_active):
                        
                        # Reinitialize the dashboard with the updated sensor list
                        print(f"DEBUG: Reinitializing dashboard graph due to sensor addition: {new_sensor.name}")
                        start_time = self.main_window.data_collection_controller.start_time
                        if start_time is not None:
                            self.main_window.graph_controller.start_live_dashboard_update(start_time)
                
            # After adding, emit the status changed signal
            self.status_changed.emit()
            return True
            
        except Exception as e:
            print(f"Error in add_sensor: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _extract_channel_name(self, display_text):
        """Extract the actual channel name from a display string
        
        Args:
            display_text: The display text which may include description
            
        Returns:
            str: The clean channel name
        """
        # If the text contains a dash (like "AIN0 - Analog Input 0"), extract the first part
        if " - " in display_text:
            return display_text.split(" - ")[0].strip()
        
        # Section headers in combos are marked with dashes
        if display_text.startswith("---"):
            return ""
            
        # Otherwise return as is
        return display_text.strip()
    
    def edit_sensor(self):
        """Edit the selected sensor"""
        # Get the selected row
        if not hasattr(self.main_window, 'data_table'):
            return
            
        selected_rows = self.main_window.data_table.selectedItems()
        if not selected_rows:
            # Show an error message
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self.main_window,
                "Edit Sensor",
                "Please select a sensor to edit first.",
                QMessageBox.StandardButton.Ok
            )
            return
            
        # Get the row index of the first selected item
        row = selected_rows[0].row()
        
        # Check if a sensor exists at this index
        if row < 0 or row >= len(self.sensors):
            return
            
        # Get the sensor to edit
        sensor = self.sensors[row]
        
        # Different handling based on sensor type
        if sensor.interface_type == "Arduino":
            # Implement Arduino sensor editing
            self.main_window.logger.log(f"Editing Arduino sensor {sensor.name}")
            
            from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit, 
                                       QDoubleSpinBox, QComboBox, QCheckBox, 
                                       QDialogButtonBox, QColorDialog, QPushButton,
                                       QHBoxLayout)
            from PyQt6.QtGui import QColor
            
            # Create dialog
            dialog = QDialog(self.main_window)
            dialog.setWindowTitle(f"Edit Arduino Sensor: {sensor.name}")
            dialog.setMinimumWidth(400)
            
            # Main layout
            layout = QVBoxLayout(dialog)
            
            # Form layout
            form_layout = QFormLayout()
            
            # Sensor name
            name_edit = QLineEdit(sensor.name)
            form_layout.addRow("Name:", name_edit)
            
            # Unit
            unit_edit = QLineEdit(sensor.unit)
            form_layout.addRow("Unit:", unit_edit)
            
            # Offset
            offset_spinbox = QDoubleSpinBox()
            offset_spinbox.setDecimals(2)
            offset_spinbox.setRange(-9999, 9999)
            offset_spinbox.setValue(sensor.offset)
            form_layout.addRow("Offset:", offset_spinbox)
            
            # Arduino port selection
            port_layout = QHBoxLayout()
            arduino_port_combo = QComboBox()
            refresh_btn = QPushButton("Refresh")
            port_layout.addWidget(arduino_port_combo)
            port_layout.addWidget(refresh_btn)
            
            # Function to refresh Arduino ports in edit mode
            def refresh_arduino_ports():
                current_port = sensor.port
                arduino_port_combo.clear()
                try:
                    if hasattr(self.main_window, 'data_collection_controller'):
                        available_ports = self.main_window.data_collection_controller.get_arduino_ports()
                        
                        # Add the current port first if it exists but is not in the list
                        if current_port and current_port not in available_ports:
                            arduino_port_combo.addItem(current_port)
                            
                        # Add all available ports
                        for port in available_ports:
                            if port != current_port:  # Avoid duplicates
                                arduino_port_combo.addItem(port)
                                
                        # Select the current port if it exists
                        if current_port:
                            index = arduino_port_combo.findText(current_port)
                            if index >= 0:
                                arduino_port_combo.setCurrentIndex(index)
                        elif len(available_ports) > 0:
                            arduino_port_combo.setCurrentIndex(0)
                        
                        print(f"Found {len(available_ports)} Arduino port(s): {', '.join(available_ports) if available_ports else 'None'}")
                except Exception as e:
                    self.main_window.logger.log(f"Error refreshing ports: {str(e)}", "ERROR")
                    QMessageBox.warning(dialog, "Port Refresh", f"Error refreshing ports: {str(e)}")
            
            # Connect refresh button
            refresh_btn.clicked.connect(refresh_arduino_ports)
            
            # Do initial refresh
            refresh_arduino_ports()
            
            # Add to form layout
            form_layout.addRow("Port:", port_layout)
            
            # Color picker
            color_button = QPushButton("Choose Color")
            current_color = QColor(sensor.color)
            
            # Update button color
            def update_color_button():
                color_style = f"background-color: {current_color.name()}; color: {'black' if current_color.lightness() > 128 else 'white'};"
                color_button.setStyleSheet(color_style)
                
            update_color_button()
            
            # Choose color function
            def choose_color():
                nonlocal current_color
                color = QColorDialog.getColor(current_color, dialog, "Choose Sensor Color")
                if color.isValid():
                    current_color = color
                    update_color_button()
                    
            color_button.clicked.connect(choose_color)
            form_layout.addRow("Color:", color_button)
            
            # Show in graph checkbox
            show_in_graph = QCheckBox("Show in Graph")
            show_in_graph.setChecked(sensor.show_in_graph)
            form_layout.addRow("", show_in_graph)
            
            layout.addLayout(form_layout)
            
            # Dialog buttons
            button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)
            layout.addWidget(button_box)
            
            # Execute the dialog
            result = dialog.exec()
            
            if result == QDialog.DialogCode.Accepted:
                # Update sensor properties
                # Create a new Arduino sensor with updated values
                updated_sensor = SensorModel(
                    name=name_edit.text(),
                    interface_type="Arduino",
                    port=arduino_port_combo.currentText(),  # Use the selected port
                    unit=unit_edit.text(),
                    offset=offset_spinbox.value(),
                    color=current_color.name(),
                    show_in_graph=show_in_graph.isChecked(),
                    stale_timeout_factor=getattr(sensor, 'stale_timeout_factor', None),
                    averaging_enabled=getattr(sensor, 'averaging_enabled', False)
                )
                
                # Replace the old sensor with the updated one
                self.sensors[row] = updated_sensor
                
                # Save the updated sensor configuration
                self.save_sensors()
                
                # Update the UI
                self.update_sensor_table()
                
                # Log the sensor update
                self.main_window.logger.log(f"Updated Arduino sensor: {name_edit.text()}")
                
                # Emit status changed signal
                self.status_changed.emit()
                
        elif sensor.interface_type == "LabJack":
            # Implement LabJack sensor editing
            self.main_window.logger.log(f"Editing LabJack sensor {sensor.name}")
            
            from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit, 
                                       QDoubleSpinBox, QComboBox, QCheckBox, 
                                       QDialogButtonBox, QColorDialog, QPushButton)
            from PyQt6.QtGui import QColor
            
            # Create dialog
            dialog = QDialog(self.main_window)
            dialog.setWindowTitle(f"Edit LabJack Sensor: {sensor.name}")
            dialog.setMinimumWidth(400)
            
            # Main layout
            layout = QVBoxLayout(dialog)
            
            # Form layout
            form_layout = QFormLayout()
            
            # Channel selection
            channel_combo = QComboBox()
            form_layout.addRow("Channel:", channel_combo)
            
            # Populate channels
            channels_info = self.get_labjack_channels_info()
            current_channel = sensor.port
            current_channel_index = 0
            
            if channels_info:
                # Group channels by type for better organization
                analog_inputs = []
                digital_ios = []
                ef_channels = []
                analog_outputs = []
                
                # Sort channels by type
                for channel in channels_info:
                    channel_type = channel.get("type", "")
                    if channel_type == "analog_input":
                        analog_inputs.append(channel)
                    elif channel_type == "digital_io":
                        digital_ios.append(channel)
                    elif channel_type.startswith("ef_"):
                        ef_channels.append(channel)
                    elif channel_type == "analog_output":
                        analog_outputs.append(channel)
                
                # Add channels to combo box with headers for each type
                if analog_inputs:
                    channel_combo.addItem("--- Analog Inputs ---")
                    for i, channel in enumerate(analog_inputs):
                        display_text = f"{channel['name']} - {channel['description']}"
                        channel_combo.addItem(display_text)
                        if channel['name'] == current_channel:
                            current_channel_index = channel_combo.count() - 1
                
                if digital_ios:
                    channel_combo.addItem("--- Digital I/O ---")
                    for i, channel in enumerate(digital_ios):
                        display_text = f"{channel['name']} - {channel['description']}"
                        channel_combo.addItem(display_text)
                        if channel['name'] == current_channel:
                            current_channel_index = channel_combo.count() - 1
                
                if ef_channels:
                    channel_combo.addItem("--- Extended Features ---")
                    for i, channel in enumerate(ef_channels):
                        display_text = f"{channel['name']} - {channel['description']}"
                        channel_combo.addItem(display_text)
                        if channel['name'] == current_channel:
                            current_channel_index = channel_combo.count() - 1
                
                if analog_outputs:
                    channel_combo.addItem("--- Analog Outputs ---")
                    for i, channel in enumerate(analog_outputs):
                        display_text = f"{channel['name']} - {channel['description']}"
                        channel_combo.addItem(display_text)
                        if channel['name'] == current_channel:
                            current_channel_index = channel_combo.count() - 1
            else:
                # Fall back to simple channel list
                channels = self.get_labjack_channels()
                for i, channel_name in enumerate(channels):
                    channel_combo.addItem(channel_name)
                    if channel_name == current_channel:
                        current_channel_index = i
            
            # Select the current channel
            if current_channel_index > 0:
                channel_combo.setCurrentIndex(current_channel_index)
            
            # Sensor name
            name_edit = QLineEdit(sensor.name)
            form_layout.addRow("Name:", name_edit)
            
            # Unit
            unit_edit = QLineEdit(sensor.unit)
            form_layout.addRow("Unit:", unit_edit)
            
            # Offset
            offset_spinbox = QDoubleSpinBox()
            offset_spinbox.setDecimals(2)
            offset_spinbox.setRange(-9999, 9999)
            offset_spinbox.setValue(sensor.offset)
            form_layout.addRow("Offset:", offset_spinbox)
            
            # Conversion factor
            conversion_spinbox = QDoubleSpinBox()
            conversion_spinbox.setDecimals(4)
            conversion_spinbox.setRange(0.0001, 10000)
            conversion_spinbox.setValue(sensor.conversion_factor)
            form_layout.addRow("Conversion Factor:", conversion_spinbox)
            
            # Color picker
            color_button = QPushButton("Choose Color")
            current_color = QColor(sensor.color)
            
            # Update button color
            def update_color_button():
                color_style = f"background-color: {current_color.name()}; color: {'black' if current_color.lightness() > 128 else 'white'};"
                color_button.setStyleSheet(color_style)
                
            update_color_button()
            
            # Choose color function
            def choose_color():
                nonlocal current_color
                color = QColorDialog.getColor(current_color, dialog, "Choose Sensor Color")
                if color.isValid():
                    current_color = color
                    update_color_button()
                    
            color_button.clicked.connect(choose_color)
            form_layout.addRow("Color:", color_button)
            
            # Show in graph checkbox
            show_in_graph = QCheckBox("Show in Graph")
            show_in_graph.setChecked(sensor.show_in_graph)
            form_layout.addRow("", show_in_graph)
            
            layout.addLayout(form_layout)
            
            # Dialog buttons
            button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)
            layout.addWidget(button_box)
            
            # Execute the dialog
            result = dialog.exec()
            
            if result == QDialog.DialogCode.Accepted:
                # Update sensor properties
                selected_channel = self._extract_channel_name(channel_combo.currentText())
                if selected_channel and not selected_channel.startswith("---"):
                    # Create a new sensor with the updated values
                    updated_sensor = self.create_labjack_sensor(
                        name=name_edit.text(),
                        port=selected_channel,
                        unit=unit_edit.text(),
                        offset=offset_spinbox.value(),
                        conversion_factor=conversion_spinbox.value(),
                        color=current_color.name(),
                        enabled=True,
                        show_in_graph=show_in_graph.isChecked(),
                        stale_timeout_factor=getattr(sensor, 'stale_timeout_factor', None),
                        averaging_enabled=getattr(sensor, 'averaging_enabled', False)
                    )
                    
                    # Replace the old sensor with the updated one
                    self.sensors[row] = updated_sensor
                    
                    # Save the updated sensor configuration
                    self.save_sensors()
                
                # Update the UI
                self.update_sensor_table()
                
                # Log the sensor update
                self.main_window.logger.log(f"Updated LabJack sensor: {name_edit.text()}")
                
                # Emit status changed signal
                self.status_changed.emit()
            
        elif sensor.interface_type == "OtherSerial":
            # Special handling for Other Serial sensors - open the popup in edit mode
            self.main_window.logger.log(f"Editing Other Serial sensor {sensor.name}")
            # Edit using the AddEditSensorDialog, then update both the main sensor list and main_window.other_sensors
            from app.ui.dialogs.other_sensors_dialog import AddEditSensorDialog
            dialog = AddEditSensorDialog(self.main_window, sensor=sensor.to_dict(), sequences=getattr(self.main_window, 'other_sequences', []))
            if dialog.exec():
                updated_sensor_dict = dialog.get_sensor()
                if updated_sensor_dict["name"]:
                    # Update the SensorModel in self.sensors
                    updated_sensor = type(sensor).from_dict(updated_sensor_dict)
                    self.sensors[row] = updated_sensor
                    # Update in main_window.other_sensors
                    for i, vs in enumerate(self.main_window.other_sensors):
                        if (isinstance(vs, dict) and vs.get("name") == sensor.name) or (hasattr(vs, 'name') and vs.name == sensor.name):
                            self.main_window.other_sensors[i] = updated_sensor_dict
                            break
                    # Save
                    if hasattr(self.main_window, 'save_virtual_sensors'):
                        self.main_window.save_virtual_sensors()
                    self.save_sensors()
                    self.update_sensor_table()
                    self.status_changed.emit()
                    self.main_window.logger.log(f"Updated OtherSerial sensor: {updated_sensor_dict['name']}")
            return
        
        elif sensor.interface_type == "OpticalSensor":
            # Open the specialized Optical Sensor configuration dialog
            self.main_window.logger.log(f"Editing Optical Sensor {sensor.name}")
            self.show_optical_sensor_config(sensor)
            return
        
        else:
            # Default editing for other sensors
            self.main_window.logger.log(f"Editing generic sensor {sensor.name}")
            
            from PyQt6.QtWidgets import QDialog, QFormLayout, QLineEdit, QDoubleSpinBox, QPushButton, QHBoxLayout, QVBoxLayout, QColorDialog, QMessageBox
            
            dialog = QDialog(self.main_window)
            dialog.setWindowTitle(f"Edit Sensor: {sensor.name}")
            
            layout = QFormLayout()
            
            # Sensor name
            name_edit = QLineEdit(sensor.name)
            layout.addRow("Name:", name_edit)
            
            # Unit
            unit_edit = QLineEdit(sensor.unit)
            layout.addRow("Unit:", unit_edit)
            
            # Offset
            offset_edit = QDoubleSpinBox()
            offset_edit.setRange(-1000, 1000)
            offset_edit.setValue(sensor.offset)
            layout.addRow("Offset:", offset_edit)
            
            # Conversion factor
            conversion_edit = QDoubleSpinBox()
            conversion_edit.setRange(0.001, 1000)
            conversion_edit.setValue(sensor.conversion_factor)
            layout.addRow("Conversion Factor:", conversion_edit)
            
            # Color button
            color_btn = QPushButton("Choose Color")
            color_btn.setStyleSheet(f"background-color: {sensor.color};")
            layout.addRow("Color:", color_btn)
            
            # Function to handle color selection
            def on_color_select():
                color = QColorDialog.getColor()
                if color.isValid():
                    color_btn.setStyleSheet(f"background-color: {color.name()};")
            
            color_btn.clicked.connect(on_color_select)
            
            # Buttons
            button_layout = QHBoxLayout()
            save_btn = QPushButton("Save Changes")
            cancel_btn = QPushButton("Cancel")
            button_layout.addWidget(save_btn)
            button_layout.addWidget(cancel_btn)
            
            # Main layout
            main_layout = QVBoxLayout()
            main_layout.addLayout(layout)
            main_layout.addLayout(button_layout)
            dialog.setLayout(main_layout)
            
            # Connect buttons
            cancel_btn.clicked.connect(dialog.reject)
            
            def on_save():
                # Update sensor properties
                sensor.name = name_edit.text()
                sensor.unit = unit_edit.text()
                sensor.offset = offset_edit.value()
                sensor.conversion_factor = conversion_edit.value()
                
                # Extract color from the stylesheet
                style = color_btn.styleSheet()
                color_start = style.find("background-color: ") + len("background-color: ")
                color_end = style.find(";", color_start)
                if color_start >= len("background-color: ") and color_end > color_start:
                    sensor.color = style[color_start:color_end]
                
                # Update the UI
                self.update_sensor_table()
                
                # Log the change
                self.main_window.logger.log(f"Updated sensor: {sensor.name}")
                
                dialog.accept()
                
            save_btn.clicked.connect(on_save)
            
            # Show the dialog
            dialog.exec()
    
    def remove_sensor(self):
        """Remove the selected sensor"""
        from PyQt6.QtWidgets import QMessageBox
        
        # Check if there are any sensors
        if not self.sensors:
            QMessageBox.information(self.main_window, "Remove Sensor", "No sensors available to remove.")
            return
            
        # Check if a row is selected in the table
        if not hasattr(self.main_window, 'data_table'):
            return
            
        table = self.main_window.data_table
        selected_rows = table.selectedIndexes()
        
        if not selected_rows:
            QMessageBox.information(self.main_window, "Remove Sensor", "Please select a sensor to remove.")
            return
            
        # Get the row of the first selected item
        row = selected_rows[0].row()
        
        # Get the sensor
        if row >= len(self.sensors):
            return
            
        sensor = self.sensors[row]
        
        # Confirm removal
        confirm = QMessageBox.question(
            self.main_window,
            "Remove Sensor",
            f"Are you sure you want to remove the sensor '{sensor.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            # Remove the sensor
            removed_sensor = self.sensors.pop(row)
            
            # Clean up sensor interface if needed
            interface_type = getattr(removed_sensor, 'interface_type', None)
            if interface_type == 'OpticalSensor':
                self.disconnect_optical_sensor(removed_sensor)
            elif interface_type == 'AudioSensor':
                self.disconnect_audio_sensor(removed_sensor)
            
            # Update the UI
            self.update_sensor_table()
            
            # Save the updated sensor list
            self.save_sensors()
            
            # Log the sensor removal
            self.main_window.logger.log(f"Removed sensor: {removed_sensor.name}")
            
            # Update status indicators immediately
            if hasattr(self.main_window, 'update_status_indicators'):
                self.main_window.update_status_indicators()
            
            # If it's a virtual sensor, remove from main_window.other_sensors too
            if hasattr(self.main_window, 'other_sensors') and getattr(removed_sensor, 'interface_type', None) == 'OtherSerial':
                self.main_window.other_sensors = [vs for vs in self.main_window.other_sensors if not ((isinstance(vs, dict) and vs.get('name') == removed_sensor.name) or (hasattr(vs, 'name') and vs.name == removed_sensor.name))]
                if hasattr(self.main_window, 'save_virtual_sensors'):
                    self.main_window.save_virtual_sensors()
            
            # Reinitialize the dashboard graph if data collection is active
            if (hasattr(self.main_window, 'data_collection_controller') and 
                hasattr(self.main_window.data_collection_controller, 'collecting_data') and
                self.main_window.data_collection_controller.collecting_data):
                
                if (hasattr(self.main_window, 'graph_controller') and 
                    hasattr(self.main_window.graph_controller, 'live_plotting_active') and
                    self.main_window.graph_controller.live_plotting_active):
                    
                    # Reinitialize the dashboard with the updated sensor list
                    print(f"DEBUG: Reinitializing dashboard graph due to sensor removal: {removed_sensor.name}")
                    start_time = self.main_window.data_collection_controller.start_time
                    if start_time is not None:
                        self.main_window.graph_controller.start_live_dashboard_update(start_time)
        
        # After removing, emit the status changed signal
        self.status_changed.emit()
    
    def load_sensors(self, is_startup_load=False):
        """Load saved sensors"""
        import json
        import os
        from app.models.sensor_model import SensorModel
        
        try:
            # First try to load from the current run directory if available
            run_dir = None
            if not is_startup_load and hasattr(self.main_window, 'project_controller') and self.main_window.project_controller:
                if (hasattr(self.main_window.project_controller, 'current_project') and 
                    hasattr(self.main_window.project_controller, 'current_test_series') and
                    hasattr(self.main_window.project_controller, 'current_run') and
                    self.main_window.project_controller.current_project and
                    self.main_window.project_controller.current_test_series and
                    self.main_window.project_controller.current_run):
                    
                    # Get the base directory from project controller
                    base_dir = self.main_window.project_base_dir.text()
                    project_name = self.main_window.project_controller.current_project
                    series_name = self.main_window.project_controller.current_test_series
                    run_name = self.main_window.project_controller.current_run
                    
                    if base_dir and os.path.exists(base_dir):
                        run_dir = os.path.join(base_dir, project_name, series_name, run_name)
                        if os.path.exists(run_dir):
                            self.main_window.logger.log(f"Checking for sensors in run directory: {run_dir}")
                            sensors_file = os.path.join(run_dir, "sensors.json")
                            if os.path.exists(sensors_file):
                                self.main_window.logger.log(f"Loading sensors from run directory: {sensors_file}")
                                self._load_sensors_from_file(sensors_file)
                                return
                            else:
                                self.main_window.logger.log(f"No sensors file found in run directory", "INFO")
            
            # If no run directory available/exists or no sensors file found there, fall back to default location
            config_dir = os.path.join(os.path.expanduser("~"), ".evolabs_daq")
            if not os.path.exists(config_dir):
                os.makedirs(config_dir)
                
            # Check for sensors file in the default config location
            sensors_file = os.path.join(config_dir, "sensors.json")
            if os.path.exists(sensors_file):
                self.main_window.logger.log(f"Loading sensors from default config: {sensors_file}")
                self._load_sensors_from_file(sensors_file)
            else:
                self.main_window.logger.log("No sensors file found in default location", "INFO")
                
        except Exception as e:
            # Log error
            self.main_window.logger.log(f"Error loading sensors: {str(e)}", "ERROR")
            import traceback
            traceback.print_exc()
            self.main_window.logger.log(traceback.format_exc(), "ERROR")
    
    def _load_sensors_from_file(self, sensors_file):
        """Helper method to load sensors from a specific file
        
        Args:
            sensors_file: Path to the sensors JSON file
        """
        import json
        from app.models.sensor_model import SensorModel
        
        with open(sensors_file, "r") as f:
            sensors_data = json.load(f)
            
        # Disconnect any active optical/audio sensors before clearing
        if hasattr(self, 'optical_sensor_interfaces'):
            for name in list(self.optical_sensor_interfaces.keys()):
                sensor = next((s for s in self.sensors if s.name == name), None)
                if sensor:
                    self.disconnect_optical_sensor(sensor)
                else:
                    # If sensor not in list, disconnect anyway using a mock sensor object
                    from types import SimpleNamespace
                    mock_sensor = SimpleNamespace(name=name)
                    self.disconnect_optical_sensor(mock_sensor)
        
        if hasattr(self, 'audio_sensor_interfaces'):
            for name in list(self.audio_sensor_interfaces.keys()):
                sensor = next((s for s in self.sensors if s.name == name), None)
                if sensor:
                    self.disconnect_audio_sensor(sensor)
                else:
                    from types import SimpleNamespace
                    mock_sensor = SimpleNamespace(name=name)
                    self.disconnect_audio_sensor(mock_sensor)

        # Clear existing sensors
        self.sensors.clear()
        
        # Create sensor objects from the data
        for sensor_data in sensors_data:
            interface_type = sensor_data.get("interface_type", "")
            
            # Specialized handling for LabJack sensors - create them directly
            if interface_type == "LabJack":
                # Log the exact data we're loading for debugging
                print(f"Loading LabJack sensor directly: {sensor_data}")
                
                # Create a new sensor using our dedicated method
                new_sensor = self.create_labjack_sensor(
                    name=sensor_data.get("name", "Unknown"),
                    port=sensor_data.get("port", ""),
                    unit=sensor_data.get("unit", ""),
                    offset=sensor_data.get("offset", 0.0),
                    conversion_factor=sensor_data.get("conversion_factor", 1.0),
                    color=sensor_data.get("color", "#4287f5"),
                    enabled=sensor_data.get("enabled", True),
                    show_in_graph=sensor_data.get("show_in_graph", True),
                    stale_timeout_factor=sensor_data.get("stale_timeout_factor", None),
                    averaging_enabled=sensor_data.get("averaging_enabled", False)
                )
                
                # Add the sensor to the collection
                self.sensors.append(new_sensor)
            else:
                # For other sensor types, use the normal from_dict method
                sensor = SensorModel.from_dict(sensor_data)
                
                # Log the sensor data for debugging
                self.main_window.logger.log(f"Loading sensor from file: {sensor.name} ({sensor.interface_type})")
                self.main_window.logger.log(f"  - Port: {sensor.port}")
                self.main_window.logger.log(f"  - Unit: {sensor.unit}")
                self.main_window.logger.log(f"  - Color: {sensor.color}")
                
                # Additional debugging for OtherSerial sensors
                if sensor.interface_type == "OtherSerial":
                    # Sanitize the sensor to ensure all properties are correct
                    if hasattr(self, '_sanitize_otherserial_sensor'):
                        self._sanitize_otherserial_sensor(sensor)
                
                # Add sensor to collection
                self.sensors.append(sensor)
        
        # Process OtherSerial sensors to recreate their sequence objects
        for sensor in self.sensors:
            if sensor.interface_type == "OtherSerial" and hasattr(sensor, 'sequence_config'):
                # Recreate the sequence if we have steps
                if 'steps' in sensor.sequence_config and hasattr(self.main_window, 'data_collection_controller'):
                    try:
                        # Use the data collection controller to create a proper sequence
                        steps = sensor.sequence_config.get('steps', [])
                        sensor.sequence = self.main_window.data_collection_controller.create_serial_sequence(
                            name=sensor.name,
                            steps_data=steps
                        )
                        self.main_window.logger.log(f"Recreated sequence for sensor {sensor.name}")
                    except Exception as e:
                        self.main_window.logger.log(f"Error recreating sequence for sensor {sensor.name}: {str(e)}", "ERROR")
        
        # Repair any corrupted or incomplete sensors
        self.repair_sensors()
            
        # Save a copy of the loaded sensors for verification (in memory)
        self._loaded_sensors_cache = [sensor.to_dict() for sensor in self.sensors]
        
        # Update the UI
        self.update_sensor_table()
        
        # Rebuild the averaging cache in data collection controller after loading sensors
        # This ensures the cache reflects the loaded sensor settings
        if hasattr(self.main_window, 'data_collection_controller'):
            self.main_window.data_collection_controller._rebuild_averaging_cache()
            self.main_window.logger.log("Rebuilt averaging cache after loading sensors", "INFO")
        
        # Log successful load
        self.main_window.logger.log(f"Loaded {len(self.sensors)} sensors")
        
        # EMERGENCY MEASURE: Comment out automatic debug dialog as it could prevent app loading
        # self.debug_show_sensor_data() 
        
        # Option to show debug info - only in development mode
        if self.main_window.settings.value("debug_mode", "false").lower() == "true":
            # Show sensor debug info
            from PyQt6.QtWidgets import QMessageBox
            debug_response = QMessageBox.question(
                self.main_window,
                "Sensor Debug",
                f"Loaded {len(self.sensors)} sensors. Show detailed debug info?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if debug_response == QMessageBox.StandardButton.Yes:
                self.debug_show_sensor_data()
    
    def save_sensors(self):
        """Save current sensors"""
        import json
        import os
        
        try:
            # First try to save to the current run directory if available
            run_dir = None
            
            # CHECK FOR REPLAY MODE: If we are just viewing an old run, don't save to its directory
            is_replay = getattr(self.main_window, 'is_replay_mode', False)
            
            if not is_replay and hasattr(self.main_window, 'project_controller') and self.main_window.project_controller:
                if (hasattr(self.main_window.project_controller, 'current_project') and 
                    hasattr(self.main_window.project_controller, 'current_test_series') and
                    hasattr(self.main_window.project_controller, 'current_run') and
                    self.main_window.project_controller.current_project and
                    self.main_window.project_controller.current_test_series and
                    self.main_window.project_controller.current_run):
                    
                    # Get the base directory from project controller
                    base_dir = self.main_window.project_base_dir.text()
                    project_name = self.main_window.project_controller.current_project
                    series_name = self.main_window.project_controller.current_test_series
                    run_name = self.main_window.project_controller.current_run
                    
                    if base_dir and os.path.exists(base_dir):
                        run_dir = os.path.join(base_dir, project_name, series_name, run_name)
                        if os.path.exists(run_dir):
                            self.main_window.logger.log(f"Saving sensors to current run directory: {run_dir}")
            
            # If no run directory available or exists, fall back to default location
            if not run_dir or not os.path.exists(run_dir):
                # Get the config directory
                config_dir = os.path.join(os.path.expanduser("~"), ".evolabs_daq")
                if not os.path.exists(config_dir):
                    os.makedirs(config_dir)
                
                # Use the config directory as the save location
                save_dir = config_dir
                self.main_window.logger.log(f"Saving sensors to config directory: {save_dir}")
            else:
                # Use the run directory as the save location
                save_dir = run_dir
                
            # Get the sensors file path
            sensors_file = os.path.join(save_dir, "sensors.json")
            
            # Prepare the sensor data
            sensors_data = []
            
            for sensor in self.sensors:
                # Sanitize LabJack sensors before saving to ensure they save correctly
                if sensor.interface_type == "LabJack":
                    self._sanitize_labjack_sensor(sensor)
            
                # Log detailed information about each sensor being saved
                self.main_window.logger.log(f"Saving sensor: {sensor.name} ({sensor.interface_type})")
                self.main_window.logger.log(f"  - Port: {sensor.port}")
                self.main_window.logger.log(f"  - Unit: {sensor.unit}")
                self.main_window.logger.log(f"  - Color: {sensor.color}")
                self.main_window.logger.log(f"  - Show in Graph: {sensor.show_in_graph}")
                
                # Make sure all important attributes are present in the dictionary
                sensor_dict = sensor.to_dict()
                
                # Add the sensor dictionary to the list
                sensors_data.append(sensor_dict)
            
            # Save the sensors to the file
            with open(sensors_file, "w") as f:
                json.dump(sensors_data, f, indent=2)
                
            # Log successful save
            self.main_window.logger.log(f"Saved {len(self.sensors)} sensors to {sensors_file}")
            
            # Save a backup copy with timestamp (only for default location)
            if save_dir == os.path.join(os.path.expanduser("~"), ".evolabs_daq"):
                try:
                    import datetime
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_file = os.path.join(save_dir, f"sensors_backup_{timestamp}.json")
                    with open(backup_file, "w") as f:
                        json.dump(sensors_data, f, indent=2)
                    self.main_window.logger.log(f"Created sensors backup at {backup_file}")
                except Exception as e:
                    self.main_window.logger.log(f"Failed to create sensors backup: {str(e)}", "WARN")
            
        except Exception as e:
            # Log error
            self.main_window.logger.log(f"Error saving sensors: {str(e)}", "ERROR")
            import traceback
            traceback.print_exc()
            self.main_window.logger.log(traceback.format_exc(), "ERROR")
    
    def _sanitize_labjack_sensor(self, sensor):
        """Ensure LabJack sensor has all required attributes properly set
        
        Args:
            sensor: The LabJack sensor to sanitize
        """
        try:
            if not hasattr(sensor, 'interface_type') or sensor.interface_type != "LabJack":
                return
                
            # Clean up the port/channel name
            if hasattr(sensor, 'port') and sensor.port:
                # Extract the actual channel name if it has a description 
                if " - " in sensor.port:
                    sensor.port = sensor.port.split(" - ")[0].strip()
                    
                # Make sure we don't have a header
                if sensor.port.startswith("---"):
                    sensor.port = ""
                    
            # Ensure conversion factor is not zero
            if not hasattr(sensor, 'conversion_factor') or sensor.conversion_factor == 0:
                sensor.conversion_factor = 1.0
                
            # Make sure other properties have sane values
            if not hasattr(sensor, 'color') or not sensor.color:
                sensor.color = "#4287f5"  # Default blue color
                
            if not hasattr(sensor, 'name') or not sensor.name:
                sensor.name = sensor.port or "LabJack Sensor"
                
            if not hasattr(sensor, 'enabled'):
                sensor.enabled = True
                
            if not hasattr(sensor, 'show_in_graph'):
                sensor.show_in_graph = True
                
            if not hasattr(sensor, 'offset'):
                sensor.offset = 0.0
                
            if not hasattr(sensor, 'unit'):
                sensor.unit = ""
                
            if not hasattr(sensor, 'current_value'):
                sensor.current_value = None
                
            if not hasattr(sensor, 'history'):
                sensor.history = []
        except Exception as e:
            print(f"Error sanitizing LabJack sensor: {str(e)}")
            # Don't let errors in sanitization prevent app loading
    
    def update_sensor_data(self, data):
        """Update sensor data with new values
        
        Args:
            data: Dictionary of sensor values
        """
        if not data or not isinstance(data, dict):
            return

        if 'timestamp' not in data:
            data['timestamp'] = time.time()

        # Store processed data
        processed_data = {}
        
        # First, handle Arduino sensors with the new improved matching logic
        for sensor in self.sensors:
            if sensor.interface_type == "Arduino":
                matched = False
                
                # Try direct name match first (exact case)
                if sensor.name in data:
                    # print(f"DEBUG - Direct name match for Arduino sensor {sensor.name}, value: {data[sensor.name]}")
                    # sensor.process_reading(data[sensor.name]) # REMOVED
                    # Directly assign the corrected value
                    try:
                        sensor.current_value = float(data[sensor.name])
                    except (ValueError, TypeError):
                        sensor.current_value = None # Set to None on error
                    processed_data[sensor.name] = sensor.current_value
                    matched = True
                # Also try case-insensitive matching for Arduino sensors
                else:
                    # Convert sensor name to lowercase for comparison
                    sensor_name_lower = sensor.name.lower()
                    for key in data:
                        if key.lower() == sensor_name_lower:
                            # print(f"DEBUG - Case-insensitive match for Arduino sensor {sensor.name} with key {key}, value: {data[key]}")
                            # sensor.process_reading(data[key]) # REMOVED
                            # Directly assign the corrected value
                            try:
                                sensor.current_value = float(data[key])
                            except (ValueError, TypeError):
                                sensor.current_value = None # Set to None on error
                            processed_data[sensor.name] = sensor.current_value
                            matched = True
                            break
                        
                if not matched:
                    # print(f"DEBUG - No match found for Arduino sensor {sensor.name}")
                    pass
        
        # Handle non-Arduino sensors with the existing logic
        for sensor in self.sensors:
            if sensor.interface_type != "Arduino":
                if sensor.name in data:
                    # Direct match by sensor name
                    # print(f"DEBUG - Direct match found for {sensor.name}, value: {data[sensor.name]}")
                    sensor.process_reading(data[sensor.name])
                elif sensor.interface_type == "LabJack" and sensor.port in data:
                    # Match by port for LabJack
                    # print(f"DEBUG - Port match found for {sensor.name} via port {sensor.port}, value: {data[sensor.port]}")
                    sensor.process_reading(data[sensor.port])
                elif sensor.interface_type == "MQTT" and sensor.port in data:
                    # Match by topic (stored in 'port' field) for MQTT
                    # print(f"DEBUG - Topic match found for MQTT sensor {sensor.name} via topic {sensor.port}, value: {data[sensor.port]}")
                    sensor.process_reading(data[sensor.port])
                elif sensor.interface_type == "CSV":
                    # Match by prefixed key (stored in 'port' field) or name
                    target_key = sensor.port
                    if not target_key:
                        target_key = f"csv_{sensor.name}"
                        
                    if target_key in data:
                        sensor.process_reading(data[target_key])
                    elif f"csv_{sensor.name}" in data:
                        sensor.process_reading(data[f"csv_{sensor.name}"])
                    elif sensor.name in data:
                        sensor.process_reading(data[sensor.name])
            
        # Update UI with the new values
        self.update_sensor_values()
        
        # Update automation context with current sensor values
        self.update_automation_context()
        
        # No need to emit data here - the DataCollectionController will handle synchronized updates
        # The original data has already been stored in the combined buffer by DataCollectionController

    def update_automation_context(self):
        """Collect current sensor values and update the automation context"""
        # Skip if no automation controller
        if not hasattr(self.main_window, 'automation_controller'):
            return
            
        # Create dictionary of current sensor values
        sensor_values = {}
        for sensor in self.sensors:
            if hasattr(sensor, 'name') and hasattr(sensor, 'current_value') and sensor.current_value is not None:
                sensor_values[sensor.name] = sensor.current_value
                
                # --- ADDED: Support unprefixed port/channel names for LabJack ---
                # This allows triggers like 'AIN0' to work even if the sensor name is 'labjack_AIN0'
                if getattr(sensor, 'interface_type', '') == 'LabJack' and hasattr(sensor, 'port') and sensor.port:
                    # Use port as an alternative key if it's different from the name
                    if sensor.port != sensor.name:
                        sensor_values[sensor.port] = sensor.current_value
        
        # Skip if no sensor values
        if not sensor_values:
            return
            
        # Update the automation context with the sensor values
        try:
            # Create context update with sensors dictionary
            context_update = {
                'sensors': sensor_values
            }
            
            # Add optical sensor data for advanced triggers
            if hasattr(self, '_optical_sensor_data') and self._optical_sensor_data:
                context_update['optical_sensors'] = self._optical_sensor_data.copy()
            
            # Add audio sensor data for advanced triggers
            if hasattr(self, '_audio_sensor_data') and self._audio_sensor_data:
                context_update['audio_sensors'] = self._audio_sensor_data.copy()
            
            # Update the automation context
            self.main_window.automation_controller.update_context(context_update)
            if hasattr(self.main_window, "logger"):
                self.main_window.logger.debug(f"SensorController: Updated automation context with {len(sensor_values)} sensor values")
        except Exception as e:
            if hasattr(self.main_window, "logger"):
                self.main_window.logger.error(f"SensorController: Failed to update automation context: {e}")
            import traceback
            traceback.print_exc()
    
    def update_sensor_values(self):
        """Update sensor values in the UI table"""
        if not hasattr(self, 'sensors') or not self.sensors:
            if hasattr(self.main_window, "logger"):
                self.main_window.logger.debug("SensorController: No sensors found in update_sensor_values")
            return
        if not hasattr(self.main_window, 'data_table') or not self.main_window.data_table:
            if hasattr(self.main_window, "logger"):
                self.main_window.logger.debug("SensorController: No data_table found in main_window")
            return
        arduino_connected = False
        other_serial_connected = False
        labjack_connected = False
        if hasattr(self.main_window, 'data_collection_controller'):
            dcc = self.main_window.data_collection_controller
            if hasattr(dcc, 'interfaces'):
                if 'arduino' in dcc.interfaces:
                    arduino_connected = dcc.interfaces['arduino'].get('connected', False)
                if 'other_serial' in dcc.interfaces:
                    if isinstance(dcc.interfaces['other_serial'], dict):
                        other_serial_connected = dcc.interfaces['other_serial'].get('connected', False)
                    else:
                        other_serial_connected = bool(dcc.interfaces['other_serial'])
                if 'labjack' in dcc.interfaces:
                    labjack_connected = dcc.interfaces['labjack'].get('connected', False)
                    
        table = self.main_window.data_table
        if table.rowCount() != len(self.sensors):
            table.setRowCount(len(self.sensors))
        for i, sensor in enumerate(self.sensors):
            # Check for staleness
            is_stale = False
            timeout_val = 2.0
            if hasattr(self.main_window, 'data_collection_controller'):
                dcc = self.main_window.data_collection_controller
                hist_key = self.get_historical_buffer_key(sensor)
                if hist_key:
                    timeout_val = dcc._get_stale_timeout_for_key(hist_key)
                    if hist_key in dcc._last_sensor_update:
                        last_ts = dcc._last_sensor_update[hist_key]
                        if time.time() - last_ts > timeout_val:
                            is_stale = True
                    else:
                        # If we have a current_value but it's not in _last_sensor_update yet,
                        # it means no data has ever been received for this prefixed key.
                        # We should treat it as stale/unavailable.
                        is_stale = True
                
            value_display = ""
            if not is_stale and hasattr(sensor, 'current_value') and sensor.current_value is not None:
                try:
                    value = sensor.current_value
                    if isinstance(value, (int, float)):
                        if value == 0:
                            value_display = "0"
                        elif abs(value) < 0.001:
                            value_display = f"{value:.6f}"
                        elif abs(value) < 0.01:
                            value_display = f"{value:.5f}"
                        elif abs(value) < 0.1:
                            value_display = f"{value:.4f}"
                        elif abs(value) < 1:
                            value_display = f"{value:.3f}"
                        elif abs(value) < 10:
                            value_display = f"{value:.2f}"
                        elif abs(value) < 100:
                            value_display = f"{value:.1f}"
                        else:
                            value_display = f"{int(value)}"
                    else:
                        value_display = str(value)
                    if hasattr(sensor, 'unit') and sensor.unit:
                        value_display = f"{value_display} {sensor.unit}"
                except Exception as e:
                    print(f"ERROR SensorController: Error formatting value for sensor {sensor.name}: {e}")
                    value_display = str(sensor.current_value)
            else:
                # Verwende Klassenkonstante für fehlende Werte
                value_display = self.NO_VALUE_DISPLAY
                
            value_item = QTableWidgetItem(value_display)
            value_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(i, 2, value_item)
        table.repaint()
        
        # --- ADDED: Update automation context whenever values are updated ---
        # This ensures triggers based on ANY sensor (Arduino, LabJack, etc.) are checked
        self.update_automation_context()
    
    def start_acquisition(self):
        """Start data acquisition"""
        self.acquisition_running = True
        # Emit status changed signal
        self.status_changed.emit()
    
    def stop_acquisition(self):
        """Stop data acquisition"""
        self.acquisition_running = False
        # Emit status changed signal
        self.status_changed.emit()
    
    def close_connections(self):
        """Close hardware connections"""
        self.connected = False
        # Emit status changed signal
        self.status_changed.emit()
        
    def disconnect_labjack(self):
        """Properly disconnect from LabJack and clean up resources"""
        try:
            print("DEBUG SENSOR_CONTROLLER: disconnect_labjack called")
            
            # 1. Stop the status monitoring timer if it exists
            if hasattr(self, '_labjack_status_timer') and self._labjack_status_timer:
                self._labjack_status_timer.stop()
                print("Stopped LabJack status monitoring timer")
            
            # 2. Call DataCollectionController to stop the monitoring thread and disconnect
            if hasattr(self.main_window, 'data_collection_controller'):
                print("DEBUG SENSOR_CONTROLLER: Calling data_collection_controller.disconnect_labjack()")
                self.main_window.data_collection_controller.disconnect_labjack()
            
            # 3. Disconnect the interface if it still exists (DataCollectionController should have handled it)
            if hasattr(self, 'labjack_interface') and self.labjack_interface:
                self.labjack_interface.disconnect()
                self.labjack_interface = None
                print("LabJack interface reference cleared in SensorController")
            
            # 4. Clear cached data and internal state
            self.labjack = None
            self.labjack_connected = False
            if hasattr(self, '_labjack_device_info'):
                self._labjack_device_info = None
            if hasattr(self, '_labjack_ef_channels'):
                self._labjack_ef_channels = None
                
            # 5. Update UI if needed
            if hasattr(self.main_window, 'update_labjack_connected_status'):
                self.main_window.update_labjack_connected_status(False)
            elif hasattr(self.main_window, 'update_device_connection_status_ui'):
                self.main_window.update_device_connection_status_ui('labjack', False)
                
            # 6. Log the disconnection
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log("LabJack properly disconnected")
                
            # 7. Emit status changed signal
            self.status_changed.emit()
            
            # 8. Force update sensor table to clear values
            self.update_sensor_values()
            
            return True
        except Exception as e:
            print(f"Error in disconnect_labjack: {e}")
            # Try to log the error
            if hasattr(self, 'main_window') and hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error disconnecting LabJack: {e}", "ERROR")
            return False
        
    def detect_arduino(self):
        """Detect available Arduino ports"""
        # Arduino detection implementation
        # ...
        # After detection, emit the status changed signal
        self.status_changed.emit()
    
    def connect_arduino(self):
        """Connect to Arduino"""
        # Skip if no data collection controller
        if not hasattr(self.main_window, 'data_collection_controller'):
            return False
        
        try:
            # Get first available port
            available_ports = self.main_window.data_collection_controller.get_arduino_ports()
            if not available_ports:
                self.main_window.logger.log("No Arduino ports found", "WARNING")
                return False
                
            port = available_ports[0]
            
            # Connect to Arduino
            success = self.main_window.data_collection_controller.connect_arduino(port, 9600, 1.0)
            
            if success:
                # Start monitoring Arduino data
                self._start_arduino_monitoring()
                
                # Set connected flag
                self.connected = True
                
                # Log success
                self.main_window.logger.log(f"Connected to Arduino on {port}")
                
                # Update UI status display
                if hasattr(self.main_window, 'update_device_connection_status_ui'):
                    self.main_window.update_device_connection_status_ui('arduino', True)
                
                # Emit status changed signal
                self.status_changed.emit()
                
                return True
            else:
                self.main_window.logger.log(f"Failed to connect to Arduino on {port}", "ERROR")
                return False
        except Exception as e:
            self.main_window.logger.log(f"Error connecting to Arduino: {str(e)}", "ERROR")
            return False
    
    def disconnect_arduino(self):
        """Disconnect from Arduino"""
        # Skip if no data collection controller
        if not hasattr(self.main_window, 'data_collection_controller'):
            print("DEBUG SensorController: disconnect_arduino - No data_collection_controller found")
            return
        
        try:
            print("DEBUG SensorController: disconnect_arduino - Disconnecting from Arduino")
            
            # Stop Arduino monitoring timer
            self._stop_arduino_monitoring()
            print("DEBUG SensorController: disconnect_arduino - Stopped Arduino monitoring timer")
            
            # Disconnect from Arduino
            self.main_window.data_collection_controller.disconnect_arduino()
            print("DEBUG SensorController: disconnect_arduino - Called data_collection_controller.disconnect_arduino()")
            
            # Set connected flag
            self.connected = False
            
            # Log Arduino sensors being reset
            arduino_sensors = [s.name for s in self.sensors if getattr(s, 'interface_type', '') == 'Arduino']
            print(f"DEBUG SensorController: disconnect_arduino - Will reset values for Arduino sensors: {arduino_sensors}")
            
            # Set all Arduino sensor values to None
            for sensor in self.sensors:
                if getattr(sensor, 'interface_type', '') == 'Arduino':
                    sensor.current_value = None
                    if hasattr(sensor, 'raw_value'):
                        sensor.raw_value = None
                    print(f"DEBUG SensorController: disconnect_arduino - Reset sensor {sensor.name} value to None")
            
            # Force an update of the sensor table to reflect cleared values
            print("DEBUG SensorController: disconnect_arduino - Calling update_sensor_values()")
            self.update_sensor_values()
            
            # Explicitly clear table cells for Arduino sensors with Em-Dash
            if hasattr(self.main_window, 'data_table') and self.main_window.data_table:
                table = self.main_window.data_table
                for i, sensor in enumerate(self.sensors):
                    if getattr(sensor, 'interface_type', '') == 'Arduino':
                        # Verwende die Klassenkonstante für fehlende Werte
                        value_item = QTableWidgetItem(self.NO_VALUE_DISPLAY)
                        value_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        table.setItem(i, 2, value_item)  # Value is in column 2
                        print(f"DEBUG SensorController: disconnect_arduino - Explicitly set sensor {sensor.name} display to '{self.NO_VALUE_DISPLAY}'")
                print("DEBUG SensorController: disconnect_arduino - Repainting table")
                table.repaint()
            else:
                print("DEBUG SensorController: disconnect_arduino - No data_table found, couldn't update display")
            
            # Update UI status display
            if hasattr(self.main_window, 'update_device_connection_status_ui'):
                print("DEBUG SensorController: disconnect_arduino - Updating device connection status UI")
                self.main_window.update_device_connection_status_ui('arduino', False)
                
            # Log disconnection
            self.main_window.logger.log("Disconnected from Arduino")
            
            # Emit status changed signal
            print("DEBUG SensorController: disconnect_arduino - Emitting status_changed signal")
            self.status_changed.emit()
            
        except Exception as e:
            print(f"ERROR SensorController: Error disconnecting from Arduino: {str(e)}")
            self.main_window.logger.log(f"Error disconnecting from Arduino: {str(e)}", "ERROR")
            import traceback
            traceback.print_exc()
    
    def connect_labjack(self, device_identifier="ANY"):
        """Connect to LabJack using the DataCollectionController
        
        Args:
            device_identifier: Specific serial number or "ANY"
        Returns:
            True if connection was successful, False otherwise
        """
        print(f"DEBUG SENSOR_CONTROLLER: connect_labjack called with identifier='{device_identifier}'") # <<< ADDED
        
        # Make sure the data collection controller exists
        if not hasattr(self.main_window, 'data_collection_controller'):
            print("ERROR SENSOR_CONTROLLER: Data Collection Controller not found!")
            if hasattr(self.main_window, 'logger'): # Check if logger exists
                self.main_window.logger.log("Data Collection Controller not found during LabJack connect", "ERROR")
            return False
            
        # Call the DataCollectionController's connect method
        print("DEBUG SENSOR_CONTROLLER: Calling data_collection_controller.connect_labjack()") # <<< ADDED
        success = self.main_window.data_collection_controller.connect_labjack(
            device_type="ANY",  # Keep these general for now
            connection_type="ANY" 
            # device_identifier=device_identifier # DataCollectionController doesn't use identifier
        )
        
        print(f"DEBUG SENSOR_CONTROLLER: data_collection_controller.connect_labjack() returned: {success}") # <<< ADDED
        
        # Update internal state based on success
        if success:
            # We can assume the interface is now available in DataCollectionController
            if 'labjack' in self.main_window.data_collection_controller.interfaces:
                self.labjack_interface = self.main_window.data_collection_controller.interfaces['labjack']['interface']
                # For backwards compatibility during transition
                self.labjack = self.labjack_interface
                print("DEBUG SENSOR_CONTROLLER: Stored LabJack interface reference")
            else:
                print("ERROR SENSOR_CONTROLLER: LabJack key not found in interfaces after successful connect")
                self.labjack_interface = None
                self.labjack = None
            self.labjack_connected = True
            if hasattr(self.main_window, 'logger'): # Check if logger exists
                self.main_window.logger.log(f"LabJack connection successful (Identifier: {device_identifier})", "INFO")
            # Emit status change
            self.status_changed.emit()
            return True
        else:
            self.labjack = None
            self.labjack_connected = False
            if hasattr(self.main_window, 'logger'): # Check if logger exists
                self.main_window.logger.log(f"LabJack connection failed (Identifier: {device_identifier})", "ERROR")
            # Emit status change
            self.status_changed.emit()
            return False
    
    def _start_labjack_status_monitoring(self):
        """Start monitoring the LabJack status queue"""
        from PyQt6.QtCore import QTimer
        
        # Create timer if it doesn't exist
        if not hasattr(self, '_labjack_status_timer'):
            self._labjack_status_timer = QTimer()
            self._labjack_status_timer.timeout.connect(self._check_labjack_status)
            
        # Start the timer
        if not self._labjack_status_timer.isActive():
            self._labjack_status_timer.start(100)  # Check every 100ms
            
    def _check_labjack_status(self):
        """Check the LabJack status queue for updates"""
        if not hasattr(self, 'labjack_interface') or self.labjack_interface is None:
            return
            
        # Get the status queue
        status_queue = self.labjack_interface.get_status_queue()
        
        # Check if there are any status updates
        try:
            # Non-blocking get
            while True:
                try:
                    status = status_queue.get_nowait()
                    self._process_labjack_status(status)
                except queue.Empty:
                    break
        except Exception as e:
            print(f"Error checking LabJack status: {e}")
            
        # Also check for data updates
        data_queue = self.labjack_interface.get_data_queue()
        
        # Process any data updates
        try:
            while True:
                try:
                    data = data_queue.get_nowait()
                    self._process_labjack_data(data)
                except queue.Empty:
                    break
        except Exception as e:
            print(f"Error checking LabJack data: {e}")
        
        # Note: Removed manual reading fallback mechanism that was causing double reads
        # The UI timer in main_window.py already calls update_sensor_values() at the configured sampling rate
    
    def _update_labjack_sensor_values(self):
        """Update values for all LabJack sensors"""
        # Find all LabJack sensors
        labjack_sensors = [s for s in self.sensors if s.interface_type == "LabJack"]
        
        if not labjack_sensors:
            return
            
        # Read values for each sensor
        for sensor in labjack_sensors:
            try:
                # Get the channel name
                channel = sensor.port
                
                # Skip if invalid channel
                if not channel or channel.startswith("---"):
                    continue
                
                # Read value
                value = self.read_labjack_channel(channel)
                
                # Update sensor
                if value is not None:
                    sensor.process_reading(value)
            except Exception as e:
                print(f"Error updating LabJack sensor {sensor.name}: {e}")
                
        # Update the UI with new values
        self.update_sensor_values()
            
    def _process_labjack_data(self, data):
        """Process data update from the LabJack interface
        
        Args:
            data: Data from the LabJack interface
        """
        if not isinstance(data, dict):
            return
            
        # Find all LabJack sensors
        labjack_sensors = [s for s in self.sensors if s.interface_type == "LabJack"]
        
        # Update each sensor if its channel is in the data
        processed_data = {}
        timestamp = time.time()  # Use current time as timestamp
        
        for sensor in labjack_sensors:
            if sensor.port in data:
                raw_value = data[sensor.port]
                sensor.process_reading(raw_value)
                
                # Add to the processed data dictionary using sensor name as the key
                processed_data[sensor.name] = sensor.current_value
        
        # Update UI
        self.update_sensor_values()
        
        # Update automation context with current sensor values
        self.update_automation_context()
        
        # No need to emit data here - the DataCollectionController will handle synchronized updates
        # The original data has already been stored in the combined buffer by DataCollectionController
    
    def _process_labjack_status(self, status):
        """Process a status update from the LabJack interface
        
        Args:
            status: Status update from the LabJack interface
        """
        if not isinstance(status, dict):
            return
            
        status_type = status.get('type')
        
        if status_type == 'status':
            # Handle connection status update
            connected = status.get('connected', False)
            
            # Update device info if provided - store in a separate attribute
            # Do NOT overwrite the interface object in self.labjack/self.labjack_interface
            if 'device_info' in status:
                self.last_device_info = status['device_info']
                
            # Update UI status display - with error handling
            try:
                if hasattr(self.main_window, 'update_device_connection_status_ui'):
                    self.main_window.update_device_connection_status_ui('labjack', connected)
            except Exception as e:
                print(f"Error updating UI from LabJack status: {e}")
                
        elif status_type == 'ef_channels':
            # Handle EF channels update
            if 'channels' in status:
                # Store the available EF channels
                self._labjack_ef_channels = status['channels']
                
                # Use fewer print statements and avoid complex string operations in the UI thread
                print(f"Received EF channels from LabJack: {len(self._labjack_ef_channels)}")
                
                # Only log with minimal processing to avoid UI blocking
                if hasattr(self.main_window, 'logger') and self.main_window.logger:
                    # Use a delayed/background logging approach
                    # Just store that we got channels, don't do string formatting here
                    self.main_window.logger.log(f"LabJack EF channels detected: {len(self._labjack_ef_channels)}")
                    
                    # Only log thermocouples if we have a reasonable number of them
                    thermocouple_channels = [ch for ch in self._labjack_ef_channels 
                                           if 'thermocouple' in ch.get('type', '')]
                    if thermocouple_channels:
                        # Just log the count of thermocouples found, not all details
                        self.main_window.logger.log(f"LabJack thermocouples found: {len(thermocouple_channels)}")
                    
        # Emit status changed signal for any status updates
        self.status_changed.emit()
    
    def test_labjack(self):
        """Test LabJack connection"""
        try:
            # If we don't have a LabJack interface yet, create one and connect
            if not hasattr(self, 'labjack_interface') or self.labjack_interface is None:
                connected = self.connect_labjack()
                if not connected:
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.warning(self.main_window, "LabJack Test", 
                                      "Failed to connect to LabJack device. Please check your settings and try again.")
                    return False
            
            # If we're already connected, just get the device info
            device_info = self.labjack_interface.device_info
            
            # Force-update the UI status to ensure it shows connected - with error handling
            try:
                self.force_update_labjack_status()
            except Exception as e:
                print(f"Error updating UI during LabJack test: {e}")
                # Don't let UI errors prevent successful test
            
            # Show success message with device details
            from PyQt6.QtWidgets import QMessageBox
            message = f"LabJack connection successful!\n\n"
            message += f"Device type: {device_info.get('device_type', 'Unknown')}\n"
            message += f"Serial number: {device_info.get('serial_number', 'Unknown')}\n"
            message += f"Firmware version: {device_info.get('firmware_version', 'Unknown')}\n"
            message += f"Hardware version: {device_info.get('hardware_version', 'Unknown')}\n"
            message += f"Connection type: {device_info.get('connection_name', device_info.get('connection_type', 'Unknown'))}\n"
            message += f"IP address: {device_info.get('ip_address', 'N/A')}"
            
            QMessageBox.information(self.main_window, "LabJack Test", message)
            
            # Update UI status display - with error handling
            try:
                if hasattr(self.main_window, 'update_device_connection_status_ui'):
                    self.main_window.update_device_connection_status_ui('labjack', True)
            except Exception as e:
                print(f"Error updating device connection UI during LabJack test: {e}")
                # Don't let UI errors prevent successful test
            
            return True
        except Exception as e:
            # Show error message
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self.main_window, "LabJack Test", 
                              f"LabJack connection test failed!\n\nError: {str(e)}")
            
            # Update UI status display
            try:
                if hasattr(self.main_window, 'update_device_connection_status_ui'):
                    self.main_window.update_device_connection_status_ui('labjack', False)
            except Exception as e:
                print(f"Error updating device connection UI during LabJack test failure: {e}")
            
            return False
    
    def force_update_labjack_status(self):
        """Force update the LabJack connection status in the UI"""
        is_connected = hasattr(self, 'labjack_interface') and self.labjack_interface and self.labjack_interface.is_connected()
        
        # Update the connection status in the UI first
        if hasattr(self.main_window, 'update_device_connection_status_ui'):
            try:
                self.main_window.update_device_connection_status_ui('labjack', is_connected)
            except Exception as e:
                print(f"Error updating device connection status UI: {e}")
        
        # Now try to update individual elements
        # Wrap each element update in its own try/except block
        
        # Update status indicator if it exists
        try:
            if hasattr(self.main_window, 'labjack_status_indicator'):
                self.main_window.labjack_status_indicator.setStyleSheet(
                    "background-color: #4CAF50; border-radius: 10px;" if is_connected else 
                    "background-color: #F44336; border-radius: 10px;"
                )
        except AttributeError:
            # Silently ignore if the element doesn't exist or is None
            pass
        except Exception as e:
            print(f"Error updating labjack_status_indicator: {e}")
        
        # Update status label if it exists
        try:
            if hasattr(self.main_window, 'labjack_status_label'):
                self.main_window.labjack_status_label.setText(
                    "Connected" if is_connected else "Not Connected"
                )
                self.main_window.labjack_status_label.setStyleSheet(
                    "color: green; font-size: 9px; background-color: transparent; border: none;" if is_connected else
                    "color: grey; font-size: 9px; background-color: transparent; border: none;"
                )
        except AttributeError:
            # Silently ignore if the element doesn't exist or is None
            pass
        except Exception as e:
            print(f"Error updating labjack_status_label: {e}")
        
        # Update general status label in tab if it exists
        try:
            if hasattr(self.main_window, 'labjack_status'):
                self.main_window.labjack_status.setText(
                    "Connected" if is_connected else "Not Connected"
                )
                self.main_window.labjack_status.setStyleSheet(
                    "color: green; font-size: 9px; background-color: transparent; border: none;" if is_connected else
                    "color: grey; font-size: 9px; background-color: transparent; border: none;"
                )
        except AttributeError:
            # Silently ignore if the element doesn't exist or is None
            pass
        except Exception as e:
            print(f"Error updating labjack_status: {e}")
            
        # Emit status changed signal
        self.status_changed.emit()
        
        # Check for thermocouples if connected
        if is_connected and hasattr(self, '_labjack_ef_channels'):
            thermocouples = [ch for ch in self._labjack_ef_channels if 'thermocouple' in ch.get('type', '')]
            if not thermocouples:
                # Force a thermocouple detection (quietly)
                if hasattr(self.labjack_interface, 'get_ef_channels'):
                    try:
                        ef_channels = self.labjack_interface.get_ef_channels()
                        if ef_channels:
                            self._labjack_ef_channels = ef_channels
                    except Exception:
                        # Ignore errors during thermocouple detection
                        pass
    
    def get_labjack_info(self, info_type, default_value=""):
        """Get LabJack device information
        
        Args:
            info_type (str): Type of information to retrieve
            default_value (str): Default value to return if information not available
            
        Returns:
            str: The requested information or default value if not available
        """
        # Use self.labjack_interface if available, otherwise fallback to self.labjack
        interface = None
        interface_source = "None"
        
        if hasattr(self, 'labjack_interface') and self.labjack_interface and self.labjack_interface.is_connected():
            interface = self.labjack_interface
            interface_source = "labjack_interface"
        elif hasattr(self, 'labjack') and self.labjack and hasattr(self.labjack, 'is_connected') and self.labjack.is_connected():
            interface = self.labjack
            interface_source = "labjack"
        else:
            print(f"DEBUG get_labjack_info: No connected interface found (checked labjack_interface and labjack) for info_type '{info_type}'") # <<< ADDED DEBUG
            return default_value
        
        # <<< ADDED DEBUG BLOCK >>>
        device_info_content = getattr(interface, 'device_info', {})
        print(f"DEBUG get_labjack_info: Using interface from '{interface_source}'. Requesting '{info_type}'. device_info content: {device_info_content}")
        # <<< END DEBUG BLOCK >>>
        
        return device_info_content.get(info_type, default_value)
        
    def get_labjack_channels(self):
        """Get available LabJack channels
        
        Returns:
            list: List of available channel names
        """
        # Check if we have a connected LabJack interface
        if hasattr(self, 'labjack_interface') and self.labjack_interface and self.labjack_interface.is_connected():
            # Use the interface method to get available channels including EF channels
            channels_info = self.labjack_interface.get_labjack_channels()
            # Extract just the channel names for backwards compatibility
            return [channel["name"] for channel in channels_info]
        
        # Fallback: Return a list of standard T7 channels that are likely to be useful
        channels = []
        
        # Add analog inputs (AIN0-AIN13 for T7)
        for i in range(14):
            channels.append(f"AIN{i}")
            
        # Add digital I/O (FIO0-FIO7, EIO0-EIO7, CIO0-CIO3)
        for i in range(8):
            channels.append(f"FIO{i}")
        for i in range(8):
            channels.append(f"EIO{i}")
        for i in range(4):
            channels.append(f"CIO{i}")
            
        # Add DAC outputs
        channels.append("DAC0")
        channels.append("DAC1")
        
        return channels
    
    def get_labjack_channels_info(self):
        """Get detailed information about available LabJack channels.
           Ensures EF channels are fetched if not cached but connected.
        
        Returns:
            list: List of dictionaries with channel information, or empty list.
        """
        # Check connection status first using the correct interface reference
        # Use labjack_interface as the primary source
        active_interface = getattr(self, 'labjack_interface', None)
        if not active_interface:
            active_interface = getattr(self, 'labjack', None)
            
        is_connected = active_interface and hasattr(active_interface, 'is_connected') and active_interface.is_connected()
        
        if not is_connected:
             if hasattr(self, '_labjack_ef_channels') and self._labjack_ef_channels:
                 print("DEBUG: LabJack not connected, returning cached EF channels.")
                 return self._labjack_ef_channels
             else:
                 print("DEBUG: LabJack not connected and no cached channels.")
                 return []

        # --- If connected, ensure we have EF channels --- 
        if hasattr(self, '_labjack_ef_channels') and self._labjack_ef_channels:
            ef_channels = self._labjack_ef_channels
            print(f"DEBUG: Using cached EF channels ({len(ef_channels)} found).")
        else:
            print("DEBUG: EF channel cache empty, fetching from interface...")
            try:
                # Use the active interface
                if hasattr(active_interface, 'get_ef_channels'): 
                     ef_channels = active_interface.get_ef_channels()
                     if ef_channels:
                         print(f"DEBUG: Fetched {len(ef_channels)} EF channels.")
                         self._labjack_ef_channels = ef_channels 
                     else:
                         print("DEBUG: get_ef_channels() returned empty list or None.")
                         ef_channels = []
                else:
                     print("WARNING: active_interface has no get_ef_channels method.")
                     ef_channels = []
            except Exception as e:
                 print(f"ERROR: Failed to fetch EF channels: {e}")
                 ef_channels = [] 
        # --------------------------------------------------
        
        # Get base channels from the interface
        base_channels = []
        try:
            # Use the active interface
            if hasattr(active_interface, 'get_labjack_channels'):
                base_channels = active_interface.get_labjack_channels()
                ef_channel_names = set([ch['name'] for ch in ef_channels])
                base_channels = [ch for ch in base_channels if ch.get('name') not in ef_channel_names]
            else:
                 print("WARNING: active_interface has no get_labjack_channels method.")
        except Exception as e:
            print(f"ERROR: Failed to fetch base channels: {e}")
            base_channels = [] 
                
        # Combine base and EF channels
        print(f"DEBUG: Returning {len(base_channels)} base channels and {len(ef_channels)} EF channels.")
        return base_channels + ef_channels
        
    def read_labjack_channel(self, channel):
        """Read a value from a specific LabJack channel
        
        Args:
            channel (str): Channel name to read
            
        Returns:
            float: Value read from the channel, or None if failed
        """
        if not hasattr(self, 'labjack_interface') or self.labjack_interface is None or not self.labjack_interface.is_connected():
            return None
            
        try:
            # Check if this is an EF channel
            if "_EF_" in channel:
                # Use the specialized EF reader
                value = self.labjack_interface.read_ef_channel(channel)
            else:
                # Use the standard channel reader
                value = self.labjack_interface.read_channel(channel)
            return value
        except Exception as e:
            print(f"Error reading LabJack channel {channel}: {str(e)}")
            return None
            
    def configure_labjack_ef(self, dio, ef_type, options=None):
        """Configure a LabJack Extended Feature
        
        Args:
            dio (str): Digital I/O line (e.g. "FIO0")
            ef_type (str): The EF type (e.g. "counter", "pwm_out")
            options (dict, optional): Additional configuration options
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not hasattr(self, 'labjack_interface') or self.labjack_interface is None or not self.labjack_interface.is_connected():
            return False
            
        return self.labjack_interface.configure_ef(dio, ef_type, options)
    
    def connect_other_sensor(self, sensor_type=None):
        """Connect to other sensor type
        
        Args:
            sensor_type (str, optional): The type of sensor to connect to
        """
        # Other sensor connection implementation
        # ...
        # For demo purposes, simulate a successful connection
        connected = True  # Replace with actual connection code
        
        # If successful, set connected flag
        self.connected = connected
        
        # Update UI status display
        if hasattr(self.main_window, 'update_device_connection_status_ui'):
            self.main_window.update_device_connection_status_ui('other', connected)
        
        # Emit status changed signal
        self.status_changed.emit()
        
    def get_status(self):
        """Get controller status"""
        return {
            "connected": self.connected,
            "acquisition_running": self.acquisition_running,
            "sensor_count": len(self.sensors)
        }
        
    def add_other_serial_sensor(self, name, unit, offset, port, baud_rate, data_bits, 
                               parity, stop_bits, poll_interval, sequence, sequence_config):
        """
        Add a new Other Serial sensor
        
        Args:
            name: Sensor name
            unit: Measurement unit
            offset: Calibration offset
            port: Serial port
            baud_rate: Baud rate
            data_bits: Data bits
            parity: Parity setting
            stop_bits: Stop bits
            poll_interval: Poll interval in seconds
            sequence: SerialSequence object
            sequence_config: Dictionary with configuration for the sequence
            
        Returns:
            True if sensor was added successfully, False otherwise
        """
        try:
            # Check if name already exists
            for sensor in self.sensors:
                if sensor.name == name:
                    if hasattr(self.main_window, 'logger'):
                        self.main_window.logger.log(f"Sensor with name '{name}' already exists!", "ERROR")
                    print(f"Sensor with name '{name}' already exists!")
                    return False
            
            # Create new sensor model
            new_sensor = SensorModel(
                name=name,
                interface_type="OtherSerial",
                unit=unit,
                color="#4CAF50",  # Default to green
                enabled=True,
                show_in_graph=True,
                offset=offset
            )
            
            # Add other serial specific properties
            new_sensor.port = port
            new_sensor.baud_rate = baud_rate
            new_sensor.data_bits = data_bits
            new_sensor.parity = parity
            new_sensor.stop_bits = stop_bits
            new_sensor.poll_interval = poll_interval
            new_sensor.sequence = sequence
            new_sensor.sequence_config = sequence_config
            
            # Add the sensor to the collection
            self.sensors.append(new_sensor)
            
            # Update UI
            self.update_sensor_table()
            
            # Emit status change signal
            self.status_changed.emit()
            
            # Log the addition
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Added new OtherSerial sensor: {name}")
            print(f"Added new OtherSerial sensor: {name}")
            
            return True
            
        except Exception as e:
            # Log the error
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error adding OtherSerial sensor: {str(e)}", "ERROR")
            print(f"Error adding OtherSerial sensor: {str(e)}")
            return False
            
    def update_sensor(self, sensor):
        """
        Update an existing sensor
        
        Args:
            sensor: The sensor object to update
            
        Returns:
            True if update was successful, False otherwise
        """
        try:
            # Find the sensor in the collection
            for i, s in enumerate(self.sensors):
                if s.name == sensor.name:
                    # Found it, update it
                    self.sensors[i] = sensor
                    
                    # Update the UI
                    self.update_sensor_table()
                    
                    # Emit status change signal
                    self.status_changed.emit()
                    
                    # Log the update
                    if hasattr(self.main_window, 'logger'):
                        self.main_window.logger.log(f"Updated sensor: {sensor.name}")
                    print(f"Updated sensor: {sensor.name}")
                    
                    return True
            
            # If we get here, sensor wasn't found
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Sensor '{sensor.name}' not found for update!", "ERROR")
            print(f"Sensor '{sensor.name}' not found for update!")
            return False
            
        except Exception as e:
            # Log the error
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error updating sensor: {str(e)}", "ERROR")
            print(f"Error updating sensor: {str(e)}")
            return False
            
    def verify_sensor_consistency(self):
        """Verify that loaded sensors match the original saved data
        
        This is a diagnostic method to help identify issues with sensor data persistence.
        """
        try:
            # Check if we have a cache of loaded sensors
            if not hasattr(self, '_loaded_sensors_cache') or not self._loaded_sensors_cache:
                self.main_window.logger.log("No sensor cache available for verification", "WARN")
                return
                
            # Compare current sensors with the loaded cache
            current_sensors = [sensor.to_dict() for sensor in self.sensors]
            
            if len(current_sensors) != len(self._loaded_sensors_cache):
                self.main_window.logger.log(f"Sensor count mismatch: current={len(current_sensors)}, loaded={len(self._loaded_sensors_cache)}", "WARN")
                
            # Compare each sensor
            for i, (current, loaded) in enumerate(zip(current_sensors, self._loaded_sensors_cache)):
                self.main_window.logger.log(f"Verifying sensor {i+1}: {current.get('name', 'Unknown')}")
                
                # Check key attributes
                for key in ['name', 'interface_type', 'port', 'unit', 'offset', 'color', 'show_in_graph']:
                    if key in current and key in loaded and current[key] != loaded[key]:
                        self.main_window.logger.log(f"  - Mismatch in {key}: current='{current[key]}', loaded='{loaded[key]}'", "WARN")
                        
            self.main_window.logger.log("Sensor verification complete")
            
        except Exception as e:
            self.main_window.logger.log(f"Error during sensor verification: {str(e)}", "ERROR")
            import traceback
            self.main_window.logger.log(traceback.format_exc(), "ERROR")
    
    def debug_show_sensor_data(self):
        """Show current sensor data in a dialog (for debugging purposes)"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QScrollArea, QDialogButtonBox, QTextEdit
        
        try:
            dialog = QDialog(self.main_window)
            dialog.setWindowTitle("Sensor Data Debug")
            dialog.setMinimumWidth(600)
            dialog.setMinimumHeight(400)
            
            layout = QVBoxLayout(dialog)
            
            # Create a text edit for displaying sensor data
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            
            # Add header
            debug_text = f"SENSOR DATA DEBUG - {len(self.sensors)} sensors\n"
            debug_text += "-" * 50 + "\n\n"
            
            # Add each sensor's data
            for i, sensor in enumerate(self.sensors):
                debug_text += f"SENSOR {i+1}: {sensor.name} ({sensor.interface_type})\n"
                debug_text += f"  Port: {sensor.port}\n"
                debug_text += f"  Unit: {sensor.unit}\n"
                debug_text += f"  Offset: {sensor.offset}\n"
                debug_text += f"  Color: {sensor.color}\n"
                debug_text += f"  Show in Graph: {sensor.show_in_graph}\n"
                debug_text += f"  Current Value: {sensor.current_value}\n"
                
                # Add all attributes
                debug_text += "  All Attributes:\n"
                for attr_name in dir(sensor):
                    if not attr_name.startswith("_") and not callable(getattr(sensor, attr_name)):
                        attr_value = getattr(sensor, attr_name)
                        if attr_name != 'history':  # Skip history as it can be large
                            debug_text += f"    {attr_name}: {attr_value}\n"
                            
                debug_text += "\n" + "-" * 50 + "\n\n"
            
            # Set the text
            text_edit.setText(debug_text)
            
            # Add to layout
            layout.addWidget(text_edit)
            
            # Add close button
            button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            button_box.rejected.connect(dialog.reject)
            layout.addWidget(button_box)
            
            # Show the dialog
            dialog.exec()
            
        except Exception as e:
            self.main_window.logger.log(f"Error showing sensor debug: {str(e)}", "ERROR")
            import traceback
            self.main_window.logger.log(traceback.format_exc(), "ERROR")
    
    def repair_sensors(self):
        """Repair any corrupted or incomplete sensors in the collection.
        This is a recovery mechanism for sensors that might have been saved incorrectly.
        """
        self.main_window.logger.log("Repairing sensors if needed...")
        
        for i, sensor in enumerate(self.sensors):
            try:
                # Basic validation for all sensors
                if not hasattr(sensor, 'name') or not sensor.name:
                    if hasattr(sensor, 'port') and sensor.port:
                        sensor.name = sensor.port
                    else:
                        sensor.name = f"Sensor {i+1}"
                    self.main_window.logger.log(f"Fixed missing name for sensor at index {i}: {sensor.name}", "WARN")
                
                if not hasattr(sensor, 'interface_type') or not sensor.interface_type:
                    sensor.interface_type = "Unknown"
                    self.main_window.logger.log(f"Fixed missing interface_type for sensor: {sensor.name}", "WARN")
                    
                if not hasattr(sensor, 'color') or not sensor.color:
                    sensor.color = "#4287f5"  # Default blue color
                    self.main_window.logger.log(f"Fixed missing color for sensor: {sensor.name}", "WARN")
                    
                if not hasattr(sensor, 'enabled'):
                    sensor.enabled = True
                    self.main_window.logger.log(f"Fixed missing enabled flag for sensor: {sensor.name}", "WARN")
                    
                if not hasattr(sensor, 'show_in_graph'):
                    sensor.show_in_graph = True
                    self.main_window.logger.log(f"Fixed missing show_in_graph flag for sensor: {sensor.name}", "WARN")
                    
                if not hasattr(sensor, 'conversion_factor') or sensor.conversion_factor == 0:
                    sensor.conversion_factor = 1.0
                    self.main_window.logger.log(f"Fixed missing/zero conversion_factor for sensor: {sensor.name}", "WARN")
                    
                if not hasattr(sensor, 'offset'):
                    sensor.offset = 0.0
                    self.main_window.logger.log(f"Fixed missing offset for sensor: {sensor.name}", "WARN")
                    
                if not hasattr(sensor, 'current_value'):
                    sensor.current_value = None
                    self.main_window.logger.log(f"Fixed missing current_value for sensor: {sensor.name}", "WARN")
                    
                if not hasattr(sensor, 'history'):
                    sensor.history = []
                    self.main_window.logger.log(f"Fixed missing history for sensor: {sensor.name}", "WARN")
                
                if not hasattr(sensor, 'averaging_enabled'):
                    sensor.averaging_enabled = False
                    self.main_window.logger.log(f"Fixed missing averaging_enabled flag for sensor: {sensor.name}", "WARN")
                
                if not hasattr(sensor, 'stale_timeout_factor'):
                    sensor.stale_timeout_factor = None
                    self.main_window.logger.log(f"Fixed missing stale_timeout_factor for sensor: {sensor.name}", "WARN")
                
                # Type-specific repairs
                if sensor.interface_type == "LabJack":
                    # Make sure LabJack sensors have all required properties
                    self._sanitize_labjack_sensor(sensor)
                    self.main_window.logger.log(f"Sanitized LabJack sensor: {sensor.name}")
                    
                elif sensor.interface_type == "OtherSerial":
                    # Make sure OtherSerial sensors have all required properties
                    if not hasattr(sensor, 'sequence_config'):
                        sensor.sequence_config = {}
                        self.main_window.logger.log(f"Fixed missing sequence_config for OtherSerial sensor: {sensor.name}", "WARN")
                
                elif sensor.interface_type == "OpticalSensor":
                    # Make sure Optical sensors have optical_config
                    if not hasattr(sensor, 'optical_config') or not sensor.optical_config:
                        sensor.optical_config = {}
                        self.main_window.logger.log(f"WARNING: Optical sensor {sensor.name} has no optical_config - sensor needs to be reconfigured", "WARN")
                    else:
                        # Validate that config has required fields
                        config = sensor.optical_config
                        if config.get("camera_id") is None or not config.get("mode"):
                            self.main_window.logger.log(f"WARNING: Optical sensor {sensor.name} has incomplete optical_config (camera_id={config.get('camera_id')}, mode={config.get('mode')}) - sensor needs to be reconfigured", "WARN")
                
                elif sensor.interface_type == "AudioSensor":
                    # Make sure Audio sensors have audio_config
                    if not hasattr(sensor, 'audio_config') or not sensor.audio_config:
                        sensor.audio_config = {}
                        self.main_window.logger.log(f"WARNING: Audio sensor {sensor.name} has no audio_config - sensor needs to be reconfigured", "WARN")
                    else:
                        # Validate that config has required fields
                        config = sensor.audio_config
                        if config.get("device_id") is None and config.get("device_id") != "default":
                            # device_id can be None for default device, so this is OK
                            pass
                        if not config.get("mode"):
                            self.main_window.logger.log(f"WARNING: Audio sensor {sensor.name} has incomplete audio_config (mode={config.get('mode')}) - sensor needs to be reconfigured", "WARN")
                        
            except Exception as e:
                self.main_window.logger.log(f"Error repairing sensor at index {i}: {str(e)}", "ERROR")
                
        self.main_window.logger.log("Sensor repair complete")
        
        # Update the UI after repairs
        self.update_sensor_table() 
    
    def create_labjack_sensor(self, name, port, unit="", offset=0.0, conversion_factor=1.0, color="#4287f5", enabled=True, show_in_graph=True, stale_timeout_factor=None, averaging_enabled=False):
        """Create a new LabJack sensor with consistent settings
        
        Args:
            name: Sensor name
            port: LabJack port/channel
            unit: Measurement unit
            offset: Calibration offset
            conversion_factor: Value conversion factor
            color: Display color
            enabled: Whether the sensor is enabled
            show_in_graph: Whether to show in graphs
            stale_timeout_factor: Multiplier for sampling interval
            averaging_enabled: Whether smoothing is enabled
            
        Returns:
            The created sensor object
        """
        try:
            # Ensure values are of correct types with defaults if invalid
            if name is None or name == "":
                name = port or "LabJack Sensor"
            
            # Ensure port is correctly formatted
            if port and " - " in port:
                port = port.split(" - ")[0].strip()
                
            # Convert numeric values safely
            try:
                offset = float(offset)
            except (ValueError, TypeError):
                offset = 0.0
                
            try:
                conversion_factor = float(conversion_factor)
                if conversion_factor == 0:
                    conversion_factor = 1.0
            except (ValueError, TypeError):
                conversion_factor = 1.0
                
            # Create the sensor
            sensor = SensorModel(
                name=name,
                interface_type="LabJack",
                port=port,
                unit=unit or "",
                offset=offset,
                conversion_factor=conversion_factor,
                color=color or "#4287f5",
                enabled=bool(enabled),
                show_in_graph=bool(show_in_graph),
                stale_timeout_factor=stale_timeout_factor,
                averaging_enabled=bool(averaging_enabled)
            )
            
            # Apply additional checks
            self._sanitize_labjack_sensor(sensor)
            
            # Log the creation (only if main_window and logger exist)
            if hasattr(self, 'main_window') and hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Created LabJack sensor: {sensor.name}")
                self.main_window.logger.log(f"  - Port: {sensor.port}")
                self.main_window.logger.log(f"  - Unit: {sensor.unit}")
                self.main_window.logger.log(f"  - Offset: {sensor.offset}")
                self.main_window.logger.log(f"  - Conversion factor: {sensor.conversion_factor}")
                self.main_window.logger.log(f"  - Color: {sensor.color}")
            
            return sensor
        except Exception as e:
            # Log error and return a basic sensor as fallback
            if hasattr(self, 'main_window') and hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error creating LabJack sensor: {str(e)}", "ERROR")
            
            # Create a basic sensor with safe defaults
            sensor = SensorModel(
                name=name or "LabJack Sensor",
                interface_type="LabJack",
                port=port or "",
                unit=unit or "",
                offset=0.0,
                conversion_factor=1.0,
                color="#4287f5",
                enabled=True,
                show_in_graph=True
            )
            return sensor
    
    def change_sensor_color(self, sensor, row):
        """Change the color of a sensor when the color button is clicked
        
        Args:
            sensor: The sensor to change the color for
            row: The row index in the table
        """
        try:
            # Open color picker dialog
            from PyQt6.QtWidgets import QColorDialog
            from PyQt6.QtGui import QColor
            
            # Create a valid color object from the sensor color
            try:
                current_color = QColor(sensor.color)
                if not current_color.isValid():
                    current_color = QColor("#FFFFFF")  # Default to white if invalid
            except:
                current_color = QColor("#FFFFFF")
                
            # Show the color dialog
            color = QColorDialog.getColor(current_color, self.main_window, "Choose Sensor Color")
            
            if color.isValid():
                # Update sensor color
                sensor.color = color.name()
                
                # Save the updated sensor configuration
                self.save_sensors()
                
                # Update the table to show the new color
                self.update_sensor_table()
                
                # Update dashboard if it exists
                if hasattr(self.main_window, '_tools_window') and self.main_window._tools_window:
                    if hasattr(self.main_window._tools_window, 'statistics_dashboard'):
                        self.main_window._tools_window.statistics_dashboard.update_sensor_color(sensor)
                elif hasattr(self.main_window, 'tools_window') and self.main_window.tools_window:
                    if hasattr(self.main_window.tools_window, 'statistics_dashboard'):
                        self.main_window.tools_window.statistics_dashboard.update_sensor_color(sensor)
                
                # Log the change
                self.main_window.logger.log(f"Changed color of sensor {sensor.name} to {sensor.color}")
                
        except Exception as e:
            print(f"Error changing sensor color: {e}")
            import traceback
            traceback.print_exc()
    
    def _start_arduino_monitoring(self):
        """Start a timer to regularly check Arduino data and update the UI"""
        from PyQt6.QtCore import QTimer
        
        # Create timer if it doesn't exist
        if not hasattr(self, '_arduino_monitor_timer') or self._arduino_monitor_timer is None:
            self._arduino_monitor_timer = QTimer()
            self._arduino_monitor_timer.timeout.connect(self._check_arduino_data)
            
        # Start timer if not already running
        if not self._arduino_monitor_timer.isActive():
            # Get the sampling rate from data_collection_controller
            sampling_rate = 1.0  # Default to 1Hz if not available
            if (hasattr(self.main_window, 'data_collection_controller') and 
                hasattr(self.main_window.data_collection_controller, 'sampling_rate')):
                sampling_rate = self.main_window.data_collection_controller.sampling_rate
            
            # Calculate interval in milliseconds (minimum 100ms for UI responsiveness)
            update_interval = max(int(1000 / sampling_rate), 100)
            
            print(f"Starting Arduino monitoring timer with interval: {update_interval}ms (sampling rate: {sampling_rate}Hz)")
            self._arduino_monitor_timer.start(update_interval)
    
    def _check_arduino_data(self):
        """Check Arduino data and update sensor values"""
        # Skip if no data collection controller or main window
        if not hasattr(self.main_window, 'data_collection_controller'):
            print("DEBUG: No data_collection_controller found in main_window")
            return
            
        try:
            # Check if Arduino is connected
            if ('arduino' in self.main_window.data_collection_controller.interfaces and 
                self.main_window.data_collection_controller.interfaces['arduino']['connected']):
                
                # Get latest data from Arduino
                latest_data = self.main_window.data_collection_controller.arduino_thread.get_latest_data()
                
                if latest_data:
                    # Process the data
                    self.update_sensor_data(latest_data)
        except Exception as e:
            print(f"ERROR in _check_arduino_data: {str(e)}")
            import traceback
            print(traceback.format_exc())
    
    def _stop_arduino_monitoring(self):
        """Stop the Arduino monitoring timer"""
        if hasattr(self, '_arduino_monitor_timer') and self._arduino_monitor_timer:
            if self._arduino_monitor_timer.isActive():
                self._arduino_monitor_timer.stop()
                print("Stopped Arduino monitoring timer")
    
    def force_update_arduino_status(self):
        """Force update Arduino status and sensor values immediately"""
        # Skip if no data collection controller or main window
        if not hasattr(self.main_window, 'data_collection_controller'):
            return
            
        # Check if Arduino is connected
        if ('arduino' in self.main_window.data_collection_controller.interfaces and 
            self.main_window.data_collection_controller.interfaces['arduino']['connected']):
            
            # Get latest data from Arduino
            latest_data = self.main_window.data_collection_controller.arduino_thread.get_latest_data()
            
            if latest_data:
                # Process the data
                print(f"Force updating Arduino sensors with data: {latest_data}")
                self.update_sensor_data(latest_data)
                
                # Log the update
                self.main_window.logger.log("Forced update of Arduino sensor values")
                
                return True
            else:
                self.main_window.logger.log("No Arduino data available for forced update", "WARNING")
                return False
        else:
            self.main_window.logger.log("Cannot force update - Arduino not connected", "WARNING")
            return False
    
    def initialize(self):
        """Initialize the controller and set up initial sensor state"""
        try:
            # Load saved sensors
            self.load_sensors()
            
            # Repair any sensors that might be incomplete or corrupted
            self.repair_sensors()
            
            # Ensure graph visibility is correctly configured
            self._ensure_graph_visibility()
            
            # Check if Arduino is connected and auto-connect if needed
            if hasattr(self.main_window, 'auto_connect_arduino') and self.main_window.auto_connect_arduino:
                self.main_window.logger.log("Auto-connecting to Arduino...")
                self.connect_arduino()
                
                # Start Arduino monitoring
                self._start_arduino_monitoring()
                
                # Force update Arduino sensor values
                self.force_update_arduino_status()
                
            # Check if LabJack is already connected
            if hasattr(self, 'labjack_interface') and self.labjack_interface:
                self._start_labjack_status_monitoring()
                
            # Connect OtherSerial sensors
            self.initialize_other_serial_connections()
            
            # Auto-connect audio and optical sensors
            self.initialize_audio_optical_connections()
            
            # Rebuild averaging cache after initialization to ensure it's current
            if hasattr(self.main_window, 'data_collection_controller'):
                self.main_window.data_collection_controller._rebuild_averaging_cache()
                self.main_window.logger.log("Rebuilt averaging cache after sensor controller initialization", "INFO")
            
        except Exception as e:
            # Log any exceptions during initialization
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error initializing sensor controller: {str(e)}", "ERROR")
            print(f"Error initializing sensor controller: {str(e)}")
    
    def initialize_audio_optical_connections(self):
        """Auto-connect audio and optical sensors on startup"""
        try:
            # Connect audio sensors - connect all enabled sensors, not just those shown in graph
            audio_sensors = [s for s in self.sensors if getattr(s, 'interface_type', '') == 'AudioSensor']
            for sensor in audio_sensors:
                if getattr(sensor, 'enabled', True):
                    try:
                        if self.connect_audio_sensor(sensor):
                            if hasattr(self.main_window, 'logger'):
                                self.main_window.logger.log(f"Auto-connected audio sensor: {sensor.name}", "INFO")
                            print(f"Auto-connected audio sensor: {sensor.name}")
                        else:
                            print(f"Failed to auto-connect audio sensor: {sensor.name}")
                    except Exception as e:
                        print(f"Error auto-connecting audio sensor {sensor.name}: {e}")
            
            # Connect optical sensors - connect all enabled sensors, not just those shown in graph
            optical_sensors = [s for s in self.sensors if getattr(s, 'interface_type', '') == 'OpticalSensor']
            for sensor in optical_sensors:
                if getattr(sensor, 'enabled', True):
                    try:
                        if self.connect_optical_sensor(sensor):
                            if hasattr(self.main_window, 'logger'):
                                self.main_window.logger.log(f"Auto-connected optical sensor: {sensor.name}", "INFO")
                    except Exception as e:
                        if hasattr(self.main_window, 'logger'):
                            self.main_window.logger.log(f"Error auto-connecting optical sensor {sensor.name}: {e}", "ERROR")
            
            # Emit status changed signal after auto-connect to update UI
            self.status_changed.emit()
            
            # Update status indicators (this will update the nav button icon)
            if hasattr(self.main_window, 'update_status_indicators'):
                self.main_window.update_status_indicators()
            
            # Update device-specific status displays (Audio, Optical, etc.)
            if hasattr(self.main_window, 'update_audio_sensor_status'):
                self.main_window.update_audio_sensor_status()
            if hasattr(self.main_window, 'update_optical_sensor_status'):
                self.main_window.update_optical_sensor_status()
                
        except Exception as e:
            print(f"Error in initialize_audio_optical_connections: {e}")
            import traceback
            traceback.print_exc()
            
    def initialize_other_serial_connections(self, is_explicit_reconnect=False):
        """Initialize connections to OtherSerial devices based on defined sequences."""
        print("DEBUG SensorController: initialize_other_serial_connections called")
        
        if not hasattr(self.main_window, 'data_collection_controller'):
            print("DEBUG SensorController: No data_collection_controller available")
            return
            
        data_controller = self.main_window.data_collection_controller
        
        # Get OtherSerial sensors from main sensor list
        other_sensors_main = [s for s in self.sensors if getattr(s, 'interface_type', '') == 'OtherSerial']
        # Also check for sensors in main_window.other_sensors (from dialog)
        other_sensors_dialog = []
        if hasattr(self.main_window, 'other_sensors'):
            other_sensors_dialog = self.main_window.other_sensors
            print(f"DEBUG SensorController: Found {len(other_sensors_dialog)} sensors in dialog's other_sensors")
            for sensor in other_sensors_dialog:
                print(f"DEBUG SensorController: Dialog sensor: {sensor.get('name', 'Unnamed')}, type: {sensor.get('type', 'Unknown')}")
            
        # Combine sensors from both sources (avoid duplicates by name)
        other_sensors_dict = {getattr(s, 'name', f"sensor_{i}"): s for i, s in enumerate(other_sensors_main)}
        for sensor in other_sensors_dialog:
            name = sensor.get('name', f"dialog_sensor_{len(other_sensors_dict)}")
            if name not in other_sensors_dict:
                # Convert dict to a temporary object if needed or ensure interface_type
                if isinstance(sensor, dict):
                    from app.models.sensor_model import SensorModel
                    sensor_model = SensorModel.from_dict(sensor)
                    sensor_model.interface_type = 'OtherSerial'
                    other_sensors_dict[name] = sensor_model
                    print(f"DEBUG SensorController: Converted dialog sensor {name} to SensorModel with interface_type='OtherSerial'")
                else:
                    other_sensors_dict[name] = sensor
        other_sensors = list(other_sensors_dict.values())
        
        # Get sequences
        other_sequences = getattr(self.main_window, 'other_sequences', [])
        
        print(f"DEBUG SensorController: Initializing OtherSerial - found {len(other_sensors)} total sensors (main: {len(other_sensors_main)}, dialog: {len(other_sensors_dialog)}) and {len(other_sequences)} sequences")
        if len(other_sensors) == 0 and len(other_sequences) == 0:
            print("DEBUG SensorController: No OtherSerial sensors or sequences to initialize: sensors={len(other_sensors)}, sequences={len(other_sequences)}")
            return
        
        if len(other_sensors) == 0:
            print("DEBUG SensorController: No OtherSerial sensors to initialize")
        else:
            print(f"DEBUG SensorController: OtherSerial sensors: {[getattr(s, 'name', 'Unnamed') for s in other_sensors]}")
        if len(other_sequences) == 0:
            print("DEBUG SensorController: No OtherSerial sequences to initialize")
        else:
            print(f"DEBUG SensorController: OtherSerial sequences: {[seq.get('name', 'Unnamed') for seq in other_sequences]}")
            
        # Disconnect any existing OtherSerial connections ONLY if it's an explicit reconnect
        if is_explicit_reconnect:
            if 'other_serial' in data_controller.interfaces: # Check if it actually exists to avoid errors
                print("DEBUG SensorController: Disconnecting existing OtherSerial connections before explicit reinitialization")
                if hasattr(self.main_window, 'logger'):
                    self.main_window.logger.log("Clearing existing OtherSerial connections for explicit re-initialization.", "INFO")
                data_controller.disconnect_other_serial_all()
        
        # Group sequences by port and baud rate for efficiency
        port_configs = {}
        for seq in other_sequences:
            port = seq.get('port', '')
            baud = seq.get('baud', 9600)
            poll_interval = seq.get('poll_interval', 1.0)
            if port:
                key = (port, baud, poll_interval)
                if key not in port_configs:
                    port_configs[key] = []
                port_configs[key].append(seq)
        
        print(f"DEBUG SensorController: Port configurations for sequences: {len(port_configs)} unique port/baud/poll combinations")
        for (port, baud, poll_interval), seqs in port_configs.items():
            print(f"DEBUG SensorController: Port {port}, Baud {baud}, Poll {poll_interval}s: {len(seqs)} sequences - {[s.get('name', 'Unnamed') for s in seqs]}")
        
        # Now connect each unique port configuration
        for (port, baud, poll_interval), sequences in port_configs.items():
            try: # Outer try for this port configuration
                print(f"DEBUG SensorController: Connecting to port {port} at baud {baud} with poll interval {poll_interval}s for {len(sequences)} sequences")
                if hasattr(self.main_window, 'logger'):
                    self.main_window.logger.log(f"Connecting Other Serial on {port} at {baud} baud", "INFO")

                primary_sequence = sequences[0] if sequences else None
                sequence_obj = None  # Initialize sequence_obj

                if primary_sequence:
                    if isinstance(primary_sequence, dict):
                        # This is the correct path for dictionary sequences
                        print(f"DEBUG SensorController: primary_sequence dict before create_serial_sequence: {primary_sequence}")
                        actions = primary_sequence.get('actions') or primary_sequence.get('steps') or []
                        print(f"DEBUG SensorController: Creating SerialSequence using create_serial_sequence for {primary_sequence.get('name', 'Unnamed')} with {len(actions)} actions")
                        sequence_obj = data_controller.create_serial_sequence(primary_sequence.get('name', 'Unnamed'), actions)
                        current_steps = getattr(sequence_obj, 'steps', [])
                        print(f"DEBUG SensorController: Created SerialSequence object via create_serial_sequence for {getattr(sequence_obj, 'name', 'Unnamed')} with {len(current_steps)} steps")
                    else:
                        # This is for objects that already have steps attribute
                        sequence_obj = primary_sequence
                        print(f"DEBUG SensorController: Using existing sequence object with name: {getattr(sequence_obj, 'name', 'Unnamed')}")

                # Now connect to the device with the sequence
                if sequence_obj:
                    print(f"DEBUG SensorController: Connecting to port {port} with sequence {getattr(sequence_obj, 'name', 'Unnamed')}")
                    
                    # Use explicit reconnect if this is a user-initiated reconnect
                    if is_explicit_reconnect and hasattr(data_controller, 'explicit_reconnect_other_serial'):
                        # Use the new explicit reconnect method
                        success = data_controller.explicit_reconnect_other_serial(
                            port=port,
                            baud_rate=baud,
                            poll_interval=float(poll_interval),
                            sequence=sequence_obj
                        )
                    else:
                        # Use the regular connect method
                        success = data_controller.connect_other_serial(
                            port=port,
                            baud_rate=baud,
                            poll_interval=float(poll_interval),
                            sequence=sequence_obj
                        )
                    
                    if success:
                        print(f"DEBUG SensorController: Successfully connected to port {port}")
                        if hasattr(self.main_window, 'logger'):
                            self.main_window.logger.log(f"Connected to Other Serial on port {port}", "INFO")
                    else:
                        print(f"DEBUG SensorController: Failed to connect to port {port}")
                        if hasattr(self.main_window, 'logger'):
                            self.main_window.logger.log(f"Failed to connect to Other Serial on port {port}", "ERROR")
                else:
                    print(f"DEBUG SensorController: No valid sequence object for port {port}, skipping connection")
                    if hasattr(self.main_window, 'logger'):
                        self.main_window.logger.log(f"No valid sequence for port {port}, skipping connection", "WARNING")
                
            except Exception as e:
                print(f"DEBUG SensorController: Error connecting to port {port}: {e}")
                import traceback
                traceback.print_exc()
                if hasattr(self.main_window, 'logger'):
                    self.main_window.logger.log(f"Error connecting to Other Serial on port {port}: {e}", "ERROR")
                
        # Force an update to the connection status in the UI
        if hasattr(self.main_window, 'update_other_connected_status'):
            print("DEBUG SensorController: Forcing update of OtherSerial connection status in UI")
            # Determine if any connections were successful
            is_connected = False
            if 'other_serial' in data_controller.interfaces:
                other_serial_interfaces = data_controller.interfaces['other_serial']
                print(f"DEBUG SensorController: Inspecting other_serial_interfaces: type={type(other_serial_interfaces)}, content={other_serial_interfaces}")
                
                # Check if other_serial_interfaces is a dictionary with a 'connected' key
                if isinstance(other_serial_interfaces, dict) and 'connected' in other_serial_interfaces:
                    is_connected = other_serial_interfaces['connected']
                    print(f"DEBUG SensorController: Found direct connection status: {is_connected}")
                # Otherwise, safely check values
                elif isinstance(other_serial_interfaces, dict):
                    for key, value in other_serial_interfaces.items():
                        if isinstance(value, dict) and value.get('connected', False):
                            is_connected = True
                            print(f"DEBUG SensorController: Found connection in key {key}: {value}")
                            break
            
            print(f"DEBUG SensorController: OtherSerial connection status determined as: {'Connected' if is_connected else 'Not Connected'}")
            self.main_window.update_other_connected_status(is_connected)

    def _ensure_graph_visibility(self):
        """Check sensor visibility in graph.
        This method now just logs information about visible sensors without changing anything."""
        
        # Check if we have sensors first
        if not self.sensors:
            print("DEBUG: No sensors available for graph visibility check")
            return
        
        # Check how many sensors are set to show in graph
        visible_sensors = []
        for sensor in self.sensors:
            if getattr(sensor, 'show_in_graph', False) and getattr(sensor, 'enabled', False):
                visible_sensors.append(sensor.name)
        
        if visible_sensors:
            print(f"DEBUG: Found {len(visible_sensors)} sensors set to show in graph: {', '.join(visible_sensors)}")
        else:
            print("DEBUG: No sensors are set to show in graph")
        
        # Log the result
        if hasattr(self.main_window, 'logger'):
            if visible_sensors:
                self.main_window.logger.log(f"Found {len(visible_sensors)} sensors set to show in graph", "INFO")
            else:
                self.main_window.logger.log("No sensors are set to show in graph", "INFO")
    
    def update_labjack_data(self, data):
        """Update sensor objects with incoming LabJack data."""
        # print(f"DEBUG SensorController: update_labjack_data called with keys {list(data.keys())}") # Too frequent
        if not data or not isinstance(data, dict):
            return

        timestamp = data.get('timestamp', time.time()) # Use provided timestamp or current time
        updates_made = 0
        sensors_matched = []

        # Iterate through the sensors managed by this controller
        for sensor in self.sensors:
            # Check if the sensor is a LabJack sensor and its name/port matches a key in the data
            if sensor.interface_type == "LabJack":
                sensor_port = sensor.port.strip().upper() if sensor.port else ""
                
                # Try to find a match in the data keys
                matched_key = None
                if sensor_port in data:
                    matched_key = sensor_port
                else:
                    # Try flexible matching (e.g., AIN0 matching AIN0_EF_READ_A)
                    for data_key in data.keys():
                        dk_upper = data_key.upper()
                        if dk_upper == sensor_port or \
                           (dk_upper.startswith(sensor_port) and "_EF_READ_" in dk_upper) or \
                           (sensor_port.startswith(dk_upper) and "_EF_READ_" in sensor_port):
                            matched_key = data_key
                            break
                
                if matched_key:
                    sensors_matched.append(sensor.name)
                    # Get the *already corrected* value from the input data dict
                    corrected_value = data[matched_key]
                    try:
                        # Directly update the sensor's current value 
                        sensor.current_value = float(corrected_value)
                        updates_made += 1
                    except (ValueError, TypeError) as e:
                        # Handle potential errors if the corrected value isn't a valid float
                        print(f"ERROR SensorController: Failed to update LabJack sensor {sensor.name} ({matched_key}) value to float: {corrected_value} - {e}")
                        sensor.current_value = None # Set to None on error
                    except Exception as e:
                        print(f"ERROR SensorController: Unexpected error updating LabJack sensor {sensor.name} ({matched_key}): {e}")
                        sensor.current_value = None # Set to None on error
        
        # Log summary only if something was expected or happened
        if updates_made > 0 or sensors_matched:
             # print(f"DEBUG SensorController: update_labjack_data matched sensors: {sensors_matched}, updated values for {updates_made} sensors.")
             pass
            
        # Update the automation context with the latest LabJack values
        # This ensures triggers are checked as soon as data arrives (at 10Hz)
        # instead of waiting for the UI timer (at 2Hz).
        self.update_automation_context()
            
        # Don't trigger UI update here, let the MainWindow timer handle it
        # self.update_sensor_values() 
    
    def get_historical_buffer_key(self, sensor):
        """Generate the key used for storing this sensor's data in DataCollectionController.historical_buffer."""
        if not sensor:
            return None
        # Based on DataCollectionController's handle_*_data methods
        interface_type = getattr(sensor, 'interface_type', '').lower()
        result_key = None
        
        if interface_type == 'arduino':
            # Arduino uses the sensor name as the key in the data dict
            result_key = f"arduino_{getattr(sensor, 'name', 'unknown')}"
        elif interface_type == 'labjack':
            # LabJack uses the port/channel name (e.g., AIN0) as the key
            result_key = f"labjack_{getattr(sensor, 'port', 'unknown')}"
        elif interface_type == 'other_serial' or interface_type == 'otherserial':
            # OtherSerial uses key pattern "other_serial_{name}" in the historical buffer
            # Must match the pattern in handle_other_serial_data
            result_key = f"other_serial_{getattr(sensor, 'name', 'unknown')}"
        elif interface_type == 'optical_sensor' or interface_type == 'opticalsensor':
            # OpticalSensor uses key pattern "optical_{name}" in the historical buffer
            result_key = f"optical_{getattr(sensor, 'name', 'unknown')}"
        elif interface_type == 'audio_sensor' or interface_type == 'audiosensor':
            # AudioSensor uses key pattern "audio_{name}" in the historical buffer
            result_key = f"audio_{getattr(sensor, 'name', 'unknown')}"
        elif interface_type == 'mqtt':
            # MQTT uses key pattern "mqtt_{topic}" where topic is stored in 'port'
            result_key = f"mqtt_{getattr(sensor, 'port', 'unknown')}"
        elif interface_type == 'csv':
            # CSV interface uses the prefixed key stored in the port field
            result_key = getattr(sensor, 'port', None)
            if not result_key:
                result_key = f"csv_{getattr(sensor, 'name', 'unknown')}"
        # result_key = f"unknown_{getattr(sensor, 'name', 'unknown')}"
            
        # print(f"DEBUG: get_historical_buffer_key for {getattr(sensor, 'name', 'unknown')} (type: {interface_type}) => {result_key}")
        return result_key
            
    def get_sensor_by_name(self, name):
        """Find and return a sensor object by its display name."""
        for sensor in self.sensors:
            if hasattr(sensor, 'name') and sensor.name == name:
                return sensor
        return None
    
    def get_sensor_by_historical_key(self, key):
        """Find and return a sensor object by its historical buffer key."""
        if not key:
            return None
        # Iterate through sensors and find matching historical key
        for sensor in self.sensors:
            if self.get_historical_buffer_key(sensor) == key:
                return sensor
        return None
        
    def get_sensor_name_by_historical_key(self, key):
        """Find a sensor's display name given its historical buffer key."""
        # This requires iterating and checking the generated key for each sensor
        for sensor in self.sensors:
            if self.get_historical_buffer_key(sensor) == key:
                return getattr(sensor, 'name', key) # Return name, or key as fallback
        return key # Fallback if no matching sensor found

    def update_other_serial_data(self, data):
        """Update sensor objects with incoming Other Serial data."""
        print(f"DEBUG SensorController: update_other_serial_data called with data: {data}")
        
        if not data or not isinstance(data, dict):
            print("DEBUG SensorController: Invalid data format received, data is empty or not a dictionary")
            return

        timestamp = data.get('timestamp', time.time()) # Use provided timestamp or current time
        print(f"DEBUG SensorController: Using timestamp {timestamp}")
        
        updates_made = 0
        sensors_matched = []

        # Handle all data keys that match a sensor name (case-insensitive)
        for key in data:
            if key == 'timestamp':
                continue
                
            # Try to find sensor with this name
            matched_sensor = None
            for sensor in self.sensors:
                # Try direct match
                if sensor.interface_type == 'OtherSerial' and sensor.name == key:
                    matched_sensor = sensor
                    break
                    
                # Try case-insensitive match
                if sensor.interface_type == 'OtherSerial' and sensor.name.lower() == key.lower():
                    matched_sensor = sensor
                    break
                    
            if matched_sensor:
                sensors_matched.append(matched_sensor.name)
                try:
                    raw_value = data[key]
                    print(f"DEBUG SensorController: Matched sensor {matched_sensor.name}, raw value: {raw_value}")
                    try:
                        offset = float(getattr(matched_sensor, 'offset', 0.0))
                        conversion_factor = float(getattr(matched_sensor, 'conversion_factor', 1.0))
                        if not isinstance(raw_value, (int, float)):
                            import re
                            match = re.search(r'[-+]?\d*\.\d+|\d+', str(raw_value))
                            if match:
                                raw_value = float(match.group(0))
                            else:
                                raw_value = 0.0
                        value = (raw_value * conversion_factor) + offset
                        print(f"DEBUG SensorController: Corrected value: raw={raw_value}, offset={offset}, factor={conversion_factor}, final={value}")
                    except (ValueError, TypeError) as e:
                        print(f"DEBUG SensorController: Error applying conversion to {key} value '{raw_value}': {e}")
                        if isinstance(raw_value, (int, float)):
                            value = raw_value
                        else:
                            value = 0.0
                    matched_sensor.current_value = value
                    matched_sensor.last_update = timestamp
                    if hasattr(matched_sensor, 'raw_value'):
                        matched_sensor.raw_value = raw_value
                    updates_made += 1
                except Exception as e:
                    print(f"DEBUG SensorController: Error updating sensor {matched_sensor.name}: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"DEBUG SensorController: No matching sensor found for key '{key}'")
                if isinstance(data[key], (int, float)) or (isinstance(data[key], str) and data[key].replace('.', '', 1).isdigit()):
                    print(f"DEBUG SensorController: Creating new sensor for key '{key}' with value {data[key]}")
                    from app.models.sensor_model import SensorModel
                    new_sensor = SensorModel()
                    new_sensor.name = key
                    new_sensor.interface_type = 'OtherSerial'
                    new_sensor.unit = ""
                    new_sensor.offset = 0.0
                    new_sensor.conversion_factor = 1.0
                    new_sensor.current_value = float(data[key])
                    new_sensor.last_update = timestamp
                    import random
                    r, g, b = random.randint(50, 200), random.randint(50, 200), random.randint(50, 200)
                    new_sensor.color = f"#{r:02x}{g:02x}{b:02x}"
                    self.add_sensor_to_list(new_sensor)
                    sensors_matched.append(new_sensor.name)
                    updates_made += 1
                    self.update_sensor_table()
                    print(f"DEBUG SensorController: Created new sensor '{key}' with value {new_sensor.current_value}")
        print(f"DEBUG SensorController: update_other_serial_data matched sensors: {sensors_matched}, updated values for {updates_made} sensors.")
        if updates_made > 0:
            self.update_sensor_values()
            # Update automation context with current sensor values
            self.update_automation_context()
        return updates_made
        
    def _update_ui_for_sensor(self, sensor):
        """Update UI for a single sensor"""
        try:
            # Find the row for this sensor
            row = -1
            for i in range(self.main_window.data_table.rowCount()):
                name_item = self.main_window.data_table.item(i, 1)  # Name is in column 1
                if name_item and name_item.text() == sensor.name:
                    row = i
                    break
                    
            if row >= 0:
                # Get the value with the unit using our formatting method
                value_text = self.format_sensor_value(sensor)
                
                # Update the table
                # Value is in column 2
                value_item = self.main_window.data_table.item(row, 2)
                if value_item:
                    value_item.setText(value_text)
                    print(f"DEBUG SensorController: Updated UI table for sensor {sensor.name} with value {value_text}")
                else:
                    print(f"DEBUG SensorController: Value item is None for sensor {sensor.name} at row {row}, column 2")
            else:
                print(f"DEBUG SensorController: Could not find row for sensor {sensor.name} in the UI table")
        except Exception as e:
            print(f"DEBUG SensorController: Error updating UI for sensor {sensor.name}: {e}")
            import traceback
            traceback.print_exc()

    def get_sensor_names(self):
        """Get a list of all sensor names."""
        if hasattr(self, 'sensors'):
            return [sensor.name for sensor in self.sensors]
        return []

    def add_sensor_to_list(self, sensor):
        """Add a new sensor to the controller's sensor list
        
        Args:
            sensor: A SensorModel object to add to the list
        """
        try:
            # Check for duplicate names
            if any(s.name == sensor.name for s in self.sensors):
                self.main_window.logger.log(f"Sensor with name '{sensor.name}' already exists", "WARNING")
                # Add numbered suffix to make unique
                original_name = sensor.name
                suffix = 1
                while any(s.name == f"{original_name}_{suffix}" for s in self.sensors):
                    suffix += 1
                sensor.name = f"{original_name}_{suffix}"
                self.main_window.logger.log(f"Renamed to '{sensor.name}'", "INFO")
            
            # Ensure sensor has a color if not already set
            if not hasattr(sensor, 'color') or not sensor.color:
                # Generate a random color
                import random
                r = random.randint(50, 200)
                g = random.randint(50, 200)
                b = random.randint(50, 200)
                sensor.color = f"#{r:02x}{g:02x}{b:02x}"
            
            # Add to the sensors list
            self.sensors.append(sensor)
            
            # Emit status changed signal
            self.status_changed.emit()
            
            # Log the addition
            self.main_window.logger.log(f"Added new sensor: {sensor.name}", "INFO")
            
            return True
        except Exception as e:
            self.main_window.logger.log(f"Error adding sensor: {str(e)}", "ERROR")
            import traceback
            self.main_window.logger.log(traceback.format_exc(), "ERROR")
            return False

    def format_sensor_value(self, sensor):
        """Format a sensor value for display with appropriate precision"""
        # Get value (check for current_value first, fall back to value for backward compatibility)
        value = None
        if hasattr(sensor, 'current_value') and sensor.current_value is not None:
            value = sensor.current_value
        elif hasattr(sensor, 'value') and sensor.value is not None:
            # For backward compatibility with older code that might set value instead
            value = sensor.value
            
        if value is None:
            return self.NO_VALUE_DISPLAY  # Verwende die Klassenkonstante
            
        # Apply decimal precision based on data range
        try:
            if value == 0:
                value_display = "0"
            elif abs(value) < 0.001:
                value_display = f"{value:.6f}"
            elif abs(value) < 0.01:
                value_display = f"{value:.5f}"
            elif abs(value) < 0.1:
                value_display = f"{value:.4f}"
            elif abs(value) < 1:
                value_display = f"{value:.3f}"
            elif abs(value) < 10:
                value_display = f"{value:.2f}"
            elif abs(value) < 100:
                value_display = f"{value:.1f}"
            else:
                value_display = f"{int(value)}"
        except (ValueError, TypeError):
            value_display = str(value)
            
        # Add unit if available
        if hasattr(sensor, 'unit') and sensor.unit:
            value_display = f"{value_display} {sensor.unit}"
            
        return value_display

    def subscribe_all_mqtt_topics(self):
        """Subscribe to all topics for enabled MQTT sensors"""
        if not hasattr(self.main_window, 'data_collection_controller'):
            return
            
        dcc = self.main_window.data_collection_controller
        if not hasattr(dcc, 'mqtt_thread') or not dcc.mqtt_thread.is_connected():
            return
            
        for sensor in self.sensors:
            if getattr(sensor, 'interface_type', '') == 'MQTT' and sensor.enabled and sensor.port:
                print(f"Subscribing to MQTT topic: {sensor.port}")
                dcc.mqtt_thread.subscribe(sensor.port)

    def reinitialize_other_serial_connections(self, is_explicit_reconnect=False):
        """Reinitialize connections to OtherSerial devices, ensuring Arduino is disconnected first."""
        print(f"DEBUG SensorController: reinitialize_other_serial_connections called with is_explicit_reconnect={is_explicit_reconnect}")
        
        # Log this action clearly
        if hasattr(self.main_window, 'logger'):
            self.main_window.logger.log("Reconnecting Other Serial sensors...", "INFO")
        
        # First, disconnect Arduino if connected to free up the COM port
        if hasattr(self.main_window, 'data_collection_controller'):
            data_controller = self.main_window.data_collection_controller
            if 'arduino' in data_controller.interfaces and data_controller.interfaces['arduino']['connected']:
                print("DEBUG SensorController: Disconnecting Arduino to free up COM port")
                if hasattr(self.main_window, 'logger'):
                    self.main_window.logger.log("Disconnecting Arduino to free up COM port for Other Serial sensors", "INFO")
                data_controller.disconnect_arduino()
        
        # Log the current state of sensors and sequences
        other_sensors_count = len([s for s in self.sensors if getattr(s, 'interface_type', '') == 'OtherSerial'])
        other_sequences_count = len(getattr(self.main_window, 'other_sequences', []))
        print(f"DEBUG SensorController: Before initialization - OtherSerial sensors: {other_sensors_count}, sequences: {other_sequences_count}")
        if other_sequences_count > 0:
            print(f"DEBUG SensorController: Sequences available: {[seq.get('name', 'Unnamed') for seq in getattr(self.main_window, 'other_sequences', [])]}")
        
        # Now initialize OtherSerial connections
        self.initialize_other_serial_connections(is_explicit_reconnect=is_explicit_reconnect)
        print("DEBUG SensorController: Completed reinitialization of OtherSerial connections")
        
        # Return True to indicate success (even if no connections were made)
        return True
    
    # =========================================================================
    # OPTICAL SENSOR METHODS
    # =========================================================================
    
    def _show_add_optical_sensor_dialog(self):
        """Show the dialog to add a new Optical Sensor"""
        try:
            from app.ui.dialogs.optical_sensor_dialog import OpticalSensorAddDialog
            from app.core.interfaces.optical_sensor_interface import OpticalSensorInterface
            
            # Identify which camera index is currently in use by the main application
            # to avoid probing it, which causes a disconnect.
            skip_indices = []
            if hasattr(self.main_window, 'camera_controller') and self.main_window.camera_controller:
                cam_ctrl = self.main_window.camera_controller
                if getattr(cam_ctrl, 'is_connected', False) and hasattr(cam_ctrl, 'camera_thread') and cam_ctrl.camera_thread:
                    current_camera = getattr(cam_ctrl.camera_thread, 'camera_id', None)
                    if current_camera is not None:
                        skip_indices.append(current_camera)
            
            # Get list of available cameras (not already in use as optical sensors)
            # Pass skip_indices to avoid probing active cameras
            available_cameras = OpticalSensorInterface.list_available_cameras(skip_indices=skip_indices)
            
            # Exclude cameras already used as optical sensors (already handled inside list_available_cameras via is_camera_available)
            # but we'll keep the list clean.
            
            # Show the add dialog
            dialog = OpticalSensorAddDialog(self.main_window, available_cameras=available_cameras)
            
            if dialog.exec():
                config = dialog.get_sensor_config()
                self._add_optical_sensor(
                    name=config["name"],
                    camera_id=config["camera_id"],
                    mode=config["mode"]
                )
        except Exception as e:
            print(f"Error showing optical sensor dialog: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self.main_window,
                "Error",
                f"Could not open Optical Sensor dialog: {str(e)}"
            )
    
    def _add_optical_sensor(self, name, camera_id, mode="light_events"):
        """Add a new Optical Sensor
        
        Args:
            name: Sensor name
            camera_id: Camera device ID
            mode: Detection mode (light_events, brightness, color, position, particle_count, fill_level)
        """
        try:
            from app.core.interfaces.optical_sensor_interface import OpticalSensorInterface
            from app.models.sensor_model import SensorModel
            
            # Check if camera is already in use
            if not OpticalSensorInterface.is_camera_available(camera_id):
                QMessageBox.warning(
                    self.main_window,
                    "Camera in Use",
                    f"Camera {camera_id} is already being used as an optical sensor."
                )
                return False
            
            # Check if camera is used by camera controller
            if hasattr(self.main_window, 'camera_controller') and self.main_window.camera_controller:
                cam_ctrl = self.main_window.camera_controller
                if cam_ctrl.is_connected and hasattr(cam_ctrl, 'camera_thread') and cam_ctrl.camera_thread:
                    current_camera = getattr(cam_ctrl.camera_thread, 'camera_id', None)
                    if current_camera == camera_id:
                        result = QMessageBox.warning(
                            self.main_window,
                            "Camera in Use",
                            f"Camera {camera_id} is currently used for video.\n\n"
                            "The camera will be disconnected from video mode if you proceed.\n\n"
                            "Continue?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        )
                        if result != QMessageBox.StandardButton.Yes:
                            return False
                        # Disconnect from camera controller
                        cam_ctrl.disconnect()
            
            # Create the optical sensor interface
            interface = OpticalSensorInterface(
                camera_id=camera_id,
                mode=mode,
                name=name
            )
            
            # Store interface reference
            if not hasattr(self, 'optical_sensor_interfaces'):
                self.optical_sensor_interfaces = {}
            self.optical_sensor_interfaces[name] = interface
            
            # Create sensor model for each output of the mode
            output_keys = interface.get_output_keys()
            
            # Create a primary sensor model
            sensor = SensorModel(
                name=name,
                interface_type="OpticalSensor",
                port=str(camera_id),
                unit="",  # Unit depends on mode
                offset=0.0,
                conversion_factor=1.0,
                color="#FF6B6B",
                enabled=True,
                show_in_graph=True
            )
            
            # Store optical sensor config
            sensor.optical_config = {
                "camera_id": camera_id,
                "mode": mode,
                "output_keys": output_keys,
            }
            
            # Add to sensor list
            self.add_sensor_to_list(sensor)
            self.update_sensor_table()
            
            # Log
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(
                    f"Added Optical Sensor '{name}' (Camera {camera_id}, Mode: {mode})",
                    "INFO"
                )
            
            return True
            
        except Exception as e:
            print(f"Error adding optical sensor: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self.main_window,
                "Error",
                f"Could not add Optical Sensor: {str(e)}"
            )
            return False
    
    def connect_optical_sensor(self, sensor):
        """Connect an optical sensor
        
        Args:
            sensor: SensorModel with interface_type="OpticalSensor"
        """
        try:
            from app.core.interfaces.optical_sensor_interface import OpticalSensorInterface
            
            # Use default config if not present
            if not hasattr(sensor, 'optical_config') or not sensor.optical_config:
                config = {}
            else:
                config = sensor.optical_config
            
            camera_id = config.get("camera_id", 0)
            mode = config.get("mode", "light_events")
            
            # Create interface if not exists
            if not hasattr(self, 'optical_sensor_interfaces'):
                self.optical_sensor_interfaces = {}
            
            if sensor.name not in self.optical_sensor_interfaces:
                interface = OpticalSensorInterface(
                    camera_id=camera_id,
                    mode=mode,
                    name=sensor.name
                )
                self.optical_sensor_interfaces[sensor.name] = interface
            else:
                interface = self.optical_sensor_interfaces[sensor.name]
            
            # Connect
            if interface.connect():
                # Connect data signal with QueuedConnection for thread safety
                if interface.sensor_thread:
                    interface.sensor_thread.data_ready.connect(
                        lambda data, s=sensor: self._handle_optical_sensor_data(s, data),
                        Qt.ConnectionType.QueuedConnection
                    )
                    interface.sensor_thread.event_detected.connect(
                        lambda event, s=sensor: self._handle_optical_sensor_event(s, event),
                        Qt.ConnectionType.QueuedConnection
                    )
                
                # Update dashboard camera sources
                if hasattr(self.main_window, 'refresh_dashboard_camera_sources'):
                    self.main_window.refresh_dashboard_camera_sources()
                
                # Emit status changed signal so the nav button icon updates
                self.status_changed.emit()
                
                # Update optical sensor status display immediately
                if hasattr(self.main_window, 'update_optical_sensor_status'):
                    self.main_window.update_optical_sensor_status()
                
                return True
            
            return False
            
        except Exception as e:
            print(f"Error connecting optical sensor: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def disconnect_optical_sensor(self, sensor):
        """Disconnect an optical sensor"""
        try:
            if hasattr(self, 'optical_sensor_interfaces') and sensor.name in self.optical_sensor_interfaces:
                interface = self.optical_sensor_interfaces[sensor.name]
                interface.disconnect()
                del self.optical_sensor_interfaces[sensor.name]
                
                # Update dashboard camera sources
                if hasattr(self.main_window, 'refresh_dashboard_camera_sources'):
                    self.main_window.refresh_dashboard_camera_sources()
                
                # Emit status changed signal so the nav button icon updates
                self.status_changed.emit()
                
                return True
            return False
        except Exception as e:
            print(f"Error disconnecting optical sensor: {e}")
            return False
    
    def _handle_optical_sensor_data(self, sensor, data):
        """Handle data from an optical sensor
        
        Args:
            sensor: The SensorModel
            data: Data dictionary from the optical sensor
        """
        try:
            import time
            
            # Validate inputs
            if not sensor or not data:
                return
            
            if not isinstance(data, dict):
                print(f"WARNING: Optical sensor data is not a dict: {type(data)}")
                return
            
            # Record data flow for monitoring
            if hasattr(self.main_window, 'data_flow_controller'):
                byte_size = len(str(data))
                self.main_window.data_flow_controller.record_optical_sensor_data(byte_size)
            
            # Get the primary value based on mode
            mode = data.get("mode", "light_events")
            
            try:
                if mode == "light_events":
                    value = float(data.get("event_count", 0))
                elif mode == "brightness":
                    value = float(data.get("brightness_mean", 0))
                elif mode == "color":
                    value = float(data.get("hue", 0))
                elif mode == "position":
                    value = float(data.get("position_x_percent", 50))
                elif mode == "particle_count":
                    value = float(data.get("particle_count", 0))
                elif mode == "fill_level":
                    value = float(data.get("fill_level", 0))
                else:
                    value = 0.0
            except (ValueError, TypeError) as e:
                print(f"WARNING: Could not convert optical sensor value: {e}")
                value = 0.0
            
            # Update sensor value
            try:
                sensor.process_reading(value)
            except Exception as e:
                print(f"WARNING: Error updating sensor reading: {e}")
            
            # Store full optical sensor data for automation triggers
            try:
                if not hasattr(self, '_optical_sensor_data'):
                    self._optical_sensor_data = {}
                self._optical_sensor_data[sensor.name] = data.copy()
            except Exception as e:
                print(f"WARNING: Error storing optical sensor data: {e}")
            
            # Update UI (safe to call from any thread due to QueuedConnection)
            try:
                self.update_sensor_values()
            except Exception as e:
                print(f"WARNING: Error updating sensor values: {e}")
            
            # Feed data to graph controller for live plotting
            try:
                if self.main_window and hasattr(self.main_window, 'graph_controller') and self.main_window.graph_controller:
                    graph_data = {
                        'timestamp': data.get('timestamp', time.time()),
                        sensor.name: value
                    }
                    # Also include additional optical data for detailed logging if needed
                    for key in data:
                        if key not in ["timestamp", "mode"]:
                            try:
                                graph_data[f"{sensor.name}_{key}"] = data[key]
                            except Exception:
                                pass  # Skip invalid keys

                    self.main_window.graph_controller.plot_new_data(graph_data)
            except Exception as e:
                print(f"WARNING: Error sending optical data to graph: {e}")
                import traceback
                traceback.print_exc()

            # Also store in data collection
            try:
                if hasattr(self.main_window, 'data_collection_controller') and self.main_window.data_collection_controller:
                    data_controller = self.main_window.data_collection_controller
                    timestamp = data.get("timestamp", time.time())
                    sensor_data = {
                        "timestamp": timestamp,
                        sensor.name: value
                    }
                    # Store all output values as separate entries for CSV logging
                    for key in data:
                        if key not in ["timestamp", "mode"]:
                            try:
                                sensor_data[f"{sensor.name}_{key}"] = data[key]
                            except Exception:
                                pass  # Skip invalid keys
                    
                    # Store in historical buffer only if collecting
                    if data_controller.collecting_data:
                        try:
                            data_controller.historical_buffer_mutex.lock()
                            try:
                                for key, val in sensor_data.items():
                                    if key != 'timestamp':
                                        sensor_id = f"optical_{key}"  # Use optical_ prefix for historical buffer
                                        try:
                                            data_controller.historical_buffer[sensor_id].append((timestamp, val))
                                        except Exception as e:
                                            print(f"WARNING: Error appending to historical buffer for {sensor_id}: {e}")
                            finally:
                                data_controller.historical_buffer_mutex.unlock()
                        except Exception as e:
                            print(f"WARNING: Error locking historical buffer: {e}")
                    
                    # Always add to combined_data for live UI and CSV writing
                    try:
                        data_controller.combined_data_mutex.lock()
                        try:
                            for key, val in sensor_data.items():
                                if key != 'timestamp':
                                    prefixed_key = f"optical_{key}"
                                    try:
                                        data_controller.combined_data[prefixed_key] = val
                                        data_controller._last_sensor_update[prefixed_key] = timestamp
                                    except Exception as e:
                                        print(f"WARNING: Error adding to combined_data: {e}")
                            if 'timestamp' in sensor_data:
                                try:
                                    if 'timestamp' not in data_controller.combined_data or sensor_data['timestamp'] > data_controller.combined_data['timestamp']:
                                        data_controller.combined_data['timestamp'] = sensor_data['timestamp']
                                except Exception as e:
                                    print(f"WARNING: Error updating timestamp: {e}")
                        finally:
                            data_controller.combined_data_mutex.unlock()
                    except Exception as e:
                        print(f"WARNING: Error locking combined_data: {e}")
            except Exception as e:
                print(f"WARNING: Error storing optical data in data collection: {e}")
                import traceback
                traceback.print_exc()
                    
        except Exception as e:
            print(f"ERROR: Critical error handling optical sensor data: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_optical_sensor_event(self, sensor, event):
        """Handle an event from an optical sensor (e.g., light flash detected)
        
        Args:
            sensor: The SensorModel
            event: Event dictionary with type, timestamp, image_path, etc.
        """
        try:
            event_type = event.get("type", "unknown")
            timestamp = event.get("timestamp", time.time())
            image_path = event.get("image_path", "")
            
            # Format timestamp for display
            from datetime import datetime
            time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S.%f")[:-3]
            
            # Log the event
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(
                    f"🔆 Optical Event: {sensor.name} - {event_type} at {time_str}" +
                    (f" (saved to {image_path})" if image_path else ""),
                    "INFO"
                )
            
            # Play notification sound if enabled
            try:
                # Check if sound notifications are enabled (default: True for light events)
                enable_sound = sensor.extra_settings.get("enable_event_sound", True)
                if enable_sound:
                    import winsound
                    # Play a short beep (frequency 1000Hz, duration 100ms)
                    winsound.Beep(1000, 100)
            except Exception:
                pass  # Sound not available on this platform
            
            # Update status bar / UI notification
            if hasattr(self.main_window, 'statusBar'):
                self.main_window.statusBar().showMessage(
                    f"🔆 {sensor.name}: {event_type} detected at {time_str}", 5000
                )
            
            # Track event for automation triggers
            if not hasattr(self, '_optical_sensor_data'):
                self._optical_sensor_data = {}
            if sensor.name not in self._optical_sensor_data:
                self._optical_sensor_data[sensor.name] = {}
            
            # Increment event count for trigger checking
            current_count = self._optical_sensor_data[sensor.name].get('event_count', 0)
            self._optical_sensor_data[sensor.name]['event_count'] = current_count + 1
            self._optical_sensor_data[sensor.name]['last_event_type'] = event_type
            self._optical_sensor_data[sensor.name]['last_event_time'] = timestamp
            
            # Update automation context immediately
            self.update_automation_context()
            
        except Exception as e:
            print(f"Error handling optical sensor event: {e}")
    
    def show_optical_sensor_config(self, sensor):
        """Show configuration dialog for an optical sensor
        
        Args:
            sensor: SensorModel with interface_type="OpticalSensor"
        """
        try:
            from app.ui.dialogs.optical_sensor_dialog import OpticalSensorConfigDialog
            
            # Get current settings
            current_settings = {}
            if hasattr(sensor, 'optical_config'):
                current_settings.update(sensor.optical_config)
            
            # If interface exists, get settings from it
            if hasattr(self, 'optical_sensor_interfaces') and sensor.name in self.optical_sensor_interfaces:
                interface = self.optical_sensor_interfaces[sensor.name]
                if interface.sensor_thread:
                    current_settings.update(interface.sensor_thread.settings)
                    current_settings["mode"] = interface.mode
            
            # Show dialog
            dialog = OpticalSensorConfigDialog(
                self.main_window,
                sensor_name=sensor.name,
                current_settings=current_settings
            )
            
            # Connect apply signal
            def on_settings_changed(settings):
                self._apply_optical_sensor_settings(sensor, settings)
            
            dialog.settings_changed.connect(on_settings_changed)
            
            if dialog.exec():
                settings = dialog.get_settings()
                self._apply_optical_sensor_settings(sensor, settings)
                
        except Exception as e:
            print(f"Error showing optical sensor config: {e}")
            import traceback
            traceback.print_exc()
    
    def _apply_optical_sensor_settings(self, sensor, settings):
        """Apply settings to an optical sensor
        
        Args:
            sensor: SensorModel
            settings: Settings dictionary
        """
        try:
            # Check if we have an active project run directory
            run_dir = None
            if hasattr(self.main_window, 'project_controller'):
                run_dir = self.main_window.project_controller.get_current_run_directory()
            
            # Add run directory to settings if available
            if run_dir:
                settings = settings.copy()  # Don't modify the original dict
                settings["run_directory"] = run_dir
            
            # Update sensor config
            if not hasattr(sensor, 'optical_config'):
                sensor.optical_config = {}
            sensor.optical_config.update(settings)
            
            # Update interface if connected
            if hasattr(self, 'optical_sensor_interfaces') and sensor.name in self.optical_sensor_interfaces:
                interface = self.optical_sensor_interfaces[sensor.name]
                if settings.get("mode"):
                    interface.set_mode(settings["mode"])
                interface.update_settings(settings)
            
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(
                    f"Updated Optical Sensor '{sensor.name}' settings",
                    "INFO"
                )
                
        except Exception as e:
            print(f"Error applying optical sensor settings: {e}")
    
    def is_camera_used_as_sensor(self, camera_id):
        """Check if a camera is being used as an optical sensor
        
        Args:
            camera_id: Camera device ID
            
        Returns:
            True if the camera is in use as an optical sensor
        """
        try:
            from app.core.interfaces.optical_sensor_interface import OpticalSensorInterface
            return not OpticalSensorInterface.is_camera_available(camera_id)
        except Exception:
            return False
    
    def get_optical_sensors(self):
        """Get list of optical sensors
        
        Returns:
            List of SensorModel objects with interface_type="OpticalSensor"
        """
        return [s for s in self.sensors if getattr(s, 'interface_type', '') == 'OpticalSensor']
    
    # =========================================================================
    # AUDIO SENSOR METHODS
    # =========================================================================
    
    def _show_add_audio_sensor_dialog(self):
        """Show the dialog to add a new Audio Sensor"""
        try:
            from app.ui.dialogs.audio_sensor_dialog import AudioSensorAddDialog
            
            dialog = AudioSensorAddDialog(self.main_window)
            
            if dialog.exec():
                config = dialog.get_sensor_config()
                self._add_audio_sensor(
                    name=config["name"],
                    device_id=config["device_id"],
                    mode=config["mode"]
                )
        except Exception as e:
            print(f"Error showing audio sensor dialog: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self.main_window,
                "Error",
                f"Could not open Audio Sensor dialog: {str(e)}"
            )
    
    def _add_audio_sensor(self, name, device_id=None, mode="rms"):
        """Add a new Audio Sensor
        
        Args:
            name: Sensor name
            device_id: Audio device ID (None = default device)
            mode: Measurement mode (rms, peak, frequency, band_energy, zero_crossing, db_level, rpm)
        """
        try:
            from app.core.interfaces.audio_interface import AudioSensorInterface
            from app.models.sensor_model import SensorModel
            
            # Create the audio sensor interface
            interface = AudioSensorInterface(
                device_id=device_id,
                mode=mode,
                name=name
            )
            
            # Store interface reference
            if not hasattr(self, 'audio_sensor_interfaces'):
                self.audio_sensor_interfaces = {}
            self.audio_sensor_interfaces[name] = interface
            
            # Determine unit based on mode
            unit_map = {
                "rms": "",
                "peak": "",
                "frequency": "Hz",
                "band_energy": "",
                "zero_crossing": "/s",
                "db_level": "dB",
                "rpm": "RPM",
            }
            unit = unit_map.get(mode, "")
            
            # Create sensor model
            sensor = SensorModel(
                name=name,
                interface_type="AudioSensor",
                port=str(device_id) if device_id is not None else "default",
                unit=unit,
                offset=0.0,
                conversion_factor=1.0,
                color="#9C27B0",  # Purple for audio
                enabled=True,
                show_in_graph=True
            )
            
            # Store audio sensor config
            sensor.audio_config = {
                "device_id": device_id,
                "mode": mode,
                "output_keys": interface.get_output_keys(),
                "rpm_pulses_per_rev": 1.0,
                "min_frequency_hz": 5.0,
            }
            
            # Add to sensor list
            self.add_sensor_to_list(sensor)
            self.update_sensor_table()
            
            # Log
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(
                    f"Added Audio Sensor '{name}' (Device: {device_id}, Mode: {mode})",
                    "INFO"
                )
            
            # Update status
            if hasattr(self.main_window, 'update_audio_sensor_status'):
                self.main_window.update_audio_sensor_status()
            
            return True
            
        except Exception as e:
            print(f"Error adding audio sensor: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self.main_window,
                "Error",
                f"Could not add Audio Sensor: {str(e)}"
            )
            return False
    
    def connect_audio_sensor(self, sensor):
        """Connect an audio sensor
        
        Args:
            sensor: SensorModel with interface_type="AudioSensor"
        """
        try:
            from app.core.interfaces.audio_interface import AudioSensorInterface
            
            if not hasattr(sensor, 'audio_config'):
                print(f"Audio sensor {sensor.name} has no config")
                return False
            
            config = sensor.audio_config
            device_id = config.get("device_id", None)
            mode = config.get("mode", "rms")

            # Prepare processing settings that need to be applied to the thread
            processing_settings = {}
            for key in ("noise_gate", "smoothing", "band_low", "band_high", "peak_hold_ms", "rpm_pulses_per_rev", "min_frequency_hz"):
                if key in config:
                    processing_settings[key] = config[key]

            output_rate = config.get("output_rate", None)
            
            # Create interface if not exists
            if not hasattr(self, 'audio_sensor_interfaces'):
                self.audio_sensor_interfaces = {}
            
            if sensor.name not in self.audio_sensor_interfaces:
                interface = AudioSensorInterface(
                    device_id=device_id,
                    mode=mode,
                    name=sensor.name
                )
                self.audio_sensor_interfaces[sensor.name] = interface
            else:
                interface = self.audio_sensor_interfaces[sensor.name]
                # Ensure interface reflects latest config before connecting
                interface.device_id = device_id
                interface.set_mode(mode)

            # Apply output rate from config (if provided) before connecting so the thread picks it up
            if output_rate is not None:
                try:
                    interface.output_rate = max(1, int(output_rate))
                except (TypeError, ValueError):
                    pass
            
            # Connect the interface (this creates the thread)
            if interface.connect():
                # Connect data signal AFTER connect() to ensure thread exists
                # Disconnect the default handler and connect to our handler instead
                if interface.sensor_thread:
                    # Disconnect the default _on_data_ready handler
                    try:
                        interface.sensor_thread.data_ready.disconnect(interface._on_data_ready)
                    except:
                        pass  # May not be connected yet
                    
                    # Use sensor name instead of reference to avoid stale reference issues
                    sensor_name = sensor.name
                    
                    # Create a wrapper that finds the sensor by name
                    def handle_data(data):
                        # Find the actual sensor from the list
                        actual_sensor = None
                        for s in self.sensors:
                            if getattr(s, 'name', None) == sensor_name and getattr(s, 'interface_type', '') == 'AudioSensor':
                                actual_sensor = s
                                break
                        if actual_sensor:
                            self._handle_audio_sensor_data(actual_sensor, data)
                        else:
                            print(f"WARNING: Could not find sensor '{sensor_name}' when handling audio data")
                    
                    # Connect to our handler with QueuedConnection for thread safety
                    interface.sensor_thread.data_ready.connect(
                        handle_data,
                        Qt.ConnectionType.QueuedConnection
                    )
                    
                    print(f"DEBUG: Connected data_ready signal for audio sensor {sensor.name}")
                    print(f"DEBUG: Signal receivers: {interface.sensor_thread.receivers(interface.sensor_thread.data_ready)}")

                    # Apply processing settings (including noise_gate) to the running thread
                    if processing_settings:
                        interface.update_settings(processing_settings)
                
                # Emit status changed signal so the nav button icon updates
                self.status_changed.emit()
                
                # Force an immediate status update
                if hasattr(self.main_window, 'update_audio_sensor_status'):
                    self.main_window.update_audio_sensor_status()
                
                return True
            
            return False
            
        except Exception as e:
            print(f"Error connecting audio sensor: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def disconnect_audio_sensor(self, sensor):
        """Disconnect an audio sensor"""
        try:
            if hasattr(self, 'audio_sensor_interfaces') and sensor.name in self.audio_sensor_interfaces:
                interface = self.audio_sensor_interfaces[sensor.name]
                interface.disconnect()
                del self.audio_sensor_interfaces[sensor.name]
                
                # Emit status changed signal so the nav button icon updates
                self.status_changed.emit()
                
                return True
            return False
        except Exception as e:
            print(f"Error disconnecting audio sensor: {e}")
            return False
    
    def _handle_audio_sensor_data(self, sensor, data):
        """Handle data from an audio sensor
        
        Args:
            sensor: The SensorModel (may be a reference, find the actual one from self.sensors)
            data: Data dictionary from the audio sensor
        """
        try:
            import time
            
            # Validate inputs
            if not sensor or not data:
                return
            
            if not isinstance(data, dict):
                print(f"WARNING: Audio sensor data is not a dict: {type(data)}")
                return
            
            # CRITICAL FIX: Find the actual sensor from self.sensors by name
            # The sensor reference passed might be stale, so we need to find the current one
            actual_sensor = None
            for s in self.sensors:
                if getattr(s, 'name', None) == sensor.name and getattr(s, 'interface_type', '') == 'AudioSensor':
                    actual_sensor = s
                    break
            
            if not actual_sensor:
                print(f"WARNING: Could not find audio sensor '{sensor.name}' in self.sensors list")
                return
            
            # Use the actual sensor from the list
            sensor = actual_sensor
            
            # Record data flow for monitoring
            if hasattr(self.main_window, 'data_flow_controller'):
                byte_size = len(str(data))
                self.main_window.data_flow_controller.record_audio_sensor_data(byte_size)
            
            # Get the primary value based on mode
            mode = data.get("mode", "rms")
            
            try:
                if mode == "rms":
                    value = float(data.get("rms", 0))
                elif mode == "peak":
                    value = float(data.get("peak", 0))
                elif mode == "frequency":
                    value = float(data.get("dominant_frequency", 0))
                elif mode == "rpm":
                    # Convert dominant frequency to RPM if provided
                    rpm_val = data.get("rpm", None)
                    if rpm_val is None and "dominant_frequency" in data:
                        rpm_val = float(data.get("dominant_frequency", 0)) * 60.0
                    value = float(rpm_val if rpm_val is not None else 0)
                elif mode == "band_energy":
                    value = float(data.get("band_energy", 0))
                elif mode == "zero_crossing":
                    value = float(data.get("zero_crossing_rate", 0))
                elif mode == "db_level":
                    value = float(data.get("db_level", -60))
                else:
                    value = float(data.get("rms", 0))
            except (ValueError, TypeError) as e:
                print(f"WARNING: Could not convert audio sensor value: {e}")
                value = 0.0
            
            # Update sensor value
            try:
                processed_value = sensor.process_reading(value)
            except Exception as e:
                print(f"WARNING: Error updating sensor reading: {e}")
                import traceback
                traceback.print_exc()
            
            # Store full audio sensor data
            try:
                if not hasattr(self, '_audio_sensor_data'):
                    self._audio_sensor_data = {}
                self._audio_sensor_data[sensor.name] = data.copy()
            except Exception as e:
                print(f"WARNING: Error storing audio sensor data: {e}")
            
            # Update UI (safe to call from any thread due to QueuedConnection)
            try:
                self.update_sensor_values()
            except Exception as e:
                print(f"WARNING: Error updating sensor values: {e}")
            
            # If not collecting data, send directly to graph for live-only monitoring
            direct_plot_allowed = True
            try:
                if hasattr(self.main_window, 'data_collection_controller') and self.main_window.data_collection_controller:
                    data_controller = self.main_window.data_collection_controller
                    direct_plot_allowed = not getattr(data_controller, 'collecting_data', False)
            except Exception:
                pass

            if direct_plot_allowed and not (
                hasattr(self.main_window, 'graph_controller')
                and self.main_window.graph_controller
                and getattr(self.main_window.graph_controller, 'live_plotting_active', False)
            ):
                try:
                    if self.main_window and hasattr(self.main_window, 'graph_controller') and self.main_window.graph_controller:
                        graph_data = {
                            'timestamp': data.get('timestamp', time.time()),
                            sensor.name: value
                        }
                        for key in data:
                            if key not in ["timestamp", "mode"]:
                                try:
                                    graph_data[f"{sensor.name}_{key}"] = data[key]
                                except Exception:
                                    pass
                        self.main_window.graph_controller.plot_new_data(graph_data)
                except Exception as e:
                    print(f"WARNING: Error sending audio data to graph: {e}")
                    import traceback
                    traceback.print_exc()

            # Store in data collection (aligns to global emit tick)
            try:
                if hasattr(self.main_window, 'data_collection_controller') and self.main_window.data_collection_controller:
                    data_controller = self.main_window.data_collection_controller
                    timestamp = data.get("timestamp", time.time())
                    sensor_data = {
                        "timestamp": timestamp,
                        sensor.name: value
                    }
                    for key in data:
                        if key not in ["timestamp", "mode"]:
                            try:
                                sensor_data[f"{sensor.name}_{key}"] = data[key]
                            except Exception:
                                pass

                    # Store in historical buffer only if collecting data
                    if data_controller.collecting_data:
                        try:
                            data_controller.historical_buffer_mutex.lock()
                            try:
                                for key, val in sensor_data.items():
                                    if key != 'timestamp':
                                        sensor_id = f"audio_{key}"
                                        try:
                                            data_controller.historical_buffer[sensor_id].append((timestamp, val))
                                        except Exception as e:
                                            print(f"WARNING: Error appending to historical buffer for {sensor_id}: {e}")
                            finally:
                                data_controller.historical_buffer_mutex.unlock()
                        except Exception as e:
                            print(f"WARNING: Error locking historical buffer: {e}")
                    
                    # Always update combined_data and _last_sensor_update for live UI
                    try:
                        data_controller.combined_data_mutex.lock()
                        try:
                            for key, val in sensor_data.items():
                                if key != 'timestamp':
                                    prefixed_key = f"audio_{key}"
                                    try:
                                        data_controller.combined_data[prefixed_key] = val
                                        data_controller._last_sensor_update[prefixed_key] = timestamp
                                    except Exception as e:
                                        print(f"WARNING: Error adding to combined_data: {e}")
                            if 'timestamp' in sensor_data:
                                try:
                                    data_controller.combined_data['audio_timestamp'] = sensor_data['timestamp']
                                    if 'timestamp' not in data_controller.combined_data or sensor_data['timestamp'] > data_controller.combined_data['timestamp']:
                                        data_controller.combined_data['timestamp'] = sensor_data['timestamp']
                                except Exception as e:
                                    print(f"WARNING: Error updating timestamp: {e}")
                        finally:
                            data_controller.combined_data_mutex.unlock()
                    except Exception as e:
                        print(f"WARNING: Error locking combined_data: {e}")
            except Exception as e:
                print(f"WARNING: Error storing audio data in data collection: {e}")
                import traceback
                traceback.print_exc()
            
        except Exception as e:
            print(f"ERROR: Critical error handling audio sensor data: {e}")
            import traceback
            traceback.print_exc()
    
    def show_audio_sensor_config(self, sensor):
        """Show configuration dialog for an audio sensor"""
        try:
            from app.ui.dialogs.audio_sensor_dialog import AudioSensorConfigDialog
            
            # Get current settings
            current_settings = {}
            if hasattr(sensor, 'audio_config'):
                current_settings = sensor.audio_config.copy()
            
            # Show config dialog
            dialog = AudioSensorConfigDialog(
                self.main_window,
                sensor_name=sensor.name,
                current_settings=current_settings
            )
            
            if dialog.exec():
                new_settings = dialog.get_settings()
                
                # Update sensor config
                sensor.audio_config = new_settings
                
                # If connected, update the interface
                if hasattr(self, 'audio_sensor_interfaces') and sensor.name in self.audio_sensor_interfaces:
                    interface = self.audio_sensor_interfaces[sensor.name]
                    interface.set_mode(new_settings.get("mode", "rms"))
                    interface.update_settings(new_settings)
                
                # Save
                self.save_sensors()
                self.update_sensor_table()
                
        except Exception as e:
            print(f"Error showing audio sensor config: {e}")
            import traceback
            traceback.print_exc()
    
    def get_audio_sensors(self):
        """Get list of audio sensors
        
        Returns:
            List of SensorModel objects with interface_type="AudioSensor"
        """
        return [s for s in self.sensors if getattr(s, 'interface_type', '') == 'AudioSensor']
    
    def _is_sensor_calibrated(self, sensor):
        """Check if a sensor has calibration data
        
        Args:
            sensor: SensorModel to check
            
        Returns:
            bool: True if sensor has calibration applied
        """
        # Use the sensor model's has_calibration method if available
        if hasattr(sensor, 'has_calibration'):
            return sensor.has_calibration()
        
        # Fallback checks for older sensor models
        if hasattr(sensor, 'calibration_data') and sensor.calibration_data:
            return True
        
        # Check if offset is non-zero (simple calibration indicator)
        if hasattr(sensor, 'offset') and sensor.offset != 0:
            return True
        
        # Check for conversion_factor if available
        if hasattr(sensor, 'conversion_factor') and sensor.conversion_factor != 1.0:
            return True
            
        return False
    
    def open_calibration_for_sensor(self, sensor):
        """Open the calibration tool with the specified sensor preselected
        
        Args:
            sensor: SensorModel to calibrate
        """
        try:
            # Get or create the tools window
            if not hasattr(self.main_window, 'tools_window') or self.main_window.tools_window is None:
                from app.ui.tools import ToolsWindow
                self.main_window.tools_window = ToolsWindow(self.main_window)
                self.main_window.tools_window.set_main_window(self.main_window)
            
            tools_window = self.main_window.tools_window
            
            # Show the window
            tools_window.show()
            tools_window.raise_()
            tools_window.activateWindow()
            
            # Switch to the calibration tab (index 1)
            tools_window.tool_tabs.setCurrentIndex(1)
            
            # Preselect the sensor in the calibration tool
            cal_tool = tools_window.sensor_calibration
            if hasattr(cal_tool, 'sensor_combo'):
                # Refresh the sensor list first
                cal_tool._populate_sensor_combo()
                
                # Find and select the sensor
                sensor_key = f"{sensor.interface_type}_{sensor.name}"
                for i in range(cal_tool.sensor_combo.count()):
                    if cal_tool.sensor_combo.itemData(i) == sensor_key:
                        cal_tool.sensor_combo.setCurrentIndex(i)
                        break
            
            # Show help panel if user might need guidance
            if not tools_window.help_visible:
                tools_window._toggle_help()
                
        except Exception as e:
            print(f"Error opening calibration for sensor: {e}")
            import traceback
            traceback.print_exc()