"""
Automation Models

Defines the core data structures for automation triggers, actions, steps, and sequences.
"""
import time
import datetime
import json
import os
import traceback
from PyQt6.QtCore import QObject, QTimer, pyqtSignal, QThreadPool, QRunnable
from enum import Enum

# --- Triggers ---
class TriggerType(Enum):
    TIME_DURATION = 1
    TIME_SPECIFIC = 2
    SENSOR_VALUE = 3
    EVENT = 4
    OPTICAL_EVENT = 5  # For optical sensor events (light detection, fill level, etc.)
    AUDIO_EVENT = 6  # For audio sensor events (frequency, level, etc.)
    COMPOUND = 7  # Combined triggers (AND/OR)

class BaseTrigger(QObject):
    triggered = pyqtSignal(object) # Signal when trigger condition is met

    def __init__(self, name, trigger_type):
        super().__init__()
        self.name = name
        self.trigger_type = trigger_type
        self.description = "Base Trigger" # Provide a default description

    def check(self, context): # context might contain sensor values, events, etc.
        """Check if the trigger condition is met."""
        raise NotImplementedError
    
    def reset(self):
        """Reset trigger state (called when sequence starts or loops)"""
        pass
    
    def cleanup(self):
        """Clean up any resources or disconnect signals."""
        pass
    
    def to_dict(self):
        """Serialize trigger to a dictionary"""
        return {
            'type': self.trigger_type.name,
            'name': self.name
            # Subclasses will add their specific attributes
        }

    @staticmethod
    def from_dict(data):
        """Deserialize trigger from a dictionary"""
        trigger_type_name = data.get('type')
        name = data.get('name')
        
        if trigger_type_name == TriggerType.TIME_DURATION.name:
            return TimeDurationTrigger.from_dict(data)
        elif trigger_type_name == TriggerType.TIME_SPECIFIC.name:
            return TimeSpecificTrigger.from_dict(data)
        elif trigger_type_name == TriggerType.SENSOR_VALUE.name:
            return SensorValueTrigger.from_dict(data)
        elif trigger_type_name == TriggerType.EVENT.name:
            return EventTrigger.from_dict(data)
        elif trigger_type_name == TriggerType.OPTICAL_EVENT.name:
            return OpticalEventTrigger.from_dict(data)
        elif trigger_type_name == TriggerType.AUDIO_EVENT.name:
            return AudioEventTrigger.from_dict(data)
        elif trigger_type_name == TriggerType.COMPOUND.name:
            return CompoundTrigger.from_dict(data)
        else:
            raise ValueError(f"Unknown trigger type: {trigger_type_name}")
            

class TimeDurationTrigger(BaseTrigger):
    def __init__(self, name, minutes, seconds):
        super().__init__(name, TriggerType.TIME_DURATION)
        self.minutes = int(minutes)
        self.seconds = int(seconds)
        self.duration = self.minutes * 60 + self.seconds
        self.start_time = None
        self.description = f"Wait for {self.minutes}m {self.seconds}s"
        
    def start(self):
        """Record the start time when the step begins."""
        self.start_time = time.monotonic()
        print(f"TimeDurationTrigger started: {self.description}, duration={self.duration}s, start_time={self.start_time}")
        
    def reset(self):
        self.start_time = None
        
    def check(self, context=None): # Context not strictly needed here
        if self.start_time is None:
            # Start time hasn't been set - this is normal when the step just became active
            self.start_time = time.monotonic()
            print(f"[Automation] TimeDurationTrigger '{self.name}' started. Target: {self.duration}s")
            return False # Don't trigger immediately
            
        elapsed = time.monotonic() - self.start_time
        is_triggered = elapsed >= self.duration
        
        # Add clean debug output every 5 seconds
        if self.duration >= 5:
            current_sec = int(elapsed)
            if current_sec % 5 == 0 and current_sec > 0:
                if not hasattr(self, '_last_log_sec') or self._last_log_sec != current_sec:
                    self._last_log_sec = current_sec
                    remaining = max(0, self.duration - elapsed)
                    print(f"[Automation] TimeDurationTrigger '{self.name}': {elapsed:.1f}s / {self.duration}s ({remaining:.1f}s remaining)")
        
        if is_triggered:
            print(f"[Automation] TimeDurationTrigger '{self.name}' triggered after {elapsed:.1f}s")
            
        return is_triggered
        
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'minutes': self.minutes,
            'seconds': self.seconds
        })
        return data

    @staticmethod
    def from_dict(data):
        return TimeDurationTrigger(data['name'], data['minutes'], data['seconds'])

class TimeSpecificTrigger(BaseTrigger):
    def __init__(self, name, hour, minute):
        super().__init__(name, TriggerType.TIME_SPECIFIC)
        self.hour = int(hour)
        self.minute = int(minute)
        self.triggered_today = False
        self.description = f"At time {self.hour:02d}:{self.minute:02d}"
        
    def reset(self):
        self.triggered_today = False
        self._armed_today = False
        if hasattr(self, '_last_check_date'):
            delattr(self, '_last_check_date')

    def check(self, context=None): # Context not needed
        now = datetime.datetime.now()
        current_time = now.time()
        target_time = datetime.time(self.hour, self.minute)
        
        # Reset flags if the day has changed
        if hasattr(self, '_last_check_date') and self._last_check_date != now.date():
            self.triggered_today = False
            self._armed_today = False
        self._last_check_date = now.date()

        # Check if current time is at or past the target time
        if current_time >= target_time:
            if not self.triggered_today:
                # We only trigger if we were "armed" (i.e., we have seen a time 
                # BEFORE the target time today). This prevents immediate 
                # triggering if the sequence is started after the target time.
                if hasattr(self, '_armed_today') and self._armed_today:
                    self.triggered_today = True
                    return True
                else:
                    # Already past the target time for today, wait for tomorrow
                    self.triggered_today = True 
                    print(f"[Automation] TimeSpecificTrigger '{self.name}' ({self.hour:02d}:{self.minute:02d}) already passed for today. Waiting for tomorrow.")
                    return False
        else:
            # We are currently before the target time today, so we are "armed" 
            # to trigger when the time is reached.
            self._armed_today = True
            self.triggered_today = False 
            
        return False

    def to_dict(self):
        data = super().to_dict()
        data.update({
            'hour': self.hour,
            'minute': self.minute
        })
        return data

    @staticmethod
    def from_dict(data):
        return TimeSpecificTrigger(data['name'], data['hour'], data['minute'])

class SensorValueTrigger(BaseTrigger):
    def __init__(self, name, sensor_name, operator, threshold, hysteresis=0.0):
        super().__init__(name, TriggerType.SENSOR_VALUE)
        self.sensor_name = str(sensor_name) # Ensure it's a string
        self.operator = str(operator)
        self.threshold = float(threshold)
        self.hysteresis = float(hysteresis)
        self._last_state = False # Track if it was previously triggered
        self._last_trigger_time = 0 # Prevent rapid fire
        self.trigger_cooldown = 1.0 # Minimum 1.0s between triggers
        
        self.description = f"When {self.sensor_name} {self.operator} {self.threshold}"
        if self.hysteresis > 0:
            self.description += f" (hyst: {self.hysteresis})"
        
    def reset(self):
        """Reset trigger state (called when sequence starts)"""
        self._last_state = False
        self._last_trigger_time = 0
        
    def check(self, context):
        if context is None or 'sensors' not in context:
            return False
            
        sensor_value = context['sensors'].get(self.sensor_name) 
        if sensor_value is None:
            return False # Sensor not found or value unavailable
            
        try:
            current_value = float(sensor_value)
        except (ValueError, TypeError):
            return False # Cannot compare if value is not a number
            
        # Evaluate condition with hysteresis
        # If we were triggered, we stay triggered until we cross (threshold -/+ hysteresis)
        triggered = False
        if self.operator == '>':
            if not self._last_state:
                triggered = current_value > self.threshold
            else:
                triggered = current_value > (self.threshold - self.hysteresis)
        elif self.operator == '<':
            if not self._last_state:
                triggered = current_value < self.threshold
            else:
                triggered = current_value < (self.threshold + self.hysteresis)
        elif self.operator == '==':
            triggered = abs(current_value - self.threshold) < (1e-6 + self.hysteresis)
        elif self.operator == '>=':
            if not self._last_state:
                triggered = current_value >= self.threshold
            else:
                triggered = current_value >= (self.threshold - self.hysteresis)
        elif self.operator == '<=':
            if not self._last_state:
                triggered = current_value <= self.threshold
            else:
                triggered = current_value <= (self.threshold + self.hysteresis)
        
        # --- Update Hysteresis State ---
        # We update _last_state as soon as the condition is met, 
        # even if we don't fire the action due to cooldown.
        prev_state = self._last_state
        self._last_state = triggered

        if triggered:
            # Only log on the initial transition to triggered state
            if not prev_state:
                print(f"[AUTOMATION] Trigger '{self.name}' entered ACTIVE state for sensor '{self.sensor_name}' (value: {current_value:.2f}, threshold: {self.threshold})")

            # Debounce/Cooldown logic for the ACTION (the True return value)
            now = time.time()
            if now - self._last_trigger_time < self.trigger_cooldown:
                # Still in cooldown, condition is met but don't fire action yet
                return False
            
            self._last_trigger_time = now
            return True
        else:
            if prev_state:
                print(f"[AUTOMATION] Trigger '{self.name}' reset to INACTIVE state (sensor '{self.sensor_name}' value: {current_value:.2f}, threshold: {self.threshold})")
            return False
            
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'sensor_name': self.sensor_name,
            'operator': self.operator,
            'threshold': self.threshold,
            'hysteresis': self.hysteresis
        })
        return data

    @staticmethod
    def from_dict(data):
        return SensorValueTrigger(
            data['name'], 
            data['sensor_name'], 
            data['operator'], 
            data['threshold'],
            data.get('hysteresis', 0.0)
        )

