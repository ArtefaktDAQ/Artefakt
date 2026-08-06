"""
Statistics Dashboard Tool

Live statistics dashboard with:
- Min/Max/Mean/Median/StdDev calculations
- Live histogram display
- Trend analysis (linear regression)
- Multi-sensor comparison
- Data distribution analysis
"""

import numpy as np
from datetime import datetime
from typing import Dict, List, Optional
from collections import deque

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QPushButton, QSpinBox,
    QGroupBox, QTableWidget, QTableWidgetItem, QSplitter,
    QFrame, QHeaderView, QCheckBox, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor

import pyqtgraph as pg

from app.ui.theme import ButtonStyles, CardStyles, GraphStyles


class StatCard(QFrame):
    """A styled card for displaying a single statistic"""
    
    def __init__(self, title: str, icon: str = "📊", parent=None):
        super().__init__(parent)
        self.title = title
        self.icon = icon
        
        self.setStyleSheet(CardStyles.stat_card())
        self.setMinimumSize(120, 80)
        self.setMaximumHeight(100)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        
        # Title
        title_label = QLabel(f"{icon} {title}")
        title_label.setStyleSheet("color: #888; font-size: 11px; border: none; background: transparent;")
        layout.addWidget(title_label)
        
        # Value
        self.value_label = QLabel("--")
        self.value_label.setStyleSheet("color: #fff; font-size: 18px; font-weight: bold; border: none; background: transparent;")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.value_label)
        
        # Sub-info (optional)
        self.sub_label = QLabel("")
        self.sub_label.setStyleSheet("color: #666; font-size: 9px; border: none; background: transparent;")
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.sub_label)
    
    def set_value(self, value: str, color: str = "#fff"):
        """Set the main value"""
        self.value_label.setText(value)
        self.value_label.setStyleSheet(f"color: {color}; font-size: 18px; font-weight: bold; border: none; background: transparent;")
    
    def set_sub_info(self, text: str):
        """Set sub-info text"""
        self.sub_label.setText(text)


