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
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QMutex, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap
import numpy as np
import copy
from scipy.io import wavfile
from .motion_detector import MotionDetector
from .overlay_manager import BaseOverlay
from threading import Thread

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
        # Windows paths
        r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
        r'C:\ffmpeg\bin\ffmpeg.exe',
        os.path.join(os.path.expanduser('~'), 'ffmpeg', 'bin', 'ffmpeg.exe'),
        # Add more potential paths here if needed
    ]
    
    for path in possible_paths:
        if os.path.isfile(path):
            return path
            
    return 'ffmpeg'  # Default to just 'ffmpeg' and hope it's in PATH

# Set the FFmpeg binary path
FFMPEG_BINARY = find_ffmpeg()
print(f"Using FFmpeg binary: {FFMPEG_BINARY}")

class DirectCameraThread(QThread):
    """Thread for direct camera capture"""
    # Signal to send frames to the UI
    frame_captured = pyqtSignal(QPixmap)
    status_update = pyqtSignal(bool, str)  # connected, message
    recording_status_signal = pyqtSignal(bool)  # recording status
    motion_detected_signal = pyqtSignal(bool) # Signal for motion detection status
    framerate_warning_signal = pyqtSignal(float, float)  # expected_fps, actual_fps
    
    def __init__(self, parent=None, main_window=None):
        """Initialize the camera thread"""
        super().__init__(parent)
        
        # Store reference to main window for accessing sensor controller
        self.main_window = main_window
        
        # Set thread priority to highest
        self.setPriority(QThread.Priority.HighestPriority)
        
        # Camera state
        self.camera_id = 0
        self.width = 1280
        self.height = 720
        self.fps = 30
        self.cap = None
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
        
        # Recording state
        self.recording = False
        self.frames_buffer = []
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
        self.direct_streaming = False
        
        # Overlay settings
        self.overlays = []  # Will be set from the controller
        self.overlay_mutex = QMutex()  # For thread-safe access to overlays
        self._overlays_changed = False  # Flag to track if overlays need copying
        self._cached_overlays = []  # Cached copy of overlays for frame processing
        
        # Memory management for buffered recording
        # Limit buffer to ~2GB (approx 300 frames at 1080p)
        self.max_buffer_frames = 300
        self.buffer_warning_emitted = False

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
        """Connect to the camera"""
        try:
            # Check if already connected
            if self.connected:
                print("Camera is already connected")
                return True
                
            print(f"Attempting to connect to camera {camera_id} with resolution {resolution} at {fps} FPS")
            
            # Parse settings
            self.camera_id = int(camera_id)
            self.fps = int(fps)
            if isinstance(resolution, str) and 'x' in resolution:
                self.width, self.height = map(int, resolution.split('x'))
            else:
                # Default resolution
                self.width, self.height = 1280, 720
            
            print(f"Parsed settings: width={self.width}, height={self.height}, fps={self.fps}")
            
            # Make sure any existing camera is released
            if self.cap:
                print("Releasing existing camera connection")
                self.cap.release()
                self.cap = None
            
            # Try to connect using different backends
            import platform
            if platform.system() == 'Windows':
                print("Windows system detected, trying different camera backends...")
                # Try DirectShow first
                print("Attempting DirectShow backend...")
                self.cap = cv2.VideoCapture(self.camera_id, cv2.CAP_DSHOW)
                if not self.cap.isOpened():
                    print("DirectShow failed, trying Media Foundation...")
                    # Try Media Foundation
                    self.cap = cv2.VideoCapture(self.camera_id, cv2.CAP_MSMF)
                if not self.cap.isOpened():
                    print("Media Foundation failed, trying default...")
                    # Try default
                    self.cap = cv2.VideoCapture(self.camera_id)
            else:
                print("Non-Windows system, using default camera backend")
                self.cap = cv2.VideoCapture(self.camera_id)
            
            # Check if camera opened
            if not self.cap.isOpened():
                error_msg = f"Failed to open camera {self.camera_id}"
                print(error_msg)
                self.status_update.emit(False, error_msg)
                self.cap.release()
                self.cap = None
                return False
            
            print("Camera opened successfully, setting properties...")
            
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
                # cv2.CAP_PROP_FOURCC doesn't always work, but we can try
                try:
                    # Try setting to a faster codec (MJPG) for the camera feed
                    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                    self.cap.set(cv2.CAP_PROP_FOURCC, fourcc)
                except:
                    print("Could not set camera codec")
                
                print("Camera properties set successfully")
            except Exception as e:
                print(f"Warning: Could not set camera properties: {str(e)}")
                print("Continuing with default properties...")
            
            print("Testing frame capture...")
            # Test if we can read a frame
            ret, test_frame = self.cap.read()
            if not ret or test_frame is None:
                error_msg = f"Camera {self.camera_id} opened but could not read frames"
                print(error_msg)
                self.status_update.emit(False, error_msg)
                self.cap.release()
                self.cap = None
                return False
            
            print("Frame capture test successful")
            
            # Get actual properties
            actual_width = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            actual_height = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
            
            print(f"Actual camera properties: {actual_width}x{actual_height}@{actual_fps}fps")
            
            # Update with actual values if they differ significantly or if initial FPS was 0
            # This ensures self.fps reflects reality, which is important for recording.
            if actual_fps > 0 and abs(actual_fps - self.fps) > 1:
                 print(f"Updating internal FPS from {self.fps} to actual {actual_fps}")
                 self.fps = actual_fps
            # Use the initially requested FPS if the camera reports 0 or the same value
            # self.width = int(actual_width) # Keep requested width/height
            # self.height = int(actual_height)
            # self.fps = actual_fps # Use actual FPS reported by camera
            
            # Success
            self.connected = True
            success_msg = f"Connected to camera {self.camera_id} ({self.width}x{self.height}@{self.fps:.1f}fps)"
            print(success_msg)
            self.status_update.emit(True, success_msg)
            
            print("Starting camera thread...")
            # Start the thread
            self.running = True
            self.start()
            
            return True
            
        except Exception as e:
            error_msg = f"Error connecting to camera: {str(e)}"
            print(error_msg)
            print("Full traceback:")
            traceback.print_exc()
            self.status_update.emit(False, error_msg)
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
            self.status_update.emit(False, "Camera disconnecting...")
            print("DirectCameraThread: Emitted initial disconnection status")
            
            # Stop recording if active (do this before stopping the thread)
            if self.recording:
                print("DirectCameraThread: Stopping active recording...")
                self.stop_recording()
            
            # Stop the thread if running
            if self.running:
                print("DirectCameraThread: Stopping thread...")
                self.running = False
                # Wait with timeout to avoid hanging - increased timeout for graceful shutdown
                if not self.wait(5000):  # 5 second timeout
                    print("DirectCameraThread: Thread did not stop in time. Releasing camera anyway...")
                    # Don't use terminate() - it's unsafe and can leave resources in bad state
                    # Instead, just proceed with cleanup. The thread will exit on next loop iteration.
            
            # Release camera
            if self.cap:
                print("DirectCameraThread: Releasing camera...")
                try:
                    self.cap.release()
                except Exception as release_error:
                    print(f"Error releasing camera: {release_error}")
                self.cap = None
            
            # Emit the final status update
            print("DirectCameraThread: Set connected to False, emitting final status update...")
            self.status_update.emit(False, "Camera disconnected")
            print("DirectCameraThread: Disconnect completed")
            
        except Exception as e:
            print(f"Error disconnecting camera: {str(e)}")
            print(traceback.format_exc())
            # Ensure state is updated even on error
            self.connected = False
            self.status_update.emit(False, f"Error during disconnect: {str(e)}")
    
    def stop(self):
        """Stop the camera thread"""
        try:
            # Stop the thread
            self.running = False
            self.wait()
            
            # Stop recording if active
            if self.recording:
                self.stop_recording()
                
            # Release camera
            if self.cap:
                self.cap.release()
                self.cap = None
                
            # Update state
            self.connected = False
            self.status_update.emit(False, "Camera stopped")
            
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
        """Thread main method - runs when thread.start() is called"""
        try:
            print("Camera thread started")
            # Set thread priority again to ensure it's applied
            self.setPriority(QThread.Priority.HighestPriority)
            
            frame_count = 0
            start_time = time.time()
            error_count = 0
            max_errors = 5  # Maximum number of consecutive errors before stopping
            
            # Main capture loop
            while self.running and self.cap and self.cap.isOpened():
                try:
                    # Capture frame
                    ret, frame = self.cap.read()
                    
                    if ret and frame is not None:
                        # Reset error count on successful frame capture
                        error_count = 0
                        
                        # --- Motion Detection --- START
                        motion_detected = self.motion_detector.process_frame(frame)
                        self.motion_detected_signal.emit(motion_detected)
                        self._last_motion_state = motion_detected  # Store for overlay drawing
                        # --- Motion Detection --- END
                        
                        # Update FPS calculation
                        frame_count += 1
                        current_time = time.time()
                        if current_time - start_time >= 1.0:
                            self.actual_fps = frame_count / (current_time - start_time)
                            print(f"Current FPS: {self.actual_fps:.1f}")
                            
                            # Check framerate during recording
                            # Wait at least 3 seconds after recording starts before checking FPS
                            if self.recording and not self.framerate_warning_shown and self.actual_fps > 0:
                                # Only check after 3 seconds of recording to get accurate measurement
                                if hasattr(self, 'recording_start_time') and self.recording_start_time > 0:
                                    time_since_recording_start = current_time - self.recording_start_time
                                    
                                    if time_since_recording_start >= 3.0:
                                        # Check if actual FPS is significantly lower than expected (more than 20% lower)
                                        expected_fps = self.fps
                                        fps_threshold = expected_fps * 0.8  # 80% of expected FPS
                                        
                                        if self.actual_fps < fps_threshold:
                                            # Emit warning signal (expected_fps, actual_fps)
                                            self.framerate_warning_signal.emit(expected_fps, self.actual_fps)
                                            self.framerate_warning_shown = True
                                            print(f"Framerate warning: Expected {expected_fps} FPS, but camera is delivering {self.actual_fps:.1f} FPS")
                            
                            frame_count = 0
                            start_time = current_time
                        
                        # Apply overlays if recording with overlays
                        frame_with_overlays = self.apply_overlays(frame)
                        
                        # Store frame if recording
                        if self.recording:
                            # --- Direct Streaming --- 
                            if self.direct_streaming and hasattr(self, 'ffmpeg_process') and self.ffmpeg_process:
                                try:
                                    if self.ffmpeg_process.stdin:
                                        # Calculate how many frames we should have sent by now to maintain target FPS
                                        frame_duration = 1.0 / self.fps
                                        
                                        # Determine how many frames to send to catch up to current time
                                        # This handles cases where the camera is delivering frames slower than target FPS
                                        # by duplicating the current frame to fill the time gaps.
                                        frames_to_send = 0
                                        
                                        # Use a small epsilon (10% of frame duration) to avoid jitter-induced skips
                                        epsilon = frame_duration * 0.1
                                        
                                        while current_time >= self.recording_next_frame_time - epsilon:
                                            frames_to_send += 1
                                            self.recording_next_frame_time += frame_duration
                                            # Safety break to avoid huge bursts if system hangs or time jumps
                                            if frames_to_send > 10:
                                                self.recording_next_frame_time = current_time + frame_duration
                                                break
                                        
                                        # If frames_to_send is 0, it means the camera is delivering frames faster 
                                        # than the target FPS. In this case we skip this frame for the recording
                                        # to maintain correct time synchronization with sensors.
                                        if frames_to_send > 0:
                                            frame_bytes = frame_with_overlays.tobytes()
                                            for _ in range(frames_to_send):
                                                self.ffmpeg_process.stdin.write(frame_bytes)
                                                
                                except Exception as write_error:
                                    print(f"Error writing frame to FFmpeg (direct streaming): {str(write_error)}")
                                    # Consider stopping recording or signaling error if writes fail persistently
                            # --- Buffer Method --- 
                            elif not self.direct_streaming: 
                                # Only buffer if direct streaming is explicitly disabled
                                # Check buffer limit to prevent memory exhaustion
                                if len(self.frames_buffer) < self.max_buffer_frames:
                                    self.frames_buffer.append((frame_with_overlays.copy(), current_time))
                                elif not self.buffer_warning_emitted:
                                    print(f"WARNING: Frame buffer limit ({self.max_buffer_frames}) reached! Consider using direct streaming for longer recordings.")
                                    self.buffer_warning_emitted = True
                            # else: (Direct streaming enabled but ffmpeg_process failed/missing) -> Do nothing, don't buffer.

                        try:
                            # Convert to RGB for Qt
                            rgb_frame = cv2.cvtColor(frame_with_overlays, cv2.COLOR_BGR2RGB)
                            
                            # Convert to QImage and QPixmap
                            h, w, ch = rgb_frame.shape
                            bytes_per_line = ch * w
                            
                            # IMPORTANT: QImage created from external data does NOT copy the data.
                            # We must ensure the numpy array stays alive until QPixmap is created,
                            # or make a copy of the QImage. Using copy() ensures data ownership.
                            q_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
                            
                            # Convert to QPixmap (this is safe now since q_image owns its data)
                            pixmap = QPixmap.fromImage(q_image)
                            
                            # Emit signal with the frame
                            self.frame_captured.emit(pixmap)
                        except Exception as e:
                            print(f"Error processing frame: {str(e)}")
                            print("Frame processing traceback:")
                            traceback.print_exc()
                            error_count += 1
                            continue
                    else:
                        error_count += 1
                        print(f"Failed to read frame (error count: {error_count})")
                    
                    # Check if we've had too many consecutive errors
                    if error_count >= max_errors:
                        print("Too many consecutive errors, stopping camera thread")
                        self.running = False
                        break
                    
                    # No sleep to allow maximum FPS
                    # Removed sleep statement completely
                    
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
            self.status_update.emit(False, "Camera disconnected (thread stopped)")
            
        except Exception as e:
            print(f"Error in camera thread: {str(e)}")
            print("Camera thread traceback:")
            traceback.print_exc()
            self.connected = False
            self.status_update.emit(False, f"Camera thread error: {str(e)}")
    
    def start_recording(self, output_dir=None, filename=None, codec=None, use_direct_streaming=None, record_audio=True, audio_device_index=None):
        """Start recording video (optionally with audio)
        
        Args:
            output_dir: Directory to save the recording
            filename: Name of the output file (if None, will be generated)
            codec: Video codec to use (if None, will use default)
            use_direct_streaming: Whether to use direct FFmpeg streaming
            record_audio: Whether to capture microphone audio
            audio_device_index: Index of the audio device to use (if None, use default)
        """
        if not self.connected or not self.cap:
            print("Start recording failed: Camera not connected or capture object invalid.")
            self.recording_status_signal.emit(False)
            return False
        
        if self.recording:
            print("Start recording called, but already recording.")
            # Ensure signal reflects current state
            self.recording_status_signal.emit(True) 
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
            
            # Determine actual video target path (temp file if muxing later)
            base, ext = os.path.splitext(self.output_file)
            self.video_output_path = self.output_file
            if self.direct_streaming and self.audio_enabled:
                self.video_output_path = f"{base}_video{ext}"
                print(f"Video will be written to temporary path for later mux: {self.video_output_path}")
            
            # Start audio capture if requested
            if self.audio_enabled:
                started = self._start_audio_capture()
                if not started:
                    self.audio_enabled = False
                    print("Audio capture could not be started; continuing with video-only recording.")
            
            # --- Select Recording Method --- 
            recording_started_successfully = False
            if self.direct_streaming:
                print("Attempting to start direct FFmpeg streaming...")
                try:
                    self._start_direct_ffmpeg_streaming() # This raises exception on failure
                    # Check if the process actually started
                    if hasattr(self, 'ffmpeg_process') and self.ffmpeg_process and self.ffmpeg_process.pid:
                         print("Direct FFmpeg streaming process started successfully.")
                         recording_started_successfully = True
                    else:
                         print("Direct FFmpeg streaming process did NOT start successfully.")
                except Exception as ffmpeg_start_error:
                    print(f"_start_direct_ffmpeg_streaming failed: {ffmpeg_start_error}")
                    # Fallback is not desired, so we fail here
                    recording_started_successfully = False 
            else:
                print("Using buffered frame recording method.")
                # Clear frames buffer for traditional method
                self.frames_buffer = []
                recording_started_successfully = True # Buffer method setup is simple
            
            # --- Finalize Recording Start --- 
            if recording_started_successfully:
                self.recording = True
                self.recording_start_time = time.time()
                self.recording_next_frame_time = self.recording_start_time
                self.framerate_warning_shown = False  # Reset warning flag for new recording
                print(f"Recording successfully started at {self.recording_start_time}")
                self.recording_status_signal.emit(True)
                return True
            else:
                print("Recording failed to start.")
                self.recording = False
                self.ffmpeg_process = None # Ensure process is None if start failed
                self.frames_buffer = [] # Ensure buffer is empty
                self.recording_status_signal.emit(False)
                return False
            
        except Exception as e:
            print(f"Critical error during start_recording setup: {str(e)}")
            traceback.print_exc()
            self.recording = False
            self.ffmpeg_process = None
            self.frames_buffer = []
            self.recording_status_signal.emit(False)
            return False
    
    def _start_direct_ffmpeg_streaming(self):
        """Start streaming frames directly to FFmpeg"""
        try:
            # Get frame dimensions from camera
            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = self.fps
            
            # Get file extension from output file
            _, ext = os.path.splitext(self.output_file)
            ext = ext.lower().strip('.')
            
            # Default to mp4 if no extension
            if not ext:
                ext = 'mp4'
                self.output_file = f"{self.output_file}.mp4"
            
            # Set encoding parameters based on file extension and codec
            input_options = []
            video_codec = 'libx264'  # Default codec
            
            # Make sure the quality is applied properly
            print(f"Starting recording with quality setting: {self.video_quality}%")
            
            # Video quality (0-100, higher is better)
            # Correct formula for CRF: higher quality → lower CRF value
            # CRF range for H.264 is 0-51 (lower is better quality)
            # Map our quality 0-100 to 51-18 (inversely, as higher quality means lower CRF)
            # Formula: CRF = 51 - (quality/100 * (51-18))
            crf_value = int(51 - (self.video_quality / 100.0 * (51-18)))
            # Ensure valid CRF range
            crf_value = max(18, min(51, crf_value))  # Don't go below 18 (very high quality)
            
            print(f"Using video quality {self.video_quality}% → CRF {crf_value}")
            
            # Configure based on codec
            if self.codec:
                # Handle various codec naming conventions
                codec_map = {
                    'H264': 'libx264',
                    'XVID': 'libxvid',
                    'MJPG': 'mjpeg',
                    'MJPEG': 'mjpeg'
                }
                video_codec = codec_map.get(self.codec.upper(), self.codec)
            
            if ext == 'avi' and not self.codec:
                video_codec = 'mjpeg'  # Default for AVI
            
            # Determine quality parameter based on codec
            if video_codec == 'mjpeg':
                # For MJPEG, use quality parameter instead of CRF
                # q:v range is 2-31 (lower is better quality)
                # Map our quality 0-100 to 31-2 (inversely)
                qp_value = int(31 - (self.video_quality / 100.0 * (31-2)))
                quality_param = f"-q:v {qp_value}"
                print(f"Using video quality {self.video_quality}% → QP {qp_value} for MJPEG")
            else:
                # For H.264 and other codecs use CRF
                quality_param = f"-crf {crf_value}"
                print(f"Using video quality {self.video_quality}% → CRF {crf_value} for {video_codec}")
            
            # Build command based on codec
            cmd = [
                self.ffmpeg_path, "-f", "rawvideo", "-pix_fmt", "bgr24", 
                "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
                "-c:v", video_codec,
            ]
            
            # Only add these options for x264 codec
            if 'x264' in video_codec:
                cmd.extend(["-preset", "ultrafast", "-tune", "zerolatency"])
            
            # Apply appropriate quality parameter
            cmd.extend(quality_param.split())
            
            # Output options
            cmd.extend([
                '-pix_fmt', 'yuv420p',     # Output pixel format
                '-movflags', '+faststart', # Optimize for streaming
                '-y',                      # Overwrite existing file
                self.video_output_path
            ])
            
            # Print the command for diagnostics
            final_cmd_str = ' '.join(cmd)
            print(f"--- Final FFmpeg Command (Direct Streaming) ---")
            print(final_cmd_str)
            print(f"---------------------------------------------")
            
            # Start FFmpeg process
            import subprocess
            self.ffmpeg_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,  # Discard stdout
                stderr=subprocess.DEVNULL,  # Discard stderr
            )
            
            print(f"FFmpeg process started with PID: {self.ffmpeg_process.pid}")
            
        except Exception as e:
            print(f"Error starting direct FFmpeg streaming: {str(e)}")
            traceback.print_exc()
            # Ensure recording state is consistent on failure
            self.recording = False 
            self.ffmpeg_process = None
            self.frames_buffer = []
            # Signal that recording failed to start properly
            self.recording_status_signal.emit(False)
            # Re-raise the exception so the calling function knows it failed
            raise e 
    
    def stop_recording(self):
        """Stop recording and save the video file"""
        if not self.recording:
            print("Stop recording called, but not currently recording.")
            # Ensure signal reflects state if somehow out of sync
            self.recording_status_signal.emit(False)
            return
        
        print(f"Stopping recording. Direct streaming mode: {self.direct_streaming}")
        
        # Stop the recording flag first
        self.recording = False
        
        # Reset buffer warning flag for next recording
        self.buffer_warning_emitted = False
        # Reset framerate warning flag for next recording
        self.framerate_warning_shown = False
        
        # Stop audio capture and save to temp if enabled
        audio_path = None
        if self.audio_enabled:
            audio_path = self._stop_audio_capture()
        
        # --- Handle Direct Streaming Case ---            
        if self.direct_streaming:
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
                        
                        # Mux audio if recorded and paths are available
                        if audio_path and audio_enabled:
                            self._mux_audio_with_video(video_path, audio_path, output_file)
                            
                    except Exception as e:
                        print(f"Error in FFmpeg finalization thread: {str(e)}")
                        traceback.print_exc()
                
                # Start finalization in background thread
                finalize_thread = Thread(target=finalize_ffmpeg, daemon=True)
                finalize_thread.start()
                
                # Clean up process reference (thread will handle the actual process)
                self.ffmpeg_process = None
            else:
                print("Direct streaming was enabled, but no ffmpeg_process found.")
            
            # Always clear buffer in direct streaming mode after stopping
            print("Clearing frame buffer in direct streaming mode.")
            self.frames_buffer = []

        # --- Handle Buffered Recording Case ---            
        else:  # if not self.direct_streaming
            print("Processing stop for buffered recording mode.")
            if len(self.frames_buffer) > 0:
                print(f"Found {len(self.frames_buffer)} frames in buffer. Processing...")
                # Process in background thread to avoid blocking
                buffer_copy = self.frames_buffer.copy()
                self.frames_buffer = []  # Clear buffer immediately
                
                def process_buffer():
                    try:
                        self._process_and_save_recording_from_buffer(buffer_copy, audio_path=audio_path)
                    except Exception as e:
                        print(f"Error processing buffered recording: {e}")
                        traceback.print_exc()
                
                process_thread = Thread(target=process_buffer, daemon=True)
                process_thread.start()
            else:
                print("Buffered recording mode, but frame buffer is empty.")
                self.frames_buffer = []
                print("Frame buffer cleared in buffered mode.")

        # Emit signal that recording has stopped
        print("Emitting recording stopped signal (False).")
        self.recording_status_signal.emit(False)
        
        # Reset audio flag after stopping
        self.audio_enabled = False
    
    def _process_and_save_recording(self, audio_path=None):
        """Process and save recorded frames to video file using FFmpeg"""
        if not self.frames_buffer:
            return
        # Use the instance's frames_buffer
        self._process_and_save_recording_from_buffer(self.frames_buffer, audio_path)
    
    def _process_and_save_recording_from_buffer(self, frames_buffer, audio_path=None):
        """Process and save recorded frames from provided buffer to video file using FFmpeg"""
        if not frames_buffer:
            return
            
        try:
            # Get first frame for dimensions
            first_frame, _ = frames_buffer[0]
            height, width = first_frame.shape[:2]
            
            # Sort frames by timestamp
            frames_buffer.sort(key=lambda x: x[1])
            
            # Create a temporary directory for frame storage
            import tempfile
            temp_dir = tempfile.mkdtemp()
            print(f"Created temporary directory: {temp_dir}")
            
            try:
                # Get quality setting (0-100, where 100 is highest quality)
                # Default to 70 if not set
                quality = getattr(self, 'video_quality', 70)
                print(f"Encoding video with quality setting: {quality}")
                
                # Set encoding parameters for JPEG quality if needed
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
                
                # Save each frame as an image in the temp directory
                frame_files = []
                file_extension = ".png" # Default to PNG for 100% quality
                if quality < 100:
                    file_extension = ".jpg"
                    print(f"Using JPEG ({quality}%) for temporary frames.")
                else:
                    print("Using PNG for temporary frames (100% quality).")

                # Use timestamps to ensure constant framerate even if camera dropped frames
                start_time = frames_buffer[0][1]
                end_time = frames_buffer[-1][1]
                duration = end_time - start_time
                
                # Calculate expected number of frames to maintain real-time duration at target FPS
                expected_frame_count = int(round(duration * self.fps))
                
                # Safety: if duration is zero or negative (invalid timestamps), 
                # or if it would result in 0 frames, fallback to the captured frame count.
                if expected_frame_count <= 0:
                    expected_frame_count = len(frames_buffer)
                
                print(f"Processing {len(frames_buffer)} frames for {duration:.2f}s recording. Target FPS: {self.fps}")
                print(f"Will generate {expected_frame_count} frames to maintain constant framerate and sync.")
                
                frame_files = []
                current_buffer_idx = 0
                
                for i in range(expected_frame_count):
                    # Target time for this frame relative to start
                    target_time = start_time + (i / self.fps)
                    
                    # Find the best frame in buffer for this time slot
                    while (current_buffer_idx + 1 < len(frames_buffer) and 
                           frames_buffer[current_buffer_idx + 1][1] <= target_time):
                        current_buffer_idx += 1
                    
                    frame, _ = frames_buffer[current_buffer_idx]
                    frame_path = os.path.join(temp_dir, f"frame_{i:06d}{file_extension}")
                    
                    # Apply quality compression if quality is less than 100
                    if quality < 100:
                        # Encode the frame to JPEG format with the specified quality and save directly
                        result = cv2.imwrite(frame_path, frame, encode_param)
                        if not result:
                            print(f"Failed to save frame {i} as JPEG")
                            continue
                    else:
                        # Save as PNG if quality is 100
                        result = cv2.imwrite(frame_path, frame)
                        if not result:
                            print(f"Failed to save frame {i} as PNG")
                            continue

                    frame_files.append(frame_path)
                
                # Ensure output directory exists
                os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
                
                # Use ffmpeg to convert the frames to video (and optionally mux audio)
                try:
                    # CRF value mapping from quality 0-100 (higher quality = lower CRF)
                    # Quality 100 -> CRF 17 (near lossless)
                    # Quality 0 -> CRF 35 (lower quality)
                    crf_value = int(35 - (quality / 100.0 * 18))
                    
                    # Verify FFmpeg path exists and is accessible
                    global FFMPEG_BINARY
                    print(f"Using FFmpeg binary: {FFMPEG_BINARY}")
                    if not os.path.exists(FFMPEG_BINARY) and not os.path.isabs(FFMPEG_BINARY):
                        # Try to find FFmpeg in PATH
                        import shutil
                        ffmpeg_in_path = shutil.which(FFMPEG_BINARY)
                        if ffmpeg_in_path:
                            print(f"Found FFmpeg in PATH: {ffmpeg_in_path}")
                            # Update to use the full path
                            FFMPEG_BINARY = ffmpeg_in_path
                        else:
                            print(f"WARNING: FFmpeg not found at {FFMPEG_BINARY} or in PATH")
                    elif os.path.exists(FFMPEG_BINARY):
                        print(f"FFmpeg binary exists at: {FFMPEG_BINARY}")
                    else:
                        print(f"WARNING: FFmpeg not found at {FFMPEG_BINARY}")
                    
                    print(f"Starting FFmpeg encoding to {self.output_file} with CRF {crf_value}")
                    
                    # Use numbered sequence format instead of glob pattern
                    # Ensure the input pattern matches the saved file extension
                    input_pattern = os.path.join(temp_dir, f'frame_%06d{file_extension}')
                    
                    # For diagnostic purposes, show the command that would be executed
                    import subprocess
                    ffmpeg_cmd = [
                        FFMPEG_BINARY,
                        '-framerate', str(self.fps),
                        '-i', input_pattern,  # Use numbered sequence format
                    ]
                    
                    has_audio = audio_path is not None and os.path.exists(audio_path)
                    if has_audio:
                        ffmpeg_cmd.extend(['-i', audio_path])
                    
                    ffmpeg_cmd.extend([
                        '-c:v', 'libx264',
                        '-preset', 'medium',
                        '-crf', str(crf_value),
                    ])
                    
                    if has_audio:
                        ext = os.path.splitext(self.output_file)[1].lower()
                        audio_codec = 'aac' if ext == '.mp4' else 'pcm_s16le'
                        ffmpeg_cmd.extend(['-c:a', audio_codec, '-shortest'])
                    
                    ffmpeg_cmd.extend([
                        '-pix_fmt', 'yuv420p',
                        '-movflags', '+faststart',
                        '-y',  # Overwrite output file
                        self.output_file
                    ])
                    print(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
                    
                    # Try direct subprocess call first - more reliable than ffmpeg-python
                    try:
                        result = subprocess.run(
                            ffmpeg_cmd,
                            capture_output=True,
                            text=True,
                            check=True
                        )
                        print(f"FFmpeg subprocess encoding completed successfully")
                        if result.stdout:
                            print(f"FFmpeg stdout: {result.stdout}")
                        if result.stderr:
                            print(f"FFmpeg stderr: {result.stderr}")
                    except subprocess.CalledProcessError as e:
                        print(f"Subprocess FFmpeg error: {str(e)}")
                        if e.stdout:
                            print(f"FFmpeg stdout: {e.stdout}")
                        if e.stderr:
                            print(f"FFmpeg stderr: {e.stderr}")
                        
                        # Try with ffmpeg-python as fallback
                        print("Trying ffmpeg-python as fallback...")
                        try:
                            # FFmpeg input from images - use numbered sequence format
                            input_args = {
                                'framerate': str(self.fps),
                            }
                            
                            # FFmpeg output settings
                            output_args = {
                                'c:v': 'libx264',     # Use H.264 codec
                                'preset': 'medium',    # Encoding speed/quality balance
                                'crf': str(crf_value),  # Constant Rate Factor (quality - lower is better)
                                'pix_fmt': 'yuv420p',  # Pixel format for maximum compatibility
                                'movflags': '+faststart'  # Enables progressive download
                            }
                            if has_audio:
                                audio_codec = 'aac' if os.path.splitext(self.output_file)[1].lower() == '.mp4' else 'pcm_s16le'
                                output_args.update({'c:a': audio_codec, 'shortest': None})
                            
                            video_input = ffmpeg.input(input_pattern, **input_args)
                            if has_audio:
                                audio_input = ffmpeg.input(audio_path)
                                stream = ffmpeg.output(video_input, audio_input, self.output_file, **output_args)
                            else:
                                stream = ffmpeg.output(video_input, self.output_file, **output_args)
                            
                            stream.overwrite_output().run(capture_stdout=True, capture_stderr=True, cmd=FFMPEG_BINARY)
                            print(f"FFmpeg-python encoding completed successfully")
                        except Exception as ffmpeg_py_error:
                            print(f"FFmpeg-python error: {str(ffmpeg_py_error)}")
                            raise e  # Re-raise the original error if ffmpeg-python also fails
                    
                    print(f"Recording saved to {self.output_file}")
                    
                except Exception as e:
                    print(f"FFmpeg error: {str(e)}")
                    traceback.print_exc()
                    raise
                
            finally:
                # Clean up the temporary files
                import shutil
                try:
                    shutil.rmtree(temp_dir)
                    print(f"Cleaned up temporary directory: {temp_dir}")
                except Exception as cleanup_error:
                    print(f"Error cleaning up temporary directory: {str(cleanup_error)}")
                
                if audio_path and os.path.exists(audio_path):
                    try:
                        os.remove(audio_path)
                    except Exception:
                        pass
        
        except Exception as e:
            print(f"Error processing recording: {str(e)}")
            traceback.print_exc()
            
            # Create a user-visible error message
            from PyQt6.QtWidgets import QMessageBox
            try:
                QMessageBox.critical(
                    None,
                    "Video Encoding Error",
                    f"Failed to encode video recording.\n\n"
                    f"Error: {str(e)}\n\n"
                    f"Please check that FFmpeg is installed at:\n{FFMPEG_BINARY}\n\n"
                    f"You can specify the correct path in Settings → Camera Settings → FFmpeg binary"
                )
            except Exception as ui_error:
                print(f"Could not display error message: {str(ui_error)}")
    
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