class EventTrigger(BaseTrigger):
    def __init__(self, name, event_type):
        super().__init__(name, TriggerType.EVENT)
        self.event_type = str(event_type)
        self.description = f"On event: {self.event_type}"
        self.triggered_event = False # Flag to trigger only once per event occurrence
        
    def reset(self):
        self.triggered_event = False

    def check(self, context):
        if context is None or 'events' not in context:
            return False
            
        # Check if the specific event occurred recently
        if self.event_type in context['events']:
            if not self.triggered_event:
                self.triggered_event = True # Set flag
                return True
        else:
            # Reset the flag if the event is no longer in the current context
            self.triggered_event = False
             
        return False
        
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'event_type': self.event_type
        })
        return data

    @staticmethod
    def from_dict(data):
        return EventTrigger(data['name'], data['event_type'])


class OpticalEventTrigger(BaseTrigger):
    """Trigger for optical sensor events (light detection, fill level changes, etc.)"""
    
    # Available event types for optical sensors
    EVENT_TYPES = {
        'light_event': 'Light Event Detected',
        'brightness_above': 'Brightness Above Threshold',
        'brightness_below': 'Brightness Below Threshold',
        'fill_level_above': 'Fill Level Above Threshold',
        'fill_level_below': 'Fill Level Below Threshold',
        'particle_count_above': 'Particle Count Above Threshold',
        'color_detected': 'Target Color Detected',
        'position_changed': 'Position Changed Significantly',
    }
    
    def __init__(self, name, sensor_name, event_type, threshold=None, threshold_percent=None):
        super().__init__(name, TriggerType.OPTICAL_EVENT)
        self.sensor_name = str(sensor_name)
        self.event_type = str(event_type)
        self.threshold = float(threshold) if threshold is not None else None
        self.threshold_percent = float(threshold_percent) if threshold_percent is not None else None
        self._last_event_count = 0
        self._last_position = None
        self._triggered = False
        
        # Build description
        if event_type == 'light_event':
            self.description = f"When {sensor_name} detects light event"
        elif 'above' in event_type:
            self.description = f"When {sensor_name} {event_type.replace('_', ' ')} {threshold or threshold_percent}{'%' if threshold_percent else ''}"
        elif 'below' in event_type:
            self.description = f"When {sensor_name} {event_type.replace('_', ' ')} {threshold or threshold_percent}{'%' if threshold_percent else ''}"
        else:
            self.description = f"When {sensor_name}: {self.EVENT_TYPES.get(event_type, event_type)}"
    
    def check(self, context):
        """Check if the optical event condition is met"""
        if context is None:
            return False
        
        # Get optical sensor data from context
        optical_data = context.get('optical_sensors', {})
        sensor_data = optical_data.get(self.sensor_name, {})
        
        if not sensor_data:
            # Fallback: Check regular sensor values
            sensors = context.get('sensors', {})
            sensor_value = sensors.get(self.sensor_name)
            if sensor_value is not None:
                sensor_data = {'value': sensor_value}
        
        if not sensor_data:
            return False
        
        # Check based on event type
        if self.event_type == 'light_event':
            # Check if a new light event was detected
            event_count = sensor_data.get('event_count', 0)
            if event_count > self._last_event_count:
                self._last_event_count = event_count
                return True
            return False
        
        elif self.event_type == 'brightness_above':
            brightness = sensor_data.get('brightness_mean', sensor_data.get('value', 0))
            threshold = self.threshold if self.threshold is not None else 128
            if brightness > threshold and not self._triggered:
                self._triggered = True
                return True
            elif brightness <= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'brightness_below':
            brightness = sensor_data.get('brightness_mean', sensor_data.get('value', 255))
            threshold = self.threshold if self.threshold is not None else 128
            if brightness < threshold and not self._triggered:
                self._triggered = True
                return True
            elif brightness >= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'fill_level_above':
            fill_level = sensor_data.get('fill_level', 0)
            threshold = self.threshold_percent if self.threshold_percent is not None else 80
            if fill_level > threshold and not self._triggered:
                self._triggered = True
                return True
            elif fill_level <= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'fill_level_below':
            fill_level = sensor_data.get('fill_level', 100)
            threshold = self.threshold_percent if self.threshold_percent is not None else 20
            if fill_level < threshold and not self._triggered:
                self._triggered = True
                return True
            elif fill_level >= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'particle_count_above':
            count = sensor_data.get('particle_count', 0)
            threshold = self.threshold if self.threshold is not None else 10
            if count > threshold and not self._triggered:
                self._triggered = True
                return True
            elif count <= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'color_detected':
            color_percent = sensor_data.get('target_color_percent', 0)
            threshold = self.threshold_percent if self.threshold_percent is not None else 10
            if color_percent > threshold and not self._triggered:
                self._triggered = True
                return True
            elif color_percent <= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'position_changed':
            x = sensor_data.get('position_x_percent', 50)
            y = sensor_data.get('position_y_percent', 50)
            threshold = self.threshold_percent if self.threshold_percent is not None else 10
            
            if self._last_position is None:
                self._last_position = (x, y)
                return False
            
            # Calculate distance moved
            dx = abs(x - self._last_position[0])
            dy = abs(y - self._last_position[1])
            distance = (dx**2 + dy**2) ** 0.5
            
            if distance > threshold:
                self._last_position = (x, y)
                return True
            return False
        
        return False
    
    def reset(self):
        """Reset trigger state"""
        self._last_event_count = 0
        self._last_position = None
        self._triggered = False
    
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'sensor_name': self.sensor_name,
            'event_type': self.event_type,
            'threshold': self.threshold,
            'threshold_percent': self.threshold_percent
        })
        return data
    
    @staticmethod
    def from_dict(data):
        return OpticalEventTrigger(
            data['name'],
            data['sensor_name'],
            data['event_type'],
            data.get('threshold'),
            data.get('threshold_percent')
        )


