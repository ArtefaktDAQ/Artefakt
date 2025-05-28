from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox, QMessageBox, QTabWidget, QComboBox, QTextEdit, QWidget, QCheckBox, QColorDialog, QDialogButtonBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
import serial.tools.list_ports
import serial
import time

class AddEditSensorDialog(QDialog):
    """Dialog for adding or editing a virtual sensor"""
    def __init__(self, parent=None, sensor=None, sequences=None):
        super().__init__(parent)
        self.setWindowTitle("Add Sensor" if sensor is None else "Edit Sensor")
        self.resize(400, 300)
        self.sensor = sensor.copy() if sensor else {"name": "", "type": "", "mapping": "", "unit": "", "offset": 0.0, "color": "#4287f5", "show_in_graph": True}
        if not self.sensor.get("interface_type"):
            self.sensor["interface_type"] = "OtherSerial"
        self.sequences = sequences or []
        self.selected_sequence = None
        self.setup_ui()

    def setup_ui(self):
        layout = QFormLayout(self)
        self.name_edit = QLineEdit(self.sensor.get("name", ""))
        self.type_edit = QLineEdit(self.sensor.get("type", ""))
        layout.addRow("Name:", self.name_edit)
        layout.addRow("Type:", self.type_edit)

        # Unit
        self.unit_edit = QLineEdit(self.sensor.get("unit", ""))
        layout.addRow("Unit:", self.unit_edit)

        # Offset
        self.offset_edit = QLineEdit(str(self.sensor.get("offset", 0.0)))
        layout.addRow("Offset:", self.offset_edit)

        # Color with color picker button
        color_layout = QHBoxLayout()
        self.color_edit = QLineEdit(self.sensor.get("color", "#4287f5"))
        self.color_edit.setReadOnly(True)  # Make it read-only since we'll use the color picker
        color_layout.addWidget(self.color_edit)
        
        # Add color button with current color as background
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(30, 25)
        self.color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color_btn.setToolTip("Click to select a color")
        self.update_color_button()  # Set initial color
        self.color_btn.clicked.connect(self.choose_color)
        color_layout.addWidget(self.color_btn)
        
        layout.addRow("Color:", color_layout)

        # Show in graph
        self.show_in_graph_checkbox = QCheckBox()
        self.show_in_graph_checkbox.setChecked(self.sensor.get("show_in_graph", True))
        layout.addRow("Show in Graph:", self.show_in_graph_checkbox)

        # Sequence selection
        self.sequence_combo = QComboBox()
        self.sequence_combo.addItem("(None)", None)
        for seq in self.sequences:
            self.sequence_combo.addItem(seq.get("name", "Unnamed"), seq)
        layout.addRow("Sequence:", self.sequence_combo)
        self.sequence_combo.currentIndexChanged.connect(self.update_variable_combo)

        # Variable selection (published variables)
        self.variable_combo = QComboBox()
        layout.addRow("Published variable:", self.variable_combo)

        # If editing, preselect mapping
        mapping = self.sensor.get("mapping", "")
        if mapping and ":" in mapping:
            seq_name, var = mapping.split(":", 1)
            idx = self.sequence_combo.findText(seq_name)
            if idx >= 0:
                self.sequence_combo.setCurrentIndex(idx)
                self.update_variable_combo()
                var_idx = self.variable_combo.findText(var)
                if var_idx >= 0:
                    self.variable_combo.setCurrentIndex(var_idx)
        else:
            self.update_variable_combo()

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

    def update_color_button(self):
        """Update the color button's background to match the current color"""
        color = QColor(self.color_edit.text())
        if not color.isValid():
            color = QColor("#4287f5")  # Default blue if invalid
            self.color_edit.setText(color.name())
            
        # Set button background color
        style = f"background-color: {color.name()}; border: 1px solid #888888;"
        # If color is very light, add a border to make it visible
        if color.lightness() > 200:
            style += " border: 1px solid #888888;"
        self.color_btn.setStyleSheet(style)

    def choose_color(self):
        """Open a color picker dialog and update the color field"""
        current_color = QColor(self.color_edit.text())
        if not current_color.isValid():
            current_color = QColor("#4287f5")  # Default blue if invalid
            
        color = QColorDialog.getColor(current_color, self, "Choose Sensor Color")
        if color.isValid():
            self.color_edit.setText(color.name())
            self.update_color_button()

    def update_variable_combo(self):
        self.variable_combo.clear()
        seq = self.sequence_combo.currentData()
        if not seq:
            self.variable_combo.setEnabled(False)
            return
        published_vars = []
        for action in seq.get("actions", []):
            if action.get("type") == "publish" and action.get("target"):
                published_vars.append(action["target"])
        if published_vars:
            self.variable_combo.addItems(published_vars)
            self.variable_combo.setEnabled(True)
        else:
            self.variable_combo.addItem("(No published variables)")
            self.variable_combo.setEnabled(False)

    def get_sensor(self):
        mapping = ""
        seq = self.sequence_combo.currentData()
        var = self.variable_combo.currentText() if self.variable_combo.isEnabled() else ""
        if seq and var:
            mapping = f"{seq.get('name','')}:{var}"
        return {
            "name": self.name_edit.text().strip(),
            "type": self.type_edit.text().strip(),
            "mapping": mapping,
            "unit": self.unit_edit.text().strip(),
            "offset": float(self.offset_edit.text().strip() or 0.0),
            "color": self.color_edit.text().strip() or "#4287f5",
            "show_in_graph": self.show_in_graph_checkbox.isChecked(),
            "interface_type": "OtherSerial",
        }

