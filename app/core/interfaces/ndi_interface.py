import numpy as np
import threading
import time
import cv2
import logging

# Set up logging
logger = logging.getLogger(__name__)

# Try to import NDI, but provide fallback if not available
NDI_AVAILABLE = False
import sys
logger.info(f"NDI search - Python: {sys.version}")
logger.info(f"NDI search - Executable: {sys.executable}")
# logger.debug(f"NDI search - Path: {sys.path}")

try:
    # Option 1: Try the 'ndi' module (from common versions of ndi-python)
    import ndi
    from ndi import (
        finder, send, recv,
        timecode_from_time, VideoFrameV2, FrameFormatType, Create,
        find_create_v2, find_get_current_sources, find_destroy,
        recv_create_v3, recv_connect, recv_capture_v2, recv_destroy,
        recv_free_video_v2, FRAME_TYPE_VIDEO
    )
    FRAME_TYPE_NONE = getattr(ndi, 'FRAME_TYPE_NONE', 0)
    FRAME_TYPE_AUDIO = getattr(ndi, 'FRAME_TYPE_AUDIO', None)
    FRAME_TYPE_METADATA = getattr(ndi, 'FRAME_TYPE_METADATA', None)
    recv_free_audio_v2 = getattr(ndi, 'recv_free_audio_v2', None)
    recv_free_audio_v3 = getattr(ndi, 'recv_free_audio_v3', None)
    recv_free_metadata = getattr(ndi, 'recv_free_metadata', None)

    _ndi_initialized = False

    def ensure_ndilib_initialized():
        """Initialize the ndi module once before any NDI API calls."""
        global _ndi_initialized
        if not _ndi_initialized:
            if hasattr(ndi, 'initialize'):
                if not ndi.initialize():
                    logger.error("Failed to initialize NDI")
                    return False
                logger.info("NDI initialized successfully")
            _ndi_initialized = True
        return True

    NDI_AVAILABLE = True
    logger.info("NDI module 'ndi' found and imported successfully.")