class AudioEventTrigger(BaseTrigger):
    """Trigger for audio sensor events (frequency changes, level thresholds, etc.)"""
    
    # Available event types for audio sensors
    EVENT_TYPES = {
        'rms_above': 'RMS Level Above Threshold',
        'rms_below': 'RMS Level Below Threshold',
        'peak_above': 'Peak Amplitude Above Threshold',
        'peak_below': 'Peak Amplitude Below Threshold',
        'frequency_above': 'Frequency Above Threshold',
        'frequency_below': 'Frequency Below Threshold',
        'frequency_stable': 'Frequency Stable (within range)',
        'frequency_unstable': 'Frequency Unstable (outside range)',
        'db_above': 'dB Level Above Threshold',
        'db_below': 'dB Level Below Threshold',
        'band_energy_above': 'Band Energy Above Threshold',
        'band_energy_below': 'Band Energy Below Threshold',
    }
    
    def __init__(self, name, sensor_name, event_type, threshold=None, threshold_percent=None):
        super().__init__(name, TriggerType.AUDIO_EVENT)
        self.sensor_name = str(sensor_name)
        self.event_type = str(event_type)
        self.threshold = float(threshold) if threshold is not None else None
        self.threshold_percent = float(threshold_percent) if threshold_percent is not None else None
        self._triggered = False
        self._last_frequency = None
        self._frequency_stability_window = []
        
        # Build description
        if 'above' in event_type:
            self.description = f"When {sensor_name} {event_type.replace('_', ' ')} {threshold or threshold_percent}{'%' if threshold_percent else ''}"
        elif 'below' in event_type:
            self.description = f"When {sensor_name} {event_type.replace('_', ' ')} {threshold or threshold_percent}{'%' if threshold_percent else ''}"
        elif 'stable' in event_type or 'unstable' in event_type:
            threshold_str = f" (range: ±{threshold or threshold_percent}{'%' if threshold_percent else ' Hz'})"
            self.description = f"When {sensor_name}: {self.EVENT_TYPES.get(event_type, event_type)}{threshold_str}"
        else:
            self.description = f"When {sensor_name}: {self.EVENT_TYPES.get(event_type, event_type)}"
    
    def check(self, context):
        """Check if the audio event condition is met"""
        if context is None:
            return False
        
        # Get audio sensor data from context
        audio_data = context.get('audio_sensors', {})
        sensor_data = audio_data.get(self.sensor_name, {})
        
        if not sensor_data:
            # Fallback: Check regular sensor values
            sensors = context.get('sensors', {})
            sensor_value = sensors.get(self.sensor_name)
            if sensor_value is not None:
                sensor_data = {'value': sensor_value}
        
        if not sensor_data:
            return False
        
        # Check based on event type
        if self.event_type == 'rms_above':
            rms = sensor_data.get('rms', sensor_data.get('value', 0))
            threshold = self.threshold if self.threshold is not None else 0.5
            if rms > threshold and not self._triggered:
                self._triggered = True
                return True
            elif rms <= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'rms_below':
            rms = sensor_data.get('rms', sensor_data.get('value', 0))
            threshold = self.threshold if self.threshold is not None else 0.1
            if rms < threshold and not self._triggered:
                self._triggered = True
                return True
            elif rms >= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'peak_above':
            peak = sensor_data.get('peak', sensor_data.get('peak_hold', sensor_data.get('value', 0)))
            threshold = self.threshold if self.threshold is not None else 0.8
            if peak > threshold and not self._triggered:
                self._triggered = True
                return True
            elif peak <= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'peak_below':
            peak = sensor_data.get('peak', sensor_data.get('peak_hold', sensor_data.get('value', 0)))
            threshold = self.threshold if self.threshold is not None else 0.2
            if peak < threshold and not self._triggered:
                self._triggered = True
                return True
            elif peak >= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'frequency_above':
            freq = sensor_data.get('dominant_frequency', sensor_data.get('value', 0))
            threshold = self.threshold if self.threshold is not None else 1000
            if freq > threshold and not self._triggered:
                self._triggered = True
                return True
            elif freq <= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'frequency_below':
            freq = sensor_data.get('dominant_frequency', sensor_data.get('value', 0))
            threshold = self.threshold if self.threshold is not None else 100
            if freq < threshold and not self._triggered:
                self._triggered = True
                return True
            elif freq >= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'frequency_stable':
            freq = sensor_data.get('dominant_frequency', sensor_data.get('value', 0))
            if freq == 0:
                return False
            
            # Track frequency in a window
            self._frequency_stability_window.append(freq)
            if len(self._frequency_stability_window) > 10:
                self._frequency_stability_window.pop(0)
            
            if len(self._frequency_stability_window) < 5:
                return False
            
            # Calculate stability (std dev)
            import numpy as np
            freq_std = np.std(self._frequency_stability_window)
            threshold = self.threshold if self.threshold is not None else 5.0  # Hz
            
            if freq_std <= threshold and not self._triggered:
                self._triggered = True
                return True
            elif freq_std > threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'frequency_unstable':
            freq = sensor_data.get('dominant_frequency', sensor_data.get('value', 0))
            if freq == 0:
                return False
            
            # Track frequency in a window
            self._frequency_stability_window.append(freq)
            if len(self._frequency_stability_window) > 10:
                self._frequency_stability_window.pop(0)
            
            if len(self._frequency_stability_window) < 5:
                return False
            
            # Calculate stability (std dev)
            import numpy as np
            freq_std = np.std(self._frequency_stability_window)
            threshold = self.threshold if self.threshold is not None else 10.0  # Hz
            
            if freq_std > threshold and not self._triggered:
                self._triggered = True
                return True
            elif freq_std <= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'db_above':
            db_level = sensor_data.get('db_level', sensor_data.get('value', -60))
            threshold = self.threshold if self.threshold is not None else -20
            if db_level > threshold and not self._triggered:
                self._triggered = True
                return True
            elif db_level <= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'db_below':
            db_level = sensor_data.get('db_level', sensor_data.get('value', -60))
            threshold = self.threshold if self.threshold is not None else -40
            if db_level < threshold and not self._triggered:
                self._triggered = True
                return True
            elif db_level >= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'band_energy_above':
            band_energy = sensor_data.get('band_energy', sensor_data.get('value', 0))
            threshold = self.threshold if self.threshold is not None else 0.5
            if band_energy > threshold and not self._triggered:
                self._triggered = True
                return True
            elif band_energy <= threshold:
                self._triggered = False
            return False
        
        elif self.event_type == 'band_energy_below':
            band_energy = sensor_data.get('band_energy', sensor_data.get('value', 0))
            threshold = self.threshold if self.threshold is not None else 0.1
            if band_energy < threshold and not self._triggered:
                self._triggered = True
                return True
            elif band_energy >= threshold:
                self._triggered = False
            return False
        
        return False
    
    def reset(self):
        """Reset trigger state"""
        self._triggered = False
        self._last_frequency = None
        self._frequency_stability_window = []
    
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'sensor_name': self.sensor_name,
            'event_type': self.event_type,
            'threshold': self.threshold,
            'threshold_percent': self.threshold_percent
        })
        return data
    
    @staticmethod
    def from_dict(data):
        # Validate required fields
        if 'name' not in data:
            raise ValueError("Missing 'name' in AudioEventTrigger data")
        if 'sensor_name' not in data:
            raise ValueError("Missing 'sensor_name' in AudioEventTrigger data")
        if 'event_type' not in data:
            raise ValueError("Missing 'event_type' in AudioEventTrigger data")
        
        return AudioEventTrigger(
            data['name'],
            data['sensor_name'],
            data['event_type'],
            data.get('threshold'),
            data.get('threshold_percent')
        )

class CompoundTrigger(BaseTrigger):
    def __init__(self, name, triggers=None, logic='AND'):
        super().__init__(name, TriggerType.COMPOUND)
        self.triggers = triggers if triggers else []
        self.logic = logic # 'AND' or 'OR'
        self.description = f"{self.logic} of {len(self.triggers)} triggers"
        
    def check(self, context):
        if not self.triggers:
            return False
            
        results = [t.check(context) for t in self.triggers]
        
        if self.logic == 'AND':
            return all(results)
        else:
            return any(results)
            
    def reset(self):
        for t in self.triggers:
            t.reset()

    def cleanup(self):
        for t in self.triggers:
            t.cleanup()
            
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'logic': self.logic,
            'triggers': [t.to_dict() for t in self.triggers]
        })
        return data

    @staticmethod
    def from_dict(data):
        triggers = [BaseTrigger.from_dict(t_data) for t_data in data.get('triggers', [])]
        return CompoundTrigger(data['name'], triggers, data.get('logic', 'AND'))


# --- Actions ---
class ActionType(Enum):
    ARDUINO_COMMAND = 1
    LABJACK_COMMAND = 2
    SERIAL_COMMAND = 3
    SYSTEM_ACTION = 4
    SET_VARIABLE = 5 # Added for variable support
    JUMP_TO_STEP = 6 # Added for branching
    CONDITION = 7 # Added for conditional branching
    MQTT_PUBLISH = 8 # Added for MQTT support
    INFO_MARKER = 9 # Added for info markers on graph

class BaseAction(QObject):
    action_completed = pyqtSignal(object) # Signal when action is done
    action_failed = pyqtSignal(object, str) # Signal on failure (self, reason)

    def __init__(self, name, action_type):
        super().__init__()
        self.name = name
        self.action_type = action_type
        self.description = "Base Action"
        self.is_async = False # Whether to run in a separate thread
        self.last_image_path = None # Store path of any image created by this action

    def execute(self, context): # context provides access to interfaces (arduino, labjack, etc.)
        """Execute the action."""
        raise NotImplementedError
        
    def cleanup(self):
        """Clean up any resources or disconnect signals."""
        pass

    def to_dict(self):
        """Serialize action to a dictionary"""
        return {
            'type': self.action_type.name,
            'name': self.name
            # Subclasses add their specific attributes
        }

    @staticmethod
    def from_dict(data):
        """Deserialize action from a dictionary"""
        action_type_name = data.get('type')
        
        if action_type_name == ActionType.ARDUINO_COMMAND.name:
            return ArduinoCommandAction.from_dict(data)
        elif action_type_name == ActionType.LABJACK_COMMAND.name:
            return LabJackCommandAction.from_dict(data)
        elif action_type_name == ActionType.SERIAL_COMMAND.name:
            return SerialCommandAction.from_dict(data)
        elif action_type_name == ActionType.SYSTEM_ACTION.name:
            return SystemAction.from_dict(data)
        elif action_type_name == ActionType.SET_VARIABLE.name:
            return SetVariableAction.from_dict(data)
        elif action_type_name == ActionType.JUMP_TO_STEP.name:
            return JumpToStepAction.from_dict(data)
        elif action_type_name == ActionType.CONDITION.name:
            return ConditionAction.from_dict(data)
        elif action_type_name == ActionType.MQTT_PUBLISH.name:
            return MQTTPublishAction.from_dict(data)
        elif action_type_name == ActionType.INFO_MARKER.name:
            return InfoMarkerAction.from_dict(data)
        else:
            raise ValueError(f"Unknown action type: {action_type_name}")

class ArduinoCommandAction(BaseAction):
    def __init__(self, name, command):
        super().__init__(name, ActionType.ARDUINO_COMMAND)
        self.command = str(command)
        self.description = f"Send Arduino: '{self.command}'"
        
    def execute(self, context):
        arduino_interface = context.get('interfaces', {}).get('arduino')
        if arduino_interface and arduino_interface.is_connected():
            try:
                # Substitute variables if present
                resolved_command = context.get('resolve_variables', lambda x: x)(self.command)
                # Send command (assuming a method like send_command exists)
                arduino_interface.send_command(resolved_command)
                
                # Track outbound command for data flow monitoring
                main_window = context.get('main_window')
                if main_window and hasattr(main_window, 'data_flow_controller'):
                    sequence_name = context.get('current_sequence_name', 'Automation')
                    main_window.data_flow_controller.record_outbound_command(
                        target='arduino',
                        command=resolved_command,
                        source_automation=sequence_name
                    )
                
                self.action_completed.emit(self)
            except Exception as e:
                self.action_failed.emit(self, f"Failed to send Arduino command: {e}")
        else:
            self.action_failed.emit(self, "Arduino not connected or available")
            
    def to_dict(self):
        data = super().to_dict()
        data.update({'command': self.command})
        return data

    @staticmethod
    def from_dict(data):
        return ArduinoCommandAction(data['name'], data['command'])