class SensorStatsRow(QFrame):
    """A row displaying statistics for a single sensor"""
    
    def __init__(self, sensor_name: str, sensor_key: str, color: str = "#4CAF50", parent=None):
        super().__init__(parent)
        self.sensor_name = sensor_name
        self.sensor_key = sensor_key
        self.color = color
        self.data_buffer = deque(maxlen=10000000)  # Store last 10,000,000 values
        
        self.setStyleSheet(CardStyles.metric_card(color))
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(15)
        
        # Sensor name with color indicator
        name_layout = QVBoxLayout()
        self.name_label = QLabel(f"● {sensor_name}")
        self.name_label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px; border: none;")
        self.name_label.setMinimumWidth(150)
        name_layout.addWidget(self.name_label)
        
        self.count_label = QLabel("0 samples")
        self.count_label.setStyleSheet("color: #666; font-size: 10px; border: none;")
        name_layout.addWidget(self.count_label)
        layout.addLayout(name_layout)
        
        # Current value
        self.current_label = self._create_stat_label("Current", "--")
        layout.addWidget(self.current_label)
        
        # Min
        self.min_label = self._create_stat_label("Min", "--", "#03A9F4")
        layout.addWidget(self.min_label)
        
        # Max
        self.max_label = self._create_stat_label("Max", "--", "#F44336")
        layout.addWidget(self.max_label)
        
        # Mean
        self.mean_label = self._create_stat_label("Mean", "--", "#4CAF50")
        layout.addWidget(self.mean_label)
        
        # Median
        self.median_label = self._create_stat_label("Median", "--", "#9C27B0")
        layout.addWidget(self.median_label)
        
        # Std Dev
        self.std_label = self._create_stat_label("Std Dev", "--", "#FF9800")
        layout.addWidget(self.std_label)
        
        # Trend
        self.trend_label = self._create_stat_label("Trend", "--", "#888")
        layout.addWidget(self.trend_label)
        
        layout.addStretch()
    
    def _create_stat_label(self, title: str, value: str, color: str = "#fff") -> QFrame:
        """Create a stat label widget"""
        frame = QFrame()
        frame.setStyleSheet("border: none; background: transparent;")
        frame.setMinimumWidth(80)
        
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("color: #666; font-size: 9px; border: none;")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_lbl)
        
        value_lbl = QLabel(value)
        value_lbl.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold; border: none;")
        value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_lbl.setObjectName(f"{title.lower()}_value")
        layout.addWidget(value_lbl)
        
        return frame
    
    def add_value(self, value: float, timestamp: float = None):
        """Add a new value to the buffer"""
        if timestamp is None:
            timestamp = datetime.now().timestamp()
        self.data_buffer.append((timestamp, value))
    
    def update_stats(self):
        """Calculate and update all statistics"""
        if len(self.data_buffer) == 0:
            return
        
        values = np.array([v[1] for v in self.data_buffer])
        times = np.array([v[0] for v in self.data_buffer])
        
        # Current (last value)
        current = values[-1]
        self._set_value(self.current_label, f"{current:.3f}")
        
        # Min
        min_val = np.min(values)
        self._set_value(self.min_label, f"{min_val:.3f}")
        
        # Max
        max_val = np.max(values)
        self._set_value(self.max_label, f"{max_val:.3f}")
        
        # Mean
        mean_val = np.mean(values)
        self._set_value(self.mean_label, f"{mean_val:.3f}")
        
        # Median
        median_val = np.median(values)
        self._set_value(self.median_label, f"{median_val:.3f}")
        
        # Standard Deviation
        std_val = np.std(values)
        self._set_value(self.std_label, f"{std_val:.4f}")
        
        # Trend (linear regression slope)
        if len(values) >= 2:
            # Normalize time for numerical stability
            times_norm = times - times[0]
            if times_norm[-1] > 0:
                slope, _ = np.polyfit(times_norm, values, 1)
                if abs(slope) < 0.001:
                    trend_text = "→ Stable"
                    trend_color = "#4CAF50"
                elif slope > 0:
                    trend_text = f"↗ +{slope:.4f}/s"
                    trend_color = "#F44336"
                else:
                    trend_text = f"↘ {slope:.4f}/s"
                    trend_color = "#03A9F4"
                self._set_value(self.trend_label, trend_text, trend_color)
        
        # Update count
        self.count_label.setText(f"{len(values):,} samples")
    
    def _set_value(self, frame: QFrame, value: str, color: str = None):
        """Set value on a stat label frame"""
        value_label = frame.findChild(QLabel, frame.findChildren(QLabel)[1].objectName())
        if value_label:
            value_label.setText(value)
            if color:
                value_label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold; border: none;")
    
    def clear_data(self):
        """Clear all buffered data"""
        self.data_buffer.clear()
        self.count_label.setText("0 samples")
    
    def update_color(self, new_color: str):
        """Update the color of this sensor row"""
        self.color = new_color
        # Update the card background color
        self.setStyleSheet(CardStyles.metric_card(new_color))
        # Update the name label color
        self.name_label.setStyleSheet(f"color: {new_color}; font-weight: bold; font-size: 12px; border: none;")


