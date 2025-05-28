import cv2
import numpy as np
from threading import Lock

class MotionDetector:
    """Handles motion detection using background subtraction."""

    def __init__(self, sensitivity: int = 20, min_area: int = 500):
        """
        Initializes the motion detector.

        Args:
            sensitivity (int): Threshold for background subtraction. Higher means less sensitive.
                                Default value corresponds to QSlider default in ui_setup.py.
            min_area (int): Minimum contour area to be considered motion.
        """
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=sensitivity, detectShadows=True)
        self.min_area = min_area
        self.sensitivity = sensitivity
        self.is_enabled = False
        self._lock = Lock() # For thread-safe settings updates

    def set_enabled(self, enabled: bool):
        """Enable or disable motion detection."""
        with self._lock:
            self.is_enabled = enabled
            if not enabled:
                # Reset background model when disabled to avoid detecting stale motion on re-enable
                self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=self.sensitivity, detectShadows=True)

    def update_settings(self, sensitivity: int, min_area: int):
        """
        Update sensitivity and minimum area settings thread-safely.

        Args:
            sensitivity (int): New sensitivity threshold.
            min_area (int): New minimum contour area.
        """
        with self._lock:
            if self.sensitivity != sensitivity:
                self.sensitivity = sensitivity
                # Recreate subtractor if sensitivity changes
                self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=self.sensitivity, detectShadows=True)
            self.min_area = min_area

    def process_frame(self, frame: np.ndarray) -> bool:
        """
        Processes a single frame to detect motion.

        Args:
            frame (np.ndarray): The input frame (expects BGR format from OpenCV).

        Returns:
            bool: True if motion is detected, False otherwise.
        """
        with self._lock:
            if not self.is_enabled or frame is None:
                return False

            # 1. Apply background subtractor
            fg_mask = self.bg_subtractor.apply(frame)

            # 2. Filter out shadows (value 127 in default MOG2 mask)
            fg_mask = cv2.threshold(fg_mask, 254, 255, cv2.THRESH_BINARY)[1]

            # 3. Noise reduction (optional but recommended)
            fg_mask = cv2.erode(fg_mask, None, iterations=1)
            fg_mask = cv2.dilate(fg_mask, None, iterations=2)

            # 4. Find contours
            contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            # 5. Check for significant motion
            motion_detected = False
            for contour in contours:
                if cv2.contourArea(contour) > self.min_area:
                    motion_detected = True
                    break # Found motion, no need to check other contours

            return motion_detected 