class LabJackCommandAction(BaseAction):
    def __init__(self, name, channel, value):
        super().__init__(name, ActionType.LABJACK_COMMAND)
        self.channel = str(channel)
        self.value = value # Can be int (digital) or float (analog)
        self.description = f"Set LabJack {self.channel} to {self.value}"
        
    def execute(self, context):
        labjack_interface = context.get('interfaces', {}).get('labjack')
        if labjack_interface and labjack_interface.is_connected():
            try:
                # Substitute variables if present in channel or value
                resolved_channel = context.get('resolve_variables', lambda x: x)(self.channel)
                
                # Attempt to resolve value if it's a string (might be a variable)
                if isinstance(self.value, str):
                    resolved_value_str = context.get('resolve_variables', lambda x: x)(self.value)
                    # Try converting resolved value to float/int
                    try:
                        resolved_value = float(resolved_value_str)
                        # Convert to int if it looks like one
                        if resolved_value == int(resolved_value):
                             resolved_value = int(resolved_value)
                    except ValueError:
                         raise ValueError(f"Could not convert resolved variable '{resolved_value_str}' to a number for LabJack value")
                else:
                     resolved_value = self.value # Use original numeric value
                
                # Send command (assuming a method like write_channel exists)
                labjack_interface.write_channel(resolved_channel, resolved_value)
                
                # Track outbound command for data flow monitoring
                main_window = context.get('main_window')
                if main_window and hasattr(main_window, 'data_flow_controller'):
                    sequence_name = context.get('current_sequence_name', 'Automation')
                    main_window.data_flow_controller.record_outbound_command(
                        target='labjack',
                        command=f"{resolved_channel}={resolved_value}",
                        source_automation=sequence_name,
                        channel=resolved_channel,
                        value=resolved_value
                    )
                
                self.action_completed.emit(self)
            except Exception as e:
                self.action_failed.emit(self, f"Failed to send LabJack command: {e}")
        else:
            self.action_failed.emit(self, "LabJack not connected or available")
            
    def to_dict(self):
        data = super().to_dict()
        data.update({'channel': self.channel, 'value': self.value})
        return data

    @staticmethod
    def from_dict(data):
        # Value could be saved as float or int, handle both
        value = data['value']
        return LabJackCommandAction(data['name'], data['channel'], value)

class SerialCommandAction(BaseAction):
    def __init__(self, name, port, command, baudrate=9600, timeout=1):
        super().__init__(name, ActionType.SERIAL_COMMAND)
        self.port = str(port)
        self.command = str(command)
        self.baudrate = int(baudrate)
        self.timeout = float(timeout)
        # Ensure command ends with newline? Often required for serial.
        if not self.command.endswith('\n'):
             self.command += '\n'
        self.description = f"Send Serial '{self.command.strip()}' to {self.port}"
        
    def execute(self, context):
        # This requires a generic serial interface manager in the context
        serial_manager = context.get('interfaces', {}).get('serial_manager') 
        if serial_manager:
            try:
                # Substitute variables if present
                resolved_port = context.get('resolve_variables', lambda x: x)(self.port)
                resolved_command = context.get('resolve_variables', lambda x: x)(self.command)
                
                # Send command using the manager
                serial_manager.send_command(resolved_port, resolved_command, self.baudrate, self.timeout)
                
                # Track outbound command for data flow monitoring
                main_window = context.get('main_window')
                if main_window and hasattr(main_window, 'data_flow_controller'):
                    sequence_name = context.get('current_sequence_name', 'Automation')
                    main_window.data_flow_controller.record_outbound_command(
                        target='serial',
                        command=resolved_command.strip(),
                        source_automation=sequence_name,
                        port=resolved_port
                    )
                
                self.action_completed.emit(self)
            except Exception as e:
                self.action_failed.emit(self, f"Failed to send Serial command to {self.port}: {e}")
        else:
            self.action_failed.emit(self, "Serial manager not available")
            
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'port': self.port,
            'command': self.command,
            'baudrate': self.baudrate,
            'timeout': self.timeout
        })
        return data

    @staticmethod
    def from_dict(data):
        return SerialCommandAction(
            data['name'], data['port'], data['command'],
            data.get('baudrate', 9600), data.get('timeout', 1)
        )

class MQTTPublishAction(BaseAction):
    def __init__(self, name, topic, payload):
        super().__init__(name, ActionType.MQTT_PUBLISH)
        self.topic = str(topic)
        self.payload = str(payload)
        self.description = f"MQTT Publish '{self.payload}' to {self.topic}"
        
    def execute(self, context):
        # Access MQTT interface via data_collection_controller in main_window
        main_window = context.get('main_window')
        if main_window and hasattr(main_window, 'data_collection_controller'):
            dcc = main_window.data_collection_controller
            if hasattr(dcc, 'mqtt_thread') and dcc.mqtt_thread.is_connected():
                try:
                    # Resolve variables in topic and payload
                    resolve_func = context.get('resolve_variables', lambda x: x)
                    resolved_topic = resolve_func(self.topic)
                    resolved_payload = resolve_func(self.payload)
                    
                    success = dcc.mqtt_thread.publish(resolved_topic, resolved_payload)
                    if success:
                        self.action_completed.emit(self)
                    else:
                        self.action_failed.emit(self, "Failed to publish MQTT message")
                except Exception as e:
                    self.action_failed.emit(self, f"MQTT publish error: {e}")
            else:
                self.action_failed.emit(self, "MQTT broker not connected")
        else:
            self.action_failed.emit(self, "Data collection controller not available")
            
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'topic': self.topic,
            'payload': self.payload
        })
        return data

    @staticmethod
    def from_dict(data):
        return MQTTPublishAction(data['name'], data['topic'], data['payload'])

class SystemAction(BaseAction):
    def __init__(self, name, action_type, parameters=None):
        # Call BaseAction init with the correct ENUM type
        super().__init__(name, ActionType.SYSTEM_ACTION)
        # Store the specific system action type (e.g., "start_recording") separately
        self.specific_action_type = str(action_type) 
        self.parameters = parameters if parameters else {}
        self.description = f"System: {self.specific_action_type}"
        if self.specific_action_type == "display_message":
            self.description += f" ('{self.parameters.get('message', '')[:20]}...')"
        elif self.specific_action_type == "play_sound":
             self.description += f" ({self.parameters.get('sound', 'beep')})"
             
    def execute(self, context):
        main_window = context.get('main_window')
        if not main_window:
            self.action_failed.emit(self, "Main window context not available")
            return

        try:
            # Substitute variables in parameters
            resolved_params = {} 
            resolve_func = context.get('resolve_variables', lambda x: x)
            for key, value in self.parameters.items():
                if isinstance(value, str):
                    resolved_params[key] = resolve_func(value)
                else:
                    resolved_params[key] = value # Keep non-strings as is

            # Find the appropriate controller/method on main_window or its controllers
            if self.specific_action_type == "start_recording" and hasattr(main_window, 'camera_controller'):
                main_window.camera_controller.start_recording()
            elif self.specific_action_type == "stop_recording" and hasattr(main_window, 'camera_controller'):
                main_window.camera_controller.stop_recording()
            elif self.specific_action_type == "take_snapshot" and hasattr(main_window, 'camera_controller'):
                # Check for camera_index in parameters
                camera_index = resolved_params.get("camera_index")
                # Capture the snapshot path to include in automation event
                self.last_image_path = main_window.camera_controller.take_snapshot(index=camera_index)
            elif self.specific_action_type == "display_message":
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(main_window, 
                                        resolved_params.get("title", "Automation Message"), 
                                        resolved_params.get("message", ""))
            elif self.specific_action_type == "play_sound":
                # Requires a sound playing utility
                sound_player = context.get('sound_player')
                if sound_player:
                    sound = resolved_params.get("sound", "beep")
                    if sound == "custom":
                        file_path = resolved_params.get("file_path")
                        if file_path and os.path.exists(file_path):
                            sound_player.play_wav(file_path)
                        else:
                            raise ValueError(f"Custom sound file not found or specified: {file_path}")
                    elif sound == "beep":
                        sound_player.play_beep()
                else:
                    print("Warning: Sound player not available in context.")
                    try:
                        import winsound # Windows only
                        winsound.MessageBeep()
                    except ImportError:
                        print("\a", end='') # Generic terminal bell
            elif self.specific_action_type == "start_acquisition":
                print(f"[Automation] Action: START ACQUISITION")
                # Ensure UI is ready
                if hasattr(main_window, 'run_description'):
                    desc = main_window.run_description.toPlainText().strip()
                    if not desc:
                        import datetime
                        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        main_window.run_description.setPlainText(f"Auto-started by Automation at {timestamp}")
                        print(f"[Automation] Set default run description")
                
                if hasattr(main_window, 'run_testers'):
                    testers = main_window.run_testers.text().strip()
                    if not testers:
                        main_window.run_testers.setText("Automation")
                        print(f"[Automation] Set default run testers")

                # Trigger the start acquisition logic directly
                if hasattr(main_window, 'start_acquisition'):
                    main_window.start_acquisition()
                else:
                    print("Error: main_window.start_acquisition not found")

            elif self.specific_action_type == "stop_acquisition":
                print(f"[Automation] Action: STOP ACQUISITION")
                if hasattr(main_window, 'stop_acquisition'):
                    main_window.stop_acquisition()
                else:
                    print("Error: main_window.stop_acquisition not found")
            else:
                raise NotImplementedError(f"System action '{self.specific_action_type}' not implemented")
                
            self.action_completed.emit(self)
            
        except Exception as e:
            self.action_failed.emit(self, f"Failed to execute system action '{self.specific_action_type}': {e}")
             
    def to_dict(self):
        # Get base dictionary (which includes the correct 'type': ActionType.SYSTEM_ACTION.name)
        data = super().to_dict() 
        # Add the specific action type and parameters
        data.update({
            'specific_action_type': self.specific_action_type,
            'parameters': self.parameters
        })
        return data

    @staticmethod
    def from_dict(data):
        # Extract the specific action type and parameters
        specific_action_type = data.get('specific_action_type') # Use the new key
        if not specific_action_type:
             # Backwards compatibility: Try the old 'action_type' key if specific isn't found
             specific_action_type = data.get('action_type') 
        
        if not specific_action_type:
             raise ValueError("Missing 'specific_action_type' in SystemAction data")
             
        # Create the object using the specific type
        return SystemAction(data['name'], specific_action_type, data.get('parameters'))