except ImportError:
    try:
        # Option 2: Try the 'NDIlib' module (sometimes installed by ndi-python on Windows)
        import NDIlib
        NDI_AVAILABLE = True
        logger.info("NDI module 'NDIlib' found. Setting up compatibility layer.")
        
        # Map constants and functions
        VideoFrameV2 = NDIlib.VideoFrameV2
        FrameFormatType = NDIlib.FrameFormatType
        find_create_v2 = NDIlib.find_create_v2
        find_get_current_sources = NDIlib.find_get_current_sources
        find_destroy = NDIlib.find_destroy
        recv_create_v3 = NDIlib.recv_create_v3
        recv_connect = NDIlib.recv_connect
        recv_capture_v2 = NDIlib.recv_capture_v2
        recv_destroy = NDIlib.recv_destroy
        recv_free_video_v2 = NDIlib.recv_free_video_v2
        FRAME_TYPE_VIDEO = NDIlib.FRAME_TYPE_VIDEO
        FRAME_TYPE_NONE = getattr(NDIlib, 'FRAME_TYPE_NONE', 0)
        FRAME_TYPE_AUDIO = getattr(NDIlib, 'FRAME_TYPE_AUDIO', None)
        FRAME_TYPE_METADATA = getattr(NDIlib, 'FRAME_TYPE_METADATA', None)
        recv_free_audio_v2 = getattr(NDIlib, 'recv_free_audio_v2', None)
        recv_free_audio_v3 = getattr(NDIlib, 'recv_free_audio_v3', None)
        recv_free_metadata = getattr(NDIlib, 'recv_free_metadata', None)

        # Compatibility wrappers
        def timecode_from_time():
            return NDIlib.SEND_TIMECODE_SYNTHESIZE

        _ndilib_initialized = False
        def ensure_ndilib_initialized():
            global _ndilib_initialized
            if not _ndilib_initialized:
                if hasattr(NDIlib, 'initialize'):
                    if not NDIlib.initialize():
                        logger.error("Failed to initialize NDIlib")
                    else:
                        logger.info("NDIlib initialized successfully")
                        _ndilib_initialized = True
            return _ndilib_initialized

        def recv_create_v3(settings=None):
            ensure_ndilib_initialized()
            if settings is None:
                settings = NDIlib.RecvCreateV3()
                settings.color_format = NDIlib.RECV_COLOR_FORMAT_BGRX_BGRA
                settings.bandwidth = NDIlib.RECV_BANDWIDTH_HIGHEST
                settings.allow_video_fields = False
            return NDIlib.recv_create_v3(settings)

        class NDISenderWrapper:
            def __init__(self, settings):
                self.handle = NDIlib.send_create(settings)
            def __bool__(self):
                return self.handle is not None
            def send_video_v2(self, frame):
                return NDIlib.send_send_video_v2(self.handle, frame)

        def Create(name="NDI Source", groups=None, clock_video=True, clock_audio=True):
            ensure_ndilib_initialized()
            settings = NDIlib.SendCreate()
            settings.ndi_name = name
            settings.groups = groups
            settings.clock_video = clock_video
            settings.clock_audio = clock_audio
            return NDISenderWrapper(settings)

        # These aren't used in the code but defined for completeness
        finder = None
        send = None
        recv = None

    except ImportError:
        logger.warning("NDI Python module ('ndi' or 'NDIlib') not found. NDI output and reception will be disabled.")
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
        recv = None   # type: ignore
        timecode_from_time = lambda: 0 # type: ignore
        VideoFrameV2 = DummyVideoFrameV2 # type: ignore
        FrameFormatType = type('FrameFormatType', (object,), {'PROGRESSIVE': 0})() # type: ignore
        Create = DummyCreate() # type: ignore
        find_create_v2 = lambda: None
        find_get_current_sources = lambda x: []
        find_destroy = lambda x: None
        recv_create_v3 = lambda: None
        recv_connect = lambda x, y: None
        recv_capture_v2 = lambda x, y: (0, None, None, None)
        recv_destroy = lambda x: None
        recv_free_video_v2 = lambda x, y: None
        FRAME_TYPE_VIDEO = 1
        FRAME_TYPE_NONE = 0
        FRAME_TYPE_AUDIO = None
        FRAME_TYPE_METADATA = None
        recv_free_audio_v2 = None
        recv_free_audio_v3 = None
        recv_free_metadata = None

        def ensure_ndilib_initialized():
            return False


def _recv_capture(receiver, timeout_ms):
    """Call recv_capture_v2, requesting video only when the API supports it."""
    try:
        return recv_capture_v2(receiver, timeout_ms, True, False, False)
    except TypeError:
        return recv_capture_v2(receiver, timeout_ms)


def _free_recv_buffers(receiver, video_data=None, audio_data=None, metadata_data=None,
                       free_video=True):
    """Release buffers returned by recv_capture_v2 to avoid SDK leaks."""
    if free_video and video_data is not None:
        try:
            recv_free_video_v2(receiver, video_data)
        except Exception as e:
            logger.debug(f"recv_free_video_v2 failed: {e}")
    if audio_data is not None:
        try:
            if recv_free_audio_v3 is not None:
                recv_free_audio_v3(receiver, audio_data)
            elif recv_free_audio_v2 is not None:
                recv_free_audio_v2(receiver, audio_data)
        except Exception as e:
            logger.debug(f"recv_free_audio failed: {e}")
    if metadata_data is not None and recv_free_metadata is not None:
        try:
            recv_free_metadata(receiver, metadata_data)
        except Exception as e:
            logger.debug(f"recv_free_metadata failed: {e}")


class NDIInterface:
    """Handles NDI video output streaming."""
    def __init__(self, source_name="Artefakt DAQ", width=1280, height=720, fps=30):
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
                elif frame.shape[2] == 4:  # Assume BGRA
                    self._last_frame_bgra = frame.copy()
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
                    frame_to_send = self._last_frame_bgra.copy()

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


