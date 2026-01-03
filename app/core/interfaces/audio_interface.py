"""
Audio Sensor Interface

Uses a microphone as a sensor for various measurement modes:
- RMS Level (Root Mean Square): Average "loudness" of the audio signal
- Peak Amplitude: Maximum amplitude in each analysis window
- Dominant Frequency: The most prominent frequency via FFT
- Zero Crossing Rate: Rate at which the signal crosses zero (pitch indicator)
- Custom Frequency Band: Energy in a specific frequency range
- RPM (from frequency): Convert dominant frequency to RPM using pulses-per-revolution

This interface outputs derived values at a configurable rate (e.g., 10-100 Hz)
that can be displayed in the Graph tab like any other sensor.
"""

import numpy as np
import time
from threading import Thread, Lock, Event
from collections import deque
from PyQt6.QtCore import QObject, pyqtSignal

from app.core.interfaces.base_interface import BaseInterface

# Try to import sounddevice
try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    print("Warning: sounddevice not installed. Audio sensor features will be unavailable.")


class AudioSensorThread(QObject):
    """Thread for audio capture and processing"""
    
    # Signals
    data_ready = pyqtSignal(dict)  # Emitted when new derived sensor data is available
    level_update = pyqtSignal(float, float)  # rms_level, peak_level for live meter
    spectrum_update = pyqtSignal(np.ndarray, np.ndarray)  # frequencies, magnitudes for FFT display
    status_update = pyqtSignal(bool, str)  # connected, message
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Audio settings
        self.device_id = None  # None = default device
        self.sample_rate = 44100
        self.channels = 1
        self.chunk_size = 2048  # Samples per chunk (affects latency and frequency resolution)
        
        # Reconnect settings
        self.auto_reconnect = True
        self._last_reconnect_attempt = 0
        self._reconnect_interval = 5.0
        
        # Processing settings
        self.output_rate = 10  # Hz - how often to emit sensor values
        self.last_output_time = 0
        
        # What to measure
        self.measurement_mode = "rms"  # rms, peak, frequency, zero_crossing, band_energy
        self.settings = {
            # Frequency band for band_energy mode
            "band_low": 100,  # Hz
            "band_high": 4000,  # Hz
            
            # Noise gate - ignore signals below this level
            "noise_gate": 0.01,  # 0-1 range
            
            # Peak hold time
            "peak_hold_ms": 500,
            
            # Smoothing (exponential moving average)
            "smoothing": 0.3,  # 0 = no smoothing, 0.99 = heavy smoothing
            
            # RPM conversion (frequency -> RPM)
            "rpm_pulses_per_rev": 1.0,  # pulses/blades per revolution
            
            # Minimum frequency to consider for dominant frequency/RPM (Hz)
            "min_frequency_hz": 5.0,
        }
        
        # State
        self.stream = None
        self.running = False
        self.connected = False
        
        # Audio buffer for processing
        self._audio_buffer = deque(maxlen=self.chunk_size * 4)
        self._lock = Lock()
        self._stop_event = Event()
        
        # Smoothed values
        self._smoothed_rms = 0.0
        self._smoothed_freq = 0.0
        self._peak_hold = 0.0
        self._peak_hold_time = 0.0
        
    @staticmethod
    def list_devices():
        """List available audio input devices"""
        if not SOUNDDEVICE_AVAILABLE:
            return []
        
        devices = []
        try:
            device_list = sd.query_devices()
            for i, device in enumerate(device_list):
                if device['max_input_channels'] > 0:
                    devices.append({
                        'id': i,
                        'name': device['name'],
                        'channels': device['max_input_channels'],
                        'sample_rate': device['default_samplerate'],
                    })
        except Exception as e:
            print(f"Error listing audio devices: {e}")
        return devices
    
    @staticmethod
    def get_default_device():
        """Get the default input device ID"""
        if not SOUNDDEVICE_AVAILABLE:
            return None
        try:
            return sd.default.device[0]  # Input device
        except:
            return None
    
    def connect(self, device_id=None, sample_rate=44100, chunk_size=2048):
        """Start audio capture"""
        if not SOUNDDEVICE_AVAILABLE:
            self.status_update.emit(False, "sounddevice library not available")
            return False
        
        try:
            self.device_id = device_id
            self.sample_rate = sample_rate
            self.chunk_size = chunk_size
            
            # Create audio stream
            self.stream = sd.InputStream(
                device=self.device_id,
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.chunk_size,
                callback=self._audio_callback,
                dtype=np.float32
            )
            
            self.stream.start()
            self.running = True
            self.connected = True
            
            # Start monitoring thread for reconnection
            self._stop_event.clear()
            self._monitor_thread = Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()
            
            device_name = "Default" if device_id is None else str(device_id)
            self.status_update.emit(True, f"Audio connected (Device: {device_name})")
            return True
            
        except Exception as e:
            self.status_update.emit(False, f"Audio connection error: {str(e)}")
            return False
    
    def _monitor_loop(self):
        """Monitor the audio stream and reconnect if it stops"""
        while not self._stop_event.is_set():
            if self.running and self.auto_reconnect:
                if self.stream is None or not self.stream.active:
                    current_time = time.time()
                    if current_time - self._last_reconnect_attempt >= self._reconnect_interval:
                        self._last_reconnect_attempt = current_time
                        print(f"AudioSensorThread: Stream inactive, attempting reconnect...")
                        
                        try:
                            if self.stream:
                                self.stream.stop()
                                self.stream.close()
                        except:
                            pass
                            
                        try:
                            self.stream = sd.InputStream(
                                device=self.device_id,
                                channels=self.channels,
                                samplerate=self.sample_rate,
                                blocksize=self.chunk_size,
                                callback=self._audio_callback,
                                dtype=np.float32
                            )
                            self.stream.start()
                            self.connected = True
                            print("AudioSensorThread: Reconnected successfully")
                            self.status_update.emit(True, f"Audio reconnected")
                        except Exception as e:
                            print(f"AudioSensorThread: Reconnect failed: {e}")
                            self.connected = False
            
            time.sleep(1.0)
    
    def disconnect(self):
        """Stop audio capture"""
        # Stop running first to prevent callbacks from processing
        self.running = False
        self._stop_event.set()
        
        # Stop and close stream before emitting signals
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except:
                pass
            self.stream = None
        
        self.connected = False
        self._audio_buffer.clear()
        
        # Emit status update only if object is still valid
        try:
            self.status_update.emit(False, "Audio disconnected")
        except RuntimeError:
            # Object has been deleted, ignore
            pass
    
    def _audio_callback(self, indata, frames, time_info, status):
        """Callback for audio stream - called for each audio chunk"""
        # Check if object is still valid and running
        try:
            if not self.running or not self.connected:
                return
        except RuntimeError:
            # Object has been deleted
            return
        
        if status:
            print(f"Audio status: {status}")
        
        # Add samples to buffer
        try:
            with self._lock:
                self._audio_buffer.extend(indata[:, 0])
        except RuntimeError:
            # Object has been deleted
            return
        
        # Process the audio
        try:
            self._process_audio(indata[:, 0])
        except RuntimeError:
            # Object has been deleted, ignore
            pass
    
    def _process_audio(self, samples):
        """Process audio samples and emit results"""
        if len(samples) == 0:
            return
        
        # Check if object is still valid
        try:
            if not self.running or not self.connected:
                return
        except RuntimeError:
            # Object has been deleted
            return
        
        current_time = time.time()
        
        # Calculate basic levels for live meter (always)
        rms = np.sqrt(np.mean(samples ** 2))
        peak = np.max(np.abs(samples))
        
        # Peak hold
        if peak > self._peak_hold or current_time - self._peak_hold_time > self.settings["peak_hold_ms"] / 1000.0:
            self._peak_hold = peak
            self._peak_hold_time = current_time
        
        # Emit level update for live meter (with error handling)
        try:
            self.level_update.emit(rms, self._peak_hold)
        except RuntimeError:
            # Object has been deleted, ignore
            return
        
        # Apply noise gate: still emit a zeroed reading so UI clears values
        if rms < self.settings["noise_gate"]:
            alpha = self.settings["smoothing"]
            self._smoothed_rms = alpha * self._smoothed_rms
            self._smoothed_freq = 0.0

            if current_time - self.last_output_time >= 1.0 / self.output_rate:
                self.last_output_time = current_time
                gated_result = {
                    "timestamp": current_time,
                    "mode": self.measurement_mode,
                    "rms": float(self._smoothed_rms),
                    "peak": float(peak),
                    "peak_hold": float(self._peak_hold),
                    "dominant_frequency": 0.0,
                    "band_energy": 0.0,
                    "zero_crossing_rate": 0.0,
                    "db_level": float(20 * np.log10(max(self._smoothed_rms, 1e-10))),
                    "rpm": 0.0,
                }
                try:
                    self.data_ready.emit(gated_result)
                except RuntimeError:
                    pass
            return
        
        # Only emit sensor data at the specified rate
        if current_time - self.last_output_time < 1.0 / self.output_rate:
            return
        
        self.last_output_time = current_time
        
        # Smoothing factor
        alpha = self.settings["smoothing"]
        
        # Calculate values based on mode
        result = {
            "timestamp": current_time,
            "mode": self.measurement_mode,
            "rpm": 0.0,
        }
        
        # Always include RMS and Peak
        self._smoothed_rms = alpha * self._smoothed_rms + (1 - alpha) * rms
        result["rms"] = float(self._smoothed_rms)
        result["peak"] = float(peak)
        result["peak_hold"] = float(self._peak_hold)
        
        # Mode-specific calculations
        if self.measurement_mode in ["frequency", "band_energy"] or True:  # Always calculate for completeness
            # Get more samples for better frequency resolution
            with self._lock:
                if len(self._audio_buffer) >= self.chunk_size:
                    analysis_samples = np.array(list(self._audio_buffer)[-self.chunk_size:])
                else:
                    analysis_samples = samples
            
            # Apply window function
            windowed = analysis_samples * np.hanning(len(analysis_samples))
            
            # FFT
            fft_result = np.fft.fft(windowed)
            freqs = np.fft.fftfreq(len(windowed), 1.0 / self.sample_rate)
            
            # Only positive frequencies
            positive_mask = freqs >= 0
            freqs = freqs[positive_mask]
            magnitudes = np.abs(fft_result[positive_mask])
            
            # Emit spectrum for visualization (with error handling)
            try:
                self.spectrum_update.emit(freqs, magnitudes)
            except RuntimeError:
                # Object has been deleted, skip remaining processing
                return
            
            # Find dominant frequency (skip DC and very low frequencies)
            min_freq = self.settings.get("min_frequency_hz", 20)
            try:
                min_freq = float(min_freq)
            except Exception:
                min_freq = 20
            valid_mask = freqs > max(0.1, min_freq)  # Above threshold
            if np.any(valid_mask):
                valid_freqs = freqs[valid_mask]
                valid_mags = magnitudes[valid_mask]
                dominant_idx = np.argmax(valid_mags)
                dominant_freq = valid_freqs[dominant_idx]
                
                self._smoothed_freq = alpha * self._smoothed_freq + (1 - alpha) * dominant_freq
                result["dominant_frequency"] = float(self._smoothed_freq)
                
                # Convert to RPM using pulses-per-rev setting
                try:
                    ppr = float(self.settings.get("rpm_pulses_per_rev", 1.0))
                    ppr = ppr if ppr != 0 else 1.0
                except Exception:
                    ppr = 1.0
                result["rpm"] = float((self._smoothed_freq * 60.0) / max(ppr, 0.001))
            else:
                result["dominant_frequency"] = 0.0
                result["rpm"] = 0.0
            
            # Band energy
            band_low = self.settings["band_low"]
            band_high = self.settings["band_high"]
            band_mask = (freqs >= band_low) & (freqs <= band_high)
            if np.any(band_mask):
                band_energy = np.sqrt(np.mean(magnitudes[band_mask] ** 2))
                result["band_energy"] = float(band_energy)
            else:
                result["band_energy"] = 0.0
        
        # Zero crossing rate
        zero_crossings = np.sum(np.abs(np.diff(np.sign(samples))) > 0)
        zcr = zero_crossings / len(samples) * self.sample_rate  # Crossings per second
        result["zero_crossing_rate"] = float(zcr)
        
        # dB level (relative to full scale)
        db_level = 20 * np.log10(rms + 1e-10)
        result["db_level"] = float(db_level)
        
        # Emit data (with error handling)
        try:
            self.data_ready.emit(result)
        except RuntimeError:
            # Object has been deleted, ignore
            pass
    
    def set_mode(self, mode):
        """Set measurement mode"""
        self.measurement_mode = mode
    
    def update_settings(self, settings_dict):
        """Update processing settings"""
        for key, value in settings_dict.items():
            if key == "output_rate":
                self.set_output_rate(value)
            elif key in self.settings:
                self.settings[key] = value

    def set_output_rate(self, rate_hz):
        """Update the output rate (Hz) for emitted readings"""
        try:
            rate_int = max(1, int(rate_hz))
        except (TypeError, ValueError):
            return

        self.output_rate = rate_int
        # Reset timer so a new value can be emitted immediately after change
        self.last_output_time = 0