# --- Variable Action ---
class SetVariableAction(BaseAction):
    def __init__(self, name, variable_name, expression):
        super().__init__(name, ActionType.SET_VARIABLE)
        self.variable_name = str(variable_name).strip()
        self.expression = str(expression).strip()
        self.description = f"Set variable '{self.variable_name}' = '{self.expression}'"
        
    def execute(self, context):
        variable_manager = context.get('variable_manager')
        
        if not variable_manager:
             self.action_failed.emit(self, "Variable manager not available in context")
             return
             
        if not self.variable_name:
             self.action_failed.emit(self, "Variable name cannot be empty")
             return
             
        try:
             # Use the manager's enhanced expression evaluator
             value_to_set = variable_manager.evaluate_expression(self.expression, context)
             
             # Set the variable in the manager
             variable_manager.set_variable(self.variable_name, value_to_set)
             self.action_completed.emit(self)
             
        except Exception as e:
             self.action_failed.emit(self, f"Failed to set variable '{self.variable_name}': {e}")
             
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'variable_name': self.variable_name,
            'expression': self.expression
        })
        return data

    @staticmethod
    def from_dict(data):
        return SetVariableAction(data['name'], data['variable_name'], data['expression'])

# --- Flow Control Actions ---
class JumpToStepAction(BaseAction):
    def __init__(self, name, target_step_index):
        super().__init__(name, ActionType.JUMP_TO_STEP)
        self.target_step_index = int(target_step_index)
        self.description = f"Jump to step {self.target_step_index + 1}"
        
    def execute(self, context):
        sequence = context.get('current_sequence')
        if sequence:
            # We subtract 1 because _handle_step_completed will increment it
            sequence.current_step_index = self.target_step_index - 1
            self.action_completed.emit(self)
        else:
            self.action_failed.emit(self, "Current sequence not found in context")
            
    def to_dict(self):
        data = super().to_dict()
        data.update({'target_step_index': self.target_step_index})
        return data

    @staticmethod
    def from_dict(data):
        return JumpToStepAction(data['name'], data['target_step_index'])

class ConditionAction(BaseAction):
    def __init__(self, name, condition_expression, if_true_step, if_false_step=None):
        super().__init__(name, ActionType.CONDITION)
        self.condition_expression = str(condition_expression)
        self.if_true_step = int(if_true_step)
        self.if_false_step = int(if_false_step) if if_false_step is not None else None
        
        self.description = f"If '{self.condition_expression}' jump to {self.if_true_step + 1}"
        if self.if_false_step is not None:
            self.description += f" else {self.if_false_step + 1}"
            
    def execute(self, context):
        variable_manager = context.get('variable_manager')
        sequence = context.get('current_sequence')
        
        if not variable_manager or not sequence:
            self.action_failed.emit(self, "Manager or sequence not in context")
            return
            
        try:
            # Resolve variables in the expression
            resolved = variable_manager.resolve_variables(self.condition_expression)
            
            # Simple evaluation for conditions (supporting <, >, ==, !=, <=, >=)
            # We'll use a slightly more permissive regex for conditions
            import re
            if not re.match(r'^[0-9.+\-*/%() !<>=&|]*$', resolved):
                 # Fallback to direct comparison if it's not a mathy condition
                 # (e.g., "{status} == 'OK'")
                 # This is still very basic.
                 pass
            
            # Use eval for the condition
            # Note: We should probably use a safer way, but following the pattern for now.
            is_true = eval(resolved, {"__builtins__": None}, {})
            
            if is_true:
                sequence.current_step_index = self.if_true_step - 1
            elif self.if_false_step is not None:
                sequence.current_step_index = self.if_false_step - 1
            
            self.action_completed.emit(self)
        except Exception as e:
            self.action_failed.emit(self, f"Condition error: {e}")
            
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'condition_expression': self.condition_expression,
            'if_true_step': self.if_true_step,
            'if_false_step': self.if_false_step
        })
        return data

    @staticmethod
    def from_dict(data):
        return ConditionAction(
            data['name'], 
            data['condition_expression'], 
            data['if_true_step'], 
            data.get('if_false_step')
        )

class InfoMarkerAction(BaseAction):
    def __init__(self, name, marker_text):
        super().__init__(name, ActionType.INFO_MARKER)
        self.marker_text = str(marker_text)
        self.description = f"Info Marker: {self.marker_text}"
        
    def execute(self, context):
        # Info markers don't "do" anything in the system, 
        # but they trigger a log event which shows up on the graph.
        # Variable resolution is supported in the marker text.
        resolve_func = context.get('resolve_variables', lambda x: x)
        resolved_text = resolve_func(self.marker_text)
        self.description = f"Info: {resolved_text}"
        self.action_completed.emit(self)
        
    def to_dict(self):
        data = super().to_dict()
        data.update({'marker_text': self.marker_text})
        return data

    @staticmethod
    def from_dict(data):
        return InfoMarkerAction(data['name'], data.get('marker_text', ''))

# --- Step and Sequence ---
class ActionWorker(QRunnable):
    """Worker for executing actions in a separate thread."""
    def __init__(self, action, context):
        super().__init__()
        self.action = action
        self.context = context

    def run(self):
        try:
            self.action.execute(self.context)
        except Exception as e:
            error_msg = f"Worker exception: {e}"
            print(error_msg)
            traceback.print_exc()
            self.action.action_failed.emit(self.action, error_msg)

