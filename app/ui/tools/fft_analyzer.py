"""
FFT Spectrum Analyzer Tool

Advanced FFT analysis with:
- Live real-time spectrum analysis
- Harmonics detection with THD calculation
- Spectrogram (waterfall) display
- Export of analysis results
- Live microphone input support
"""

import numpy as np
import time
import csv
import json
import threading
from datetime import datetime
from scipy.fft import fft, fftfreq

import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QCheckBox, QPushButton, QSpinBox,
    QGroupBox, QTableWidget, QTableWidgetItem, QSplitter,
    QFrame, QFileDialog, QHeaderView, QSizePolicy, QDoubleSpinBox,
    QSpacerItem
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot, QMetaObject, Q_ARG
from PyQt6.QtGui import QFont, QColor

from app.ui.theme import ButtonStyles, GraphStyles

# Try to import sounddevice for microphone support
try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False


class FFTAnalyzerTool(QWidget):
    """Advanced FFT Spectrum Analyzer Tool"""
    
    # Signals for thread-safe updates
    analysis_updated = pyqtSignal(dict)
    audio_devices_scanned = pyqtSignal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = None
        self.sensor_controller = None
        
        # Analysis state
        self.is_live = False
        self.current_sensor_key = None
        self.last_analysis_result = None
        self.last_raw_times = None
        self.last_raw_values = None
        self.spectrogram_min_db_spin = None
        self.spectrogram_max_db_spin = None
        self.spectrogram_normalize_checkbox = None
        self.spectrogram_autoscale_checkbox = None
        self.rpm_ppr_spin = None
        
        # Microphone state
        self.mic_stream = None
        self.mic_device_id = None
        self.mic_sample_rate = 44100
        self.mic_buffer = []
        self.mic_buffer_lock = threading.Lock()
        self.mic_buffer_size = 8192  # Keep last N samples
        self._mic_scan_generation = 0
        
        # Spectrogram data (time x frequency matrix)
        self.spectrogram_data = []
        self.spectrogram_times = []
        self.max_spectrogram_history = 100  # Number of FFT snapshots to keep
        
        # Live update timer
        self.live_timer = QTimer()
        self.live_timer.timeout.connect(self._live_update)
        self.live_update_interval = 200  # ms
        
        self._setup_ui()
        
        # Connect signals for thread-safe updates
        self.audio_devices_scanned.connect(self._do_update_mic_options)
        
    def set_main_window(self, main_window):
        """Set reference to main window for accessing sensor data"""
        self.main_window = main_window
        if hasattr(main_window, 'sensor_controller'):
            self.sensor_controller = main_window.sensor_controller
        self._populate_sensor_combo()
    
    def _setup_ui(self):
        """Setup the main UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # === Control Panel ===
        controls_frame = QFrame()
        controls_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        controls_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(40, 40, 40, 0.8);
                border: 1px solid #555;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        controls_layout = QGridLayout(controls_frame)
        controls_layout.setContentsMargins(4, 2, 4, 2)
        controls_layout.setHorizontalSpacing(14)
        controls_layout.setVerticalSpacing(6)
        
        # Sensor selection
        sensor_group = QVBoxLayout()
        sensor_label = QLabel("Sensor:")
        sensor_label.setStyleSheet("color: #aaa; font-size: 11px; border: none;")
        self.sensor_combo = QComboBox()
        self.sensor_combo.setMinimumWidth(160)
        self.sensor_combo.currentIndexChanged.connect(self._on_sensor_changed)
        sensor_group.addWidget(sensor_label)
        sensor_group.addWidget(self.sensor_combo)
        controls_layout.addLayout(sensor_group, 0, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        
        # FFT Size
        fft_group = QVBoxLayout()
        fft_label = QLabel("FFT Size:")
        fft_label.setStyleSheet("color: #aaa; font-size: 11px; border: none;")
        self.fft_size_combo = QComboBox()
        self.fft_size_combo.addItems(["128", "256", "512", "1024", "2048", "4096", "8192"])
        self.fft_size_combo.setCurrentText("1024")
        self.fft_size_combo.setFixedWidth(90)
        self.fft_size_combo.currentIndexChanged.connect(self._on_settings_changed)
        fft_group.addWidget(fft_label)
        fft_group.addWidget(self.fft_size_combo)
        controls_layout.addLayout(fft_group, 0, 1, alignment=Qt.AlignmentFlag.AlignVCenter)
        
        # Window Type
        window_group = QVBoxLayout()
        window_label = QLabel("Window:")
        window_label.setStyleSheet("color: #aaa; font-size: 11px; border: none;")
        self.window_combo = QComboBox()
        self.window_combo.addItems(["Hanning", "Hamming", "Blackman", "Rectangular", "Bartlett", "Kaiser"])
        self.window_combo.setMinimumWidth(130)
        self.window_combo.currentIndexChanged.connect(self._on_settings_changed)
        window_group.addWidget(window_label)
        window_group.addWidget(self.window_combo)
        controls_layout.addLayout(window_group, 0, 2, alignment=Qt.AlignmentFlag.AlignVCenter)
        
        # Display options
        display_group = QVBoxLayout()
        display_label = QLabel("Display:")
        display_label.setStyleSheet("color: #aaa; font-size: 11px; border: none;")
        display_group.addWidget(display_label)

        self.db_checkbox = QCheckBox("dB Scale")
        self.db_checkbox.setChecked(True)
        self.db_checkbox.setStyleSheet("color: #ccc; border: none;")
        self.db_checkbox.stateChanged.connect(self._on_settings_changed)
        display_group.addWidget(self.db_checkbox)
        
        self.log_freq_checkbox = QCheckBox("Log Freq")
        self.log_freq_checkbox.setStyleSheet("color: #ccc; border: none;")
        self.log_freq_checkbox.stateChanged.connect(self._on_settings_changed)
        display_group.addWidget(self.log_freq_checkbox)

        rpm_row = QHBoxLayout()
        rpm_row.setSpacing(6)
        rpm_label = QLabel("Pulses / Rev:")
        rpm_label.setStyleSheet("color: #aaa; font-size: 11px; border: none;")
        self.rpm_ppr_spin = QDoubleSpinBox()
        self.rpm_ppr_spin.setRange(0.1, 100.0)
        self.rpm_ppr_spin.setSingleStep(0.1)
        self.rpm_ppr_spin.setValue(1.0)
        self.rpm_ppr_spin.setDecimals(2)
        self.rpm_ppr_spin.setToolTip("Number of pulses/blades per revolution when estimating RPM from fundamental frequency.")
        self.rpm_ppr_spin.valueChanged.connect(self._on_settings_changed)
        rpm_row.addWidget(rpm_label)
        rpm_row.addWidget(self.rpm_ppr_spin)
        display_group.addLayout(rpm_row)

        display_group.addStretch()
        controls_layout.addLayout(display_group, 0, 3, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Spectrogram scale controls
        spectro_scale_layout = QVBoxLayout()
        spectro_scale_layout.setSpacing(4)
        spectro_label = QLabel("Spectrogram dB range:")
        spectro_label.setStyleSheet("color: #aaa; font-size: 11px; border: none;")

        range_row = QHBoxLayout()
        range_row.setSpacing(6)
        self.spectrogram_min_db_spin = QDoubleSpinBox()
        self.spectrogram_min_db_spin.setRange(-200.0, 0.0)
        self.spectrogram_min_db_spin.setValue(-60.0)
        self.spectrogram_min_db_spin.setDecimals(1)
        self.spectrogram_min_db_spin.setSuffix(" dB")
        self.spectrogram_min_db_spin.setToolTip("Lower limit for spectrogram color scale")
        self.spectrogram_min_db_spin.valueChanged.connect(self._on_settings_changed)

        self.spectrogram_max_db_spin = QDoubleSpinBox()
        self.spectrogram_max_db_spin.setRange(-120.0, 20.0)
        self.spectrogram_max_db_spin.setValue(0.0)
        self.spectrogram_max_db_spin.setDecimals(1)
        self.spectrogram_max_db_spin.setSuffix(" dB")
        self.spectrogram_max_db_spin.setToolTip("Upper limit for spectrogram color scale")
        self.spectrogram_max_db_spin.valueChanged.connect(self._on_settings_changed)

        range_row.addWidget(self.spectrogram_min_db_spin)
        range_row.addWidget(self.spectrogram_max_db_spin)

        self.spectrogram_normalize_checkbox = QCheckBox("Normalize per frame")
        self.spectrogram_normalize_checkbox.setStyleSheet("color: #ccc; border: none;")
        self.spectrogram_normalize_checkbox.setToolTip("Re-center each frame so its loudest bin is 0 dB")
        self.spectrogram_normalize_checkbox.setChecked(True)
        self.spectrogram_normalize_checkbox.stateChanged.connect(self._on_settings_changed)

        self.spectrogram_autoscale_checkbox = QCheckBox("Auto-scale dB (frame)")
        self.spectrogram_autoscale_checkbox.setStyleSheet("color: #ccc; border: none;")
        self.spectrogram_autoscale_checkbox.setToolTip("Use 5th/95th percentile of each frame to set color scale")
        self.spectrogram_autoscale_checkbox.setChecked(True)
        self.spectrogram_autoscale_checkbox.stateChanged.connect(self._on_settings_changed)

        spectro_scale_layout.addWidget(spectro_label)
        spectro_scale_layout.addLayout(range_row)
        spectro_scale_layout.addWidget(self.spectrogram_normalize_checkbox)
        spectro_scale_layout.addWidget(self.spectrogram_autoscale_checkbox)
        controls_layout.addLayout(spectro_scale_layout, 0, 4, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Spacer to push actions to the right
        controls_layout.addItem(
            QSpacerItem(20, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum),
            0, 5
        )
        
        # Live mode toggle
        self.live_btn = QPushButton("▶ Start Live")
        self.live_btn.setCheckable(True)
        self.live_btn.setStyleSheet(ButtonStyles.toggle("medium"))
        self.live_btn.clicked.connect(self._toggle_live_mode)
        controls_layout.addWidget(self.live_btn, 0, 6, alignment=Qt.AlignmentFlag.AlignVCenter)
        
        # Single analysis button
        self.analyze_btn = QPushButton("📊 Analyze Now")
        self.analyze_btn.setStyleSheet(ButtonStyles.info("medium"))
        self.analyze_btn.clicked.connect(self._analyze_once)
        controls_layout.addWidget(self.analyze_btn, 0, 7, alignment=Qt.AlignmentFlag.AlignVCenter)

        controls_layout.setColumnStretch(4, 1)
        controls_layout.setColumnStretch(5, 2)
        
        main_layout.addWidget(controls_frame)
        
        # === Main Content (Splitter) ===
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Top section: Spectrum + Spectrogram
        plots_widget = QWidget()
        plots_layout = QHBoxLayout(plots_widget)
        plots_layout.setContentsMargins(0, 0, 0, 0)
        plots_layout.setSpacing(10)
        
        # Left: Spectrum Plot
        spectrum_container = QFrame()
        spectrum_container.setStyleSheet("QFrame { background-color: #1a1a2e; border-radius: 8px; }")
        spectrum_layout = QVBoxLayout(spectrum_container)
        spectrum_layout.setContentsMargins(5, 5, 5, 5)
        
        spectrum_title = QLabel("📊 Frequency Spectrum")
        spectrum_title.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 12px;")
        spectrum_layout.addWidget(spectrum_title)
        
        self.spectrum_plot = pg.PlotWidget()
        GraphStyles.apply_spectrum_theme(self.spectrum_plot)
        self.spectrum_plot.setLabel('bottom', 'Frequency', 'Hz')
        self.spectrum_plot.setLabel('left', 'Amplitude', 'dB')
        
        # Add crosshair for cursor
        self.vLine = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('#888', width=1, style=Qt.PenStyle.DashLine))
        self.hLine = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen('#888', width=1, style=Qt.PenStyle.DashLine))
        self.spectrum_plot.addItem(self.vLine, ignoreBounds=True)
        self.spectrum_plot.addItem(self.hLine, ignoreBounds=True)
        
        # Cursor info label
        self.cursor_label = QLabel("Cursor: -- Hz, -- dB")
        self.cursor_label.setStyleSheet("color: #888; font-size: 10px;")
        
        spectrum_layout.addWidget(self.spectrum_plot)
        spectrum_layout.addWidget(self.cursor_label)
        plots_layout.addWidget(spectrum_container, stretch=2)
        
        # Connect mouse move for crosshair
        self.spectrum_plot.scene().sigMouseMoved.connect(self._on_mouse_moved)
        
        # Right: Spectrogram (Waterfall)
        spectrogram_container = QFrame()
        spectrogram_container.setStyleSheet("QFrame { background-color: #1a1a2e; border-radius: 8px; }")
        spectrogram_layout = QVBoxLayout(spectrogram_container)
        spectrogram_layout.setContentsMargins(5, 5, 5, 5)
        
        spectrogram_header = QHBoxLayout()
        spectrogram_title = QLabel("🌊 Spectrogram (Waterfall)")
        spectrogram_title.setStyleSheet("color: #03A9F4; font-weight: bold; font-size: 12px;")
        spectrogram_header.addWidget(spectrogram_title)
        
        self.clear_spectrogram_btn = QPushButton("Clear")
        self.clear_spectrogram_btn.setStyleSheet(ButtonStyles.secondary("small"))
        self.clear_spectrogram_btn.clicked.connect(self._clear_spectrogram)
        spectrogram_header.addWidget(self.clear_spectrogram_btn)
        spectrogram_layout.addLayout(spectrogram_header)
        
        self.spectrogram_widget = pg.PlotWidget()
        GraphStyles.apply_spectrum_theme(self.spectrogram_widget)
        self.spectrogram_widget.setLabel('bottom', 'Time', 's')
        self.spectrogram_widget.setLabel('left', 'Frequency', 'Hz')
        
        # Create image item for spectrogram
        self.spectrogram_img = pg.ImageItem()
        self.spectrogram_widget.addItem(self.spectrogram_img)
        
        # Add colorbar
        self.colorbar = pg.ColorBarItem(
            values=(0, 1),
            colorMap=pg.colormap.get('viridis'),
            label='Amplitude (dB)'
        )
        self.colorbar.setImageItem(self.spectrogram_img)
        
        spectrogram_layout.addWidget(self.spectrogram_widget)
        plots_layout.addWidget(spectrogram_container, stretch=1)
        
        splitter.addWidget(plots_widget)
        
        # Bottom section: Harmonics Table + Info
        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(10)
        
        # Harmonics Table
        harmonics_frame = QFrame()
        harmonics_frame.setStyleSheet("QFrame { background-color: #1a1a2e; border-radius: 8px; }")
        harmonics_layout = QVBoxLayout(harmonics_frame)
        harmonics_layout.setContentsMargins(10, 10, 10, 10)
        
        harmonics_header = QHBoxLayout()
        harmonics_title = QLabel("🎵 Harmonics Analysis")
        harmonics_title.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 12px;")
        harmonics_header.addWidget(harmonics_title)
        harmonics_header.addStretch()
        
        # THD Display
        self.thd_label = QLabel("THD: -- %")
        self.thd_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 14px;")
        harmonics_header.addWidget(self.thd_label)
        harmonics_layout.addLayout(harmonics_header)
        
        self.harmonics_table = QTableWidget()
        self.harmonics_table.setColumnCount(6)
        self.harmonics_table.setHorizontalHeaderLabels([
            "Harmonic", "Frequency (Hz)", "Amplitude", "dB", "Phase (°)", "% of Fund."
        ])
        self.harmonics_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.harmonics_table.setStyleSheet("""
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
        self.harmonics_table.setMaximumHeight(200)
        harmonics_layout.addWidget(self.harmonics_table)
        bottom_layout.addWidget(harmonics_frame, stretch=2)
        
        # Info Panel
        info_frame = QFrame()
        info_frame.setStyleSheet("QFrame { background-color: #1a1a2e; border-radius: 8px; }")
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(10, 10, 10, 10)
        
        info_title = QLabel("📋 Analysis Info")
        info_title.setStyleSheet("color: #9C27B0; font-weight: bold; font-size: 12px;")
        info_layout.addWidget(info_title)
        
        # Info grid
        info_grid = QGridLayout()
        info_grid.setSpacing(5)
        
        self.info_labels = {}
        info_items = [
            ("sample_rate", "Sample Rate:"),
            ("fft_size", "FFT Size:"),
            ("freq_resolution", "Freq Resolution:"),
            ("fundamental", "Fundamental:"),
            ("rpm", "Estimated RPM:"),
            ("nyquist", "Nyquist Freq:"),
            ("data_points", "Data Points:"),
        ]
        
        for row, (key, label_text) in enumerate(info_items):
            label = QLabel(label_text)
            label.setStyleSheet("color: #888; font-size: 11px;")
            value = QLabel("--")
            value.setStyleSheet("color: #fff; font-size: 11px; font-weight: bold;")
            info_grid.addWidget(label, row, 0)
            info_grid.addWidget(value, row, 1)
            self.info_labels[key] = value
        
        info_layout.addLayout(info_grid)
        info_layout.addStretch()
        
        # Export buttons
        export_layout = QHBoxLayout()
        
        self.export_csv_btn = QPushButton("📄 Export CSV")
        self.export_csv_btn.setStyleSheet(ButtonStyles.success("small"))
        self.export_csv_btn.clicked.connect(self._export_csv)
        export_layout.addWidget(self.export_csv_btn)
        
        self.export_json_btn = QPushButton("📋 Export JSON")
        self.export_json_btn.setStyleSheet(ButtonStyles.secondary("small"))
        self.export_json_btn.clicked.connect(self._export_json)
        export_layout.addWidget(self.export_json_btn)
        
        info_layout.addLayout(export_layout)
        bottom_layout.addWidget(info_frame, stretch=1)
        
        splitter.addWidget(bottom_widget)
        splitter.setSizes([400, 200])
        
        main_layout.addWidget(splitter)
    
    def _populate_sensor_combo(self):
        """Populate sensor dropdown with available sensors in a background thread if audio scanning is needed."""
        self.sensor_combo.clear()
        self.sensor_combo.addItem("-- Select Sensor --", None)
        
        # Add basic sensors immediately
        self._add_basic_sensors()
        
        # Scan for microphone in background
        if SOUNDDEVICE_AVAILABLE:
            from threading import Thread

            self._mic_scan_generation += 1
            scan_generation = self._mic_scan_generation

            def scan_audio_task():
                try:
                    import sounddevice as sd
                    devices = sd.query_devices()
                    self.audio_devices_scanned.emit((scan_generation, list(devices)))
                except Exception as e:
                    print(f"Error listing audio devices: {e}")

            Thread(target=scan_audio_task, daemon=True).start()

    def _add_basic_sensors(self):
        """Add non-audio sensors to the combo box."""
        # Add separator-like item
        self.sensor_combo.addItem("── Sensors ──", None)
        
        if self.sensor_controller and hasattr(self.sensor_controller, 'sensors'):
            for sensor in self.sensor_controller.sensors:
                if not getattr(sensor, 'enabled', True) or not getattr(sensor, 'show_in_graph', True):
                    continue
                display_name = f"{sensor.name} ({sensor.interface_type})"
                sensor_key = self.sensor_controller.get_historical_buffer_key(sensor)
                self.sensor_combo.addItem(display_name, sensor_key)

    def _remove_mic_combo_entries(self):
        """Remove existing microphone entries before refreshing the device list."""
        idx = 0
        while idx < self.sensor_combo.count():
            data = self.sensor_combo.itemData(idx)
            if isinstance(data, str) and data.startswith("mic:"):
                self.sensor_combo.removeItem(idx)
            else:
                idx += 1

    @pyqtSlot(object)
    def _do_update_mic_options(self, payload):
        """Actual UI update for microphone options."""
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        scan_generation, devices = payload
        if scan_generation != self._mic_scan_generation:
            return

        self._remove_mic_combo_entries()

        # Find where to insert (before "── Sensors ──")
        insert_idx = 1
        self.sensor_combo.insertItem(insert_idx, "🎤 Live Microphone (Default)", "mic:default")
        insert_idx += 1
        
        for i, device in enumerate(devices):
            try:
                if device['max_input_channels'] > 0:
                    self.sensor_combo.insertItem(insert_idx, f"🎤 {device['name']}", f"mic:{i}")
                    insert_idx += 1
            except (KeyError, TypeError):
                continue
    
    def _on_sensor_changed(self):
        """Handle sensor selection change"""
        old_key = self.current_sensor_key
        self.current_sensor_key = self.sensor_combo.currentData()
        self.last_raw_times = None
        self.last_raw_values = None
        self.last_analysis_result = None
        
        # Stop microphone if switching away from it
        if old_key and old_key.startswith("mic:") and (not self.current_sensor_key or not self.current_sensor_key.startswith("mic:")):
            self._stop_microphone()
        
        # Start microphone if switching to it
        if self.current_sensor_key and self.current_sensor_key.startswith("mic:"):
            self._start_microphone()
        
        if self.is_live:
            self._clear_spectrogram()
    
    def _on_settings_changed(self):
        """Handle settings change"""
        if self.last_raw_times and self.last_raw_values:
            # Re-run analysis on the last captured data without grabbing new samples
            self._perform_analysis(use_cached_data=True)
    
    def _toggle_live_mode(self):
        """Toggle live analysis mode"""
        self.is_live = self.live_btn.isChecked()
        
        if self.is_live:
            self.live_btn.setText("⏹ Stop Live")
            self.analyze_btn.setEnabled(False)
            self._clear_spectrogram()
            self.live_timer.start(self.live_update_interval)
        else:
            self.live_btn.setText("▶ Start Live")
            self.analyze_btn.setEnabled(True)
            self.live_timer.stop()
    
    def _live_update(self):
        """Perform live analysis update"""
        if not self.current_sensor_key:
            return
        self._perform_analysis()
    
    def _analyze_once(self):
        """Perform single analysis"""
        if not self.current_sensor_key:
            return
        self._perform_analysis()
    
    def _perform_analysis(self, use_cached_data=False):
        """Perform FFT analysis on current sensor data"""
        if not self.main_window or not self.current_sensor_key:
            return
        
        if use_cached_data:
            if not self.last_raw_times or not self.last_raw_values:
                return
            times = list(self.last_raw_times)
            values = list(self.last_raw_values)
        else:
            # Get data from data collection controller
            data_controller = getattr(self.main_window, 'data_collection_controller', None)
            if not data_controller:
                return
            
            times, values = self._get_sensor_data()
            if times is None or values is None or len(values) < 8:
                self._update_info("data_points", f"{len(values) if values is not None else 0} (need 8+)")
                return
        
        # Get settings
        fft_size = int(self.fft_size_combo.currentText())
        window_type = self.window_combo.currentText()
        use_db = self.db_checkbox.isChecked()
        use_log_freq = self.log_freq_checkbox.isChecked()
        
        # Ensure we have enough data
        n = min(len(values), fft_size)
        if n < 8:
            return
        
        # Take last n samples
        values = np.array(values[-n:], dtype=float)
        times = np.array(times[-n:], dtype=float)
        self.last_raw_times = times.tolist()
        self.last_raw_values = values.tolist()
        
        # Calculate sample rate
        if len(times) < 2:
            return
        sample_spacing = np.mean(np.diff(times))
        if sample_spacing <= 0 or np.isnan(sample_spacing):
            return
        sample_rate = 1.0 / sample_spacing
        nyquist_freq = sample_rate / 2.0
        freq_resolution = sample_rate / n
        
        # Apply window function
        window = self._get_window(window_type, n)
        values_windowed = (values - np.mean(values)) * window
        
        # Perform FFT
        yf = fft(values_windowed)
        xf = fftfreq(n, sample_spacing)[:n//2]
        
        # Get amplitude and phase
        complex_spectrum = yf[:n//2]
        amplitude = 2.0/n * np.abs(complex_spectrum)
        phase = np.angle(complex_spectrum, deg=True)
        amplitude_db_values = 20 * np.log10(amplitude + 1e-10)
        
        # Convert to dB if selected
        if use_db:
            amplitude_plot = amplitude_db_values
            self.spectrum_plot.setLabel('left', 'Amplitude', 'dB')
        else:
            amplitude_plot = amplitude
            self.spectrum_plot.setLabel('left', 'Amplitude')
        
        # Prepare data for plotting (log scale cannot include 0 Hz)
        if use_log_freq:
            valid_mask = xf > 0
            if not np.any(valid_mask):
                return
            plot_freqs = xf[valid_mask]
            plot_amplitude = amplitude_plot[valid_mask]
        else:
            plot_freqs = xf
            plot_amplitude = amplitude_plot
        
        # Update spectrum plot
        self.spectrum_plot.clear()
        self.spectrum_plot.addItem(self.vLine)
        self.spectrum_plot.addItem(self.hLine)
        
        self.spectrum_plot.setLogMode(x=use_log_freq, y=False)
        
        self.spectrum_plot.plot(plot_freqs, plot_amplitude, pen=pg.mkPen('#4CAF50', width=2))
        
        # Detect peaks and harmonics
        harmonics_data = self._detect_harmonics(xf, amplitude, phase, nyquist_freq)
        
        # Calculate THD
        thd = self._calculate_thd(harmonics_data)
        rpm_value = None
        try:
            ppr = float(self.rpm_ppr_spin.value()) if self.rpm_ppr_spin else 1.0
        except Exception:
            ppr = 1.0
        if harmonics_data and ppr > 0:
            rpm_value = harmonics_data[0]['frequency'] * 60.0 / max(ppr, 0.001)
        
        # Update displays
        self._update_harmonics_table(harmonics_data)
        self._update_thd_display(thd)
        self._update_info_panel(sample_rate, n, freq_resolution, nyquist_freq, harmonics_data, len(values), rpm_value)
        
        # Mark peaks on spectrum
        self._mark_peaks_on_spectrum(harmonics_data, use_db)
        
        # Update spectrogram
        self._update_spectrogram(
            xf,
            amplitude_db_values,
            append=not use_cached_data
        )
        
        # Store result
        self.last_analysis_result = {
            'timestamp': datetime.now().isoformat(),
            'sensor': self.current_sensor_key,
            'sample_rate': sample_rate,
            'fft_size': n,
            'freq_resolution': freq_resolution,
            'frequencies': xf.tolist(),
            'amplitude': amplitude.tolist(),
            'amplitude_db': (20 * np.log10(amplitude + 1e-10)).tolist(),
            'phase': phase.tolist(),
            'harmonics': harmonics_data,
            'thd': thd,
            'rpm': rpm_value if rpm_value is not None else 0.0,
        }
        
        self.analysis_updated.emit(self.last_analysis_result)
    
    def _get_sensor_data(self):
        """Get sensor data from the data collection controller or microphone with robust error handling"""
        if not self.current_sensor_key:
            return None, None
        
        # Handle microphone input
        if self.current_sensor_key.startswith("mic:"):
            return self._get_microphone_data()
        
        if not self.main_window:
            return None, None
        
        try:
            data_controller = getattr(self.main_window, 'data_collection_controller', None)
            if not data_controller or not hasattr(data_controller, 'get_historical_data'):
                return None, None

            historical = data_controller.get_historical_data([self.current_sensor_key])
            if historical and self.current_sensor_key in historical:
                data = historical[self.current_sensor_key]
                times = data.get('time', [])
                values = data.get('value', [])
                if times and values:
                    return list(times), list(values)
        except Exception as e:
            print(f"Error in FFTAnalyzerTool._get_sensor_data: {e}")
        
        return None, None
    
    def _start_microphone(self):
        """Start capturing audio from microphone"""
        if not SOUNDDEVICE_AVAILABLE:
            return False
        
        # Stop existing stream
        self._stop_microphone()
        
        try:
            # Parse device ID from key
            device_str = self.current_sensor_key.replace("mic:", "")
            if device_str == "default":
                self.mic_device_id = None
            else:
                self.mic_device_id = int(device_str)
            
            # Create input stream
            with self.mic_buffer_lock:
                self.mic_buffer = []
            self.mic_stream = sd.InputStream(
                device=self.mic_device_id,
                channels=1,
                samplerate=self.mic_sample_rate,
                blocksize=1024,
                callback=self._mic_callback,
                dtype=np.float32
            )
            self.mic_stream.start()
            return True
            
        except Exception as e:
            print(f"Error starting microphone: {e}")
            return False
    
    def _stop_microphone(self):
        """Stop microphone capture"""
        if self.mic_stream:
            try:
                self.mic_stream.stop()
                self.mic_stream.close()
            except:
                pass
            self.mic_stream = None
        with self.mic_buffer_lock:
            self.mic_buffer = []
    
    def _mic_callback(self, indata, frames, time_info, status):
        """Callback for microphone audio data"""
        if status:
            print(f"Audio status: {status}")
        
        # Add samples to buffer
        samples = indata[:, 0].tolist()
        with self.mic_buffer_lock:
            self.mic_buffer.extend(samples)
            if len(self.mic_buffer) > self.mic_buffer_size:
                self.mic_buffer = self.mic_buffer[-self.mic_buffer_size:]
    
    def _get_microphone_data(self):
        """Get data from microphone buffer for FFT analysis"""
        with self.mic_buffer_lock:
            if not self.mic_buffer or len(self.mic_buffer) < 128:
                return None, None
            buffer_copy = list(self.mic_buffer)
        
        # Create time array based on sample rate
        n_samples = len(buffer_copy)
        sample_spacing = 1.0 / self.mic_sample_rate
        times = np.arange(n_samples) * sample_spacing
        values = np.array(buffer_copy)
        
        return times.tolist(), values.tolist()
    
    def _get_window(self, window_type, n):
        """Get window function"""
        if window_type == "Hanning":
            return np.hanning(n)
        elif window_type == "Hamming":
            return np.hamming(n)
        elif window_type == "Blackman":
            return np.blackman(n)
        elif window_type == "Bartlett":
            return np.bartlett(n)
        elif window_type == "Kaiser":
            return np.kaiser(n, 14)  # Beta=14 for good sidelobe suppression
        else:  # Rectangular
            return np.ones(n)
    
    def _detect_harmonics(self, frequencies, amplitudes, phases, nyquist_freq):
        """Detect fundamental frequency and its harmonics"""
        harmonics = []
        
        if len(frequencies) == 0 or len(amplitudes) == 0:
            return harmonics
        
        # Find fundamental (strongest peak above 0.5 Hz)
        valid_idx = np.where(frequencies > 0.5)[0]
        if len(valid_idx) == 0:
            return harmonics
        
        # Find peaks (local maxima)
        peaks = []
        for i in valid_idx:
            if i > 0 and i < len(amplitudes) - 1:
                if amplitudes[i] > amplitudes[i-1] and amplitudes[i] > amplitudes[i+1]:
                    if amplitudes[i] > np.max(amplitudes) * 0.02:  # Above 2% of max
                        peaks.append((frequencies[i], amplitudes[i], phases[i], i))
        
        if not peaks:
            return harmonics
        
        # Sort by amplitude
        peaks.sort(key=lambda x: x[1], reverse=True)
        
        # Fundamental is the strongest
        fund_freq, fund_amp, fund_phase, fund_idx = peaks[0]
        
        # Add fundamental
        harmonics.append({
            'harmonic': 1,
            'name': 'Fundamental',
            'frequency': fund_freq,
            'amplitude': fund_amp,
            'amplitude_db': 20 * np.log10(fund_amp + 1e-10),
            'phase': fund_phase,
            'percent_of_fund': 100.0
        })
        
        # Find harmonics (2x, 3x, 4x, ...)
        for h in range(2, 16):  # Up to 15th harmonic
            target_freq = fund_freq * h
            if target_freq >= nyquist_freq:
                break
            
            # Find closest frequency bin
            closest_idx = np.argmin(np.abs(frequencies - target_freq))
            freq = frequencies[closest_idx]
            amp = amplitudes[closest_idx]
            ph = phases[closest_idx]
            
            # Check if it's actually close to the harmonic frequency (within 5%)
            if abs(freq - target_freq) / target_freq < 0.05:
                harmonics.append({
                    'harmonic': h,
                    'name': f'{h}x',
                    'frequency': freq,
                    'amplitude': amp,
                    'amplitude_db': 20 * np.log10(amp + 1e-10),
                    'phase': ph,
                    'percent_of_fund': (amp / fund_amp) * 100 if fund_amp > 0 else 0
                })
        
        return harmonics
    
    def _calculate_thd(self, harmonics_data):
        """Calculate Total Harmonic Distortion"""
        if len(harmonics_data) < 2:
            return 0.0
        
        fund_amp = harmonics_data[0]['amplitude']
        if fund_amp <= 0:
            return 0.0
        
        # Sum of squares of harmonic amplitudes (excluding fundamental)
        harmonic_power = sum(h['amplitude']**2 for h in harmonics_data[1:])
        
        # THD = sqrt(sum of harmonic powers) / fundamental
        thd = np.sqrt(harmonic_power) / fund_amp * 100
        
        return thd
    
    def _update_harmonics_table(self, harmonics_data):
        """Update the harmonics table"""
        self.harmonics_table.setRowCount(len(harmonics_data))
        
        for row, h in enumerate(harmonics_data):
            self.harmonics_table.setItem(row, 0, QTableWidgetItem(h['name']))
            self.harmonics_table.setItem(row, 1, QTableWidgetItem(f"{h['frequency']:.2f}"))
            self.harmonics_table.setItem(row, 2, QTableWidgetItem(f"{h['amplitude']:.6f}"))
            self.harmonics_table.setItem(row, 3, QTableWidgetItem(f"{h['amplitude_db']:.1f}"))
            self.harmonics_table.setItem(row, 4, QTableWidgetItem(f"{h['phase']:.1f}"))
            self.harmonics_table.setItem(row, 5, QTableWidgetItem(f"{h['percent_of_fund']:.1f}%"))
            
            # Color code based on harmonic number
            if row == 0:  # Fundamental
                color = QColor("#4CAF50")
            elif row < 3:
                color = QColor("#FFC107")
            else:
                color = QColor("#888888")
            
            for col in range(6):
                item = self.harmonics_table.item(row, col)
                if item:
                    item.setForeground(color)
    
    def _update_thd_display(self, thd):
        """Update THD display"""
        if thd < 1:
            color = "#4CAF50"  # Green - excellent
        elif thd < 5:
            color = "#8BC34A"  # Light green - good
        elif thd < 10:
            color = "#FFC107"  # Yellow - moderate
        else:
            color = "#F44336"  # Red - high distortion
        
        self.thd_label.setText(f"THD: {thd:.2f}%")
        self.thd_label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 14px;")
    
    def _update_info(self, key, value):
        """Update single info label"""
        if key in self.info_labels:
            self.info_labels[key].setText(str(value))
    
    def _update_info_panel(self, sample_rate, fft_size, freq_resolution, nyquist_freq, harmonics_data, data_points, rpm_value=None):
        """Update the info panel"""
        self._update_info("sample_rate", f"{sample_rate:.1f} Hz")
        self._update_info("fft_size", str(fft_size))
        self._update_info("freq_resolution", f"{freq_resolution:.3f} Hz")
        self._update_info("nyquist", f"{nyquist_freq:.1f} Hz")
        self._update_info("data_points", str(data_points))
        
        if harmonics_data:
            fund_freq = harmonics_data[0]['frequency']
            self._update_info("fundamental", f"{fund_freq:.2f} Hz")
        else:
            self._update_info("fundamental", "--")

        if rpm_value is not None:
            self._update_info("rpm", f"{rpm_value:.0f} RPM")
        else:
            self._update_info("rpm", "--")
    
    def _mark_peaks_on_spectrum(self, harmonics_data, use_db):
        """Mark detected peaks on the spectrum plot"""
        colors = ['#FF5722', '#FFC107', '#03A9F4', '#E91E63', '#9C27B0', 
                  '#00BCD4', '#CDDC39', '#FF9800', '#795548', '#607D8B']
        
        for i, h in enumerate(harmonics_data[:10]):  # Max 10 markers
            freq = h['frequency']
            amp = h['amplitude_db'] if use_db else h['amplitude']
            color = colors[i % len(colors)]
            
            # Vertical line
            line = pg.InfiniteLine(
                pos=freq,
                angle=90,
                pen=pg.mkPen(color=color, width=1, style=Qt.PenStyle.DashLine)
            )
            self.spectrum_plot.addItem(line)
            
            # Label
            label_text = f"{h['name']}\n{freq:.1f} Hz"
            text = pg.TextItem(label_text, color=color, anchor=(0.5, 1))
            text.setPos(freq, amp)
            self.spectrum_plot.addItem(text)
    
    def _update_spectrogram(self, frequencies, amplitude_db, append=True):
        """Update the spectrogram (waterfall) display"""
        current_time = time.time()

        # Optionally normalize each frame so loudest bin is 0 dB
        frame_db = amplitude_db
        if self.spectrogram_normalize_checkbox and self.spectrogram_normalize_checkbox.isChecked():
            max_val = np.max(amplitude_db) if len(amplitude_db) else 0
            frame_db = amplitude_db - max_val

        # Add or replace FFT snapshot depending on caller (store un-clipped frame)
        if append or not self.spectrogram_data:
            self.spectrogram_data.append(frame_db.copy())
            self.spectrogram_times.append(current_time)
        else:
            # Replace last entry to avoid growing history when only re-rendering
            self.spectrogram_data[-1] = frame_db.copy()
            if self.spectrogram_times:
                self.spectrogram_times[-1] = current_time
        
        # Limit history
        while len(self.spectrogram_data) > self.max_spectrogram_history:
            self.spectrogram_data.pop(0)
            self.spectrogram_times.pop(0)
        
        if len(self.spectrogram_data) < 1:
            return
        
        # Create 2D array for image
        try:
            spectrogram_array = np.array(self.spectrogram_data).T  # Transpose: freq x time

            # Determine dB range (auto uses all stored frames)
            vmin = -80.0
            vmax = 0.0
            use_autoscale = self.spectrogram_autoscale_checkbox and self.spectrogram_autoscale_checkbox.isChecked()
            if use_autoscale:
                flat_vals = spectrogram_array.flatten()
                finite_vals = flat_vals[np.isfinite(flat_vals)]
                if len(finite_vals) > 0:
                    p5 = np.percentile(finite_vals, 5)
                    p95 = np.percentile(finite_vals, 95)
                    vmin = float(p5)
                    vmax = float(p95)
            elif self.spectrogram_min_db_spin and self.spectrogram_max_db_spin:
                vmin = float(self.spectrogram_min_db_spin.value())
                vmax = float(self.spectrogram_max_db_spin.value())

            if vmax - vmin < 1.0:
                vmax = vmin + 1.0  # avoid zero span

            # Update image with proper orientation and levels
            self.spectrogram_img.setImage(
                spectrogram_array,
                autoLevels=False,
                levels=(vmin, vmax)
            )

            # Set correct scale
            time_range = self.spectrogram_times[-1] - self.spectrogram_times[0]
            freq_range = frequencies[-1] if len(frequencies) > 0 else 1

            # Set transform to map image to correct coordinates
            self.spectrogram_img.setRect(0, 0, len(self.spectrogram_data), len(frequencies))

            # Update axis labels
            self.spectrogram_widget.setLabel('bottom', f'Time (last {time_range:.1f}s)')

            # Update colorbar range to configured window
            self.colorbar.setLevels((vmin, vmax))

        except Exception as e:
            print(f"Spectrogram update error: {e}")
    
    def _clear_spectrogram(self):
        """Clear the spectrogram data"""
        self.spectrogram_data.clear()
        self.spectrogram_times.clear()
        self.spectrogram_img.clear()
    
    def _on_mouse_moved(self, pos):
        """Handle mouse movement for crosshair cursor"""
        if self.spectrum_plot.sceneBoundingRect().contains(pos):
            mouse_point = self.spectrum_plot.plotItem.vb.mapSceneToView(pos)
            self.vLine.setPos(mouse_point.x())
            self.hLine.setPos(mouse_point.y())
            
            unit = "dB" if self.db_checkbox.isChecked() else ""
            self.cursor_label.setText(f"Cursor: {mouse_point.x():.2f} Hz, {mouse_point.y():.2f} {unit}")
    
    def _export_csv(self):
        """Export analysis results to CSV"""
        if not self.last_analysis_result:
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export FFT Analysis", 
            f"fft_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV Files (*.csv)"
        )
        
        if not filename:
            return
        
        try:
            with open(filename, 'w', newline='') as f:
                writer = csv.writer(f)
                
                # Header info
                writer.writerow(["FFT Analysis Export"])
                writer.writerow(["Timestamp", self.last_analysis_result['timestamp']])
                writer.writerow(["Sensor", self.last_analysis_result['sensor']])
                writer.writerow(["Sample Rate (Hz)", self.last_analysis_result['sample_rate']])
                writer.writerow(["FFT Size", self.last_analysis_result['fft_size']])
                writer.writerow(["THD (%)", f"{self.last_analysis_result['thd']:.4f}"])
                writer.writerow([])
                
                # Harmonics
                writer.writerow(["=== HARMONICS ==="])
                writer.writerow(["Harmonic", "Frequency (Hz)", "Amplitude", "Amplitude (dB)", "Phase (°)", "% of Fundamental"])
                for h in self.last_analysis_result['harmonics']:
                    writer.writerow([
                        h['name'], h['frequency'], h['amplitude'], 
                        h['amplitude_db'], h['phase'], h['percent_of_fund']
                    ])
                writer.writerow([])
                
                # Full spectrum
                writer.writerow(["=== FULL SPECTRUM ==="])
                writer.writerow(["Frequency (Hz)", "Amplitude", "Amplitude (dB)", "Phase (°)"])
                freqs = self.last_analysis_result['frequencies']
                amps = self.last_analysis_result['amplitude']
                amps_db = self.last_analysis_result['amplitude_db']
                phases = self.last_analysis_result['phase']
                
                for i in range(len(freqs)):
                    writer.writerow([freqs[i], amps[i], amps_db[i], phases[i]])
                
            print(f"Exported to {filename}")
        except Exception as e:
            print(f"Export error: {e}")
    
    def _export_json(self):
        """Export analysis results to JSON"""
        if not self.last_analysis_result:
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export FFT Analysis", 
            f"fft_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON Files (*.json)"
        )
        
        if not filename:
            return
        
        try:
            with open(filename, 'w') as f:
                json.dump(self.last_analysis_result, f, indent=2)
            print(f"Exported to {filename}")
        except Exception as e:
            print(f"Export error: {e}")
    
    def stop(self):
        """Stop live analysis (call when closing)"""
        self.live_timer.stop()
        self.is_live = False
        self.live_btn.setChecked(False)
        self.live_btn.setText("▶ Start Live")
        self.analyze_btn.setEnabled(True)
        self._stop_microphone()

