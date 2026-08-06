"""
Sensor Calibration Tool

Multi-point calibration wizard with:
- Reference point input (measured vs. actual values)
- Linear and polynomial regression
- Offset and gain calculation
- Live preview of calibrated values
- Export/Import calibration data
- Apply calibration to sensors
"""

import numpy as np
import json
import csv
from datetime import datetime
from typing import List, Tuple, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QPushButton, QSpinBox, QDoubleSpinBox,
    QGroupBox, QTableWidget, QTableWidgetItem, QSplitter,
    QFrame, QFileDialog, QHeaderView, QMessageBox,
    QRadioButton, QButtonGroup, QLineEdit, QTextEdit
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor

import pyqtgraph as pg

# Import theme system
from app.ui.theme import GroupBoxStyles, GraphStyles


class CalibrationPoint:
    """Represents a single calibration point"""
    def __init__(self, measured: float, actual: float, timestamp: str = None):
        self.measured = measured
        self.actual = actual
        self.timestamp = timestamp or datetime.now().isoformat()


class CalibrationResult:
    """Stores calibration calculation results"""
    def __init__(self):
        self.method = "linear"  # linear, polynomial, offset_gain
        self.coefficients = []  # Polynomial coefficients (highest degree first)
        self.offset = 0.0
        self.gain = 1.0
        self.r_squared = 0.0
        self.rmse = 0.0
        self.points_count = 0
        self.created_at = datetime.now().isoformat()