class AutomationStep(QObject):
    step_started = pyqtSignal(object)
    step_completed = pyqtSignal(object)
    step_failed = pyqtSignal(object, str)

    def __init__(self, trigger, action, enabled=True):
        super().__init__()
        if not isinstance(trigger, BaseTrigger):
             raise TypeError("trigger must be an instance of BaseTrigger")
        if not isinstance(action, BaseAction):
             raise TypeError("action must be an instance of BaseAction")
             
        self.trigger = trigger
        self.action = action
        self.enabled = bool(enabled)
        self.is_running = False # Tracks if action is currently executing
        
        # Connect signals
        self.action.action_completed.connect(self._on_action_completed)
        self.action.action_failed.connect(self._on_action_failed)
        
    def check_trigger(self, context):
        """Check if the step's trigger condition is met."""
        if not self.enabled or self.is_running:
            return False
        return self.trigger.check(context)
        
    def execute_action(self, context):
        """Execute the step's action."""
        if not self.enabled:
            self.step_failed.emit(self, "Step is disabled")
            return
            
        if self.is_running:
             print(f"Warning: Action '{self.action.name}' already running for step.")
             return
             
        self.is_running = True
        # Clear previous result data
        self.action.last_image_path = None
        # Capture context and start time for logging
        self._last_context = context
        self.last_execution_timestamp = time.time()
        
        self.step_started.emit(self)
        
        # We now log action execution AFTER completion to capture any generated data (like snapshot paths)
        # unless it's an async action that might take a long time.
        # For simplicity, we'll log most actions on completion.
            
        # Execute the action (async if requested)
        if getattr(self.action, 'is_async', False):
            # For async actions, we still log at the start because completion might be much later
            self._log_action_event(context, timestamp=self.last_execution_timestamp)
            worker = ActionWorker(self.action, context)
            QThreadPool.globalInstance().start(worker)
        else:
            self.action.execute(context)
            # Synchronous actions are logged in _on_action_completed which is called at the end of execute()
    
    def _log_action_event(self, context, timestamp=None):
        """Log when an action is executed"""
        import time
        # Get sequence name from context if available
        sequence_name = context.get('current_sequence_name', 'Unknown')
        # Try to get manager from context or main_window
        manager = None
        main_window = context.get('main_window')
        if main_window and hasattr(main_window, 'automation_controller'):
            manager = main_window.automation_controller.manager
        
        if manager and hasattr(manager, 'event_logged'):
            event = {
                'timestamp': timestamp or time.time(),
                'type': 'action',
                'sequence_name': sequence_name,
                'action_name': self.action.name,
                'action_description': getattr(self.action, 'description', 'Unknown action'),
                'action_type': self.action.action_type.name if hasattr(self.action, 'action_type') else 'Unknown',
                'image_path': getattr(self.action, 'last_image_path', None)
            }
            manager.event_logged.emit(event)
        
    def _on_action_completed(self, action_obj):
        if action_obj == self.action:
            # For synchronous actions, log now so we include any result data (like last_image_path)
            if not getattr(self.action, 'is_async', False):
                # Retrieve context from parent sequence if possible
                context = getattr(self.parent(), '_context', {}) if hasattr(self, 'parent') else {}
                # If we can't get context easily, we'll use a minimal one or find it from main_window
                if not context:
                    main_window = None
                    # Try to find main_window to get controller
                    # This is a bit of a hack but AutomationStep doesn't store context
                    pass 
                
                # Actually, AutomationStep.execute_action receives context. 
                # Let's store a reference to the last context.
                last_context = getattr(self, '_last_context', {})
                self._log_action_event(last_context, timestamp=self.last_execution_timestamp)

            self.is_running = False
            self.step_completed.emit(self)
            
    def _on_action_failed(self, action_obj, reason):
        if action_obj == self.action:
            self.is_running = False
            self.step_failed.emit(self, reason)

    def cleanup(self):
        """Clean up step resources and disconnect signals."""
        try:
            self.action.action_completed.disconnect(self._on_action_completed)
        except (TypeError, RuntimeError):
            pass
        try:
            self.action.action_failed.disconnect(self._on_action_failed)
        except (TypeError, RuntimeError):
            pass
        
        self.trigger.cleanup()
        self.action.cleanup()

    def to_dict(self):
        # Serialize trigger and action with error handling
        try:
            trigger_dict = self.trigger.to_dict()
        except Exception as e:
            print(f"Error serializing trigger '{getattr(self.trigger, 'name', 'Unknown')}' in step: {e}")
            traceback.print_exc()
            raise  # Re-raise to let caller handle it
        
        try:
            action_dict = self.action.to_dict()
        except Exception as e:
            print(f"Error serializing action '{getattr(self.action, 'name', 'Unknown')}' in step: {e}")
            traceback.print_exc()
            raise  # Re-raise to let caller handle it
        
        return {
            'trigger': trigger_dict,
            'action': action_dict,
            'enabled': self.enabled
        }
        
    @staticmethod
    def from_dict(data):
        trigger = BaseTrigger.from_dict(data['trigger'])
        action = BaseAction.from_dict(data['action'])
        return AutomationStep(trigger, action, data.get('enabled', True))

class AutomationSequence(QObject):
    sequence_started = pyqtSignal(object)
    sequence_step_changed = pyqtSignal(object, int) # sequence, step_index
    sequence_completed = pyqtSignal(object)
    sequence_stopped = pyqtSignal(object)
    sequence_error = pyqtSignal(object, str) # sequence, error_message

    def __init__(self, name, steps=None, loop=False, checked=False, run_linked=False):
        super().__init__()
        self.name = name
        self.steps = steps if steps else []
        self.loop = loop
        self.checked = checked
        self.run_linked = run_linked
        self.current_step_index = -1
        self.is_running = False
        self._timer = None
        self._context = {} # Execution context passed to triggers/actions
        self._current_step_failed = False
        
        # Connect signals from steps
        for step in self.steps:
            step.step_completed.connect(self._handle_step_completed)
            step.step_failed.connect(self._handle_step_failed)
            
    def set_context(self, context):
        self._context = context
        
    def start(self, check_interval_ms=100):
        """Start executing the sequence."""
        if self.is_running:
            print(f"Sequence '{self.name}' is already running.")
            return
            
        if not self.steps:
             self.sequence_error.emit(self, "Cannot start sequence with no steps.")
             return
             
        self.is_running = True
        self.current_step_index = 0
        self._current_step_failed = False
        
        # Reset all triggers and step states
        for step in self.steps:
             step.trigger.reset()
             step.is_running = False

        self.sequence_started.emit(self)
        self.sequence_step_changed.emit(self, self.current_step_index)
        
        # Start the main execution loop timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._run_loop)
        self._timer.start(check_interval_ms)
        
        # Immediately try to execute the first step if its trigger allows
        self._run_loop()
        
    def stop(self):
        """Stop executing the sequence."""
        if not self.is_running:
            return
            
        if self._timer:
            self._timer.stop()
            self._timer = None
            
        # Stop any currently running step action if possible (graceful stop TBD)
        if 0 <= self.current_step_index < len(self.steps):
            current_step = self.steps[self.current_step_index]
            if current_step.is_running:
                 # TODO: Need a way to signal actions to stop gracefully if needed
                 current_step.is_running = False # Force stop for now
                 print(f"Forcibly stopped action '{current_step.action.name}'")
        
        self.is_running = False
        self.current_step_index = -1
        self.sequence_stopped.emit(self)
        
    def _run_loop(self):
        """The main execution loop checked periodically by the timer."""
        if not self.is_running or self._current_step_failed:
            # Stop timer if sequence stopped or failed
            if self._timer:
                 self._timer.stop()
            return
            
        # Ensure index is valid
        if not (0 <= self.current_step_index < len(self.steps)):
             # This shouldn't happen if logic is correct, but handle defensively
             print(f"Error: Invalid step index {self.current_step_index} in sequence '{self.name}'")
             self.stop()
             self.sequence_error.emit(self, "Internal error: Invalid step index")
             return
             
        current_step = self.steps[self.current_step_index]
        
        # Only proceed if the step is not already running its action
        if not current_step.is_running:
             # Check the trigger for the current step
             trigger_met = current_step.check_trigger(self._context)
             
             if trigger_met:
                 # Trigger condition met - log trigger event
                 print(f"[Automation] Sequence '{self.name}' Step {self.current_step_index + 1}: Trigger met ({current_step.trigger.name})")
                 self._log_trigger_event(current_step, self._context)
                 # Execute the action
                 try:
                     print(f"[Automation] Sequence '{self.name}' Step {self.current_step_index + 1}: Executing action ({current_step.action.name})")
                     current_step.execute_action(self._context)
                 except Exception as e:
                     error_msg = f"Exception during action execution: {e}"
                     print(f"Error in sequence '{self.name}', step {self.current_step_index + 1}: {error_msg}")
                     traceback.print_exc() # Log the full traceback
                     # Manually trigger the failure handling
                     self._handle_step_failed(current_step, error_msg)
                     return # Stop further processing in this loop iteration

                 # Action completion/failure is handled by signals _handle_step_completed/_handle_step_failed
             else:
                  # If it's a duration trigger, start its timer when the step becomes active
                  # (even if check returns false initially)
                  if isinstance(current_step.trigger, TimeDurationTrigger) and current_step.trigger.start_time is None:
                       print(f"[Automation] Sequence '{self.name}' Step {self.current_step_index + 1}: Starting duration timer ({current_step.trigger.name})")
                       current_step.trigger.start()

    def _handle_step_completed(self, completed_step):
        if not self.is_running or completed_step != self.steps[self.current_step_index]:
            return # Ignore if sequence stopped or it's not the current step
            
        print(f"[Automation] Sequence '{self.name}' Step {self.current_step_index + 1} completed.")
        
        # Move to the next step
        self.current_step_index += 1
        
        if self.current_step_index >= len(self.steps):
            # End of sequence
            if self.loop:
                # Loop back to the beginning
                self.current_step_index = 0
                print(f"Sequence '{self.name}' looping back to step 1.")
                self.sequence_step_changed.emit(self, self.current_step_index)
                
                # We don't call trigger.reset() here because we want to maintain 
                # state like cooldowns and hysteresis across loops.
                # reset() is only called when the sequence is explicitly (re)started.
                    
                # Use singleShot to break recursion and allow event loop processing
                # This prevents UI hangs in tight loops
                QTimer.singleShot(0, self._run_loop)
            else:
                # Sequence finished
                print(f"Sequence '{self.name}' completed.")
                self.stop()
                self.sequence_completed.emit(self)
        else:
            # Proceed to the next step
            print(f"[Automation] Sequence '{self.name}' moving to Step {self.current_step_index + 1}.")
            self.sequence_step_changed.emit(self, self.current_step_index)
            # Use singleShot to break recursion
            QTimer.singleShot(0, self._run_loop)
            
    def _handle_step_failed(self, failed_step, reason):
         if not self.is_running or failed_step != self.steps[self.current_step_index]:
            return
            
         print(f"Error in sequence '{self.name}', step {self.current_step_index + 1} ('{failed_step.trigger.name}' -> '{failed_step.action.name}'): {reason}")
         self._current_step_failed = True # Flag to stop the run loop
         self.stop()
         self.sequence_error.emit(self, f"Step {self.current_step_index + 1} failed: {reason}")
    
    def _log_trigger_event(self, step, context):
        """Log when a trigger fires"""
        import time
        if hasattr(self, 'manager') and hasattr(self.manager, 'event_logged'):
            event = {
                'timestamp': time.time(),
                'type': 'trigger',
                'sequence_name': self.name,
                'step_index': self.current_step_index,
                'trigger_name': step.trigger.name,
                'trigger_description': getattr(step.trigger, 'description', 'Unknown trigger'),
                'action_name': step.action.name,
                'action_description': getattr(step.action, 'description', 'Unknown action'),
                'image_path': None # Triggers don't usually have images, but keep schema consistent
            }
            print(f"DEBUG AUTOMATION: Emitting trigger event: {event.get('trigger_description')} from sequence '{self.name}'")
            self.manager.event_logged.emit(event)
        else:
            print(f"DEBUG AUTOMATION: Cannot log trigger event - manager not available (has manager: {hasattr(self, 'manager')})")

    def cleanup(self):
        """Clean up sequence resources and disconnect signals."""
        self.stop()
        for step in self.steps:
            try:
                step.step_completed.disconnect(self._handle_step_completed)
            except (TypeError, RuntimeError):
                pass
            try:
                step.step_failed.disconnect(self._handle_step_failed)
            except (TypeError, RuntimeError):
                pass
            step.cleanup()

    def to_dict(self):
        # Serialize steps with error handling
        steps_data = []
        for i, step in enumerate(self.steps):
            try:
                step_dict = step.to_dict()
                steps_data.append(step_dict)
            except Exception as e:
                print(f"Error serializing step {i} in sequence '{self.name}': {e}")
                traceback.print_exc()
                # Skip this step but continue with others
                continue
        
        return {
            'name': self.name,
            'loop': self.loop,
            'checked': self.checked,
            'run_linked': self.run_linked,
            'steps': steps_data
        }
        
    @staticmethod
    def from_dict(data):
        name = data.get('name', 'Unnamed Sequence')
        loop = data.get('loop', False)
        steps_data = data.get('steps', [])
        steps = [AutomationStep.from_dict(step_data) for step_data in steps_data]
        checked_state = data.get('checked', False)
        run_linked = data.get('run_linked', False)
        return AutomationSequence(name, steps, loop, checked_state, run_linked)