class StatisticsDashboard(QWidget):
    """Live Statistics Dashboard Tool"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = None
        self.sensor_controller = None
        
        # Sensor stat rows
        self.sensor_rows: Dict[str, SensorStatsRow] = {}
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_stats)
        # Initial interval will be set based on sampling rate
        self.update_timer.setInterval(500)
        
        # Histogram data
        self.selected_sensor_key = None
        
        self._setup_ui()
    
    def set_main_window(self, main_window):
        """Set reference to main window"""
        self.main_window = main_window
        if hasattr(main_window, 'sensor_controller'):
            self.sensor_controller = main_window.sensor_controller
        # Update timer interval based on sampling rate
        self._update_timer_interval()
        self._populate_sensors()
    
    def _update_timer_interval(self):
        """Update timer interval based on current sampling rate"""
        try:
            # Get sampling rate from data collection controller
            sampling_rate_hz = 1.0  # Default to 1 Hz
            
            if self.main_window and hasattr(self.main_window, 'data_collection_controller'):
                if hasattr(self.main_window.data_collection_controller, 'sampling_rate'):
                    sampling_rate_hz = self.main_window.data_collection_controller.sampling_rate
            elif self.main_window and hasattr(self.main_window, 'sampling_rate_spinbox'):
                # Fallback: get from spinbox (already in Hz)
                sampling_rate_hz = self.main_window.sampling_rate_spinbox.value()
            
            # Convert Hz to milliseconds for timer interval
            # Ensure minimum interval of 50ms (max 20 Hz) to avoid UI overload
            interval_ms = max(int(1000 / sampling_rate_hz), 50)
            self.update_timer.setInterval(interval_ms)
            
        except Exception as e:
            print(f"Error updating dashboard timer interval: {e}")
            # Fallback to default 500ms if error occurs
            self.update_timer.setInterval(500)
    
    def _setup_ui(self):
        """Setup the main UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("📈 Live Statistics Dashboard")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #4CAF50;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Refresh sensors button
        self.refresh_btn = QPushButton("🔄 Refresh Sensors")
        self.refresh_btn.setStyleSheet(ButtonStyles.secondary("small"))
        self.refresh_btn.clicked.connect(self._populate_sensors)
        header_layout.addWidget(self.refresh_btn)
        
        # Clear all data button
        self.clear_btn = QPushButton("🗑️ Clear All Data")
        self.clear_btn.setStyleSheet(ButtonStyles.danger("small"))
        self.clear_btn.clicked.connect(self._clear_all_data)
        header_layout.addWidget(self.clear_btn)
        
        # Live toggle
        self.live_btn = QPushButton("▶ Start Live")
        self.live_btn.setCheckable(True)
        self.live_btn.setStyleSheet(ButtonStyles.toggle("small"))
        self.live_btn.clicked.connect(self._toggle_live)
        header_layout.addWidget(self.live_btn)
        
        main_layout.addLayout(header_layout)
        
        # Main splitter
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # === Top Section: Summary Cards ===
        summary_frame = QFrame()
        summary_frame.setStyleSheet("QFrame { background-color: #1a1a2e; border-radius: 8px; }")
        summary_layout = QVBoxLayout(summary_frame)
        summary_layout.setContentsMargins(10, 10, 10, 10)
        
        summary_title = QLabel("📊 Global Summary")
        summary_title.setStyleSheet("color: #888; font-weight: bold;")
        summary_layout.addWidget(summary_title)
        
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(10)
        
        self.total_sensors_card = StatCard("Active Sensors", "🔌")
        cards_layout.addWidget(self.total_sensors_card)
        
        self.total_samples_card = StatCard("Total Samples", "📝")
        cards_layout.addWidget(self.total_samples_card)
        
        self.update_rate_card = StatCard("Refresh Rate", "⚡")
        cards_layout.addWidget(self.update_rate_card)
        
        self.running_time_card = StatCard("Running Time", "⏱️")
        cards_layout.addWidget(self.running_time_card)
        
        self.global_min_card = StatCard("Global Min", "📉")
        cards_layout.addWidget(self.global_min_card)
        
        self.global_max_card = StatCard("Global Max", "📈")
        cards_layout.addWidget(self.global_max_card)
        
        cards_layout.addStretch()
        summary_layout.addLayout(cards_layout)
        
        splitter.addWidget(summary_frame)
        
        # === Middle Section: Per-Sensor Stats ===
        sensors_frame = QFrame()
        sensors_frame.setStyleSheet("QFrame { background-color: #1a1a2e; border-radius: 8px; }")
        sensors_layout = QVBoxLayout(sensors_frame)
        sensors_layout.setContentsMargins(10, 10, 10, 10)
        
        sensors_header = QHBoxLayout()
        sensors_title = QLabel("📋 Per-Sensor Statistics")
        sensors_title.setStyleSheet("color: #888; font-weight: bold;")
        sensors_header.addWidget(sensors_title)
        sensors_header.addStretch()
        sensors_layout.addLayout(sensors_header)
        
        # Scrollable sensor list
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #2D2D2D;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background-color: #555;
                border-radius: 5px;
                min-height: 20px;
            }
        """)
        
        self.sensors_container = QWidget()
        self.sensors_list_layout = QVBoxLayout(self.sensors_container)
        self.sensors_list_layout.setContentsMargins(0, 0, 0, 0)
        self.sensors_list_layout.setSpacing(5)
        self.sensors_list_layout.addStretch()
        
        scroll_area.setWidget(self.sensors_container)
        sensors_layout.addWidget(scroll_area)
        
        splitter.addWidget(sensors_frame)
        
        # === Bottom Section: Histogram & Distribution ===
        bottom_frame = QFrame()
        bottom_frame.setStyleSheet("QFrame { background-color: #1a1a2e; border-radius: 8px; }")
        bottom_layout = QHBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(10, 10, 10, 10)
        bottom_layout.setSpacing(10)
        
        # Histogram
        hist_container = QVBoxLayout()
        hist_header = QHBoxLayout()
        hist_title = QLabel("📊 Value Distribution (Histogram)")
        hist_title.setStyleSheet("color: #888; font-weight: bold;")
        hist_header.addWidget(hist_title)
        
        hist_header.addWidget(QLabel("Sensor:"))
        self.hist_sensor_combo = QComboBox()
        self.hist_sensor_combo.setMinimumWidth(150)
        self.hist_sensor_combo.currentIndexChanged.connect(self._on_hist_sensor_changed)
        hist_header.addWidget(self.hist_sensor_combo)
        
        hist_header.addWidget(QLabel("Bins:"))
        self.hist_bins_spin = QSpinBox()
        self.hist_bins_spin.setRange(5, 100)
        self.hist_bins_spin.setValue(30)
        self.hist_bins_spin.valueChanged.connect(self._update_histogram)
        hist_header.addWidget(self.hist_bins_spin)
        
        hist_header.addStretch()
        hist_container.addLayout(hist_header)
        
        self.histogram_plot = pg.PlotWidget()
        GraphStyles.apply_histogram_theme(self.histogram_plot)
        self.histogram_plot.setLabel('bottom', 'Value')
        self.histogram_plot.setLabel('left', 'Count')
        hist_container.addWidget(self.histogram_plot)
        
        bottom_layout.addLayout(hist_container, stretch=2)
        
        # Distribution info
        dist_container = QVBoxLayout()
        dist_title = QLabel("📐 Distribution Info")
        dist_title.setStyleSheet("color: #888; font-weight: bold;")
        dist_container.addWidget(dist_title)
        
        self.dist_info_labels = {}
        dist_items = [
            ("range", "Range:"),
            ("iqr", "IQR (Q3-Q1):"),
            ("q1", "Q1 (25%):"),
            ("q3", "Q3 (75%):"),
            ("skewness", "Skewness:"),
            ("kurtosis", "Kurtosis:"),
            ("cv", "Coef. of Var.:"),
        ]
        
        dist_grid = QGridLayout()
        for row, (key, label_text) in enumerate(dist_items):
            label = QLabel(label_text)
            label.setStyleSheet("color: #888; font-size: 11px;")
            value = QLabel("--")
            value.setStyleSheet("color: #fff; font-weight: bold; font-size: 11px;")
            dist_grid.addWidget(label, row, 0)
            dist_grid.addWidget(value, row, 1)
            self.dist_info_labels[key] = value
        
        dist_container.addLayout(dist_grid)
        dist_container.addStretch()
        
        bottom_layout.addLayout(dist_container, stretch=1)
        
        splitter.addWidget(bottom_frame)
        
        # Set splitter proportions
        splitter.setSizes([100, 250, 200])
        main_layout.addWidget(splitter)
        
        # Track start time
        self.start_time = None
        self.last_update_time = None
        self.update_count = 0
        self.last_sensor_update_times = {}
    
    def _populate_sensors(self):
        """Populate sensor list and histogram combo"""
        # Clear existing rows
        for row in self.sensor_rows.values():
            row.setParent(None)
            row.deleteLater()
        self.sensor_rows.clear()
        
        # Clear histogram combo
        self.hist_sensor_combo.clear()
        self.hist_sensor_combo.addItem("-- Select Sensor --", None)
        
        if not self.sensor_controller or not hasattr(self.sensor_controller, 'sensors'):
            return
        
        # Fallback color palette for sensors without color
        fallback_colors = ['#4CAF50', '#2196F3', '#FF9800', '#E91E63', '#9C27B0',
                          '#00BCD4', '#CDDC39', '#FF5722', '#795548', '#607D8B']
        
        for i, sensor in enumerate(self.sensor_controller.sensors):
            if not getattr(sensor, 'show_in_graph', True) or not getattr(sensor, 'enabled', True):
                continue
                
            sensor_key = f"{sensor.interface_type}_{sensor.name}"
            
            # Use sensor color from sensor management table, fallback to palette if not set
            if hasattr(sensor, 'color') and sensor.color:
                # Validate color format (should be hex like #RRGGBB)
                try:
                    from PyQt6.QtGui import QColor
                    color_obj = QColor(sensor.color)
                    if color_obj.isValid():
                        color = sensor.color
                    else:
                        color = fallback_colors[i % len(fallback_colors)]
                except Exception:
                    color = fallback_colors[i % len(fallback_colors)]
            else:
                color = fallback_colors[i % len(fallback_colors)]
            
            # Create sensor row
            row = SensorStatsRow(sensor.name, sensor_key, color)
            self.sensor_rows[sensor_key] = row
            
            # Insert before the stretch
            self.sensors_list_layout.insertWidget(self.sensors_list_layout.count() - 1, row)
            
            # Add to histogram combo
            self.hist_sensor_combo.addItem(f"{sensor.name} ({sensor.interface_type})", sensor_key)
        
        # Update summary
        self.total_sensors_card.set_value(str(len(self.sensor_rows)))

        if self.hist_sensor_combo.count() > 1:
            self.hist_sensor_combo.setCurrentIndex(1)
            self._on_hist_sensor_changed()
    
    def update_sensor_color(self, sensor):
        """Update the color of a sensor row if it exists in the dashboard
        
        Args:
            sensor: The sensor object with updated color
        """
        if not self.sensor_controller:
            return
        
        # Generate the sensor key
        sensor_key = f"{getattr(sensor, 'interface_type', 'Unknown')}_{getattr(sensor, 'name', 'Unknown')}"
        
        # Check if this sensor has a row in the dashboard
        if sensor_key in self.sensor_rows:
            row = self.sensor_rows[sensor_key]
            
            # Get the new color from the sensor
            if hasattr(sensor, 'color') and sensor.color:
                try:
                    from PyQt6.QtGui import QColor
                    color_obj = QColor(sensor.color)
                    if color_obj.isValid():
                        new_color = sensor.color
                        # Update the row color
                        row.update_color(new_color)
                except Exception:
                    pass  # If color is invalid, skip update
    
    def _toggle_live(self):
        """Toggle live update mode"""
        if self.live_btn.isChecked():
            self.live_btn.setText("⏹ Stop Live")
            # Update timer interval based on current sampling rate before starting
            self._update_timer_interval()
            self.start_time = datetime.now()
            self.update_count = 0
            self.last_update_time = None  # Reset for rate calculation
            self.update_timer.start()
        else:
            self.live_btn.setText("▶ Start Live")
            self.update_timer.stop()
    
    def _update_stats(self):
        """Update statistics from sensor data with robust error handling"""
        if not self.sensor_controller:
            return
        
        try:
            # Periodically check if sampling rate has changed and update timer interval
            # Check every 10 updates to avoid overhead
            if self.update_count % 10 == 0:
                self._update_timer_interval()
            
            current_time = datetime.now()
            self.update_count += 1
            
            total_samples = 0
            global_min = float('inf')
            global_max = float('-inf')
            
            # Update each sensor row
            try:
                # Use list() to avoid RuntimeError if sensors changed during iteration
                sensors_snapshot = list(self.sensor_controller.sensors)
                for sensor in sensors_snapshot:
                    try:
                        sensor_key = f"{getattr(sensor, 'interface_type', 'Unknown')}_{getattr(sensor, 'name', 'Unknown')}"
                        
                        if sensor_key in self.sensor_rows:
                            row = self.sensor_rows[sensor_key]
                            
                            # Get current value
                            current_val = getattr(sensor, 'current_value', None)
                            if current_val is not None:
                                sensor_update_time = getattr(sensor, 'last_update_time', None)
                                last_seen_time = self.last_sensor_update_times.get(sensor_key)
                                last_buffered = row.data_buffer[-1][1] if row.data_buffer else None
                                value_changed = last_buffered is None or current_val != last_buffered
                                time_changed = sensor_update_time is not None and sensor_update_time != last_seen_time
                                if value_changed or time_changed:
                                    row.add_value(current_val)
                                    if sensor_update_time is not None:
                                        self.last_sensor_update_times[sensor_key] = sensor_update_time
                                row.update_stats()
                                
                                total_samples += len(row.data_buffer)
                                
                                if len(row.data_buffer) > 0:
                                    values = [v[1] for v in list(row.data_buffer)]
                                    if values:
                                        global_min = min(global_min, min(values))
                                        global_max = max(global_max, max(values))
                    except (AttributeError, RuntimeError, ValueError):
                        continue
            except RuntimeError:
                pass
            
            # Update summary cards
            self.total_samples_card.set_value(f"{total_samples:,}")
            
            # Update rate
            if self.last_update_time:
                elapsed = (current_time - self.last_update_time).total_seconds()
                if elapsed > 0:
                    rate = 1.0 / elapsed
                    self.update_rate_card.set_value(f"{rate:.1f} Hz")
            self.last_update_time = current_time
            
            # Running time
            if self.start_time:
                running = (current_time - self.start_time).total_seconds()
                hours = int(running // 3600)
                minutes = int((running % 3600) // 60)
                seconds = int(running % 60)
                self.running_time_card.set_value(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
            
            # Global min/max
            if global_min != float('inf'):
                self.global_min_card.set_value(f"{global_min:.3f}", "#03A9F4")
            if global_max != float('-inf'):
                self.global_max_card.set_value(f"{global_max:.3f}", "#F44336")
            
            # Update histogram
            self._update_histogram()
        except Exception as e:
            print(f"Error in StatisticsDashboard._update_stats: {e}")
    
    def _on_hist_sensor_changed(self):
        """Handle histogram sensor selection change"""
        self.selected_sensor_key = self.hist_sensor_combo.currentData()
        self._update_histogram()
    
    def _update_histogram(self):
        """Update the histogram plot"""
        self.histogram_plot.clear()
        
        if not self.selected_sensor_key or self.selected_sensor_key not in self.sensor_rows:
            return
        
        row = self.sensor_rows[self.selected_sensor_key]
        if len(row.data_buffer) < 2:
            return
        
        values = np.array([v[1] for v in row.data_buffer])
        bins = self.hist_bins_spin.value()
        
        # Calculate histogram
        hist, bin_edges = np.histogram(values, bins=bins)
        
        # Plot as bar graph - ensure bars start from y=0 baseline
        bar_width = (bin_edges[1] - bin_edges[0]) * 0.9
        bar_graph = pg.BarGraphItem(
            x=bin_edges[:-1] + bar_width/2,
            y=0,
            height=hist,
            width=bar_width,
            brush='#4CAF50',
            pen=pg.mkPen('#2E7D32', width=1)
        )
        self.histogram_plot.addItem(bar_graph)
        
        # Update distribution info
        self._update_distribution_info(values)
    
    def _update_distribution_info(self, values: np.ndarray):
        """Update distribution statistics"""
        if len(values) < 2:
            return
        
        # Range
        val_range = np.max(values) - np.min(values)
        self.dist_info_labels["range"].setText(f"{val_range:.4f}")
        
        # Quartiles
        q1 = np.percentile(values, 25)
        q3 = np.percentile(values, 75)
        iqr = q3 - q1
        self.dist_info_labels["q1"].setText(f"{q1:.4f}")
        self.dist_info_labels["q3"].setText(f"{q3:.4f}")
        self.dist_info_labels["iqr"].setText(f"{iqr:.4f}")
        
        # Coefficient of variation
        mean = np.mean(values)
        std = np.std(values)
        if mean != 0:
            cv = (std / abs(mean)) * 100
            self.dist_info_labels["cv"].setText(f"{cv:.2f}%")
        else:
            self.dist_info_labels["cv"].setText("--")
        
        # Skewness (using Fisher's definition)
        if std > 0:
            n = len(values)
            skewness = (n / ((n-1) * (n-2))) * np.sum(((values - mean) / std) ** 3) if n > 2 else 0
            self.dist_info_labels["skewness"].setText(f"{skewness:.4f}")
            
            # Kurtosis (excess kurtosis)
            if n > 3:
                kurtosis = ((n * (n + 1)) / ((n - 1) * (n - 2) * (n - 3))) * \
                           np.sum(((values - mean) / std) ** 4) - \
                           (3 * (n - 1) ** 2) / ((n - 2) * (n - 3))
                self.dist_info_labels["kurtosis"].setText(f"{kurtosis:.4f}")
        else:
            self.dist_info_labels["skewness"].setText("--")
            self.dist_info_labels["kurtosis"].setText("--")
    
    def _clear_all_data(self):
        """Clear all buffered data"""
        for row in self.sensor_rows.values():
            row.clear_data()
        
        self.total_samples_card.set_value("0")
        self.global_min_card.set_value("--")
        self.global_max_card.set_value("--")
        self.histogram_plot.clear()
        
        for label in self.dist_info_labels.values():
            label.setText("--")
    
    def stop(self):
        """Stop live updates"""
        self.update_timer.stop()

