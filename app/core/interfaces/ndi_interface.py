import numpy as np
import threading
import time
import cv2
import logging

# Set up logging
logger = logging.getLogger(__name__)

# Try to import NDI, but provide fallback if not available
NDI_AVAILABLE = False
try:
    # Note: The package is 'ndi-python', but the module is 'ndi'
    from ndi import finder, send, timecode_from_time, VideoFrameV2, FrameFormatType, Create
    NDI_AVAILABLE = True
    logger.info("NDI Python module found and imported successfully.")
except ImportError:
    logger.warning("NDI Python module ('ndi') not found. NDI output will be disabled.")
    logger.warning("To enable NDI: ")
    logger.warning("  1. Install the NDI SDK from https://ndi.tv/sdk/")
    logger.warning("  2. Add the NDI SDK Bin directory to your system PATH.")
    logger.warning("  3. Install the Python package: pip install ndi-python")
    # Define dummy classes/functions if NDI is not available to prevent errors
    class DummySender:
        def send_video_v2(self, frame):
            pass
    class DummyCreate:
        def __call__(self, *args, **kwargs):
            return DummySender()
    class DummyVideoFrameV2:
        def __init__(self, *args, **kwargs):
            pass
    
    finder = None # type: ignore
    send = None   # type: ignore
    timecode_from_time = lambda: 0 # type: ignore
    VideoFrameV2 = DummyVideoFrameV2 # type: ignore
    FrameFormatType = type('FrameFormatType', (object,), {'PROGRESSIVE': 0})() # type: ignore
    Create = DummyCreate() # type: ignore


