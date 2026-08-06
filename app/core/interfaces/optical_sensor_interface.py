"""
Optical Sensor Interface

Uses a camera as a sensor for various detection modes:
- Light Events: Detect small bright spots (scintillation, electron impacts)
- Brightness: Measure overall brightness level
- Color Tracking: Track average color values (RGB/HSV)
- Position Tracking: Track position of bright/colored objects
- Particle Counter: Count distinct bright spots
- Fill Level: Detect when a line/level is reached
"""

import cv2
import numpy as np
import time
import os
from collections import deque
from datetime import datetime
from threading import Thread, Lock, Event
from PyQt6.QtCore import QObject, pyqtSignal

from app.core.interfaces.base_interface import BaseInterface


class RpmEstimator:
    """Lightweight estimator that converts brightness modulation into RPM."""

    def __init__(self):
        self.values = deque(maxlen=512)
        self.times = deque(maxlen=512)

    def reset(self):
        self.values.clear()
        self.times.clear()

    def process(self, gray_frame, settings):
        """Compute RPM from a grayscale frame and settings."""
        result = {
            "rpm": 0.0,
            "rpm_freq_hz": 0.0,
            "rpm_confidence": 0.0,
            "rpm_signal_mean": 0.0,
            "rpm_signal_std": 0.0,
            "rpm_roi_mean": 0.0,
            "rpm_roi_size": 0,
        }

        if gray_frame is None or gray_frame.size == 0:
            return result

        h, w = gray_frame.shape[:2]
        roi_x = int(settings.get("rpm_roi_x", 0))
        roi_y = int(settings.get("rpm_roi_y", 0))
        roi_w = int(settings.get("rpm_roi_width", w))
        roi_h = int(settings.get("rpm_roi_height", h))

        # Clamp ROI to frame bounds
        roi_x = max(0, min(roi_x, w - 1))
        roi_y = max(0, min(roi_y, h - 1))
        roi_w = max(1, min(roi_w, w - roi_x))
        roi_h = max(1, min(roi_h, h - roi_y))

        roi = gray_frame[roi_y : roi_y + roi_h, roi_x : roi_x + roi_w]
        roi_mean = float(np.mean(roi))

        now = time.time()
        self.values.append(roi_mean)
        self.times.append(now)

        result.update(
            {
                "rpm_roi_mean": roi_mean,
                "rpm_roi_size": int(roi_w * roi_h),
            }
        )

        # Trim history to configured window
        history_seconds = float(settings.get("rpm_history_seconds", 4.0))
        while len(self.times) > 2 and now - self.times[0] > history_seconds:
            self.times.popleft()
            self.values.popleft()

        if len(self.values) < 8:
            return result

        dt = (self.times[-1] - self.times[0]) / max(len(self.times) - 1, 1)
        if dt <= 0:
            return result

        signal = np.array(self.values, dtype=np.float32)
        result["rpm_signal_mean"] = float(signal.mean())
        result["rpm_signal_std"] = float(signal.std())

        # Remove DC component and apply Hann window to reduce spectral leakage
        signal = signal - signal.mean()
        window = np.hanning(len(signal))
        spectrum = np.abs(np.fft.rfft(signal * window))
        freqs = np.fft.rfftfreq(len(signal), d=dt)

        min_hz = float(settings.get("rpm_min_hz", 0.5))
        max_hz = float(settings.get("rpm_max_hz", 30.0))
        freq_mask = (freqs >= min_hz) & (freqs <= max_hz)
        if not np.any(freq_mask):
            return result

        masked_spectrum = spectrum[freq_mask]
        masked_freqs = freqs[freq_mask]
        if masked_spectrum.size == 0:
            return result

        idx = int(np.argmax(masked_spectrum))
        dom_amp = float(masked_spectrum[idx])
        dom_freq = float(masked_freqs[idx])

        # Estimate confidence relative to noise floor
        noise_floor = float(np.median(masked_spectrum) + 1e-6)
        confidence = dom_amp / noise_floor if noise_floor > 0 else 0.0

        min_prom = float(settings.get("rpm_min_prominence", 3.0))
        pulses_per_rev = max(float(settings.get("rpm_pulses_per_rev", 1.0)), 0.001)

        rpm_value = 0.0
        if confidence >= min_prom:
            rpm_value = dom_freq * 60.0 / pulses_per_rev

        result.update(
            {
                "rpm": float(rpm_value),
                "rpm_freq_hz": dom_freq,
                "rpm_confidence": float(confidence),
            }
        )

        return result