class OtherSensorsDialog(QDialog):
    """Dialog for managing virtual/other sensors"""
    def __init__(self, parent=None, sensors=None, sequences=None):
        super().__init__(parent)
        self.setWindowTitle("Other Sensors Management")
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)
        
        # Store parent for access to controllers
        self._parent = parent
        
        # Initialize default values
        self.sensors = sensors or []
        self.sequences = sequences or []
        
        # Setup UI
        self.setup_ui()
        
        # Update tables with initial data
        self.update_sequences_table()
        # Auto-connect if configured
        QTimer.singleShot(300, self.handle_autoconnect)

    def setup_ui(self):
        """Set up the dialog UI"""
        # Main layout
        layout = QVBoxLayout(self)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # --- Setup Sequences Tab ---
        sequences_tab = QWidget()
        sequences_layout = QVBoxLayout(sequences_tab)
        
        # Add sequences table
        self.sequences_table = QTableWidget()
        self.sequences_table.setColumnCount(3)
        self.sequences_table.setHorizontalHeaderLabels(["Name", "Port", "Baud Rate"])
        self.sequences_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.sequences_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.sequences_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.sequences_table.verticalHeader().setVisible(False)
        self.sequences_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        sequences_layout.addWidget(self.sequences_table)
        
        # Add sequences buttons
        seq_btn_layout = QHBoxLayout()
        self.add_seq_btn = QPushButton("Add")
        self.edit_seq_btn = QPushButton("Edit")
        self.remove_seq_btn = QPushButton("Remove")
        
        self.add_seq_btn.clicked.connect(self.add_sequence)
        self.edit_seq_btn.clicked.connect(self.edit_sequence)
        self.remove_seq_btn.clicked.connect(self.remove_sequence)
        
        seq_btn_layout.addWidget(self.add_seq_btn)
        seq_btn_layout.addWidget(self.edit_seq_btn)
        seq_btn_layout.addWidget(self.remove_seq_btn)
        seq_btn_layout.addStretch()
        
        sequences_layout.addLayout(seq_btn_layout)
        
        # Add sequences tab to tab widget
        self.tab_widget.addTab(sequences_tab, "Sequences")
        
        # --- Setup Help Tab ---
        help_tab = QWidget()
        help_layout = QVBoxLayout(help_tab)
        
        # Add help instructions
        help_title = QLabel("How to Use Sequences")
        help_title.setStyleSheet("font-size: 14pt; font-weight: bold; margin-bottom: 10px;")
        help_layout.addWidget(help_title)
        
        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setHtml("""
        <h3>Working with Sequences</h3>
        <p>The Sequences tab allows you to define communication protocols for sensors connected via serial ports.</p>
        
        <h4>Creating a New Sequence:</h4>
        <ol>
            <li>Click the <b>Add</b> button to create a new sequence</li>
            <li>Enter a descriptive name for your sequence</li>
            <li>Select the COM port and baud rate for your device</li>
            <li>Add actions to define how to communicate with your device</li>
        </ol>
        
        <h4>Available Actions:</h4>
        <ul>
            <li><b>Send:</b> Send a command to the device</li>
            <li><b>Wait:</b> Wait for a specific time period</li>
            <li><b>Receive:</b> Receive data from the device</li>
            <li><b>Parse:</b> Extract numerical values from received data</li>
            <li><b>Publish:</b> Make parsed values available as sensor readings</li>
        </ul>
        
        <h4>Tips:</h4>
        <ul>
            <li>Use the <b>Test</b> button to validate your sequence before saving</li>
            <li>Create a sensor in the main window and link it to a published variable from your sequence</li>
            <li>Each sequence can publish multiple variables that can be used by different sensors</li>
        </ul>
        """)
        help_layout.addWidget(help_text)
        
        # Add help tab to tab widget
        self.tab_widget.addTab(help_tab, "Help")
        
        # --- Add Connect Button at Bottom ---
        bottom_layout = QHBoxLayout()
        
        # Add status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray; font-style: italic;")
        bottom_layout.addWidget(self.status_label)
        
        # Add autoconnect checkbox
        self.autoconnect_checkbox = QCheckBox("Auto-connect on startup")
        if hasattr(self.parent(), 'other_sensors_autoconnect'):
            self.autoconnect_checkbox.setChecked(self.parent().other_sensors_autoconnect)
        bottom_layout.addWidget(self.autoconnect_checkbox)
        
        # Add spacer
        bottom_layout.addStretch()
        
        # Add connect button
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setMinimumWidth(100)
        self.connect_btn.clicked.connect(self.on_connect_clicked)
        bottom_layout.addWidget(self.connect_btn)
        
        # Add cancel/ok buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        bottom_layout.addWidget(self.button_box)
        
        layout.addLayout(bottom_layout)
        
        # Set up the sequences table initial data
        self.update_sequences_table()
        
        # Check connection status for button state
        self.update_connect_button_state()
        
        # Handle autoconnect if needed
        QTimer.singleShot(500, self.handle_autoconnect)

    def update_sequences_table(self):
        self.sequences_table.setRowCount(len(self.sequences))
        for i, seq in enumerate(self.sequences):
            self.sequences_table.setItem(i, 0, QTableWidgetItem(seq.get("name", "")))
            self.sequences_table.setItem(i, 1, QTableWidgetItem(seq.get("port", "")))
            self.sequences_table.setItem(i, 2, QTableWidgetItem(str(seq.get("baud", ""))))

    def update_seq_button_states(self):
        selected = self.sequences_table.currentRow() >= 0
        self.edit_seq_btn.setEnabled(selected)
        self.remove_seq_btn.setEnabled(selected)

    def add_sequence(self):
        dialog = AddEditSequenceDialog(self)
        if dialog.exec():
            new_seq = dialog.get_sequence()
            if new_seq["name"]:
                self.sequences.append(new_seq)
                self.update_sequences_table()
                # Check for published variables
                published_vars = [a["target"] for a in new_seq.get("actions", []) if a.get("type") == "publish" and a.get("target")]
                if published_vars:
                    from PyQt6.QtWidgets import QMessageBox
                    resp = QMessageBox.question(self, "Create Sensor?", "This sequence has a published variable.\nDo you want to create a new sensor using this sequence now?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                    if resp == QMessageBox.StandardButton.Yes:
                        # Open AddEditSensorDialog with this sequence preselected
                        from .other_sensors_dialog import AddEditSensorDialog
                        dlg = AddEditSensorDialog(self, sequences=self.sequences)
                        idx = dlg.sequence_combo.findText(new_seq["name"])
                        if idx >= 0:
                            dlg.sequence_combo.setCurrentIndex(idx)
                        if dlg.exec():
                            sensor = dlg.get_sensor()
                            if sensor["name"]:
                                self.sensors.append(sensor)
                                # Also add to main sensor list in controller
                                if hasattr(self.parent(), 'sensor_controller'):
                                    from app.models.sensor_model import SensorModel
                                    sensor_model = SensorModel.from_dict(sensor)
                                    # Explicitly set interface_type to OtherSerial
                                    sensor_model.interface_type = 'OtherSerial'
                                    print(f"DEBUG OtherSensorsDialog: Adding sensor {sensor_model.name} with interface_type='OtherSerial'")
                                    self.parent().sensor_controller.add_sensor_to_list(sensor_model)
                                    self.parent().sensor_controller.update_sensor_table()
                                # Removed call to update_sensors_table() as it doesn't exist in this dialog

    def edit_sequence(self):
        row = self.sequences_table.currentRow()
        if row < 0 or row >= len(self.sequences):
            return
        dialog = AddEditSequenceDialog(self, sequence=self.sequences[row])
        if dialog.exec():
            updated_seq = dialog.get_sequence()
            if updated_seq["name"]:
                self.sequences[row] = updated_seq
                self.update_sequences_table()

    def remove_sequence(self):
        row = self.sequences_table.currentRow()
        if row < 0 or row >= len(self.sequences):
            return
        del self.sequences[row]
        self.update_sequences_table()

    def on_connect_clicked(self):
        """Handle connect button click"""
        try:
            # Check if we're currently connected based on button text
            is_currently_connected = self.connect_btn.text() == "Disconnect"
            action_text = "Disconnecting" if is_currently_connected else "Connecting"
            
            # Log that we're attempting to connect or disconnect
            print(f"DEBUG OtherSensorsDialog: {action_text} button clicked")
            if hasattr(self.parent(), 'logger'):
                self.parent().logger.log(f"{action_text} OtherSerial sensors from dialog...", "INFO")
            
            # Make sure we store the current configuration even if not accepted yet
            self.save_current_config_to_parent()
            
            # Disable the button to prevent multiple clicks
            self.connect_btn.setEnabled(False)
            print(f"DEBUG OtherSensorsDialog: Connect button disabled to prevent multiple clicks")
            
            # Now attempt to reinitialize or disconnect
            if hasattr(self.parent(), 'data_collection_controller'):
                if is_currently_connected:
                    # Disconnect all OtherSerial connections
                    self.parent().data_collection_controller.disconnect_other_serial_all()
                    print("DEBUG OtherSensorsDialog: Disconnected OtherSerial sensors")
                    
                    # Clear values for OtherSerial sensors to show "--" in the UI
                    if hasattr(self.parent(), 'sensor_controller'):
                        for sensor in self.parent().sensor_controller.sensors:
                            if getattr(sensor, 'interface_type', '') == 'OtherSerial':
                                # Set current_value to None so it displays as "--"
                                sensor.current_value = None
                        # Force update of sensor values in UI
                        self.parent().sensor_controller.update_sensor_values()
                        print("DEBUG OtherSensorsDialog: Reset all OtherSerial sensor values to display '--'")
                    
                    # Update connection status in data_collection_controller - this is important!
                    if hasattr(self.parent().data_collection_controller, 'interfaces') and 'other_serial' in self.parent().data_collection_controller.interfaces:
                        self.parent().data_collection_controller.interfaces['other_serial']['connected'] = False
                        print("DEBUG OtherSensorsDialog: Explicitly set connection status to FALSE in data_collection_controller")
                    
                    # Update UI to reflect disconnected state
                    if hasattr(self.parent(), 'update_other_connected_status'):
                        self.parent().update_other_connected_status(False)
                        print("DEBUG OtherSensorsDialog: Updated UI to show disconnected status")
                    elif hasattr(self.parent(), 'update_device_connection_status_ui'):
                        self.parent().update_device_connection_status_ui('other', False)
                        print("DEBUG OtherSensorsDialog: Updated device connection status UI to disconnected")
                    
                    # Re-enable button after disconnection
                    self.connect_btn.setEnabled(True)
                    self.connect_btn.setText("Connect")
                    print("DEBUG OtherSensorsDialog: Connect button re-enabled and text set to 'Connect'")
                else:
                    # Connect - use sensor controller if available
                    connection_success = False
                    if hasattr(self.parent(), 'sensor_controller'):
                        if hasattr(self.parent().sensor_controller, 'reinitialize_other_serial_connections'):
                            # Add a timeout for the connection attempt
                            from threading import Timer
                            def timeout_handler():
                                print("DEBUG OtherSensorsDialog: Connection attempt timed out after 10 seconds")
                                if hasattr(self.parent(), 'logger'):
                                    self.parent().logger.log("Connection attempt timed out after 10 seconds", "ERROR")
                                self.connect_btn.setEnabled(True)
                                if hasattr(self.parent(), 'update_other_connected_status'):
                                    self.parent().update_other_connected_status(False)
                                elif hasattr(self.parent(), 'update_device_connection_status_ui'):
                                    self.parent().update_device_connection_status_ui('other', False)
                            
                            timeout_timer = Timer(10.0, timeout_handler)
                            timeout_timer.start()
                            
                            # This is a user-initiated connect, so it should override the manual disconnect flag
                            connection_success = self.parent().sensor_controller.reinitialize_other_serial_connections(is_explicit_reconnect=True)
                            timeout_timer.cancel()  # Cancel the timeout if connection attempt completes
                            print(f"DEBUG OtherSensorsDialog: Attempted to reinitialize OtherSerial connections, success={connection_success}")
                        else:
                            # Fallback to direct connection method
                            if len(self.sequences) > 0:
                                primary_sequence = self.sequences[0]
                                port = primary_sequence.get('port', '')
                                baud = primary_sequence.get('baud', 9600)
                                poll_interval = primary_sequence.get('poll_interval', 1.0)
                                steps = primary_sequence.get('actions', [])
                                
                                if port:
                                    # Create sequence object
                                    if hasattr(self.parent().data_collection_controller, 'create_serial_sequence'):
                                        sequence_obj = self.parent().data_collection_controller.create_serial_sequence(
                                            primary_sequence.get('name', 'Unnamed'), steps)
                                        
                                        # Use explicit_reconnect_other_serial if available
                                        if hasattr(self.parent().data_collection_controller, 'explicit_reconnect_other_serial'):
                                            connection_success = self.parent().data_collection_controller.explicit_reconnect_other_serial(
                                                port=port,
                                                baud_rate=baud,
                                                poll_interval=float(poll_interval),
                                                sequence=sequence_obj
                                            )
                                        else:
                                            # Fall back to regular connect
                                            connection_success = self.parent().data_collection_controller.connect_other_serial(
                                                port=port,
                                                baud_rate=baud,
                                                poll_interval=float(poll_interval),
                                                sequence=sequence_obj
                                            )
                                        
                                        print(f"DEBUG OtherSensorsDialog: Direct connection attempt result: {connection_success}")
                                    else:
                                        print("DEBUG OtherSensorsDialog: No create_serial_sequence method available")
                                else:
                                    print("DEBUG OtherSensorsDialog: No port specified in primary sequence")
                            else:
                                print("DEBUG OtherSensorsDialog: No sequences available for connection")
                    else:
                        print("DEBUG OtherSensorsDialog: No sensor_controller available")
                    
                    # Update connection status in data_collection_controller - this is important!
                    if hasattr(self.parent().data_collection_controller, 'interfaces') and 'other_serial' in self.parent().data_collection_controller.interfaces:
                        self.parent().data_collection_controller.interfaces['other_serial']['connected'] = connection_success
                        print(f"DEBUG OtherSensorsDialog: Explicitly set connection status to {connection_success} in data_collection_controller")
                    
                    # Update UI to reflect connection status
                    if connection_success:
                        if hasattr(self.parent(), 'update_other_connected_status'):
                            self.parent().update_other_connected_status(True)
                            print("DEBUG OtherSensorsDialog: Updated UI to show connected status")
                        elif hasattr(self.parent(), 'update_device_connection_status_ui'):
                            self.parent().update_device_connection_status_ui('other', True)
                            print("DEBUG OtherSensorsDialog: Updated device connection status UI to connected")
                        self.connect_btn.setText("Disconnect")
                        self.connect_btn.setStyleSheet("background-color: #ff5555;")  # Red
                    else:
                        if hasattr(self.parent(), 'update_other_connected_status'):
                            self.parent().update_other_connected_status(False)
                            print("DEBUG OtherSensorsDialog: Updated UI to show failed connection status")
                        elif hasattr(self.parent(), 'update_device_connection_status_ui'):
                            self.parent().update_device_connection_status_ui('other', False)
                            print("DEBUG OtherSensorsDialog: Updated device connection status UI to failed connection")
                        if hasattr(self.parent(), 'logger'):
                            self.parent().logger.log("Failed to connect to OtherSerial sensors", "ERROR")
                    
                    # Re-enable button after connection attempt
                    self.connect_btn.setEnabled(True)
                    print("DEBUG OtherSensorsDialog: Connect button re-enabled after connection attempt")
            else:
                print("DEBUG OtherSensorsDialog: No data_collection_controller available, cannot connect/disconnect")
                self.connect_btn.setEnabled(True)
                print("DEBUG OtherSensorsDialog: Connect button re-enabled due to no controller")
        except Exception as e:
            print(f"DEBUG OtherSensorsDialog: Error in on_connect_clicked: {e}")
            if hasattr(self.parent(), 'logger'):
                self.parent().logger.log(f"Error {action_text.lower()} OtherSerial sensors: {str(e)}", "ERROR")
            self.connect_btn.setEnabled(True)
            print("DEBUG OtherSensorsDialog: Connect button re-enabled after error")

    def update_connect_button_state(self):
        """Update the connect button state based on connection status"""
        is_connected = False
        
        # Check connection status if possible
        if hasattr(self.parent(), 'data_collection_controller'):
            data_controller = self.parent().data_collection_controller
            if hasattr(data_controller, 'interfaces') and 'other_serial' in data_controller.interfaces:
                other_serial_interfaces = data_controller.interfaces['other_serial']
                
                # Based on log analysis, other_serial_interfaces is a dictionary with a 'connected' key directly
                if isinstance(other_serial_interfaces, dict) and 'connected' in other_serial_interfaces:
                    is_connected = other_serial_interfaces['connected']
                    print(f"DEBUG OtherSensorsDialog: Found connection status in other_serial_interfaces: {is_connected}")
                # For safety, also handle the case where it might be a different structure
                elif isinstance(other_serial_interfaces, dict):
                    # Safely iterate through values checking for dictionaries with a 'connected' key
                    for value in other_serial_interfaces.values():
                        if isinstance(value, dict) and value.get('connected', False):
                            is_connected = True
                            break
        
        # Update button text and style
        if is_connected:
            self.connect_btn.setText("Disconnect")
            self.connect_btn.setStyleSheet("color: #FF4136; font-weight: bold;")  # Red
            if self.status_label.text() == "":
                self.status_label.setText("Connected")
                self.status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.connect_btn.setText("Connect")
            self.connect_btn.setStyleSheet("color: #2ECC40; font-weight: bold;")  # Green
            if self.status_label.text() == "":
                self.status_label.setText("Not connected")
                self.status_label.setStyleSheet("color: gray; font-style: italic;")
                
        # Ensure button is enabled
        self.connect_btn.setEnabled(True)

    def handle_autoconnect(self):
        """Handle auto-connect if the checkbox is checked"""
        if self.autoconnect_checkbox.isChecked():
            # Check if the user has manually disconnected
            is_connected = False
            if hasattr(self.parent(), 'data_collection_controller'):
                data_controller = self.parent().data_collection_controller
                if hasattr(data_controller, 'interfaces') and 'other_serial' in data_controller.interfaces:
                    other_serial_interfaces = data_controller.interfaces['other_serial']
                    if isinstance(other_serial_interfaces, dict) and 'connected' in other_serial_interfaces:
                        is_connected = other_serial_interfaces['connected']
                    elif isinstance(other_serial_interfaces, dict):
                        for value in other_serial_interfaces.values():
                            if isinstance(value, dict) and value.get('connected', False):
                                is_connected = True
                                break
            if not is_connected:
                print("DEBUG OtherSensorsDialog: Auto-connect is enabled, but respecting manual disconnection. Not reconnecting.")
                if hasattr(self.parent(), 'logger'):
                    self.parent().logger.log("Auto-connect enabled but respecting manual disconnection. Not reconnecting.", "INFO")
                return
            print("DEBUG OtherSensorsDialog: Auto-connect is enabled, connecting...")
            if hasattr(self.parent(), 'logger'):
                self.parent().logger.log("Auto-connecting Other Serial sensors...", "INFO")
            self.on_connect_clicked()

    def accept(self):
        """Override the accept method to ensure connection status is properly updated in the main window"""
        # Get the current connection status from the button text
        is_connected = self.connect_btn.text() == "Disconnect"
        
        # Store the current sensors and sequences in main_window
        self.parent().other_sensors = self.sensors
        self.parent().other_sequences = self.sequences
        
        # Save sequences and autoconnect setting
        if hasattr(self.parent(), 'save_virtual_sensors'):
            self.parent().save_virtual_sensors()
        
        # Update autoconnect setting in main window
        self.parent().other_sensors_autoconnect = self.autoconnect_checkbox.isChecked()
        
        # Check the actual connection status from the data_collection_controller
        actual_connected = False
        if hasattr(self.parent(), 'data_collection_controller'):
            data_controller = self.parent().data_collection_controller
            if hasattr(data_controller, 'interfaces') and 'other_serial' in data_controller.interfaces:
                if isinstance(data_controller.interfaces['other_serial'], dict) and 'connected' in data_controller.interfaces['other_serial']:
                    actual_connected = data_controller.interfaces['other_serial']['connected']
                    print(f"DEBUG OtherSensorsDialog: accept - actual connection status from data_collection_controller: {actual_connected}")
        
        # Use the actual connection status, or fallback to button status
        is_connected = actual_connected or is_connected
        print(f"DEBUG OtherSensorsDialog: accept - using connection status: {is_connected}")
        
        # If we're in a disconnected state when closing, ensure values show as "--"
        if not is_connected:
            # Clear values for OtherSerial sensors to show "--" in the UI
            if hasattr(self.parent(), 'sensor_controller'):
                for sensor in self.parent().sensor_controller.sensors:
                    if getattr(sensor, 'interface_type', '') == 'OtherSerial':
                        # Set current_value to None so it displays as "--"
                        sensor.current_value = None
                
                # Force update of sensor values in UI
                self.parent().sensor_controller.update_sensor_values()
                print("DEBUG OtherSensorsDialog: Reset all OtherSerial sensor values to display '--' on dialog close")
            
        # Update the connection status in the main window UI - try multiple methods for robustness
        if hasattr(self.parent(), 'update_device_connection_status_ui'):
            print(f"DEBUG OtherSensorsDialog: Calling update_device_connection_status_ui('other', {is_connected})")
            self.parent().update_device_connection_status_ui('other', is_connected)
        elif hasattr(self.parent(), 'update_other_connected_status'):
            print(f"DEBUG OtherSensorsDialog: Calling update_other_connected_status({is_connected})")
            self.parent().update_other_connected_status(is_connected)
        
        # Only update connection status in data_collection_controller if it differs from the current status
        if hasattr(self.parent(), 'data_collection_controller'):
            if hasattr(self.parent().data_collection_controller, 'interfaces') and 'other_serial' in self.parent().data_collection_controller.interfaces:
                current_status = self.parent().data_collection_controller.interfaces['other_serial'].get('connected', False)
                if current_status != is_connected:
                    self.parent().data_collection_controller.interfaces['other_serial']['connected'] = is_connected
                    print(f"DEBUG OtherSensorsDialog: Updated connection status in data_collection_controller from {current_status} to {is_connected}")
                else:
                    print(f"DEBUG OtherSensorsDialog: Connection status in data_collection_controller already matches: {is_connected}")
                
            # Emit signal to update UI
            if hasattr(self.parent().data_collection_controller, 'interface_status_signal'):
                self.parent().data_collection_controller.interface_status_signal.emit('other', is_connected)
                print(f"DEBUG OtherSensorsDialog: Emitted interface_status_signal('other', {is_connected})")
        
        # Continue with standard dialog accept
        super().accept()

    def save_current_config_to_parent(self):
        # Implement the logic to save the current configuration to the parent
        # This method should be implemented based on your specific requirements
        pass

# Dialog für Sequenz hinzufügen/bearbeiten
class AddEditActionDialog(QDialog):
    def __init__(self, parent=None, action=None, variables=None):
        super().__init__(parent)
        self.setWindowTitle("Add Action" if action is None else "Edit Action")
        self.resize(400, 220)
        self.action = action.copy() if action else {"type": "send", "command": "", "ms": 200, "source": "", "target": "", "parse_mode": "after", "start": "", "end": ""}
        self.variables = variables or []
        self.setup_ui()

    def setup_ui(self):
        layout = QFormLayout(self)
        self.type_combo = QComboBox()
        self.type_combo.addItems(["send", "wait", "read", "parse", "publish"])
        self.type_combo.setCurrentText(self.action.get("type", "send"))
        layout.addRow("Type:", self.type_combo)

        self.command_edit = QLineEdit(self.action.get("command", ""))
        self.ms_edit = QLineEdit(str(self.action.get("ms", 200)))
        self.source_edit = QLineEdit(self.action.get("source", ""))
        self.target_edit = QLineEdit(self.action.get("target", ""))
        self.target_edit.setToolTip("The variable where the result will be stored. You can use this variable in later steps.")
        self.source_edit.setToolTip("The variable to parse/process (e.g. from a previous read).")

        # For publish: dropdown of known variables
        self.publish_var_combo = QComboBox()
        self.publish_var_combo.addItems(self.variables)
        if self.action.get("target") and self.action["target"] in self.variables:
            self.publish_var_combo.setCurrentText(self.action["target"])
        self.publish_var_combo.setToolTip("Select the variable to publish as the sensor value.")

        # Parse options
        self.parse_mode_combo = QComboBox()
        self.parse_mode_combo.addItems([
            "Everything after text",
            "Value between two texts",
            "Everything before text",
            "Entire response"
        ])
        parse_mode_map = {
            "after": 0,
            "between": 1,
            "before": 2,
            "entire": 3
        }
        self.parse_mode_combo.setCurrentIndex(parse_mode_map.get(self.action.get("parse_mode", "after"), 0))
        self.parse_start = QLineEdit(self.action.get("start", ""))
        self.parse_end = QLineEdit(self.action.get("end", ""))

        layout.addRow("Command (send):", self.command_edit)
        layout.addRow("Wait time ms (wait):", self.ms_edit)
        # For read: only show target
        self.read_target_label = QLabel("Store result in variable:")
        self.read_target_label.setToolTip("The value read from the device will be stored in this variable. You can use this variable in later steps (e.g. for parsing).")
        layout.addRow(self.read_target_label, self.target_edit)
        # For parse: show both source and target
        self.parse_source_label = QLabel("Source variable (parse):")
        self.parse_source_label.setToolTip("The variable to parse/process (e.g. from a previous read).")
        self.parse_target_label = QLabel("Target variable (parse):")
        self.parse_target_label.setToolTip("The variable where the parsed value will be stored.")
        layout.addRow(self.parse_source_label, self.source_edit)
        layout.addRow(self.parse_target_label, self.target_edit)
        layout.addRow("Parse mode:", self.parse_mode_combo)
        layout.addRow("Start text:", self.parse_start)
        layout.addRow("End text:", self.parse_end)
        layout.addRow("Publish variable:", self.publish_var_combo)

        self.type_combo.currentTextChanged.connect(self.update_fields)
        self.parse_mode_combo.currentIndexChanged.connect(self.update_parse_fields)
        self.update_fields(self.type_combo.currentText())
        self.update_parse_fields(self.parse_mode_combo.currentIndex())

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

    def update_fields(self, typ):
        self.command_edit.setVisible(typ == "send")
        self.ms_edit.setVisible(typ == "wait")
        # For read: only show target
        self.read_target_label.setVisible(typ == "read")
        self.target_edit.setVisible(typ == "read" or typ == "parse")
        # For parse: show both source and target
        self.parse_source_label.setVisible(typ == "parse")
        self.source_edit.setVisible(typ == "parse")
        self.parse_target_label.setVisible(typ == "parse")
        self.parse_mode_combo.setVisible(typ == "parse")
        self.parse_start.setVisible(typ == "parse")
        self.parse_end.setVisible(typ == "parse")
        self.publish_var_combo.setVisible(typ == "publish")
        self.update_parse_fields(self.parse_mode_combo.currentIndex())

    def update_parse_fields(self, idx):
        if self.type_combo.currentText() != "parse":
            self.parse_start.setVisible(False)
            self.parse_end.setVisible(False)
            return
        if idx == 0:  # after
            self.parse_start.setVisible(True)
            self.parse_end.setVisible(False)
            self.parse_start.setPlaceholderText("Text to search after")
        elif idx == 1:  # between
            self.parse_start.setVisible(True)
            self.parse_end.setVisible(True)
            self.parse_start.setPlaceholderText("Start text")
            self.parse_end.setPlaceholderText("End text")
        elif idx == 2:  # before
            self.parse_start.setVisible(False)
            self.parse_end.setVisible(True)
            self.parse_end.setPlaceholderText("Text to search before")
        elif idx == 3:  # entire
            self.parse_start.setVisible(False)
            self.parse_end.setVisible(False)

    def get_action(self):
        typ = self.type_combo.currentText()
        action = {"type": typ}
        if typ == "send":
            action["command"] = self.command_edit.text()
        elif typ == "wait":
            action["ms"] = int(self.ms_edit.text().strip() or 200)
        elif typ == "read":
            action["source"] = self.source_edit.text().strip()
            action["target"] = self.target_edit.text().strip()
        elif typ == "parse":
            action["source"] = self.source_edit.text().strip()
            action["target"] = self.target_edit.text().strip()
            idx = self.parse_mode_combo.currentIndex()
            if idx == 0:
                action["parse_mode"] = "after"
                action["start"] = self.parse_start.text()
            elif idx == 1:
                action["parse_mode"] = "between"
                action["start"] = self.parse_start.text()
                action["end"] = self.parse_end.text()
            elif idx == 2:
                action["parse_mode"] = "before"
                action["end"] = self.parse_end.text()
            elif idx == 3:
                action["parse_mode"] = "entire"
        elif typ == "publish":
            action["source_var"] = "value"  # Default source variable
            action["target"] = self.publish_var_combo.currentText()
        return action

class AddEditSequenceDialog(QDialog):
    def __init__(self, parent=None, sequence=None):
        super().__init__(parent)
        self.setWindowTitle("Add Sequence" if sequence is None else "Edit Sequence")
        self.resize(500, 440)
        self.sequence = sequence.copy() if sequence else {"name": "", "port": "", "baud": 9600, "actions": [], "poll_interval": 1.0}
        if isinstance(self.sequence.get("actions"), str):
            import json
            try:
                self.sequence["actions"] = json.loads(self.sequence["actions"])
            except Exception:
                self.sequence["actions"] = []
        self.setup_ui()
        self.update_actions_table()

    def setup_ui(self):
        layout = QFormLayout(self)
        self.name_edit = QLineEdit(self.sequence.get("name", ""))
        self.port_combo = QComboBox()
        self.ports = self.get_serial_ports()
        for port, desc in self.ports:
            label = f"{desc} ({port})" if desc else port
            self.port_combo.addItem(label, port)
        if self.sequence.get("port"):
            idx = self.port_combo.findData(self.sequence["port"])
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)
        self.baud_edit = QLineEdit(str(self.sequence.get("baud", 9600)))
        layout.addRow("Name:", self.name_edit)
        layout.addRow("COM Port:", self.port_combo)
        layout.addRow("Baudrate:", self.baud_edit)
        
        # Add poll interval field
        self.poll_interval_edit = QLineEdit(str(self.sequence.get("poll_interval", 1.0)))
        self.poll_interval_edit.setToolTip("How often to poll the sensor (in seconds). Lower values update more frequently but use more resources.")
        layout.addRow("Poll Interval (seconds):", self.poll_interval_edit)

        self.actions_table = QTableWidget()
        self.actions_table.setColumnCount(2)
        self.actions_table.setHorizontalHeaderLabels(["Type", "Details"])
        self.actions_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.actions_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.actions_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.actions_table.verticalHeader().setVisible(False)
        self.actions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addRow(QLabel("Actions:"), self.actions_table)

        btn_layout = QHBoxLayout()
        self.add_action_btn = QPushButton("Add")
        self.edit_action_btn = QPushButton("Edit")
        self.remove_action_btn = QPushButton("Remove")
        self.up_action_btn = QPushButton("Up")
        self.down_action_btn = QPushButton("Down")
        btn_layout.addWidget(self.add_action_btn)
        btn_layout.addWidget(self.edit_action_btn)
        btn_layout.addWidget(self.remove_action_btn)
        btn_layout.addWidget(self.up_action_btn)
        btn_layout.addWidget(self.down_action_btn)
        layout.addRow(btn_layout)
        self.edit_action_btn.setEnabled(False)
        self.remove_action_btn.setEnabled(False)
        self.up_action_btn.setEnabled(False)
        self.down_action_btn.setEnabled(False)
        self.actions_table.itemSelectionChanged.connect(self.update_action_buttons)
        self.add_action_btn.clicked.connect(self.add_action)
        self.edit_action_btn.clicked.connect(self.edit_action)
        self.remove_action_btn.clicked.connect(self.remove_action)
        self.up_action_btn.clicked.connect(self.move_action_up)
        self.down_action_btn.clicked.connect(self.move_action_down)

        # Test mode placeholder
        test_btn_layout = QHBoxLayout()
        self.test_btn = QPushButton("Test Sequence")
        self.test_btn.clicked.connect(self.open_test_dialog)
        test_btn_layout.addWidget(self.test_btn)
        layout.addRow(test_btn_layout)

        ok_cancel_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        ok_cancel_layout.addWidget(ok_btn)
        ok_cancel_layout.addWidget(cancel_btn)
        layout.addRow(ok_cancel_layout)

    def get_serial_ports(self):
        ports = []
        try:
            for p in serial.tools.list_ports.comports():
                ports.append((p.device, p.description))
        except Exception:
            pass
        return ports

    def update_actions_table(self):
        actions = self.sequence.get("actions", [])
        self.actions_table.setRowCount(len(actions))
        for i, action in enumerate(actions):
            typ = action.get("type", "")
            if typ == "send":
                details = f'Command: {action.get("command", "")}'
            elif typ == "wait":
                details = f'Wait: {action.get("ms", "")} ms'
            elif typ == "read":
                details = f'Read {action.get("source", "")} -> {action.get("target", "")}'
            elif typ == "parse":
                mode = action.get("parse_mode", "after")
                if mode == "after":
                    details = f'Parse {action.get("source", "")} after "{action.get("start", "")}" -> {action.get("target", "")}'
                elif mode == "between":
                    details = f'Parse {action.get("source", "")} between "{action.get("start", "")}" and "{action.get("end", "")}" -> {action.get("target", "")}'
                elif mode == "before":
                    details = f'Parse {action.get("source", "")} before "{action.get("end", "")}" -> {action.get("target", "")}'
                elif mode == "entire":
                    details = f'Parse entire {action.get("source", "")} -> {action.get("target", "")}'
                else:
                    details = "Parse"
            elif typ == "publish":
                details = f'Publish variable: {action.get("target", "")}'
            else:
                details = ""
            self.actions_table.setItem(i, 0, QTableWidgetItem(typ))
            self.actions_table.setItem(i, 1, QTableWidgetItem(details))
        self.update_action_buttons()

    def update_action_buttons(self):
        row = self.actions_table.currentRow()
        count = self.actions_table.rowCount()
        self.edit_action_btn.setEnabled(row >= 0)
        self.remove_action_btn.setEnabled(row >= 0)
        self.up_action_btn.setEnabled(row > 0)
        self.down_action_btn.setEnabled(0 <= row < count - 1)

    def get_known_variables(self):
        # Collect all target variables from previous actions
        vars = set()
        for a in self.sequence.get("actions", []):
            if a.get("type") in ("read", "parse") and a.get("target"):
                vars.add(a["target"])
        return sorted(vars)

    def add_action(self):
        known_vars = self.get_known_variables()
        dialog = AddEditActionDialog(self, variables=known_vars)
        if dialog.exec():
            action = dialog.get_action()
            self.sequence["actions"].append(action)
            self.update_actions_table()

    def edit_action(self):
        row = self.actions_table.currentRow()
        if row < 0 or row >= len(self.sequence["actions"]):
            return
        known_vars = self.get_known_variables()
        dialog = AddEditActionDialog(self, action=self.sequence["actions"][row], variables=known_vars)
        if dialog.exec():
            self.sequence["actions"][row] = dialog.get_action()
            self.update_actions_table()

    def remove_action(self):
        row = self.actions_table.currentRow()
        if row < 0 or row >= len(self.sequence["actions"]):
            return
        del self.sequence["actions"][row]
        self.update_actions_table()

    def move_action_up(self):
        row = self.actions_table.currentRow()
        if row > 0:
            actions = self.sequence["actions"]
            actions[row-1], actions[row] = actions[row], actions[row-1]
            self.update_actions_table()
            self.actions_table.selectRow(row-1)

    def move_action_down(self):
        row = self.actions_table.currentRow()
        actions = self.sequence["actions"]
        if 0 <= row < len(actions)-1:
            actions[row], actions[row+1] = actions[row+1], actions[row]
            self.update_actions_table()
            self.actions_table.selectRow(row+1)

    def get_sequence(self):
        return {
            "name": self.name_edit.text().strip(),
            "port": self.port_combo.currentData(),
            "baud": int(self.baud_edit.text().strip() or 9600),
            "poll_interval": float(self.poll_interval_edit.text().strip() or 1.0),
            "actions": self.sequence["actions"],
        }

    def open_test_dialog(self):
        dlg = TestSequenceDialog(self, self.get_sequence())
        dlg.exec()

