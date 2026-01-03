from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, 
    QLabel, QLineEdit, QPushButton, QComboBox, 
    QSpinBox, QDoubleSpinBox, QGroupBox, QCheckBox,
    QTabWidget, QTimeEdit, QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit,
    QWidget, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QTime
from app.ui.theme import GroupBoxStyles, DialogStyles
from app.models.automation import (  # Adjusted import
    TimeDurationTrigger, TimeSpecificTrigger, SensorValueTrigger, EventTrigger,
    OpticalEventTrigger, AudioEventTrigger, CompoundTrigger,
    ArduinoCommandAction, LabJackCommandAction, SerialCommandAction, SystemAction,
    SetVariableAction, JumpToStepAction, ConditionAction, InfoMarkerAction,
    AutomationStep, AutomationSequence
)

# Placeholder for actions not yet in automation.py (or needing refinement)
class DelayAction:
    def __init__(self, name, seconds):
        self.name = name
        self.seconds = seconds
        self.description = f"Wait for {seconds} seconds"

class SystemCommandAction: # Likely needs merging/replacing with SystemAction logic
     def __init__(self, name, command):
        self.name = name
        self.command = command
        self.description = f"Run system command: {command}"


class TriggerDialog(QDialog):
    """Dialog for creating or editing a trigger"""
    def __init__(self, parent=None, trigger=None, sensors=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Trigger")
        self.resize(500, 400)
        self.setStyleSheet(DialogStyles.dark_dialog())
        self.trigger = trigger
        self.sensors = sensors or []
        
        self.setup_ui()
        
        # If editing existing trigger, load its values
        if trigger:
            self.load_trigger(trigger)
            
    def setup_ui(self):
        """Set up the dialog UI"""
        layout = QVBoxLayout(self)
        
        # Trigger type selection
        form_layout = QFormLayout()
        self.trigger_name = QLineEdit()
        self.trigger_name.setPlaceholderText("Enter a name for this trigger")
        form_layout.addRow("Trigger Name:", self.trigger_name)
        
        self.trigger_type = QComboBox()
        self.trigger_type.addItems([
            "After Duration (Wait)",
            "At Specific Time",
            "When Sensor Value",
            "When Event Occurs",
            "When Optical Event",  # For camera-based sensors
            "When Audio Event",  # For audio sensors
            "Compound (AND/OR)"  # Combined triggers
        ])
        self.trigger_type.currentIndexChanged.connect(self.update_trigger_options)
        form_layout.addRow("Trigger Type:", self.trigger_type)
        
        layout.addLayout(form_layout)
        
        # Stacked widget for different trigger types
        self.trigger_options = QTabWidget()
        self.trigger_options.setTabPosition(QTabWidget.TabPosition.West)
        
        # Duration trigger options
        self.duration_widget = self.create_duration_options()
        self.trigger_options.addTab(self.duration_widget, "Duration")
        
        # Specific time trigger options
        self.time_widget = self.create_time_options()
        self.trigger_options.addTab(self.time_widget, "Time")
        
        # Sensor value trigger options
        self.sensor_widget = self.create_sensor_options()
        self.trigger_options.addTab(self.sensor_widget, "Sensor")
        
        # Event trigger options
        self.event_widget = self.create_event_options()
        self.trigger_options.addTab(self.event_widget, "Event")
        
        # Optical event trigger options
        self.optical_widget = self.create_optical_options()
        self.trigger_options.addTab(self.optical_widget, "Optical")
        
        # Audio event trigger options
        self.audio_widget = self.create_audio_options()
        self.trigger_options.addTab(self.audio_widget, "Audio")
        
        # Compound trigger options
        self.compound_widget = self.create_compound_options()
        self.trigger_options.addTab(self.compound_widget, "Compound")
        
        layout.addWidget(self.trigger_options)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.ok_button)
        buttons_layout.addWidget(self.cancel_button)
        
        layout.addLayout(buttons_layout)
        
        # Ensure the correct tab is visible initially
        self.update_trigger_options()

    def create_duration_options(self):
        """Create options for duration trigger"""
        widget = QGroupBox("Wait for Duration")
        widget.setStyleSheet(GroupBoxStyles.compact())
        layout = QFormLayout(widget)
        
        self.duration_minutes = QSpinBox()
        self.duration_minutes.setRange(0, 1440)  # Up to 24 hours
        self.duration_minutes.setSuffix(" minutes")
        
        self.duration_seconds = QSpinBox()
        self.duration_seconds.setRange(0, 59)
        self.duration_seconds.setSuffix(" seconds")
        
        layout.addRow("Minutes:", self.duration_minutes)
        layout.addRow("Seconds:", self.duration_seconds)
        
        return widget
        
    def create_time_options(self):
        """Create options for specific time trigger"""
        widget = QGroupBox("At Specific Time")
        widget.setStyleSheet(GroupBoxStyles.compact())
        layout = QFormLayout(widget)
        
        self.specific_time = QTimeEdit()
        self.specific_time.setDisplayFormat("HH:mm")
        self.specific_time.setTime(QTime.currentTime())
        
        layout.addRow("Time:", self.specific_time)
        
        return widget
        
    def create_sensor_options(self):
        """Create options for sensor value trigger"""
        widget = QGroupBox("Sensor Value Condition")
        widget.setStyleSheet(GroupBoxStyles.compact())
        layout = QFormLayout(widget)
        
        self.sensor_name = QComboBox()
        # Use sensor names for display
        sensor_names = [s.name if hasattr(s, 'name') else str(s) for s in self.sensors]
        self.sensor_name.addItems(sensor_names)
        
        self.sensor_operator = QComboBox()
        self.sensor_operator.addItems([">", "<", "==", ">=", "<="])
        
        self.sensor_threshold = QDoubleSpinBox()
        self.sensor_threshold.setRange(-999999, 999999)
        self.sensor_threshold.setDecimals(2)
        self.sensor_threshold.setSingleStep(0.1)
        
        self.sensor_hysteresis = QDoubleSpinBox()
        self.sensor_hysteresis.setRange(0, 999999)
        self.sensor_hysteresis.setDecimals(2)
        self.sensor_hysteresis.setSingleStep(0.01)
        self.sensor_hysteresis.setToolTip("Hysteresis prevents rapid triggering near the threshold")
        
        layout.addRow("Sensor:", self.sensor_name)
        layout.addRow("Operator:", self.sensor_operator)
        layout.addRow("Threshold:", self.sensor_threshold)
        layout.addRow("Hysteresis:", self.sensor_hysteresis)
        
        return widget
        
    def create_event_options(self):
        """Create options for event trigger"""
        widget = QGroupBox("Event")
        widget.setStyleSheet(GroupBoxStyles.compact())
        layout = QFormLayout(widget)
        
        self.event_type = QComboBox()
        # TODO: Make these event types configurable or dynamically discovered?
        self.event_type.addItems([
            "recording_started",
            "recording_stopped",
            "motion_detected" 
        ])
        
        layout.addRow("Event Type:", self.event_type)
        
        return widget
    
    def create_optical_options(self):
        """Create options for optical sensor event trigger"""
        widget = QGroupBox("Optical Sensor Event")
        widget.setStyleSheet(GroupBoxStyles.compact())
        layout = QFormLayout(widget)
        
        # Optical sensor selection (filter to show only optical sensors)
        self.optical_sensor_name = QComboBox()
        # Filter sensors to show only optical sensors
        self.optical_sensors = [s for s in self.sensors if hasattr(s, 'interface_type') and s.interface_type == 'OpticalSensor']
        
        if not self.optical_sensors:
            # Fallback if no proper SensorModel objects found
            optical_sensor_names = [str(s) for s in self.sensors if 'Optical' in str(s) or 'optical' in str(s).lower()]
            if not optical_sensor_names:
                optical_sensor_names = [s.name if hasattr(s, 'name') else str(s) for s in self.sensors]
            self.optical_sensor_name.addItems(optical_sensor_names)
        else:
            self.optical_sensor_name.addItems([s.name for s in self.optical_sensors])
            
        self.optical_sensor_name.currentTextChanged.connect(self._on_optical_sensor_changed)
        layout.addRow("Optical Sensor:", self.optical_sensor_name)
        
        # Event type selection
        self.optical_event_type = QComboBox()
        self.optical_event_type.addItems([
            "light_event",           # Light Event Detected
            "brightness_above",       # Brightness Above Threshold
            "brightness_below",       # Brightness Below Threshold
            "fill_level_above",       # Fill Level Above Threshold
            "fill_level_below",       # Fill Level Below Threshold
            "particle_count_above",   # Particle Count Above Threshold
            "color_detected",         # Target Color Detected
            "position_changed"        # Position Changed Significantly
        ])
        self.optical_event_type.currentIndexChanged.connect(self._update_optical_threshold_visibility)
        layout.addRow("Event Type:", self.optical_event_type)
        
        # Event type descriptions
        self.optical_event_desc = QLabel("Triggers when a light event is detected")
        self.optical_event_desc.setWordWrap(True)
        self.optical_event_desc.setStyleSheet("color: gray; font-style: italic;")
        layout.addRow("", self.optical_event_desc)
        
        # Threshold for value-based events
        self.optical_threshold = QDoubleSpinBox()
        self.optical_threshold.setRange(0, 100000)
        self.optical_threshold.setDecimals(1)
        self.optical_threshold.setValue(50)
        self.optical_threshold_label = QLabel("Threshold:")
        layout.addRow(self.optical_threshold_label, self.optical_threshold)
        
        # Threshold type indicator
        self.optical_threshold_unit = QLabel("%")
        layout.addRow("", self.optical_threshold_unit)
        
        # Initially hide threshold for light_event
        self._update_optical_threshold_visibility()
        
        # Trigger initial sensor-based mode selection
        self._on_optical_sensor_changed()
        
        return widget

    def _on_optical_sensor_changed(self):
        """Update event type based on selected optical sensor's configuration"""
        sensor_name = self.optical_sensor_name.currentText()
        
        # Find the sensor object
        sensor = None
        for s in self.sensors:
            if hasattr(s, 'name') and s.name == sensor_name:
                sensor = s
                break
        
        if sensor and hasattr(sensor, 'optical_config'):
            mode = sensor.optical_config.get('mode')
            
            # Map optical sensor modes to automation event types
            mode_to_event = {
                'light_events': 'light_event',
                'brightness': 'brightness_above',
                'particle_count': 'particle_count_above',
                'color': 'color_detected',
                'position': 'position_changed',
                'fill_level': 'fill_level_above'
            }
            
            event_type = mode_to_event.get(mode)
            if event_type:
                index = self.optical_event_type.findText(event_type)
                if index >= 0:
                    self.optical_event_type.setCurrentIndex(index)
                    # For specific modes, we might want to auto-populate the threshold
                    if mode == 'fill_level':
                        target_pct = sensor.optical_config.get('fill_threshold_percent', 50)
                        self.optical_threshold.setValue(target_pct)
                    elif mode == 'light_events':
                        # No threshold needed
                        pass
                    # Add other mode-specific threshold loading if helpful
    
    def _update_optical_threshold_visibility(self):
        """Update threshold visibility based on selected optical event type"""
        event_type = self.optical_event_type.currentText()
        
        # Descriptions for each event type
        descriptions = {
            "light_event": "Triggers when a light event (bright spot) is detected",
            "brightness_above": "Triggers when average brightness exceeds threshold",
            "brightness_below": "Triggers when average brightness falls below threshold",
            "fill_level_above": "Triggers when fill level exceeds threshold percentage",
            "fill_level_below": "Triggers when fill level falls below threshold percentage",
            "particle_count_above": "Triggers when particle count exceeds threshold",
            "color_detected": "Triggers when target color coverage exceeds threshold %",
            "position_changed": "Triggers when tracked position moves more than threshold %"
        }
        self.optical_event_desc.setText(descriptions.get(event_type, ""))
        
        # Show/hide threshold based on event type
        needs_threshold = event_type != "light_event"
        self.optical_threshold.setVisible(needs_threshold)
        self.optical_threshold_label.setVisible(needs_threshold)
        self.optical_threshold_unit.setVisible(needs_threshold)
        
        # Set appropriate range and unit
        if event_type in ["fill_level_above", "fill_level_below", "color_detected", "position_changed"]:
            self.optical_threshold.setRange(0, 100)
            self.optical_threshold_unit.setText("% (percentage)")
            self.optical_threshold.setValue(50 if "above" in event_type else 20)
        elif event_type in ["brightness_above", "brightness_below"]:
            self.optical_threshold.setRange(0, 255)
            self.optical_threshold_unit.setText("(0-255 brightness)")
            self.optical_threshold.setValue(128)
        elif event_type == "particle_count_above":
            self.optical_threshold.setRange(0, 10000)
            self.optical_threshold_unit.setText("(count)")
            self.optical_threshold.setValue(10)
    
    def create_compound_options(self):
        """Create options for compound trigger"""
        widget = QGroupBox("Logic Combination")
        widget.setStyleSheet(GroupBoxStyles.compact())
        layout = QVBoxLayout(widget)
        
        self.compound_logic = QComboBox()
        self.compound_logic.addItems(["AND", "OR"])
        layout.addLayout(QFormLayout())
        layout.itemAt(0).layout().addRow("Logic:", self.compound_logic)
        
        label = QLabel("Note: Compound triggers can currently only be created by combining two existing triggers.")
        label.setWordWrap(True)
        label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(label)
        
        # We'll just show buttons to configure two sub-triggers
        self.sub_trigger1 = None
        self.sub_trigger2 = None
        
        self.btn_trig1 = QPushButton("Configure Trigger 1")
        self.btn_trig1.clicked.connect(self._edit_sub_trigger1)
        self.label_trig1 = QLabel("Not configured")
        
        self.btn_trig2 = QPushButton("Configure Trigger 2")
        self.btn_trig2.clicked.connect(self._edit_sub_trigger2)
        self.label_trig2 = QLabel("Not configured")
        
        layout.addWidget(self.btn_trig1)
        layout.addWidget(self.label_trig1)
        layout.addWidget(self.btn_trig2)
        layout.addWidget(self.label_trig2)
        
        return widget

    def _edit_sub_trigger1(self):
        dialog = TriggerDialog(self, self.sub_trigger1, self.sensors)
        if dialog.exec():
            self.sub_trigger1 = dialog.get_trigger()
            self.label_trig1.setText(self.sub_trigger1.description if self.sub_trigger1 else "Not configured")

    def _edit_sub_trigger2(self):
        dialog = TriggerDialog(self, self.sub_trigger2, self.sensors)
        if dialog.exec():
            self.sub_trigger2 = dialog.get_trigger()
            self.label_trig2.setText(self.sub_trigger2.description if self.sub_trigger2 else "Not configured")

    def create_audio_options(self):
        """Create options for audio sensor event trigger"""
        widget = QGroupBox("Audio Sensor Event")
        widget.setStyleSheet(GroupBoxStyles.compact())
        layout = QFormLayout(widget)
        
        # Audio sensor selection (filter to show only audio sensors)
        self.audio_sensor_name = QComboBox()
        # Filter sensors to show only audio sensors
        self.audio_sensors = [s for s in self.sensors if hasattr(s, 'interface_type') and s.interface_type == 'AudioSensor']
        
        if not self.audio_sensors:
            audio_sensor_names = [str(s) for s in self.sensors if 'Audio' in str(s) or 'audio' in str(s).lower()]
            if not audio_sensor_names:
                audio_sensor_names = [s.name if hasattr(s, 'name') else str(s) for s in self.sensors]
            self.audio_sensor_name.addItems(audio_sensor_names)
        else:
            self.audio_sensor_name.addItems([s.name for s in self.audio_sensors])
            
        self.audio_sensor_name.currentTextChanged.connect(self._on_audio_sensor_changed)
        layout.addRow("Audio Sensor:", self.audio_sensor_name)
        
        # Event type selection
        self.audio_event_type = QComboBox()
        self.audio_event_type.addItems([
            "rms_above",           # RMS Level Above Threshold
            "rms_below",            # RMS Level Below Threshold
            "peak_above",           # Peak Amplitude Above Threshold
            "peak_below",           # Peak Amplitude Below Threshold
            "frequency_above",      # Frequency Above Threshold
            "frequency_below",      # Frequency Below Threshold
            "frequency_stable",     # Frequency Stable (within range)
            "frequency_unstable",   # Frequency Unstable (outside range)
            "db_above",            # dB Level Above Threshold
            "db_below",            # dB Level Below Threshold
            "band_energy_above",   # Band Energy Above Threshold
            "band_energy_below",   # Band Energy Below Threshold
        ])
        self.audio_event_type.currentIndexChanged.connect(self._update_audio_threshold_visibility)
        layout.addRow("Event Type:", self.audio_event_type)
        
        # Event type descriptions
        self.audio_event_desc = QLabel("Triggers when RMS level exceeds threshold")
        self.audio_event_desc.setWordWrap(True)
        self.audio_event_desc.setStyleSheet("color: gray; font-style: italic;")
        layout.addRow("", self.audio_event_desc)
        
        # Threshold for value-based events
        self.audio_threshold = QDoubleSpinBox()
        self.audio_threshold.setRange(0, 100000)
        self.audio_threshold.setDecimals(2)
        self.audio_threshold.setValue(0.5)
        self.audio_threshold_label = QLabel("Threshold:")
        layout.addRow(self.audio_threshold_label, self.audio_threshold)
        
        # Threshold unit indicator
        self.audio_threshold_unit = QLabel("(0-1 range)")
        layout.addRow("", self.audio_threshold_unit)
        
        # Initially update visibility
        self._update_audio_threshold_visibility()
        
        return widget
    
    def _update_audio_threshold_visibility(self):
        """Update threshold visibility and settings based on selected audio event type"""
        event_type = self.audio_event_type.currentText()
        
        # Descriptions for each event type
        descriptions = {
            "rms_above": "Triggers when RMS level exceeds threshold (0-1 range)",
            "rms_below": "Triggers when RMS level falls below threshold (0-1 range)",
            "peak_above": "Triggers when peak amplitude exceeds threshold (0-1 range)",
            "peak_below": "Triggers when peak amplitude falls below threshold (0-1 range)",
            "frequency_above": "Triggers when dominant frequency exceeds threshold (Hz)",
            "frequency_below": "Triggers when dominant frequency falls below threshold (Hz)",
            "frequency_stable": "Triggers when frequency stability (std dev) is within threshold (Hz)",
            "frequency_unstable": "Triggers when frequency stability (std dev) exceeds threshold (Hz)",
            "db_above": "Triggers when dB level exceeds threshold (dB, typically -60 to 0)",
            "db_below": "Triggers when dB level falls below threshold (dB, typically -60 to 0)",
            "band_energy_above": "Triggers when band energy exceeds threshold (0-1 range)",
            "band_energy_below": "Triggers when band energy falls below threshold (0-1 range)",
        }
        self.audio_event_desc.setText(descriptions.get(event_type, ""))
        
        # All audio events need a threshold
        self.audio_threshold.setVisible(True)
        self.audio_threshold_label.setVisible(True)
        self.audio_threshold_unit.setVisible(True)
        
        # Set appropriate range and unit based on event type
        if event_type in ["rms_above", "rms_below", "peak_above", "peak_below", "band_energy_above", "band_energy_below"]:
            self.audio_threshold.setRange(0, 1)
            self.audio_threshold.setDecimals(3)
            self.audio_threshold.setSingleStep(0.01)
            self.audio_threshold.setValue(0.5 if "above" in event_type else 0.1)
            self.audio_threshold_unit.setText("(0-1 range)")
        elif event_type in ["frequency_above", "frequency_below"]:
            self.audio_threshold.setRange(20, 20000)
            self.audio_threshold.setDecimals(1)
            self.audio_threshold.setSingleStep(10)
            self.audio_threshold.setValue(1000 if "above" in event_type else 100)
            self.audio_threshold_unit.setText("(Hz)")
        elif event_type in ["frequency_stable", "frequency_unstable"]:
            self.audio_threshold.setRange(0.1, 100)
            self.audio_threshold.setDecimals(2)
            self.audio_threshold.setSingleStep(0.5)
            self.audio_threshold.setValue(5.0 if "stable" in event_type else 10.0)
            self.audio_threshold_unit.setText("(Hz std dev)")
        elif event_type in ["db_above", "db_below"]:
            self.audio_threshold.setRange(-60, 0)
            self.audio_threshold.setDecimals(1)
            self.audio_threshold.setSingleStep(1)
            self.audio_threshold.setValue(-20 if "above" in event_type else -40)
            self.audio_threshold_unit.setText("(dB)")

    def _on_audio_sensor_changed(self):
        """Update event type based on selected audio sensor's configuration"""
        sensor_name = self.audio_sensor_name.currentText()
        
        # Find the sensor object
        sensor = None
        for s in self.sensors:
            if hasattr(s, 'name') and s.name == sensor_name:
                sensor = s
                break
        
        if sensor and hasattr(sensor, 'audio_config'):
            mode = sensor.audio_config.get('mode')
            
            # Map audio sensor modes to automation event types
            mode_to_event = {
                'rms': 'rms_above',
                'peak': 'peak_above',
                'freq': 'frequency_above',
                'band_energy': 'band_energy_above',
                'db': 'db_above'
            }
            
            event_type = mode_to_event.get(mode)
            if event_type:
                index = self.audio_event_type.findText(event_type)
                if index >= 0:
                    self.audio_event_type.setCurrentIndex(index)
                    
                    # Auto-populate threshold from gate if available
                    if 'noise_gate' in sensor.audio_config:
                        self.audio_threshold.setValue(sensor.audio_config['noise_gate'])
        
    def update_trigger_options(self):
        """Update the visible trigger options based on selected type"""
        index = self.trigger_type.currentIndex()
        self.trigger_options.setCurrentIndex(index)
        
    def load_trigger(self, trigger):
        """Load values from an existing trigger"""
        self.trigger_name.setText(trigger.name)
        
        if isinstance(trigger, TimeDurationTrigger):
            self.trigger_type.setCurrentIndex(0)
            self.duration_minutes.setValue(trigger.minutes)
            self.duration_seconds.setValue(trigger.seconds)
        elif isinstance(trigger, TimeSpecificTrigger):
            self.trigger_type.setCurrentIndex(1)
            self.specific_time.setTime(QTime(trigger.hour, trigger.minute))
        elif isinstance(trigger, SensorValueTrigger):
            self.trigger_type.setCurrentIndex(2)
            sensor_name_str = str(trigger.sensor_name)
            # Check if the sensor name exists in the combo box
            if self.sensor_name.findText(sensor_name_str) != -1:
                 self.sensor_name.setCurrentText(sensor_name_str)
            else:
                 # Add the sensor if it's not there (e.g., loaded from file)
                 self.sensor_name.addItem(sensor_name_str)
                 self.sensor_name.setCurrentText(sensor_name_str)
                 
            self.sensor_operator.setCurrentText(trigger.operator)
            self.sensor_threshold.setValue(trigger.threshold)
            self.sensor_hysteresis.setValue(getattr(trigger, 'hysteresis', 0.0))
        elif isinstance(trigger, EventTrigger):
            self.trigger_type.setCurrentIndex(3)
            self.event_type.setCurrentText(trigger.event_type)
        elif isinstance(trigger, OpticalEventTrigger):
            self.trigger_type.setCurrentIndex(4)
            # Set sensor name
            sensor_name_str = str(trigger.sensor_name)
            if self.optical_sensor_name.findText(sensor_name_str) != -1:
                self.optical_sensor_name.setCurrentText(sensor_name_str)
            else:
                self.optical_sensor_name.addItem(sensor_name_str)
                self.optical_sensor_name.setCurrentText(sensor_name_str)
            # Set event type
            self.optical_event_type.setCurrentText(trigger.event_type)
            # Set threshold
            if trigger.threshold_percent is not None:
                self.optical_threshold.setValue(trigger.threshold_percent)
            elif trigger.threshold is not None:
                self.optical_threshold.setValue(trigger.threshold)
        elif isinstance(trigger, AudioEventTrigger):
            self.trigger_type.setCurrentIndex(5)
            # Set sensor name
            sensor_name_str = str(trigger.sensor_name)
            if self.audio_sensor_name.findText(sensor_name_str) != -1:
                self.audio_sensor_name.setCurrentText(sensor_name_str)
            else:
                self.audio_sensor_name.addItem(sensor_name_str)
                self.audio_sensor_name.setCurrentText(sensor_name_str)
            # Set event type
            self.audio_event_type.setCurrentText(trigger.event_type)
            # Set threshold
            if trigger.threshold is not None:
                self.audio_threshold.setValue(trigger.threshold)
            elif trigger.threshold_percent is not None:
                self.audio_threshold.setValue(trigger.threshold_percent)
        elif isinstance(trigger, CompoundTrigger):
            self.trigger_type.setCurrentIndex(6)
            self.compound_logic.setCurrentText(trigger.logic)
            if len(trigger.triggers) >= 1:
                self.sub_trigger1 = trigger.triggers[0]
                self.label_trig1.setText(self.sub_trigger1.description)
            if len(trigger.triggers) >= 2:
                self.sub_trigger2 = trigger.triggers[1]
                self.label_trig2.setText(self.sub_trigger2.description)
            
        # Ensure the correct tab is visible after loading
        self.update_trigger_options()
            
    def get_trigger(self):
        """Get the configured trigger"""
        name = self.trigger_name.text() or "Unnamed Trigger"
        trigger_type = self.trigger_type.currentIndex()
        
        if trigger_type == 0:  # Duration
            minutes = self.duration_minutes.value()
            seconds = self.duration_seconds.value()
            return TimeDurationTrigger(name, minutes, seconds)
        elif trigger_type == 1:  # Specific time
            time = self.specific_time.time()
            return TimeSpecificTrigger(name, time.hour(), time.minute())
        elif trigger_type == 2:  # Sensor value
            sensor_name = self.sensor_name.currentText()
            operator = self.sensor_operator.currentText()
            threshold = self.sensor_threshold.value()
            hysteresis = self.sensor_hysteresis.value()
            return SensorValueTrigger(name, sensor_name, operator, threshold, hysteresis)
        elif trigger_type == 3:  # Event
            event_type = self.event_type.currentText()
            return EventTrigger(name, event_type)
        elif trigger_type == 4:  # Optical Event
            sensor_name = self.optical_sensor_name.currentText()
            event_type = self.optical_event_type.currentText()
            threshold_value = self.optical_threshold.value()
            
            # Determine if threshold is percentage or absolute value
            if event_type in ["fill_level_above", "fill_level_below", "color_detected", "position_changed"]:
                return OpticalEventTrigger(name, sensor_name, event_type, 
                                          threshold=None, threshold_percent=threshold_value)
            elif event_type == "light_event":
                return OpticalEventTrigger(name, sensor_name, event_type)
            else:
                return OpticalEventTrigger(name, sensor_name, event_type, 
                                          threshold=threshold_value, threshold_percent=None)
        elif trigger_type == 5:  # Audio Event
            sensor_name = self.audio_sensor_name.currentText().strip()
            event_type = self.audio_event_type.currentText().strip()
            threshold_value = self.audio_threshold.value()
            
            # Validate that sensor name and event type are not empty
            if not sensor_name:
                QMessageBox.warning(self, "Missing Sensor", "Please select an audio sensor.")
                return None
            if not event_type:
                QMessageBox.warning(self, "Missing Event Type", "Please select an event type.")
                return None
            
            return AudioEventTrigger(name, sensor_name, event_type, 
                                    threshold=threshold_value, threshold_percent=None)
        elif trigger_type == 6: # Compound
            logic = self.compound_logic.currentText()
            triggers = []
            if self.sub_trigger1: triggers.append(self.sub_trigger1)
            if self.sub_trigger2: triggers.append(self.sub_trigger2)
            
            if not triggers:
                QMessageBox.warning(self, "Missing Triggers", "Please configure at least one sub-trigger.")
                return None
                
            return CompoundTrigger(name, triggers, logic)
        
        return None


