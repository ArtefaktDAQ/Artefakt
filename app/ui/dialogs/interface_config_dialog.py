from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, 
    QLabel, QLineEdit, QPushButton, QGroupBox, 
    QMessageBox, QComboBox, QCheckBox, QWidget,
    QDialogButtonBox, QDoubleSpinBox, QTabWidget, QTextEdit, QInputDialog, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QSize
from PyQt6.QtGui import QDesktopServices
import os
from app.ui.theme import DialogStyles, ButtonStyles, ConnectionStyles, COLORS, GroupBoxStyles

class InterfaceConfigDialog(QDialog):
    """
    A harmonized dialog for configuring any hardware interface (built-in or plugin).
    Provides standard controls for connection, auto-connect, and enabled state,
    plus dynamic fields based on the interface's CONFIG_SCHEMA.
    """
    connection_status_changed = pyqtSignal(str, bool)
    
    def __init__(self, parent=None, interface_class=None, interface_instance=None, config=None):
        super().__init__(parent)
        self.interface_class = interface_class
        self.interface_instance = interface_instance
        self.config = config or {}
        
        if interface_class:
            self.display_name = getattr(interface_class, "DISPLAY_NAME", interface_class.__name__)
        elif interface_instance:
            self.display_name = getattr(interface_instance, "DISPLAY_NAME", interface_instance.__class__.__name__)
            self.interface_class = interface_instance.__class__
        else:
            self.display_name = "Unknown Interface"
            
        self.setWindowTitle(f"Configure {self.display_name}")
        self.setMinimumWidth(500)
        self._apply_screen_friendly_size()
        self.setStyleSheet(DialogStyles.dark_dialog())
        
        self.field_widgets = {}
        self.setup_ui()
        
        # Setup refresh timer to keep status in sync with hardware
        from PyQt6.QtCore import QTimer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.update_connection_state)
        self.refresh_timer.start(1000) # Refresh every second
        
    def setup_ui(self):
        layout = QVBoxLayout(self)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        
        # Description header (More prominent, outside tabs)
        desc = getattr(self.interface_class, "DESCRIPTION", "")
        if desc:
            desc_header = QLabel(desc)
            desc_header.setWordWrap(True)
            desc_header.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; font-size: 13px; font-weight: bold; padding: 10px; background-color: {COLORS.BG_CARD}; border-radius: 5px; margin-bottom: 5px;")
            content_layout.addWidget(desc_header)
            
        # Tab Widget for organization
        self.tabs = QTabWidget()
        content_layout.addWidget(self.tabs)
        
        # --- General Settings Tab ---
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        
        # Status Group
        status_group = QGroupBox("Status & Control")
        status_group.setStyleSheet(GroupBoxStyles.default())
        status_form = QFormLayout(status_group)
        
        # Enabled Checkbox
        self.enabled_checkbox = QCheckBox("Interface Enabled")
        self.enabled_checkbox.setToolTip("Enable or disable this entire interface and all its sensors.")
        self.enabled_checkbox.setChecked(self.config.get("enabled", True))
        status_form.addRow(self.enabled_checkbox)
        
        # Auto-connect Checkbox
        self.auto_connect_checkbox = QCheckBox("Auto-connect on Startup")
        self.auto_connect_checkbox.setToolTip("Automatically attempt to connect to this device when the application starts.")
        self.auto_connect_checkbox.setChecked(self.config.get("auto_connect", False))
        status_form.addRow(self.auto_connect_checkbox)
        
        # Connection Control
        conn_layout = QHBoxLayout()
        self.status_label = QLabel("Status: Disconnected")
        self.status_label.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY};")
        conn_layout.addWidget(self.status_label)
        conn_layout.addStretch()
        
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setMinimumWidth(120)
        self.update_connection_state()
        self.connect_btn.clicked.connect(self.on_connect_clicked)
        conn_layout.addWidget(self.connect_btn)
        
        status_form.addRow("Connection:", conn_layout)
        general_layout.addWidget(status_group)

        test_actions = []
        if self.interface_class and hasattr(self.interface_class, "get_test_actions"):
            try:
                test_actions = self.interface_class.get_test_actions() or []
            except Exception:
                test_actions = []

        if test_actions:
            diagnostics_group = QGroupBox("Diagnostics")
            diagnostics_group.setStyleSheet(GroupBoxStyles.default())
            diagnostics_layout = QVBoxLayout(diagnostics_group)

            btn_row = QHBoxLayout()
            for action in test_actions:
                btn = QPushButton(action.get("label", action.get("id", "Run Test")))
                btn.clicked.connect(lambda _, a=action: self._run_test_action(a))
                btn_row.addWidget(btn)
            btn_row.addStretch()
            diagnostics_layout.addLayout(btn_row)

            self.diagnostics_output = QTextEdit()
            self.diagnostics_output.setReadOnly(True)
            self.diagnostics_output.setPlaceholderText("Test results will appear here.")
            self.diagnostics_output.setMinimumHeight(140)
            diagnostics_layout.addWidget(self.diagnostics_output)

            general_layout.addWidget(diagnostics_group)

        general_layout.addStretch()
        
        self.tabs.addTab(general_tab, "General")
        
        # --- Configuration Tab ---
        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)
        
        config_form = QFormLayout()
        config_layout.addLayout(config_form)
        
        # Dynamic fields from schema
        schema = getattr(self.interface_class, "CONFIG_SCHEMA", {})
        self.field_labels = {} # Store labels so we can hide them too
        for key, field_config in schema.items():
            label_text = field_config.get("label", key.replace("_", " ").title())
            label_widget = QLabel(label_text + ":")
            widget = self._create_field_widget(key, field_config)
            
            config_form.addRow(label_widget, widget)
            self.field_widgets[key] = widget
            self.field_labels[key] = label_widget
            
            # Connect change signal if it's a combo box to update visibility
            if isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(lambda _: self.update_field_visibility())
            elif isinstance(widget, QWidget) and widget.findChild(QComboBox):
                combo = widget.findChild(QComboBox)
                combo.currentTextChanged.connect(lambda _: self.update_field_visibility())

        config_layout.addStretch()
        self.tabs.addTab(config_tab, "Settings")
        
        # Initial visibility update
        self.update_field_visibility()
        
        # --- Help & Information Tab ---
        help_tab = QWidget()
        help_layout = QVBoxLayout(help_tab)
        
        help_text = getattr(self.interface_class, "HELP_TEXT", "")
        if not help_text:
            help_text = f"<h3>{self.display_name}</h3><p>No additional help information provided for this interface.</p>"
        
        # Add information about available sensor keys if we can find them
        sensor_info = self._get_available_sensors_html()
        if sensor_info:
            help_text += "<hr>" + sensor_info
            
        help_view = QTextEdit()
        help_view.setReadOnly(True)
        help_view.setHtml(help_text)
        help_layout.addWidget(help_view)
        
        # Special button for Arduino Examples
        if self.display_name == "Arduino":
            source_btn_layout = QHBoxLayout()
            view_examples_btn = QPushButton("📘 View Arduino Examples")
            view_examples_btn.setStyleSheet(ButtonStyles.get("primary", "small"))
            
            def open_examples():
                # Look for "Arduino example code" in project root
                example_path = os.path.join(os.getcwd(), "Arduino example code")
                if os.path.exists(example_path):
                    QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(example_path)))
                else:
                    QMessageBox.warning(self, "Error", "Arduino example folder not found.")
            
            view_examples_btn.clicked.connect(open_examples)
            source_btn_layout.addWidget(view_examples_btn)
            source_btn_layout.addStretch()
            help_layout.addLayout(source_btn_layout)
            
        self.tabs.addTab(help_tab, "Help")
            
        # Dialog Buttons
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        content_layout.addWidget(self.buttons)

        scroll_area.setWidget(content)
        layout.addWidget(scroll_area)

    def _apply_screen_friendly_size(self):
        screen = self.screen()
        if not screen:
            return

        available = screen.availableGeometry()
        target_width = min(max(560, int(available.width() * 0.55)), 900)
        target_height = min(max(520, int(available.height() * 0.8)), 820)
        self.resize(QSize(target_width, target_height))
        self.setMaximumSize(available.width() - 40, available.height() - 40)
        
    def _create_field_widget(self, key, field_config):
        field_type = field_config.get("type", "string")
        default = self.config.get(key, field_config.get("default"))
        
        if field_type == "list":
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            
            widget = QComboBox()
            options = field_config.get("options", [])
            options_cmd = field_config.get("options_cmd")
            
            def refresh_options():
                if options_cmd and hasattr(self.interface_class, "get_ui_options"):
                    new_options = self.interface_class.get_ui_options(key)
                    current = widget.currentText()
                    widget.clear()
                    for opt in new_options:
                        widget.addItem(str(opt))
                    if current:
                        idx = widget.findText(current)
                        if idx >= 0:
                            widget.setCurrentIndex(idx)
            
            # Initial load
            if options_cmd and hasattr(self.interface_class, "get_ui_options"):
                options = self.interface_class.get_ui_options(key)
            
            for opt in options:
                widget.addItem(str(opt))
            
            if default is not None:
                index = widget.findText(str(default))
                if index >= 0:
                    widget.setCurrentIndex(index)
            
            layout.addWidget(widget, 1)
            
            if options_cmd:
                refresh_btn = QPushButton("🔄")
                refresh_btn.setFixedWidth(30)
                refresh_btn.setToolTip("Refresh list")
                refresh_btn.clicked.connect(refresh_options)
                layout.addWidget(refresh_btn)
                
            return container
            
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

    def update_field_visibility(self):
        """Update field visibility based on class-defined rules if available."""
        if not hasattr(self.interface_class, "get_field_visibility"):
            return
            
        current_config = self.get_config()
        visibility_map = self.interface_class.get_field_visibility(current_config)
        
        for key, is_visible in visibility_map.items():
            if key in self.field_widgets:
                self.field_widgets[key].setVisible(is_visible)
            if key in self.field_labels:
                self.field_labels[key].setVisible(is_visible)

    def update_connection_state(self):
        is_connected = False
        if self.interface_instance:
            is_connected = self.interface_instance.is_connected()
        
        if is_connected:
            self.connect_btn.setText("Disconnect")
            self.connect_btn.setStyleSheet(ConnectionStyles.disconnected())
            self.status_label.setText("Status: Connected")
            self.status_label.setStyleSheet(f"color: {COLORS.SUCCESS}; font-weight: bold;")
        else:
            self.connect_btn.setText("Connect")
            self.connect_btn.setStyleSheet(ConnectionStyles.connected())
            self.status_label.setText("Status: Disconnected")
            self.status_label.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY};")

    def on_connect_clicked(self):
        if not self._ensure_interface_instance():
            return
            
        if self.interface_instance.is_connected():
            self.interface_instance.disconnect()
        else:
            # Update instance config from UI before connecting
            self.apply_config_to_instance()

            # For now, just try to connect. Real implementations might need config update.
            success = self.interface_instance.connect()
            if not success:
                error = getattr(self.interface_instance, "error_message", "Unknown error")
                QMessageBox.critical(self, "Connection Failed", f"Could not connect to {self.display_name}:\n{error}")
            else:
                # Emit signal to notify main window
                self.connection_status_changed.emit(self.display_name, True)
        
        # If we disconnected, notify main window as well
        if not self.interface_instance.is_connected():
            self.connection_status_changed.emit(self.display_name, False)
        
        self.update_connection_state()

    def _ensure_interface_instance(self):
        if self.interface_instance:
            return True

        if not self.interface_class:
            QMessageBox.information(self, "Connection", "Interface not initialized. Please try again or restart the application.")
            return False

        try:
            current_config = self.get_config()
            
            # --- ADDED: Try to find an active instance for this interface type ---
            # This prevents PermissionError if the port is already open by the app
            dcc = getattr(self.parent_window, 'data_collection_controller', None)
            if not dcc and hasattr(self.parent_window, 'main_window'): # Some parents are controllers
                dcc = getattr(self.parent_window.main_window, 'data_collection_controller', None)
            
            if dcc:
                # 1. Check interface_threads (plugins)
                device_type = getattr(self.interface_class, 'DISPLAY_NAME', self.display_name)
                if device_type in dcc.interface_threads:
                    thread = dcc.interface_threads[device_type]
                    if hasattr(thread, 'interface'):
                        self.interface_instance = thread.interface
                        return True
                
                # 2. Check standard interfaces
                st_lower = device_type.lower()
                if st_lower == "arduino" and hasattr(dcc, 'arduino_thread'):
                    self.interface_instance = dcc.arduino_thread
                    return True
                elif st_lower == "labjack" and hasattr(dcc, 'labjack_thread'):
                    self.interface_instance = dcc.labjack_thread
                    return True
                elif st_lower == "mqtt" and hasattr(dcc, 'mqtt_thread'):
                    self.interface_instance = dcc.mqtt_thread
                    return True
            # ---------------------------------------------------------------------

            import inspect
            sig = inspect.signature(self.interface_class.__init__)
            valid_params = sig.parameters.keys()

            filtered_config = {k: v for k, v in current_config.items() if k in valid_params}

            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                filtered_config = current_config

            self.interface_instance = self.interface_class(**filtered_config)
            return True
        except Exception as e:
            QMessageBox.warning(self, "Connection", f"Could not initialize interface: {e}")
            return False

    def _append_diagnostics_output(self, text):
        output = getattr(self, "diagnostics_output", None)
        if output:
            output.append(text)

    def _run_test_action(self, action):
        if not self._ensure_interface_instance():
            return

        if not hasattr(self.interface_instance, "run_test_action"):
            QMessageBox.information(self, "Diagnostics", "No test actions are available for this interface.")
            return

        input_value = None
        input_label = action.get("input_label")
        if input_label:
            default_value = str(action.get("default_value", ""))
            value, ok = QInputDialog.getText(
                self,
                action.get("label", "Test Input"),
                input_label,
                text=default_value,
            )
            if not ok:
                return
            input_value = value

        self.apply_config_to_instance()

        was_connected = self.interface_instance.is_connected()
        connected_for_test = False

        if not was_connected:
            if not self.interface_instance.connect():
                error = getattr(self.interface_instance, "error_message", "Unknown error")
                QMessageBox.critical(self, "Diagnostics", f"Could not connect to {self.display_name}:\n{error}")
                self._append_diagnostics_output(f"Connection failed:\n{error}")
                self.update_connection_state()
                return
            connected_for_test = True

        try:
            result = self.interface_instance.run_test_action(action.get("id"), input_value=input_value)
            success = bool(result.get("success")) if isinstance(result, dict) else bool(result)
            message = result.get("message", str(result)) if isinstance(result, dict) else str(result)

            prefix = "SUCCESS" if success else "FAILED"
            self._append_diagnostics_output(f"[{prefix}] {action.get('label', action.get('id'))}\n{message}\n")

            if success:
                QMessageBox.information(self, "Diagnostics", message)
            else:
                QMessageBox.warning(self, "Diagnostics", message)
        except Exception as e:
            QMessageBox.critical(self, "Diagnostics", f"Test failed with an exception:\n{e}")
            self._append_diagnostics_output(f"[EXCEPTION] {action.get('label', action.get('id'))}\n{e}\n")
        finally:
            if connected_for_test and self.interface_instance.is_connected():
                self.interface_instance.disconnect()
            self.update_connection_state()

    def apply_config_to_instance(self):
        """Applies current UI configuration to the interface instance."""
        if not self.interface_instance:
            return
            
        current_config = self.get_config()
        
        # Update instance attributes dynamically based on config
        for key, value in current_config.items():
            if hasattr(self.interface_instance, key):
                # Try to match the type if possible
                attr_val = getattr(self.interface_instance, key)
                if isinstance(attr_val, bool) and not isinstance(value, bool):
                    value = str(value).lower() == "true"
                elif isinstance(attr_val, int) and not isinstance(value, int):
                    try:
                        value = int(value)
                    except (ValueError, TypeError):
                        pass
                elif isinstance(attr_val, float) and not isinstance(value, float):
                    try:
                        if isinstance(value, str):
                            value = value.replace(',', '.')
                        value = float(value)
                    except (ValueError, TypeError):
                        pass
                setattr(self.interface_instance, key, value)
        
        # Special handling for baud_rate which might be baud_rate or baud
        if "baud_rate" in current_config:
            baud_val = current_config["baud_rate"]
            try:
                baud_val = int(baud_val)
                if hasattr(self.interface_instance, "baud"):
                    self.interface_instance.baud = baud_val
                if hasattr(self.interface_instance, "baud_rate"):
                    self.interface_instance.baud_rate = baud_val
            except (ValueError, TypeError):
                pass

        # Special handling for LabJack sampling_rate
        if "sampling_rate" in current_config and hasattr(self.interface_instance, "sampling_rate"):
            try:
                rate_val = current_config["sampling_rate"]
                if isinstance(rate_val, str):
                    rate_val = rate_val.replace(',', '.')
                self.interface_instance.sampling_rate = float(rate_val)
            except (ValueError, TypeError):
                pass

    def accept(self):
        """Override accept to ensure config is applied to instance even if 'Connect' wasn't clicked."""
        self.apply_config_to_instance()
        super().accept()

    def get_config(self):
        config = {
            "enabled": self.enabled_checkbox.isChecked(),
            "auto_connect": self.auto_connect_checkbox.isChecked()
        }
        
        # Merge existing config to preserve keys not in schema
        merged_config = self.config.copy()
        merged_config.update(config)
        
        for key, widget in self.field_widgets.items():
            # If it's a list type, the widget is actually a container QWidget
            if isinstance(widget, QWidget) and not isinstance(widget, (QComboBox, QDoubleSpinBox, QCheckBox, QLineEdit)):
                # It's our list container, find the QComboBox inside
                combo = widget.findChild(QComboBox)
                if combo:
                    merged_config[key] = combo.currentText()
            elif isinstance(widget, QComboBox):
                merged_config[key] = widget.currentText()
            elif isinstance(widget, QDoubleSpinBox):
                merged_config[key] = widget.value()
            elif isinstance(widget, QCheckBox):
                merged_config[key] = widget.isChecked()
            else:
                merged_config[key] = widget.text()
                
        return merged_config

    def _get_available_sensors_html(self):
        """Try to find and list all available sensor keys from the system."""
        try:
            # Try to find the data collection controller
            main_window = self.parent()
            # If parent is not MainWindow, try to find it up the tree
            while main_window and not hasattr(main_window, 'data_collection_controller'):
                main_window = main_window.parent()
            
            if not main_window or not hasattr(main_window, 'data_collection_controller'):
                return None
                
            dcc = main_window.data_collection_controller
            dcc.combined_data_mutex.lock()
            try:
                # Get keys that aren't timestamps or internal metadata
                keys = [k for k in dcc.combined_data.keys() 
                       if k != 'timestamp' and not k.endswith('_timestamp')
                       and k not in ['automation_trigger', 'automation_action', 'automation_sequence', 'automation_image']]
            finally:
                dcc.combined_data_mutex.unlock()
                
            if not keys:
                return "<p><b>Sensor Keys:</b> No active sensors detected yet. Connect interfaces to see available keys.</p>"
                
            keys.sort()
            html = "<h4>Available Live Sensor Keys</h4>"
            html += "<p style='font-size: 11px; color: #aaaaaa;'>These are the <b>exact</b> internal names used in the data stream and CSV files. Use these for alarms, scripts, or outbound plugins:</p>"
            html += "<div style='background-color: #222222; padding: 5px; border-radius: 3px; font-family: monospace;'>"
            html += "<br>".join(keys)
            html += "</div>"
            return html
        except Exception as e:
            return f"<p><i>Note: Could not retrieve live sensor list ({e})</i></p>"
