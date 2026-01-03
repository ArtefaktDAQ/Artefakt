class SensorModel:
    """Model for sensor data and configuration."""
    
    def __init__(self, name="", interface_type="", port="", unit="", 
                 offset=0.0, conversion_factor=1.0, color="#FFFFFF", 
                 enabled=True, show_in_graph=True, sequence_config=None, 
                 audio_config=None, optical_config=None,
                 stale_timeout_factor=None, averaging_enabled=False):
        self.name = name
        self.interface_type = interface_type
        self.port = port
        self.unit = unit
        self.offset = offset
        self.conversion_factor = conversion_factor
        self.color = color
        self.enabled = enabled
        self.show_in_graph = show_in_graph
        self.averaging_enabled = averaging_enabled
        self.current_value = None
        self.history = []
        self.sequence_config = sequence_config or {}  # Store sequence configuration for OtherSerial sensors
        self.audio_config = audio_config or {}  # Store audio sensor configuration
        self.optical_config = optical_config or {}  # Store optical sensor configuration
        # Per-sensor stale timeout factor (multiplied with sampling interval); None -> use global default
        self.stale_timeout_factor = stale_timeout_factor
        
        # Calibration data - stores full calibration including points
        self.calibration_data = None  # Will hold dict with method, coefficients, gain, points, etc.
        
    def process_reading(self, raw_value):
        """Process a raw sensor reading, applying calibration if available"""
        if raw_value is None:
            return None
            
        try:
            raw_float = float(raw_value)
            
            # Apply calibration if available
            if self.calibration_data:
                processed_value = self._apply_calibration(raw_float)
            else:
                # Fallback to simple offset + conversion factor
                processed_value = (raw_float * self.conversion_factor) + self.offset
            
            self.current_value = processed_value
            self.history.append(processed_value)
            return processed_value
        except (ValueError, TypeError):
            return None
    
    def _apply_calibration(self, raw_value):
        """Apply full calibration to a raw value
        
        Supports:
        - Linear: y = gain * x + offset
        - Polynomial: y = c[0]*x^n + c[1]*x^(n-1) + ... + c[n]
        - Offset+Gain: y = gain * x + offset
        """
        import numpy as np
        
        method = self.calibration_data.get('method', 'linear')
        coefficients = self.calibration_data.get('coefficients', [])
        
        if method == 'offset_gain' or method == 'linear':
            # Linear calibration: y = gain * x + offset
            gain = self.calibration_data.get('gain', 1.0)
            offset = self.calibration_data.get('offset', 0.0)
            return raw_value * gain + offset
        
        elif 'polynomial' in method and coefficients:
            # Polynomial calibration: use numpy polyval
            return float(np.polyval(coefficients, raw_value))
        
        else:
            # Fallback to simple gain + offset
            gain = self.calibration_data.get('gain', 1.0)
            offset = self.calibration_data.get('offset', 0.0)
            return raw_value * gain + offset
    
    def reset_calibration(self):
        """Reset calibration to default (no calibration)"""
        self.calibration_data = None
        self.offset = 0.0
        self.conversion_factor = 1.0
    
    def has_calibration(self):
        """Check if sensor has calibration applied"""
        if self.calibration_data:
            return True
        if self.offset != 0.0:
            return True
        if self.conversion_factor != 1.0:
            return True
        return False
    
    def to_dict(self):
        d = {
            "name": self.name,
            "interface_type": self.interface_type,
            "port": self.port,
            "unit": self.unit,
            "offset": self.offset,
            "conversion_factor": self.conversion_factor,
            "color": self.color,
            "enabled": self.enabled,
            "show_in_graph": self.show_in_graph,
            "averaging_enabled": self.averaging_enabled,
            "sequence_config": self.sequence_config
        }
        if self.stale_timeout_factor is not None:
            d["stale_timeout_factor"] = self.stale_timeout_factor
        if hasattr(self, "mapping") and self.mapping is not None:
            d["mapping"] = self.mapping
        # Save calibration data if present
        if self.calibration_data:
            d["calibration_data"] = self.calibration_data
        # Save audio_config if present (for AudioSensor type)
        if hasattr(self, "audio_config") and self.audio_config:
            d["audio_config"] = self.audio_config
        # Save optical_config if present (for OpticalSensor type)
        if hasattr(self, "optical_config") and self.optical_config:
            d["optical_config"] = self.optical_config
        return d
    
    @classmethod
    def from_dict(cls, data):
        """Create a SensorModel from a dictionary

        This handles all sensor types, including special handling for OtherSerial 
        sensors that need additional configuration attributes set from sequence_config.
        """
        # Create the basic sensor object
        sensor = cls(
            name=data.get("name", ""),
            interface_type=data.get("interface_type", ""),
            port=data.get("port", ""),
            unit=data.get("unit", ""),
            offset=data.get("offset", 0.0),
            conversion_factor=data.get("conversion_factor", 1.0),
            color=data.get("color", "#FFFFFF"),
            enabled=data.get("enabled", True),
            show_in_graph=data.get("show_in_graph", True),
            averaging_enabled=data.get("averaging_enabled", False),
            sequence_config=data.get("sequence_config", {}),
            audio_config=data.get("audio_config", {}),
            optical_config=data.get("optical_config", {}),
            stale_timeout_factor=data.get("stale_timeout_factor", None)
        )
        # Patch: Set mapping if present
        if "mapping" in data:
            sensor.mapping = data["mapping"]
        
        # Load calibration data if present
        if "calibration_data" in data:
            sensor.calibration_data = data["calibration_data"]
        
        # Special handling for OtherSerial sensors - extract additional properties from sequence_config
        if sensor.interface_type == "OtherSerial" and sensor.sequence_config:
            # Set properties directly from sequence_config
            sequence_config = sensor.sequence_config
            sensor.baud_rate = sequence_config.get("baud_rate", 9600)
            sensor.data_bits = sequence_config.get("data_bits", 8)
            sensor.parity = sequence_config.get("parity", "None")
            sensor.stop_bits = sequence_config.get("stop_bits", 1)
            sensor.poll_interval = sequence_config.get("poll_interval", 1.0)
            
            # If there are steps defined, try to create a sequence from them
            if "steps" in sequence_config:
                try:
                    # Import here to avoid circular imports
                    from app.core.interfaces.other_serial_interface import SerialSequence
                    
                    # Create the sequence
                    steps_data = sequence_config.get("steps", [])
                    sensor.sequence = SerialSequence(name=sensor.name)
                    # Note: SerialSequence.from_dict would properly create the steps,
                    # but since we don't have the full dict format that from_dict expects,
                    # we'll handle recreation of the sequence later when the sensor is used
                except ImportError:
                    # If SerialSequence import fails, we'll just keep sequence_config
                    # and the sensor will be recreated when used
                    sensor.sequence = None
        
        # Special handling for LabJack sensors to ensure all properties are set
        elif sensor.interface_type == "LabJack":
            # Properly initialize LabJack-specific properties
            # Make sure the port is exactly as expected for a LabJack channel
            if sensor.port:
                if " - " in sensor.port:
                    # Extract the actual channel name from the description format
                    sensor.port = sensor.port.split(" - ")[0].strip()
                
                # Make sure we don't have a header
                if sensor.port.startswith("---"):
                    sensor.port = ""
                
            # Make sure conversion_factor is properly set
            if sensor.conversion_factor == 0:
                sensor.conversion_factor = 1.0
        
        # Return the fully configured sensor
        return sensor 