class OpticalSensorThread(QObject):
    """Thread for optical sensor frame processing"""
    
    # Signals
    data_ready = pyqtSignal(dict)  # Emitted when new sensor data is available
    event_detected = pyqtSignal(dict)  # Emitted when an event is detected (with image path if saved)
    status_update = pyqtSignal(bool, str)  # connected, message
    frame_for_display = pyqtSignal(dict)  # Emitted with frame data for dashboard display
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Camera state
        self.camera_id = 0
        self.cap = None
        self.running = False
        self.connected = False
        self.auto_reconnect = True
        self._last_reconnect_attempt = 0
        self._reconnect_interval = 5.0
        
        # Resolution settings (stored for reconnect)
        self.width = 640
        self.height = 480
        self.fps = 30
        
        # Detection settings (mode-specific)
        self.settings = {
            # Light Events mode
            "brightness_threshold": 30,
            "relative_threshold": 3.0,
            "threshold_mode": "absolute",  # "absolute" or "relative"
            "min_pixels": 1,
            "max_pixels": 100,
            
            # Color tracking
            "target_hue": 0,  # 0-179 for OpenCV HSV
            "hue_tolerance": 10,
            "saturation_min": 100,
            
            # Position tracking
            "tracking_method": "brightness",  # "brightness" or "color"
            
            # Fill level detection
            "roi_x": 0,
            "roi_y": 0,
            "roi_width": 100,
            "roi_height": 100,
            "fill_threshold": 128,
            "fill_direction": "horizontal",  # "horizontal" or "vertical"
            
            # Brightness measurement
            "brightness_roi_x": 0,
            "brightness_roi_y": 0,
            "brightness_roi_width": 640,
            "brightness_roi_height": 480,
            
            # RPM detection
            "rpm_roi_x": 0,
            "rpm_roi_y": 0,
            "rpm_roi_width": 200,
            "rpm_roi_height": 200,
            "rpm_history_seconds": 4.0,
            "rpm_min_hz": 0.5,
            "rpm_max_hz": 30.0,
            "rpm_min_prominence": 3.0,
            "rpm_pulses_per_rev": 1.0,
            
            # General
            "save_event_images": True,
            "output_dir": "optical_events",
            "cooldown_ms": 100,  # Minimum time between events
            "sample_rate": 10,
        }
        
        self.last_sample_time = 0.0
        self.sample_rate = self.settings["sample_rate"]
        
        # Baseline tracking - use deque for O(1) append/pop operations
        self.baseline_buffer = deque(maxlen=30)
        self.baseline_size = 30
        
        # Event tracking
        self.last_event_time = 0
        self.event_count = 0

        # RPM estimator state
        self.rpm_estimator = RpmEstimator()
        
        # Thread control
        self._lock = Lock()
        self._stop_event = Event()
        self._thread = None
        
    def connect(self, camera_id, width=640, height=480, fps=30):
        """Connect to camera"""
        try:
            self.camera_id = int(camera_id)
            self.width = width
            self.height = height
            self.fps = fps
            
            # Try different backends on Windows
            import platform
            if platform.system() == 'Windows':
                self.cap = cv2.VideoCapture(self.camera_id, cv2.CAP_DSHOW)
                if not self.cap.isOpened():
                    self.cap = cv2.VideoCapture(self.camera_id, cv2.CAP_MSMF)
                if not self.cap.isOpened():
                    self.cap = cv2.VideoCapture(self.camera_id)
            else:
                self.cap = cv2.VideoCapture(self.camera_id)
            
            if not self.cap.isOpened():
                self.status_update.emit(False, f"Failed to open camera {self.camera_id}")
                return False
            
            # Set resolution
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_FPS, fps)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            # Test frame
            ret, frame = self.cap.read()
            if not ret or frame is None:
                self.status_update.emit(False, f"Camera {self.camera_id} cannot capture frames")
                self.cap.release()
                self.cap = None
                return False
            
            self.connected = True
            self.status_update.emit(True, f"Optical Sensor connected (Camera {self.camera_id})")
            
            # Start processing thread
            self._stop_event.clear()
            self._thread = Thread(target=self._processing_loop, daemon=True)
            self.running = True
            self._thread.start()
            
            return True
            
        except Exception as e:
            self.status_update.emit(False, f"Error connecting to camera: {str(e)}")
            return False
    
    def disconnect(self):
        """Disconnect from camera"""
        # Stop running first to prevent processing loop from continuing
        self.running = False
        self._stop_event.set()
        
        # Wait for thread to finish before emitting signals
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        
        if self.cap:
            self.cap.release()
            self.cap = None
        
        self.connected = False
        self.baseline_buffer.clear()
        self.rpm_estimator.reset()
        
        # Emit status update only if object is still valid
        try:
            self.status_update.emit(False, "Optical Sensor disconnected")
        except RuntimeError:
            # Object has been deleted, ignore
            pass
    
    def set_mode(self, mode):
        """Set detection mode"""
        with self._lock:
            self.mode = mode
            self.baseline_buffer.clear()  # Reset baseline for new mode
            self.event_count = 0
            self.rpm_estimator.reset()
    
    def update_settings(self, settings_dict):
        """Update detection settings"""
        with self._lock:
            for key, value in settings_dict.items():
                if key in self.settings:
                    self.settings[key] = value
                if key == "sample_rate":
                    self.sample_rate = float(value)
    
    def _processing_loop(self):
        """Main processing loop running in thread"""
        frame_display_counter = 0
        while not self._stop_event.is_set():
            try:
                # Check if object is still valid
                try:
                    if not self.running:
                        break
                except RuntimeError:
                    # Object has been deleted
                    break
                
                # Handle reconnection if camera is closed
                if self.cap is None or not self.cap.isOpened():
                    if self.auto_reconnect:
                        current_time = time.time()
                        if current_time - self._last_reconnect_attempt >= self._reconnect_interval:
                            self._last_reconnect_attempt = current_time
                            print(f"OpticalSensorThread: Connection lost, attempting reconnect to camera {self.camera_id}...")
                            # Close old cap just in case
                            if self.cap:
                                self.cap.release()
                            
                            # Try to reconnect
                            import platform
                            if platform.system() == 'Windows':
                                self.cap = cv2.VideoCapture(self.camera_id, cv2.CAP_DSHOW)
                                if not self.cap or not self.cap.isOpened():
                                    self.cap = cv2.VideoCapture(self.camera_id, cv2.CAP_MSMF)
                                if not self.cap or not self.cap.isOpened():
                                    self.cap = cv2.VideoCapture(self.camera_id)
                            else:
                                self.cap = cv2.VideoCapture(self.camera_id)
                            
                            if self.cap and self.cap.isOpened():
                                # Restore settings
                                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                                self.cap.set(cv2.CAP_PROP_FPS, self.fps)
                                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                                
                                self.connected = True
                                print("OpticalSensorThread: Reconnected successfully")
                                self.status_update.emit(True, f"Optical Sensor reconnected (Camera {self.camera_id})")
                            else:
                                print("OpticalSensorThread: Reconnect failed")
                                self.connected = False
                        
                        time.sleep(1.0)
                        continue
                    else:
                        print("OpticalSensorThread: Connection lost, stopping")
                        break

                ret, frame = self.cap.read()
                if not ret or frame is None:
                    time.sleep(0.01)
                    continue
                
                # Process frame based on mode
                try:
                    with self._lock:
                        mode = self.mode
                        settings = self.settings.copy()
                except RuntimeError:
                    # Object has been deleted
                    break
                
                result = self._process_frame(frame, mode, settings)
                
                if result:
                    # Emit data at sample rate (with error handling)
                    current_time = time.time()
                    if current_time - self.last_sample_time >= 1.0 / self.sample_rate:
                        self.last_sample_time = current_time
                        try:
                            self.data_ready.emit(result)
                        except RuntimeError:
                            # Object has been deleted, exit loop
                            break
                
                # Emit frame for display (at ~15 FPS to reduce load)
                frame_display_counter += 1
                if frame_display_counter >= 2:  # Every 2nd frame
                    frame_display_counter = 0
                    try:
                        self.frame_for_display.emit({
                            'frame': frame.copy(),
                            'mode': mode,
                            'result': result
                        })
                    except RuntimeError:
                        # Object has been deleted, exit loop
                        break
                
            except RuntimeError:
                # Object has been deleted, exit loop
                break
            except Exception as e:
                print(f"Optical sensor processing error: {e}")
                time.sleep(0.1)
    
    def _process_frame(self, frame, mode, settings):
        """Process a single frame based on current mode"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        
        result = {
            "timestamp": time.time(),
            "mode": mode,
        }
        
        if mode == "light_events":
            result.update(self._detect_light_events(frame, gray, settings))
        elif mode == "brightness":
            result.update(self._measure_brightness(gray, settings))
        elif mode == "color":
            result.update(self._track_color(frame, hsv, settings))
        elif mode == "position":
            result.update(self._track_position(frame, gray, hsv, settings))
        elif mode == "particle_count":
            result.update(self._count_particles(gray, settings))
        elif mode == "fill_level":
            result.update(self._detect_fill_level(frame, gray, settings))
        elif mode == "rpm":
            result.update(self._detect_rpm(gray, settings))
        
        return result
    
    def _detect_light_events(self, frame, gray, settings):
        """Detect small light events (scintillation, electron impacts)"""
        result = {
            "event_detected": False,
            "event_count": self.event_count,
            "max_brightness": 0,
            "mean_brightness": 0,
            "bright_pixel_count": 0,
        }
        
        mean_val = np.mean(gray)
        max_val = np.max(gray)
        
        result["mean_brightness"] = float(mean_val)
        result["max_brightness"] = float(max_val)
        
        # Build baseline
        if len(self.baseline_buffer) < self.baseline_size:
            self.baseline_buffer.append(mean_val)
            return result
        
        baseline = np.mean(self.baseline_buffer)
        noise = np.std(self.baseline_buffer) + 0.001  # Avoid division by zero
        
        # Determine threshold
        if settings["threshold_mode"] == "absolute":
            threshold = baseline + settings["brightness_threshold"]
        else:
            threshold = baseline + settings["relative_threshold"] * noise
        
        # Find bright pixels (NO erosion/dilation - we want tiny spots!)
        bright_mask = gray > threshold
        num_bright = np.sum(bright_mask)
        result["bright_pixel_count"] = int(num_bright)
        
        # Check for event
        current_time = time.time()
        cooldown = settings["cooldown_ms"] / 1000.0
        
        if (settings["min_pixels"] <= num_bright <= settings["max_pixels"] and 
            current_time - self.last_event_time > cooldown):
            
            result["event_detected"] = True
            self.event_count += 1
            result["event_count"] = self.event_count
            self.last_event_time = current_time
            
            # Save event image if enabled
            if settings["save_event_images"]:
                image_path = self._save_event_image(frame, gray, bright_mask, settings)
                if image_path:
                    result["image_path"] = image_path
                    
                    # Emit event signal (with error handling)
                    try:
                        self.event_detected.emit({
                            "type": "light_event",
                            "timestamp": current_time,
                            "brightness": float(max_val),
                            "pixel_count": int(num_bright),
                            "image_path": image_path
                        })
                    except RuntimeError:
                        # Object has been deleted, ignore
                        pass
        else:
            # Update baseline only when no event
            # deque with maxlen automatically removes oldest item when full
            self.baseline_buffer.append(mean_val)
        
        return result
    
    def _measure_brightness(self, gray, settings):
        """Measure brightness in the ROI"""
        h_frame, w_frame = gray.shape
        x = int(settings.get("brightness_roi_x", 0))
        y = int(settings.get("brightness_roi_y", 0))
        w = int(settings.get("brightness_roi_width", w_frame))
        h = int(settings.get("brightness_roi_height", h_frame))
        
        # Clamp ROI to frame bounds
        x = max(0, min(x, w_frame - 1))
        y = max(0, min(y, h_frame - 1))
        w = max(1, min(w, w_frame - x))
        h = max(1, min(h, h_frame - y))
        
        roi = gray[y:y+h, x:x+w]
        
        return {
            "brightness_mean": float(np.mean(roi)),
            "brightness_max": float(np.max(roi)),
            "brightness_min": float(np.min(roi)),
            "brightness_std": float(np.std(roi)),
            "brightness_roi_w": int(w),
            "brightness_roi_h": int(h)
        }
    
    def _track_color(self, frame, hsv, settings):
        """Track color values"""
        # Calculate mean color in BGR
        mean_bgr = np.mean(frame, axis=(0, 1))
        mean_hsv = np.mean(hsv, axis=(0, 1))
        
        # Track specific color if target_hue is set
        hue = settings.get("target_hue", 0)
        tolerance = settings.get("hue_tolerance", 10)
        sat_min = settings.get("saturation_min", 100)
        
        # Create mask for target color
        lower = np.array([max(0, hue - tolerance), sat_min, 50])
        upper = np.array([min(179, hue + tolerance), 255, 255])
        color_mask = cv2.inRange(hsv, lower, upper)
        color_percentage = np.sum(color_mask > 0) / color_mask.size * 100
        
        return {
            "red": float(mean_bgr[2]),
            "green": float(mean_bgr[1]),
            "blue": float(mean_bgr[0]),
            "hue": float(mean_hsv[0]),
            "saturation": float(mean_hsv[1]),
            "value": float(mean_hsv[2]),
            "target_color_percent": float(color_percentage),
        }
    
    def _track_position(self, frame, gray, hsv, settings):
        """Track position of brightest/colored region"""
        method = settings.get("tracking_method", "brightness")
        
        if method == "brightness":
            # Find brightest region
            _, max_val, _, max_loc = cv2.minMaxLoc(gray)
            x, y = max_loc
        else:
            # Find center of target color
            hue = settings.get("target_hue", 0)
            tolerance = settings.get("hue_tolerance", 10)
            sat_min = settings.get("saturation_min", 100)
            
            lower = np.array([max(0, hue - tolerance), sat_min, 50])
            upper = np.array([min(179, hue + tolerance), 255, 255])
            mask = cv2.inRange(hsv, lower, upper)
            
            moments = cv2.moments(mask)
            if moments["m00"] > 0:
                x = int(moments["m10"] / moments["m00"])
                y = int(moments["m01"] / moments["m00"])
            else:
                x, y = frame.shape[1] // 2, frame.shape[0] // 2
        
        # Normalize to 0-100 range
        height, width = frame.shape[:2]
        x_norm = x / width * 100
        y_norm = y / height * 100
        
        return {
            "position_x": float(x),
            "position_y": float(y),
            "position_x_percent": float(x_norm),
            "position_y_percent": float(y_norm),
        }
    
    def _count_particles(self, gray, settings):
        """Count distinct bright spots"""
        threshold = settings.get("brightness_threshold", 30)
        min_pixels = settings.get("min_pixels", 1)
        max_pixels = settings.get("max_pixels", 100)
        
        # Build baseline
        mean_val = np.mean(gray)
        if len(self.baseline_buffer) < self.baseline_size:
            self.baseline_buffer.append(mean_val)
            return {"particle_count": 0}
        
        baseline = np.mean(self.baseline_buffer)
        
        # Threshold
        _, binary = cv2.threshold(gray, baseline + threshold, 255, cv2.THRESH_BINARY)
        
        # Find contours (particles)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Count particles within size range
        particle_count = 0
        for contour in contours:
            area = cv2.contourArea(contour)
            if min_pixels <= area <= max_pixels:
                particle_count += 1
        
        # Update baseline - deque with maxlen handles removal automatically
        self.baseline_buffer.append(mean_val)
        
        return {
            "particle_count": particle_count,
            "total_contours": len(contours),
        }
    
    def _detect_fill_level(self, frame, gray, settings):
        """Detect fill level in a region of interest"""
        h_frame, w_frame = gray.shape
        roi_x = int(settings.get("roi_x", 0))
        roi_y = int(settings.get("roi_y", 0))
        roi_w = int(settings.get("roi_width", w_frame))
        roi_h = int(settings.get("roi_height", h_frame))
        threshold = settings.get("fill_threshold", 128)
        direction = settings.get("fill_direction", "horizontal")
        
        # Clamp ROI to frame bounds
        roi_x = max(0, min(roi_x, w_frame - 1))
        roi_y = max(0, min(roi_y, h_frame - 1))
        roi_w = max(1, min(roi_w, w_frame - roi_x))
        roi_h = max(1, min(roi_h, h_frame - roi_y))
        
        # Extract ROI
        roi = gray[roi_y:roi_y+roi_h, roi_x:roi_x+roi_w]
        
        # Binary threshold
        _, binary = cv2.threshold(roi, threshold, 255, cv2.THRESH_BINARY)
        
        # Calculate fill level
        if direction == "horizontal":
            # Sum each row, find where it changes
            row_sums = np.sum(binary, axis=1)
            total = np.sum(row_sums > 0)
            fill_level = total / roi_h * 100  # 0% = empty, 100% = full
        else:
            # Sum each column
            col_sums = np.sum(binary, axis=0)
            total = np.sum(col_sums > 0)
            fill_level = total / roi_w * 100
        
        # Detect level change events
        current_time = time.time()
        event_detected = False
        
        # Check if level crossed threshold
        if hasattr(self, '_last_fill_level'):
            level_threshold = settings.get("fill_threshold_percent", 50)
            if (self._last_fill_level < level_threshold <= fill_level or
                self._last_fill_level > level_threshold >= fill_level):
                event_detected = True
                
                if settings["save_event_images"]:
                    image_path = self._save_event_image(frame, gray, binary, settings, "fill_level")
                    if image_path:
                        try:
                            self.event_detected.emit({
                                "type": "fill_level",
                                "timestamp": current_time,
                                "level": fill_level,
                                "image_path": image_path
                            })
                        except RuntimeError:
                            # Object has been deleted, ignore
                            pass
        
        self._last_fill_level = fill_level
        
        return {
            "fill_level": float(fill_level),
            "event_detected": event_detected,
        }

    def _detect_rpm(self, gray, settings):
        """Estimate RPM from brightness modulation inside an ROI."""
        # Reuse estimator to keep state across frames
        result = self.rpm_estimator.process(gray, settings)
        result["rpm_mode"] = "optical"
        return result
    
    def _save_event_image(self, frame, gray, mask, settings, event_type="light_event"):
        """Save event image to output directory"""
        try:
            # Check if run directory is available (preferred location)
            output_dir = settings.get("run_directory")
            if not output_dir or not os.path.exists(output_dir):
                # Fall back to configured output_dir or default
                output_dir = settings.get("output_dir", "optical_events")
            
            os.makedirs(output_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{event_type}_{timestamp}.png"
            filepath = os.path.join(output_dir, filename)
            
            # Create composite image: original + mask overlay
            if mask is not None and mask.shape == gray.shape:
                # Create colored overlay where bright pixels were detected
                overlay = frame.copy()
                overlay[mask > 0] = [0, 0, 255]  # Red for detected pixels
                
                # Blend with original
                result = cv2.addWeighted(frame, 0.7, overlay, 0.3, 0)
            else:
                result = frame
            
            cv2.imwrite(filepath, result)
            print(f"Optical sensor event image saved: {filepath}")
            return filepath
            
        except Exception as e:
            print(f"Error saving event image: {e}")
            return None


class OpticalSensorInterface(BaseInterface):
    """
    Optical Sensor Interface - Uses camera as measurement sensor
    
    Modes:
    - light_events: Detect small bright spots (scintillation, EVOs)
    - brightness: Measure overall brightness
    - color: Track color values
    - position: Track position of objects
    - particle_count: Count bright spots
    - fill_level: Detect fill level changes
    """
    
    DISPLAY_NAME = "Optical"
    DESCRIPTION = "Use a camera as a measurement sensor"
    ICON = "🎥"
    
    HELP_TEXT = """
    <h3>Optical Sensor Interface</h3>
    <p>Uses a camera as a measurement sensor for brightness, color tracking, particle counting, etc.</p>
    <p><b>How to use:</b></p>
    <ol>
        <li>Select the camera device (Camera ID).</li>
        <li>Select the detection mode (Brightness, Color, etc.).</li>
        <li>Once configured, add sensors with interface type 'Optical' and select the desired measurement output.</li>
    </ol>
    """
    
    CONFIG_SCHEMA = {
        "camera_id": {"type": "number", "label": "Camera ID", "default": 0},
        "mode": {
            "type": "list", 
            "label": "Detection Mode", 
            "options": ["light_events", "brightness", "color", "position", "particle_count", "fill_level", "rpm"],
            "default": "light_events"
        }
    }

    # Class-level tracking of which cameras are in use
    _cameras_in_use = set()
    _cameras_lock = Lock()
    
    def __init__(self, camera_id=0, mode="light_events", name="Optical Sensor"):
        """
        Initialize Optical Sensor Interface
        
        Args:
            camera_id: Camera device ID (0, 1, 2, ...)
            mode: Detection mode
            name: Sensor name
        """
        super().__init__(name=name)
        self.camera_id = int(camera_id)
        self.mode = mode
        self.sensor_thread = None
        self.current_data = {}
        self.last_frame = None
        self._data_lock = Lock()
        
        # Resolution settings
        self.width = 640
        self.height = 480
        self.fps = 30
        
    @classmethod
    def is_camera_available(cls, camera_id):
        """Check if a camera is available (not used by another optical sensor)"""
        with cls._cameras_lock:
            return camera_id not in cls._cameras_in_use
    
    @classmethod
    def get_cameras_in_use(cls):
        """Get set of camera IDs currently used as optical sensors"""
        with cls._cameras_lock:
            return cls._cameras_in_use.copy()
    
    @classmethod
    def list_available_cameras(cls, skip_indices=None):
        """List cameras that are available for use using a background scan to avoid UI freeze.
        
        Args:
            skip_indices: List of camera indices to skip probing (e.g. if already in use)
        """
        if skip_indices is None:
            skip_indices = []
            
        available = []
        
        # Check first 5 indices instead of 10 to reduce time
        for i in range(5):
            # If this camera is already known to be in use by us (main camera), 
            # don't probe it as it will cause a disconnect.
            if i in skip_indices:
                continue
                
            if cls.is_camera_available(i):
                # Try to open camera briefly to see if it exists
                # Set a very small timeout if possible, or just accept the delay for one camera
                try:
                    cap = cv2.VideoCapture(i)
                    if cap.isOpened():
                        available.append(i)
                        cap.release()
                except Exception:
                    continue
        return available
    
    def connect(self):
        """Connect to camera and start processing"""
        # Check if camera is already in use
        if not self.is_camera_available(self.camera_id):
            self.error_message = f"Camera {self.camera_id} is already in use as optical sensor"
            return False
        
        try:
            # Mark camera as in use
            with self._cameras_lock:
                self._cameras_in_use.add(self.camera_id)
            
            # Create and start sensor thread
            self.sensor_thread = OpticalSensorThread()
            self.sensor_thread.set_mode(self.mode)
            
            # Connect signals
            self.sensor_thread.data_ready.connect(self._on_data_ready)
            self.sensor_thread.event_detected.connect(self._on_event_detected)
            self.sensor_thread.frame_for_display.connect(self._on_frame_ready)
            
            if self.sensor_thread.connect(self.camera_id, self.width, self.height, self.fps):
                self.connected = True
                self.error_message = ""
                return True
            else:
                # Release camera if connection failed
                with self._cameras_lock:
                    self._cameras_in_use.discard(self.camera_id)
                self.error_message = "Failed to connect to camera"
                return False
                
        except Exception as e:
            with self._cameras_lock:
                self._cameras_in_use.discard(self.camera_id)
            self.error_message = f"Error connecting: {str(e)}"
            return False
    
    def disconnect(self):
        """Disconnect from camera"""
        if self.sensor_thread:
            self.sensor_thread.disconnect()
            self.sensor_thread = None
        
        # Release camera
        with self._cameras_lock:
            self._cameras_in_use.discard(self.camera_id)
        
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
                self.sensor_thread.update_settings(data)
            return True
        except Exception as e:
            self.error_message = f"Error updating settings: {str(e)}"
            return False
    
    def _on_data_ready(self, data):
        """Handle new data from sensor thread"""
        with self._data_lock:
            self.current_data = data
    
    def _on_frame_ready(self, frame_data):
        """Handle new frame for display/AI preview"""
        with self._data_lock:
            self.last_frame = frame_data.get('frame')
    
    def _on_event_detected(self, event):
        """Handle event detection"""
        print(f"Optical Sensor Event: {event}")
    
    def set_mode(self, mode):
        """Set detection mode"""
        self.mode = mode
        if self.sensor_thread:
            self.sensor_thread.set_mode(mode)
    
    def update_settings(self, settings):
        """Update detection settings"""
        if self.sensor_thread:
            self.sensor_thread.update_settings(settings)
    
    @classmethod
    def get_output_keys(cls, mode=None):
        """Get list of possible output keys for a mode (or all modes if None)"""
        mode_outputs = {
            "light_events": ["event_count", "max_brightness", "mean_brightness", "bright_pixel_count"],
            "brightness": ["brightness_mean", "brightness_max", "brightness_min", "brightness_std"],
            "color": ["red", "green", "blue", "hue", "saturation", "value", "target_color_percent"],
            "position": ["position_x", "position_y", "position_x_percent", "position_y_percent"],
            "particle_count": ["particle_count", "total_contours"],
            "fill_level": ["fill_level"],
            "rpm": ["rpm", "rpm_freq_hz", "rpm_confidence", "rpm_signal_mean", "rpm_signal_std"],
        }
        if mode:
            return mode_outputs.get(mode, [])
        # Return all unique keys across all modes
        all_keys = set()
        for keys in mode_outputs.values():
            all_keys.update(keys)
        return sorted(list(all_keys))

    def get_instance_output_keys(self):
        """Get list of output keys for current mode"""
        return self.get_output_keys(self.mode)


# Availability flag
OPTICAL_SENSOR_AVAILABLE = True

