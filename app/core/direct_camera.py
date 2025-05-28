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
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QMutex, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap
import numpy as np
import copy
from .motion_detector import MotionDetector

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
        
        # Recording state
        self.recording = False
        self.frames_buffer = []
        self.recording_start_time = 0
        self.output_file = ""
        self.output_dir = "recordings"
        
        # Video settings
        self.video_quality = 85  # Default quality
        self.ffmpeg_path = FFMPEG_BINARY
        self.direct_streaming = False
        
        # Overlay settings
        self.overlays = []  # Will be set from the controller
        self.overlay_mutex = QMutex()  # For thread-safe access to overlays

        # Motion detector
        self.motion_detector = MotionDetector()
    
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
                    self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)  # Disable autofocus
                    self.cap.set(cv2.CAP_PROP_FOCUS, self.focus_value)
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
            
            # Stop the thread if running
            if self.running:
                print("DirectCameraThread: Stopping thread...")
                self.running = False
                # Wait with timeout to avoid hanging
                if not self.wait(3000):  # 3 second timeout
                    print("DirectCameraThread: Thread did not stop naturally, terminating...")
                    self.terminate()
                    self.wait(1000)  # Wait a bit after termination
            
            # Stop recording if active
            if self.recording:
                print("DirectCameraThread: Stopping active recording...")
                self.stop_recording()
            
            # Release camera
            if self.cap:
                print("DirectCameraThread: Releasing camera...")
                self.cap.release()
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
                        # --- Motion Detection --- END
                        
                        # Update FPS calculation
                        frame_count += 1
                        current_time = time.time()
                        if current_time - start_time >= 1.0:
                            self.actual_fps = frame_count / (current_time - start_time)
                            print(f"Current FPS: {self.actual_fps:.1f}")
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
                                        self.ffmpeg_process.stdin.write(frame_with_overlays.tobytes())
                                except Exception as write_error:
                                    print(f"Error writing frame to FFmpeg (direct streaming): {str(write_error)}")
                                    # Consider stopping recording or signaling error if writes fail persistently
                            # --- Buffer Method --- 
                            elif not self.direct_streaming: 
                                # Only buffer if direct streaming is explicitly disabled
                                self.frames_buffer.append((frame_with_overlays.copy(), time.time()))
                            # else: (Direct streaming enabled but ffmpeg_process failed/missing) -> Do nothing, don't buffer.

                        try:
                            # Convert to RGB for Qt - optimize by doing in-place conversion if possible
                            rgb_frame = cv2.cvtColor(frame_with_overlays, cv2.COLOR_BGR2RGB)
                            
                            # Skip the additional copy to save processing time
                            # frame_data = rgb_frame.copy()  # This copy is unnecessary
                            
                            # Convert to QImage and QPixmap
                            h, w, ch = rgb_frame.shape
                            bytes_per_line = ch * w
                            q_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                            
                            # Only make a copy if absolutely necessary
                            # q_image_copy = q_image.copy()  # This copy is unnecessary in most cases
                            
                            # Convert to QPixmap
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
            
        except Exception as e:
            print(f"Error in camera thread: {str(e)}")
            print("Camera thread traceback:")
            traceback.print_exc()
            self.status_update.emit(False, f"Camera thread error: {str(e)}")
    
    def start_recording(self, output_dir=None, filename=None, codec=None, use_direct_streaming=None):
        """Start recording video
        
        Args:
            output_dir: Directory to save the recording
            filename: Name of the output file (if None, will be generated)
            codec: Video codec to use (if None, will use default)
            use_direct_streaming: Whether to use direct FFmpeg streaming
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
                
            # Set direct streaming option based on argument received
            if use_direct_streaming is not None:
                self.direct_streaming = bool(use_direct_streaming)
            print(f"Internal direct_streaming flag set to: {self.direct_streaming}")
            
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
                self.output_file
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
        recording_was_active = False # Flag to track if we actually need to emit stop signal

        try:
            # Stop the recording flag first
            self.recording = False 
            
            # --- Handle Direct Streaming Case ---            
            if self.direct_streaming:
                print("Processing stop for direct streaming mode.")
                if hasattr(self, 'ffmpeg_process') and self.ffmpeg_process:
                    recording_was_active = True # Mark that recording was active
                    try:
                        # Close stdin pipe to signal end of input to FFmpeg
                        print("Closing FFmpeg stdin...")
                        if self.ffmpeg_process.stdin:
                            self.ffmpeg_process.stdin.close()
                        
                        # Wait for FFmpeg to finish
                        print("Waiting for FFmpeg process to finish...")
                        stdout, stderr = self.ffmpeg_process.communicate(timeout=15) # Increased timeout
                        
                        # Check if FFmpeg completed successfully
                        if self.ffmpeg_process.returncode == 0:
                            print(f"FFmpeg encoding completed successfully.")
                            print(f"Recording saved to {self.output_file}")
                        else:
                            # Decode stderr only if it exists
                            error_output = stderr.decode(errors='ignore') if stderr else 'None'
                            print(f"FFmpeg error (returncode {self.ffmpeg_process.returncode}):")
                            print(f"FFmpeg stderr: {error_output}")
                        
                    except Exception as e:
                        print(f"Error communicating with or closing FFmpeg process: {str(e)}")
                        traceback.print_exc()
                        # Try to terminate the process if communication failed
                        try:
                            print("Attempting to terminate FFmpeg process...")
                            self.ffmpeg_process.terminate()
                            self.ffmpeg_process.wait(timeout=5) # Wait briefly after terminate
                        except Exception as term_error:
                            print(f"Error terminating FFmpeg process: {str(term_error)}")
                    finally:
                        # Clean up process object regardless of success/failure
                        self.ffmpeg_process = None
                        print("FFmpeg process cleaned up.")
                else:
                    print("Direct streaming was enabled, but no ffmpeg_process found.")
                
                # Always clear buffer in direct streaming mode after stopping
                print("Clearing frame buffer in direct streaming mode.")
                self.frames_buffer = []

            # --- Handle Buffered Recording Case ---            
            else: # if not self.direct_streaming
                print("Processing stop for buffered recording mode.")
                if len(self.frames_buffer) > 0:
                    recording_was_active = True # Mark that recording was active
                    print(f"Found {len(self.frames_buffer)} frames in buffer. Processing...")
                    self._process_and_save_recording() # Call the original saving method
                else:
                    print("Buffered recording mode, but frame buffer is empty.")
                # Clear buffer after processing or if it was empty
                self.frames_buffer = []
                print("Frame buffer cleared in buffered mode.")

            # --- Final Signal Emission ---            
            # Emit signal that recording has stopped only if it was actually active
            if recording_was_active:
                print("Emitting recording stopped signal (False).")
                self.recording_status_signal.emit(False)
            else:
                 print("Recording was not considered active (no process/no frames), not emitting stop signal.")
                
        except Exception as e:
            print(f"Error during stop_recording: {str(e)}")
            traceback.print_exc()
            # Ensure signal is emitted on unexpected error during stop
            print("Emitting recording stopped signal (False) due to error.")
            self.recording_status_signal.emit(False)
            # Also clear buffer and process on error
            self.frames_buffer = []
            if hasattr(self, 'ffmpeg_process') and self.ffmpeg_process:
                try: self.ffmpeg_process.terminate() 
                except: pass
                self.ffmpeg_process = None
    
    def _process_and_save_recording(self):
        """Process and save recorded frames to video file using FFmpeg"""
        if not self.frames_buffer:
            return
            
        try:
            # Get first frame for dimensions
            first_frame, _ = self.frames_buffer[0]
            height, width = first_frame.shape[:2]
            
            # Sort frames by timestamp
            self.frames_buffer.sort(key=lambda x: x[1])
            
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

                for i, (frame, _) in enumerate(self.frames_buffer):
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
                
                # Use ffmpeg-python to convert the frames to video
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
                        '-c:v', 'libx264',
                        '-preset', 'medium',
                        '-crf', str(crf_value),
                        '-pix_fmt', 'yuv420p',
                        '-movflags', '+faststart',
                        '-y',  # Overwrite output file
                        self.output_file
                    ]
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
                            
                            (
                                ffmpeg
                                .input(input_pattern, **input_args)  # Use numbered sequence format
                                .output(self.output_file, **output_args)
                                .overwrite_output()
                                .run(capture_stdout=True, capture_stderr=True, cmd=FFMPEG_BINARY)
                            )
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
        self.overlay_mutex.unlock()
    
    def get_overlays(self):
        """Get the current overlays (thread-safe)"""
        self.overlay_mutex.lock()
        overlays_copy = self.overlays.copy() if self.overlays else []
        self.overlay_mutex.unlock()
        return overlays_copy
        
    def apply_overlays(self, frame):
        """Apply all overlays to a frame"""
        if not hasattr(self, 'overlays') or not self.overlays:
            return frame

        # Make a copy of the frame to avoid modifying the original
        result = frame.copy()
        
        try:
            # Get the overlay list in a thread-safe way
            self.overlay_mutex.lock()
            current_overlays = copy.deepcopy(self.overlays)
            self.overlay_mutex.unlock()
            
            # Apply each overlay
            for overlay in current_overlays:
                if not overlay.get('visible', True):
                    continue
                
                overlay_type = overlay.get('type', '')
                
                # Get position from the position tuple
                position = overlay.get('position', (10, 30))
                x, y = position
                
                if overlay_type == 'text':
                    text = overlay.get('text', '')
                    font_scale = overlay.get('font_scale', 0.7)
                    thickness = overlay.get('thickness', 2)
                    color = overlay.get('text_color', (0, 255, 0))
                    bg_color = overlay.get('bg_color', (0, 0, 0))
                    bg_alpha = overlay.get('bg_alpha', 50) / 100.0  # Convert from percentage to fraction
                    
                    # Draw text with background
                    # Calculate text size
                    (text_width, text_height), baseline = cv2.getTextSize(
                        text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
                    
                    # Add extra padding to ensure the background covers the text fully
                    padding_x = 8
                    padding_y = 8
                    
                    # Create semi-transparent background
                    if bg_alpha > 0:
                        # Create background rectangle
                        overlay_bg = result.copy()
                        cv2.rectangle(
                            overlay_bg, 
                            (int(x - padding_x), int(y - text_height - padding_y)), 
                            (int(x + text_width + padding_x), int(y + padding_y)), 
                            bg_color, 
                            -1
                        )
                        # Apply transparency
                        cv2.addWeighted(overlay_bg, bg_alpha, result, 1 - bg_alpha, 0, result)
                    
                    # Draw text
                    cv2.putText(
                        result, text, (int(x), int(y)), 
                        cv2.FONT_HERSHEY_SIMPLEX, font_scale, 
                        color, thickness
                    )
                
                elif overlay_type == 'timestamp':
                    # Get current time as formatted string
                    now = datetime.datetime.now()
                    time_format = overlay.get('format', '%Y-%m-%d %H:%M:%S')
                    time_text = now.strftime(time_format)
                    
                    font_scale = overlay.get('font_scale', 0.7)
                    thickness = overlay.get('thickness', 2)
                    color = overlay.get('text_color', (0, 255, 0))
                    bg_color = overlay.get('bg_color', (0, 0, 0))
                    bg_alpha = overlay.get('bg_alpha', 50) / 100.0  # Convert from percentage to fraction
                    
                    # Calculate text size
                    (text_width, text_height), baseline = cv2.getTextSize(
                        time_text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
                    
                    # Add extra padding to ensure the background covers the text fully
                    padding_x = 8
                    padding_y = 8
                    
                    # Create semi-transparent background
                    if bg_alpha > 0:
                        # Create background rectangle
                        overlay_bg = result.copy()
                        cv2.rectangle(
                            overlay_bg, 
                            (int(x - padding_x), int(y - text_height - padding_y)), 
                            (int(x + text_width + padding_x), int(y + padding_y)), 
                            bg_color, 
                            -1
                        )
                        # Apply transparency
                        cv2.addWeighted(overlay_bg, bg_alpha, result, 1 - bg_alpha, 0, result)
                    
                    # Draw timestamp
                    cv2.putText(
                        result, time_text, (int(x), int(y)), 
                        cv2.FONT_HERSHEY_SIMPLEX, font_scale, 
                        color, thickness
                    )
                
                elif overlay_type == 'sensor':
                    # Get the sensor name from the overlay
                    sensor_name = overlay.get('sensor_name', '')
                    
                    # Get the sensor value from the controller
                    sensor_value = "N/A"
                    sensor_unit = ""
                    
                    # If we have a main_window reference use it to get the sensor controller
                    if hasattr(self, 'main_window') and self.main_window:
                        if hasattr(self.main_window, 'sensor_controller') and self.main_window.sensor_controller:
                            # Get sensor by name
                            sensor = self.main_window.sensor_controller.get_sensor_by_name(sensor_name)
                            if sensor and hasattr(sensor, 'current_value') and sensor.current_value is not None:
                                # Format to 2 decimal places
                                try:
                                    sensor_value = f"{float(sensor.current_value):.2f}"
                                except (ValueError, TypeError):
                                    sensor_value = str(sensor.current_value)
                                
                                # Add unit if available
                                if hasattr(sensor, 'unit') and sensor.unit:
                                    sensor_unit = sensor.unit
                    
                    # Format the sensor text
                    sensor_text = f"{sensor_name}: {sensor_value}"
                    if sensor_unit:
                        sensor_text += f" {sensor_unit}"
                    
                    font_scale = overlay.get('font_scale', 0.7)
                    thickness = overlay.get('thickness', 2)
                    color = overlay.get('text_color', (0, 255, 0))
                    bg_color = overlay.get('bg_color', (0, 0, 0))
                    bg_alpha = overlay.get('bg_alpha', 50) / 100.0  # Convert from percentage to fraction
                    
                    # Calculate text size
                    (text_width, text_height), baseline = cv2.getTextSize(
                        sensor_text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
                    
                    # Add extra padding to ensure the background covers the text fully
                    padding_x = 8
                    padding_y = 8
                    
                    # Create semi-transparent background
                    if bg_alpha > 0:
                        # Create background rectangle
                        overlay_bg = result.copy()
                        cv2.rectangle(
                            overlay_bg, 
                            (int(x - padding_x), int(y - text_height - padding_y)), 
                            (int(x + text_width + padding_x), int(y + padding_y)), 
                            bg_color, 
                            -1
                        )
                        # Apply transparency
                        cv2.addWeighted(overlay_bg, bg_alpha, result, 1 - bg_alpha, 0, result)
                    
                    # Draw sensor text
                    cv2.putText(
                        result, sensor_text, (int(x), int(y)), 
                        cv2.FONT_HERSHEY_SIMPLEX, font_scale, 
                        color, thickness
                    )
                
                elif overlay_type == 'rectangle':
                    width = overlay.get('width', 150)
                    height = overlay.get('height', 80)
                    thickness = overlay.get('thickness', 2)
                    color = overlay.get('text_color', (0, 255, 0))
                    bg_color = overlay.get('bg_color', (0, 0, 0))
                    bg_alpha = overlay.get('bg_alpha', 50) / 100.0  # Convert from percentage to fraction
                    
                    # Calculate rectangle coordinates
                    x1 = int(x)
                    y1 = int(y)
                    x2 = int(x + width)
                    y2 = int(y + height)
                    
                    # Create semi-transparent background
                    if bg_alpha > 0:
                        # Create filled rectangle
                        overlay_bg = result.copy()
                        cv2.rectangle(
                            overlay_bg, 
                            (x1, y1), 
                            (x2, y2), 
                            bg_color, 
                            -1  # Filled rectangle
                        )
                        # Apply transparency
                        cv2.addWeighted(overlay_bg, bg_alpha, result, 1 - bg_alpha, 0, result)
                    
                    # Draw rectangle outline
                    cv2.rectangle(result, (x1, y1), (x2, y2), color, thickness)
        
        except Exception as e:
            print(f"Error applying overlays: {str(e)}")
            import traceback
            traceback.print_exc()
        
        return result 

    def set_camera_properties(self, manual_focus=None, focus_value=None, manual_exposure=None, exposure_value=None):
        """Set camera focus and exposure properties"""
        try:
            if manual_focus is not None:
                self.manual_focus = manual_focus
            
            if focus_value is not None:
                self.focus_value = focus_value
            
            if manual_exposure is not None:
                self.manual_exposure = manual_exposure
            
            if exposure_value is not None:
                self.exposure_value = exposure_value
            
            # Apply settings if camera is connected
            if self.cap and self.connected:
                # Apply focus settings
                if manual_focus is not None:
                    if self.manual_focus:
                        self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)  # Disable autofocus
                        self.cap.set(cv2.CAP_PROP_FOCUS, self.focus_value)
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