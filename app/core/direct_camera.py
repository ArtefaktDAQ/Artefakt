"""
Direct Camera Implementation

A simpler, direct implementation of the camera functionality that works reliably.
"""

import cv2
import os
import time
import sys
import ffmpeg
import traceback
import datetime
import tempfile
import subprocess
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QMutex, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap
import numpy as np
import copy
from scipy.io import wavfile
from .motion_detector import MotionDetector
from .overlay_manager import BaseOverlay
from threading import Thread

# NDI imports are now handled inside methods to avoid driver lock/conflicts

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    sd = None
    print("sounddevice not available: audio recording disabled.")

# Define path to FFmpeg executable - adjust according to your installation
FFMPEG_BINARY = os.environ.get('FFMPEG_BINARY', 'ffmpeg')

# Try to find ffmpeg in common installation locations
def find_ffmpeg():
    """Find the FFmpeg executable in common locations"""
    # Check if already in PATH
    import shutil
    ffmpeg_in_path = shutil.which('ffmpeg')
    if ffmpeg_in_path:
        return ffmpeg_in_path

    # Common installation paths
    possible_paths = [
        # Check current directory
        os.path.join(os.getcwd(), 'ffmpeg.exe'),
        # Windows paths
        r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
        r'C:\ffmpeg\bin\ffmpeg.exe',
        os.path.join(os.path.expanduser('~'), 'ffmpeg', 'bin', 'ffmpeg.exe'),
    ]
    
    for path in possible_paths:
        if os.path.isfile(path):
            return path
            
    return 'ffmpeg'  # Default to just 'ffmpeg' and hope it's in PATH

# Set the FFmpeg binary path
FFMPEG_BINARY = find_ffmpeg()
print(f"Using FFmpeg binary: {FFMPEG_BINARY}")

def get_available_ffmpeg_encoders():
    """Detect available hardware encoders from FFmpeg with actual support check"""
    import subprocess
    import tempfile
    
    # Standard names for codecs we want to check
    codecs = {
        'nvidia': 'h264_nvenc',
        'intel': 'h264_qsv',
        'amd': 'h264_amf',
        'windows': 'h264_mf',
    }
    
    available = []
    
    # First, get the list of supported encoders from the binary
    try:
        result = subprocess.run([FFMPEG_BINARY, '-encoders'], capture_output=True, text=True, check=True)
        supported_in_binary = result.stdout.lower()
    except Exception as e:
        print(f"Error listing FFmpeg encoders: {e}")
        return ['cpu']

    # For each hardware codec, try a small test to see if it actually works with the current hardware/drivers
    for name, codec in codecs.items():
        if codec in supported_in_binary:
            try:
                # Run a very short encoding test (0.1s) to null output
                test_cmd = [
                    FFMPEG_BINARY,
                    '-f', 'lavfi',
                    '-i', 'color=c=black:s=64x64:d=0.1',
                    '-c:v', codec,
                    '-f', 'null',
                    '-'
                ]
                # We use a short timeout and hide all output
                subprocess.run(test_cmd, capture_output=True, timeout=2.0, check=True)
                available.append(name)
                print(f"Hardware encoder verified: {name} ({codec})")
            except Exception:
                # If the test fails, the hardware or driver is likely missing
                print(f"Hardware encoder detected in binary but not supported by system: {name} ({codec})")
    
    available.append('cpu')  # CPU is always available
    return available

AVAILABLE_ENCODERS = get_available_ffmpeg_encoders()
print(f"Available hardware encoders: {AVAILABLE_ENCODERS}")

