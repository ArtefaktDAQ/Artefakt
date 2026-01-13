"""
Optical Sensor Quick Test Tool

Provides a lightweight way to preview a webcam and estimate RPM/flicker
without starting a full run. Uses the same RPM estimator as the optical
sensor interface.
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QCheckBox,
    QGroupBox,
    QFormLayout,
    QSpinBox,
    QDoubleSpinBox,
    QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QMetaObject, Q_ARG
from PyQt6.QtGui import QImage, QPixmap

import cv2

from app.ui.theme import ButtonStyles, COLORS, GroupBoxStyles
from app.core.interfaces.optical_sensor_interface import (
    OpticalSensorInterface,
    RpmEstimator,
)
from app.ui.dialogs.optical_sensor_dialog import PreviewThread


class OpticalSensorTool(QWidget):
    """Quick tester for webcam-based RPM detection."""
    
    # Signal for thread-safe camera list updates
    cameras_scanned = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = None
        self.preview_thread = None
        self.preview_running = False
        self.last_frame = None
        self.rpm_estimator = RpmEstimator()
        self._last_result = {}
        self._is_scanning = False  # Flag to prevent multiple concurrent scans

        self._setup_ui()
        
        # Connect signal for thread-safe updates
        self.cameras_scanned.connect(self._do_update_camera_combo)
        
    def set_main_window(self, main_window):
        """Set reference to main window and trigger initial camera scan."""
        self.main_window = main_window
        # Trigger initial scan now that we have main_window reference 
        # to correctly skip indices in use.
        self._populate_cameras()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(0)

        # Centering container
        centering_layout = QHBoxLayout()
        centering_layout.addStretch()

        # Content container with max width
        content_widget = QWidget()
        content_widget.setMaximumWidth(700)
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QLabel("🔁 Optical RPM Tester")
        header.setStyleSheet("color: #fff; font-weight: bold; font-size: 14px;")
        layout.addWidget(header)

        desc = QLabel(
            "Use a camera and estimate RPM from brightness flicker in a selected ROI. "
            "Use a high-contrast marker on the rotating part for best results."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY};")
        layout.addWidget(desc)

        # Camera controls
        cam_group = QGroupBox("Camera")
        cam_group.setStyleSheet(GroupBoxStyles.compact())
        cam_form = QFormLayout(cam_group)

        self.camera_combo = QComboBox()
        cam_form.addRow("Camera:", self.camera_combo)

        res_layout = QHBoxLayout()
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(
            ["320x240", "640x480", "800x600", "1280x720", "1920x1080"]
        )
        self.resolution_combo.setCurrentText("640x480")
        res_layout.addWidget(self.resolution_combo)

        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setStyleSheet(ButtonStyles.secondary("small"))
        refresh_btn.clicked.connect(self._populate_cameras)
        res_layout.addWidget(refresh_btn)

        cam_form.addRow("Resolution:", res_layout)

        layout.addWidget(cam_group)

        # RPM settings
        rpm_group = QGroupBox("RPM Detection")
        rpm_group.setStyleSheet(GroupBoxStyles.compact())
        rpm_form = QFormLayout(rpm_group)

        roi_layout = QHBoxLayout()
        self.rpm_roi_x = QSpinBox()
        self.rpm_roi_x.setRange(0, 4000)
        self.rpm_roi_x.setValue(0)
        self.rpm_roi_y = QSpinBox()
        self.rpm_roi_y.setRange(0, 4000)
        self.rpm_roi_y.setValue(0)
        roi_layout.addWidget(QLabel("X"))
        roi_layout.addWidget(self.rpm_roi_x)
        roi_layout.addWidget(QLabel("Y"))
        roi_layout.addWidget(self.rpm_roi_y)
        rpm_form.addRow("ROI Position:", roi_layout)

        roi_size_layout = QHBoxLayout()
        self.rpm_roi_w = QSpinBox()
        self.rpm_roi_w.setRange(10, 4000)
        self.rpm_roi_w.setValue(200)
        self.rpm_roi_h = QSpinBox()
        self.rpm_roi_h.setRange(10, 4000)
        self.rpm_roi_h.setValue(200)
        roi_size_layout.addWidget(QLabel("W"))
        roi_size_layout.addWidget(self.rpm_roi_w)
        roi_size_layout.addWidget(QLabel("H"))
        roi_size_layout.addWidget(self.rpm_roi_h)
        rpm_form.addRow("ROI Size:", roi_size_layout)

        self.rpm_ppr = QDoubleSpinBox()
        self.rpm_ppr.setRange(0.1, 100.0)
        self.rpm_ppr.setValue(1.0)
        self.rpm_ppr.setSingleStep(0.1)
        self.rpm_ppr.setSuffix(" pulses/rev")
        rpm_form.addRow("Pulses per Rev:", self.rpm_ppr)

        self.rpm_min_hz = QDoubleSpinBox()
        self.rpm_min_hz.setRange(0.1, 120.0)
        self.rpm_min_hz.setValue(0.5)
        self.rpm_min_hz.setSingleStep(0.1)
        self.rpm_min_hz.setSuffix(" Hz")
        rpm_form.addRow("Min Frequency:", self.rpm_min_hz)

        self.rpm_max_hz = QDoubleSpinBox()
        self.rpm_max_hz.setRange(0.5, 240.0)
        self.rpm_max_hz.setValue(30.0)
        self.rpm_max_hz.setSingleStep(0.5)
        self.rpm_max_hz.setSuffix(" Hz")
        rpm_form.addRow("Max Frequency:", self.rpm_max_hz)

        self.rpm_prominence = QDoubleSpinBox()
        self.rpm_prominence.setRange(1.0, 50.0)
        self.rpm_prominence.setValue(3.0)
        self.rpm_prominence.setSingleStep(0.5)
        rpm_form.addRow("Min Prominence:", self.rpm_prominence)

        self.rpm_history = QDoubleSpinBox()
        self.rpm_history.setRange(0.5, 15.0)
        self.rpm_history.setValue(4.0)
        self.rpm_history.setSingleStep(0.5)
        self.rpm_history.setSuffix(" s")
        rpm_form.addRow("History Window:", self.rpm_history)

        self.show_roi_cb = QCheckBox("Show ROI on preview")
        self.show_roi_cb.setChecked(True)
        rpm_form.addRow(self.show_roi_cb)

        layout.addWidget(rpm_group)

        # Preview controls
        controls = QHBoxLayout()
        self.preview_btn = QPushButton("▶ Start Camera")
        self.preview_btn.setStyleSheet(ButtonStyles.success("small"))
        self.preview_btn.clicked.connect(self._toggle_preview)
        controls.addWidget(self.preview_btn)
        controls.addStretch()
        layout.addLayout(controls)

        self.preview_label = QLabel("Camera stopped")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(320)
        self.preview_label.setStyleSheet(
            f"""
            QLabel {{
                background: {COLORS.BG_DARK};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 6px;
                color: {COLORS.TEXT_SECONDARY};
            }}
            """
        )
        layout.addWidget(self.preview_label)

        self.result_label = QLabel("RPM: -- | Freq: -- | Confidence: --")
        self.result_label.setStyleSheet(
            f"color: {COLORS.TEXT_PRIMARY}; background: {COLORS.BG_INPUT}; padding: 6px; border-radius: 4px;"
        )
        layout.addWidget(self.result_label)

        layout.addStretch()
        
        centering_layout.addWidget(content_widget)
        centering_layout.addStretch()
        main_layout.addLayout(centering_layout)
        main_layout.addStretch()

    def _populate_cameras(self):
        """Refresh available camera list in a background thread to prevent UI freeze."""
        if self._is_scanning:
            return
            
        self._is_scanning = True
        self.camera_combo.clear()
        self.camera_combo.addItem("Scanning cameras...", -1)
        self.camera_combo.setEnabled(False)
        
        from threading import Thread
        
        def scan_task():
            try:
                # Identify which camera index is currently in use by the main application
                # to avoid probing it, which causes a disconnect.
                skip_indices = []
                if self.main_window and hasattr(self.main_window, 'camera_controller'):
                    cc = self.main_window.camera_controller
                    # Use is_connected attribute which is managed by CameraController
                    is_main_connected = getattr(cc, 'is_connected', False)
                    if is_main_connected and hasattr(cc, 'camera_thread') and cc.camera_thread:
                        skip_indices.append(cc.camera_thread.camera_id)
                
                available = OpticalSensorInterface.list_available_cameras(skip_indices=skip_indices)
                self.cameras_scanned.emit(available)
            except Exception as e:
                print(f"Error scanning cameras: {e}")
                self.cameras_scanned.emit([])
            finally:
                self._is_scanning = False

        Thread(target=scan_task, daemon=True).start()

    @pyqtSlot(list)
    def _do_update_camera_combo(self, available):
        """Actual UI update for camera combo."""
        current = self.camera_combo.currentData()
        self.camera_combo.clear()
        self.camera_combo.setEnabled(True)
        
        if not available:
            self.camera_combo.addItem("No cameras found", -1)
            return

        for cam_id in available:
            self.camera_combo.addItem(f"Camera index {cam_id}", cam_id)

        if current is not None:
            idx = self.camera_combo.findData(current)
            if idx >= 0:
                self.camera_combo.setCurrentIndex(idx)

    def _collect_settings(self):
        """Collect rpm-specific settings."""
        return {
            "rpm_roi_x": self.rpm_roi_x.value(),
            "rpm_roi_y": self.rpm_roi_y.value(),
            "rpm_roi_width": self.rpm_roi_w.value(),
            "rpm_roi_height": self.rpm_roi_h.value(),
            "rpm_history_seconds": self.rpm_history.value(),
            "rpm_min_hz": self.rpm_min_hz.value(),
            "rpm_max_hz": self.rpm_max_hz.value(),
            "rpm_min_prominence": self.rpm_prominence.value(),
            "rpm_pulses_per_rev": self.rpm_ppr.value(),
        }

    def _toggle_preview(self):
        if self.preview_running:
            self._stop_preview()
        else:
            self._start_preview()

    def _start_preview(self):
        cam_id = self.camera_combo.currentData()
        if cam_id is None or cam_id == -1:
            QMessageBox.warning(self, "Camera", "No camera selected.")
            return

        width, height = map(int, self.resolution_combo.currentText().split("x"))

        try:
            self.rpm_estimator.reset()
            self.preview_thread = PreviewThread(cam_id, width, height)
            self.preview_thread.frame_ready.connect(self._on_frame)
            self.preview_thread.error_occurred.connect(self._on_preview_error)
            self.preview_thread.start()

            self.preview_running = True
            self.preview_btn.setText("⏹ Stop Camera")
            self.preview_btn.setStyleSheet(ButtonStyles.danger("small"))
            self.preview_label.setText("Starting camera...")
        except Exception as exc:
            QMessageBox.critical(self, "Preview Error", str(exc))

    def _stop_preview(self):
        if self.preview_thread:
            self.preview_thread.stop()
            self.preview_thread = None

        self.preview_running = False
        self.last_frame = None
        self.rpm_estimator.reset()
        self.preview_btn.setText("▶ Start Camera")
        self.preview_btn.setStyleSheet(ButtonStyles.success("small"))
        self.preview_label.setText("Camera stopped")
        self.result_label.setText("RPM: -- | Freq: -- | Confidence: --")

    def _on_preview_error(self, msg):
        self._stop_preview()
        QMessageBox.warning(self, "Preview Error", msg)

    def _on_frame(self, frame):
        """Handle incoming frame from preview thread."""
        try:
            self.last_frame = frame.copy()
            display_frame = frame.copy()
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            result = self.rpm_estimator.process(gray, self._collect_settings())
            self._last_result = result
            self._update_result_label(result)

            if self.show_roi_cb.isChecked():
                x = self.rpm_roi_x.value()
                y = self.rpm_roi_y.value()
                w = self.rpm_roi_w.value()
                h = self.rpm_roi_h.value()
                cv2.rectangle(display_frame, (x, y), (x + w, y + h), (255, 215, 0), 2)

            # Convert to pixmap
            height, width, channel = display_frame.shape
            bytes_per_line = 3 * width
            rgb_frame = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            q_img = QImage(
                rgb_frame.data,
                width,
                height,
                bytes_per_line,
                QImage.Format.Format_RGB888,
            )
            pixmap = QPixmap.fromImage(q_img).scaled(
                self.preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview_label.setPixmap(pixmap)
        except Exception as exc:
            self.result_label.setText(f"⚠️ Preview error: {exc}")

    def _update_result_label(self, result: dict):
        rpm = result.get("rpm", 0.0)
        freq = result.get("rpm_freq_hz", 0.0)
        conf = result.get("rpm_confidence", 0.0)
        self.result_label.setText(
            f"RPM: {rpm:.1f} | Freq: {freq:.2f} Hz | Confidence: {conf:.1f}"
        )

    def stop(self):
        """Stop preview when the tool is closed."""
        self._stop_preview()

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)

