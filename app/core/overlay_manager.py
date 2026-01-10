import cv2
import datetime
import json
import os
from abc import ABC, abstractmethod

class BaseOverlay(ABC):
    def __init__(self, overlay_id, name, position=(0.1, 0.1), visible=True, 
                 text_color=(255, 255, 255), bg_color=(0, 0, 0), bg_alpha=0.5):
        self.id = overlay_id
        self.name = name
        self.position = position  # (rel_x, rel_y) normalized 0.0 to 1.0
        self.visible = visible
        self.text_color = text_color  # BGR
        self.bg_color = bg_color      # BGR
        self.bg_alpha = bg_alpha      # 0.0 to 1.0
        self.font_scale = 0.7
        self.thickness = 2

    @abstractmethod
    def draw(self, frame):
        pass

    def get_draw_params(self, frame_h, frame_w):
        x = int(self.position[0] * frame_w)
        y = int(self.position[1] * frame_h)
        return x, y

    def _get_smooth_text_params(self, text, frame_w, frame_h):
        """Calculate smooth positioning that keeps text on screen based on position (0-1)"""
        (text_width, text_height), baseline = cv2.getTextSize(
            text, cv2.FONT_HERSHEY_SIMPLEX, self.font_scale, self.thickness)
        
        padding_x = 8
        padding_y = 8
        
        x_rel, y_rel = self.position
        full_width = text_width + 2 * padding_x
        full_height = text_height + 2 * padding_y
        
        # Calculate x and y for _draw_text_with_bg
        x = x_rel * frame_w - x_rel * full_width + padding_x
        y = y_rel * frame_h - y_rel * full_height + padding_y + text_height
        
        return int(x), int(y), full_width, full_height, text_width, text_height

    def get_bounds(self, frame_w, frame_h):
        """Return (x1, y1, x2, y2) in relative coordinates (0-1)"""
        # Default implementation for non-text overlays
        return (self.position[0] - 0.05, self.position[1] - 0.05, 
                self.position[0] + 0.05, self.position[1] + 0.05)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "type": self.get_type(),
            "position": self.position,
            "visible": self.visible,
            "text_color": self.text_color,
            "bg_color": self.bg_color,
            "bg_alpha": self.bg_alpha,
            "font_scale": self.font_scale,
            "thickness": self.thickness
        }

    @abstractmethod
    def get_type(self):
        pass

    @staticmethod
    def from_dict(data):
        overlay_type = data.get("type")
        if overlay_type == "text":
            obj = TextOverlay(data["id"], data["name"], data.get("text", ""))
        elif overlay_type == "timestamp":
            obj = TimestampOverlay(data["id"], data["name"], data.get("format", "%Y-%m-%d %H:%M:%S"))
        elif overlay_type == "sensor":
            obj = SensorOverlay(data["id"], data["name"], data.get("sensor_name", ""))
            obj.sensor_value = data.get("sensor_value", "N/A")
            obj.sensor_unit = data.get("sensor_unit", "")
        elif overlay_type == "rectangle":
            obj = RectangleOverlay(data["id"], data["name"], data.get("width", 0.1), data.get("height", 0.1))
        elif overlay_type == "motion":
            obj = MotionOverlay(data["id"], data["name"])
            obj.motion_detected = data.get("motion_detected", False)
        else:
            return None

        obj.position = data.get("position", obj.position)
        obj.visible = data.get("visible", obj.visible)
        obj.text_color = tuple(data.get("text_color", obj.text_color))
        obj.bg_color = tuple(data.get("bg_color", obj.bg_color))
        obj.bg_alpha = data.get("bg_alpha", obj.bg_alpha)
        obj.font_scale = data.get("font_scale", obj.font_scale)
        obj.thickness = data.get("thickness", obj.thickness)
        return obj

    def _draw_text_with_bg(self, frame, text, x, y):
        (text_width, text_height), baseline = cv2.getTextSize(
            text, cv2.FONT_HERSHEY_SIMPLEX, self.font_scale, self.thickness)
        
        padding_x = 8
        padding_y = 8
        
        # Calculate ROI coordinates
        x1, y1 = int(x - padding_x), int(y - text_height - padding_y)
        x2, y2 = int(x + text_width + padding_x), int(y + padding_y)
        
        # Ensure ROI is within frame bounds
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        
        if x2 > x1 and y2 > y1 and self.bg_alpha > 0:
            roi = frame[y1:y2, x1:x2]
            overlay_bg = roi.copy()
            cv2.rectangle(overlay_bg, (0, 0), (x2-x1, y2-y1), self.bg_color, -1)
            cv2.addWeighted(overlay_bg, self.bg_alpha, roi, 1 - self.bg_alpha, 0, roi)
            
        cv2.putText(frame, text, (int(x), int(y)), 
                    cv2.FONT_HERSHEY_SIMPLEX, self.font_scale, 
                    self.text_color, self.thickness)

class TextOverlay(BaseOverlay):
    def __init__(self, overlay_id, name, text=""):
        super().__init__(overlay_id, name)
        self.text = text

    def get_type(self): return "text"

    def draw(self, frame):
        if not self.visible: return
        h, w = frame.shape[:2]
        x, y, _, _, _, _ = self._get_smooth_text_params(self.text, w, h)
        self._draw_text_with_bg(frame, self.text, x, y)

    def get_bounds(self, frame_w, frame_h):
        x, y, full_width, full_height, _, _ = self._get_smooth_text_params(self.text, frame_w, frame_h)
        padding_x = 8
        x1 = (x - padding_x) / frame_w
        y1 = (y - (full_height - 8)) / frame_h # 8 is padding_y
        x2 = (x - padding_x + full_width) / frame_w
        y2 = (y + 8) / frame_h
        return (x1, y1, x2, y2)

    def to_dict(self):
        d = super().to_dict()
        d["text"] = self.text
        return d

