"""
Optical Sensor Configuration Dialog

Dialog for configuring optical sensor settings based on detection mode.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QSpinBox, QDoubleSpinBox, QGroupBox, QCheckBox,
    QTabWidget, QWidget, QFileDialog, QMessageBox,
    QSlider, QFrame, QGridLayout, QSizePolicy, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QColor, QImage, QPixmap, QPainter, QPen

from app.ui.theme import (
    ButtonStyles, GroupBoxStyles, COLORS, CardStyles, DialogStyles
)
from app.ui.tools.help_panel import HelpPanel, get_help_content
from app.core.interfaces.optical_sensor_interface import RpmEstimator

import cv2
import numpy as np


class PreviewThread(QThread):
    """Thread for capturing camera frames for preview"""
    frame_ready = pyqtSignal(np.ndarray)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, camera_id=0, width=640, height=480):
        super().__init__()
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self.running = False
        self.cap = None
    
    def run(self):
        """Capture frames from camera"""
        try:
            self.cap = cv2.VideoCapture(self.camera_id)
            if not self.cap.isOpened():
                self.error_occurred.emit(f"Could not open camera {self.camera_id}")
                return
            
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            
            self.running = True
            while self.running:
                ret, frame = self.cap.read()
                if ret:
                    self.frame_ready.emit(frame)
                else:
                    break
                self.msleep(33)  # ~30 FPS for preview
            
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            if self.cap:
                self.cap.release()
    
    def stop(self):
        """Stop the preview thread"""
        self.running = False
        self.wait(1000)


class OpticalSensorConfigDialog(QDialog):
    """Dialog for configuring an Optical Sensor"""
    
    # Signal emitted when settings are applied
    settings_changed = pyqtSignal(dict)
    
    # Detection modes and their descriptions
    MODES = {
        "light_events": {
            "name": "Light Events",
            "icon": "💡",
            "description": "Detect small bright spots (scintillation, particle impacts, EVOs)"
        },
        "brightness": {
            "name": "Brightness",
            "icon": "☀️",
            "description": "Measure overall brightness levels (mean, max, min, std) in a selected Region of Interest. Useful for light level monitoring or transition detection."
        },
        "color": {
            "name": "Color Tracking",
            "icon": "🎨",
            "description": "Track color values (RGB/HSV) and specific color presence"
        },
        "position": {
            "name": "Position Tracking",
            "icon": "📍",
            "description": "Track position of brightest point or colored object"
        },
        "particle_count": {
            "name": "Particle Counter",
            "icon": "✨",
            "description": "Count distinct bright spots/particles in frame"
        },
        "fill_level": {
            "name": "Fill Level",
            "icon": "📊",
            "description": "Detect fill level in a region (containers, tubes)"
        },
        "rpm": {
            "name": "RPM",
            "icon": "🔁",
            "description": "Estimate RPM by tracking brightness modulation inside a region"
        },
    }
    
    def __init__(self, parent=None, sensor_name="Optical Sensor", current_settings=None):
        super().__init__(parent)
        self.setWindowTitle(f"Configure {sensor_name}")
        self.setMinimumSize(900, 500)  # Wider, less tall for two-column layout
        self.sensor_name = sensor_name
        
        # Apply dark dialog style
        self.setStyleSheet(DialogStyles.dark_dialog())
        
        # Default settings
        self.settings = {
            "mode": "light_events",
            "camera_id": 0,
            "width": 640,
            "height": 480,
            "sample_rate": 10,
            
            # Light events
            "brightness_threshold": 30,
            "relative_threshold": 3.0,
            "threshold_mode": "absolute",
            "min_pixels": 1,
            "max_pixels": 100,
            "cooldown_ms": 100,
            
            # Particle counter
            "particle_threshold_mode": "relative",
            "particle_brightness_threshold": 50,
            "particle_relative_threshold": 3.0,
            "particle_min_size": 3,
            "particle_max_size": 500,
            "particle_min_distance": 5,
            "particle_bg_subtract": False,
            
            # Color tracking
            "target_hue": 0,
            "hue_tolerance": 10,
            "saturation_min": 100,
            
            # Position tracking
            "tracking_method": "brightness",
            
            # Fill level
            "roi_x": 0,
            "roi_y": 0,
            "roi_width": 100,
            "roi_height": 100,
            "fill_threshold": 128,
            "fill_direction": "horizontal",
            "fill_threshold_percent": 50,

            # Brightness
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
            
            # Event saving
            "save_event_images": True,
            "output_dir": "optical_events",
        }
        
        # Override with current settings if provided
        if current_settings:
            self.settings.update(current_settings)

        # RPM estimator for preview/testing (stateful)
        self.rpm_test_estimator = RpmEstimator()
        self._last_rpm_result = {}
        
        self._setup_ui()
        self._load_settings()
        
    def _setup_ui(self):
        """Setup the dialog UI - Two column layout with help panel"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # === Header with Help Button ===
        header_layout = QHBoxLayout()

        header = QLabel(f"🎥 {self.sensor_name} Configuration")
        header.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {COLORS.TEXT_PRIMARY};")
        header_layout.addWidget(header)

        header_layout.addStretch()

        self.help_btn = QPushButton("❓ Help")
        self.help_btn.setCheckable(True)
        self.help_btn.setStyleSheet(ButtonStyles.secondary("small"))
        self.help_btn.clicked.connect(self._toggle_help)
        header_layout.addWidget(self.help_btn)

        main_layout.addLayout(header_layout)

        # === Content Splitter ===
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setHandleWidth(1)
        self.content_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #3a3a5c;
            }
        """)

        # Main content widget (contains the two column layout)
        main_content = QWidget()
        content_layout = QVBoxLayout(main_content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # === Two Column Layout ===
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(15)
        
        # ====== LEFT COLUMN: Mode, Camera, Event Saving ======
        left_column = QVBoxLayout()
        left_column.setSpacing(10)
        
        # Mode Selection
        mode_group = QGroupBox("Detection Mode")
        mode_group.setStyleSheet(GroupBoxStyles.compact())
        mode_layout = QVBoxLayout(mode_group)
        mode_layout.setSpacing(5)
        
        self.mode_combo = QComboBox()
        for mode_key, mode_info in self.MODES.items():
            self.mode_combo.addItem(
                f"{mode_info['icon']} {mode_info['name']}", 
                mode_key
            )
        # Add green border to highlight as the most important element
        self.mode_combo.setStyleSheet(f"""
            QComboBox {{
                border: 2px solid {COLORS.SUCCESS};
                border-radius: 4px;
                padding: 5px;
                background: {COLORS.BG_INPUT};
                color: {COLORS.TEXT_PRIMARY};
            }}
            QComboBox:hover {{
                border: 2px solid {COLORS.SUCCESS_BRIGHT};
            }}
            QComboBox:focus {{
                border: 2px solid {COLORS.SUCCESS_BRIGHT};
            }}
        """)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        
        self.mode_description = QLabel()
        self.mode_description.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 10px;")
        self.mode_description.setWordWrap(True)
        self.mode_description.setMinimumHeight(35)
        mode_layout.addWidget(self.mode_description)
        
        left_column.addWidget(mode_group)
        
        # Camera Settings
        camera_group = QGroupBox("Camera Settings")
        camera_group.setStyleSheet(GroupBoxStyles.compact())
        camera_layout = QFormLayout(camera_group)
        camera_layout.setSpacing(5)
        
        self.camera_id_spin = QSpinBox()
        self.camera_id_spin.setRange(0, 10)
        camera_layout.addRow("Camera ID:", self.camera_id_spin)
        
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems([
            "320x240", "640x480", "800x600", "1280x720", "1920x1080"
        ])
        self.resolution_combo.setCurrentText("640x480")
        camera_layout.addRow("Resolution:", self.resolution_combo)
        
        self.sample_rate_spin = QSpinBox()
        self.sample_rate_spin.setRange(1, 60)
        self.sample_rate_spin.setValue(10)
        self.sample_rate_spin.setSuffix(" Hz")
        camera_layout.addRow("Sample Rate:", self.sample_rate_spin)
        
        self.auto_connect_cb = QCheckBox("Auto-connect on Startup")
        self.auto_connect_cb.setChecked(True)
        self.auto_connect_cb.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; font-size: 11px;")
        camera_layout.addRow("", self.auto_connect_cb)
        
        left_column.addWidget(camera_group)
        
        # Event Saving
        save_group = QGroupBox("Event Saving")
        save_group.setStyleSheet(GroupBoxStyles.compact())
        save_layout = QVBoxLayout(save_group)
        save_layout.setSpacing(5)
        
        self.save_events_check = QCheckBox("Save event images")
        self.save_events_check.setChecked(True)
        self.save_events_check.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; font-size: 11px;")
        save_layout.addWidget(self.save_events_check)
        
        left_column.addWidget(save_group)
        
        # Add stretch to push everything up
        left_column.addStretch()
        
        # Buttons in left column
        buttons_group = QGroupBox()
        buttons_group.setStyleSheet("QGroupBox { border: none; }")
        buttons_layout = QVBoxLayout(buttons_group)
        buttons_layout.setSpacing(5)
        
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setStyleSheet(ButtonStyles.success("medium"))
        self.apply_btn.clicked.connect(self._apply_settings)
        buttons_layout.addWidget(self.apply_btn)
        
        self.ok_btn = QPushButton("OK")
        self.ok_btn.setStyleSheet(ButtonStyles.primary("medium"))
        self.ok_btn.clicked.connect(self._ok_clicked)
        buttons_layout.addWidget(self.ok_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet(ButtonStyles.secondary("medium"))
        self.cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(self.cancel_btn)
        
        left_column.addWidget(buttons_group)
        
        columns_layout.addLayout(left_column, stretch=1)  # Takes less space
        
        # ====== RIGHT COLUMN: Tab Widget (Settings + Preview) ======
        right_column = QVBoxLayout()
        right_column.setSpacing(10)
        
        # Mode-specific Settings (Tab Widget)
        self.settings_tabs = QTabWidget()
        self.settings_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 8px;
                background: {COLORS.BG_CARD};
            }}
            QTabBar::tab {{
                background: {COLORS.BG_INPUT};
                color: {COLORS.TEXT_SECONDARY};
                padding: 6px 12px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 11px;
            }}
            QTabBar::tab:selected {{
                background: {COLORS.BG_ELEVATED};
                color: {COLORS.TEXT_PRIMARY};
            }}
        """)
        
        # Light Events Tab
        self.light_events_tab = self._create_light_events_tab()
        self.settings_tabs.addTab(self.light_events_tab, "💡 Light")
        
        # Brightness Tab
        self.brightness_tab = self._create_brightness_tab()
        self.settings_tabs.addTab(self.brightness_tab, "☀️ Bright")
        
        # Particle Counter Tab
        self.particle_counter_tab = self._create_particle_counter_tab()
        self.settings_tabs.addTab(self.particle_counter_tab, "✨ Particles")
        
        # Color Tab
        self.color_tab = self._create_color_tab()
        self.settings_tabs.addTab(self.color_tab, "🎨 Color")
        
        # Position Tab
        self.position_tab = self._create_position_tab()
        self.settings_tabs.addTab(self.position_tab, "📍 Pos")
        
        # RPM Tab
        self.rpm_tab = self._create_rpm_tab()
        self.settings_tabs.addTab(self.rpm_tab, "🔁 RPM")
        
        # Fill Level Tab
        self.fill_level_tab = self._create_fill_level_tab()
        self.settings_tabs.addTab(self.fill_level_tab, "📊 Fill")
        
        # Preview Tab
        self.preview_tab = self._create_preview_tab()
        self.settings_tabs.addTab(self.preview_tab, "👁️ Preview")
        
        right_column.addWidget(self.settings_tabs)
        columns_layout.addLayout(right_column, stretch=3)  # Takes more space
        
        content_layout.addLayout(columns_layout)
        self.content_splitter.addWidget(main_content)

        # Setup help panel
        self._setup_help_panel()

        main_layout.addWidget(self.content_splitter)

        # Update UI based on initial mode
        self._on_mode_changed()
    
    def _create_light_events_tab(self):
        """Create the light events settings tab"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(10)
        
        # Threshold mode
        self.threshold_mode_combo = QComboBox()
        self.threshold_mode_combo.addItems(["Absolute", "Relative (σ)"])
        self.threshold_mode_combo.currentIndexChanged.connect(self._on_threshold_mode_changed)
        layout.addRow("Threshold Mode:", self.threshold_mode_combo)
        
        # Absolute threshold
        self.brightness_threshold_spin = QSpinBox()
        self.brightness_threshold_spin.setRange(1, 255)
        self.brightness_threshold_spin.setValue(30)
        self.brightness_threshold_spin.setSuffix(" (brightness above baseline)")
        layout.addRow("Brightness Threshold:", self.brightness_threshold_spin)
        
        # Relative threshold
        self.relative_threshold_spin = QDoubleSpinBox()
        self.relative_threshold_spin.setRange(0.5, 10.0)
        self.relative_threshold_spin.setValue(3.0)
        self.relative_threshold_spin.setSingleStep(0.5)
        self.relative_threshold_spin.setSuffix(" σ (std deviations)")
        layout.addRow("Relative Threshold:", self.relative_threshold_spin)
        
        # Pixel range
        pixel_layout = QHBoxLayout()
        
        self.min_pixels_spin = QSpinBox()
        self.min_pixels_spin.setRange(1, 1000)
        self.min_pixels_spin.setValue(1)
        pixel_layout.addWidget(QLabel("Min:"))
        pixel_layout.addWidget(self.min_pixels_spin)
        
        self.max_pixels_spin = QSpinBox()
        self.max_pixels_spin.setRange(1, 10000)
        self.max_pixels_spin.setValue(100)
        pixel_layout.addWidget(QLabel("Max:"))
        pixel_layout.addWidget(self.max_pixels_spin)
        
        layout.addRow("Pixel Count Range:", pixel_layout)
        
        # Cooldown
        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setRange(0, 5000)
        self.cooldown_spin.setValue(100)
        self.cooldown_spin.setSuffix(" ms")
        layout.addRow("Event Cooldown:", self.cooldown_spin)
        
        # Info
        info_label = QLabel(
            "💡 Light Events mode detects tiny bright spots (1-100 pixels) "
            "against a dark baseline. Perfect for scintillation detection, "
            "particle impacts, or cosmic ray detection."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {COLORS.TEXT_MUTED}; font-size: 11px; padding: 10px;")
        layout.addRow(info_label)
        
        return widget
    
    def _create_brightness_tab(self):
        """Create the brightness settings tab"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(10)
        
        # ROI settings
        roi_group = QGroupBox("Region of Interest (ROI)")
        roi_layout = QGridLayout(roi_group)
        
        roi_layout.addWidget(QLabel("X:"), 0, 0)
        self.brightness_roi_x_spin = QSpinBox()
        self.brightness_roi_x_spin.setRange(0, 1920)
        roi_layout.addWidget(self.brightness_roi_x_spin, 0, 1)
        
        roi_layout.addWidget(QLabel("Y:"), 0, 2)
        self.brightness_roi_y_spin = QSpinBox()
        self.brightness_roi_y_spin.setRange(0, 1080)
        roi_layout.addWidget(self.brightness_roi_y_spin, 0, 3)
        
        roi_layout.addWidget(QLabel("Width:"), 1, 0)
        self.brightness_roi_width_spin = QSpinBox()
        self.brightness_roi_width_spin.setRange(10, 1920)
        self.brightness_roi_width_spin.setValue(640)
        roi_layout.addWidget(self.brightness_roi_width_spin, 1, 1)
        
        roi_layout.addWidget(QLabel("Height:"), 1, 2)
        self.brightness_roi_height_spin = QSpinBox()
        self.brightness_roi_height_spin.setRange(10, 1080)
        self.brightness_roi_height_spin.setValue(480)
        roi_layout.addWidget(self.brightness_roi_height_spin, 1, 3)
        
        layout.addRow(roi_group)
        
        # Info
        info_label = QLabel(
            "☀️ Brightness mode measures overall light levels (mean, max, min, std) "
            "within the selected region of interest (ROI). "
            "Leave ROI at full resolution for global measurement, or "
            "constrain it to a specific area of interest."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {COLORS.TEXT_MUTED}; font-size: 11px; padding: 10px;")
        layout.addRow(info_label)
        
        return widget
    
    def _create_particle_counter_tab(self):
        """Create the particle counter settings tab"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(10)
        
        # Threshold mode (same as light events but with different defaults)
        self.particle_threshold_mode_combo = QComboBox()
        self.particle_threshold_mode_combo.addItems(["Absolute", "Relative (σ)"])
        self.particle_threshold_mode_combo.currentIndexChanged.connect(self._on_particle_threshold_mode_changed)
        layout.addRow("Threshold Mode:", self.particle_threshold_mode_combo)
        
        # Absolute threshold
        self.particle_brightness_threshold_spin = QSpinBox()
        self.particle_brightness_threshold_spin.setRange(1, 255)
        self.particle_brightness_threshold_spin.setValue(50)
        self.particle_brightness_threshold_spin.setSuffix(" (brightness)")
        layout.addRow("Brightness Threshold:", self.particle_brightness_threshold_spin)
        
        # Relative threshold
        self.particle_relative_threshold_spin = QDoubleSpinBox()
        self.particle_relative_threshold_spin.setRange(0.5, 10.0)
        self.particle_relative_threshold_spin.setValue(3.0)
        self.particle_relative_threshold_spin.setSingleStep(0.5)
        self.particle_relative_threshold_spin.setSuffix(" σ (std deviations)")
        layout.addRow("Relative Threshold:", self.particle_relative_threshold_spin)
        
        # Particle size range
        size_layout = QHBoxLayout()
        
        self.particle_min_size_spin = QSpinBox()
        self.particle_min_size_spin.setRange(1, 1000)
        self.particle_min_size_spin.setValue(3)
        self.particle_min_size_spin.setSuffix(" px")
        size_layout.addWidget(QLabel("Min:"))
        size_layout.addWidget(self.particle_min_size_spin)
        
        self.particle_max_size_spin = QSpinBox()
        self.particle_max_size_spin.setRange(1, 10000)
        self.particle_max_size_spin.setValue(500)
        self.particle_max_size_spin.setSuffix(" px")
        size_layout.addWidget(QLabel("Max:"))
        size_layout.addWidget(self.particle_max_size_spin)
        
        layout.addRow("Particle Size:", size_layout)
        
        # Minimum distance between particles
        self.particle_min_distance_spin = QSpinBox()
        self.particle_min_distance_spin.setRange(0, 100)
        self.particle_min_distance_spin.setValue(5)
        self.particle_min_distance_spin.setSuffix(" px")
        self.particle_min_distance_spin.setToolTip("Minimum distance between particles to count as separate")
        layout.addRow("Min Distance:", self.particle_min_distance_spin)
        
        # Background subtraction
        self.particle_bg_subtract_check = QCheckBox("Enable background subtraction")
        self.particle_bg_subtract_check.setChecked(False)
        self.particle_bg_subtract_check.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; font-size: 11px;")
        self.particle_bg_subtract_check.setToolTip("Subtract static background to improve detection")
        layout.addRow("Background:", self.particle_bg_subtract_check)
        
        # Info
        info_label = QLabel(
            "✨ Particle Counter mode counts distinct bright spots or particles in each frame. "
            "Use Min/Max size to filter out noise (small) and large objects. "
            "3σ threshold works well for detecting real particles above noise level."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {COLORS.TEXT_MUTED}; font-size: 11px; padding: 10px;")
        layout.addRow(info_label)
        
        # Initialize threshold mode visibility
        self._on_particle_threshold_mode_changed()
        
        return widget
    
    def _on_particle_threshold_mode_changed(self):
        """Handle particle threshold mode change"""
        is_absolute = self.particle_threshold_mode_combo.currentIndex() == 0
        self.particle_brightness_threshold_spin.setEnabled(is_absolute)
        self.particle_relative_threshold_spin.setEnabled(not is_absolute)
    
    def _create_color_tab(self):
        """Create the color tracking settings tab"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(10)
        
        # Target hue with preview
        hue_layout = QHBoxLayout()
        
        self.target_hue_slider = QSlider(Qt.Orientation.Horizontal)
        self.target_hue_slider.setRange(0, 179)
        self.target_hue_slider.setValue(0)
        self.target_hue_slider.valueChanged.connect(self._update_hue_preview)
        hue_layout.addWidget(self.target_hue_slider)
        
        self.hue_preview = QFrame()
        self.hue_preview.setFixedSize(30, 30)
        self.hue_preview.setStyleSheet("background: red; border-radius: 4px;")
        hue_layout.addWidget(self.hue_preview)
        
        layout.addRow("Target Hue:", hue_layout)
        
        # Hue tolerance
        self.hue_tolerance_spin = QSpinBox()
        self.hue_tolerance_spin.setRange(1, 90)
        self.hue_tolerance_spin.setValue(10)
        layout.addRow("Hue Tolerance:", self.hue_tolerance_spin)
        
        # Saturation minimum
        self.saturation_min_spin = QSpinBox()
        self.saturation_min_spin.setRange(0, 255)
        self.saturation_min_spin.setValue(100)
        layout.addRow("Min Saturation:", self.saturation_min_spin)
        
        # Info
        info_label = QLabel(
            "🎨 Color Tracking measures RGB/HSV values and can track "
            "the percentage of a specific target color in the frame. "
            "Useful for pH indicators, chemical reactions, or color-based sensing."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {COLORS.TEXT_MUTED}; font-size: 11px; padding: 10px;")
        layout.addRow(info_label)
        
        return widget
    
    def _create_position_tab(self):
        """Create the position tracking settings tab"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(10)
        
        # Tracking method
        self.tracking_method_combo = QComboBox()
        self.tracking_method_combo.addItems(["Brightness (brightest point)", "Color (target color center)"])
        layout.addRow("Tracking Method:", self.tracking_method_combo)
        
        # Info
        info_label = QLabel(
            "📍 Position Tracking outputs X/Y coordinates of the tracked point. "
            "Use 'Brightness' to track the brightest spot, or 'Color' to track "
            "the center of a specific color region."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {COLORS.TEXT_MUTED}; font-size: 11px; padding: 10px;")
        layout.addRow(info_label)
        
        return widget
    
    def _create_rpm_tab(self):
        """Create RPM detection settings tab"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(10)

        roi_group = QGroupBox("Region of Interest (ROI)")
        roi_layout = QGridLayout(roi_group)

        roi_layout.addWidget(QLabel("X:"), 0, 0)
        self.rpm_roi_x_spin = QSpinBox()
        self.rpm_roi_x_spin.setRange(0, 1920)
        roi_layout.addWidget(self.rpm_roi_x_spin, 0, 1)

        roi_layout.addWidget(QLabel("Y:"), 0, 2)
        self.rpm_roi_y_spin = QSpinBox()
        self.rpm_roi_y_spin.setRange(0, 1080)
        roi_layout.addWidget(self.rpm_roi_y_spin, 0, 3)

        roi_layout.addWidget(QLabel("Width:"), 1, 0)
        self.rpm_roi_w_spin = QSpinBox()
        self.rpm_roi_w_spin.setRange(10, 1920)
        self.rpm_roi_w_spin.setValue(200)
        roi_layout.addWidget(self.rpm_roi_w_spin, 1, 1)

        roi_layout.addWidget(QLabel("Height:"), 1, 2)
        self.rpm_roi_h_spin = QSpinBox()
        self.rpm_roi_h_spin.setRange(10, 1080)
        self.rpm_roi_h_spin.setValue(200)
        roi_layout.addWidget(self.rpm_roi_h_spin, 1, 3)

        layout.addRow(roi_group)

        self.rpm_ppr_spin = QDoubleSpinBox()
        self.rpm_ppr_spin.setRange(0.1, 100.0)
        self.rpm_ppr_spin.setValue(1.0)
        self.rpm_ppr_spin.setSingleStep(0.1)
        self.rpm_ppr_spin.setSuffix(" pulses/rev")
        layout.addRow("Pulses per Revolution:", self.rpm_ppr_spin)

        self.rpm_min_hz_spin = QDoubleSpinBox()
        self.rpm_min_hz_spin.setRange(0.1, 120.0)
        self.rpm_min_hz_spin.setValue(0.5)
        self.rpm_min_hz_spin.setSingleStep(0.1)
        self.rpm_min_hz_spin.setSuffix(" Hz")
        layout.addRow("Min Frequency:", self.rpm_min_hz_spin)

        self.rpm_max_hz_spin = QDoubleSpinBox()
        self.rpm_max_hz_spin.setRange(0.5, 240.0)
        self.rpm_max_hz_spin.setValue(30.0)
        self.rpm_max_hz_spin.setSingleStep(0.5)
        self.rpm_max_hz_spin.setSuffix(" Hz")
        layout.addRow("Max Frequency:", self.rpm_max_hz_spin)

        self.rpm_prominence_spin = QDoubleSpinBox()
        self.rpm_prominence_spin.setRange(1.0, 50.0)
        self.rpm_prominence_spin.setValue(3.0)
        self.rpm_prominence_spin.setSingleStep(0.5)
        layout.addRow("Min Spectral Prominence:", self.rpm_prominence_spin)

        self.rpm_history_spin = QDoubleSpinBox()
        self.rpm_history_spin.setRange(0.5, 15.0)
        self.rpm_history_spin.setValue(4.0)
        self.rpm_history_spin.setSingleStep(0.5)
        self.rpm_history_spin.setSuffix(" s window")
        layout.addRow("History Window:", self.rpm_history_spin)

        info_label = QLabel(
            "🔁 RPM estimates are derived from brightness flicker in the ROI. "
            "Use a high-contrast marker or reflective spot on the rotating part. "
            "Increase the prominence or narrow the frequency band if noise appears."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {COLORS.TEXT_MUTED}; font-size: 11px; padding: 10px;")
        layout.addRow(info_label)

        return widget
    
    def _create_fill_level_tab(self):
        """Create the fill level detection settings tab"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(10)
        
        # ROI settings
        roi_group = QGroupBox("Region of Interest (ROI)")
        roi_layout = QGridLayout(roi_group)
        
        roi_layout.addWidget(QLabel("X:"), 0, 0)
        self.roi_x_spin = QSpinBox()
        self.roi_x_spin.setRange(0, 1920)
        roi_layout.addWidget(self.roi_x_spin, 0, 1)
        
        roi_layout.addWidget(QLabel("Y:"), 0, 2)
        self.roi_y_spin = QSpinBox()
        self.roi_y_spin.setRange(0, 1080)
        roi_layout.addWidget(self.roi_y_spin, 0, 3)
        
        roi_layout.addWidget(QLabel("Width:"), 1, 0)
        self.roi_width_spin = QSpinBox()
        self.roi_width_spin.setRange(10, 1920)
        self.roi_width_spin.setValue(100)
        roi_layout.addWidget(self.roi_width_spin, 1, 1)
        
        roi_layout.addWidget(QLabel("Height:"), 1, 2)
        self.roi_height_spin = QSpinBox()
        self.roi_height_spin.setRange(10, 1080)
        self.roi_height_spin.setValue(100)
        roi_layout.addWidget(self.roi_height_spin, 1, 3)
        
        layout.addRow(roi_group)
        
        # Fill threshold
        self.fill_threshold_spin = QSpinBox()
        self.fill_threshold_spin.setRange(0, 255)
        self.fill_threshold_spin.setValue(128)
        layout.addRow("Brightness Threshold:", self.fill_threshold_spin)
        
        # Direction
        self.fill_direction_combo = QComboBox()
        self.fill_direction_combo.addItems(["Horizontal (left-right)", "Vertical (bottom-up)"])
        layout.addRow("Fill Direction:", self.fill_direction_combo)
        
        # Event threshold
        self.fill_event_threshold_spin = QSpinBox()
        self.fill_event_threshold_spin.setRange(0, 100)
        self.fill_event_threshold_spin.setValue(50)
        self.fill_event_threshold_spin.setSuffix(" %")
        layout.addRow("Event at Level:", self.fill_event_threshold_spin)
        
        # Info
        info_label = QLabel(
            "📊 Fill Level detection monitors a region and outputs 0-100% fill level. "
            "An event is triggered when the level crosses the threshold. "
            "Useful for monitoring containers, tubes, or liquid levels."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {COLORS.TEXT_MUTED}; font-size: 11px; padding: 10px;")
        layout.addRow(info_label)
        
        return widget
    
    def _create_preview_tab(self):
        """Create the preview/test tab with live camera feed"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        
        # Preview controls
        controls_layout = QHBoxLayout()
        
        self.preview_start_btn = QPushButton("▶️ Start Preview")
        self.preview_start_btn.setStyleSheet(ButtonStyles.success("small"))
        self.preview_start_btn.clicked.connect(self._toggle_preview)
        controls_layout.addWidget(self.preview_start_btn)
        
        self.test_detection_btn = QPushButton("🔍 Test Detection")
        self.test_detection_btn.setStyleSheet(ButtonStyles.secondary("small"))
        self.test_detection_btn.clicked.connect(self._test_detection)
        self.test_detection_btn.setEnabled(False)
        controls_layout.addWidget(self.test_detection_btn)
        
        self.show_roi_check = QCheckBox("Show ROI")
        self.show_roi_check.setChecked(True)
        self.show_roi_check.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY};")
        controls_layout.addWidget(self.show_roi_check)
        
        self.show_detections_check = QCheckBox("Show Detections")
        self.show_detections_check.setChecked(True)
        self.show_detections_check.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY};")
        controls_layout.addWidget(self.show_detections_check)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # Preview image label
        self.preview_label = QLabel()
        self.preview_label.setMinimumSize(480, 360)
        self.preview_label.setMaximumSize(640, 480)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(f"""
            QLabel {{
                background: {COLORS.BG_DARK};
                border: 2px solid {COLORS.BORDER_DEFAULT};
                border-radius: 8px;
            }}
        """)
        self.preview_label.setText("Click 'Start Preview' to see camera feed")
        layout.addWidget(self.preview_label, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Detection results
        self.detection_result_label = QLabel("")
        self.detection_result_label.setStyleSheet(f"""
            color: {COLORS.TEXT_SECONDARY}; 
            font-size: 11px; 
            padding: 5px;
            background: {COLORS.BG_INPUT};
            border-radius: 4px;
        """)
        self.detection_result_label.setWordWrap(True)
        self.detection_result_label.setMinimumHeight(40)
        layout.addWidget(self.detection_result_label)
        
        # Info
        info_label = QLabel(
            "👁️ Use this preview to test your settings. "
            "The ROI overlay shows the region being monitored. "
            "Detected events will be highlighted in the preview."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {COLORS.TEXT_MUTED}; font-size: 11px; padding: 5px;")
        layout.addWidget(info_label)
        
        # Initialize preview state
        self.preview_thread = None
        self.preview_running = False
        self.last_frame = None
        
        return widget
    
    def _toggle_preview(self):
        """Start or stop the camera preview"""
        if self.preview_running:
            self._stop_preview()
        else:
            self._start_preview()
    
    def _start_preview(self):
        """Start the camera preview"""
        try:
            camera_id = self.camera_id_spin.value()
            resolution = self.resolution_combo.currentText()
            width, height = map(int, resolution.split('x'))

            # Reset RPM estimator for fresh measurements
            self.rpm_test_estimator.reset()
            self._last_rpm_result = {}
            
            self.preview_thread = PreviewThread(camera_id, width, height)
            self.preview_thread.frame_ready.connect(self._update_preview)
            self.preview_thread.error_occurred.connect(self._preview_error)
            self.preview_thread.start()
            
            self.preview_running = True
            self.preview_start_btn.setText("⏹️ Stop Preview")
            self.preview_start_btn.setStyleSheet(ButtonStyles.danger("small"))
            self.test_detection_btn.setEnabled(True)
            self.detection_result_label.setText("Preview started. Adjust settings and click 'Test Detection'.")
            
        except Exception as e:
            QMessageBox.warning(self, "Preview Error", f"Could not start preview: {e}")
    
    def _stop_preview(self):
        """Stop the camera preview"""
        thread = self.preview_thread
        if thread:
            try:
                thread.frame_ready.disconnect(self._update_preview)
            except (TypeError, RuntimeError):
                pass
            try:
                thread.error_occurred.disconnect(self._preview_error)
            except (TypeError, RuntimeError):
                pass
            thread.stop()
            if thread.isRunning():
                thread.wait(3000)
            self.preview_thread = None

        self.preview_running = False
        self.preview_start_btn.setText("▶️ Start Preview")
        self.preview_start_btn.setStyleSheet(ButtonStyles.success("small"))
        self.test_detection_btn.setEnabled(False)
        self.preview_label.setText("Preview stopped")
        self.last_frame = None
        self.rpm_test_estimator.reset()
        self._last_rpm_result = {}
    
    def _update_preview(self, frame):
        """Update the preview with a new frame"""
        try:
            self.last_frame = frame.copy()
            display_frame = frame.copy()
            mode = self.mode_combo.currentData()
            frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Live RPM estimation during preview
            if mode == "rpm":
                rpm_settings = self._collect_settings()
                rpm_result = self.rpm_test_estimator.process(frame_gray, rpm_settings)
                self._last_rpm_result = rpm_result
                rpm_text = (
                    f"RPM: {rpm_result.get('rpm', 0.0):.1f} | "
                    f"Freq: {rpm_result.get('rpm_freq_hz', 0.0):.2f} Hz | "
                    f"Confidence: {rpm_result.get('rpm_confidence', 0.0):.1f}"
                )
                self.detection_result_label.setText(rpm_text)
            
            # Draw ROI if enabled
            if self.show_roi_check.isChecked():
                if mode == "fill_level":
                    x = self.roi_x_spin.value()
                    y = self.roi_y_spin.value()
                    w = self.roi_width_spin.value()
                    h = self.roi_height_spin.value()
                    cv2.rectangle(display_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    cv2.putText(display_frame, "ROI", (x, y - 5), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                elif mode == "brightness":
                    x = self.brightness_roi_x_spin.value()
                    y = self.brightness_roi_y_spin.value()
                    w = self.brightness_roi_width_spin.value()
                    h = self.brightness_roi_height_spin.value()
                    cv2.rectangle(display_frame, (x, y), (x + w, y + h), (255, 255, 0), 2)
                    cv2.putText(display_frame, "Brightness ROI", (x, y - 5),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
                elif mode == "rpm":
                    x = self.rpm_roi_x_spin.value()
                    y = self.rpm_roi_y_spin.value()
                    w = self.rpm_roi_w_spin.value()
                    h = self.rpm_roi_h_spin.value()
                    cv2.rectangle(display_frame, (x, y), (x + w, y + h), (255, 215, 0), 2)
                    cv2.putText(display_frame, "RPM ROI", (x, y - 5),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 215, 0), 1)
            
            # Convert to QImage and display
            height, width, channel = display_frame.shape
            bytes_per_line = 3 * width
            rgb_frame = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            q_img = QImage(rgb_frame.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
            
            # Scale to fit label while maintaining aspect ratio
            pixmap = QPixmap.fromImage(q_img)
            scaled_pixmap = pixmap.scaled(
                self.preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled_pixmap)
            
        except Exception as e:
            print(f"Preview update error: {e}")
    
    def _preview_error(self, error_msg):
        """Handle preview errors"""
        self._stop_preview()
        QMessageBox.warning(self, "Preview Error", error_msg)
    
    def _test_detection(self):
        """Test detection on the current frame"""
        if self.last_frame is None:
            self.detection_result_label.setText("⚠️ No frame available. Start the preview first.")
            return
        
        try:
            frame = self.last_frame.copy()
            mode = self.mode_combo.currentData()
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            results = []
            
            if mode == "light_events":
                # Test light event detection
                threshold = self.brightness_threshold_spin.value()
                min_pixels = self.min_pixels_spin.value()
                max_pixels = self.max_pixels_spin.value()
                
                # Calculate baseline
                baseline = np.mean(gray)
                std_dev = np.std(gray)
                
                # Find bright pixels
                if self.threshold_mode_combo.currentIndex() == 0:  # Absolute
                    bright_mask = gray > (baseline + threshold)
                else:  # Relative
                    bright_mask = gray > (baseline + self.relative_threshold_spin.value() * std_dev)
                
                bright_count = np.sum(bright_mask)
                
                # Find contours of bright regions
                bright_regions = np.where(bright_mask)
                if len(bright_regions[0]) > 0:
                    # Draw detected bright pixels on preview
                    display_frame = frame.copy()
                    display_frame[bright_mask] = [0, 0, 255]  # Mark bright pixels red
                    self._update_preview(display_frame)
                
                event_detected = min_pixels <= bright_count <= max_pixels
                results.append(f"Baseline: {baseline:.1f}, Std: {std_dev:.1f}")
                results.append(f"Bright pixels: {bright_count}")
                results.append(f"Event: {'✅ YES' if event_detected else '❌ No'} (range: {min_pixels}-{max_pixels})")
                
            elif mode == "brightness":
                x = self.brightness_roi_x_spin.value()
                y = self.brightness_roi_y_spin.value()
                w = self.brightness_roi_width_spin.value()
                h = self.brightness_roi_height_spin.value()
                
                # Clip ROI to frame bounds
                h_frame, w_frame = gray.shape
                x = max(0, min(x, w_frame - 1))
                y = max(0, min(y, h_frame - 1))
                w = max(1, min(w, w_frame - x))
                h = max(1, min(h, h_frame - y))
                
                roi = gray[y:y+h, x:x+w]
                mean_brightness = np.mean(roi)
                max_brightness = np.max(roi)
                min_brightness = np.min(roi)
                results.append(f"ROI: {w}x{h} at ({x},{y})")
                results.append(f"Mean: {mean_brightness:.1f}")
                results.append(f"Max: {max_brightness}, Min: {min_brightness}")
                
            elif mode == "fill_level":
                # Test fill level in ROI
                x = self.roi_x_spin.value()
                y = self.roi_y_spin.value()
                w = self.roi_width_spin.value()
                h = self.roi_height_spin.value()
                threshold = self.fill_threshold_spin.value()
                
                # Clip ROI to frame bounds
                h_frame, w_frame = gray.shape
                x = min(x, w_frame - 1)
                y = min(y, h_frame - 1)
                w = min(w, w_frame - x)
                h = min(h, h_frame - y)
                
                roi = gray[y:y+h, x:x+w]
                if roi.size > 0:
                    filled_pixels = np.sum(roi > threshold)
                    total_pixels = roi.size
                    fill_percent = (filled_pixels / total_pixels) * 100
                    
                    results.append(f"ROI: ({x}, {y}) {w}x{h}")
                    results.append(f"Fill Level: {fill_percent:.1f}%")
                    results.append(f"Threshold crossing: {'✅ YES' if fill_percent > self.fill_event_threshold_spin.value() else '❌ No'}")
                else:
                    results.append("⚠️ Invalid ROI - check coordinates")
                    
            elif mode == "color":
                # Test color detection
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                target_hue = self.target_hue_slider.value()
                tolerance = self.hue_tolerance_spin.value()
                sat_min = self.saturation_min_spin.value()
                
                # Create mask for target color
                lower = np.array([max(0, target_hue - tolerance), sat_min, 50])
                upper = np.array([min(179, target_hue + tolerance), 255, 255])
                mask = cv2.inRange(hsv, lower, upper)
                
                color_pixels = np.sum(mask > 0)
                total_pixels = mask.size
                color_percent = (color_pixels / total_pixels) * 100
                
                # Show detection overlay
                display_frame = frame.copy()
                display_frame[mask > 0] = [0, 255, 0]  # Highlight detected color
                self._update_preview(display_frame)
                
                results.append(f"Target Hue: {target_hue} ± {tolerance}")
                results.append(f"Color pixels: {color_pixels} ({color_percent:.2f}%)")
                
            elif mode == "particle_count":
                baseline = np.mean(gray)
                std_dev = np.std(gray)

                if self.particle_threshold_mode_combo.currentIndex() == 0:
                    threshold_val = baseline + self.particle_brightness_threshold_spin.value()
                else:
                    threshold_val = baseline + self.particle_relative_threshold_spin.value() * std_dev

                _, binary = cv2.threshold(gray, threshold_val, 255, cv2.THRESH_BINARY)
                contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                min_area = self.particle_min_size_spin.value()
                max_area = self.particle_max_size_spin.value()
                valid_contours = [c for c in contours if min_area <= cv2.contourArea(c) <= max_area]
                
                # Draw contours
                display_frame = frame.copy()
                cv2.drawContours(display_frame, valid_contours, -1, (0, 255, 0), 2)
                self._update_preview(display_frame)
                
                results.append(f"Total contours: {len(contours)}")
                results.append(f"Valid particles: {len(valid_contours)} (area: {min_area}-{max_area})")
                
            elif mode == "position":
                # Test position tracking
                if self.tracking_method_combo.currentIndex() == 0:  # Brightness
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(gray)
                    x, y = max_loc
                    h_frame, w_frame = gray.shape
                    x_percent = (x / w_frame) * 100
                    y_percent = (y / h_frame) * 100
                    
                    # Draw marker
                    display_frame = frame.copy()
                    cv2.circle(display_frame, max_loc, 10, (0, 0, 255), 2)
                    cv2.drawMarker(display_frame, max_loc, (0, 255, 0), cv2.MARKER_CROSS, 20, 2)
                    self._update_preview(display_frame)
                    
                    results.append(f"Brightest point: ({x}, {y})")
                    results.append(f"Position: {x_percent:.1f}%, {y_percent:.1f}%")
                    results.append(f"Brightness at point: {max_val}")
            elif mode == "rpm":
                rpm_settings = self._collect_settings()
                rpm_result = self.rpm_test_estimator.process(gray, rpm_settings)
                self._last_rpm_result = rpm_result
                results.append(f"RPM: {rpm_result.get('rpm', 0.0):.1f}")
                results.append(f"Freq: {rpm_result.get('rpm_freq_hz', 0.0):.2f} Hz")
                results.append(f"Confidence: {rpm_result.get('rpm_confidence', 0.0):.1f}")
                # Update preview text immediately
                self.detection_result_label.setText(" | ".join(results))
            
            self.detection_result_label.setText(" | ".join(results))
            
        except Exception as e:
            self.detection_result_label.setText(f"⚠️ Detection error: {e}")
    
    def closeEvent(self, event):
        """Clean up when dialog is closed"""
        self._stop_preview()
        super().closeEvent(event)
    
    def _on_mode_changed(self):
        """Handle mode selection change"""
        mode = self.mode_combo.currentData()
        if mode in self.MODES:
            self.mode_description.setText(self.MODES[mode]["description"])

        # Reset RPM estimator when changing modes to avoid stale data
        self.rpm_test_estimator.reset()
        self._last_rpm_result = {}
        
        preview_tab_index = self.settings_tabs.count() - 1
        # Switch to appropriate tab while keeping preview accessible
        tab_map = {
            "light_events": 0,
            "brightness": 1,
            "particle_count": 2,
            "color": 3,
            "position": 4,
            "rpm": 5,
            "fill_level": 6,
        }
        # Only switch if not on preview tab
        if self.settings_tabs.currentIndex() != preview_tab_index:
            self.settings_tabs.setCurrentIndex(tab_map.get(mode, 0))
    
    def _on_threshold_mode_changed(self):
        """Handle threshold mode change"""
        is_absolute = self.threshold_mode_combo.currentIndex() == 0
        self.brightness_threshold_spin.setEnabled(is_absolute)
        self.relative_threshold_spin.setEnabled(not is_absolute)
    
    def _update_hue_preview(self, hue):
        """Update the hue preview color"""
        # Convert HSV to RGB for preview
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(hue / 179.0, 1.0, 1.0)
        color = QColor(int(r * 255), int(g * 255), int(b * 255))
        self.hue_preview.setStyleSheet(
            f"background: {color.name()}; border-radius: 4px; border: 1px solid {COLORS.BORDER_DEFAULT};"
        )
    
    def _load_settings(self):
        """Load current settings into UI"""
        # Mode
        mode_index = self.mode_combo.findData(self.settings.get("mode", "light_events"))
        if mode_index >= 0:
            self.mode_combo.setCurrentIndex(mode_index)
        
        # Camera
        self.camera_id_spin.setValue(self.settings.get("camera_id", 0))
        resolution = f"{self.settings.get('width', 640)}x{self.settings.get('height', 480)}"
        res_index = self.resolution_combo.findText(resolution)
        if res_index >= 0:
            self.resolution_combo.setCurrentIndex(res_index)
        self.sample_rate_spin.setValue(self.settings.get("sample_rate", 10))
        self.auto_connect_cb.setChecked(self.settings.get("auto_connect", True))
        
        # Light events
        threshold_mode = self.settings.get("threshold_mode", "absolute")
        self.threshold_mode_combo.setCurrentIndex(0 if threshold_mode == "absolute" else 1)
        self.brightness_threshold_spin.setValue(self.settings.get("brightness_threshold", 30))
        self.relative_threshold_spin.setValue(self.settings.get("relative_threshold", 3.0))
        self.min_pixels_spin.setValue(self.settings.get("min_pixels", 1))
        self.max_pixels_spin.setValue(self.settings.get("max_pixels", 100))
        self.cooldown_spin.setValue(self.settings.get("cooldown_ms", 100))
        
        # Brightness
        self.brightness_roi_x_spin.setValue(self.settings.get("brightness_roi_x", 0))
        self.brightness_roi_y_spin.setValue(self.settings.get("brightness_roi_y", 0))
        self.brightness_roi_width_spin.setValue(self.settings.get("brightness_roi_width", 640))
        self.brightness_roi_height_spin.setValue(self.settings.get("brightness_roi_height", 480))
        
        # Particle counter
        particle_threshold_mode = self.settings.get("particle_threshold_mode", "relative")
        self.particle_threshold_mode_combo.setCurrentIndex(0 if particle_threshold_mode == "absolute" else 1)
        self.particle_brightness_threshold_spin.setValue(self.settings.get("particle_brightness_threshold", 50))
        self.particle_relative_threshold_spin.setValue(self.settings.get("particle_relative_threshold", 3.0))
        self.particle_min_size_spin.setValue(self.settings.get("particle_min_size", 3))
        self.particle_max_size_spin.setValue(self.settings.get("particle_max_size", 500))
        self.particle_min_distance_spin.setValue(self.settings.get("particle_min_distance", 5))
        self.particle_bg_subtract_check.setChecked(self.settings.get("particle_bg_subtract", False))
        self._on_particle_threshold_mode_changed()
        
        # Color
        self.target_hue_slider.setValue(self.settings.get("target_hue", 0))
        self.hue_tolerance_spin.setValue(self.settings.get("hue_tolerance", 10))
        self.saturation_min_spin.setValue(self.settings.get("saturation_min", 100))
        
        # Position
        tracking = self.settings.get("tracking_method", "brightness")
        self.tracking_method_combo.setCurrentIndex(0 if tracking == "brightness" else 1)
        
        # Fill level
        self.roi_x_spin.setValue(self.settings.get("roi_x", 0))
        self.roi_y_spin.setValue(self.settings.get("roi_y", 0))
        self.roi_width_spin.setValue(self.settings.get("roi_width", 100))
        self.roi_height_spin.setValue(self.settings.get("roi_height", 100))
        self.fill_threshold_spin.setValue(self.settings.get("fill_threshold", 128))
        direction = self.settings.get("fill_direction", "horizontal")
        self.fill_direction_combo.setCurrentIndex(0 if direction == "horizontal" else 1)
        self.fill_event_threshold_spin.setValue(self.settings.get("fill_threshold_percent", 50))

        # RPM
        self.rpm_roi_x_spin.setValue(self.settings.get("rpm_roi_x", 0))
        self.rpm_roi_y_spin.setValue(self.settings.get("rpm_roi_y", 0))
        self.rpm_roi_w_spin.setValue(self.settings.get("rpm_roi_width", 200))
        self.rpm_roi_h_spin.setValue(self.settings.get("rpm_roi_height", 200))
        self.rpm_history_spin.setValue(self.settings.get("rpm_history_seconds", 4.0))
        self.rpm_min_hz_spin.setValue(self.settings.get("rpm_min_hz", 0.5))
        self.rpm_max_hz_spin.setValue(self.settings.get("rpm_max_hz", 30.0))
        self.rpm_prominence_spin.setValue(self.settings.get("rpm_min_prominence", 3.0))
        self.rpm_ppr_spin.setValue(self.settings.get("rpm_pulses_per_rev", 1.0))
        
        # Event saving
        self.save_events_check.setChecked(self.settings.get("save_event_images", True))
        
        self._on_threshold_mode_changed()
        self._update_hue_preview(self.target_hue_slider.value())
    
    def _collect_settings(self):
        """Collect settings from UI"""
        # Parse resolution
        resolution = self.resolution_combo.currentText()
        width, height = map(int, resolution.split('x'))
        
        settings = {
            "mode": self.mode_combo.currentData(),
            "camera_id": self.camera_id_spin.value(),
            "width": width,
            "height": height,
            "sample_rate": self.sample_rate_spin.value(),
            
            # Light events
            "threshold_mode": "absolute" if self.threshold_mode_combo.currentIndex() == 0 else "relative",
            "brightness_threshold": self.brightness_threshold_spin.value(),
            "relative_threshold": self.relative_threshold_spin.value(),
            "min_pixels": self.min_pixels_spin.value(),
            "max_pixels": self.max_pixels_spin.value(),
            "cooldown_ms": self.cooldown_spin.value(),
            
            # Brightness
            "brightness_roi_x": self.brightness_roi_x_spin.value(),
            "brightness_roi_y": self.brightness_roi_y_spin.value(),
            "brightness_roi_width": self.brightness_roi_width_spin.value(),
            "brightness_roi_height": self.brightness_roi_height_spin.value(),
            
            # Particle counter
            "particle_threshold_mode": "absolute" if self.particle_threshold_mode_combo.currentIndex() == 0 else "relative",
            "particle_brightness_threshold": self.particle_brightness_threshold_spin.value(),
            "particle_relative_threshold": self.particle_relative_threshold_spin.value(),
            "particle_min_size": self.particle_min_size_spin.value(),
            "particle_max_size": self.particle_max_size_spin.value(),
            "particle_min_distance": self.particle_min_distance_spin.value(),
            "particle_bg_subtract": self.particle_bg_subtract_check.isChecked(),
            
            # Color
            "target_hue": self.target_hue_slider.value(),
            "hue_tolerance": self.hue_tolerance_spin.value(),
            "saturation_min": self.saturation_min_spin.value(),
            
            # Position
            "tracking_method": "brightness" if self.tracking_method_combo.currentIndex() == 0 else "color",
            
            # Fill level
            "roi_x": self.roi_x_spin.value(),
            "roi_y": self.roi_y_spin.value(),
            "roi_width": self.roi_width_spin.value(),
            "roi_height": self.roi_height_spin.value(),
            "fill_threshold": self.fill_threshold_spin.value(),
            "fill_direction": "horizontal" if self.fill_direction_combo.currentIndex() == 0 else "vertical",
            "fill_threshold_percent": self.fill_event_threshold_spin.value(),
            
            # RPM
            "rpm_roi_x": self.rpm_roi_x_spin.value(),
            "rpm_roi_y": self.rpm_roi_y_spin.value(),
            "rpm_roi_width": self.rpm_roi_w_spin.value(),
            "rpm_roi_height": self.rpm_roi_h_spin.value(),
            "rpm_history_seconds": self.rpm_history_spin.value(),
            "rpm_min_hz": self.rpm_min_hz_spin.value(),
            "rpm_max_hz": self.rpm_max_hz_spin.value(),
            "rpm_min_prominence": self.rpm_prominence_spin.value(),
            "rpm_pulses_per_rev": self.rpm_ppr_spin.value(),
            "auto_connect": self.auto_connect_cb.isChecked(),
            
            # Event saving
            "save_event_images": self.save_events_check.isChecked(),
        }
        
        # Preserve existing output_dir as fallback (images are saved to run_directory when available)
        if "output_dir" in self.settings:
            settings["output_dir"] = self.settings["output_dir"]
        
        return settings
    
    def _validate_settings(self):
        """Reject invalid min/max ranges and obviously invalid ROIs."""
        issues = []
        if self.min_pixels_spin.value() > self.max_pixels_spin.value():
            issues.append("Light events: Min pixels cannot exceed max pixels.")
        if self.particle_min_size_spin.value() > self.particle_max_size_spin.value():
            issues.append("Particle counter: Min size cannot exceed max size.")
        if self.rpm_min_hz_spin.value() > self.rpm_max_hz_spin.value():
            issues.append("RPM: Min frequency cannot exceed max frequency.")
        if self.roi_width_spin.value() < 1 or self.roi_height_spin.value() < 1:
            issues.append("Fill level ROI must have positive width and height.")
        if issues:
            QMessageBox.warning(self, "Validation Error", "\n".join(issues))
            return False
        return True

    def _apply_settings(self):
        """Apply settings without closing dialog"""
        if not self._validate_settings():
            return
        self.settings = self._collect_settings()
        self.settings_changed.emit(self.settings)
    
    def _ok_clicked(self):
        """OK button clicked - apply and close"""
        if not self._validate_settings():
            return
        self.settings = self._collect_settings()
        self.settings_changed.emit(self.settings)
        self.accept()
    
    def get_settings(self):
        """Get the current settings"""
        return self._collect_settings()

    def _setup_help_panel(self):
        """Setup the help panel"""
        self.help_panel = HelpPanel("Optical Sensor Help")
        self.help_panel.close_requested.connect(self._toggle_help)
        self.help_panel.setVisible(False)
        self.content_splitter.addWidget(self.help_panel)

        # Load help content
        help_content = get_help_content("optical_sensor")
        self.help_panel.clear_sections()
        self.help_panel.title = help_content.get("title", "Help")

        for section in help_content.get("sections", []):
            self.help_panel.add_section(
                section.get("title", ""),
                section.get("content", ""),
                section.get("icon", "📖")
            )

        # Expand first section by default
        if self.help_panel.sections:
            self.help_panel.sections[0]._toggle()

    def _toggle_help(self):
        """Toggle help panel visibility"""
        self.help_visible = not hasattr(self, 'help_visible') or not self.help_visible
        self.help_panel.setVisible(self.help_visible)
        self.help_btn.setChecked(self.help_visible)

        if self.help_visible:
            # Set splitter sizes to show help
            total = self.content_splitter.width()
            self.content_splitter.setSizes([total - 350, 350])


class OpticalSensorAddDialog(QDialog):
    """Dialog for adding a new Optical Sensor"""
    
    def __init__(self, parent=None, available_cameras=None):
        super().__init__(parent)
        self.setWindowTitle("Add Optical Sensor")
        self.setMinimumSize(400, 300)
        
        # Apply dark dialog style
        self.setStyleSheet(DialogStyles.dark_dialog())
        
        self.available_cameras = available_cameras or []
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        header = QLabel("🎥 Add New Optical Sensor")
        header.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLORS.TEXT_PRIMARY};")
        layout.addWidget(header)
        
        # Form
        form_layout = QFormLayout()
        
        # Sensor name
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g., Light Detector 1")
        form_layout.addRow("Sensor Name:", self.name_edit)
        
        # Camera selection
        self.camera_combo = QComboBox()
        if self.available_cameras:
            for cam_id in self.available_cameras:
                self.camera_combo.addItem(f"Camera index {cam_id}", cam_id)
        else:
            self.camera_combo.addItem("No cameras available", -1)
        form_layout.addRow("Camera:", self.camera_combo)
        
        # Mode selection
        self.mode_combo = QComboBox()
        for mode_key, mode_info in OpticalSensorConfigDialog.MODES.items():
            self.mode_combo.addItem(
                f"{mode_info['icon']} {mode_info['name']}", 
                mode_key
            )
        form_layout.addRow("Detection Mode:", self.mode_combo)
        
        self.auto_connect_cb = QCheckBox("Auto-connect on Startup")
        self.auto_connect_cb.setChecked(True)
        form_layout.addRow("", self.auto_connect_cb)
        
        layout.addLayout(form_layout)
        
        # Info text
        info = QLabel(
            "⚠️ Note: A camera used as an optical sensor cannot be used "
            "simultaneously for video recording in the Camera tab."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {COLORS.WARNING}; font-size: 11px; padding: 10px;")
        layout.addWidget(info)
        
        layout.addStretch()
        
        # Buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(ButtonStyles.secondary("medium"))
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)
        
        add_btn = QPushButton("Add Sensor")
        add_btn.setStyleSheet(ButtonStyles.success("medium"))
        add_btn.clicked.connect(self._validate_and_accept)
        buttons_layout.addWidget(add_btn)
        
        layout.addLayout(buttons_layout)
    
    def _validate_and_accept(self):
        """Validate input and accept dialog"""
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Validation Error", "Please enter a sensor name.")
            return
        
        camera_id = self.camera_combo.currentData()
        if camera_id == -1:
            QMessageBox.warning(self, "Validation Error", "No camera available.")
            return
        
        self.accept()
    
    def get_sensor_config(self):
        """Get the new sensor configuration"""
        return {
            "name": self.name_edit.text().strip(),
            "camera_id": self.camera_combo.currentData(),
            "mode": self.mode_combo.currentData(),
            "auto_connect": self.auto_connect_cb.isChecked(),
        }