class AudioSensorInterface(BaseInterface):
    """
    Audio Sensor Interface - Uses microphone as measurement sensor
    
    Outputs derived values (RMS, Peak, Frequency, etc.) at a configurable rate
    that can be graphed like any other sensor.
    
    Modes:
    - rms: Root Mean Square level (average loudness)
    - peak: Peak amplitude
    - frequency: Dominant frequency via FFT
    - rpm: RPM estimation from dominant frequency
    - band_energy: Energy in a specific frequency band
    - zero_crossing: Zero crossing rate
    """
    
    # Class-level tracking of which devices are in use
    _devices_in_use = set()
    _devices_lock = Lock()
    
    def __init__(self, device_id=None, mode="rms", name="Audio Sensor"):
        """
        Initialize Audio Sensor Interface
        
        Args:
            device_id: Audio device ID (None = default)
            mode: Measurement mode
            name: Sensor name
        """
        super().__init__(name=name)
        self.device_id = device_id
        self.mode = mode
        self.sensor_thread = None
        self.current_data = {}
        self._data_lock = Lock()
        
        # Audio settings
        self.sample_rate = 44100
        self.chunk_size = 2048
        self.output_rate = 10  # Hz
    
    @classmethod
    def is_device_available(cls, device_id):
        """Check if a device is available"""
        with cls._devices_lock:
            return device_id not in cls._devices_in_use
    
    @classmethod
    def list_available_devices(cls):
        """List available audio input devices"""
        return AudioSensorThread.list_devices()
    
    def connect(self):
        """Connect to audio device and start processing"""
        if not SOUNDDEVICE_AVAILABLE:
            self.error_message = "sounddevice library not installed"
            return False
        
        # Check if device is already in use
        device_key = self.device_id if self.device_id is not None else "default"
        if not self.is_device_available(device_key):
            self.error_message = f"Audio device {device_key} is already in use"
            return False
        
        try:
            # Mark device as in use
            with self._devices_lock:
                self._devices_in_use.add(device_key)
            
            # Create and start sensor thread
            self.sensor_thread = AudioSensorThread()
            self.sensor_thread.set_mode(self.mode)
            self.sensor_thread.output_rate = self.output_rate
            
            # Connect signals
            self.sensor_thread.data_ready.connect(self._on_data_ready)
            
            if self.sensor_thread.connect(self.device_id, self.sample_rate, self.chunk_size):
                self.connected = True
                self.error_message = ""
                return True
            else:
                # Release device if connection failed
                with self._devices_lock:
                    self._devices_in_use.discard(device_key)
                self.error_message = "Failed to connect to audio device"
                return False
                
        except Exception as e:
            with self._devices_lock:
                self._devices_in_use.discard(device_key)
            self.error_message = f"Error connecting: {str(e)}"
            return False
    
    def disconnect(self):
        """Disconnect from audio device"""
        if self.sensor_thread:
            self.sensor_thread.disconnect()
            self.sensor_thread = None
        
        # Release device
        device_key = self.device_id if self.device_id is not None else "default"
        with self._devices_lock:
            self._devices_in_use.discard(device_key)
        
        self.connected = False
    
    def is_connected(self):
        """Check if connected"""
        return self.connected and self.sensor_thread is not None
    
    def read_data(self):
        """Read current sensor data"""
        if not self.is_connected():
            return None
        
        with self._data_lock:
            if self.current_data:
                return self.current_data.copy()
        return None
    
    def write_data(self, data):
        """Update sensor settings"""
        if not self.is_connected() or not self.sensor_thread:
            return False
        
        try:
            if isinstance(data, dict):
                if "mode" in data:
                    self.sensor_thread.set_mode(data["mode"])
                    self.mode = data["mode"]
                if "output_rate" in data:
                    self.set_output_rate(data["output_rate"])
                self.sensor_thread.update_settings(data)
            return True
        except Exception as e:
            self.error_message = f"Error updating settings: {str(e)}"
            return False
    
    def _on_data_ready(self, data):
        """Handle new data from sensor thread"""
        with self._data_lock:
            self.current_data = data
    
    def set_mode(self, mode):
        """Set measurement mode"""
        self.mode = mode
        if self.sensor_thread:
            self.sensor_thread.set_mode(mode)

    def set_output_rate(self, rate_hz):
        """Set output rate and apply to running thread if present"""
        try:
            rate_int = max(1, int(rate_hz))
        except (TypeError, ValueError):
            return

        self.output_rate = rate_int
        if self.sensor_thread:
            self.sensor_thread.set_output_rate(rate_int)
    
    def update_settings(self, settings):
        """Update processing settings"""
        if "output_rate" in settings:
            self.set_output_rate(settings["output_rate"])

        if self.sensor_thread:
            self.sensor_thread.update_settings(settings)
    
    def get_output_keys(self):
        """Get list of output keys for current mode"""
        # Return all available keys - user can choose which to graph
        return [
            "rms",
            "peak", 
            "peak_hold",
            "dominant_frequency",
            "rpm",
            "band_energy",
            "zero_crossing_rate",
            "db_level"
        ]


# Check availability
AUDIO_SENSOR_AVAILABLE = SOUNDDEVICE_AVAILABLE