class TestSequenceDialog(QDialog):
    def __init__(self, parent, sequence):
        super().__init__(parent)
        self.setWindowTitle("Test Sequence")
        self.resize(600, 500)
        self.sequence = sequence
        self.actions = sequence.get("actions", [])
        self.port = sequence.get("port", "")
        self.baud = sequence.get("baud", 9600)
        self.current_step = 0
        self.variables = {}
        self.serial = None
        self.setup_ui()
        self.open_port()
        self.update_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.steps_table = QTableWidget()
        self.steps_table.setColumnCount(2)
        self.steps_table.setHorizontalHeaderLabels(["Type", "Details"])
        self.steps_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.steps_table.setRowCount(len(self.actions))
        for i, action in enumerate(self.actions):
            self.steps_table.setItem(i, 0, QTableWidgetItem(action.get("type", "")))
            self.steps_table.setItem(i, 1, QTableWidgetItem(str(action)))
        self.steps_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.steps_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.steps_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.steps_table.verticalHeader().setVisible(False)
        layout.addWidget(QLabel(f"Port: {self.port}  Baudrate: {self.baud}"))
        layout.addWidget(self.steps_table)

        self.vars_label = QLabel("Variables:")
        layout.addWidget(self.vars_label)
        self.vars_text = QTextEdit()
        self.vars_text.setReadOnly(True)
        layout.addWidget(self.vars_text)

        self.log_label = QLabel("Log:")
        layout.addWidget(self.log_label)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        btn_layout = QHBoxLayout()
        self.next_btn = QPushButton("Next Step")
        self.repeat_btn = QPushButton("Repeat Step")
        self.stop_btn = QPushButton("Stop")
        btn_layout.addWidget(self.next_btn)
        btn_layout.addWidget(self.repeat_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)
        self.next_btn.clicked.connect(self.next_step)
        self.repeat_btn.clicked.connect(self.repeat_step)
        self.stop_btn.clicked.connect(self.close)

    def open_port(self):
        try:
            self.serial = serial.Serial(self.port, self.baud, timeout=2)
            self.log("Opened port successfully.")
        except Exception as e:
            self.serial = None
            self.log(f"Error opening port: {e}")
            self.next_btn.setEnabled(False)
            self.repeat_btn.setEnabled(False)

    def closeEvent(self, event):
        if self.serial and self.serial.is_open:
            try:
                self.serial.close()
            except Exception:
                pass
        event.accept()

    def log(self, msg):
        self.log_text.append(msg)

    def update_vars(self):
        lines = [f"{k}: {v}" for k, v in self.variables.items()]
        self.vars_text.setPlainText("\n".join(lines))

    def update_ui(self):
        self.steps_table.selectRow(self.current_step)
        self.update_vars()

    def next_step(self):
        if self.current_step >= len(self.actions):
            self.log("Sequence finished.")
            self.next_btn.setEnabled(False)
            return
        action = self.actions[self.current_step]
        self.execute_action(action)
        self.current_step += 1
        self.update_ui()

    def repeat_step(self):
        if self.current_step >= len(self.actions):
            return
        action = self.actions[self.current_step]
        self.execute_action(action)
        self.update_ui()

    def execute_action(self, action):
        typ = action.get("type")
        try:
            if typ == "send":
                cmd = action.get("command", "").encode("utf-8")
                if self.serial and self.serial.is_open:
                    self.serial.write(cmd + b"\n")
                    self.log(f"Sent: {cmd}")
                else:
                    self.log("Port not open.")
            elif typ == "wait":
                ms = int(action.get("ms", 200))
                self.log(f"Wait {ms} ms...")
                QTimer.singleShot(ms, lambda: None)
                time.sleep(ms/1000)
            elif typ == "read":
                source = action.get("source", "")
                target = action.get("target", "result")
                if self.serial and self.serial.is_open:
                    line = self.serial.readline().decode(errors="replace")
                    self.variables[target] = line
                    self.log(f"Read into {target}: {line}")
                else:
                    self.log("Port not open.")
            elif typ == "parse":
                source = action.get("source", "")
                target = action.get("target", "parsed")
                val = self.variables.get(source, "")
                mode = action.get("parse_mode", "after")
                start = action.get("start", "")
                end = action.get("end", "")
                result = ""
                if mode == "after":
                    idx = val.find(start)
                    result = val[idx+len(start):] if idx != -1 else ""
                elif mode == "between":
                    idx1 = val.find(start)
                    idx2 = val.find(end, idx1+len(start)) if idx1 != -1 else -1
                    result = val[idx1+len(start):idx2] if idx1 != -1 and idx2 != -1 else ""
                elif mode == "before":
                    idx = val.find(end)
                    result = val[:idx] if idx != -1 else ""
                elif mode == "entire":
                    result = val
                self.variables[target] = result
                self.log(f"Parsed {source} -> {target}: {result}")
            elif typ == "publish":
                target = action.get("target", "")
                value = self.variables.get(target, "")
                self.log(f"Published value: {value}")
            else:
                self.log(f"Unknown action type: {typ}")
        except Exception as e:
            self.log(f"Error in step: {e}") 