class TimestampOverlay(BaseOverlay):
    def __init__(self, overlay_id, name, time_format="%Y-%m-%d %H:%M:%S"):
        super().__init__(overlay_id, name, position=(1.0, 1.0))
        self.format = time_format
        self.font_scale = 1.0  # Default font scale for timestamps is 1.0 as requested

    def get_type(self): return "timestamp"

    def _get_time_text(self):
        try:
            return datetime.datetime.now().strftime(self.format)
        except (ValueError, TypeError):
            return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def draw(self, frame):
        if not self.visible: return
        h, w = frame.shape[:2]
        text = self._get_time_text()
        x, y, _, _, _, _ = self._get_smooth_text_params(text, w, h)
        self._draw_text_with_bg(frame, text, x, y)

    def get_bounds(self, frame_w, frame_h):
        text = self._get_time_text()
        x, y, full_width, full_height, _, _ = self._get_smooth_text_params(text, frame_w, frame_h)
        padding_x = 8
        x1 = (x - padding_x) / frame_w
        y1 = (y - (full_height - 8)) / frame_h
        x2 = (x - padding_x + full_width) / frame_w
        y2 = (y + 8) / frame_h
        return (x1, y1, x2, y2)

    def to_dict(self):
        d = super().to_dict()
        d["format"] = self.format
        return d

class SensorOverlay(BaseOverlay):
    def __init__(self, overlay_id, name, sensor_name=""):
        super().__init__(overlay_id, name)
        self.sensor_name = sensor_name
        self.sensor_value = "N/A"
        self.sensor_unit = ""

    def get_type(self): return "sensor"

    def _get_sensor_text(self):
        sensor_text = f"{self.sensor_name}: {self.sensor_value}"
        if self.sensor_unit:
            sensor_text += f" {self.sensor_unit}"
        return sensor_text

    def draw(self, frame):
        if not self.visible: return
        h, w = frame.shape[:2]
        text = self._get_sensor_text()
        x, y, _, _, _, _ = self._get_smooth_text_params(text, w, h)
        self._draw_text_with_bg(frame, text, x, y)

    def get_bounds(self, frame_w, frame_h):
        text = self._get_sensor_text()
        x, y, full_width, full_height, _, _ = self._get_smooth_text_params(text, frame_w, frame_h)
        padding_x = 8
        x1 = (x - padding_x) / frame_w
        y1 = (y - (full_height - 8)) / frame_h
        x2 = (x - padding_x + full_width) / frame_w
        y2 = (y + 8) / frame_h
        return (x1, y1, x2, y2)

    def to_dict(self):
        d = super().to_dict()
        d["sensor_name"] = self.sensor_name
        d["sensor_value"] = self.sensor_value
        d["sensor_unit"] = self.sensor_unit
        return d

class RectangleOverlay(BaseOverlay):
    def __init__(self, overlay_id, name, width=0.1, height=0.1):
        super().__init__(overlay_id, name)
        self.width = width  # relative width
        self.height = height # relative height

    def get_type(self): return "rectangle"

    def draw(self, frame):
        if not self.visible: return
        h, w = frame.shape[:2]
        x, y = self.get_draw_params(h, w)
        rect_w = int(self.width * w)
        rect_h = int(self.height * h)
        
        x2, y2 = min(w, x + rect_w), min(h, y + rect_h)
        
        if x2 > x and y2 > y and self.bg_alpha > 0:
            roi = frame[y:y2, x:x2]
            overlay_bg = roi.copy()
            cv2.rectangle(overlay_bg, (0, 0), (x2-x, y2-y), self.bg_color, -1)
            cv2.addWeighted(overlay_bg, self.bg_alpha, roi, 1 - self.bg_alpha, 0, roi)
            
        cv2.rectangle(frame, (x, y), (x2, y2), self.text_color, self.thickness)

    def get_bounds(self, frame_w, frame_h):
        x1, y1 = self.position
        return (x1, y1, x1 + self.width, y1 + self.height)

    def to_dict(self):
        d = super().to_dict()
        d["width"] = self.width
        d["height"] = self.height
        return d

class MotionOverlay(BaseOverlay):
    def __init__(self, overlay_id, name):
        super().__init__(overlay_id, name)
        self.motion_detected = False
        self.position = (0.95, 0.05)  # Default to top-right

    def get_type(self): return "motion"

    def draw(self, frame):
        if not self.visible: return
        h, w = frame.shape[:2]
        x, y = self.get_draw_params(h, w)
        
        indicator_size = 20
        # Red for motion, Green for idle (BGR)
        color = (0, 0, 255) if self.motion_detected else (0, 255, 0)
        
        # Ensure indicator stays within bounds
        x = max(indicator_size, min(w - indicator_size, x))
        y = max(indicator_size, min(h - indicator_size, y))
        
        cv2.circle(frame, (x, y), indicator_size // 2, color, -1)
        cv2.circle(frame, (x, y), indicator_size // 2, (255, 255, 255), 2)

    def get_bounds(self, frame_w, frame_h):
        indicator_size = 20
        rel_size_x = indicator_size / frame_w
        rel_size_y = indicator_size / frame_h
        x, y = self.position
        return (x - rel_size_x, y - rel_size_y, x + rel_size_x, y + rel_size_y)

    def to_dict(self):
        d = super().to_dict()
        d["motion_detected"] = self.motion_detected
        return d