class NDISourceFinder:
    """Discovers NDI sources on the network."""
    def __init__(self):
        self._finder = None
        if NDI_AVAILABLE:
            ensure_ndilib_initialized()
            try:
                self._finder = find_create_v2()
            except Exception as e:
                logger.error(f"Failed to create NDI finder: {e}")

    def get_sources(self):
        """Returns a list of discovered NDI sources."""
        if not self._finder:
            return []
        try:
            # This returns a list of Source objects
            return find_get_current_sources(self._finder)
        except Exception as e:
            logger.error(f"Error getting NDI sources: {e}")
            return []

    def __del__(self):
        if self._finder:
            try:
                find_destroy(self._finder)
            except:
                pass


class NDIReceiver:
    """Receives video frames from an NDI source."""
    def __init__(self, source_name=None):
        self.source_name = source_name
        self._receiver = None
        self._connected = False
        self._consecutive_capture_failures = 0

    def connect(self, source):
        """Connects to a specific NDI source.
        
        Args:
            source: An NDI Source object (from finder)
        """
        if not NDI_AVAILABLE:
            return False
        
        try:
            if self._receiver:
                self.disconnect()

            ensure_ndilib_initialized()
            self._receiver = recv_create_v3()
            if not self._receiver:
                return False
            
            recv_connect(self._receiver, source)
            self._connected = True
            self._consecutive_capture_failures = 0
            # Use ndi_name which is often available on the source object
            self.source_name = getattr(source, 'ndi_name', str(source))
            logger.info(f"Connected to NDI source: {self.source_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to NDI source: {e}")
            return False

    def disconnect(self):
        """Disconnects from the current NDI source."""
        if self._receiver:
            try:
                recv_destroy(self._receiver)
            except:
                pass
            self._receiver = None
        self._connected = False
        self._consecutive_capture_failures = 0
        logger.info(f"Disconnected from NDI source: {self.source_name}")

    def capture_frame(self, timeout_ms=1000):
        """Captures a single video frame from the NDI source."""
        if not self._receiver or not self._connected:
            return None

        try:
            deadline = time.perf_counter() + timeout_ms / 1000.0
            while True:
                remaining_ms = max(1, int((deadline - time.perf_counter()) * 1000))
                frame_type, video_data, audio_data, metadata_data = _recv_capture(
                    self._receiver, remaining_ms
                )

                if frame_type == FRAME_TYPE_NONE:
                    self._consecutive_capture_failures += 1
                    return None

                if frame_type == FRAME_TYPE_VIDEO:
                    if video_data is None or video_data.data is None:
                        logger.error("NDI video frame captured but data is None")
                        _free_recv_buffers(
                            self._receiver, video_data, audio_data, metadata_data
                        )
                        self._consecutive_capture_failures += 1
                        return None

                    frame = np.copy(video_data.data)
                    _free_recv_buffers(
                        self._receiver, video_data, audio_data, metadata_data
                    )

                    self._consecutive_capture_failures = 0
                    if frame.shape[2] == 4:
                        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    return frame

                logger.debug(f"Captured non-video NDI frame type: {frame_type}")
                _free_recv_buffers(
                    self._receiver, video_data, audio_data, metadata_data
                )

                if time.perf_counter() >= deadline:
                    self._consecutive_capture_failures += 1
                    return None
        except Exception as e:
            logger.error(f"Error capturing NDI frame: {e}")
            self._consecutive_capture_failures += 1
            return None

    def is_connected(self):
        # Connection state only; consecutive timeout handling lives in direct_camera (CAM-07).
        return self._connected

    def consecutive_capture_failures(self) -> int:
        """Number of consecutive capture_frame calls that did not return video."""
        return self._consecutive_capture_failures

    def __del__(self):
        self.disconnect()