class DirectCameraThread(QThread):
    """Thread for direct camera capture"""
    # Signal to send frames to the UI
    frame_captured = pyqtSignal(int, QImage)  # Changed from QPixmap to QImage for thread safety
    status_update = pyqtSignal(int, bool, str)  # Added index, connected, message
    recording_status_signal = pyqtSignal(int, bool)  # Added index, recording status
    motion_detected_signal = pyqtSignal(int, bool) # Added index, Signal for motion detection status
    framerate_warning_signal = pyqtSignal(int, float, float)  # Added index, expected_fps, actual_fps
    
    def __init__(self, index=0, parent=None, main_window=None):
        """Initialize the camera thread"""
        super().__init__(parent)
        
        self.index = index  # Store camera index
        # Store reference to main window for accessing sensor controller
        self.main_window = main_window
        
        # Set thread priority to high but not highest to allow UI thread to breathe
        self.setPriority(QThread.Priority.HighPriority)
        
        # Camera state
        self.camera_id = 0
        self.width = 1280
        self.height = 720
        self.fps = 30
        self.cap = None
        self.ndi_receiver = None
        self.is_ndi = False
        self.ndi_source_obj = None # Store the actual NDI source object
        self.running = False
        self.connected = False
        
        # Camera control settings
        self.manual_focus = True
        self.focus_value = 0
        self.manual_exposure = True
        self.exposure_value = 0
        
        # FPS tracking
        self.actual_fps = 0
        self.framerate_warning_shown = False  # Track if warning was shown for current recording
        
        # Preview throttling
        self.preview_fps = 15
        self.last_preview_time = 0
        self.is_visible = False # Whether this camera is currently visible in UI
        self.preview_mode = "none" # "active", "dashboard", "thumbnail", or "none"
        
        # Recording state
        self.recording = False
        self.recording_start_time = 0
        self.recording_next_frame_time = 0
        self.output_file = ""
        self.video_output_path = ""
        self.output_dir = "recordings"
        self.record_audio = True
        self.audio_enabled = False
        self.audio_stream = None
        self.audio_frames = []
        self.audio_sample_rate = 44100
        self.audio_channels = 1
        self.audio_temp_path = ""
        self.audio_device_index = None  # None means default device
        
        # Video settings
        self.video_quality = 85  # Default quality
        self.ffmpeg_path = FFMPEG_BINARY
        self.direct_streaming = True  # Always use direct streaming
        self.use_hw_accel = True  # Default to True as requested
        
        # Overlay settings
        self.overlays = []  # Will be set from the controller
        self.overlay_mutex = QMutex()  # For thread-safe access to overlays
        self._overlays_changed = False  # Flag to track if overlays need copying
        self._cached_overlays = []  # Cached copy of overlays for frame processing
        
        # Motion detector
        self.motion_detector = MotionDetector()
        self._last_motion_state = False  # Store last motion detection state for overlay
    
    @staticmethod
    def get_audio_input_devices():
        """Get a list of available audio input devices"""
        if not SOUNDDEVICE_AVAILABLE or sd is None:
            return []
        
        try:
            devices = []
            device_list = sd.query_devices()
            for i, dev in enumerate(device_list):
                if dev['max_input_channels'] > 0:
                    devices.append({
                        'index': i,
                        'name': dev['name'],
                        'hostapi': dev['hostapi']
                    })
            return devices
        except Exception as e:
            print(f"Error querying audio devices: {e}")
            return []

    def _apply_focus_settings(self):
        """Apply manual focus to the capture device with backend fallbacks."""
        if not self.cap:
            return False
        
        try:
            # Ensure autofocus is off before applying manual focus
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            
            requested = float(self.focus_value)
            
            # First try the raw value (DirectShow typically expects 0-255)
            success = self.cap.set(cv2.CAP_PROP_FOCUS, requested)
            
            # Some backends (e.g., MSMF) expect a normalized 0-1 value
            if not success:
                success = self.cap.set(cv2.CAP_PROP_FOCUS, requested / 255.0)
            
            reported = self.cap.get(cv2.CAP_PROP_FOCUS)
            print(f"Applied focus (manual={self.manual_focus}): requested={requested}, reported={reported}, success={success}")
            return success
        except Exception as e:
            print(f"Error applying focus settings: {str(e)}")
            traceback.print_exc()
            return False
    
    def connect(self, camera_id, resolution, fps):
        """Setup connection parameters and start background thread for asynchronous connection."""
        try:
            # If already running, stop it first to ensure a clean reconnect
            if self.isRunning():
                print("Camera thread already running, stopping for reconnect...")
                self.running = False
                self.wait(500)
            
            # Reset connection state
            self.connected = False
            self.cap = None
            self.ndi_receiver = None
            
            print(f"Queueing connection to camera {camera_id} with resolution {resolution} at {fps} FPS")
            
            # Parse and store settings for the background thread
            # Handle NDI source which might be a special string or object
            self.is_ndi = False
            self.ndi_source_obj = None
            
            if isinstance(camera_id, str) and camera_id.startswith("NDI:"):
                self.is_ndi = True
                self.camera_id = camera_id
            elif hasattr(camera_id, 'ndi_name'): # It's likely an NDI Source object
                self.is_ndi = True
                self.camera_id = getattr(camera_id, 'ndi_name', str(camera_id))
                self.ndi_source_obj = camera_id
            else:
                try:
                    self.camera_id = int(camera_id)
                except (ValueError, TypeError):
                    self.camera_id = 0
            
            self.fps = int(fps)
            if isinstance(resolution, str) and 'x' in resolution:
                self.width, self.height = map(int, resolution.split('x'))
            else:
                # Default resolution
                self.width, self.height = 1280, 720
            
            # Start the thread - connection will be handled in _perform_connection called by run()
            self.running = True
            self.start()
            
            return True
            
        except Exception as e:
            error_msg = f"Error preparing camera connection: {str(e)}"
            print(error_msg)
            self.status_update.emit(self.index, False, error_msg)
            return False

    def _perform_connection(self):
        """Internal method to perform the actual camera connection (runs in background thread)."""
        # Import inside method to avoid global/local conflicts
        from .interfaces.ndi_interface import NDI_AVAILABLE, NDISourceFinder, NDIReceiver
        
        try:
            print(f"Attempting to connect to camera {self.camera_id} ({self.width}x{self.height}@{self.fps}fps) in background...")
            
            # Make sure any existing camera or NDI receiver is released
            if self.cap:
                print("Releasing existing camera connection")
                self.cap.release()
                self.cap = None
            if self.ndi_receiver:
                print("Releasing existing NDI connection")
                self.ndi_receiver.disconnect()
                self.ndi_receiver = None

            # --- NDI CONNECTION PATH ---
            if self.is_ndi:
                if not NDI_AVAILABLE:
                    error_msg = "NDI libraries not available for reception"
                    print(error_msg)
                    self.status_update.emit(self.index, False, error_msg)
                    return False
                
                print(f"Connecting to NDI source: {self.camera_id}")
                self.ndi_receiver = NDIReceiver()
                
                # If we have the actual object, use it, otherwise we'd need a way to find it by name
                # For now, let's assume we have the object or will handle name lookup in controller
                if self.ndi_source_obj:
                    if self.ndi_receiver.connect(self.ndi_source_obj):
                        self.connected = True
                        
                        # Try to get initial resolution
                        print("NDI connected, attempting to get initial resolution...")
                        initial_frame = self.ndi_receiver.capture_frame(timeout_ms=1000)
                        if initial_frame is not None:
                            f_h, f_w = initial_frame.shape[:2]
                            if f_w > 0 and f_h > 0:
                                self.width = f_w
                                self.height = f_h
                                print(f"Initial NDI resolution: {self.width}x{self.height}")
                        
                        success_msg = f"Connected to NDI source: {self.camera_id}"
                        print(success_msg)
                        self.status_update.emit(self.index, True, success_msg)
                        return True
                    else:
                        error_msg = f"Failed to connect to NDI source: {self.camera_id}"
                        print(error_msg)
                        self.status_update.emit(self.index, False, error_msg)
                        return False
                else:
                    # Fallback: try to find by name if only string was provided
                    finder = NDISourceFinder()
                    sources = finder.get_sources()
                    target_source = None
                    clean_name = self.camera_id.replace("NDI:", "").strip()
                    
                    for s in sources:
                        if getattr(s, 'ndi_name', '') == clean_name or str(s) == clean_name:
                            target_source = s
                            break
                    
                    if target_source and self.ndi_receiver.connect(target_source):
                        self.connected = True
                        
                        # Try to get initial resolution
                        print("NDI connected, attempting to get initial resolution...")
                        initial_frame = self.ndi_receiver.capture_frame(timeout_ms=1000)
                        if initial_frame is not None:
                            f_h, f_w = initial_frame.shape[:2]
                            if f_w > 0 and f_h > 0:
                                self.width = f_w
                                self.height = f_h
                                print(f"Initial NDI resolution: {self.width}x{self.height}")
                        
                        success_msg = f"Connected to NDI source: {self.camera_id}"
                        print(success_msg)
                        self.status_update.emit(self.index, True, success_msg)
                        return True
                    else:
                        error_msg = f"NDI source '{clean_name}' not found on network"
                        print(error_msg)
                        self.status_update.emit(self.index, False, error_msg)
                        return False

            # --- STANDARD CAMERA CONNECTION PATH ---
            # IMPORTANT: Ensure NDI receiver and finder are fully inactive before opening a standard camera
            # to prevent driver conflicts on Windows.
            if self.is_ndi:
                pass # Already handled above
            else:
                # If we're going for a normal camera, we need to be VERY aggressive about cleaning up NDI
                if self.ndi_receiver:
                    print("Destroying NDI receiver before opening standard camera...")
                    try:
                        self.ndi_receiver.disconnect()
                        self.ndi_receiver = None
                    except: pass
                
                # Check if NDI discovery is active and try to suppress it
                if NDI_AVAILABLE:
                    print("NDI available, ensuring discovery is suppressed for webcam...")
                    # We can't easily kill the finder from here if it's in the controller,
                    # but we can try to set the env var just in case
                    os.environ["NDI_SKIP_LOCAL_SOURCES"] = "1"

            # Try to connect using different backends
            import platform
            backends = []
            if platform.system() == 'Windows':
                print("Windows system detected, trying different camera backends...")
                # Try Media Foundation first as it's modern and less likely to conflict with NDI's DSHOW hooks
                backends = [cv2.CAP_MSMF, cv2.CAP_DSHOW, cv2.CAP_ANY]
            else:
                backends = [cv2.CAP_ANY]

            self.cap = None
            for backend in backends:
                print(f"Attempting camera connection with backend: {backend}...")
                self.cap = cv2.VideoCapture(self.camera_id, backend)
                if self.cap and self.cap.isOpened():
                    # --- WAKE-UP ROUTINE ---
                    # Some drivers (like C920) can get stuck. Setting a low resolution 
                    # can sometimes "wake them up".
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
                    time.sleep(0.1)
                    
                    # Now set the actual requested resolution
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                    self.cap.set(cv2.CAP_PROP_FPS, self.fps)
                    
                    # Test if we can actually read a frame and it's not all zeros (black)
                    # We try up to 2 times to give the driver a chance to produce a real frame
                    for retry in range(2):
                        ret, frame = self.cap.read()
                        if ret and frame is not None:
                            mean_val = np.mean(frame)
                            std_val = np.std(frame)
                            
                            if mean_val > 0.1 or std_val > 0.1: 
                                print(f"Successfully opened camera with backend {backend} (try {retry+1})")
                                self.connected = True
                                break
                            else:
                                print(f"Backend {backend} (try {retry+1}) returned black frame. Retrying...")
                                time.sleep(0.1)
                        else:
                            print(f"Backend {backend} (try {retry+1}) read failed. Retrying...")
                            time.sleep(0.1)
                    
                    if self.connected:
                        break
                    else:
                        print(f"Backend {backend} failed black frame test. Releasing...")
                        self.cap.release()
                        self.cap = None
                time.sleep(0.1) # Brief gap between attempts

            # Check if camera opened
            if not self.cap or not self.cap.isOpened():
                error_msg = f"Failed to open camera {self.camera_id}. Returned a black frame or driver lock."
                print(error_msg)
                self.status_update.emit(self.index, False, error_msg)
                return False
            
            print("Camera opened successfully, performing wake-up routine...")
            # Set resolution to a small value then back to target to "wake up" the driver
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            time.sleep(0.1)
            
            print("Setting target camera properties...")
            
            # Set resolution and FPS
            try:
                # Set buffer size and other properties to improve FPS
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 3)  # Increase buffer size
                
                # Set resolution
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                
                # Set to maximum FPS
                self.cap.set(cv2.CAP_PROP_FPS, self.fps)
                
                # Apply focus settings
                if self.manual_focus:
                    self._apply_focus_settings()
                else:
                    self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)  # Enable autofocus
                
                # Apply exposure settings
                if self.manual_exposure:
                    self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # Manual exposure (0.25 is the magic value for manual)
                    self.cap.set(cv2.CAP_PROP_EXPOSURE, self.exposure_value)
                else:
                    self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)  # Auto exposure (0.75 is the magic value for auto)
                
                # Reduce format compression for faster processing
                try:
                    # Try setting to a faster codec (MJPG) for the camera feed
                    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                    self.cap.set(cv2.CAP_PROP_FOURCC, fourcc)
                except:
                    print("Could not set camera codec")
                
                print("Camera properties set successfully")
            except Exception as e:
                print(f"Warning: Could not set camera properties: {str(e)}")
            
            print("Testing frame capture...")
            # Test if we can read a frame
            ret, test_frame = self.cap.read()
            if not ret or test_frame is None:
                error_msg = f"Camera {self.camera_id} opened but could not read frames"
                print(error_msg)
                self.status_update.emit(self.index, False, error_msg)
                self.cap.release()
                self.cap = None
                return False
            
            print("Frame capture test successful")
            
            # Get actual properties
            actual_width = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            actual_height = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
            
            print(f"Actual camera properties: {actual_width}x{actual_height}@{actual_fps}fps")
            
            # Update internal state
            if actual_fps > 0 and abs(actual_fps - self.fps) > 1:
                 print(f"Updating internal FPS from {self.fps} to actual {actual_fps}")
                 self.fps = actual_fps
            
            # Final success status
            self.connected = True
            success_msg = f"Connected to camera {self.camera_id} ({self.width}x{self.height}@{self.fps:.1f}fps)"
            print(success_msg)
            self.status_update.emit(self.index, True, success_msg)
            return True
            
        except Exception as e:
            error_msg = f"Error in background camera connection: {str(e)}"
            print(error_msg)
            traceback.print_exc()
            self.status_update.emit(self.index, False, error_msg)
            if self.cap:
                self.cap.release()
                self.cap = None
            return False
    
    def disconnect(self):
        """Disconnect from the camera"""
        try:
            print("DirectCameraThread: Starting disconnect process...")
            
            # First, emit the status update signal to ensure the UI updates
            # immediately even if the thread takes time to stop
            self.connected = False
            self.status_update.emit(self.index, False, "Camera disconnecting...")
            print("DirectCameraThread: Emitted initial disconnection status")
            
            # Stop recording if active (do this before stopping the thread)
            if self.recording:
                print("DirectCameraThread: Stopping active recording...")
                self.stop_recording()
            
            # Stop the thread if running
            if self.running:
                print("DirectCameraThread: Stopping thread...")
                self.running = False
                # Wait with timeout to avoid hanging
                if not self.wait(500):  # Reduced from 5000ms
                    print("DirectCameraThread: Thread did not stop in time. Releasing camera anyway...")
                    # Don't use terminate() - it's unsafe and can leave resources in bad state
                    # Instead, just proceed with cleanup. The thread will exit on next loop iteration.
            
            # Release camera or NDI
            if self.cap:
                print("DirectCameraThread: Releasing camera...")
                try:
                    self.cap.release()
                except Exception as release_error:
                    print(f"Error releasing camera: {release_error}")
                self.cap = None
            
            if self.ndi_receiver:
                print("DirectCameraThread: Releasing NDI receiver...")
                try:
                    self.ndi_receiver.disconnect()
                except Exception as release_error:
                    print(f"Error releasing NDI: {release_error}")
                self.ndi_receiver = None
            
            # Emit the final status update
            print("DirectCameraThread: Set connected to False, emitting final status update...")
            self.status_update.emit(self.index, False, "Camera disconnected")
            print("DirectCameraThread: Disconnect completed")
            
        except Exception as e:
            print(f"Error disconnecting camera: {str(e)}")
            print(traceback.format_exc())
            # Ensure state is updated even on error
            self.connected = False
            self.status_update.emit(self.index, False, f"Error during disconnect: {str(e)}")
    
    def stop(self):
        """Stop the camera thread"""
        try:
            # Stop the thread
            self.running = False
            self.wait()
            
            # Stop recording if active
            if self.recording:
                self.stop_recording()
                
            # Release camera or NDI
            if self.cap:
                self.cap.release()
                self.cap = None
            if self.ndi_receiver:
                self.ndi_receiver.disconnect()
                self.ndi_receiver = None
                
            # Update state
            self.connected = False
            self.status_update.emit(self.index, False, "Camera stopped")
            
        except Exception as e:
            print(f"Error stopping camera: {str(e)}")
    
    def _start_audio_capture(self):
        """Begin capturing audio from the default microphone."""
        if not self.record_audio:
            self.audio_enabled = False
            return False
        
        if not SOUNDDEVICE_AVAILABLE or sd is None:
            print("Audio recording requested but sounddevice is not available.")
            self.audio_enabled = False
            return False
        
        try:
            self.audio_frames = []
            self.audio_temp_path = ""
            self.audio_enabled = True
            
            self.audio_stream = sd.InputStream(
                device=self.audio_device_index,
                samplerate=self.audio_sample_rate,
                channels=self.audio_channels,
                dtype="float32",
                callback=self._audio_callback,
            )
            self.audio_stream.start()
            print(f"Audio capture started at {self.audio_sample_rate} Hz ({self.audio_channels} channel).")
            return True
        except Exception as e:
            print(f"Failed to start audio capture: {e}")
            traceback.print_exc()
            self.audio_stream = None
            self.audio_enabled = False
            return False
    
    def _audio_callback(self, indata, frames, time_info, status):
        """Audio callback collecting microphone samples while recording."""
        try:
            if not self.recording or not self.audio_enabled:
                return
            # Copy to avoid referencing the internal buffer
            self.audio_frames.append(indata.copy())
        except Exception as e:
            print(f"Audio callback error: {e}")
    
    def _stop_audio_capture(self):
        """Stop audio capture and persist to a temporary WAV file."""
        if self.audio_stream:
            try:
                self.audio_stream.stop()
                self.audio_stream.close()
            except Exception as e:
                print(f"Error stopping audio stream: {e}")
            finally:
                self.audio_stream = None
        
        if not self.audio_enabled or not self.audio_frames:
            return None
        
        try:
            audio_data = np.concatenate(self.audio_frames, axis=0)
            # Convert float32 [-1,1] to int16 PCM
            audio_int16 = np.clip(audio_data * 32767, -32768, 32767).astype(np.int16)
            temp_dir = tempfile.mkdtemp()
            self.audio_temp_path = os.path.join(temp_dir, "audio.wav")
            wavfile.write(self.audio_temp_path, self.audio_sample_rate, audio_int16)
            print(f"Audio captured to {self.audio_temp_path}")
            return self.audio_temp_path
        except Exception as e:
            print(f"Failed to save audio data: {e}")
            traceback.print_exc()
            self.audio_temp_path = ""
            return None
    
    def _mux_audio_with_video(self, video_path, audio_path, final_path):
        """Mux recorded audio into the video file using FFmpeg."""
        if not video_path or not audio_path:
            return
        if not os.path.exists(video_path) or not os.path.exists(audio_path):
            print("Mux skipped: video or audio path missing.")
            return
        
        base, ext = os.path.splitext(final_path)
        audio_codec = "aac" if ext.lower() == ".mp4" else "pcm_s16le"
        
        # Avoid overwriting input while reading it
        temp_output = final_path
        if os.path.abspath(video_path) == os.path.abspath(final_path):
            temp_output = f"{base}_av{ext}"
        
        mux_cmd = [
            self.ffmpeg_path,
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", audio_codec,
            "-shortest",
            "-y",
            temp_output
        ]
        print(f"Muxing audio with command: {' '.join(mux_cmd)}")
        try:
            import subprocess
            subprocess.run(mux_cmd, check=True, capture_output=True)
            # If we used a temp output, replace the final file
            if temp_output != final_path:
                os.replace(temp_output, final_path)
            print(f"Muxed audio into {final_path}")
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg mux error: {e}")
            if e.stderr:
                print(f"FFmpeg stderr: {e.stderr}")
        finally:
            # Clean up temporary files
            if video_path != final_path and os.path.exists(video_path):
                try:
                    os.remove(video_path)
                    print(f"Cleaned up temporary video file: {video_path}")
                except Exception as e:
                    print(f"Warning: Could not delete temporary video file {video_path}: {e}")
                    # Try again after a short delay in case file is still locked
                    import time
                    time.sleep(0.5)
                    try:
                        os.remove(video_path)
                        print(f"Successfully deleted temporary video file on retry: {video_path}")
                    except Exception as e2:
                        print(f"Error: Failed to delete temporary video file {video_path} after retry: {e2}")
            if audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                    print(f"Cleaned up temporary audio file: {audio_path}")
                except Exception as e:
                    print(f"Warning: Could not delete temporary audio file {audio_path}: {e}")
    
    def run(self):
        """Thread main method - handles connection then captures frames."""
        try:
            print("Camera thread started")
            # Set thread priority again to ensure it's applied
            self.setPriority(QThread.Priority.HighPriority)
            
            # --- Perform Connection in Background ---
            # If not yet connected, attempt connection now in this thread
            if not self.connected:
                if not self._perform_connection():
                    print("Background connection failed, exiting camera thread")
                    self.running = False
                    return
            # ----------------------------------------
            
            frame_count = 0
            start_time = time.time()
            error_count = 0
            max_errors = 5  # Maximum number of consecutive errors before stopping
            
            # Main capture loop
            while self.running:
                # Brief sleep to allow other threads to run and prevent tight loops
                time.sleep(0.001)
                
                # Check connection status
                is_connected = False
                if self.is_ndi and self.ndi_receiver:
                    is_connected = self.ndi_receiver.is_connected()
                elif self.cap and self.cap.isOpened():
                    is_connected = True
                
                if not is_connected:
                    # Connection lost or not yet established
                    error_count += 1
                    if error_count > max_errors:
                        break
                    time.sleep(0.1)
                    continue

                try:
                    # Capture frame
                    if self.is_ndi and self.ndi_receiver:
                        try:
                            # Robust NDI frame capture
                            frame = self.ndi_receiver.capture_frame(timeout_ms=100)
                            ret = frame is not None
                        except Exception as ndi_err:
                            print(f"NDI Capture Error on Cam {self.index+1}: {ndi_err}")
                            ret = False
                            frame = None
                            time.sleep(0.1) # Cool down on error
                        
                        # For NDI, a timeout isn't necessarily a fatal error
                        if not ret:
                            # Give UI time to breathe even on timeout
                            time.sleep(0.01)
                            continue
                    else:
                        ret, frame = self.cap.read()
                    
                    if ret and frame is not None:
                        # Reset error count on successful frame capture
                        error_count = 0
                        
                        # Sync resolution - especially important for NDI which may not match requested res
                        f_h, f_w = frame.shape[:2]
                        if f_w != self.width or f_h != self.height:
                            if f_w > 0 and f_h > 0:
                                print(f"Camera resolution changed/mismatch: {self.width}x{self.height} -> {f_w}x{f_h}. Updating...")
                                self.width = f_w
                                self.height = f_h
                        
                        # --- Motion Detection --- START
                        motion_detected = self.motion_detector.process_frame(frame)
                        self.motion_detected_signal.emit(self.index, motion_detected)
                        self._last_motion_state = motion_detected  # Store for overlay drawing
                        # --- Motion Detection --- END
                        
                        # Update FPS calculation
                        frame_count += 1
                        current_time = time.time()
                        
                        if current_time - start_time >= 1.0:
                            self.actual_fps = frame_count / (current_time - start_time)
                            
                            # Check framerate during recording
                            if self.recording and not self.framerate_warning_shown and self.actual_fps > 0:
                                if hasattr(self, 'recording_start_time') and self.recording_start_time > 0:
                                    time_since_recording_start = current_time - self.recording_start_time
                                    if time_since_recording_start >= 3.0:
                                        expected_fps = self.fps
                                        fps_threshold = expected_fps * 0.8
                                        if self.actual_fps < fps_threshold:
                                            self.framerate_warning_signal.emit(self.index, expected_fps, self.actual_fps)
                                            self.framerate_warning_shown = True
                            
                            frame_count = 0
                            start_time = current_time
                        
                        # --- Lazy Overlay Application ---
                        frame_with_overlays = None
                        if self.recording or self.is_visible:
                            frame_with_overlays = self.apply_overlays(frame)
                        
                        # Store frame if recording
                        if self.recording and frame_with_overlays is not None:
                            # --- Direct Streaming Only --- 
                            if hasattr(self, 'ffmpeg_process') and self.ffmpeg_process:
                                if frame_count % 10 == 0:
                                    if self.ffmpeg_process.poll() is not None:
                                        print(f"CRITICAL: FFmpeg process cam{self.index+1} died during recording!")
                                        self.recording = False
                                        self.recording_status_signal.emit(self.index, False)
                                        continue

                                try:
                                    if self.ffmpeg_process.stdin:
                                        frame_duration = 1.0 / self.fps
                                        frames_to_send = 0
                                        epsilon = frame_duration * 0.1
                                        
                                        while current_time >= self.recording_next_frame_time - epsilon:
                                            frames_to_send += 1
                                            self.recording_next_frame_time += frame_duration
                                            if frames_to_send > 10:
                                                self.recording_next_frame_time = current_time + frame_duration
                                                break
                                        
                                        if frames_to_send > 0:
                                            if not frame_with_overlays.flags['C_CONTIGUOUS']:
                                                frame_with_overlays = np.ascontiguousarray(frame_with_overlays)
                                            
                                            frame_bytes = frame_with_overlays.tobytes()
                                            
                                            expected_size = self.width * self.height * 3
                                            if len(frame_bytes) != expected_size:
                                                print(f"CRITICAL: Frame byte size mismatch! Got {len(frame_bytes)}, expected {expected_size}. Skipping frame.")
                                            else:
                                                for _ in range(frames_to_send):
                                                    self.ffmpeg_process.stdin.write(frame_bytes)
                                                
                                                if frame_count % 5 == 0:
                                                    self.ffmpeg_process.stdin.flush()
                                                
                                except Exception as write_error:
                                    print(f"Error writing frame to FFmpeg: {str(write_error)}")
                                    if "Broken pipe" in str(write_error) or "Invalid argument" in str(write_error) or (hasattr(write_error, 'errno') and write_error.errno == 32):
                                        self.recording = False
                                        self.recording_status_signal.emit(self.index, False)

                        # --- UI Preview Optimization ---
                        if self.is_visible and frame_with_overlays is not None:
                            effective_fps = self.preview_fps
                            if self.preview_mode == "thumbnail":
                                effective_fps = min(self.preview_fps, 5)
                            
                            preview_interval = 1.0 / effective_fps
                            
                            if current_time - self.last_preview_time >= preview_interval:
                                self.last_preview_time = current_time
                                try:
                                    ui_frame = frame_with_overlays
                                    if self.preview_mode in ["dashboard", "thumbnail"] and self.width > 640:
                                        new_w = 640
                                        new_h = int(640 * self.height / self.width)
                                        ui_frame = cv2.resize(frame_with_overlays, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                                    elif self.preview_mode == "active" and self.width > 1280:
                                        new_w = 1280
                                        new_h = int(1280 * self.height / self.width)
                                        ui_frame = cv2.resize(frame_with_overlays, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

                                    rgb_frame = cv2.cvtColor(ui_frame, cv2.COLOR_BGR2RGB)
                                    h, w, ch = rgb_frame.shape
                                    bytes_per_line = ch * w
                                    q_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
                                    self.frame_captured.emit(self.index, q_image)
                                except Exception as e:
                                    print(f"Error processing frame for UI: {str(e)}")
                                    error_count += 1
                                    continue
                    else:
                        error_count += 1
                        print(f"Failed to read frame (error count: {error_count})")
                        # Give UI time to breathe even on read error
                        time.sleep(0.01)
                    
                    # Check if we've had too many consecutive errors
                    if error_count >= max_errors:
                        print("Too many consecutive errors, stopping camera thread")
                        self.running = False
                        break
                    
                    # Give UI time to breathe every loop
                    time.sleep(0.001)
                    
                except Exception as e:
                    print(f"Error capturing frame: {str(e)}")
                    print("Frame capture traceback:")
                    traceback.print_exc()
                    error_count += 1
                    time.sleep(0.05)  # Brief delay only on error (reduced from 0.1)
            
            # Thread is ending
            if self.cap:
                self.cap.release()
                self.cap = None
            
            self.connected = False
            print("Camera thread stopped")
            # Emit status update to notify controller that camera is disconnected
            self.status_update.emit(self.index, False, "Camera disconnected (thread stopped)")
            
        except Exception as e:
            print(f"Error in camera thread: {str(e)}")
            print("Camera thread traceback:")
            traceback.print_exc()
            self.connected = False
            self.status_update.emit(self.index, False, f"Camera thread error: {str(e)}")
    
    def start_recording(self, output_dir=None, filename=None, codec=None, use_direct_streaming=None, record_audio=True, audio_device_index=None, use_hw_accel=None):
        """Start recording video (optionally with audio)
        
        Args:
            output_dir: Directory to save the recording
            filename: Name of the output file (if None, will be generated)
            codec: Video codec to use (if None, will use default)
            use_direct_streaming: Whether to use direct FFmpeg streaming
            record_audio: Whether to capture microphone audio
            audio_device_index: Index of the audio device to use (if None, use default)
            use_hw_accel: Whether to use hardware acceleration
        """
        if not self.connected:
            print("Start recording failed: Camera not connected.")
            self.recording_status_signal.emit(self.index, False)
            return False
            
        if not self.is_ndi and not self.cap:
            print("Start recording failed: Standard camera capture object invalid.")
            self.recording_status_signal.emit(self.index, False)
            return False
            
        if self.is_ndi and not self.ndi_receiver:
            print("Start recording failed: NDI receiver object invalid.")
            self.recording_status_signal.emit(self.index, False)
            return False
        
        if self.recording:
            print("Start recording called, but already recording.")
            # Ensure signal reflects current state
            self.recording_status_signal.emit(self.index, True) 
            return True  # Already recording
        
        print(f"Attempting to start recording. Received use_direct_streaming flag: {use_direct_streaming}")
        
        try:
            # Set audio device index
            self.audio_device_index = audio_device_index
            
            # Set output directory
            if output_dir:
                self.output_dir = output_dir
            print(f"Output directory set to: {self.output_dir}")
            
            # Create output directory if needed
            os.makedirs(self.output_dir, exist_ok=True)
            
            # Set output filename
            if filename:
                self.output_file = os.path.join(self.output_dir, filename)
            else:
                # Generate output filename with timestamp
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                self.output_file = os.path.join(self.output_dir, f"webcam_{timestamp}.mp4")
            print(f"Output file set to: {self.output_file}")
            
            # Set codec
            if codec:
                self.codec = codec
            else:
                self.codec = "MJPG"  # Default codec
            print(f"Codec set to: {self.codec}")
            
            # Set audio preference (actual availability checked later)
            self.record_audio = bool(record_audio)
            self.audio_enabled = self.record_audio
                
            # Set direct streaming option based on argument received
            if use_direct_streaming is not None:
                self.direct_streaming = bool(use_direct_streaming)
            print(f"Internal direct_streaming flag set to: {self.direct_streaming}")

            # Set hardware acceleration option
            if use_hw_accel is not None:
                self.use_hw_accel = bool(use_hw_accel)
            print(f"Internal use_hw_accel flag set to: {self.use_hw_accel}")
            
            # Determine actual video target path (temp file if muxing later)
            base, ext = os.path.splitext(self.output_file)
            self.video_output_path = self.output_file
            if self.audio_enabled:
                self.video_output_path = f"{base}_video{ext}"
                print(f"Video will be written to temporary path for later mux: {self.video_output_path}")
            
            # Start audio capture if requested
            if self.audio_enabled:
                started = self._start_audio_capture()
                if not started:
                    self.audio_enabled = False
                    print("Audio capture could not be started; continuing with video-only recording.")
            
            # --- Start Direct FFmpeg Streaming --- 
            recording_started_successfully = False
            print("Attempting to start direct FFmpeg streaming...")
            try:
                self._start_direct_ffmpeg_streaming()
                if hasattr(self, 'ffmpeg_process') and self.ffmpeg_process and self.ffmpeg_process.pid:
                    print("Direct FFmpeg streaming process started successfully.")
                    recording_started_successfully = True
                else:
                    print("Direct FFmpeg streaming process did NOT start successfully.")
            except Exception as ffmpeg_start_error:
                print(f"_start_direct_ffmpeg_streaming failed: {ffmpeg_start_error}")
                recording_started_successfully = False 
            
            # --- Finalize Recording Start --- 
            if recording_started_successfully:
                self.recording = True
                self.recording_start_time = time.time()
                self.recording_next_frame_time = self.recording_start_time
                self.framerate_warning_shown = False
                print(f"Recording successfully started at {self.recording_start_time}")
                self.recording_status_signal.emit(self.index, True)
                return True
            else:
                print("Recording failed to start.")
                self.recording = False
                self.ffmpeg_process = None
                self.recording_status_signal.emit(self.index, False)
                return False
                
        except Exception as e:
            print(f"Critical error during start_recording setup: {str(e)}")
            traceback.print_exc()
            self.recording = False
            self.ffmpeg_process = None
            self.recording_status_signal.emit(self.index, False)
            return False
    
    def _start_direct_ffmpeg_streaming(self):
        """Start streaming frames directly to FFmpeg with automatic fallback"""
        try:
            width = self.width
            height = self.height
            fps = self.fps
            
            # Get file extension from output file
            _, ext = os.path.splitext(self.output_file)
            ext = ext.lower().strip('.')
            if not ext: ext = 'mp4'

            # Define encoder configurations
            configs = []
            
            # 1. GPU Encoders (if enabled)
            if self.use_hw_accel:
                if 'nvidia' in AVAILABLE_ENCODERS:
                    configs.append({
                        'name': 'nvidia',
                        'codec': 'h264_nvenc',
                        'args': [
                            "-rc", "vbr", 
                            "-cq", str(max(18, min(51, int(51 - (self.video_quality / 100.0 * 33))))), 
                            "-b:v", "0", 
                            "-preset", "p4", 
                            "-tune", "hq",
                            "-g", "30",       # Keyframe every 30 frames (1s at 30fps) for better seeking
                            "-bf", "0",       # No B-frames for maximum compatibility
                            "-profile:v", "high"
                        ]
                    })
                if 'intel' in AVAILABLE_ENCODERS:
                    configs.append({
                        'name': 'intel',
                        'codec': 'h264_qsv',
                        'args': [
                            "-global_quality", str(max(1, min(51, int(51 - (self.video_quality / 100.0 * 33))))), 
                            "-preset", "balanced",
                            "-g", "30",
                            "-bf", "0"
                        ]
                    })
                if 'amd' in AVAILABLE_ENCODERS:
                    configs.append({
                        'name': 'amd',
                        'codec': 'h264_amf',
                        'args': [
                            "-rc", "vbr_latency", 
                            "-qv", str(int(self.video_quality / 100.0 * 51)),
                            "-g", "30",
                            "-bf", "0"
                        ]
                    })
                if 'windows' in AVAILABLE_ENCODERS:
                    configs.append({
                        'name': 'windows',
                        'codec': 'h264_mf',
                        'args': [
                            "-rate_control", "quality",
                            "-quality", str(self.video_quality)
                        ]
                    })

            # 2. CPU Fallbacks
            if self.codec and self.codec.upper() in ['MJPG', 'MJPEG']:
                configs.append({
                    'name': 'mjpeg',
                    'codec': 'mjpeg',
                    'args': ["-q:v", str(max(2, min(31, int(31 - (self.video_quality / 100.0 * 29)))))]
                })
            else:
                configs.append({
                    'name': 'cpu',
                    'codec': 'libx264',
                    'args': ["-crf", str(max(18, min(51, int(51 - (self.video_quality / 100.0 * 33))))), "-preset", "ultrafast", "-tune", "zerolatency"]
                })

            # Try each configuration until one works
            self.ffmpeg_process = None
            last_error = ""

            for config in configs:
                try:
                    # Input options (MUST come before -i)
                    cmd = [
                        self.ffmpeg_path,
                        "-f", "rawvideo",
                        "-pix_fmt", "bgr24",
                        "-s", f"{width}x{height}",
                        "-r", str(fps),
                        "-i", "-"  # Input from pipe
                    ]
                    
                    # Output options
                    cmd.extend(["-c:v", config['codec']])
                    cmd.extend(config['args'])
                    
                    # Compatibility and finalize
                    # We remove +faststart for now to ensure data is written immediately to disk
                    cmd.extend(["-pix_fmt", "yuv420p", "-y", self.video_output_path])
                    
                    print(f"Attempting FFmpeg start with {config['name']} ({config['codec']})...")
                    print(f"Command: {' '.join(cmd)}")
                    
                    # Redirect stderr to a log file for this attempt
                    log_path = os.path.join("logs", f"ffmpeg_cam{self.index+1}_{config['name']}.log")
                    os.makedirs("logs", exist_ok=True)
                    err_file = open(log_path, "w")
                    
                    proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=err_file,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
                    
                    # Give it a moment to see if it crashes
                    time.sleep(0.3)
                    if proc.poll() is None:
                        # Process is still running!
                        self.ffmpeg_process = proc
                        self.ffmpeg_err_file = err_file # Keep reference to close later
                        print(f"Successfully started FFmpeg with {config['name']} encoder.")
                        return
                    else:
                        # Process died
                        err_file.close()
                        with open(log_path, "r") as f:
                            error_text = f.read()
                        print(f"Encoder {config['codec']} failed to start. Error: {error_text[:100]}...")
                        last_error = error_text
                except Exception as e:
                    print(f"Error trying encoder {config['codec']}: {e}")
                    last_error = str(e)

            # If we get here, no encoder worked
            raise Exception(f"All FFmpeg encoders failed to start. Last error: {last_error}")

        except Exception as e:
            print(f"Error in _start_direct_ffmpeg_streaming: {e}")
            self.recording = False
            self.recording_status_signal.emit(self.index, False)
            raise e 
    
    def stop_recording(self):
        """Stop recording and save the video file"""
        if not self.recording:
            print("Stop recording called, but not currently recording.")
            self.recording_status_signal.emit(self.index, False)
            return
        
        print("Stopping recording.")
        
        # Stop the recording flag first
        self.recording = False
        
        # Reset framerate warning flag for next recording
        self.framerate_warning_shown = False
        
        # Stop audio capture and save to temp if enabled
        audio_path = None
        if self.audio_enabled:
            audio_path = self._stop_audio_capture()
        
        # --- Handle Direct Streaming Finalization ---            
        print("Processing stop for direct streaming mode.")
        if hasattr(self, 'ffmpeg_process') and self.ffmpeg_process:
            # Run FFmpeg finalization in a separate thread to avoid blocking
            ffmpeg_proc = self.ffmpeg_process
            video_path = self.video_output_path
            output_file = self.output_file
            audio_enabled = self.audio_enabled
            
            def finalize_ffmpeg():
                try:
                    # Close stdin pipe to signal end of input to FFmpeg
                    print("Closing FFmpeg stdin...")
                    if ffmpeg_proc.stdin:
                        ffmpeg_proc.stdin.close()
                    
                    # Wait for FFmpeg to finish (with timeout)
                    print("Waiting for FFmpeg process to finish...")
                    try:
                        stdout, stderr = ffmpeg_proc.communicate(timeout=15)
                        
                        if ffmpeg_proc.returncode == 0:
                            print(f"FFmpeg encoding completed successfully.")
                            print(f"Recording saved to {video_path}")
                        else:
                            error_output = stderr.decode(errors='ignore') if stderr else 'None'
                            print(f"FFmpeg error (returncode {ffmpeg_proc.returncode}):")
                            print(f"FFmpeg stderr: {error_output}")
                    except Exception as comm_error:
                        print(f"FFmpeg communication timeout/error: {comm_error}")
                        try:
                            ffmpeg_proc.terminate()
                            ffmpeg_proc.wait(timeout=5)
                        except Exception:
                            pass
                    
                    # Close the error log file if it was opened
                    if hasattr(self, 'ffmpeg_err_file'):
                        try:
                            self.ffmpeg_err_file.close()
                            delattr(self, 'ffmpeg_err_file')
                        except: pass

                    # Mux audio if recorded and paths are available
                    if audio_path and audio_enabled:
                        self._mux_audio_with_video(video_path, audio_path, output_file)
                        
                except Exception as e:
                    print(f"Error in FFmpeg finalization thread: {str(e)}")
                    traceback.print_exc()
            
            # Start finalization in background thread
            finalize_thread = Thread(target=finalize_ffmpeg, daemon=True)
            finalize_thread.start()
            
            # Clean up process reference
            self.ffmpeg_process = None
        else:
            print("No ffmpeg_process found during stop.")

        # Emit signal that recording has stopped
        self.recording_status_signal.emit(self.index, False)
        self.audio_enabled = False
    
    def set_preview_fps(self, fps):
        """Set the maximum FPS for the UI preview"""
        self.preview_fps = max(1, min(60, int(fps)))
        print(f"Camera {self.index+1} preview FPS set to {self.preview_fps}")

    def set_visible(self, visible):
        """Enable or disable processing for UI preview"""
        self.is_visible = bool(visible)
        # print(f"Camera {self.index+1} visibility: {self.is_visible}")
    
    def set_video_quality(self, quality):
        """Set the video quality (0-100)
        
        Args:
            quality (int): Quality value from 0 to 100, where 100 is highest quality
        """
        # Ensure quality is in valid range
        self.video_quality = max(0, min(100, int(quality)))
        print(f"Video quality set to {self.video_quality}%")
    
    def enable_direct_streaming(self, enabled):
        """Enable or disable direct streaming to FFmpeg"""
        self.direct_streaming = bool(enabled)
        print(f"Direct streaming {'enabled' if self.direct_streaming else 'disabled'}")
    
    def set_ffmpeg_binary(self, binary_path):
        """Set the path to FFmpeg binary"""
        if os.path.exists(binary_path):
            self.ffmpeg_path = binary_path
            print(f"FFmpeg binary path set to: {self.ffmpeg_path}")
        else:
            print(f"Warning: FFmpeg binary not found at {binary_path}, using default")
    
    def is_connected(self):
        """Check if camera is connected"""
        return self.connected
    
    def is_recording(self):
        """Check if recording is in progress"""
        return self.recording
    
    def get_actual_fps(self):
        """Get actual FPS being achieved"""
        return self.actual_fps
    
    def set_overlays(self, overlays):
        """Set the overlays to be applied to frames (thread-safe)"""
        self.overlay_mutex.lock()
        self.overlays = overlays.copy() if overlays else []
        self._overlays_changed = True  # Mark that overlays need re-caching
        self.overlay_mutex.unlock()
    
    def get_overlays(self):
        """Get the current overlays (thread-safe)"""
        self.overlay_mutex.lock()
        overlays_copy = self.overlays.copy() if self.overlays else []
        self.overlay_mutex.unlock()
        return overlays_copy
        
    def apply_overlays(self, frame):
        """Apply all overlays to a frame with ROI optimization"""
        if not hasattr(self, 'overlays') or not self.overlays:
            return frame

        # Make a copy of the frame to avoid modifying the original
        result = frame.copy()
        
        try:
            # Thread-safe access to overlays
            self.overlay_mutex.lock()
            if self._overlays_changed:
                # Cache the overlays if they changed
                self._cached_overlays = copy.deepcopy(self.overlays)
                self._overlays_changed = False
            current_overlays = self._cached_overlays
            self.overlay_mutex.unlock()
            
            # Apply each overlay using its specific draw method
            for overlay in current_overlays:
                if isinstance(overlay, BaseOverlay):
                    # For motion overlays, update their state before drawing
                    if hasattr(overlay, 'get_type') and overlay.get_type() == 'motion':
                        overlay.motion_detected = getattr(self, '_last_motion_state', False)
                    overlay.draw(result)
                elif isinstance(overlay, dict):
                    # Fallback for old dictionary-style overlays if any remain
                    obj = BaseOverlay.from_dict(overlay)
                    if obj:
                        if hasattr(obj, 'get_type') and obj.get_type() == 'motion':
                            obj.motion_detected = getattr(self, '_last_motion_state', False)
                        obj.draw(result)
        
        except Exception as e:
            print(f"Error applying overlays: {str(e)}")
            traceback.print_exc()
        
        return result 

    def update_sensor_overlay_data(self, sensor_name, value, unit):
        """Update data for sensor overlays (push model)"""
        self.overlay_mutex.lock()
        data_updated = False
        for overlay in self.overlays:
            if hasattr(overlay, 'get_type') and overlay.get_type() == 'sensor':
                if getattr(overlay, 'sensor_name', '') == sensor_name:
                    overlay.sensor_value = value
                    overlay.sensor_unit = unit
                    data_updated = True
        
        if data_updated:
            self._overlays_changed = True
        self.overlay_mutex.unlock() 

    def set_camera_properties(self, manual_focus=None, focus_value=None, manual_exposure=None, exposure_value=None):
        """Set camera focus and exposure properties"""
        try:
            if manual_focus is not None:
                self.manual_focus = manual_focus
            
            if focus_value is not None:
                # Clamp to typical DirectShow range
                self.focus_value = max(0, min(255, int(focus_value)))
            
            if manual_exposure is not None:
                self.manual_exposure = manual_exposure
            
            if exposure_value is not None:
                self.exposure_value = exposure_value
            
            # Apply settings if camera is connected
            if self.cap and self.connected:
                # Apply focus settings
                if manual_focus is not None or focus_value is not None:
                    if self.manual_focus:
                        self._apply_focus_settings()
                    else:
                        self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)  # Enable autofocus
                
                # Apply exposure settings
                if manual_exposure is not None:
                    if self.manual_exposure:
                        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # Manual exposure (0.25 is the magic value for manual)
                        self.cap.set(cv2.CAP_PROP_EXPOSURE, self.exposure_value)
                    else:
                        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)  # Auto exposure (0.75 is the magic value for auto)
            
            print(f"Camera properties set: manual focus={self.manual_focus}, focus value={self.focus_value}, "
                  f"manual exposure={self.manual_exposure}, exposure value={self.exposure_value}")
            
            return True
        except Exception as e:
            print(f"Error setting camera properties: {str(e)}")
            traceback.print_exc()
            return False 

    # --- Motion Detection Slots --- START
    @pyqtSlot(bool)
    def set_motion_detection_enabled(self, enabled: bool):
        """Slot to enable/disable motion detection."""
        print(f"Setting motion detection enabled: {enabled}")
        self.motion_detector.set_enabled(enabled)

    @pyqtSlot(int, int)
    def update_motion_detection_settings(self, sensitivity: int, min_area: int):
        """Slot to update motion detection sensitivity and min_area."""
        print(f"Updating motion detection settings: Sensitivity={sensitivity}, Min Area={min_area}")
        self.motion_detector.update_settings(sensitivity, min_area)
    # --- Motion Detection Slots --- END 