"""
Tools Window

Main window for hosting analysis and diagnostic tools.
Accessible via status bar button or keyboard shortcut.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QLabel, QPushButton, QFrame, QSizePolicy, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeySequence, QShortcut

from .fft_analyzer import FFTAnalyzerTool
from .sensor_calibration import SensorCalibrationTool
from .statistics_dashboard import StatisticsDashboard
from .diagnostics_tool import DiagnosticsTool
from .calculator_tool import CalculatorTool
from .optical_sensor_tool import OpticalSensorTool
from .help_panel import HelpPanel, get_help_content


class ToolsWindow(QWidget):
    """Main Tools Window containing various analysis tools"""
    
    # Signal emitted when window is closed
    closed = pyqtSignal()
    
    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.help_visible = False
        
        self.setWindowTitle("🧰 Analysis Tools")
        self.setMinimumSize(1200, 800)
        self.setWindowFlags(Qt.WindowType.Window)  # Separate window
        
        self._setup_ui()
        self._setup_tools()
        self._setup_help_panel()
        
        # Apply dark theme
        self.setStyleSheet("""
            QWidget {
                background-color: #1a1a2e;
                color: #ffffff;
            }
            QTabWidget::pane {
                border: 1px solid #444;
                border-radius: 8px;
                background-color: #1a1a2e;
            }
            QTabBar::tab {
                background-color: #2d2d44;
                color: #aaa;
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background-color: #3d3d5c;
                color: #fff;
            }
            QTabBar::tab:hover {
                background-color: #3d3d5c;
            }
        """)
    
    def _setup_ui(self):
        """Setup the main UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Header
        header_frame = QFrame()
        header_frame.setFixedHeight(50)  # Match dashboard header height
        header_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2E1F5E, stop:1 #1a1a2e);
                border-radius: 8px;
                padding: 0px 10px;
            }
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(15, 0, 15, 0)
        
        title_label = QLabel("🧰 Analysis Tools")
        title_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #fff; background: transparent;")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        # Help text
        help_label = QLabel("Press Ctrl+Shift+T to toggle | On-demand analysis tools")
        help_label.setStyleSheet("color: #888; font-size: 11px; background: transparent;")
        header_layout.addWidget(help_label)
        
        # Help button
        self.help_btn = QPushButton("❓ Help")
        self.help_btn.setCheckable(True)
        self.help_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d3d6c;
                color: #A0A0D0;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #4d4d8c;
                color: #fff;
            }
            QPushButton:checked {
                background-color: #5d5dac;
                color: #fff;
            }
        """)
        self.help_btn.clicked.connect(self._toggle_help)
        header_layout.addWidget(self.help_btn)
        
        main_layout.addWidget(header_frame)
        
        # Main content area with splitter for help panel
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setHandleWidth(1)
        self.content_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #3a3a5c;
            }
        """)
        
        # Tab widget for tools
        self.tool_tabs = QTabWidget()
        self.tool_tabs.currentChanged.connect(self._on_tab_changed)
        self.content_splitter.addWidget(self.tool_tabs)
        
        main_layout.addWidget(self.content_splitter)
    
    def _setup_tools(self):
        """Setup individual tools"""
        # FFT Analyzer
        self.fft_analyzer = FFTAnalyzerTool()
        if self.main_window:
            self.fft_analyzer.set_main_window(self.main_window)
        self.tool_tabs.addTab(self.fft_analyzer, "📊 FFT Spectrum Analyzer")
        
        # Sensor Calibration
        self.sensor_calibration = SensorCalibrationTool()
        if self.main_window:
            self.sensor_calibration.set_main_window(self.main_window)
        self.tool_tabs.addTab(self.sensor_calibration, "🔧 Sensor Calibration")
        
        # Statistics Dashboard
        self.statistics_dashboard = StatisticsDashboard()
        if self.main_window:
            self.statistics_dashboard.set_main_window(self.main_window)
        self.tool_tabs.addTab(self.statistics_dashboard, "📈 Statistics")
        
        # Diagnostics Tool
        self.diagnostics_tool = DiagnosticsTool()
        if self.main_window:
            self.diagnostics_tool.set_main_window(self.main_window)
        self.tool_tabs.addTab(self.diagnostics_tool, "🔌 Diagnostics")
        
        # Calculator Tool
        self.calculator_tool = CalculatorTool()
        if self.main_window:
            self.calculator_tool.set_main_window(self.main_window)
        self.tool_tabs.addTab(self.calculator_tool, "📐 Calculator")

        # Optical Sensor / RPM Tester
        self.optical_sensor_tool = OpticalSensorTool()
        if self.main_window:
            self.optical_sensor_tool.set_main_window(self.main_window)
        self.tool_tabs.addTab(self.optical_sensor_tool, "🔁 Optical RPM Sensor")
    
    def _setup_help_panel(self):
        """Setup the help panel"""
        self.help_panel = HelpPanel("Help")
        self.help_panel.close_requested.connect(self._toggle_help)
        self.help_panel.setVisible(False)
        self.content_splitter.addWidget(self.help_panel)
        
        # Map tab indices to help content keys
        self.tab_help_map = {
            0: "fft",
            1: "calibration",
            2: "statistics",
            3: "diagnostics",
            4: "calculator",
            5: "optical_sensor",
        }
        
        # Load initial help content
        self._load_help_for_tab(0)
    
    def _toggle_help(self):
        """Toggle help panel visibility"""
        self.help_visible = not self.help_visible
        self.help_panel.setVisible(self.help_visible)
        self.help_btn.setChecked(self.help_visible)
        
        if self.help_visible:
            # Set splitter sizes
            total = self.width()
            self.content_splitter.setSizes([total - 350, 350])
            # Load help for current tab
            self._load_help_for_tab(self.tool_tabs.currentIndex())
    
    def _on_tab_changed(self, index: int):
        """Handle tab change"""
        # Refresh the newly selected tool
        self.refresh_sensors(force_all=False)
        
        if self.help_visible:
            self._load_help_for_tab(index)
    
    def _load_help_for_tab(self, index: int):
        """Load help content for the specified tab"""
        help_key = self.tab_help_map.get(index, "")
        help_content = get_help_content(help_key)
        
        # Clear and reload sections
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
            self.help_panel.sections[0].expand()
    
    def _add_placeholder_tab(self, title, description):
        """Add a placeholder tab for future tools"""
        placeholder = QWidget()
        layout = QVBoxLayout(placeholder)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        icon_label = QLabel(title.split()[0])  # Get emoji
        icon_label.setFont(QFont("Segoe UI Emoji", 48))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)
        
        title_label = QLabel(title.split(" ", 1)[1] if " " in title else title)
        title_label.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #666;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        desc_label = QLabel(description)
        desc_label.setStyleSheet("color: #888; font-size: 14px;")
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc_label)
        
        self.tool_tabs.addTab(placeholder, title)
    
    def set_main_window(self, main_window):
        """Set reference to main window"""
        self.main_window = main_window
        self.fft_analyzer.set_main_window(main_window)
        self.sensor_calibration.set_main_window(main_window)
        self.statistics_dashboard.set_main_window(main_window)
        self.diagnostics_tool.set_main_window(main_window)
        self.calculator_tool.set_main_window(main_window)
        self.optical_sensor_tool.set_main_window(main_window)
    
    def refresh_sensors(self, force_all=False):
        """Refresh sensor lists in tools. If force_all is False, only refreshes the current tab."""
        current_idx = self.tool_tabs.currentIndex()
        
        # FFT Analyzer (Index 0)
        if (force_all or current_idx == 0) and hasattr(self.fft_analyzer, '_populate_sensor_combo'):
            self.fft_analyzer._populate_sensor_combo()
            
        # Sensor Calibration (Index 1)
        if (force_all or current_idx == 1) and hasattr(self.sensor_calibration, '_populate_sensor_combo'):
            self.sensor_calibration._populate_sensor_combo()
            
        # Statistics Dashboard (Index 2)
        if (force_all or current_idx == 2) and hasattr(self.statistics_dashboard, '_populate_sensors'):
            self.statistics_dashboard._populate_sensors()
            
        # Diagnostics Tool (Index 3)
        if (force_all or current_idx == 3) and hasattr(self.diagnostics_tool, '_populate_devices'):
            self.diagnostics_tool._populate_devices()
            
        # Calculator Tool (Index 4) - No sensors to refresh
        
        # Optical Sensor (Index 5)
        if (force_all or current_idx == 5) and hasattr(self.optical_sensor_tool, '_populate_cameras'):
            self.optical_sensor_tool._populate_cameras()
    
    def show_with_help(self):
        """Show the window with help panel visible"""
        self.show()
        if not self.help_visible:
            self._toggle_help()
    
    def pause_tools(self):
        """Stop live timers, previews, and capture streams without destroying window state."""
        if hasattr(self.fft_analyzer, 'stop'):
            self.fft_analyzer.stop()
        if hasattr(self.sensor_calibration, 'stop'):
            self.sensor_calibration.stop()
        if hasattr(self.statistics_dashboard, 'stop'):
            self.statistics_dashboard.stop()
        if hasattr(self.diagnostics_tool, 'stop'):
            self.diagnostics_tool.stop()
        if hasattr(self.calculator_tool, 'stop'):
            self.calculator_tool.stop()
        if hasattr(self.optical_sensor_tool, 'stop'):
            self.optical_sensor_tool.stop()

    def hideEvent(self, event):
        """Pause active tools when the window is hidden."""
        self.pause_tools()
        super().hideEvent(event)

    def closeEvent(self, event):
        """Handle window close"""
        self.pause_tools()
        self.closed.emit()
        event.accept()
    
    def showEvent(self, event):
        """Handle window show"""
        # Refresh sensors when window is shown
        self.refresh_sensors()
        super().showEvent(event)