class ActionDialog(QDialog):
    """Dialog for creating or editing an action"""
    def __init__(self, parent=None, action=None, available_ports=None, app_context=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Action")
        self.resize(500, 400)
        self.setStyleSheet(DialogStyles.dark_dialog())
        self.action = action
        self.available_ports = available_ports or []
        self.app_context = app_context # Used to get LabJack channels, etc.
        
        # Map action type names to classes for loading/getting
        self.action_classes = {
            "Send Arduino Command": ArduinoCommandAction,
            "Send LabJack Command": LabJackCommandAction,
            "Send Serial Command": SerialCommandAction,
            "System Action": SystemAction,
            "Set Variable": SetVariableAction,
            "Info Marker": InfoMarkerAction
        }
        
        self.setup_ui()
        
        # If editing an existing action, populate the fields
        if action:
            self.load_action(action)
            
    def setup_ui(self):
        """Set up the dialog UI"""
        layout = QVBoxLayout(self)
        
        # Action type selection
        form_layout = QFormLayout()
        self.action_name = QLineEdit()
        self.action_name.setPlaceholderText("Enter a name for this action")
        form_layout.addRow("Action Name:", self.action_name)
        
        self.action_type = QComboBox()
        # Combine action types from automation.py and any placeholders
        self.action_type.addItems([
            "Send Arduino Command",
            "Send LabJack Command",
            "Send Serial Command",
            "System Action",
            "Set Variable",
            "Info Marker",
            "Jump to Step",
            "Condition (If/Else Jump)"
        ])
        self.action_type.currentIndexChanged.connect(self.update_action_options)
        form_layout.addRow("Action Type:", self.action_type)
        
        layout.addLayout(form_layout)
        
        # Tab widget for different action types
        self.action_options = QTabWidget()
        self.action_options.setTabPosition(QTabWidget.TabPosition.West)
        
        # Arduino command options
        self.arduino_widget = self.create_arduino_options()
        self.action_options.addTab(self.arduino_widget, "Arduino")
        
        # LabJack command options
        self.labjack_widget = self.create_labjack_options()
        self.action_options.addTab(self.labjack_widget, "LabJack")
        
        # Serial command options
        self.serial_widget = self.create_serial_options()
        self.action_options.addTab(self.serial_widget, "Serial")
        
        # System action options
        self.system_widget = self.create_system_options()
        self.action_options.addTab(self.system_widget, "System")

        # Set Variable action options
        self.set_variable_widget = self.create_set_variable_options()
        self.action_options.addTab(self.set_variable_widget, "Variable")
        
        # Info Marker options
        self.info_marker_widget = self.create_info_marker_options()
        self.action_options.addTab(self.info_marker_widget, "Marker")
        
        # Jump options
        self.jump_widget = self.create_jump_options()
        self.action_options.addTab(self.jump_widget, "Jump")
        
        # Condition options
        self.condition_widget = self.create_condition_options()
        self.action_options.addTab(self.condition_widget, "Condition")

        layout.addWidget(self.action_options)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.ok_button)
        buttons_layout.addWidget(self.cancel_button)
        
        layout.addLayout(buttons_layout)

        # Ensure the correct tab is visible initially
        self.update_action_options()
        
    def create_arduino_options(self):
        """Create options for Arduino command"""
        widget = QGroupBox("Arduino Command")
        widget.setStyleSheet(GroupBoxStyles.compact())
        layout = QFormLayout(widget)
        
        self.arduino_command = QLineEdit()
        self.arduino_command.setPlaceholderText("Enter command (e.g., LED:ON)")
        
        layout.addRow("Command:", self.arduino_command)
        
        return widget
        
    def create_labjack_options(self):
        """Create options for LabJack command"""
        widget = QGroupBox("LabJack Command")
        widget.setStyleSheet(GroupBoxStyles.compact())
        layout = QFormLayout(widget)
        
        # Channel selection
        self.labjack_channel = QComboBox()
        
        # Try to get available channels from the app context
        labjack_channels = ["dac0", "dac1", "fio0", "fio1"] # Defaults
        if self.app_context and hasattr(self.app_context, 'interfaces') and 'labjack' in self.app_context.interfaces:
            labjack = self.app_context.interfaces['labjack']
            # Make sure get_available_output_channels method exists and labjack is connected
            if labjack and hasattr(labjack, 'get_available_output_channels') and labjack.connected:
                labjack_channels = labjack.get_available_output_channels() # Use a method to get channels
        
        self.labjack_channel.addItems(labjack_channels)
        self.labjack_channel.setEditable(True) # Allow manual entry
        
        # Value input (stacked layout for analog/digital)
        self.value_widget = QWidget()
        self.value_layout = QHBoxLayout(self.value_widget)
        self.value_layout.setContentsMargins(0,0,0,0)

        self.labjack_value_analog = QDoubleSpinBox()
        self.labjack_value_analog.setRange(-10, 10) # Typical LabJack DAC range? Verify.
        self.labjack_value_analog.setDecimals(3)
        self.labjack_value_analog.setSingleStep(0.1)
        self.value_layout.addWidget(QLabel("Analog Value:"))
        self.value_layout.addWidget(self.labjack_value_analog)
        
        self.labjack_value_digital = QComboBox()
        self.labjack_value_digital.addItems(["Low (0)", "High (1)"])
        self.value_layout.addWidget(QLabel("Digital Value:"))
        self.value_layout.addWidget(self.labjack_value_digital)
        
        # Function to update UI based on selected channel
        def on_channel_changed(text=None):
            channel_name = text if text is not None else self.labjack_channel.currentText()
            is_digital = any(prefix in channel_name.lower() for prefix in ["fio", "eio", "cio", "mio"]) 

            self.labjack_value_analog.setVisible(not is_digital)
            self.labjack_value_analog.setEnabled(not is_digital)
            self.value_layout.itemAt(0).widget().setVisible(not is_digital) # Analog Label

            self.labjack_value_digital.setVisible(is_digital)
            self.labjack_value_digital.setEnabled(is_digital)
            self.value_layout.itemAt(2).widget().setVisible(is_digital) # Digital Label
                
        self.labjack_channel.currentTextChanged.connect(on_channel_changed)
        
        layout.addRow("Channel:", self.labjack_channel)
        layout.addRow("Value:", self.value_widget)
        
        # Initialize UI state
        on_channel_changed()
        
        return widget
        
    def create_serial_options(self):
        """Create options for serial command"""
        widget = QGroupBox("Serial Command")
        widget.setStyleSheet(GroupBoxStyles.compact())
        layout = QFormLayout(widget)
        
        self.serial_port = QComboBox()
        self.serial_port.addItems(self.available_ports)
        self.serial_port.setEditable(True)
        
        self.serial_command = QLineEdit()
        self.serial_command.setPlaceholderText("Enter command to send")
        
        layout.addRow("Port:", self.serial_port)
        layout.addRow("Command:", self.serial_command)
        
        return widget
        
    def create_system_options(self):
        """Create options for system action"""
        widget = QGroupBox("System Action")
        widget.setStyleSheet(GroupBoxStyles.compact())
        layout = QVBoxLayout(widget)
        
        # Action type selection
        action_type_layout = QFormLayout()
        self.system_action_type = QComboBox()
        # These should match SystemAction capabilities in automation.py
        self.system_action_type.addItems([
            "start_recording",
            "stop_recording",
            "take_snapshot",
            "display_message",
            "play_sound"
        ])
        self.system_action_type.currentTextChanged.connect(self.update_system_action_options)
        action_type_layout.addRow("Action:", self.system_action_type)
        layout.addLayout(action_type_layout)
        
        # Container for additional options
        self.system_options_container = QWidget()
        self.system_options_layout = QFormLayout(self.system_options_container)
        layout.addWidget(self.system_options_container)
        
        # Initialize with empty options
        self.update_system_action_options()
        
        return widget
        
    def create_set_variable_options(self):
        """Create options for Set Variable action"""
        widget = QGroupBox("Set Automation Variable")
        widget.setStyleSheet(GroupBoxStyles.compact())
        layout = QFormLayout(widget)
        
        self.variable_name_input = QLineEdit()
        self.variable_name_input.setPlaceholderText("Enter variable name (e.g., target_temp)")
        
        self.variable_expression_input = QLineEdit()
        self.variable_expression_input.setPlaceholderText("Enter value or expression (e.g., 25.5 or {sensor_temp} + 1)")
        
        layout.addRow("Variable Name:", self.variable_name_input)
        layout.addRow("Value/Expression:", self.variable_expression_input)
        
        # Add a small help label
        help_label = QLabel("Use {variable_name} or {sensor_name} for substitutions in expression.")
        help_label.setStyleSheet("font-size: 9pt; color: gray;")
        help_label.setWordWrap(True)
        layout.addRow(help_label)

        return widget

    def create_info_marker_options(self):
        """Create options for Info Marker action"""
        widget = QGroupBox("Info Marker on Graph")
        widget.setStyleSheet(GroupBoxStyles.compact())
        layout = QFormLayout(widget)
        
        self.marker_text_input = QLineEdit()
        self.marker_text_input.setPlaceholderText("Enter text for the graph event marker")
        
        layout.addRow("Marker Text:", self.marker_text_input)
        
        # Add a small help label
        help_label = QLabel("This text will appear on the graph as an event marker. Use {variable_name} or {sensor_name} for substitutions.")
        help_label.setStyleSheet("font-size: 9pt; color: gray;")
        help_label.setWordWrap(True)
        layout.addRow(help_label)

        return widget

    def create_jump_options(self):
        """Create options for Jump action"""
        widget = QGroupBox("Jump to Step")
        widget.setStyleSheet(GroupBoxStyles.compact())
        layout = QFormLayout(widget)
        
        self.jump_target = QSpinBox()
        self.jump_target.setRange(1, 100)
        self.jump_target.setPrefix("Step ")
        
        layout.addRow("Target Step:", self.jump_target)
        layout.addRow(QLabel("Note: Steps are 1-indexed in the UI."))
        
        return widget

    def create_condition_options(self):
        """Create options for Condition action"""
        widget = QGroupBox("Conditional Branching")
        widget.setStyleSheet(GroupBoxStyles.compact())
        layout = QFormLayout(widget)
        
        self.cond_expression = QLineEdit()
        self.cond_expression.setPlaceholderText("e.g., {temp} > 100")
        
        self.cond_true_target = QSpinBox()
        self.cond_true_target.setRange(1, 100)
        self.cond_true_target.setPrefix("Step ")
        
        self.cond_false_target = QSpinBox()
        self.cond_false_target.setRange(1, 100)
        self.cond_false_target.setPrefix("Step ")
        self.cond_false_target.setSpecialValueText("Continue (Next Step)")
        
        layout.addRow("Condition:", self.cond_expression)
        layout.addRow("If True, Jump to:", self.cond_true_target)
        layout.addRow("If False, Jump to:", self.cond_false_target)
        
        return widget
        
    def update_system_action_options(self):
        """Update the system action options based on the selected action type"""
        # Clear existing options
        while self.system_options_layout.count():
            item = self.system_options_layout.takeAt(0)
            widget_to_delete = item.widget()
            if widget_to_delete:
                widget_to_delete.deleteLater()
            # Also try taking layout item if it's a layout
            layout_item = item.layout()
            if layout_item:
                 # Properly delete widgets within the layout
                 while layout_item.count():
                     child = layout_item.takeAt(0)
                     if child.widget():
                         child.widget().deleteLater()

        
        action_type = self.system_action_type.currentText()
        
        if action_type == "display_message":
            # Message input
            self.message_title_input = QLineEdit()
            self.message_title_input.setPlaceholderText("Enter message title")
            self.message_title_input.setText("Automation Message")
            self.system_options_layout.addRow("Title:", self.message_title_input)
            
            self.message_input = QTextEdit()
            self.message_input.setPlaceholderText("Enter message to display")
            self.message_input.setMaximumHeight(100)
            self.system_options_layout.addRow("Message:", self.message_input)
            
        elif action_type == "play_sound":
            # Sound type selection
            self.sound_type = QComboBox()
            self.sound_type.addItems(["beep", "custom"])
            self.sound_type.currentTextChanged.connect(self.update_sound_options)
            self.system_options_layout.addRow("Sound Type:", self.sound_type)
            
            # Container for sound file selection (initially hidden)
            self.sound_file_container = QWidget()
            self.sound_file_layout = QHBoxLayout(self.sound_file_container)
            self.sound_file_layout.setContentsMargins(0, 0, 0, 0)
            
            self.sound_file_input = QLineEdit()
            self.sound_file_input.setPlaceholderText("Path to sound file (.wav)")
            self.sound_file_layout.addWidget(self.sound_file_input)
            
            self.browse_sound_btn = QPushButton("Browse...")
            self.browse_sound_btn.clicked.connect(self.browse_sound_file)
            self.sound_file_layout.addWidget(self.browse_sound_btn)
            
            self.system_options_layout.addRow("Sound File:", self.sound_file_container)
            
            # Initialize sound options
            self.update_sound_options()
    
    def update_sound_options(self):
        """Update sound options based on selected sound type"""
        if hasattr(self, 'sound_type'): # Ensure widgets exist
            sound_type = self.sound_type.currentText()
            self.sound_file_container.setVisible(sound_type == "custom")
    
    def browse_sound_file(self):
        """Open file dialog to browse for sound file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Sound File", "", "Sound Files (*.wav)"
        )
        if file_path:
            self.sound_file_input.setText(file_path)
        
    def update_action_options(self):
        """Update the visible action options based on selected type"""
        # Map action type text to tab index
        type_map = {
            "Send Arduino Command": 0,
            "Send LabJack Command": 1,
            "Send Serial Command": 2,
            "System Action": 3,
            "Set Variable": 4,
            "Info Marker": 5,
            "Jump to Step": 6,
            "Condition (If/Else Jump)": 7
        }
        action_text = self.action_type.currentText()
        index = type_map.get(action_text, 0) # Default to first tab if not found
        self.action_options.setCurrentIndex(index)
        
    def load_action(self, action):
        """Load values from an existing action"""
        self.action_name.setText(action.name)
        
        action_map = {
            ArduinoCommandAction: ("Send Arduino Command", self.arduino_command, "command"),
            LabJackCommandAction: ("Send LabJack Command", None, None), # Special handling
            SerialCommandAction: ("Send Serial Command", self.serial_command, "command"), # Port handling needed
            SystemAction: ("System Action", None, None), # Special handling
            SetVariableAction: ("Set Variable", None, None), # <<< Added, special handling
            InfoMarkerAction: ("Info Marker", None, None),
            JumpToStepAction: ("Jump to Step", None, None),
            ConditionAction: ("Condition (If/Else Jump)", None, None)
        }

        action_type_text = ""
        widget_to_set = None
        attribute_name = None

        for cls, (text, widget, attr) in action_map.items():
            if isinstance(action, cls):
                action_type_text = text
                widget_to_set = widget
                attribute_name = attr
                break

        if action_type_text:
            self.action_type.setCurrentText(action_type_text)
            self.update_action_options() # Make sure correct tab is visible

            if widget_to_set and attribute_name and hasattr(action, attribute_name):
                 if isinstance(widget_to_set, QLineEdit):
                     widget_to_set.setText(getattr(action, attribute_name))
                 elif isinstance(widget_to_set, QSpinBox) or isinstance(widget_to_set, QDoubleSpinBox):
                     widget_to_set.setValue(getattr(action, attribute_name))
                 # Add other widget types if needed

            # Special handling for complex actions
            if isinstance(action, LabJackCommandAction):
                self.labjack_channel.setCurrentText(action.channel)
                # Update value based on channel type
                channel_name = action.channel
                is_digital = any(prefix in channel_name.lower() for prefix in ["fio", "eio", "cio", "mio"]) 
                if is_digital:
                    self.labjack_value_digital.setCurrentIndex(1 if action.value == 1 else 0)
                else:
                    self.labjack_value_analog.setValue(action.value)
            elif isinstance(action, SerialCommandAction):
                 self.serial_port.setCurrentText(action.port) # Set port separately
                 self.serial_command.setText(action.command)
            elif isinstance(action, SystemAction):
                 self.system_action_type.setCurrentText(action.specific_action_type)
                 self.update_system_action_options() # Show correct sub-options
                 # Load specific parameters based on action type
                 if action.specific_action_type == "display_message" and hasattr(self, 'message_input'):
                     self.message_title_input.setText(action.parameters.get("title", "Automation Message"))
                     self.message_input.setText(action.parameters.get("message", ""))
                 elif action.specific_action_type == "play_sound" and hasattr(self, 'sound_type'):
                     sound_type = action.parameters.get("sound", "beep")
                     self.sound_type.setCurrentText(sound_type)
                     self.update_sound_options()
                     if sound_type == "custom" and hasattr(self, 'sound_file_input'):
                         self.sound_file_input.setText(action.parameters.get("file_path", ""))
            elif isinstance(action, SetVariableAction):
                 if hasattr(self, 'variable_name_input'):
                     self.variable_name_input.setText(action.variable_name)
                 if hasattr(self, 'variable_expression_input'):
                     self.variable_expression_input.setText(action.expression)
            elif isinstance(action, InfoMarkerAction):
                 if hasattr(self, 'marker_text_input'):
                     self.marker_text_input.setText(action.marker_text)
            elif isinstance(action, JumpToStepAction):
                self.jump_target.setValue(action.target_step_index + 1)
            elif isinstance(action, ConditionAction):
                self.cond_expression.setText(action.condition_expression)
                self.cond_true_target.setValue(action.if_true_step + 1)
                if action.if_false_step is not None:
                    self.cond_false_target.setValue(action.if_false_step + 1)
                else:
                    self.cond_false_target.setValue(0) # Special value for continue

        else:
             print(f"Warning: Could not load action of type {type(action).__name__}")


    def get_action(self):
        """Get the configured action"""
        name = self.action_name.text().strip() or "Unnamed Action"
        action_type = self.action_type.currentText()
        
        if action_type == "Send Arduino Command":
            command = self.arduino_command.text().strip()
            return ArduinoCommandAction(name, command)
            
        elif action_type == "Send LabJack Command":
            channel = self.labjack_channel.currentText().strip()
            
            # Determine value based on channel type visibility
            is_digital = self.labjack_value_digital.isVisible()
            if is_digital:
                value = 1 if self.labjack_value_digital.currentIndex() == 1 else 0
            else:
                value = self.labjack_value_analog.value()
                
            return LabJackCommandAction(name, channel, value)
            
        elif action_type == "Send Serial Command":
            port = self.serial_port.currentText().strip() # Use currentText for editable combo box
            command = self.serial_command.text().strip()
            return SerialCommandAction(name, port, command)
            
        elif action_type == "System Action":
            sys_action_type = self.system_action_type.currentText()
            params = {}
            if sys_action_type == "display_message":
                 params["title"] = self.message_title_input.text()
                 params["message"] = self.message_input.toPlainText() # Use toPlainText for QTextEdit
            elif sys_action_type == "play_sound":
                 sound_type = self.sound_type.currentText()
                 params["sound"] = sound_type
                 if sound_type == "custom":
                     params["file_path"] = self.sound_file_input.text()
            # No extra params needed for start/stop recording, snapshot

            # Ensure sys_action_type (e.g., "start_recording") is passed
            return SystemAction(name, sys_action_type, params)

        # <<< Added handling for SetVariableAction >>>
        elif action_type == "Set Variable":
             var_name = self.variable_name_input.text().strip()
             var_expression = self.variable_expression_input.text().strip()
             if not var_name:
                 QMessageBox.warning(self, "Missing Name", "Variable name cannot be empty.")
                 return None # Prevent accepting dialog
             return SetVariableAction(name, var_name, var_expression)

        elif action_type == "Info Marker":
            marker_text = self.marker_text_input.text().strip()
            return InfoMarkerAction(name, marker_text)

        elif action_type == "Jump to Step":
            target = self.jump_target.value() - 1
            return JumpToStepAction(name, target)
            
        elif action_type == "Condition (If/Else Jump)":
            expression = self.cond_expression.text().strip()
            true_target = self.cond_true_target.value() - 1
            false_target = self.cond_false_target.value() - 1
            
            if false_target < 0:
                false_target = None
                
            if not expression:
                 QMessageBox.warning(self, "Missing Condition", "Condition expression cannot be empty.")
                 return None
                 
            return ConditionAction(name, expression, true_target, false_target)
            
        return None


class StepDialog(QDialog):
    """Dialog for creating or editing an automation step"""
    def __init__(self, parent=None, step=None, sensors=None, available_ports=None, app_context=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Automation Step")
        self.resize(700, 500)
        self.setStyleSheet(DialogStyles.dark_dialog())
        self.step = step
        self.sensors = sensors or []
        self.available_ports = available_ports or []
        self.app_context = app_context
        
        # Initialize variables from step or None
        self.trigger = step.trigger if step else None
        self.action = step.action if step else None
        
        self.setup_ui()
        
        # Load step values if editing
        if step:
            self.load_step(step)
            
    def setup_ui(self):
        """Set up the dialog UI"""
        layout = QVBoxLayout(self)
        
        # Trigger configuration
        trigger_group = QGroupBox("Trigger (When)")
        trigger_group.setStyleSheet(GroupBoxStyles.default())
        trigger_layout = QVBoxLayout(trigger_group)
        
        # Trigger info display
        self.trigger_info = QLabel("No trigger configured")
        self.trigger_info.setWordWrap(True)
        trigger_layout.addWidget(self.trigger_info)
        
        # Trigger edit button
        self.edit_trigger_btn = QPushButton("Configure Trigger")
        self.edit_trigger_btn.clicked.connect(self.edit_trigger)
        trigger_layout.addWidget(self.edit_trigger_btn)
        
        layout.addWidget(trigger_group)
        
        # Action configuration
        action_group = QGroupBox("Action (Do)")
        action_group.setStyleSheet(GroupBoxStyles.default())
        action_layout = QVBoxLayout(action_group)
        
        # Action info display
        self.action_info = QLabel("No action configured")
        self.action_info.setWordWrap(True)
        action_layout.addWidget(self.action_info)
        
        # Action edit button
        self.edit_action_btn = QPushButton("Configure Action")
        self.edit_action_btn.clicked.connect(self.edit_action)
        action_layout.addWidget(self.edit_action_btn)
        
        layout.addWidget(action_group)
        
        # Enabled checkbox
        self.enabled_checkbox = QCheckBox("Step Enabled")
        self.enabled_checkbox.setChecked(True) # Default to enabled
        layout.addWidget(self.enabled_checkbox)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.ok_button)
        buttons_layout.addWidget(self.cancel_button)
        
        layout.addLayout(buttons_layout)

        # Update displays initially based on loaded step (if any)
        self.update_trigger_info()
        self.update_action_info()
        
    def edit_trigger(self):
        """Open dialog to edit trigger"""
        # Pass the current trigger (or None) to the dialog
        dialog = TriggerDialog(self, self.trigger, self.sensors)
        if dialog.exec():
            self.trigger = dialog.get_trigger()
            self.update_trigger_info()
            
    def edit_action(self):
        """Open dialog to edit action"""
        # Pass the current action (or None) and context to the dialog
        dialog = ActionDialog(self, self.action, self.available_ports, self.app_context)
        if dialog.exec():
            self.action = dialog.get_action()
            self.update_action_info()
            
    def update_trigger_info(self):
        """Update trigger info display"""
        if self.trigger and hasattr(self.trigger, 'name') and hasattr(self.trigger, 'description'):
            self.trigger_info.setText(f"<b>{self.trigger.name}</b>: {self.trigger.description}")
        else:
            self.trigger_info.setText("No trigger configured")
            
    def update_action_info(self):
        """Update action info display"""
        if self.action and hasattr(self.action, 'name') and hasattr(self.action, 'description'):
            self.action_info.setText(f"<b>{self.action.name}</b>: {self.action.description}")
        else:
            self.action_info.setText("No action configured")
            
    def load_step(self, step):
        """Load values from an existing step"""
        # Already set in __init__
        # self.trigger = step.trigger
        # self.action = step.action
        self.enabled_checkbox.setChecked(step.enabled)
        
        self.update_trigger_info()
        self.update_action_info()
        
    def get_step(self):
        """Get the configured step"""
        if not self.trigger:
            QMessageBox.warning(self, "Missing Trigger", "Please configure a trigger for this step.")
            return None
            
        if not self.action:
            QMessageBox.warning(self, "Missing Action", "Please configure an action for this step.")
            return None
            
        # Create a new AutomationStep instance
        return AutomationStep(
            self.trigger,
            self.action,
            self.enabled_checkbox.isChecked()
        )


class SequenceDialog(QDialog):
    """Dialog for creating or editing an automation sequence"""
    def __init__(self, parent=None, sequence=None, sensors=None, available_ports=None, app_context=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Automation Sequence")
        self.resize(800, 600)
        self.setStyleSheet(DialogStyles.dark_dialog())
        
        # Store context needed by StepDialog
        self.sensors = sensors or []
        self.available_ports = available_ports or []
        self.app_context = app_context
        
        # Use a copy of the steps if editing, otherwise start fresh
        if sequence and hasattr(sequence, 'steps'):
            self.steps = sequence.steps.copy() 
        else:
            self.steps = []
            
        self.original_sequence = sequence # Keep track for editing/saving
        
        self.setup_ui()
        
        # Load sequence data if editing
        if sequence:
            self.load_sequence(sequence)
        else:
             # Ensure table is updated even for new sequences
             self.update_steps_table()

            
    def setup_ui(self):
        """Set up the dialog UI"""
        layout = QVBoxLayout(self)
        
        # Sequence name
        name_layout = QFormLayout()
        self.sequence_name = QLineEdit()
        self.sequence_name.setPlaceholderText("Enter a name for this sequence")
        name_layout.addRow("Sequence Name:", self.sequence_name)
        
        # Loop checkbox
        self.loop_checkbox = QCheckBox("Loop Sequence (Restart from beginning when complete)")
        name_layout.addRow("", self.loop_checkbox)
        
        layout.addLayout(name_layout)
        
        # Steps list
        steps_group = QGroupBox("Sequence Steps")
        steps_group.setStyleSheet(GroupBoxStyles.elevated())
        steps_layout = QVBoxLayout(steps_group)

        self.steps_table = QTableWidget()
        self.steps_table.setColumnCount(4)
        self.steps_table.setHorizontalHeaderLabels(["#", "Trigger", "Action", "Enabled"])
        self.steps_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.steps_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.steps_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.steps_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.steps_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.steps_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection) # Only one row selectable
        self.steps_table.verticalHeader().setVisible(False)
        self.steps_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers) # Don't allow editing in table
        self.steps_table.itemSelectionChanged.connect(self.update_button_states) # Enable/disable buttons
        # Connect double-click to edit step
        self.steps_table.cellDoubleClicked.connect(self._on_step_double_clicked)

        steps_layout.addWidget(self.steps_table)
        
        # Step editing buttons
        buttons_layout = QHBoxLayout()
        
        self.add_step_btn = QPushButton("Add Step")
        self.add_step_btn.clicked.connect(self.add_step)
        
        self.edit_step_btn = QPushButton("Edit Step")
        self.edit_step_btn.clicked.connect(self.edit_step)
        
        self.delete_step_btn = QPushButton("Delete Step")
        self.delete_step_btn.clicked.connect(self.delete_step)
        
        self.move_up_btn = QPushButton("Move Up")
        self.move_up_btn.clicked.connect(self.move_step_up)
        
        self.move_down_btn = QPushButton("Move Down")
        self.move_down_btn.clicked.connect(self.move_step_down)
        
        buttons_layout.addWidget(self.add_step_btn)
        buttons_layout.addWidget(self.edit_step_btn)
        buttons_layout.addWidget(self.delete_step_btn)
        buttons_layout.addStretch() # Add space
        buttons_layout.addWidget(self.move_up_btn)
        buttons_layout.addWidget(self.move_down_btn)
        
        steps_layout.addLayout(buttons_layout)
        layout.addWidget(steps_group)
        
        # Dialog buttons
        dialog_buttons = QHBoxLayout()
        
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        
        dialog_buttons.addStretch()
        dialog_buttons.addWidget(self.ok_button)
        dialog_buttons.addWidget(self.cancel_button)
        
        layout.addLayout(dialog_buttons)
        
        # Initialize button states
        self.update_button_states()

    def update_button_states(self):
        """Enable/disable buttons based on selection and list size"""
        selected_row = self.get_selected_row()
        has_selection = selected_row is not None
        num_steps = len(self.steps)

        self.edit_step_btn.setEnabled(has_selection)
        self.delete_step_btn.setEnabled(has_selection)
        self.move_up_btn.setEnabled(has_selection and selected_row > 0)
        self.move_down_btn.setEnabled(has_selection and selected_row < num_steps - 1)

    def get_selected_row(self):
        """Get the index of the currently selected row, or None"""
        selected_items = self.steps_table.selectedItems()
        if selected_items:
            return selected_items[0].row()
        return None
        
    def update_steps_table(self):
        """Update the steps table with current steps"""
        current_row = self.get_selected_row() # Preserve selection if possible

        self.steps_table.setRowCount(len(self.steps))
        
        for i, step in enumerate(self.steps):
            # Step number
            item_num = QTableWidgetItem(str(i + 1))
            item_num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.steps_table.setItem(i, 0, item_num)
            
            # Trigger
            trigger_text = "N/A"
            if step and step.trigger:
                trigger_text = f"{step.trigger.name}: {step.trigger.description}"
            self.steps_table.setItem(i, 1, QTableWidgetItem(trigger_text))
            
            # Action
            action_text = "N/A"
            if step and step.action:
                action_text = f"{step.action.name}: {step.action.description}"
            self.steps_table.setItem(i, 2, QTableWidgetItem(action_text))
            
            # Enabled
            enabled_text = "N/A"
            if step:
               enabled_text = "Yes" if step.enabled else "No"
            enabled_item = QTableWidgetItem(enabled_text)
            enabled_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.steps_table.setItem(i, 3, enabled_item)
            
        # Restore selection if valid
        if current_row is not None and current_row < len(self.steps):
             self.steps_table.selectRow(current_row)
        else:
             self.steps_table.clearSelection() # Clear if previous selection invalid

        self.update_button_states() # Update buttons after table change
        
    def add_step(self):
        """Add a new step"""
        # Pass context to StepDialog
        dialog = StepDialog(self, None, self.sensors, self.available_ports, self.app_context)
        if dialog.exec():
            step = dialog.get_step()
            if step:
                self.steps.append(step)
                self.update_steps_table()
                self.steps_table.selectRow(len(self.steps) - 1) # Select the new row
            else:
                # Error message shown in StepDialog.get_step()
                pass 
            
    def edit_step(self):
        """Edit the selected step"""
        row = self.get_selected_row()
        if row is None:
             QMessageBox.information(self, "Select Step", "Please select a step to edit.")
             return
            
        if 0 <= row < len(self.steps):
            # Pass the selected step and context to StepDialog
            dialog = StepDialog(self, self.steps[row], self.sensors, self.available_ports, self.app_context)
            if dialog.exec():
                updated_step = dialog.get_step()
                if updated_step:
                    self.steps[row] = updated_step
                    self.update_steps_table()
                    # Re-select the edited row
                    self.steps_table.selectRow(row)
                else:
                     # Error message shown in StepDialog.get_step()
                     pass
        else:
             print(f"Error: Invalid row index {row} for editing.")

                    
    def delete_step(self):
        """Delete the selected step"""
        row = self.get_selected_row()
        if row is None:
             QMessageBox.information(self, "Select Step", "Please select a step to delete.")
             return

        if 0 <= row < len(self.steps):
            reply = QMessageBox.question(self, "Confirm Delete", 
                                        f"Are you sure you want to delete step {row + 1}?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                del self.steps[row]
                self.update_steps_table()
        else:
            print(f"Error: Invalid row index {row} for deletion.")
            
    def move_step_up(self):
        """Move the selected step up"""
        row = self.get_selected_row()
        if row is not None and 0 < row < len(self.steps):
            self.steps[row], self.steps[row-1] = self.steps[row-1], self.steps[row]
            self.update_steps_table()
            self.steps_table.selectRow(row - 1) # Select the moved item
            
    def move_step_down(self):
        """Move the selected step down"""
        row = self.get_selected_row()
        if row is not None and 0 <= row < len(self.steps) - 1:
            self.steps[row], self.steps[row+1] = self.steps[row+1], self.steps[row]
            self.update_steps_table()
            self.steps_table.selectRow(row + 1) # Select the moved item
    
    def _on_step_double_clicked(self, row, column):
        """Handle double-click on a step row to open it in edit mode."""
        if 0 <= row < len(self.steps):
            # Select the row first
            self.steps_table.selectRow(row)
            # Then edit the step
            self.edit_step()
            
    def load_sequence(self, sequence):
        """Load values from an existing sequence"""
        self.sequence_name.setText(sequence.name)
        self.loop_checkbox.setChecked(sequence.loop)
        # Steps are already loaded in __init__
        # self.steps = sequence.steps.copy() 
        self.update_steps_table()
        
    def get_sequence(self):
        """Get the configured sequence"""
        name = self.sequence_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing Name", "Please enter a name for the sequence.")
            return None
            
        if not self.steps:
             QMessageBox.warning(self, "No Steps", "Please add at least one step to the sequence.")
             return None

        # If we were editing an existing sequence, return the modified original
        if self.original_sequence:
             self.original_sequence.name = name
             self.original_sequence.steps = self.steps.copy()
             self.original_sequence.loop = self.loop_checkbox.isChecked()
             return self.original_sequence
        else:
             # Otherwise, create a new sequence object
             new_sequence = AutomationSequence(name, self.steps.copy())
             new_sequence.loop = self.loop_checkbox.isChecked()
             return new_sequence 