class NDIInterface:
    """Handles NDI video output streaming."""
    def __init__(self, source_name="EvoLabs DAQ", width=1280, height=720, fps=30):
        self.source_name = source_name
        self.width = width
        self.height = height
        self.fps = max(1, fps) # Ensure FPS is at least 1
        self._running = False
        self._thread = None
        self._last_frame_bgra = None
        self._frame_lock = threading.Lock()
        self._sender = None
        self.ndi_available = NDI_AVAILABLE

        logger.info(f"NDI Interface initialized. NDI Available: {self.ndi_available}")

    def start(self):
        """Starts the NDI output stream."""
        if self._running:
            logger.warning("NDI start called but already running.")
            return False

        if not self.ndi_available:
            logger.error("Cannot start NDI output: NDI libraries not available.")
            return False

        logger.info(f"Starting NDI output stream: '{self.source_name}' ({self.width}x{self.height} @ {self.fps} FPS)")
        try:
            send_create_settings = Create(name=self.source_name, clock_video=True, clock_audio=False)
            self._sender = send_create_settings # Renamed variable for clarity
            if not self._sender:
                 raise RuntimeError("Failed to create NDI sender instance.")

            self._running = True
            self._thread = threading.Thread(target=self._send_frames_loop, name="NDI Send Thread")
            self._thread.daemon = True
            self._thread.start()
            logger.info("NDI output stream started successfully.")
            return True
        except Exception as e:
            logger.exception(f"Error starting NDI output: {e}", exc_info=True)
            self._running = False
            self._sender = None # Ensure sender is cleaned up on error
            return False

    def stop(self):
        """Stops the NDI output stream."""
        if not self._running:
            # logger.debug("NDI stop called but not running.") # Can be noisy
            return False

        logger.info("Stopping NDI output stream...")
        try:
            self._running = False
            if self._thread:
                self._thread.join(timeout=1.5) # Increased timeout slightly
                if self._thread.is_alive():
                    logger.warning("NDI send thread did not terminate cleanly.")
                self._thread = None

            # NDI sender resources are managed automatically when the object is destroyed
            # or when the process exits. Explicitly setting to None helps GC.
            self._sender = None
            logger.info("NDI output stream stopped.")
            return True
        except Exception as e:
            logger.exception(f"Error stopping NDI output: {e}", exc_info=True)
            return False

    def update_frame(self, frame: np.ndarray):
        """Updates the frame to be sent via NDI.

        Args:
            frame: The new video frame (should be BGR or BGRA numpy array).
        """
        if not self._running or not self.ndi_available:
            return False

        if frame is None:
            logger.warning("Attempted to update NDI with a None frame.")
            return False

        try:
            with self._frame_lock:
                # Ensure frame dimensions match configured dimensions
                # This is important as NDI sender expects consistent frame sizes
                if frame.shape[1] != self.width or frame.shape[0] != self.height:
                     frame = cv2.resize(frame, (self.width, self.height),
                                        interpolation=cv2.INTER_LINEAR)

                # Convert BGR to BGRA if necessary (NDI typically requires BGRA)
                if frame.shape[2] == 3:  # BGR
                    self._last_frame_bgra = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
                elif frame.shape[2] == 4: # Assume BGRA
                    self._last_frame_bgra = frame # Use directly, avoid copy if possible
                else:
                    logger.error(f"Unsupported frame format: {frame.shape}")
                    return False
            return True
        except cv2.error as e:
            logger.error(f"OpenCV error updating NDI frame: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.exception(f"Unexpected error updating NDI frame: {e}", exc_info=True)
            return False

    def _send_frames_loop(self):
        """Internal thread function to continuously send frames via NDI."""
        if not self.ndi_available or not self._sender:
            logger.error("NDI sender not initialized in send loop.")
            return

        frame_interval = 1.0 / self.fps
        last_send_time = time.perf_counter()
        frame_count = 0

        logger.debug(f"NDI send loop started. Target interval: {frame_interval:.4f}s")

        while self._running:
            start_time = time.perf_counter()

            frame_to_send = None
            with self._frame_lock:
                if self._last_frame_bgra is not None:
                    # Create a copy to send, releasing the lock quicker
                    frame_to_send = self._last_frame_bgra
                    # Optionally clear self._last_frame_bgra if we only want to send new frames
                    # self._last_frame_bgra = None

            if frame_to_send is not None:
                try:
                    # Ensure frame is C-contiguous (required by NDI)
                    if not frame_to_send.flags['C_CONTIGUOUS']:
                        frame_to_send = np.ascontiguousarray(frame_to_send)

                    video_frame = VideoFrameV2(
                        data=frame_to_send,
                        width=self.width,
                        height=self.height,
                        frame_rate_N=int(self.fps * 1000), # Use integer frame rate (e.g., 30000 for 30fps)
                        frame_rate_D=1000,
                        picture_aspect_ratio=float(self.width) / float(self.height),
                        frame_format_type=FrameFormatType.PROGRESSIVE,
                        timecode=timecode_from_time() # Generate NDI timecode
                        # data format is implicitly BGRA for VideoFrameV2 with numpy array
                    )

                    self._sender.send_video_v2(video_frame)
                    frame_count += 1
                    # logger.debug(f"NDI frame {frame_count} sent.") # Very verbose
                    last_send_time = start_time

                except AttributeError:
                     # Handle case where NDI became unavailable during runtime (less likely)
                     logger.error("NDI sender object seems to be missing or invalid.")
                     self._running = False # Stop the loop if sender is gone
                     break
                except Exception as e:
                    # Catch potential errors during frame sending
                    logger.exception(f"Error sending NDI frame: {e}", exc_info=True)
                    # Decide if we should stop or just log and continue
                    # time.sleep(0.5) # Avoid spamming logs if error persists

            # Calculate time to sleep to maintain target FPS
            elapsed_time = time.perf_counter() - start_time
            sleep_time = frame_interval - elapsed_time

            if sleep_time > 0:
                time.sleep(sleep_time)
            # else: # Optional: Log if we're falling behind
                 # logger.warning(f"NDI send loop fell behind by {-sleep_time:.4f}s")

        logger.debug("NDI send loop finished.")

    def set_properties(self, source_name=None, width=None, height=None, fps=None):
        """Sets NDI output properties. Requires restarting the stream if changed while running."""
        restart_required = False
        current_state = self.get_state()

        if source_name is not None and source_name != self.source_name:
            logger.info(f"NDI source name changed: {self.source_name} -> {source_name}")
            self.source_name = source_name
            restart_required = True

        if width is not None and width != self.width:
            logger.info(f"NDI width changed: {self.width} -> {width}")
            self.width = width
            restart_required = True

        if height is not None and height != self.height:
            logger.info(f"NDI height changed: {self.height} -> {height}")
            self.height = height
            restart_required = True

        new_fps = max(1, fps) if fps is not None else self.fps
        if fps is not None and new_fps != self.fps:
            logger.info(f"NDI FPS changed: {self.fps} -> {new_fps}")
            self.fps = new_fps
            # No restart technically needed for FPS, sender loop adjusts
            # But good practice to restart if dimensions change too
            restart_required = True

        if restart_required and self._running:
            logger.info("Restarting NDI stream due to property changes.")
            self.stop()
            self.start()
        elif restart_required:
             logger.info("NDI properties changed, will take effect on next start.")

        return self.get_state()

    def get_state(self):
         """Returns the current state of the NDI interface."""
         return {
            'source_name': self.source_name,
            'width': self.width,
            'height': self.height,
            'fps': self.fps,
            'running': self._running,
            'available': self.ndi_available
        }

    def is_running(self) -> bool:
        """Checks if NDI output is currently running."""
        return self._running

    def is_available(self) -> bool:
        """Checks if NDI libraries are available."""
        return self.ndi_available 