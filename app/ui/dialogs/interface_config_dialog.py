from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, 
    QLabel, QLineEdit, QPushButton, QGroupBox, 
    QMessageBox, QComboBox, QCheckBox, QWidget,
    QDialogButtonBox, QDoubleSpinBox, QTabWidget, QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl
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
        
        # Tab Widget for organization
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
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
        
        # Description
        desc_label = QLabel(getattr(self.interface_class, "DESCRIPTION", ""))
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-style: italic; margin: 10px;")
        general_layout.addWidget(desc_label)
        general_layout.addStretch()
        
        self.tabs.addTab(general_tab, "General")
        
        # --- Configuration Tab ---
        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)
        
        config_form = QFormLayout()
        config_layout.addLayout(config_form)
        
        # Dynamic fields from schema
        schema = getattr(self.interface_class, "CONFIG_SCHEMA", {})
        for key, field_config in schema.items():
            label = field_config.get("label", key.replace("_", " ").title())
            widget = self._create_field_widget(key, field_config)
            config_form.addRow(label + ":", widget)
            self.field_widgets[key] = widget
            
        config_layout.addStretch()
        self.tabs.addTab(config_tab, "Settings")
        
        help_text = getattr(self.interface_class, "HELP_TEXT", None)
        if help_text:
            help_tab = QWidget()
            help_layout = QVBoxLayout(help_tab)
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
        layout.addWidget(self.buttons)
        
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
        if not self.interface_instance:
            # Try to create a temporary instance of the class for testing connection
            if self.interface_class:
                try:
                    # Initialize with default config from UI
                    current_config = self.get_config()
                    
                    # Robust instantiation: only pass arguments that the constructor actually accepts
                    import inspect
                    sig = inspect.signature(self.interface_class.__init__)
                    valid_params = sig.parameters.keys()
                    
                    # Filter config to only include keys that are in the __init__ arguments
                    # This prevents "unexpected keyword argument" errors for standard fields like 'enabled'
                    filtered_config = {k: v for k, v in current_config.items() if k in valid_params}
                    
                    # If the class accepts **kwargs, we can pass everything
                    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                        filtered_config = current_config
                        
                    self.interface_instance = self.interface_class(**filtered_config)
                except Exception as e:
                    QMessageBox.warning(self, "Connection", f"Could not initialize interface: {e}")
                    return
            else:
                QMessageBox.information(self, "Connection", "Interface not initialized. Please try again or restart the application.")
                return
            
        if self.interface_instance.is_connected():
            self.interface_instance.disconnect()
        else:
            # Update instance config from UI before connecting
            current_config = self.get_config()
            
            # Update instance attributes dynamically based on config
            for key, value in current_config.items():
                if hasattr(self.interface_instance, key):
                    # Try to match the type if possible
                    attr_val = getattr(self.interface_instance, key)
                    if isinstance(attr_val, int) and not isinstance(value, int):
                        try:
                            value = int(value)
                        except (ValueError, TypeError):
                            pass
                    elif isinstance(attr_val, float) and not isinstance(value, float):
                        try:
                            value = float(value)
                        except (ValueError, TypeError):
                            pass
                    setattr(self.interface_instance, key, value)
            
            # Special handling for baud_rate which might be baud_rate or baud
            if "baud_rate" in current_config:
                if hasattr(self.interface_instance, "baud"):
                    try:
                        self.interface_instance.baud = int(current_config["baud_rate"])
                    except (ValueError, TypeError):
                        pass
                if hasattr(self.interface_instance, "baud_rate"):
                    try:
                        self.interface_instance.baud_rate = int(current_config["baud_rate"])
                    except (ValueError, TypeError):
                        pass

            # Special handling for LabJack sampling_rate
            if "sampling_rate" in current_config and hasattr(self.interface_instance, "sampling_rate"):
                try:
                    self.interface_instance.sampling_rate = float(current_config["sampling_rate"])
                except (ValueError, TypeError):
                    pass

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
