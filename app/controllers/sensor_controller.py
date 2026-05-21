"""
Sensor Controller

Manages sensor data acquisition and operations.
"""
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit, QDialogButtonBox, QColorDialog, QCheckBox, QFormLayout, QSpinBox, QDoubleSpinBox, QPushButton, QMessageBox, QTableWidgetItem, QWidget, QScrollArea, QTextEdit, QInputDialog, QListWidgetItem, QGroupBox)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt
from app.models.sensor_model import SensorModel
from app.utils.common_types import StatusState
from app.models.settings_model import SettingsModel
from app.ui.theme import COLORS

# Import the LabJack interface
import sys
import os
import queue  # Add this import for queue.Empty exceptions
import time
import collections  # For deque in buffer clearing
import re

# Import from the app.core.interfaces package
from app.core.interfaces.interface_registry import InterfaceRegistry

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
        
        # NOTE: initialize() is now called explicitly by DAQApp.init_controllers()
        # to ensure all controllers (especially DataCollectionController) are available.
        # self.initialize()
    
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
        
        # Ensure table has 10 columns (added Sec Y)
        if table.columnCount() < 10:
            table.setColumnCount(10)
            table.setHorizontalHeaderLabels(["Use", "Sensor", "Value", "Interface", "Offset/Unit", "Stale xInt", "Smooth", "Sec Y", "Color", "Cal."])
            table.setColumnWidth(0, 50)  # Use checkbox
            table.setColumnWidth(1, 120)  # Sensor name
            table.setColumnWidth(2, 90)   # Value
            table.setColumnWidth(3, 80)   # Interface
            table.setColumnWidth(4, 95)   # Offset/Unit
            table.setColumnWidth(5, 85)  # Stale xInt
            table.setColumnWidth(6, 55)  # Smooth checkbox
            table.setColumnWidth(7, 50)  # Sec Y checkbox
            table.setColumnWidth(8, 70)   # Color
            table.setColumnWidth(9, 50)   # Cal.
        
        # Clear the table rows
        table.setRowCount(0)
        
        # Add rows for each sensor
        for i, sensor in enumerate(self.sensors):
            table.insertRow(i)
            
            # Create a checkbox for "Use in Graphs"
            show_checkbox = QCheckBox()
            show_checkbox.setChecked(sensor.show_in_graph)
            show_checkbox.setToolTip("Show sensor in graph visualizations. Data is always recorded for all enabled sensors.")
            show_checkbox.stateChanged.connect(lambda state, s=sensor: self.toggle_sensor_in_graph(s, state))
            
            # Center the checkbox in the cell
            cell_widget = QTableWidgetItem()
            table.setItem(i, 0, cell_widget)
            table.setCellWidget(i, 0, show_checkbox)
            
            # Sensor name
            name_item = QTableWidgetItem(sensor.name)
            name_item.setData(Qt.ItemDataRole.UserRole, sensor.name)
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

            # Secondary Y axis toggle
            sec_y_checkbox = QCheckBox()
            sec_y_checked = getattr(sensor, 'use_secondary_axis', False)
            sec_y_checkbox.setChecked(sec_y_checked)
            sec_y_checkbox.setToolTip("Plot this sensor on a separate Y-axis (right side)")
            sec_y_checkbox.stateChanged.connect(lambda state, s=sensor: self.toggle_secondary_axis(s, state))
            
            sec_y_container = QWidget()
            sec_y_layout = QVBoxLayout(sec_y_container)
            sec_y_layout.setContentsMargins(0, 0, 0, 0)
            sec_y_layout.setSpacing(0)
            sec_y_layout.addStretch()
            sec_y_layout.addWidget(sec_y_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
            sec_y_layout.addStretch()
            table.setCellWidget(i, 7, sec_y_container)

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
            table.setCellWidget(i, 8, color_container)
            
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
            
            table.setCellWidget(i, 9, cal_container)
            
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
            elif interface_type.lower() in ('otherserial', 'serial', 'other_serial') and sensor_name:
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
            
    def toggle_secondary_axis(self, sensor, state):
        """Toggle whether sensor uses the secondary Y axis"""
        sensor.use_secondary_axis = int(state) == Qt.CheckState.Checked.value
        
        # Save the updated sensor configuration
        self.save_sensors()
        
        # Trigger graph update if active
        if hasattr(self.main_window, 'graph_controller'):
            self.main_window.graph_controller.update_dashboard_graph()
        
        # Update the main analysis graph as well
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
    
    def add_sensor(self, preselected_type=None):
        """Add a new sensor (Harmonized)"""
        try:
            InterfaceRegistry.initialize()
            interfaces = InterfaceRegistry.get_interfaces()
            
            from app.ui.theme import DialogStyles, COLORS, GroupBoxStyles, ButtonStyles, ConnectionStyles
            from app.ui.dialogs.interface_config_dialog import InterfaceConfigDialog
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit, QDoubleSpinBox, QHBoxLayout, QLabel, QGroupBox, QCheckBox, QDialogButtonBox, QPushButton, QTextEdit, QInputDialog
            from PyQt6.QtCore import Qt

            dialog = QDialog(self.main_window)
            dialog.setWindowTitle("Add Sensor")
            dialog.setMinimumWidth(500)
            dialog.setStyleSheet(DialogStyles.dark_dialog())
            screen = dialog.screen()
            if screen:
                available = screen.availableGeometry()
                dialog.resize(min(max(560, int(available.width() * 0.58)), 920), min(max(560, int(available.height() * 0.82)), 900))
                dialog.setMaximumSize(available.width() - 40, available.height() - 40)
            
            layout = QVBoxLayout(dialog)
            scroll_area = QScrollArea(dialog)
            scroll_area.setWidgetResizable(True)
            scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            content = QWidget()
            content_layout = QVBoxLayout(content)
            
            # 1. Device & Interface Group
            dev_group = QGroupBox("Interface Selection")
            dev_group.setStyleSheet(GroupBoxStyles.default())
            dev_layout = QFormLayout(dev_group)
            
            device_type_combo = QComboBox()
            ordered_names = ["Arduino", "LabJack", "Serial", "Read CSV", "Optical", "Audio", "MQTT"]
            all_names = list(interfaces.keys())
            sorted_names = [n for n in ordered_names if n in all_names] + [n for n in all_names if n not in ordered_names]
            for name in sorted_names:
                device_type_combo.addItem(name)
            
            if preselected_type and preselected_type in sorted_names:
                device_type_combo.setCurrentText(preselected_type)
                
            dev_layout.addRow("Interface Type:", device_type_combo)
            
            description_label = QLabel("")
            description_label.setWordWrap(True)
            description_label.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; font-style: italic; margin-top: 5px;")
            dev_layout.addRow("", description_label)
            
            content_layout.addWidget(dev_group)
            
            # 2. Interface Configuration Group (Dynamic)
            int_group = QGroupBox("Interface Settings")
            int_group.setStyleSheet(GroupBoxStyles.default())
            int_layout = QFormLayout(int_group)
            content_layout.addWidget(int_group)
            
            # 3. Sensor Metadata Group
            sensor_group = QGroupBox("Sensor Details")
            sensor_group.setStyleSheet(GroupBoxStyles.default())
            sensor_layout = QFormLayout(sensor_group)
            
            measurement_combo = QComboBox()
            sensor_layout.addRow("Measurement:", measurement_combo)
            
            name_input = QLineEdit()
            sensor_layout.addRow("Sensor Name:", name_input)
            
            unit_input = QLineEdit()
            sensor_layout.addRow("Unit:", unit_input)
            
            poll_rate_spin = QDoubleSpinBox()
            poll_rate_spin.setRange(0.1, 1000.0)
            poll_rate_spin.setDecimals(3)
            global_rate = getattr(self.main_window.data_collection_controller, 'sampling_rate', 1.0)
            poll_rate_spin.setValue(global_rate)
            sensor_layout.addRow("Poll Rate (Hz):", poll_rate_spin)
            
            rate_info = QLabel(f"Global sampling rate: {global_rate:.3f} Hz.\nOverride if the hardware interface updates at a different speed.")
            rate_info.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 10px;")
            sensor_layout.addRow("", rate_info)
            
            content_layout.addWidget(sensor_group)
            
            # 4. Connection & Status Group
            conn_group = QGroupBox("Connection & Status")
            conn_group.setStyleSheet(GroupBoxStyles.default())
            conn_layout = QVBoxLayout(conn_group)
            
            status_row = QHBoxLayout()
            enabled_checkbox = QCheckBox("Enabled")
            enabled_checkbox.setChecked(True)
            
            autoconnect_checkbox = QCheckBox("Auto-connect on Startup")
            autoconnect_checkbox.setChecked(False)
            
            # (Settings will be loaded in update_dynamic_ui)

            status_row.addWidget(enabled_checkbox)
            status_row.addWidget(autoconnect_checkbox)
            conn_layout.addLayout(status_row)
            
            conn_btn_row = QHBoxLayout()
            status_indicator = QLabel("●")
            status_indicator.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 20px;")
            conn_btn_row.addWidget(status_indicator)
            status_text = QLabel("Disconnected")
            conn_btn_row.addWidget(status_text)
            conn_btn_row.addStretch()
            
            connect_btn = QPushButton("Connect")
            connect_btn.setMinimumWidth(100)
            conn_btn_row.addWidget(connect_btn)
            conn_layout.addLayout(conn_btn_row)

            diagnostics_group = QGroupBox("Diagnostics")
            diagnostics_group.setStyleSheet(GroupBoxStyles.default())
            diagnostics_layout = QVBoxLayout(diagnostics_group)
            diagnostics_btn_row = QHBoxLayout()
            diagnostics_output = QTextEdit()
            diagnostics_output.setReadOnly(True)
            diagnostics_output.setPlaceholderText("Test results will appear here.")
            diagnostics_output.setMinimumHeight(120)
            diagnostics_group.setVisible(False)
            diagnostics_layout.addLayout(diagnostics_btn_row)
            diagnostics_layout.addWidget(diagnostics_output)
            conn_layout.addWidget(diagnostics_group)

            content_layout.addWidget(conn_group)

            # Field storage
            self.current_dialog_fields = {}

            def _get_serial_measurements_for_current_port():
                """Return available published outputs for the Serial interface as 'Sequence:Target' keys."""
                try:
                    port_widget = self.current_dialog_fields.get("port")
                    selected_port = None
                    if port_widget and hasattr(port_widget, "currentText"):
                        selected_port = port_widget.currentText()
                    sequences = getattr(self.main_window, "other_sequences", []) or []
                    opts = set()
                    for seq in sequences:
                        if not isinstance(seq, dict):
                            continue
                        if selected_port and seq.get("port") and seq.get("port") != selected_port:
                            continue
                        seq_name = seq.get("name", "").strip()
                        if not seq_name:
                            continue
                        steps_or_actions = seq.get("actions") or seq.get("steps") or []
                        has_publish = False
                        for a in steps_or_actions:
                            if not isinstance(a, dict):
                                continue
                            if (a.get("type") or "").strip().lower() == "publish":
                                target = (a.get("target") or "").strip()
                                if target:
                                    opts.add(f"{seq_name}:{target}")
                                    has_publish = True
                        
                        # Fallback: if no publish steps, allow selecting the sequence itself
                        if not has_publish:
                            opts.add(f"{seq_name}:value")
                    return sorted(opts)
                except Exception:
                    return []

            def update_dynamic_ui():
                # Clear interface layout
                while int_layout.count() > 0:
                    item = int_layout.takeAt(0)
                    if item:
                        w = item.widget()
                        if w:
                            w.setParent(None)
                            w.deleteLater()
                
                self.current_dialog_fields = {}
                selected_type = device_type_combo.currentText()
                interface_class = interfaces.get(selected_type)
                
                # Update description
                if interface_class:
                    description = getattr(interface_class, "DESCRIPTION", "")
                    description_label.setText(description)
                    description_label.setVisible(bool(description))
                else:
                    description_label.setVisible(False)
                
                # Load interface-wide settings (Enabled/Auto-connect) for this type
                settings_key = selected_type.lower().replace(" ", "_")
                if hasattr(self, 'settings') and self.settings:
                    enabled = self.settings.get_bool(f"{settings_key}_enabled", True)
                    auto_conn = self.settings.get_bool(f"{settings_key}_auto_connect", False)
                else:
                    enabled = self.main_window.settings.value(f"{settings_key}_enabled", "true") == "true"
                    auto_conn = self.main_window.settings.value(f"{settings_key}_auto_connect", "false") == "true"
                
                enabled_checkbox.setChecked(enabled)
                autoconnect_checkbox.setChecked(auto_conn)

                if interface_class:
                    schema = getattr(interface_class, "CONFIG_SCHEMA", {})
                    for key, config in schema.items():
                        field_widget = self._create_ui_field(key, config, interface_class)
                        int_layout.addRow(config.get("label", key.replace("_", " ").title()) + ":", field_widget)
                        self.current_dialog_fields[key] = field_widget
                        # Refresh measurement options when Serial port changes
                        if device_type_combo.currentText() == "Serial" and key == "port" and hasattr(field_widget, "currentIndexChanged"):
                            field_widget.currentIndexChanged.connect(lambda _: update_dynamic_ui())
                    
                    refresh_measurements()

                while diagnostics_btn_row.count() > 0:
                    item = diagnostics_btn_row.takeAt(0)
                    widget = item.widget()
                    if widget:
                        widget.setParent(None)
                        widget.deleteLater()

                test_actions = []
                if interface_class and hasattr(interface_class, "get_test_actions"):
                    try:
                        test_actions = interface_class.get_test_actions() or []
                    except Exception:
                        test_actions = []

                diagnostics_group.setVisible(bool(test_actions))
                if test_actions:
                    for action in test_actions:
                        btn = QPushButton(action.get("label", action.get("id", "Run Test")))
                        btn.clicked.connect(lambda _, a=action: run_test_action(a))
                        diagnostics_btn_row.addWidget(btn)
                    diagnostics_btn_row.addStretch()

                update_conn_ui()

            def collect_current_interface_config():
                current_config = {}
                for key, widget in self.current_dialog_fields.items():
                    if isinstance(widget, QComboBox):
                        current_config[key] = widget.currentText()
                    elif isinstance(widget, QDoubleSpinBox):
                        current_config[key] = widget.value()
                    elif isinstance(widget, QCheckBox):
                        current_config[key] = widget.isChecked()
                    else:
                        current_config[key] = widget.text()
                return current_config

            def append_diagnostics(text):
                diagnostics_output.append(text)

            def run_test_action(action):
                selected_type = device_type_combo.currentText()
                interface_class = interfaces.get(selected_type)
                if not interface_class:
                    return

                input_value = None
                if action.get("input_label"):
                    value, ok = QInputDialog.getText(
                        dialog,
                        action.get("label", "Test Input"),
                        action.get("input_label"),
                        text=str(action.get("default_value", "")),
                    )
                    if not ok:
                        return
                    input_value = value

                try:
                    # Check for active instance first to avoid PermissionError if port is already open
                    instance = None
                    is_active_instance = False
                    dcc = getattr(self.main_window, 'data_collection_controller', None)
                    if dcc and selected_type in dcc.interface_threads:
                        active_thread = dcc.interface_threads[selected_type]
                        if hasattr(active_thread, 'interface'):
                            instance = active_thread.interface
                            is_active_instance = True
                    
                    if not instance:
                        instance = interface_class(**collect_current_interface_config())
                    
                    if not hasattr(instance, "run_test_action"):
                        QMessageBox.information(dialog, "Diagnostics", "No test actions are available for this interface.")
                        return
                    
                    # Only connect if not already connected
                    if not instance.is_connected():
                        if not instance.connect():
                            error = getattr(instance, "error_message", "Unknown error")
                            QMessageBox.critical(dialog, "Diagnostics", f"Could not connect to {selected_type}:\n{error}")
                            append_diagnostics(f"[FAILED] {action.get('label', action.get('id'))}\nConnection failed: {error}\n")
                            return

                    result = instance.run_test_action(action.get("id"), input_value=input_value)
                    success = bool(result.get("success")) if isinstance(result, dict) else bool(result)
                    message = result.get("message", str(result)) if isinstance(result, dict) else str(result)
                    prefix = "SUCCESS" if success else "FAILED"
                    append_diagnostics(f"[{prefix}] {action.get('label', action.get('id'))}\n{message}\n")

                    if success:
                        QMessageBox.information(dialog, "Diagnostics", message)
                    else:
                        QMessageBox.warning(dialog, "Diagnostics", message)
                except Exception as e:
                    QMessageBox.critical(dialog, "Diagnostics", f"Test failed:\n{e}")
                    append_diagnostics(f"[EXCEPTION] {action.get('label', action.get('id'))}\n{e}\n")
                finally:
                    try:
                        # Only disconnect if we created a TEMPORARY instance
                        if not is_active_instance and 'instance' in locals() and hasattr(instance, "is_connected") and instance.is_connected():
                            instance.disconnect()
                    except Exception:
                        pass

            def refresh_measurements():
                try:
                    selected_type = device_type_combo.currentText()
                    interface_class = interfaces.get(selected_type)
                    if not interface_class:
                        return

                    # Update measurement combo
                    current_selection = measurement_combo.currentText()
                    measurement_combo.clear()
                    outputs = []
                    
                    # Try to get outputs from active instance if connected
                    active_instance_outputs = []
                    dcc = getattr(self.main_window, 'data_collection_controller', None)
                    if dcc:
                        st_lower = selected_type.lower()
                        if st_lower == "arduino" and dcc.arduino_connected:
                            if hasattr(dcc, 'arduino_thread') and hasattr(dcc.arduino_thread, 'get_available_sensor_names'):
                                active_instance_outputs = dcc.arduino_thread.get_available_sensor_names()
                        elif st_lower == "labjack" and dcc.labjack_connected:
                            if hasattr(dcc, 'labjack_thread') and hasattr(dcc.labjack_thread, '_labjack_interface') and dcc.labjack_thread._labjack_interface:
                                if hasattr(dcc.labjack_thread._labjack_interface, 'get_instance_output_keys'):
                                    active_instance_outputs = dcc.labjack_thread._labjack_interface.get_instance_output_keys()
                                elif hasattr(dcc.labjack_thread._labjack_interface, 'get_labjack_channels'):
                                    active_instance_outputs = [ch['name'] for ch in dcc.labjack_thread._labjack_interface.get_labjack_channels()]
                        elif st_lower == "mqtt" and dcc.mqtt_connected:
                            if hasattr(dcc, 'mqtt_thread') and hasattr(dcc.mqtt_thread, 'interface') and dcc.mqtt_thread.interface:
                                if hasattr(dcc.mqtt_thread.interface, 'get_instance_output_keys'):
                                    active_instance_outputs = dcc.mqtt_thread.interface.get_instance_output_keys()
                        elif st_lower == "optical":
                            # Optical usually doesn't have a single global thread in the same way, but let's check
                            for key, thread in dcc.interface_threads.items():
                                if key.lower() == "optical" and hasattr(thread, 'interface') and thread.interface:
                                    if hasattr(thread.interface, 'get_instance_output_keys'):
                                        active_instance_outputs = thread.interface.get_instance_output_keys()
                                        break
                        else:
                            # Generic plugin support
                            interface_class = InterfaceRegistry.get_interface_class(selected_type)
                            if interface_class and hasattr(interface_class, "get_output_keys"):
                                active_instance_outputs = interface_class.get_output_keys()
                            
                            # Also check active thread for dynamic output keys
                            if not active_instance_outputs and selected_type in dcc.interface_threads:
                                thread = dcc.interface_threads[selected_type]
                                if hasattr(thread, 'interface') and hasattr(thread.interface, 'get_output_keys'):
                                    active_instance_outputs = thread.interface.get_output_keys()
                                elif hasattr(thread, 'get_available_sensor_names'):
                                    active_instance_outputs = thread.get_available_sensor_names()

                    if active_instance_outputs:
                        outputs = active_instance_outputs
                    elif selected_type == "Serial":
                        outputs = _get_serial_measurements_for_current_port()
                    elif hasattr(interface_class, "get_output_keys"):
                        outputs = interface_class.get_output_keys()

                    if outputs:
                        measurement_combo.addItems(outputs)
                        measurement_combo.setEnabled(True)
                        # Try to restore selection
                        idx = measurement_combo.findText(current_selection)
                        if idx >= 0:
                            measurement_combo.setCurrentIndex(idx)
                    else:
                        measurement_combo.addItem("Standard Output")
                        measurement_combo.setEnabled(False)
                except Exception as e:
                    print(f"Error refreshing measurements: {e}")
                    # Fallback
                    if measurement_combo.count() == 0:
                        measurement_combo.addItem("Standard Output")
                        measurement_combo.setEnabled(False)

            def update_conn_ui():
                selected_type = device_type_combo.currentText()
                is_connected = False
                if hasattr(self.main_window, 'data_collection_controller'):
                    dcc = self.main_window.data_collection_controller
                    
                    # Normalize selected_type for lookup
                    st_lower = selected_type.lower()
                    
                    if st_lower == "arduino": 
                        is_connected = dcc.arduino_connected
                    elif st_lower == "labjack": 
                        is_connected = dcc.labjack_connected
                    elif st_lower == "mqtt":
                        is_connected = bool(dcc.interfaces.get("mqtt", {}).get("connected", False))
                    elif st_lower == "serial" or st_lower == "otherserial":
                        is_connected = bool(dcc.interfaces.get("other_serial", {}).get("connected", False))
                    else:
                        # Check generic plugins (case-insensitive lookup)
                        for key, val in dcc.interfaces.items():
                            if key.lower() == st_lower:
                                is_connected = val.get('connected', False)
                                break
                        
                        # Fallback to checking threads if not in interfaces dict
                        if not is_connected:
                            for key, thread in dcc.interface_threads.items():
                                if key.lower() == st_lower:
                                    # If it has an interface and it's connected
                                    if hasattr(thread, 'interface') and thread.interface:
                                        is_connected = thread.interface.is_connected()
                                    elif hasattr(thread, 'is_connected'):
                                        is_connected = thread.is_connected()
                                    break
                
                # Check if connection status changed to refresh measurements
                was_connected = status_text.text() == "Connected"
                if is_connected and not was_connected:
                    refresh_measurements()

                if is_connected:
                    status_indicator.setStyleSheet(f"color: {COLORS.SUCCESS}; font-size: 20px;")
                    status_text.setText("Connected")
                    connect_btn.setText("Disconnect")
                    connect_btn.setStyleSheet(ConnectionStyles.disconnected())
                else:
                    status_indicator.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 20px;")
                    status_text.setText("Disconnected")
                    connect_btn.setText("Connect")
                    connect_btn.setStyleSheet(ConnectionStyles.connected())

            def on_conn_click():
                selected_type = device_type_combo.currentText()
                dcc = self.main_window.data_collection_controller
                if "Disconnect" in connect_btn.text():
                    if selected_type == "Arduino": dcc.disconnect_arduino()
                    elif selected_type == "LabJack": dcc.disconnect_labjack()
                    elif selected_type == "MQTT": dcc.disconnect_mqtt()
                    elif selected_type == "Serial": dcc.disconnect_other_serial()
                    else: dcc.disconnect_plugin_interface(selected_type)
                else:
                    # Connect logic
                    if selected_type == "Arduino": dcc.connect_arduino()
                    elif selected_type == "LabJack": dcc.connect_labjack()
                    elif selected_type == "MQTT":
                        broker = self.main_window.settings.value("mqtt_broker", "localhost")
                        port = int(self.main_window.settings.value("mqtt_port", 1883))
                        dcc.connect_mqtt(broker=broker, port=port)
                    elif selected_type == "Serial":
                        # Build and connect all sequences configured for the selected port (and current baud/poll group).
                        port_widget = self.current_dialog_fields.get("port")
                        baud_widget = self.current_dialog_fields.get("baud_rate")
                        poll_widget = self.current_dialog_fields.get("poll_interval")
                        port_val = port_widget.currentText() if port_widget else ""
                        baud_val = int(baud_widget.currentText()) if baud_widget and hasattr(baud_widget, "currentText") else 9600
                        poll_val = float(poll_widget.value()) if poll_widget and hasattr(poll_widget, "value") else 1.0

                        other_sequences = getattr(self.main_window, "other_sequences", []) or []
                        matching = []
                        for seq in other_sequences:
                            if isinstance(seq, dict) and seq.get("port") == port_val:
                                # Respect different baud/poll groups if stored
                                if int(seq.get("baud", baud_val)) != baud_val:
                                    continue
                                if float(seq.get("poll_interval", poll_val)) != poll_val:
                                    continue
                                matching.append(seq)

                        seq_objs = []
                        if matching:
                            for seq in matching:
                                actions = seq.get("actions") or seq.get("steps") or []
                                seq_obj = dcc.create_serial_sequence(seq.get("name", "Unnamed"), actions)
                                if seq_obj:
                                    seq_objs.append(seq_obj)

                        if seq_objs:
                            dcc.connect_other_serial(port=port_val, baud_rate=baud_val, poll_interval=poll_val, sequences=seq_objs)
                        else:
                            # Fallback: connect with a single empty sequence (no outputs until configured)
                            dcc.connect_other_serial(port=port_val, baud_rate=baud_val, poll_interval=poll_val)
                    else:
                        # Collect current dialog values for the connection
                        temp_config = {
                            "type": selected_type,
                            "name": name_input.text(),
                            "unit": unit_input.text(),
                            "poll_rate": poll_rate_spin.value()
                        }
                        for key, widget in self.current_dialog_fields.items():
                            if isinstance(widget, QComboBox): val = widget.currentText()
                            elif isinstance(widget, QDoubleSpinBox): val = widget.value()
                            elif isinstance(widget, QCheckBox): val = widget.isChecked()
                            else: val = widget.text()
                            temp_config[key] = val
                        
                        dcc.add_sensor_from_config(temp_config, persist=False, should_connect=True)
                update_conn_ui()

            device_type_combo.currentIndexChanged.connect(update_dynamic_ui)
            connect_btn.clicked.connect(on_conn_click)
            
            # Add a timer to keep connection status in sync
            from PyQt6.QtCore import QTimer
            sync_timer = QTimer(dialog)
            sync_timer.timeout.connect(update_conn_ui)
            sync_timer.start(1000) # Sync every second
            
            def _auto_name_from_measurement(t: str):
                if not t or t == "Standard Output":
                    return
                # If measurement is "Sequence:Target", default the sensor name to Target.
                if ":" in t:
                    name_input.setText(t.split(":", 1)[1])
                else:
                    name_input.setText(t)
            measurement_combo.currentTextChanged.connect(_auto_name_from_measurement)
            
            update_dynamic_ui()

            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            content_layout.addWidget(buttons)
            scroll_area.setWidget(content)
            layout.addWidget(scroll_area)
            
            if dialog.exec():
                selected_measurement = measurement_combo.currentText()
                if selected_measurement == "Standard Output": selected_measurement = None
                
                # Get interface-specific settings from the dynamic layout
                interface_config = {
                    "type": device_type_combo.currentText(),
                    "name": name_input.text(),
                    "unit": unit_input.text(),
                    "measurement": selected_measurement,
                    "poll_rate": poll_rate_spin.value(),
                    "enabled": enabled_checkbox.isChecked(),
                    "auto_connect": autoconnect_checkbox.isChecked()
                }
                
                # Collect values from dynamic fields
                for key, widget in self.current_dialog_fields.items():
                    if isinstance(widget, QComboBox):
                        interface_config[key] = widget.currentText()
                    elif isinstance(widget, QDoubleSpinBox):
                        interface_config[key] = widget.value()
                    elif isinstance(widget, QCheckBox):
                        interface_config[key] = widget.isChecked()
                    else:
                        interface_config[key] = widget.text()
                
                # Save auto_connect and enabled state to QSettings as well for consistency across the app
                # This ensures settings popups (which use QSettings) and sensors (which use virtual_sensors.json) stay in sync
                settings_key = device_type_combo.currentText().lower().replace(" ", "_")
                self.main_window.settings.setValue(f"{settings_key}_enabled", "true" if enabled_checkbox.isChecked() else "false")
                self.main_window.settings.setValue(f"{settings_key}_auto_connect", "true" if autoconnect_checkbox.isChecked() else "false")
                
                # For generic fields, also store them in QSettings so they appear in settings popups
                for key, val in interface_config.items():
                    if key not in ["name", "type", "unit", "measurement", "poll_rate", "enabled", "auto_connect"]:
                        self.main_window.settings.setValue(f"{settings_key}_{key}", str(val))

                return bool(self.main_window.data_collection_controller.add_sensor_from_config(interface_config))
            return False

        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self.main_window, "Error", f"Failed to open Add Sensor dialog: {e}")
            return False

    def _process_add_sensor_result(self, device_type, name, unit, measurement=None, poll_rate=10.0, enabled=True, auto_connect=False):
        """Process the results from the dynamic add sensor dialog"""
        # Collect configuration from dynamic fields
        config = {
            "name": name, 
            "unit": unit, 
            "type": device_type,
            "measurement": measurement, # The sub-key to look for
            "poll_rate": poll_rate,
            "enabled": enabled,
            "auto_connect": auto_connect
        }
        
        for key, widget in self.current_dialog_fields.items():
            if isinstance(widget, QComboBox):
                config[key] = widget.currentText()
            elif isinstance(widget, QDoubleSpinBox):
                config[key] = widget.value()
            elif isinstance(widget, QCheckBox):
                config[key] = widget.isChecked()
            else:
                config[key] = widget.text()
        
        # Now pass this to the data collection controller to actually add the sensor
        if hasattr(self.main_window, 'data_collection_controller'):
            # Save auto_connect and enabled state to QSettings as well for consistency across the app
            settings_key = device_type.lower().replace(" ", "_")
            self.main_window.settings.setValue(f"{settings_key}_enabled", "true" if enabled else "false")
            self.main_window.settings.setValue(f"{settings_key}_auto_connect", "true" if auto_connect else "false")
            
            ok = bool(self.main_window.data_collection_controller.add_sensor_from_config(config))
            if ok:
                self.update_sensor_table()
            return ok
        return False

    def _create_ui_field(self, key, config, interface_class):
        """Helper to create a UI widget based on schema config"""
        field_type = config.get("type", "string")
        default = config.get("default")
        
        if field_type == "list":
            widget = QComboBox()
            options = config.get("options", [])
            options_cmd = config.get("options_cmd")
            
            if options_cmd and hasattr(interface_class, "get_ui_options"):
                options = interface_class.get_ui_options(key)
            
            for opt in options:
                widget.addItem(str(opt))
            
            if default is not None:
                index = widget.findText(str(default))
                if index >= 0:
                    widget.setCurrentIndex(index)
            return widget
            
        elif field_type == "number":
            widget = QDoubleSpinBox()
            widget.setRange(-999999, 999999)
            if default is not None:
                widget.setValue(float(default))
            return widget
            
        elif field_type == "boolean":
            widget = QCheckBox()
            if default:
                widget.setChecked(True)
            return widget
            
        else:  # string
            widget = QLineEdit()
            if default is not None:
                widget.setText(str(default))
            return widget

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
        """Edit the selected sensor (Harmonized)"""
        if not hasattr(self.main_window, 'data_table'):
            return
            
        selected_rows = self.main_window.data_table.selectedItems()
        if not selected_rows:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self.main_window, "Edit Sensor", "Please select a sensor to edit first.")
            return
            
        row = selected_rows[0].row()
        if row < 0 or row >= len(self.sensors):
            return
            
        sensor = self.sensors[row]
        self.main_window.logger.log(f"Editing sensor: {sensor.name} ({sensor.interface_type})")

        # Use harmonized dialog for all types that have a schema or are standard
        InterfaceRegistry.initialize()
        interface_class = InterfaceRegistry.get_interface_class(sensor.interface_type)
        
        # If it's a specialized type that doesn't fit the generic pattern yet, keep old logic
        if sensor.interface_type == "OpticalSensor":
            self.show_optical_sensor_config(sensor)
            return
        elif sensor.interface_type in ("OtherSerial", "Serial"):
            from app.ui.dialogs.other_sensors_dialog import AddEditSensorDialog
            dialog = AddEditSensorDialog(self.main_window, sensor=sensor.to_dict(), sequences=getattr(self.main_window, 'other_sequences', []))
            if dialog.exec():
                updated_sensor_dict = dialog.get_sensor()
                if updated_sensor_dict["name"]:
                    updated_sensor = type(sensor).from_dict(updated_sensor_dict)
                    self.sensors[row] = updated_sensor
                    # Update in main_window.other_sensors
                    if hasattr(self.main_window, 'other_sensors'):
                        for i, vs in enumerate(self.main_window.other_sensors):
                            if (isinstance(vs, dict) and vs.get("name") == sensor.name) or (hasattr(vs, 'name') and vs.name == sensor.name):
                                self.main_window.other_sensors[i] = updated_sensor_dict
                                break
                    self.save_sensors()
                    self.update_sensor_table()
                    self.status_changed.emit()
            return

        # Generic harmonized Edit Dialog
        from app.ui.dialogs.interface_config_dialog import InterfaceConfigDialog
        
        # We need a way to edit sensor metadata AND interface config
        # For now, let's use a specialized dialog that combines both
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDoubleSpinBox, QCheckBox, QDialogButtonBox, QColorDialog, QPushButton, QHBoxLayout, QGroupBox, QComboBox
        from PyQt6.QtGui import QColor
        from app.ui.theme import DialogStyles, ButtonStyles, COLORS, GroupBoxStyles

        original_sensor_name = sensor.name

        dialog = QDialog(self.main_window)
        dialog.setWindowTitle(f"Edit Sensor: {sensor.name}")
        dialog.setMinimumWidth(450)
        dialog.setStyleSheet(DialogStyles.dark_dialog())
        
        layout = QVBoxLayout(dialog)
        
        # 1. Sensor Metadata Group
        meta_group = QGroupBox("Sensor Properties")
        meta_group.setStyleSheet(GroupBoxStyles.default())
        meta_layout = QFormLayout(meta_group)
        
        name_edit = QLineEdit(sensor.name)
        meta_layout.addRow("Name:", name_edit)
        
        unit_edit = QLineEdit(sensor.unit)
        meta_layout.addRow("Unit:", unit_edit)
        
        # Measurement selection (Harmonized)
        measurement_combo = QComboBox()
        meta_layout.addRow("Measurement:", measurement_combo)
        
        def _get_serial_measurements_for_current_port():
            """Return available published outputs for the Serial interface as 'Sequence:Target' keys."""
            try:
                # In edit dialog, we look at the port field in the current_dialog_fields or from sensor
                port_widget = self.current_dialog_fields.get("port")
                selected_port = None
                if port_widget and hasattr(port_widget, "currentText"):
                    selected_port = port_widget.currentText()
                elif hasattr(sensor, 'port'):
                    selected_port = sensor.port
                
                sequences = getattr(self.main_window, "other_sequences", []) or []
                opts = set()
                for seq in sequences:
                    if not isinstance(seq, dict): continue
                    if selected_port and seq.get("port") and seq.get("port") != selected_port:
                        continue
                    seq_name = seq.get("name", "").strip()
                    if not seq_name: continue
                    steps_or_actions = seq.get("actions") or seq.get("steps") or []
                    has_publish = False
                    for a in steps_or_actions:
                        if not isinstance(a, dict): continue
                        if (a.get("type") or "").strip().lower() == "publish":
                            target = (a.get("target") or "").strip()
                            if target:
                                opts.add(f"{seq_name}:{target}")
                                has_publish = True
                    # Fallback: if no publish steps, allow selecting the sequence itself
                    if not has_publish:
                        opts.add(f"{seq_name}:value")
                return sorted(opts)
            except Exception:
                return []

        def refresh_measurements():
            selected_type = sensor.interface_type
            measurement_combo.clear()
            outputs = []
            
            active_instance_outputs = []
            dcc = getattr(self.main_window, 'data_collection_controller', None)
            if dcc:
                st_lower = selected_type.lower()
                if st_lower == "arduino" and dcc.arduino_connected:
                    if hasattr(dcc, 'arduino_thread') and hasattr(dcc.arduino_thread, 'get_available_sensor_names'):
                        active_instance_outputs = dcc.arduino_thread.get_available_sensor_names()
                elif st_lower == "labjack" and dcc.labjack_connected:
                    if hasattr(dcc, 'labjack_thread') and hasattr(dcc.labjack_thread, '_labjack_interface') and dcc.labjack_thread._labjack_interface:
                        if hasattr(dcc.labjack_thread._labjack_interface, 'get_instance_output_keys'):
                            active_instance_outputs = dcc.labjack_thread._labjack_interface.get_instance_output_keys()
                        elif hasattr(dcc.labjack_thread._labjack_interface, 'get_labjack_channels'):
                            active_instance_outputs = [ch['name'] for ch in dcc.labjack_thread._labjack_interface.get_labjack_channels()]
                elif st_lower == "mqtt" and dcc.mqtt_connected:
                    if hasattr(dcc, 'mqtt_thread') and hasattr(dcc.mqtt_thread, 'interface') and dcc.mqtt_thread.interface:
                        if hasattr(dcc.mqtt_thread.interface, 'get_instance_output_keys'):
                            active_instance_outputs = dcc.mqtt_thread.interface.get_instance_output_keys()
                elif st_lower == "optical":
                    for key, thread in dcc.interface_threads.items():
                        if key.lower() == "optical" and hasattr(thread, 'interface') and thread.interface:
                            if hasattr(thread.interface, 'get_instance_output_keys'):
                                active_instance_outputs = thread.interface.get_instance_output_keys()
                                break
                else:
                    # Generic plugin support
                    interface_class = InterfaceRegistry.get_interface_class(selected_type)
                    if interface_class and hasattr(interface_class, "get_output_keys"):
                        active_instance_outputs = interface_class.get_output_keys()
                    
                    # Also check active thread for dynamic output keys
                    if not active_instance_outputs and selected_type in dcc.interface_threads:
                        thread = dcc.interface_threads[selected_type]
                        if hasattr(thread, 'interface') and hasattr(thread.interface, 'get_output_keys'):
                            active_instance_outputs = thread.interface.get_output_keys()
                        elif hasattr(thread, 'get_available_sensor_names'):
                            active_instance_outputs = thread.get_available_sensor_names()

            if active_instance_outputs:
                outputs = active_instance_outputs
            elif selected_type in ("Serial", "OtherSerial"):
                outputs = _get_serial_measurements_for_current_port()
            
            if outputs:
                measurement_combo.addItems(outputs)
                measurement_combo.setEnabled(True)
                # Set current mapping if available
                current_mapping = getattr(sensor, 'mapping', None)
                if current_mapping:
                    idx = measurement_combo.findText(current_mapping)
                    if idx >= 0: measurement_combo.setCurrentIndex(idx)
            else:
                measurement_combo.addItem("Standard Output")
                measurement_combo.setEnabled(False)

        # Offset & Factor row
        math_layout = QHBoxLayout()
        offset_edit = QDoubleSpinBox()
        offset_edit.setRange(-10000, 10000)
        offset_edit.setValue(sensor.offset)
        math_layout.addWidget(QLabel("Offset:"))
        math_layout.addWidget(offset_edit)
        
        factor_edit = QDoubleSpinBox()
        factor_edit.setRange(0.00001, 10000)
        factor_edit.setDecimals(5)
        factor_edit.setValue(sensor.conversion_factor)
        math_layout.addWidget(QLabel("Factor:"))
        math_layout.addWidget(factor_edit)

        # Advanced calibration info/button
        adv_cal_btn = QPushButton("...")
        adv_cal_btn.setFixedWidth(30)
        adv_cal_btn.setToolTip("Open advanced calibration wizard (Linear/Polynomial)")
        adv_cal_btn.setStyleSheet(ButtonStyles.get("secondary", "small"))
        adv_cal_btn.clicked.connect(lambda: [dialog.reject(), self.open_calibration_for_sensor(sensor)])
        math_layout.addWidget(adv_cal_btn)
        
        meta_layout.addRow("Calibration:", math_layout)

        # Info text for advanced calibration
        cal_hint = QLabel("💡 <i>Advanced calibration methods available via '...'</i>")
        cal_hint.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 10px; margin-top: -5px;")
        meta_layout.addRow("", cal_hint)

        # Advanced Calibration Info
        if hasattr(sensor, 'calibration_data') and sensor.calibration_data:
            cal_method = sensor.calibration_data.get('method', 'linear')
            cal_msg = f"⚠️ Advanced Calibration Active ({cal_method})"
            cal_info_label = QLabel(cal_msg)
            cal_info_label.setStyleSheet(f"color: {COLORS.WARNING}; font-weight: bold;")
            cal_info_label.setToolTip("Advanced calibration (from Tools > Calibration) is currently overriding these simple offset/factor values.")
            meta_layout.addRow("Status:", cal_info_label)
            
            reset_cal_btn = QPushButton("Reset Advanced Calibration")
            reset_cal_btn.setStyleSheet(ButtonStyles.get("secondary", "small"))
            def reset_advanced_cal():
                sensor.calibration_data = None
                cal_info_label.setText("✅ Using simple calibration")
                cal_info_label.setStyleSheet(f"color: {COLORS.SUCCESS};")
                reset_cal_btn.setEnabled(False)
            reset_cal_btn.clicked.connect(reset_advanced_cal)
            meta_layout.addRow("", reset_cal_btn)
        
        # Color & Visibility
        vis_layout = QHBoxLayout()
        color_btn = QPushButton("Color")
        color_btn.setMinimumWidth(80)
        current_color = QColor(sensor.color)
        def update_color_btn():
            color_btn.setStyleSheet(f"background-color: {current_color.name()}; color: {'black' if current_color.lightness() > 128 else 'white'}; font-weight: bold; border-radius: 4px;")
        update_color_btn()
        
        def pick_color():
            nonlocal current_color
            new_color = QColorDialog.getColor(current_color, dialog, "Select Sensor Color")
            if new_color.isValid():
                current_color = new_color
                update_color_btn()
        color_btn.clicked.connect(pick_color)
        vis_layout.addWidget(color_btn)
        
        show_graph_cb = QCheckBox("Show in Graph")
        show_graph_cb.setChecked(sensor.show_in_graph)
        vis_layout.addWidget(show_graph_cb)
        
        avg_cb = QCheckBox("Averaging")
        avg_cb.setChecked(sensor.averaging_enabled)
        vis_layout.addWidget(avg_cb)

        autoconnect_cb = QCheckBox("Auto-connect")
        autoconnect_cb.setChecked(getattr(sensor, 'auto_connect', True))
        vis_layout.addWidget(autoconnect_cb)
        
        meta_layout.addRow("Display:", vis_layout)
        layout.addWidget(meta_group)
        
        # 2. Interface Configuration Group (if schema exists)
        self.current_dialog_fields = {}
        if interface_class:
            # Use display name for settings key (harmonized)
            settings_key = sensor.interface_type.lower().replace(" ", "_")
            
            int_group = QGroupBox(f"{sensor.interface_type} Interface Settings")
            int_group.setStyleSheet(GroupBoxStyles.default())
            int_layout = QFormLayout(int_group)
            
            # Add port/channel field as first if it's LabJack or Arduino
            if sensor.interface_type == "LabJack":
                channel_combo = QComboBox()
                channels_info = self.get_labjack_channels_info()
                for ch in channels_info:
                    channel_combo.addItem(f"{ch['name']} - {ch['description']}")
                
                # Try to find current port
                index = channel_combo.findText(sensor.port, Qt.MatchFlag.MatchStartsWith)
                if index >= 0:
                    channel_combo.setCurrentIndex(index)
                int_layout.addRow("Channel:", channel_combo)
                self.current_dialog_fields["port"] = channel_combo
            
            # Add fields from schema
            schema = getattr(interface_class, "CONFIG_SCHEMA", {})
            for key, config in schema.items():
                # Skip port if we handled it specially above
                if key == "port" and sensor.interface_type == "LabJack":
                    continue
                    
                field_widget = self._create_ui_field(key, config, interface_class)
                
                # Try to set current value from QSettings (the source of truth for interfaces)
                try:
                    saved_val = self.main_window.settings.value(f"{settings_key}_{key}", None)
                except (TypeError, Exception):
                    saved_val = None
                    
                if saved_val is not None:
                    if isinstance(field_widget, QLineEdit):
                        field_widget.setText(str(saved_val))
                    elif isinstance(field_widget, QDoubleSpinBox):
                        try: field_widget.setValue(float(saved_val))
                        except: pass
                    elif isinstance(field_widget, QCheckBox):
                        field_widget.setChecked(str(saved_val).lower() == "true")
                    elif isinstance(field_widget, QComboBox):
                        idx = field_widget.findText(str(saved_val))
                        if idx >= 0: field_widget.setCurrentIndex(idx)
                
                int_layout.addRow(config.get("label", key.replace("_", " ").title()) + ":", field_widget)
                self.current_dialog_fields[key] = field_widget
                # Refresh measurement options when Serial port changes
                if sensor.interface_type in ("Serial", "OtherSerial") and key == "port" and hasattr(field_widget, "currentIndexChanged"):
                    field_widget.currentIndexChanged.connect(lambda _: refresh_measurements())

            layout.addWidget(int_group)
        
        # Initial measurement refresh
        refresh_measurements()
            
        # 3. Connection Control (Harmonized)
        if interface_class:
            conn_group = QGroupBox("Connection Control")
            conn_group.setStyleSheet(GroupBoxStyles.default())
            conn_layout = QHBoxLayout(conn_group)
            
            status_indicator = QLabel("●")
            status_indicator.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 20px;")
            conn_layout.addWidget(status_indicator)
            
            status_text = QLabel("Disconnected")
            conn_layout.addWidget(status_text)
            conn_layout.addStretch()
            
            connect_btn = QPushButton("Connect")
            connect_btn.setMinimumWidth(100)
            from app.ui.theme import ConnectionStyles
            
            def update_conn_ui():
                is_connected = False
                if hasattr(self.main_window, 'data_collection_controller'):
                    dcc = self.main_window.data_collection_controller
                    st_lower = sensor.interface_type.lower()
                    
                    if st_lower == "arduino":
                        is_connected = dcc.arduino_connected
                    elif st_lower == "labjack":
                        is_connected = dcc.labjack_connected
                    elif st_lower == "mqtt":
                        is_connected = dcc.mqtt_connected
                    elif st_lower in ("serial", "otherserial"):
                        is_connected = dcc.other_serial_connected
                    else:
                        # Check generic plugins (case-insensitive lookup)
                        for key, val in dcc.interfaces.items():
                            if key.lower() == st_lower:
                                is_connected = val.get('connected', False)
                                break
                        
                        # Fallback to checking threads
                        if not is_connected:
                            for key, thread in dcc.interface_threads.items():
                                if key.lower() == st_lower:
                                    if hasattr(thread, 'interface') and thread.interface:
                                        is_connected = thread.interface.is_connected()
                                    elif hasattr(thread, 'is_connected'):
                                        is_connected = thread.is_connected()
                                    break
                
                # If connection just happened, refresh measurements
                was_connected = status_text.text() == "Connected"
                if is_connected and not was_connected:
                    refresh_measurements()

                if is_connected:
                    status_indicator.setStyleSheet(f"color: {COLORS.SUCCESS}; font-size: 20px;")
                    status_text.setText("Connected")
                    connect_btn.setText("Disconnect")
                    connect_btn.setStyleSheet(ConnectionStyles.disconnected())
                else:
                    status_indicator.setStyleSheet(f"color: {COLORS.ERROR}; font-size: 20px;")
                    status_text.setText("Disconnected")
                    connect_btn.setText("Connect")
                    connect_btn.setStyleSheet(ConnectionStyles.connected())
            
            def on_conn_click():
                dcc = self.main_window.data_collection_controller
                if "Disconnect" in connect_btn.text():
                    if sensor.interface_type == "Arduino": dcc.disconnect_arduino()
                    elif sensor.interface_type == "LabJack": dcc.disconnect_labjack()
                    elif sensor.interface_type == "MQTT": dcc.disconnect_mqtt()
                    elif sensor.interface_type in ("Serial", "OtherSerial"): dcc.disconnect_other_serial()
                    else: dcc.disconnect_plugin_interface(sensor.interface_type)
                else:
                    if sensor.interface_type == "Arduino": self.connect_arduino()
                    elif sensor.interface_type == "LabJack": self.connect_labjack()
                    elif sensor.interface_type == "MQTT":
                        # Use settings
                        broker = self.main_window.settings.value("mqtt_broker", "localhost")
                        port = int(self.main_window.settings.value("mqtt_port", 1883))
                        dcc.connect_mqtt(broker=broker, port=port)
                    elif sensor.interface_type in ("Serial", "OtherSerial"):
                        # Connect with the configured port and baud
                        port_widget = self.current_dialog_fields.get("port")
                        baud_widget = self.current_dialog_fields.get("baud_rate")
                        port_val = port_widget.currentText() if port_widget else getattr(sensor, 'port', "")
                        baud_val = int(baud_widget.currentText()) if baud_widget and hasattr(baud_widget, 'currentText') else 9600
                        dcc.connect_other_serial(port=port_val, baud_rate=baud_val)
                    else:
                        # Collect current dialog values for the connection
                        temp_config = {"type": sensor.interface_type, "name": sensor.name}
                        for key, widget in self.current_dialog_fields.items():
                            if isinstance(widget, QComboBox): val = widget.currentText()
                            elif isinstance(widget, QDoubleSpinBox): val = widget.value()
                            elif isinstance(widget, QCheckBox): val = widget.isChecked()
                            else: val = widget.text()
                            temp_config[key] = val
                        
                        # Use add_sensor_from_config directly with persist=False to update the current sensor
                        dcc.add_sensor_from_config(temp_config, persist=False, should_connect=True)
                update_conn_ui()
                
            connect_btn.clicked.connect(on_conn_click)
            conn_layout.addWidget(connect_btn)
            update_conn_ui()
            
            # Use a timer to keep connection status updated while dialog is open
            from PyQt6.QtCore import QTimer
            conn_timer = QTimer(dialog)
            conn_timer.timeout.connect(update_conn_ui)
            conn_timer.start(1000) # Update every second
            
            layout.addWidget(conn_group)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec():
            # Update sensor properties
            sensor.name = name_edit.text()
            sensor.unit = unit_edit.text()
            sensor.offset = offset_edit.value()
            sensor.conversion_factor = factor_edit.value()
            sensor.color = current_color.name()
            sensor.show_in_graph = show_graph_cb.isChecked()
            sensor.averaging_enabled = avg_cb.isChecked()
            sensor.auto_connect = autoconnect_cb.isChecked()
            
            # Update mapping (Harmonized)
            selected_measurement = measurement_combo.currentText()
            if selected_measurement and selected_measurement != "Standard Output":
                sensor.mapping = selected_measurement
            else:
                sensor.mapping = None
            
            # Use display name for settings key (harmonized)
            settings_key = sensor.interface_type.lower().replace(" ", "_")
            
            # Save interface settings to QSettings
            self.main_window.settings.setValue(f"{settings_key}_enabled", "true" if sensor.enabled else "false")
            self.main_window.settings.setValue(f"{settings_key}_auto_connect", "true" if sensor.auto_connect else "false")
            
            # Save dynamic interface settings to QSettings
            dynamic_values = {}
            for key, widget in self.current_dialog_fields.items():
                if key == "port" and sensor.interface_type == "LabJack":
                    continue
                if isinstance(widget, QComboBox):
                    value = widget.currentText()
                elif isinstance(widget, QDoubleSpinBox):
                    value = widget.value()
                elif isinstance(widget, QCheckBox):
                    value = widget.isChecked()
                else:
                    value = widget.text()

                dynamic_values[key] = value
                if isinstance(value, bool):
                    self.main_window.settings.setValue(f"{settings_key}_{key}", "true" if value else "false")
                else:
                    self.main_window.settings.setValue(f"{settings_key}_{key}", str(value))
            
            if "port" in self.current_dialog_fields:
                widget = self.current_dialog_fields["port"]
                if isinstance(widget, QComboBox):
                    sensor.port = self._extract_channel_name(widget.currentText())
                else:
                    sensor.port = widget.text()
            
            # Save and update
            self.save_sensors()
            
            # If it's a plugin sensor, update in main_window.other_sensors too to persist changes to virtual_sensors.json
            if hasattr(self.main_window, 'other_sensors') and sensor.interface_type not in ["Arduino", "LabJack", "Serial", "Read CSV", "OtherSerial"]:
                for i, vs in enumerate(self.main_window.other_sensors):
                    name_match = False
                    if isinstance(vs, dict):
                        if vs.get("name") in (original_sensor_name, sensor.name) and vs.get("type") == sensor.interface_type:
                            name_match = True
                    elif hasattr(vs, 'name'):
                        if getattr(vs, 'name', None) in (original_sensor_name, sensor.name):
                            name_match = True
                        
                    if name_match:
                        # IMPORTANT:
                        # `virtual_sensors.json` uses the unified config format (keys like "type", "measurement"),
                        # while `SensorModel.to_dict()` uses the sensors.json format (keys like "interface_type", "mapping").
                        # Do not overwrite the unified config with the sensors.json schema.
                        if not isinstance(vs, dict):
                            try:
                                vs = vs.to_dict()
                            except Exception:
                                vs = {"name": sensor.name}

                        # Only update fields that are relevant for persistence & startup behavior.
                        vs["name"] = sensor.name
                        vs.setdefault("type", sensor.interface_type)
                        vs["unit"] = sensor.unit
                        vs["enabled"] = bool(getattr(sensor, "enabled", True))
                        vs["auto_connect"] = bool(getattr(sensor, "auto_connect", False))
                        vs["port"] = getattr(sensor, "port", vs.get("port", ""))
                        if hasattr(sensor, "mapping") and sensor.mapping is not None:
                            # Unified plugin config uses "measurement" (per output key)
                            vs["measurement"] = sensor.mapping
                        elif "measurement" in vs:
                            vs.pop("measurement", None)

                        for key, value in dynamic_values.items():
                            vs[key] = value

                        self.main_window.other_sensors[i] = vs
                        if hasattr(self.main_window, 'save_virtual_sensors'):
                            self.main_window.save_virtual_sensors()
                        break

            self.update_sensor_table()
            self.status_changed.emit()
            self.main_window.logger.log(f"Updated sensor: {sensor.name}")

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
            
            # If it's a virtual/plugin sensor, remove from main_window.other_sensors too
            if hasattr(self.main_window, 'other_sensors'):
                # Identify if this was a plugin sensor or OtherSerial
                is_plugin = False
                module_name = ""
                
                # Check if it matches any registered plugin interface or is OtherSerial
                if interface_type == 'OtherSerial':
                    is_plugin = True
                else:
                    # Check in registry
                    iface_class = InterfaceRegistry.get_interface_class(interface_type)
                    if iface_class:
                        module_name = getattr(iface_class, "__module__", "")
                        if "plugins." in module_name:
                            is_plugin = True
                
                if is_plugin:
                    original_len = len(self.main_window.other_sensors)
                    self.main_window.other_sensors = [
                        vs for vs in self.main_window.other_sensors 
                        if not ((isinstance(vs, dict) and vs.get('name') == removed_sensor.name) or 
                                (hasattr(vs, 'name') and vs.name == removed_sensor.name))
                    ]
                    
                    if len(self.main_window.other_sensors) != original_len:
                        print(f"DEBUG: Removed '{removed_sensor.name}' from main_window.other_sensors")
                        if hasattr(self.main_window, 'save_virtual_sensors'):
                            self.main_window.save_virtual_sensors()
                
                # If no more sensors for this plugin interface, disconnect it
                if is_plugin and interface_type != 'OtherSerial':
                    remaining_plugin_sensors = [s for s in self.sensors if s.interface_type == interface_type]
                    if not remaining_plugin_sensors:
                        print(f"DEBUG: No more sensors for plugin {interface_type}. Disconnecting interface.")
                        if hasattr(self.main_window, 'data_collection_controller'):
                            self.main_window.data_collection_controller.disconnect_plugin_interface(interface_type)
                    else:
                        # Re-configure the shared interface with the settings of a remaining sensor
                        # to ensure background polling uses valid registers/settings.
                        remaining_config = None
                        if hasattr(self.main_window, 'other_sensors'):
                            for vs in self.main_window.other_sensors:
                                if isinstance(vs, dict) and vs.get('type') == interface_type:
                                    if any(s.name == vs.get('name') for s in remaining_plugin_sensors):
                                        remaining_config = vs
                                        break
                        
                        if remaining_config and hasattr(self.main_window, 'data_collection_controller'):
                            print(f"DEBUG: Re-configuring plugin {interface_type} with settings from remaining sensor '{remaining_config.get('name')}'")
                            self.main_window.data_collection_controller.add_sensor_from_config(
                                remaining_config, persist=False, should_connect=False
                            )
            
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
            # EXCEPT when we are explicitly loading a past run (is_startup_load=False and we have a run dir)
            # CHANGE: We now allow fallback to default config even if a run dir exists, provided that 
            # run dir doesn't have its own sensors.json. This ensures global sensors (LabJack, etc.) 
            # are not lost on startup.
            if not is_startup_load and run_dir:
                sensors_file = os.path.join(run_dir, "sensors.json")
                if not os.path.exists(sensors_file):
                    self.main_window.logger.log(f"Sensors.json missing in run directory {run_dir}, falling back to default config", "INFO")
                else:
                    # If it exists, it should have been loaded above. If we are here, something else happened.
                    pass

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
                
        # Invalidate the DCC sensor cache after loading to ensure new sensors are mapped correctly
        if hasattr(self.main_window, 'data_collection_controller'):
            self.main_window.data_collection_controller.invalidate_sensor_cache()
    
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
            
                # Save all sensors including plugins to sensors.json 
                # This ensures they are available in Replay mode and for live metrics
                # on startup, even if they aren't fully reconnected yet.
                
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
                sensor_port_str = str(sensor.port)
                if " - " in sensor_port_str:
                    sensor.port = sensor_port_str.split(" - ")[0].strip()
                    
                # Make sure we don't have a header
                if str(sensor.port).startswith("---"):
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
                    sensor.set_value(data[sensor.name])
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
                            sensor.set_value(data[key])
                            processed_data[sensor.name] = sensor.current_value
                            matched = True
                            break
                        
                if not matched:
                    # print(f"DEBUG - No match found for Arduino sensor {sensor.name}")
                    pass
        
        # Handle non-Arduino sensors with the existing logic
        for sensor in self.sensors:
            if sensor.interface_type != "Arduino":
                if sensor.interface_type == "LabJack":
                    # For LabJack, data is already corrected in DataCollectionController.handle_labjack_data
                    # Use set_value to update current_value, history, and last_update_time
                    # Try to find a match in the data keys (case-insensitive)
                    matched_key = None
                    sensor_port = str(sensor.port).strip() if sensor.port is not None else ""
                    sensor_name = str(getattr(sensor, 'name', '')).strip()

                    # Build candidate keys in priority order:
                    # 1) configured port, 2) sensor name (legacy setups often use name as channel key)
                    candidates = []
                    if sensor_port and sensor_port.upper() != "ANY":
                        clean_port = sensor_port.split(" - ")[0].strip() if " - " in sensor_port else sensor_port
                        if clean_port:
                            candidates.append(clean_port.upper())
                    if sensor_name:
                        clean_name = sensor_name.split(" - ")[0].strip() if " - " in sensor_name else sensor_name
                        if clean_name:
                            name_upper = clean_name.upper()
                            if name_upper not in candidates:
                                candidates.append(name_upper)

                    if not candidates:
                        continue
                    
                    # 1) Exact key matching first (most reliable).
                    for target in candidates:
                        for data_key in data.keys():
                            if data_key.upper() == target:
                                matched_key = data_key
                                break
                        if matched_key:
                            break
                    
                    if not matched_key:
                        # 2) Flexible EF/base matching for compatibility.
                        for data_key in data.keys():
                            dk_upper = data_key.upper()
                            for target in candidates:
                                # Allow mapping base-channel sensors to EF data keys,
                                # but never map EF sensors back to base AIN keys.
                                if dk_upper.startswith(target) and "_EF_READ_" in dk_upper:
                                    matched_key = data_key
                                    break
                            if matched_key:
                                break
                    
                    if matched_key:
                        sensor.set_value(data[matched_key])
                    elif sensor.name in data:
                        sensor.set_value(data[sensor.name])
                    else:
                        # Try case-insensitive name match as final fallback
                        sensor_name_upper = sensor.name.upper()
                        for data_key in data.keys():
                            if data_key.upper() == sensor_name_upper:
                                sensor.set_value(data[data_key])
                                break
                elif sensor.interface_type in ("CSV", "Read CSV"):
                    # Match by prefixed key (stored in 'port' field) or name
                    target_key = sensor.port
                    
                    if target_key and target_key in data:
                        sensor.process_reading(data[target_key])
                    elif target_key and f"csv_{target_key}" in data:
                        sensor.process_reading(data[f"csv_{target_key}"])
                    elif f"csv_{sensor.name}" in data:
                        sensor.process_reading(data[f"csv_{sensor.name}"])
                    elif sensor.name in data:
                        sensor.process_reading(data[sensor.name])
                else:
                    # Match by mapping (for plugins) or special interfaces like MQTT
                    mapping = getattr(sensor, 'mapping', None)
                    if mapping and mapping in data:
                        # For OtherSerial/Serial, data is already corrected in DCC
                        if sensor.interface_type in ("OtherSerial", "Serial"):
                            sensor.set_value(data[mapping])
                        else:
                            sensor.process_reading(data[mapping])
                    elif sensor.name in data:
                        # Direct match by sensor name
                        if sensor.interface_type in ("OtherSerial", "Serial"):
                            sensor.set_value(data[sensor.name])
                        else:
                            sensor.process_reading(data[sensor.name])
                    elif sensor.interface_type == "MQTT" and sensor.port in data:
                        # Match by topic (stored in 'port' field) for MQTT
                        sensor.process_reading(data[sensor.port])
                    else:
                        # Last resort for plugins: if no mapping, try common output keys
                        # This handles plugin outputs where sensor name may not match 'Temperature'
                        if sensor.interface_type in ("Dwyer16B", "Love Controls 16B"):
                            if "Temperature" in data:
                                sensor.process_reading(data["Temperature"])
                            if "Setpoint" in data:
                                # We check both, so if a sensor is named 'Setpoint' it gets the right value
                                # even if 'Temperature' is also present in data.
                                sensor.process_reading(data["Setpoint"])
            
        # Update automation context with current sensor values
        self.update_automation_context()
        
        # NOTE: We no longer call self.update_sensor_values() here.
        # The MainWindow has a dedicated 1Hz timer that updates the table.
        # Triggering it here on every data packet (especially from plugins)
        # leads to a refresh rate higher than the intended 1Hz.
        
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
            return
        if not hasattr(self.main_window, 'data_table') or not self.main_window.data_table:
            return
            
        table = self.main_window.data_table
        
        # Mapping of sensor names to sensor objects for fast lookup
        sensor_map = {sensor.name: sensor for sensor in self.sensors}
        
        # Iterate through all table rows to find which sensor belongs where (handles sorting)
        for row in range(table.rowCount()):
            name_item = table.item(row, 1)
            if not name_item:
                continue
                
            sensor_name = name_item.data(Qt.ItemDataRole.UserRole) or name_item.text()
            sensor = sensor_map.get(sensor_name)
            
            if not sensor:
                continue
                
            # Check for staleness
            is_stale = False
            timeout_val = 2.0
            
            # Get the key used for staleness tracking
            hist_key = self.get_historical_buffer_key(sensor)
            
            # Use the new per-sensor last_update_time if available, 
            # falling back to the data_collection_controller's lookup
            if hasattr(sensor, 'last_update_time') and sensor.last_update_time > 0:
                # Use data_collection_controller to determine timeout
                if hasattr(self.main_window, 'data_collection_controller'):
                    dcc = self.main_window.data_collection_controller
                    timeout_val = dcc._get_stale_timeout_for_key(hist_key)
                
                # Check age
                age = time.time() - sensor.last_update_time
                if age > timeout_val:
                    is_stale = True
            elif hasattr(self.main_window, 'data_collection_controller'):
                dcc = self.main_window.data_collection_controller
                if hist_key:
                    timeout_val = dcc._get_stale_timeout_for_key(hist_key)
                    if hist_key in dcc._last_sensor_update:
                        last_ts = dcc._last_sensor_update[hist_key]
                        if time.time() - last_ts > timeout_val:
                            is_stale = True
                    else:
                        # No data ever received for this key
                        is_stale = True
            else:
                # No way to check staleness, assume not stale if we have a value
                pass
                
            # If we just received data (current_value is not None) and we are 
            # within a very short window (e.g. 2s), don't mark as stale even if 
            # the timeout logic above thought otherwise. This handles startup/glitches.
            if is_stale and hasattr(sensor, 'current_value') and sensor.current_value is not None:
                if hasattr(sensor, 'last_update_time') and time.time() - sensor.last_update_time < 2.0:
                    is_stale = False
                
            value_display = ""
            if not is_stale and hasattr(sensor, 'current_value') and sensor.current_value is not None:
                try:
                    value = sensor.current_value
                    if isinstance(value, (int, float)):
                        if abs(value) < 0.001 and value != 0:
                            value_display = f"{value:.6f}"
                        elif abs(value) < 100:
                            value_display = f"{value:.2f}"
                        else:
                            value_display = f"{value:.1f}"
                    else:
                        value_display = str(value)
                        
                    if hasattr(sensor, 'unit') and sensor.unit:
                        value_display = f"{value_display} {sensor.unit}"
                except Exception as e:
                    value_display = str(sensor.current_value)
            else:
                value_display = self.NO_VALUE_DISPLAY
                
            # Update the table cell
            current_item = table.item(row, 2)
            if not current_item or current_item.text() != value_display:
                # If item doesn't exist, create it
                if not current_item:
                    value_item = QTableWidgetItem(value_display)
                    value_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(row, 2, value_item)
                else:
                    current_item.setText(value_display)
                
        # Update automation context with current sensor values
        self.update_automation_context()
        
        # Force a repaint of the table to ensure values show up on startup
        table.viewport().update()

    def update_from_combined_data(self, data):
        """Update all sensors from a combined data dictionary (from all interfaces)"""
        if not data:
            return
            
        # Throttling to 20Hz (50ms) to save CPU
        now = time.time()
        if not hasattr(self, '_last_data_update_time'):
            self._last_data_update_time = 0
        if now - self._last_data_update_time < 0.05:
            return
        self._last_data_update_time = now

        timestamp = data.get('timestamp', time.time())
        updates_made = 0
        
        # print(f"DEBUG: update_from_combined_data with {len(data)} keys")
        
        for sensor in self.sensors:
            key = self.get_historical_buffer_key(sensor)
            if key and key in data:
                try:
                    raw_value = data[key]
                    # print(f"DEBUG: Found data for sensor {sensor.name} (key: {key}): {raw_value}")
                    
                    # Apply calibration/offset/conversion via SensorModel logic if possible
                    # or do it here for simplicity
                    offset = float(getattr(sensor, 'offset', 0.0))
                    conversion_factor = float(getattr(sensor, 'conversion_factor', 1.0))
                    
                    # Convert raw_value to float if it's a string
                    if isinstance(raw_value, str):
                        try:
                            # Try to extract a number from the string
                            import re
                            match = re.search(r'[-+]?\d*\.\d+|\d+', raw_value)
                            if match:
                                raw_value = float(match.group(0))
                            else:
                                raw_value = 0.0
                        except:
                            raw_value = 0.0
                            
                    if isinstance(raw_value, (int, float)):
                        # For interfaces that already apply calibration in DataCollectionController,
                        # we should not re-apply it here to avoid double-multiplication.
                        itype = getattr(sensor, 'interface_type', '').lower()
                        # We only skip for Serial/OtherSerial because they are corrected in DCC.
                        # Arduino/LabJack/etc. are also corrected in DCC, but they use update_sensor_data
                        # which calls set_value() directly. However, update_from_combined_data (this method)
                        # is called via combined_data_signal and MUST not re-apply calibration.
                        if itype in ('arduino', 'labjack', 'otherserial', 'serial', 'audio', 'audiosensor', 'optical', 'opticalsensor'):
                            sensor.set_value(raw_value)
                        else:
                            sensor.set_value((raw_value * conversion_factor) + offset)
                        updates_made += 1
                except Exception as e:
                    print(f"Error updating sensor {sensor.name} from combined data: {e}")
                    
        if updates_made > 0:
            # We don't call update_sensor_values here as it's called by a timer anyway.
            # This just ensures the data is ready for the next UI refresh.
            pass

    def get_historical_buffer_key(self, sensor):
        """Helper to get the prefixed key used in combined_data and historical_buffer"""
        if not sensor:
            return None
            
        interface_type = getattr(sensor, 'interface_type', '')
        itype_lower = interface_type.lower()
        
        if itype_lower == "arduino":
            return f"arduino_{sensor.name}"
        elif itype_lower == "labjack":
            # Prefer port/channel name, fallback to name if port is "ANY" or empty
            port = getattr(sensor, 'port', None)
            if port and str(port).upper() != "ANY":
                # Ensure we strip any trailing/leading spaces or descriptions
                clean_port = str(port).strip()
                if " - " in clean_port:
                    clean_port = clean_port.split(" - ")[0].strip()
                return f"labjack_{clean_port}"
            return f"labjack_{sensor.name}"
        elif itype_lower == "serial" or itype_lower == "otherserial" or itype_lower == "other_serial":
            return f"other_serial_{sensor.name}"
        elif itype_lower == "mqtt":
            return f"mqtt_{sensor.name}"
        elif itype_lower == "read csv" or itype_lower == "csv":
            # For CSV, the key might be in the port field or follow the standard prefix
            port_key = getattr(sensor, 'port', None)
            if port_key:
                port_key_str = str(port_key)
                if port_key_str.startswith("csv_"):
                    return port_key_str
            return f"csv_{sensor.name}"
        elif itype_lower == "audio" or itype_lower == "audiosensor":
            return f"audio_{sensor.name}"
        elif itype_lower == "optical" or itype_lower == "opticalsensor":
            return f"optical_{sensor.name}"
        else:
            # For dynamic plugins and others
            # measurement_name is often stored in the 'mapping' field for plugins
            mapping = getattr(sensor, 'mapping', None)
            
            # Special case for Dwyer16B (and legacy Love Controls 16B) default mapping
            if not mapping and itype_lower in ("dwyer16b", "love controls 16b"):
                mapping = "Temperature"
                
            if mapping:
                # Use the original case for interface_type to match handle_plugin_data
                return f"{interface_type}_{mapping}"
            return f"{interface_type}_{sensor.name}"
    
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
            # Connect to Arduino using saved settings
            success = self.main_window.data_collection_controller.connect_arduino()
            
            if success:
                # Start monitoring Arduino data
                self._start_arduino_monitoring()
                
                # Set connected flag
                self.connected = True
                
                # Log success
                self.main_window.logger.log("Connected to Arduino")
                
                # Update UI status display
                if hasattr(self.main_window, 'update_device_connection_status_ui'):
                    self.main_window.update_device_connection_status_ui('arduino', True)
                
                # Emit status changed signal
                self.status_changed.emit()
                
                return True
            else:
                self.main_window.logger.log("Failed to connect to Arduino", "ERROR")
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
    
    def connect_labjack(self, device_identifier=None):
        """Connect to LabJack using the DataCollectionController
        
        Args:
            device_identifier: Specific serial number or "ANY" (if None, use settings)
        Returns:
            True if connection was successful, False otherwise
        """
        print(f"DEBUG SENSOR_CONTROLLER: connect_labjack called with identifier='{device_identifier}'") 
        
        # Make sure the data collection controller exists
        if not hasattr(self.main_window, 'data_collection_controller'):
            print("ERROR SENSOR_CONTROLLER: Data Collection Controller not found!")
            if hasattr(self.main_window, 'logger'): 
                self.main_window.logger.log("Data Collection Controller not found during LabJack connect", "ERROR")
            return False
            
        # Call the DataCollectionController's connect method
        print("DEBUG SENSOR_CONTROLLER: Calling data_collection_controller.connect_labjack()")
        
        # If device_identifier is provided, use it as the port
        success = self.main_window.data_collection_controller.connect_labjack(
            port=device_identifier
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
        # self.update_sensor_values()
            
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
        # self.update_sensor_values()
        
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
    
    def initialize(self, defer_connections=False):
        """Initialize the controller and set up initial sensor state (Harmonized).
        
        If defer_connections is True, only loads sensor definitions from disk — no hardware
        auto-connect. Call initialize_hardware_connections() from a QTimer after the window is shown.
        """
        try:
            # Load saved sensors
            self.load_sensors()
            
            # Repair any sensors that might be incomplete or corrupted
            self.repair_sensors()
            
            # Ensure graph visibility is correctly configured
            self._ensure_graph_visibility()
            
            if defer_connections:
                return
            
            self.initialize_hardware_connections()
            
        except Exception as e:
            # Log any exceptions during initialization
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error initializing sensor controller: {str(e)}", "ERROR")
            print(f"Error initializing sensor controller: {str(e)}")
            import traceback
            traceback.print_exc()

    def initialize_hardware_connections(self):
        """Auto-connect hardware (Arduino, LabJack, MQTT, plugins, Other Serial, audio, optical).
        Safe to invoke from a queued/deferred call after the main window is visible."""
        try:
            # Harmonized Auto-connect logic for all registered interfaces
            InterfaceRegistry.initialize()
            interfaces = InterfaceRegistry.get_interfaces()
            
            for display_name in interfaces:
                # Map display name to settings key (e.g. "Arduino" -> "arduino")
                settings_key = display_name.lower().replace(" ", "_")
                
                # Skip plugins/virtual sensors here - they are handled by main_window._connect_virtual_sensors
                # after the sensors and sequences are fully loaded from virtual_sensors.json.
                # This prevents connecting too early with dummy configs.
                module_name = getattr(interfaces[display_name], "__module__", "")
                if not module_name.startswith("app.core.interfaces"):
                    print(f"DEBUG: Skipping harmonized auto-connect for plugin '{display_name}' in sc.initialize()")
                    continue

                # Get settings using the SettingsModel helper if possible
                enabled = True
                auto_connect = False
                
                if hasattr(self, 'settings') and self.settings:
                    enabled = self.settings.get_bool(f"{settings_key}_enabled", True)
                    auto_connect = self.settings.get_bool(f"{settings_key}_auto_connect", False)
                else:
                    enabled = self.main_window.settings.value(f"{settings_key}_enabled", "true") == "true"
                    auto_connect = self.main_window.settings.value(f"{settings_key}_auto_connect", "false") == "true"
                
                if enabled and auto_connect:
                    self.main_window.logger.log(f"Auto-connecting to {display_name}...")
                    
                    if display_name == "Arduino":
                        self.connect_arduino()
                        self._start_arduino_monitoring()
                        self.force_update_arduino_status()
                    elif display_name == "LabJack":
                        self.connect_labjack()
                        self._start_labjack_status_monitoring()
                    elif display_name == "MQTT":
                        # MQTT connect requires settings from MainWindow
                        if hasattr(self.main_window, 'data_collection_controller'):
                            broker = self.main_window.settings.value("mqtt_broker", "localhost")
                            port = int(self.main_window.settings.value("mqtt_port", 1883))
                            client_id = self.main_window.settings.value("mqtt_client_id", f"ArtefaktDAQ_{int(time.time())}")
                            user = self.main_window.settings.value("mqtt_username", "")
                            pw = self.main_window.settings.value("mqtt_password", "")
                            self.main_window.data_collection_controller.connect_mqtt(
                                broker=broker, port=port, client_id=client_id, username=user, password=pw
                            )
                    else:
                        # Handle other built-in interfaces via DataCollectionController
                        if hasattr(self.main_window, 'data_collection_controller'):
                            # Explicitly pass the should_connect flag based on auto_connect setting
                            self.main_window.data_collection_controller.connect_plugin_interface(
                                display_name, 
                                should_connect=auto_connect
                            )

            # Legacy connection handling for non-harmonized interfaces
            # Connect OtherSerial sensors
            self.initialize_other_serial_connections()
            
            # Auto-connect audio and optical sensors
            self.initialize_audio_optical_connections()
            
            # Rebuild averaging cache after initialization to ensure it's current
            if hasattr(self.main_window, 'data_collection_controller'):
                self.main_window.data_collection_controller._rebuild_averaging_cache()
                self.main_window.logger.log("Rebuilt averaging cache after sensor controller initialization", "INFO")
                
                # Initial table update
                self.update_sensor_table()
            
        except Exception as e:
            # Log any exceptions during initialization
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error initializing sensor controller: {str(e)}", "ERROR")
            print(f"Error initializing sensor controller: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def initialize_audio_optical_connections(self):
        """Auto-connect audio and optical sensors on startup"""
        try:
            # Connect audio sensors - connect only if enabled AND auto_connect is True
            audio_sensors = [s for s in self.sensors if getattr(s, 'interface_type', '') == 'AudioSensor']
            for sensor in audio_sensors:
                # Get auto_connect from config if available, default to True for backward compatibility
                auto_connect = True
                if hasattr(sensor, 'audio_config'):
                    auto_connect = sensor.audio_config.get('auto_connect', True)
                elif hasattr(sensor, 'auto_connect'):
                    auto_connect = sensor.auto_connect
                
                if getattr(sensor, 'enabled', True) and auto_connect:
                    try:
                        if self.connect_audio_sensor(sensor):
                            if hasattr(self.main_window, 'logger'):
                                self.main_window.logger.log(f"Auto-connected audio sensor: {sensor.name}", "INFO")
                            print(f"Auto-connected audio sensor: {sensor.name}")
                        else:
                            print(f"Failed to auto-connect audio sensor: {sensor.name}")
                    except Exception as e:
                        print(f"Error auto-connecting audio sensor {sensor.name}: {e}")
            
            # Connect optical sensors - connect only if enabled AND auto_connect is True
            optical_sensors = [s for s in self.sensors if getattr(s, 'interface_type', '') == 'OpticalSensor']
            for sensor in optical_sensors:
                # Get auto_connect from config if available, default to True for backward compatibility
                auto_connect = True
                if hasattr(sensor, 'optical_config'):
                    auto_connect = sensor.optical_config.get('auto_connect', True)
                elif hasattr(sensor, 'auto_connect'):
                    auto_connect = sensor.auto_connect
                
                if getattr(sensor, 'enabled', True) and auto_connect:
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
            
    def initialize_other_serial_connections(self, is_explicit_reconnect=False, port_override=None, baud_override=None):
        """Initialize connections to OtherSerial devices based on defined sequences."""
        print(f"DEBUG SensorController: initialize_other_serial_connections called (is_explicit_reconnect={is_explicit_reconnect}, port_override={port_override})")
        
        if not hasattr(self.main_window, 'data_collection_controller'):
            print("DEBUG SensorController: No data_collection_controller available")
            return
            
        data_controller = self.main_window.data_collection_controller
        
        # Get OtherSerial sensors from main sensor list
        other_sensors_main = [s for s in self.sensors if getattr(s, 'interface_type', '') in ('OtherSerial', 'Serial')]
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
        if len(other_sensors) == 0 and len(other_sequences) == 0 and not port_override:
            print(f"DEBUG SensorController: No OtherSerial sensors or sequences to initialize: sensors={len(other_sensors)}, sequences={len(other_sequences)}")
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
            
            # Apply overrides if port matches
            if port_override and str(port) == str(port_override):
                if baud_override: baud = baud_override

            poll_interval = seq.get('poll_interval', 1.0)
            if port:
                key = (port, baud, poll_interval)
                if key not in port_configs:
                    port_configs[key] = []
                port_configs[key].append(seq)
        
        # If port_override was provided but no sequences found, add a placeholder entry so we still try to connect
        if port_override and not any(str(p) == str(port_override) for (p, b, pi) in port_configs.keys()):
            port_configs[(port_override, baud_override or 9600, 1.0)] = []

        print(f"DEBUG SensorController: Port configurations for sequences: {len(port_configs)} unique port/baud/poll combinations")
        for (port, baud, poll_interval), seqs in port_configs.items():
            print(f"DEBUG SensorController: Port {port}, Baud {baud}, Poll {poll_interval}s: {len(seqs)} sequences - {[s.get('name', 'Unnamed') for s in seqs]}")
        
        # Now connect each unique port configuration
        for (port, baud, poll_interval), sequences in port_configs.items():
            try: # Outer try for this port configuration
                # Check if ANY sequence for this port has auto_connect enabled
                # or if this is an explicit reconnect
                should_connect = is_explicit_reconnect
                if not should_connect:
                    for seq in sequences:
                        if seq.get('auto_connect', False): # Default to False to respect user choice
                            should_connect = True
                            break
                
                if not should_connect:
                    print(f"DEBUG SensorController: Skipping auto-connect for port {port} (all sequences have auto_connect=False)")
                    continue

                print(f"DEBUG SensorController: Connecting to port {port} at baud {baud} with poll interval {poll_interval}s for {len(sequences)} sequences")
                if hasattr(self.main_window, 'logger'):
                    self.main_window.logger.log(f"Connecting Other Serial on {port} at {baud} baud", "INFO")

                # Build sequence objects for ALL configured sequences on this port group
                seq_objs = []
                for seq_cfg in sequences:
                    if isinstance(seq_cfg, dict):
                        actions = seq_cfg.get('actions') or seq_cfg.get('steps') or []
                        seq_name = seq_cfg.get('name', 'Unnamed')
                        seq_obj = data_controller.create_serial_sequence(seq_name, actions)
                        if seq_obj:
                            seq_objs.append(seq_obj)
                            print(f"DEBUG SensorController: Created SerialSequence object for '{seq_name}' with {len(getattr(seq_obj, 'steps', []))} steps")
                    else:
                        # Already a SerialSequence-like object
                        seq_objs.append(seq_cfg)
                        print(f"DEBUG SensorController: Using existing sequence object with name: {getattr(seq_cfg, 'name', 'Unnamed')}")

                # Now connect to the device with the sequence
                if seq_objs:
                    print(f"DEBUG SensorController: Connecting to port {port} with {len(seq_objs)} sequences: {[getattr(s, 'name', 'Unnamed') for s in seq_objs]}")
                    
                    # Use explicit reconnect if this is a user-initiated reconnect
                    if is_explicit_reconnect and hasattr(data_controller, 'explicit_reconnect_other_serial'):
                        # Use the new explicit reconnect method
                        success = data_controller.explicit_reconnect_other_serial(
                            port=port,
                            baud_rate=baud,
                            poll_interval=float(poll_interval),
                            sequences=seq_objs
                        )
                    else:
                        # Use the regular connect method
                        success = data_controller.connect_other_serial(
                            port=port,
                            baud_rate=baud,
                            poll_interval=float(poll_interval),
                            sequences=seq_objs
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
                sensor_port = str(sensor.port).strip().upper() if sensor.port is not None else ""
                sensor_name = str(getattr(sensor, 'name', '')).strip().upper()
                candidates = []
                if sensor_port and sensor_port != "ANY":
                    candidates.append(sensor_port)
                if sensor_name and sensor_name not in candidates:
                    candidates.append(sensor_name)
                if not candidates:
                    continue
                
                # Try to find a match in the data keys
                matched_key = None
                for target in candidates:
                    if target in data:
                        matched_key = target
                        break

                if not matched_key:
                    # Try flexible matching (e.g., AIN0 matching AIN0_EF_READ_A)
                    for data_key in data.keys():
                        dk_upper = data_key.upper()
                        for target in candidates:
                            if dk_upper == target or \
                               (dk_upper.startswith(target) and "_EF_READ_" in dk_upper) or \
                               (target.startswith(dk_upper) and "_EF_READ_" in target):
                                matched_key = data_key
                                break
                        if matched_key:
                            break
                
                if matched_key:
                    sensors_matched.append(sensor.name)
                    # Get the *already corrected* value from the input data dict
                    # and use set_value to update current_value, history, and last_update_time
                    sensor.set_value(data[matched_key])
                    updates_made += 1
                
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
                if getattr(sensor, 'interface_type', '') in ('OtherSerial', 'Serial') and sensor.name == key:
                    matched_sensor = sensor
                    break
                    
                # Try case-insensitive match
                if getattr(sensor, 'interface_type', '') in ('OtherSerial', 'Serial') and sensor.name.lower() == key.lower():
                    matched_sensor = sensor
                    break
                    
            if matched_sensor:
                sensors_matched.append(matched_sensor.name)
                try:
                    # value is already corrected by DataCollectionController before calling this method
                    value = data[key]
                    print(f"DEBUG SensorController: Matched sensor {matched_sensor.name}, already corrected value: {value}")
                    matched_sensor.set_value(value)
                    updates_made += 1
                except Exception as e:
                    print(f"DEBUG SensorController: Error updating sensor {matched_sensor.name}: {e}")
                    matched_sensor.set_value(None)
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
                    new_sensor.set_value(data[key])
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
            # self.update_sensor_values()
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
            
            # Update UI and graph dropdowns automatically
            self.update_sensor_table(update_dropdowns=True)
            
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

    def reinitialize_other_serial_connections(self, is_explicit_reconnect=False, port=None, baud_rate=None):
        """Reinitialize connections to OtherSerial devices, ensuring Arduino is disconnected first."""
        print(f"DEBUG SensorController: reinitialize_other_serial_connections called with is_explicit_reconnect={is_explicit_reconnect}, port={port}")
        
        # Log this action clearly
        if hasattr(self.main_window, 'logger'):
            self.main_window.logger.log(f"Reconnecting Other Serial sensors (Port: {port or 'all'})...", "INFO")
        
        # First, disconnect Arduino if connected to free up the COM port
        if hasattr(self.main_window, 'data_collection_controller'):
            data_controller = self.main_window.data_collection_controller
            if 'arduino' in data_controller.interfaces and data_controller.interfaces['arduino']['connected']:
                # If a specific port is requested, only disconnect Arduino if it's on that port
                arduino_port = data_controller.interfaces['arduino'].get('port')
                if port is None or str(arduino_port) == str(port):
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
        self.initialize_other_serial_connections(is_explicit_reconnect=is_explicit_reconnect, port_override=port, baud_override=baud_rate)
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
                
                # Clear the sensor value
                sensor.current_value = None
                self.update_sensor_values()
                
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
            # try:
            #     self.update_sensor_values()
            # except Exception as e:
            #     print(f"WARNING: Error updating sensor values: {e}")
            
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
                
                # Clear the sensor value
                sensor.current_value = None
                self.update_sensor_values()
                
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
            # try:
            #     self.update_sensor_values()
            # except Exception as e:
            #     print(f"WARNING: Error updating sensor values: {e}")
            
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