class SensorCalibrationTool(QWidget):
    """Sensor Calibration Tool with multi-point wizard"""
    
    # Signal emitted when calibration is applied
    calibration_applied = pyqtSignal(str, dict)  # sensor_key, calibration_data
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = None
        self.sensor_controller = None
        
        # Calibration data
        self.calibration_points: List[CalibrationPoint] = []
        self.calibration_result: Optional[CalibrationResult] = None
        self.current_sensor_key = None
        
        # Live update timer
        self.live_timer = QTimer()
        self.live_timer.timeout.connect(self._update_live_reading)
        self.live_timer.setInterval(500)
        
        self._setup_ui()
    
    def set_main_window(self, main_window):
        """Set reference to main window"""
        self.main_window = main_window
        if hasattr(main_window, 'sensor_controller'):
            self.sensor_controller = main_window.sensor_controller
        self._populate_sensor_combo()
    
    def _setup_ui(self):
        """Setup the main UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Create splitter for left/right layout
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # === LEFT PANEL: Calibration Input ===
        left_panel = QFrame()
        left_panel.setStyleSheet("QFrame { background-color: #1a1a2e; border-radius: 8px; }")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(15, 15, 15, 15)
        left_layout.setSpacing(10)
        
        # Title
        title_label = QLabel("🔧 Sensor Calibration Wizard")
        title_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #FFC107;")
        left_layout.addWidget(title_label)
        
        # Sensor Selection
        sensor_group = QGroupBox("1️⃣ Select Sensor")
        sensor_group.setStyleSheet(self._groupbox_style())
        sensor_layout = QVBoxLayout(sensor_group)
        
        self.sensor_combo = QComboBox()
        self.sensor_combo.setMinimumWidth(200)
        self.sensor_combo.currentIndexChanged.connect(self._on_sensor_changed)
        sensor_layout.addWidget(self.sensor_combo)
        
        # Live reading display
        live_layout = QHBoxLayout()
        live_layout.addWidget(QLabel("Current Reading:"))
        self.live_reading_label = QLabel("-- ")
        self.live_reading_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 16px;")
        live_layout.addWidget(self.live_reading_label)
        live_layout.addStretch()
        
        self.capture_btn = QPushButton("📷 Capture Value")
        self.capture_btn.setStyleSheet(self._button_style("#2196F3"))
        self.capture_btn.clicked.connect(self._capture_current_value)
        live_layout.addWidget(self.capture_btn)
        sensor_layout.addLayout(live_layout)
        
        left_layout.addWidget(sensor_group)
        
        # Calibration Method
        method_group = QGroupBox("2️⃣ Calibration Method")
        method_group.setStyleSheet(self._groupbox_style())
        method_layout = QVBoxLayout(method_group)
        
        self.method_button_group = QButtonGroup()
        
        self.linear_radio = QRadioButton("Linear (y = mx + b) - Best for 2+ points")
        self.linear_radio.setChecked(True)
        self.linear_radio.setStyleSheet("color: #ccc;")
        self.method_button_group.addButton(self.linear_radio, 0)
        method_layout.addWidget(self.linear_radio)
        
        self.poly_radio = QRadioButton("Polynomial (y = ax² + bx + c) - Best for 3+ points")
        self.poly_radio.setStyleSheet("color: #ccc;")
        self.method_button_group.addButton(self.poly_radio, 1)
        method_layout.addWidget(self.poly_radio)
        
        poly_degree_layout = QHBoxLayout()
        poly_degree_layout.addSpacing(20)
        poly_degree_layout.addWidget(QLabel("Degree:"))
        self.poly_degree_spin = QSpinBox()
        self.poly_degree_spin.setRange(2, 5)
        self.poly_degree_spin.setValue(2)
        poly_degree_layout.addWidget(self.poly_degree_spin)
        poly_degree_layout.addStretch()
        method_layout.addLayout(poly_degree_layout)
        
        self.offset_gain_radio = QRadioButton("Offset + Gain (manual values)")
        self.offset_gain_radio.setStyleSheet("color: #ccc;")
        self.method_button_group.addButton(self.offset_gain_radio, 2)
        method_layout.addWidget(self.offset_gain_radio)
        
        # Manual offset/gain inputs
        manual_layout = QGridLayout()
        manual_layout.setColumnStretch(2, 1)
        manual_layout.addWidget(QLabel("Offset:"), 0, 0)
        self.manual_offset_spin = QDoubleSpinBox()
        self.manual_offset_spin.setRange(-1000000, 1000000)
        self.manual_offset_spin.setDecimals(6)
        self.manual_offset_spin.setValue(0)
        manual_layout.addWidget(self.manual_offset_spin, 0, 1)
        
        manual_layout.addWidget(QLabel("Gain:"), 1, 0)
        self.manual_gain_spin = QDoubleSpinBox()
        self.manual_gain_spin.setRange(-1000000, 1000000)
        self.manual_gain_spin.setDecimals(6)
        self.manual_gain_spin.setValue(1.0)
        manual_layout.addWidget(self.manual_gain_spin, 1, 1)
        method_layout.addLayout(manual_layout)
        
        left_layout.addWidget(method_group)
        
        # Calibration Points
        points_group = QGroupBox("3️⃣ Calibration Points")
        points_group.setStyleSheet(self._groupbox_style())
        points_layout = QVBoxLayout(points_group)
        
        # Add point input
        add_point_layout = QHBoxLayout()
        add_point_layout.addWidget(QLabel("Measured:"))
        self.measured_spin = QDoubleSpinBox()
        self.measured_spin.setRange(-1000000, 1000000)
        self.measured_spin.setDecimals(6)
        add_point_layout.addWidget(self.measured_spin)
        
        add_point_layout.addWidget(QLabel("Actual:"))
        self.actual_spin = QDoubleSpinBox()
        self.actual_spin.setRange(-1000000, 1000000)
        self.actual_spin.setDecimals(6)
        add_point_layout.addWidget(self.actual_spin)
        
        self.add_point_btn = QPushButton("➕ Add")
        self.add_point_btn.setStyleSheet(self._button_style("#4CAF50"))
        self.add_point_btn.clicked.connect(self._add_calibration_point)
        add_point_layout.addWidget(self.add_point_btn)
        points_layout.addLayout(add_point_layout)
        
        # Points table
        self.points_table = QTableWidget()
        self.points_table.setColumnCount(4)
        self.points_table.setHorizontalHeaderLabels(["Measured", "Actual", "Error", ""])
        self.points_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.points_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.points_table.setColumnWidth(3, 60)
        self.points_table.setStyleSheet("""
            QTableWidget {
                background-color: #222;
                color: #ddd;
                gridline-color: #444;
                border: none;
            }
            QHeaderView::section {
                background-color: #333;
                color: #fff;
                padding: 5px;
                border: 1px solid #444;
            }
        """)
        self.points_table.setMaximumHeight(150)
        points_layout.addWidget(self.points_table)
        
        # Quick calibration buttons
        quick_layout = QHBoxLayout()
        
        self.clear_points_btn = QPushButton("🗑️ Clear All")
        self.clear_points_btn.setStyleSheet(self._button_style("#666"))
        self.clear_points_btn.clicked.connect(self._clear_all_points)
        quick_layout.addWidget(self.clear_points_btn)
        
        self.add_zero_btn = QPushButton("0️⃣ Add Zero Point")
        self.add_zero_btn.setStyleSheet(self._button_style("#607D8B"))
        self.add_zero_btn.setToolTip("Add (0, 0) as calibration point")
        self.add_zero_btn.clicked.connect(lambda: self._add_point(0, 0))
        quick_layout.addWidget(self.add_zero_btn)
        
        quick_layout.addStretch()
        points_layout.addLayout(quick_layout)
        
        left_layout.addWidget(points_group)
        
        # Calculate and Apply
        action_group = QGroupBox("4️⃣ Calculate & Apply")
        action_group.setStyleSheet(self._groupbox_style())
        action_layout = QVBoxLayout(action_group)
        
        btn_layout = QHBoxLayout()
        
        self.calculate_btn = QPushButton("🔢 Calculate Calibration")
        self.calculate_btn.setStyleSheet(self._button_style("#FF9800"))
        self.calculate_btn.clicked.connect(self._calculate_calibration)
        btn_layout.addWidget(self.calculate_btn)
        
        self.apply_btn = QPushButton("✅ Apply to Sensor")
        self.apply_btn.setStyleSheet(self._button_style("#4CAF50"))
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply_calibration)
        btn_layout.addWidget(self.apply_btn)
        
        self.reset_btn = QPushButton("🔄 Reset Calibration")
        self.reset_btn.setStyleSheet(self._button_style("#F44336"))
        self.reset_btn.setToolTip("Remove all calibration from the selected sensor")
        self.reset_btn.clicked.connect(self._reset_calibration)
        btn_layout.addWidget(self.reset_btn)
        
        btn_layout.addStretch()
        action_layout.addLayout(btn_layout)
        
        left_layout.addWidget(action_group)
        
        left_layout.addStretch()
        splitter.addWidget(left_panel)
        
        # === RIGHT PANEL: Results & Preview ===
        right_panel = QFrame()
        right_panel.setStyleSheet("QFrame { background-color: #1a1a2e; border-radius: 8px; }")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(15, 15, 15, 15)
        right_layout.setSpacing(10)
        
        # Calibration Curve Plot
        curve_title = QLabel("📈 Calibration Curve")
        curve_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        curve_title.setStyleSheet("color: #4CAF50;")
        right_layout.addWidget(curve_title)
        
        self.curve_plot = pg.PlotWidget()
        GraphStyles.apply_calibration_theme(self.curve_plot)
        self.curve_plot.setLabel('bottom', 'Measured Value')
        self.curve_plot.setLabel('left', 'Actual Value')
        self.curve_plot.setMinimumHeight(200)
        right_layout.addWidget(self.curve_plot)
        
        # Results display
        results_group = QGroupBox("📋 Calibration Results")
        results_group.setStyleSheet(self._groupbox_style())
        results_layout = QGridLayout(results_group)
        
        self.result_labels = {}
        result_items = [
            ("method", "Method:"),
            ("equation", "Equation:"),
            ("offset", "Offset:"),
            ("gain", "Gain/Slope:"),
            ("r_squared", "R² (Fit Quality):"),
            ("rmse", "RMSE:"),
        ]
        
        for row, (key, label_text) in enumerate(result_items):
            label = QLabel(label_text)
            label.setStyleSheet("color: #888;")
            value = QLabel("--")
            value.setStyleSheet("color: #fff; font-weight: bold;")
            value.setWordWrap(True)
            results_layout.addWidget(label, row, 0)
            results_layout.addWidget(value, row, 1)
            self.result_labels[key] = value
        
        right_layout.addWidget(results_group)
        
        # Live Preview
        preview_group = QGroupBox("🔍 Live Preview")
        preview_group.setStyleSheet(self._groupbox_style())
        preview_layout = QVBoxLayout(preview_group)
        
        preview_grid = QGridLayout()
        preview_grid.addWidget(QLabel("Raw Value:"), 0, 0)
        self.preview_raw_label = QLabel("--")
        self.preview_raw_label.setStyleSheet("color: #FFC107; font-size: 14px;")
        preview_grid.addWidget(self.preview_raw_label, 0, 1)
        
        preview_grid.addWidget(QLabel("→"), 0, 2)
        
        preview_grid.addWidget(QLabel("Calibrated:"), 0, 3)
        self.preview_cal_label = QLabel("--")
        self.preview_cal_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 14px;")
        preview_grid.addWidget(self.preview_cal_label, 0, 4)
        
        preview_layout.addLayout(preview_grid)
        
        self.preview_checkbox = QPushButton("👁️ Enable Live Preview")
        self.preview_checkbox.setCheckable(True)
        self.preview_checkbox.setStyleSheet("""
            QPushButton {
                background-color: #333;
                color: #aaa;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 5px;
            }
            QPushButton:checked {
                background-color: #1565C0;
                color: white;
                border-color: #1976D2;
            }
        """)
        self.preview_checkbox.clicked.connect(self._toggle_live_preview)
        preview_layout.addWidget(self.preview_checkbox)
        
        right_layout.addWidget(preview_group)
        
        # Export/Import
        io_group = QGroupBox("💾 Save / Load")
        io_group.setStyleSheet(self._groupbox_style())
        io_layout = QHBoxLayout(io_group)
        
        self.export_btn = QPushButton("📤 Export")
        self.export_btn.setStyleSheet(self._button_style("#00796B"))
        self.export_btn.clicked.connect(self._export_calibration)
        io_layout.addWidget(self.export_btn)
        
        self.import_btn = QPushButton("📥 Import")
        self.import_btn.setStyleSheet(self._button_style("#5D4037"))
        self.import_btn.clicked.connect(self._import_calibration)
        io_layout.addWidget(self.import_btn)
        
        right_layout.addWidget(io_group)
        
        right_layout.addStretch()
        splitter.addWidget(right_panel)
        
        # Set splitter sizes
        splitter.setSizes([500, 400])
        main_layout.addWidget(splitter)
    
    def _groupbox_style(self):
        """Return groupbox style - uses centralized theme system"""
        return GroupBoxStyles.compact()
    
    def _button_style(self, color):
        """Return button style with given color"""
        return f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {self._lighten_color(color)};
            }}
            QPushButton:disabled {{
                background-color: #555;
                color: #888;
            }}
        """
    
    def _lighten_color(self, hex_color):
        """Lighten a hex color"""
        # Simple lightening - just make it slightly brighter
        if hex_color.startswith('#'):
            hex_color = hex_color[1:]
        
        # Handle shorthand hex colors (e.g., #666 -> #666666)
        if len(hex_color) == 3:
            hex_color = hex_color[0] * 2 + hex_color[1] * 2 + hex_color[2] * 2
        
        r = min(255, int(hex_color[0:2], 16) + 20)
        g = min(255, int(hex_color[2:4], 16) + 20)
        b = min(255, int(hex_color[4:6], 16) + 20)
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def _populate_sensor_combo(self):
        """Populate sensor dropdown"""
        self.sensor_combo.clear()
        self.sensor_combo.addItem("-- Select Sensor --", None)
        
        if self.sensor_controller and hasattr(self.sensor_controller, 'sensors'):
            for sensor in self.sensor_controller.sensors:
                display_name = f"{sensor.name} ({sensor.interface_type})"
                sensor_key = f"{sensor.interface_type}_{sensor.name}"
                self.sensor_combo.addItem(display_name, sensor_key)
    
    def _on_sensor_changed(self):
        """Handle sensor selection change"""
        self.current_sensor_key = self.sensor_combo.currentData()
        self._clear_all_points()
        self.calibration_result = None
        self._update_results_display()
        
        if self.current_sensor_key:
            self.live_timer.start()
        else:
            self.live_timer.stop()
            self.live_reading_label.setText("--")
    
    def _update_live_reading(self):
        """Update live reading from sensor with robust error handling"""
        if not self.current_sensor_key or not self.sensor_controller:
            return
        
        try:
            # Get current sensor value
            value = self._get_current_sensor_value()
            if value is not None:
                self.live_reading_label.setText(f"{value:.4f}")
                self.preview_raw_label.setText(f"{value:.4f}")
                
                # Update calibrated preview if we have a calibration
                if self.calibration_result and self.preview_checkbox.isChecked():
                    calibrated = self._apply_calibration_to_value(value)
                    self.preview_cal_label.setText(f"{calibrated:.4f}")
        except Exception as e:
            print(f"Error in SensorCalibrationTool._update_live_reading: {e}")

    def _get_current_sensor_value(self):
        """Get current value from selected sensor with robust error handling"""
        if not self.sensor_controller:
            return None
        
        try:
            # Use list() to avoid RuntimeError if sensors changed during iteration
            sensors_snapshot = list(self.sensor_controller.sensors)
            for sensor in sensors_snapshot:
                try:
                    sensor_key = f"{getattr(sensor, 'interface_type', 'Unknown')}_{getattr(sensor, 'name', 'Unknown')}"
                    if sensor_key == self.current_sensor_key:
                        return getattr(sensor, 'current_value', None)
                except (AttributeError, RuntimeError):
                    continue
        except RuntimeError:
            pass
            
        return None
    
    def _capture_current_value(self):
        """Capture current sensor value to measured field"""
        value = self._get_current_sensor_value()
        if value is not None:
            self.measured_spin.setValue(value)
    
    def _add_calibration_point(self):
        """Add a calibration point from input fields"""
        measured = self.measured_spin.value()
        actual = self.actual_spin.value()
        self._add_point(measured, actual)
    
    def _add_point(self, measured: float, actual: float):
        """Add a calibration point"""
        point = CalibrationPoint(measured, actual)
        self.calibration_points.append(point)
        self._update_points_table()
        self._update_curve_plot()
    
    def _update_points_table(self):
        """Update the calibration points table"""
        self.points_table.setRowCount(len(self.calibration_points))
        
        for row, point in enumerate(self.calibration_points):
            # Measured value
            self.points_table.setItem(row, 0, QTableWidgetItem(f"{point.measured:.4f}"))
            
            # Actual value
            self.points_table.setItem(row, 1, QTableWidgetItem(f"{point.actual:.4f}"))
            
            # Error (difference)
            error = point.actual - point.measured
            error_item = QTableWidgetItem(f"{error:+.4f}")
            if abs(error) < 0.01:
                error_item.setForeground(QColor("#4CAF50"))
            elif abs(error) < 0.1:
                error_item.setForeground(QColor("#FFC107"))
            else:
                error_item.setForeground(QColor("#F44336"))
            self.points_table.setItem(row, 2, error_item)
            
            # Delete button
            delete_btn = QPushButton("🗑️")
            delete_btn.setStyleSheet("background: transparent; border: none;")
            delete_btn.clicked.connect(lambda checked, r=row: self._delete_point(r))
            self.points_table.setCellWidget(row, 3, delete_btn)
    
    def _delete_point(self, row: int):
        """Delete a calibration point"""
        if 0 <= row < len(self.calibration_points):
            self.calibration_points.pop(row)
            self._update_points_table()
            self._update_curve_plot()
    
    def _clear_all_points(self):
        """Clear all calibration points"""
        self.calibration_points.clear()
        self._update_points_table()
        self._update_curve_plot()
    
    def _update_curve_plot(self):
        """Update the calibration curve plot"""
        self.curve_plot.clear()
        
        if not self.calibration_points:
            return
        
        # Plot calibration points
        measured = [p.measured for p in self.calibration_points]
        actual = [p.actual for p in self.calibration_points]
        
        self.curve_plot.plot(
            measured, actual,
            pen=None,
            symbol='o',
            symbolSize=10,
            symbolBrush='#FFC107',
            symbolPen='#FFC107'
        )
        
        # Plot calibration curve if calculated
        if self.calibration_result:
            x_range = np.linspace(min(measured) - 0.1 * abs(min(measured)),
                                  max(measured) + 0.1 * abs(max(measured)), 100)
            y_values = [self._apply_calibration_to_value(x) for x in x_range]
            self.curve_plot.plot(x_range, y_values, pen=pg.mkPen('#4CAF50', width=2))
        
        # Plot ideal line (y = x) for reference
        if measured:
            x_ideal = [min(measured), max(measured)]
            self.curve_plot.plot(x_ideal, x_ideal, 
                               pen=pg.mkPen('#888', width=1, style=Qt.PenStyle.DashLine))
    
    def _calculate_calibration(self):
        """Calculate calibration based on points and method"""
        method_id = self.method_button_group.checkedId()
        
        if method_id == 2:  # Manual offset/gain
            self._calculate_manual()
        elif len(self.calibration_points) < 2:
            QMessageBox.warning(self, "Insufficient Points",
                              "Please add at least 2 calibration points for regression.")
            self.calibration_result = None
            self.apply_btn.setEnabled(False)
            self._update_results_display()
            return
        elif method_id == 0:  # Linear
            self._calculate_linear()
        elif method_id == 1:  # Polynomial
            self._calculate_polynomial()
        
        self._update_results_display()
        self._update_curve_plot()
        self.apply_btn.setEnabled(self.calibration_result is not None)
    
    def _calculate_linear(self):
        """Calculate linear calibration (y = mx + b)"""
        measured = np.array([p.measured for p in self.calibration_points])
        actual = np.array([p.actual for p in self.calibration_points])
        
        # Linear regression
        coeffs = np.polyfit(measured, actual, 1)
        
        self.calibration_result = CalibrationResult()
        self.calibration_result.method = "linear"
        self.calibration_result.coefficients = coeffs.tolist()
        self.calibration_result.gain = coeffs[0]
        self.calibration_result.offset = coeffs[1]
        self.calibration_result.points_count = len(self.calibration_points)
        
        # Calculate R² and RMSE
        predicted = np.polyval(coeffs, measured)
        ss_res = np.sum((actual - predicted) ** 2)
        ss_tot = np.sum((actual - np.mean(actual)) ** 2)
        self.calibration_result.r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        self.calibration_result.rmse = np.sqrt(np.mean((actual - predicted) ** 2))
    
    def _calculate_polynomial(self):
        """Calculate polynomial calibration"""
        measured = np.array([p.measured for p in self.calibration_points])
        actual = np.array([p.actual for p in self.calibration_points])
        degree = self.poly_degree_spin.value()
        
        if len(self.calibration_points) <= degree:
            QMessageBox.warning(self, "Insufficient Points",
                              f"Need at least {degree + 1} points for degree {degree} polynomial.")
            self.calibration_result = None
            self.apply_btn.setEnabled(False)
            self._update_results_display()
            return
        
        # Polynomial regression
        coeffs = np.polyfit(measured, actual, degree)
        
        self.calibration_result = CalibrationResult()
        self.calibration_result.method = f"polynomial_deg{degree}"
        self.calibration_result.coefficients = coeffs.tolist()
        self.calibration_result.points_count = len(self.calibration_points)
        
        # For display purposes, show equivalent offset/gain for first two terms
        if len(coeffs) >= 2:
            self.calibration_result.gain = coeffs[-2]
            self.calibration_result.offset = coeffs[-1]
        
        # Calculate R² and RMSE
        predicted = np.polyval(coeffs, measured)
        ss_res = np.sum((actual - predicted) ** 2)
        ss_tot = np.sum((actual - np.mean(actual)) ** 2)
        self.calibration_result.r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        self.calibration_result.rmse = np.sqrt(np.mean((actual - predicted) ** 2))
    
    def _calculate_manual(self):
        """Use manual offset and gain values"""
        self.calibration_result = CalibrationResult()
        self.calibration_result.method = "offset_gain"
        self.calibration_result.offset = self.manual_offset_spin.value()
        self.calibration_result.gain = self.manual_gain_spin.value()
        self.calibration_result.coefficients = [self.calibration_result.gain, self.calibration_result.offset]
        self.calibration_result.r_squared = 1.0  # Manual, so "perfect" fit by definition
        self.calibration_result.rmse = 0.0
        self.calibration_result.points_count = 0
    
    def _apply_calibration_to_value(self, value: float) -> float:
        """Apply calibration to a single value"""
        if not self.calibration_result:
            return value
        
        if self.calibration_result.method == "offset_gain":
            return value * self.calibration_result.gain + self.calibration_result.offset
        else:
            return np.polyval(self.calibration_result.coefficients, value)
    
    def _update_results_display(self):
        """Update the results display"""
        if not self.calibration_result:
            for key in self.result_labels:
                self.result_labels[key].setText("--")
            return
        
        result = self.calibration_result
        
        self.result_labels["method"].setText(result.method.replace("_", " ").title())
        self.result_labels["offset"].setText(f"{result.offset:.6f}")
        self.result_labels["gain"].setText(f"{result.gain:.6f}")
        
        # R² with color coding
        r2_text = f"{result.r_squared:.6f}"
        if result.r_squared >= 0.99:
            self.result_labels["r_squared"].setStyleSheet("color: #4CAF50; font-weight: bold;")
        elif result.r_squared >= 0.95:
            self.result_labels["r_squared"].setStyleSheet("color: #8BC34A; font-weight: bold;")
        elif result.r_squared >= 0.9:
            self.result_labels["r_squared"].setStyleSheet("color: #FFC107; font-weight: bold;")
        else:
            self.result_labels["r_squared"].setStyleSheet("color: #F44336; font-weight: bold;")
        self.result_labels["r_squared"].setText(r2_text)
        
        self.result_labels["rmse"].setText(f"{result.rmse:.6f}")
        
        # Build equation string
        if result.method == "linear":
            eq = f"y = {result.gain:.4f}x + {result.offset:.4f}"
        elif result.method == "offset_gain":
            eq = f"y = {result.gain:.4f}x + {result.offset:.4f}"
        elif "polynomial" in result.method:
            terms = []
            degree = len(result.coefficients) - 1
            for i, c in enumerate(result.coefficients):
                power = degree - i
                if power == 0:
                    terms.append(f"{c:.4f}")
                elif power == 1:
                    terms.append(f"{c:.4f}x")
                else:
                    terms.append(f"{c:.4f}x^{power}")
            eq = " + ".join(terms)
        else:
            eq = "--"
        self.result_labels["equation"].setText(eq)
    
    def _toggle_live_preview(self):
        """Toggle live preview mode"""
        if self.preview_checkbox.isChecked():
            self.preview_checkbox.setText("👁️ Live Preview Active")
        else:
            self.preview_checkbox.setText("👁️ Enable Live Preview")
            self.preview_cal_label.setText("--")
    
    def _apply_calibration(self):
        """Apply calibration to the selected sensor"""
        if not self.calibration_result or not self.current_sensor_key:
            return
        
        # Prepare calibration data
        cal_data = {
            'method': self.calibration_result.method,
            'coefficients': self.calibration_result.coefficients,
            'offset': self.calibration_result.offset,
            'gain': self.calibration_result.gain,
            'r_squared': self.calibration_result.r_squared,
            'rmse': self.calibration_result.rmse,
            'created_at': self.calibration_result.created_at,
            'points': [{'measured': p.measured, 'actual': p.actual} for p in self.calibration_points]
        }
        
        # Find and update sensor
        if self.sensor_controller:
            for sensor in self.sensor_controller.sensors:
                sensor_key = f"{sensor.interface_type}_{sensor.name}"
                if sensor_key == self.current_sensor_key:
                    # Store the full calibration data on the sensor
                    sensor.calibration_data = cal_data
                    
                    # Also update offset for backwards compatibility
                    sensor.offset = self.calibration_result.offset
                    
                    # Save the sensor configuration
                    self.sensor_controller.save_sensors()
                    self.sensor_controller.update_sensor_table()
                    break
        
        self.calibration_applied.emit(self.current_sensor_key, cal_data)
        
        QMessageBox.information(self, "Calibration Applied",
                               f"Calibration has been applied to the sensor.\n\n"
                               f"Method: {self.calibration_result.method}\n"
                               f"Offset: {self.calibration_result.offset:.6f}\n"
                               f"Gain: {self.calibration_result.gain:.6f}\n"
                               f"R²: {self.calibration_result.r_squared:.6f}\n\n"
                               f"Calibration saved and will persist across sessions.")
    
    def _reset_calibration(self):
        """Reset calibration for the selected sensor"""
        if not self.current_sensor_key:
            QMessageBox.warning(self, "No Sensor Selected",
                              "Please select a sensor first.")
            return
        
        # Confirm reset
        reply = QMessageBox.question(
            self, "Reset Calibration",
            f"Are you sure you want to reset the calibration for this sensor?\n\n"
            f"This will:\n"
            f"• Remove all calibration data\n"
            f"• Set offset to 0\n"
            f"• Set gain/conversion factor to 1\n\n"
            f"Raw sensor values will be displayed without any correction.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Find and reset the sensor
        if self.sensor_controller:
            for sensor in self.sensor_controller.sensors:
                sensor_key = f"{sensor.interface_type}_{sensor.name}"
                if sensor_key == self.current_sensor_key:
                    # Reset calibration using the model method
                    sensor.reset_calibration()
                    
                    # Save the sensor configuration
                    self.sensor_controller.save_sensors()
                    self.sensor_controller.update_sensor_table()
                    
                    QMessageBox.information(self, "Calibration Reset",
                                          f"Calibration has been reset for sensor:\n{sensor.name}\n\n"
                                          f"The sensor will now display raw values.")
                    break
        
        # Clear local calibration state
        self._clear_all_points()
        self.calibration_result = None
        self._update_results_display()
        self.apply_btn.setEnabled(False)
    
    def _export_calibration(self):
        """Export calibration to file"""
        if not self.calibration_result and not self.calibration_points:
            QMessageBox.warning(self, "Nothing to Export",
                              "Please add calibration points or calculate calibration first.")
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Calibration",
            f"calibration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON Files (*.json);;CSV Files (*.csv)"
        )
        
        if not filename:
            return
        
        try:
            data = {
                'sensor_key': self.current_sensor_key,
                'created_at': datetime.now().isoformat(),
                'points': [{'measured': p.measured, 'actual': p.actual, 'timestamp': p.timestamp}
                          for p in self.calibration_points],
                'result': {
                    'method': self.calibration_result.method if self.calibration_result else None,
                    'coefficients': self.calibration_result.coefficients if self.calibration_result else [],
                    'offset': self.calibration_result.offset if self.calibration_result else 0,
                    'gain': self.calibration_result.gain if self.calibration_result else 1,
                    'r_squared': self.calibration_result.r_squared if self.calibration_result else 0,
                    'rmse': self.calibration_result.rmse if self.calibration_result else 0,
                }
            }
            
            if filename.endswith('.json'):
                with open(filename, 'w') as f:
                    json.dump(data, f, indent=2)
            else:  # CSV
                with open(filename, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Calibration Export'])
                    writer.writerow(['Sensor', self.current_sensor_key])
                    writer.writerow(['Method', data['result']['method']])
                    writer.writerow(['Offset', data['result']['offset']])
                    writer.writerow(['Gain', data['result']['gain']])
                    writer.writerow(['R²', data['result']['r_squared']])
                    writer.writerow([])
                    writer.writerow(['Measured', 'Actual'])
                    for p in data['points']:
                        writer.writerow([p['measured'], p['actual']])
            
            QMessageBox.information(self, "Export Complete", f"Calibration exported to:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export: {e}")
    
    def _import_calibration(self):
        """Import calibration from file"""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import Calibration",
            "",
            "JSON Files (*.json);;CSV Files (*.csv)"
        )
        
        if not filename:
            return
        
        try:
            if filename.endswith('.json'):
                with open(filename, 'r') as f:
                    data = json.load(f)
                
                # Load points
                self.calibration_points.clear()
                for p in data.get('points', []):
                    self.calibration_points.append(CalibrationPoint(p['measured'], p['actual']))
                
                # Load result
                result_data = data.get('result', {})
                if result_data.get('method'):
                    self.calibration_result = CalibrationResult()
                    self.calibration_result.method = result_data['method']
                    self.calibration_result.coefficients = result_data.get('coefficients', [])
                    self.calibration_result.offset = result_data.get('offset', 0)
                    self.calibration_result.gain = result_data.get('gain', 1)
                    self.calibration_result.r_squared = result_data.get('r_squared', 0)
                    self.calibration_result.rmse = result_data.get('rmse', 0)
            
            else:  # CSV
                with open(filename, 'r') as f:
                    reader = csv.reader(f)
                    rows = list(reader)
                
                self.calibration_points.clear()
                in_data_section = False
                for row in rows:
                    if len(row) >= 2:
                        if row[0] == 'Measured' and row[1] == 'Actual':
                            in_data_section = True
                            continue
                        if in_data_section:
                            try:
                                measured = float(row[0])
                                actual = float(row[1])
                                self.calibration_points.append(CalibrationPoint(measured, actual))
                            except ValueError:
                                continue
            
            self._update_points_table()
            self._update_results_display()
            self._update_curve_plot()
            self.apply_btn.setEnabled(self.calibration_result is not None)
            
            QMessageBox.information(self, "Import Complete",
                                   f"Loaded {len(self.calibration_points)} calibration points.")
        
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import: {e}")
    
    def stop(self):
        """Stop live updates"""
        self.live_timer.stop()