# --- Automation Manager (Handles loading/saving/running sequences) ---
class AutomationManager(QObject):
    sequences_changed = pyqtSignal() # Emitted when sequences list changes
    sequence_started = pyqtSignal(object) # Re-emitted from sequence
    sequence_stopped = pyqtSignal(object) # Re-emitted from sequence
    sequence_completed = pyqtSignal(object) # Re-emitted from sequence
    sequence_step_changed = pyqtSignal(object, int) # Re-emitted from sequence
    sequence_error = pyqtSignal(object, str) # Re-emitted from sequence
    status_changed = pyqtSignal() # Generic signal for UI updates
    event_logged = pyqtSignal(dict) # Emitted when an automation event occurs (for CSV/graph logging)

    def __init__(self, sequences_file="automation_sequences.json", app_context=None, master_file=None):
        super().__init__()
        self.sequences = []
        self.active_sequences = set() # Sequences currently running
        self.sequences_file = sequences_file
        self.master_file = master_file
        self.app_context = app_context if app_context else {}
        self.variables = {} # Dictionary to store shared variables
        self.load_sequences() # Load sequences on initialization

    def set_sequences_file(self, new_path):
        """Sets the path for the sequences JSON file."""
        if self.sequences_file != new_path:
            print(f"AutomationManager: Setting sequences file to {new_path}")
            self.sequences_file = new_path
            # Note: load_sequences is called separately after setting the path

    def set_master_file(self, new_path):
        """Sets the path for the master sequences JSON file (for persistent storage)."""
        if self.master_file != new_path:
            print(f"AutomationManager: Setting master sequences file to {new_path}")
            self.master_file = new_path

    def get_available_sensors(self):
        """Get a list of sensor names available in the context."""
        return [s.name for s in self.get_available_sensor_objects()]

    def get_available_sensor_objects(self):
        """Get a list of SensorModel objects available in the context."""
        # First check if we have a sensor_controller
        sensor_controller = self.app_context.get('sensor_controller')
        if sensor_controller:
            if hasattr(sensor_controller, 'get_sensors'):
                return sensor_controller.get_sensors()
            elif hasattr(sensor_controller, 'sensors'):
                return sensor_controller.sensors
                
        # If we have a main_window, try to get from there
        main_window = self.app_context.get('main_window')
        if main_window and hasattr(main_window, 'sensor_controller'):
            sc = main_window.sensor_controller
            if hasattr(sc, 'get_sensors'):
                return sc.get_sensors()
            elif hasattr(sc, 'sensors'):
                return sc.sensors
                
        return [] # Return empty list if unavailable
        
    def get_available_serial_ports(self):
        """Get a list of available serial ports."""
        serial_manager = self.app_context.get('interfaces', {}).get('serial_manager')
        if serial_manager and hasattr(serial_manager, 'list_ports'):
            return serial_manager.list_ports()
        return []
        
    def update_context(self, context):
         """Update the context used by running sequences."""
         # Add variable management and resolution to the context
         context['variable_manager'] = self
         context['resolve_variables'] = self.resolve_variables
         context['variables'] = self.variables # Direct access (read-only recommended)
         
         # --- ADDED: Expose main app state to automation ---
         main_window = self.app_context.get('main_window')
         if main_window:
             context['is_running'] = getattr(main_window, 'running', False)
             # Handle camera recording state (could be bool or list)
             is_rec = False
             if hasattr(main_window, 'camera_controller'):
                 if isinstance(main_window.camera_controller.is_recording, list):
                     is_rec = any(main_window.camera_controller.is_recording)
                 else:
                     is_rec = main_window.camera_controller.is_recording
             context['is_recording'] = is_rec
         # --------------------------------------------------

         # Preserve events dictionary if it exists (don't overwrite with empty dict)
         if 'events' in self.app_context and 'events' not in context:
             # Keep existing events
             pass
         elif 'events' not in self.app_context:
             # Initialize events if it doesn't exist
             context.setdefault('events', set())
         
         self.app_context.update(context)
         # Update context for all currently running sequences
         for seq in self.active_sequences:
             seq.set_context(self.app_context)
             
    # --- Variable Management ---
    def set_variable(self, name, value):
        """Set or update an automation variable."""
        print(f"[Automation] Setting variable '{name}' = {value}")
        self.variables[name] = value
        self.status_changed.emit() # Notify UI potentially
        
    def get_variable(self, name, default=None):
        """Get the value of an automation variable."""
        return self.variables.get(name, default)
        
    def resolve_variables(self, text):
        """Replace placeholders like {var_name} in a string with variable values."""
        if not isinstance(text, str):
             return text # Only resolve in strings
             
        resolved_text = text
        # Basic placeholder replacement
        import re
        placeholders = re.findall(r"\{([^}]+)\}", text)
        for placeholder in placeholders:
            var_name = placeholder.strip()
            # Try to resolve from variables or sensors
            value = self.get_variable(var_name)
            
            # If not in variables, check sensors in app_context
            if value is None:
                sensors = self.app_context.get('sensors', {})
                value = sensors.get(var_name)
                
            if value is not None:
                resolved_text = resolved_text.replace(f"{{{placeholder}}}", str(value))
            else:
                 print(f"[Automation] Warning: Variable/Sensor '{var_name}' not found for substitution in '{text}'")
        return resolved_text

    def evaluate_expression(self, expression, context=None):
        """Safely evaluate a mathematical expression."""
        if not expression:
            return None
            
        # 1. Resolve variables first
        resolved = self.resolve_variables(str(expression))
        
        # 2. Basic cleanup
        # Only allow numbers, basic operators, and parentheses
        import re
        if not re.match(r'^[0-9.+\-*/%() ]*$', resolved):
            # If it's not a pure math expression, return the resolved string
            # This allows it to still be used for simple string assignments
            return resolved
            
        try:
            # Using a very restricted eval is still slightly risky, 
            # but the regex above only allows safe characters.
            return eval(resolved, {"__builtins__": None}, {})
        except Exception as e:
            print(f"[Automation] Error evaluating expression '{expression}' (resolved as '{resolved}'): {e}")
            return resolved
        
    # --- Sequence Management ---
    def add_sequence(self, sequence):
        if isinstance(sequence, AutomationSequence):
            self.sequences.append(sequence)
            self._connect_sequence_signals(sequence)
            self.sequences_changed.emit()
            self.save_sequences()
        else:
            print("Error: Attempted to add non-sequence object to manager.")
            
    def remove_sequence(self, sequence_to_remove):
        """Remove a sequence from the list and save to file."""
        sequence_name = sequence_to_remove.name if hasattr(sequence_to_remove, 'name') else "Unknown"
        print(f"Removing sequence: {sequence_name} from file: {self.sequences_file}")
        
        if sequence_to_remove in self.active_sequences:
            self.stop_sequence(sequence_to_remove)
            
        if sequence_to_remove in self.sequences:
            self.sequences.remove(sequence_to_remove)
            self._disconnect_sequence_signals(sequence_to_remove)
            print(f"Sequence '{sequence_name}' removed from memory. Remaining sequences: {len(self.sequences)}")
            self.sequences_changed.emit()
            
            # Save to file immediately after removal
            try:
                self.save_sequences()
                print(f"Sequences saved after removal of '{sequence_name}'")
            except Exception as e:
                print(f"Error saving sequences after removal: {e}")
                traceback.print_exc()
                raise  # Re-raise to notify caller of failure
        else:
            print(f"Warning: Sequence '{sequence_name}' not found in sequences list")
            
    def update_sequence(self, original_sequence, updated_sequence_data):
        """Update an existing sequence (e.g., after editing)"""
        if original_sequence in self.sequences:
             # Re-create the sequence object from the updated data
             # This ensures signals are handled correctly if steps were added/removed
             try:
                 index = self.sequences.index(original_sequence)
                 was_running = original_sequence in self.active_sequences
                 
                 if was_running:
                      self.stop_sequence(original_sequence)
                      
                 self._disconnect_sequence_signals(original_sequence)
                 
                 # Assume updated_sequence_data is the *object* returned by SequenceDialog
                 # If it was just a dict, we'd use AutomationSequence.from_dict here
                 new_sequence = updated_sequence_data 
                 
                 self.sequences[index] = new_sequence
                 self._connect_sequence_signals(new_sequence)
                 
                 self.sequences_changed.emit()
                 self.save_sequences()
                 
                 # Optionally restart if it was running? Or leave stopped?
                 # if was_running:
                 #     self.start_sequence(new_sequence)
                     
             except Exception as e:
                  print(f"Error updating sequence '{original_sequence.name}': {e}")
        else:
             print(f"Error: Cannot update sequence '{original_sequence.name}', not found.")
            
    def start_sequence(self, sequence):
        if sequence in self.sequences and sequence not in self.active_sequences:
            self.active_sequences.add(sequence)
            # Pass the current context to the sequence
            self.update_context({}) # Ensure latest context vars are included
            # Add sequence info to context for event logging and flow control
            self.app_context['current_sequence_name'] = sequence.name
            self.app_context['current_sequence'] = sequence
            sequence.set_context(self.app_context)
            # Store reference to manager in sequence for event logging
            sequence.manager = self
            sequence.start()
            self.status_changed.emit()
        elif sequence in self.active_sequences:
             print(f"Sequence '{sequence.name}' is already running.")
        else:
             print(f"Sequence '{sequence.name}' not found in manager.")
             
    def stop_sequence(self, sequence):
        if sequence in self.active_sequences:
            sequence.stop()
            # The sequence_stopped signal handler will remove it from active_sequences
            self.status_changed.emit()
        else:
            print(f"Sequence '{sequence.name}' is not currently running.")
            
    def stop_all_sequences(self):
         print("Stopping all active automation sequences...")
         # Iterate over a copy as stop_sequence modifies the set
         for seq in list(self.active_sequences):
             self.stop_sequence(seq)
         print("All sequences stopped.")

    def save_sequences(self):
        """Save the current sequences list to the JSON file."""
        if not self.sequences_file:
            print("Error: No sequence file path set for saving.")
            return

        # Check for replay mode via app_context
        main_window = self.app_context.get('main_window')
        is_replay = getattr(main_window, 'is_replay_mode', False) if main_window else False

        try:
            # Ensure the directory exists
            directory = os.path.dirname(self.sequences_file)
            if directory:
                os.makedirs(directory, exist_ok=True)
            
            # Serialize sequences with error handling for each sequence
            sequences_data = []
            for i, seq in enumerate(self.sequences):
                try:
                    seq_dict = seq.to_dict()
                    sequences_data.append(seq_dict)
                except Exception as e:
                    print(f"Error serializing sequence {i} '{getattr(seq, 'name', 'Unknown')}': {e}")
                    traceback.print_exc()
                    # Skip this sequence but continue with others
                    continue
            
            # Use atomic write: write to temporary file first, then rename
            # This ensures the file is either completely written or not at all
            
            # If in replay mode, we skip saving to the specific run file (sequences_file)
            # and instead save directly to the master file if it exists.
            target_file = self.master_file if is_replay and self.master_file else self.sequences_file
            
            if not target_file:
                return

            temp_file = target_file + ".tmp"
            
            # Write to temporary file
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(sequences_data, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk
            
            # Atomic rename: replace old file with new one
            # On Windows, we need to remove the old file first if it exists
            if os.path.exists(target_file):
                os.replace(temp_file, target_file)
            else:
                os.rename(temp_file, target_file)
            
            # Verify the save was successful by checking file exists and is readable
            if os.path.exists(target_file):
                with open(target_file, 'r', encoding='utf-8') as f:
                    saved_data = json.load(f)
                    if len(saved_data) == len(sequences_data):
                        print(f"Automation sequences saved successfully to {target_file} ({len(sequences_data)} sequences)")
                        
                        # ALSO save to master file if it's different (persistence across runs)
                        # but only if we weren't ALREADY saving to the master file
                        if not is_replay and self.master_file and self.master_file != target_file:
                            try:
                                # Ensure the master directory exists
                                master_dir = os.path.dirname(self.master_file)
                                if master_dir:
                                    os.makedirs(master_dir, exist_ok=True)
                                
                                # Use shutil to copy the file we just verified
                                import shutil
                                shutil.copy2(target_file, self.master_file)
                                print(f"Master automation sequences also updated at: {self.master_file}")
                            except Exception as e:
                                print(f"Error updating master sequences file {self.master_file}: {e}")
                    else:
                        print(f"Warning: Saved sequence count mismatch. Expected {len(sequences_data)}, got {len(saved_data)}")
            else:
                print(f"Error: File was not created at {target_file}")

        except IOError as e:
            print(f"Error saving automation sequences to {target_file}: {e}")
            traceback.print_exc()
            # Clean up temp file if it exists
            temp_file = target_file + ".tmp"
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
        except Exception as e:
            print(f"Unexpected error saving automation sequences: {e}")
            traceback.print_exc()
            # Clean up temp file if it exists
            temp_file = target_file + ".tmp"
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

    def load_sequences(self):
        """Load sequences from the JSON file."""
        if self.active_sequences:
            print(f"[Automation] WARNING: load_sequences called while {len(self.active_sequences)} sequences are active. Stopping them now.")
        
        # Stop any currently running sequences before loading new ones
        self.stop_all_sequences() 
        
        # Clear existing sequences
        self.sequences = []
        self.active_sequences.clear()

        # Clear sensor and event data from context to avoid stale triggers from previous runs
        if 'sensors' in self.app_context:
            self.app_context['sensors'] = {}
        if 'events' in self.app_context:
            self.app_context['events'] = set()
        self.variables = {} # Reset shared automation variables

        if not self.sequences_file:
            print("Error: No sequence file path set for loading.")
            self.sequences_changed.emit()
            self.status_changed.emit()
            return

        if not os.path.exists(self.sequences_file):
            print(f"Sequence file not found: {self.sequences_file}. No sequences loaded.")
            self.sequences_changed.emit() # Notify UI that sequences are cleared
            self.status_changed.emit()
            return

        try:
            with open(self.sequences_file, 'r') as f:
                # Handle empty file case
                content = f.read()
                if not content:
                    print(f"Sequence file is empty: {self.sequences_file}. No sequences loaded.")
                    self.sequences_changed.emit()
                    self.status_changed.emit()
                    return
                sequences_data = json.loads(content)
            
            loaded_sequences = []
            for data in sequences_data:
                try:
                    sequence = AutomationSequence.from_dict(data)
                    loaded_sequences.append(sequence)
                    self._connect_sequence_signals(sequence) # Connect signals for loaded sequence
                except Exception as e:
                    print(f"Error deserializing sequence data: {data}. Error: {e}")
                    traceback.print_exc()
                    # Skip this sequence and continue loading others
            
            self.sequences = loaded_sequences
            print(f"Loaded {len(self.sequences)} automation sequences from {self.sequences_file}")

        except FileNotFoundError:
            # This case is handled by the os.path.exists check above, but good practice
            print(f"Sequence file not found: {self.sequences_file}. No sequences loaded.")
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from sequence file {self.sequences_file}: {e}")
            # File might be corrupted, leave sequences empty
        except Exception as e:
            print(f"Error loading automation sequences from {self.sequences_file}: {e}")
            traceback.print_exc()
            # Generic error, leave sequences empty
            
        # Always emit signals after attempting to load
        self.sequences_changed.emit()
        self.status_changed.emit()

    # --- Signal Handling ---
    def _connect_sequence_signals(self, sequence):
         sequence.sequence_started.connect(self.sequence_started)
         sequence.sequence_stopped.connect(self._handle_sequence_stopped)
         sequence.sequence_completed.connect(self.sequence_completed)
         sequence.sequence_step_changed.connect(self.sequence_step_changed)
         sequence.sequence_error.connect(self.sequence_error)
         
    def _disconnect_sequence_signals(self, sequence):
         # Use the new cleanup method
         sequence.cleanup()
         
         # Also attempt to disconnect sequence signals from manager
         try: sequence.sequence_started.disconnect(self.sequence_started)
         except (TypeError, RuntimeError): pass
         try: sequence.sequence_stopped.disconnect(self._handle_sequence_stopped)
         except (TypeError, RuntimeError): pass
         try: sequence.sequence_completed.disconnect(self.sequence_completed)
         except (TypeError, RuntimeError): pass
         try: sequence.sequence_step_changed.disconnect(self.sequence_step_changed)
         except (TypeError, RuntimeError): pass
         try: sequence.sequence_error.disconnect(self.sequence_error)
         except (TypeError, RuntimeError): pass

    def _handle_sequence_stopped(self, sequence):
        """Handle sequence stopped signal to remove from active set."""
        self.active_sequences.discard(sequence)
        self.status_changed.emit()
        # Re-emit the signal from the manager
        self.sequence_stopped.emit(sequence) 